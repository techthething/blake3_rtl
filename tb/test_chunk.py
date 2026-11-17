import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ClockCycles

from blake3 import ChunkState, Blake3, IV, KEYED_HASH, bytes_to_words32

def pack(words): # list of 32-bit words -> one integer
    value = 0
    for i, w in enumerate(words):
        value |= w << (32 * i)
    return value

def unpack(value, n): # one integer -> list of n 32-bit words
    return [(value >> (32 * i)) & 0xFFFFFFFF for i in range(n)]

async def start_and_reset(dut):
    Clock(dut.clk, 10, unit="ns").start() # start clock

    dut.rst_n.value = 0 # reset
    dut.blk_valid.value = 0 # no block yet

    await ClockCycles(dut.clk, 2) # wait until we can confidently reset

    dut.rst_n.value = 1

    await FallingEdge(dut.clk)

async def send_block(dut, block, block_len, last, root, chunk_index, msg_last=False):
    # present one block (zero-padded to 64 bytes) and hold it until it is accepted
    dut.blk_data.value = pack(bytes_to_words32(block + b"\x00" * (64 - block_len)))
    dut.blk_len.value = block_len
    dut.blk_last.value = last
    dut.blk_root.value = root
    dut.blk_msg_last.value = msg_last # last block of the whole message
    dut.chunk_index.value = chunk_index
    dut.blk_valid.value = 1

    cycles = 0
    while int(dut.blk_ready.value) != 1: # wait until the chunk controller can take it
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 50, "blk_ready never went high"

    await FallingEdge(dut.clk) # the rising edge in between accepted it
    dut.blk_valid.value = 0

async def run_chunk(dut, data, key, base_flags, chunk_index, root, msg_last=False):
    # send every block of one chunk, then wait for the chunk value
    # msg_last: this chunk ends the message (marked on its last block); cv_last must match
    dut.key.value = pack(key)
    dut.base_flags.value = base_flags

    blocks = [data[i:i + 64] for i in range(0, len(data), 64)] or [b""] # empty chunk = one 0-byte block

    for n, block in enumerate(blocks):
        last = (n == len(blocks) - 1)
        await send_block(dut, block, len(block), last, root and last, chunk_index, msg_last and last)

    cycles = 0
    while int(dut.cv_valid.value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 50, "cv_valid never went high"

    assert int(dut.cv_last.value) == msg_last, f"cv_last is {int(dut.cv_last.value)}, expected {int(msg_last)}"

    return unpack(int(dut.cv_out.value), 8)

@cocotb.test()
async def test_lengths(dut):
    # Chunks of hand-picked lengths that hit every block boundary: empty, one
    # byte, one block exactly, just over one block, and a full 16-block chunk.
    # Each length is run as a root and a non-root chunk, in plain and keyed mode.
    await start_and_reset(dut)

    for length in [0, 1, 63, 64, 65, 127, 128, 129, 500, 960, 1023, 1024]:
        for root in [True, False]:
            for keyed in [False, True]:
                data = bytes(random.getrandbits(8) for _ in range(length))
                key = [random.getrandbits(32) for _ in range(8)] if keyed else list(IV)
                base_flags = KEYED_HASH if keyed else 0
                chunk_index = 0 if root else random.getrandbits(64)

                got = await run_chunk(dut, data, key, base_flags, chunk_index, root)

                chunk = ChunkState(key, chunk_index, base_flags)
                chunk.update(data)
                expected, _ = chunk.output_cv(is_root=root)

                context = f"len={length} root={root} keyed={keyed} chunk_index={chunk_index}"

                for i in range(8):
                    assert got[i] == expected[i], f"{context}, word {i}, got {got[i]:#010x}, expected {expected[i]:#010x}"

        dut._log.info(f"passed: length {length}")

@cocotb.test()
async def test_matches_real_hash(dut):
    # For a message of 1024 bytes or less, the root chunk's value IS the BLAKE3
    # hash, so the hardware should reproduce the full hash of short messages.
    await start_and_reset(dut)

    for length in [0, 1, 64, 65, 200, 1024]:
        data = bytes(i % 251 for i in range(length))

        got = await run_chunk(dut, data, list(IV), 0, 0, True)

        got_bytes = b"".join(w.to_bytes(4, "little") for w in got) # 8 words -> 32 bytes
        expected = Blake3().hash(data)

        assert got_bytes == expected, f"len={length}, got {got_bytes.hex()}, expected {expected.hex()}"

@cocotb.test()
async def test_many_random_chunks(dut):
    # 100 chunks back to back with no reset: random lengths, modes, chunk
    # indexes, root settings, and "last chunk of the message" settings.
    # Checks that first_q and cv_q start correctly for each new chunk after
    # the previous one finishes, and that cv_last follows blk_msg_last.
    await start_and_reset(dut)

    for n in range(100):
        length = random.randint(0, 1024)
        data = bytes(random.getrandbits(8) for _ in range(length))
        keyed = random.random() < 0.5
        key = [random.getrandbits(32) for _ in range(8)] if keyed else list(IV)
        base_flags = KEYED_HASH if keyed else 0
        root = random.random() < 0.3
        chunk_index = 0 if root else random.getrandbits(64)
        msg_last = root or random.random() < 0.5 # a root chunk is always the message's last

        got = await run_chunk(dut, data, key, base_flags, chunk_index, root, msg_last)

        chunk = ChunkState(key, chunk_index, base_flags)
        chunk.update(data)
        expected, _ = chunk.output_cv(is_root=root)

        context = f"chunk {n}: len={length} root={root} msg_last={msg_last} keyed={keyed} chunk_index={chunk_index}"

        for i in range(8):
            assert got[i] == expected[i], f"{context}, word {i}, got {got[i]:#010x}, expected {expected[i]:#010x}"

@cocotb.test()
async def test_slow_source(dut):
    # The block source pauses for a random number of cycles before each block.
    # The chunk controller must simply wait; the result must not change.
    await start_and_reset(dut)

    for n in range(50):
        length = random.randint(0, 1024)
        data = bytes(random.getrandbits(8) for _ in range(length))

        dut.key.value = pack(list(IV))
        dut.base_flags.value = 0

        blocks = [data[i:i + 64] for i in range(0, len(data), 64)] or [b""]

        for b, block in enumerate(blocks):
            await ClockCycles(dut.clk, random.randint(0, 15)) # random pause
            await FallingEdge(dut.clk)
            await send_block(dut, block, len(block), b == len(blocks) - 1, False, n)

        cycles = 0
        while int(dut.cv_valid.value) != 1:
            await FallingEdge(dut.clk)
            cycles += 1

            assert cycles < 50, "cv_valid never went high"

        got = unpack(int(dut.cv_out.value), 8)

        chunk = ChunkState(list(IV), n, 0)
        chunk.update(data)
        expected, _ = chunk.output_cv(is_root=False)

        for i in range(8):
            assert got[i] == expected[i], f"chunk {n}: len={length}, word {i}, got {got[i]:#010x}, expected {expected[i]:#010x}"

@cocotb.test()
async def test_cv_valid_pulse(dut):
    # cv_valid must be high for exactly one cycle per chunk, and never after a
    # block that isn't the chunk's last.
    await start_and_reset(dut)

    data = bytes(random.getrandbits(8) for _ in range(300)) # 5 blocks
    dut.key.value = pack(list(IV))
    dut.base_flags.value = 0

    blocks = [data[i:i + 64] for i in range(0, len(data), 64)]

    for b, block in enumerate(blocks):
        last = (b == len(blocks) - 1)
        await send_block(dut, block, len(block), last, False, 0)

        if not last: # until the controller is ready again, cv_valid must stay low
            while int(dut.blk_ready.value) != 1:
                assert int(dut.cv_valid.value) == 0, f"cv_valid after block {b}, which was not the last"
                await FallingEdge(dut.clk)

    cycles = 0
    while int(dut.cv_valid.value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 50, "cv_valid never went high"

    await FallingEdge(dut.clk)
    assert int(dut.cv_valid.value) == 0, "cv_valid lasted more than one cycle"