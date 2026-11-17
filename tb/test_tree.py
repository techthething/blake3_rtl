import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ClockCycles

from blake3 import ChunkState, Blake3, IV, KEYED_HASH

CHUNK_GAP = 144 # cycles between chunk values: the chunk controller needs 16 blocks x 9 cycles per full chunk

def pack(words): # list of 32-bit words -> one integer
    value = 0
    for i, w in enumerate(words):
        value |= w << (32 * i)
    return value

def unpack(value, n): # one integer -> list of n 32-bit words
    return [(value >> (32 * i)) & 0xFFFFFFFF for i in range(n)]

def chunk_values(data, key, base_flags):
    # What the chunk controller would send for this message: one (chunk value, last) pair per chunk.
    # Only a one-chunk message gets ROOT on its chunk; otherwise the tree's final merge gets it.
    chunks = [data[i:i + 1024] for i in range(0, len(data), 1024)] or [b""] # empty message = one empty chunk
    values = []

    for i, chunk_data in enumerate(chunks):
        chunk = ChunkState(key, i, base_flags)
        chunk.update(chunk_data)
        cv, _ = chunk.output_cv(is_root=(len(chunks) == 1))
        values.append((cv, i == len(chunks) - 1))

    return values

async def start_and_reset(dut):
    Clock(dut.clk, 10, unit="ns").start() # start clock

    dut.rst_n.value = 0 # reset
    dut.chunk_cv_valid.value = 0 # no chunk value yet

    await ClockCycles(dut.clk, 2) # wait until we can confidently reset

    dut.rst_n.value = 1

    await FallingEdge(dut.clk)

async def send_chunk_cv(dut, cv, last):
    # present one chunk value for exactly one cycle, like the chunk controller's cv_valid pulse
    dut.chunk_cv.value = pack(cv)
    dut.chunk_cv_last.value = last
    dut.chunk_cv_valid.value = 1

    await FallingEdge(dut.clk) # the rising edge in between saved it into the buffer
    dut.chunk_cv_valid.value = 0

async def run_message(dut, data, key, base_flags):
    # send every chunk value of one message, then wait for the root; returns the 32-byte hash
    dut.key.value = pack(key)
    dut.base_flags.value = base_flags

    for cv, last in chunk_values(data, key, base_flags):
        await send_chunk_cv(dut, cv, last)

        if not last:
            await ClockCycles(dut.clk, CHUNK_GAP) # time the chunk controller needs for the next chunk
            await FallingEdge(dut.clk)

    cycles = 0
    while int(dut.root_valid.value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 500, "root_valid never went high"

    return b"".join(w.to_bytes(4, "little") for w in unpack(int(dut.root_out.value), 8)) # 8 words -> 32 bytes

@cocotb.test()
async def test_chunk_counts(dut):
    # Messages with hand-picked numbers of chunks, chosen to hit every tree shape:
    # powers of 2 (perfect trees: 2, 4, 8, 16, 32), one more than a power of 2
    # (a lone chunk merged at the very end: 3, 5, 9, 17, 33), and everything in
    # between. The last chunk has a random length, so it is usually partial.
    # The root must match the real BLAKE3 hash.
    await start_and_reset(dut)

    for n_chunks in [1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 16, 17, 32, 33]:
        length = (n_chunks - 1) * 1024 + random.randint(1, 1024)
        data = bytes(random.getrandbits(8) for _ in range(length))

        got = await run_message(dut, data, list(IV), 0)
        expected = Blake3().hash(data)

        assert got == expected, f"chunks={n_chunks} len={length}, got {got.hex()}, expected {expected.hex()}"

        dut._log.info(f"passed: {n_chunks} chunks")

@cocotb.test()
async def test_keyed(dut):
    # Same idea in keyed mode: the key replaces the IV in every parent
    # compression, and KEYED_HASH is ORed into every parent's flags.
    await start_and_reset(dut)

    for n_chunks in [1, 2, 3, 4, 9]:
        key = [random.getrandbits(32) for _ in range(8)]
        length = (n_chunks - 1) * 1024 + random.randint(1, 1024)
        data = bytes(random.getrandbits(8) for _ in range(length))

        got = await run_message(dut, data, key, KEYED_HASH)
        expected = Blake3(key, KEYED_HASH).hash(data)

        assert got == expected, f"keyed chunks={n_chunks} len={length}, got {got.hex()}, expected {expected.hex()}"

@cocotb.test()
async def test_many_messages(dut):
    # 20 messages back to back with no reset: random lengths (including empty)
    # and random modes. Checks that count_q and the stack are cleared after
    # each root, so every message starts fresh.
    await start_and_reset(dut)

    for n in range(20):
        length = random.choice([0, random.randint(1, 1024), random.randint(1025, 20000)])
        data = bytes(random.getrandbits(8) for _ in range(length))
        keyed = random.random() < 0.5
        key = [random.getrandbits(32) for _ in range(8)] if keyed else list(IV)
        base_flags = KEYED_HASH if keyed else 0

        got = await run_message(dut, data, key, base_flags)
        expected = Blake3(key, base_flags).hash(data)

        assert got == expected, f"message {n}: len={length} keyed={keyed}, got {got.hex()}, expected {expected.hex()}"

@cocotb.test()
async def test_chunk_arrives_while_busy(dut):
    # Chunk values arrive while the tree controller is still merging the
    # previous one, so they must wait in the input buffer. After every chunk
    # that needs merges (even chunk counts), the next chunk is sent only 3
    # cycles later, in the middle of those merges. The hash must not change.
    await start_and_reset(dut)

    data = bytes(random.getrandbits(8) for _ in range(12 * 1024)) # 12 chunks
    dut.key.value = pack(list(IV))
    dut.base_flags.value = 0

    values = chunk_values(data, list(IV), 0)
    buffered = 0 # how many chunk values arrived while the tree was busy

    for i, (cv, last) in enumerate(values):
        if int(dut.u_tree.state_q.value) != 0: # tree is not IDLE: this value has to wait in the buffer
            buffered += 1

        await send_chunk_cv(dut, cv, last)

        if not last:
            gap = 3 if (i + 1) % 2 == 0 else CHUNK_GAP # short gap right after a chunk that needs merges
            await ClockCycles(dut.clk, gap)
            await FallingEdge(dut.clk)

    cycles = 0
    while int(dut.root_valid.value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 500, "root_valid never went high"

    got = b"".join(w.to_bytes(4, "little") for w in unpack(int(dut.root_out.value), 8))
    expected = Blake3().hash(data)

    assert buffered > 0, "no chunk value arrived while the tree was busy, so the buffer was never tested"
    assert got == expected, f"got {got.hex()}, expected {expected.hex()}"

    dut._log.info(f"{buffered} chunk values waited in the buffer")

@cocotb.test()
async def test_root_valid_pulse(dut):
    # root_valid must stay low until the last chunk value has been sent,
    # then be high for exactly one cycle.
    await start_and_reset(dut)

    data = bytes(random.getrandbits(8) for _ in range(5 * 1024)) # 5 chunks
    dut.key.value = pack(list(IV))
    dut.base_flags.value = 0

    for cv, last in chunk_values(data, list(IV), 0):
        await send_chunk_cv(dut, cv, last)

        if not last: # while waiting for the next chunk, no root allowed
            for _ in range(CHUNK_GAP + 1):
                assert int(dut.root_valid.value) == 0, "root_valid before the last chunk was sent"
                await FallingEdge(dut.clk)

    cycles = 0
    while int(dut.root_valid.value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 500, "root_valid never went high"

    await FallingEdge(dut.clk)
    assert int(dut.root_valid.value) == 0, "root_valid lasted more than one cycle"