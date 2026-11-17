import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ClockCycles

from blake3 import Blake3, KEYED_HASH, bytes_to_words32

def pack(words): # list of 32-bit words -> one integer
    value = 0
    for i, w in enumerate(words):
        value |= w << (32 * i)
    return value

def unpack(value, n): # one integer -> list of n 32-bit words
    return [(value >> (32 * i)) & 0xFFFFFFFF for i in range(n)]

def expected_hash(data, key, keyed): # what the Python model says the hash is
    if keyed:
        return Blake3(bytes_to_words32(key), KEYED_HASH).hash(data)
    return Blake3().hash(data)

async def start_and_reset(dut):
    Clock(dut.clk, 10, unit="ns").start() # start clock

    dut.rst_n.value = 0 # reset
    dut.in_valid.value = 0 # no block yet

    await ClockCycles(dut.clk, 2) # wait until we can confidently reset

    dut.rst_n.value = 1

    await FallingEdge(dut.clk)

async def send_block(dut, block, last):
    # present one block (zero-padded to 64 bytes) and hold it until it is accepted
    dut.in_data.value = pack(bytes_to_words32(block + b"\x00" * (64 - len(block))))
    dut.in_len.value = len(block)
    dut.in_last.value = last
    dut.in_valid.value = 1

    cycles = 0
    while int(dut.in_ready.value) != 1: # wait until the accelerator can take it
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 200, "in_ready never went high"

    await FallingEdge(dut.clk) # the rising edge in between accepted it
    dut.in_valid.value = 0

async def hash_message(dut, data, key, keyed, max_pause=0):
    # send a whole message block by block, then wait for the hash; returns 32 bytes.
    # max_pause > 0 adds a random pause (0 to max_pause cycles) before each block.
    dut.keyed.value = keyed
    dut.key.value = pack(bytes_to_words32(key))

    blocks = [data[i:i + 64] for i in range(0, len(data), 64)] or [b""] # empty message = one 0-byte block

    for n, block in enumerate(blocks):
        if max_pause > 0:
            await ClockCycles(dut.clk, random.randint(0, max_pause))
            await FallingEdge(dut.clk)

        await send_block(dut, block, n == len(blocks) - 1)

    cycles = 0
    while int(dut.hash_valid.value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 1000, "hash_valid never went high"

    return b"".join(w.to_bytes(4, "little") for w in unpack(int(dut.hash_out.value), 8)) # 8 words -> 32 bytes

@cocotb.test()
async def test_lengths(dut):
    # Hand-picked message lengths around every boundary: empty, one byte, one
    # block, one chunk (1024), just past one chunk, and around 2, 3, 16, and
    # 17 chunks (where the tree changes shape). Plain mode.
    await start_and_reset(dut)

    lengths = [0, 1, 63, 64, 65, 1023, 1024, 1025, 2047, 2048, 2049, 3072, 3073,
               4096, 5000, 8192, 8193, 16 * 1024, 16 * 1024 + 1, 17 * 1024]

    for length in lengths:
        data = bytes(random.getrandbits(8) for _ in range(length))

        got = await hash_message(dut, data, bytes(32), False)
        expected = expected_hash(data, bytes(32), False)

        assert got == expected, f"len={length}, got {got.hex()}, expected {expected.hex()}"

        dut._log.info(f"passed: length {length}")

@cocotb.test()
async def test_keyed(dut):
    # The same kind of lengths in keyed mode, each with a random key.
    await start_and_reset(dut)

    for length in [0, 1, 64, 1024, 1025, 3000, 9000]:
        key = bytes(random.getrandbits(8) for _ in range(32))
        data = bytes(random.getrandbits(8) for _ in range(length))

        got = await hash_message(dut, data, key, True)
        expected = expected_hash(data, key, True)

        assert got == expected, f"keyed len={length}, got {got.hex()}, expected {expected.hex()}"

@cocotb.test()
async def test_many_messages(dut):
    # 25 random messages back to back with no reset: random lengths up to
    # about 12 chunks, random modes and keys. Each message starts right after
    # the previous hash, so the chunk index, block counter, and tree must all
    # start fresh every time.
    await start_and_reset(dut)

    for n in range(25):
        length = random.choice([random.randint(0, 1024), random.randint(1025, 12 * 1024)])
        keyed = random.random() < 0.5
        key = bytes(random.getrandbits(8) for _ in range(32))
        data = bytes(random.getrandbits(8) for _ in range(length))

        got = await hash_message(dut, data, key, keyed)
        expected = expected_hash(data, key, keyed)

        assert got == expected, f"message {n}: len={length} keyed={keyed}, got {got.hex()}, expected {expected.hex()}"

@cocotb.test()
async def test_slow_source(dut):
    # Blocks arrive with random pauses between them. The accelerator must
    # simply wait; the hashes must not change.
    await start_and_reset(dut)

    for n in range(8):
        length = random.randint(0, 5000)
        data = bytes(random.getrandbits(8) for _ in range(length))

        got = await hash_message(dut, data, bytes(32), False, max_pause=10)
        expected = expected_hash(data, bytes(32), False)

        assert got == expected, f"message {n}: len={length}, got {got.hex()}, expected {expected.hex()}"

@cocotb.test()
async def test_one_message_at_a_time(dut):
    # After a message's last block, in_ready must stay low until hash_valid,
    # so the next message cannot start early. hash_valid must last one cycle.
    await start_and_reset(dut)

    data = bytes(random.getrandbits(8) for _ in range(3 * 1024 + 100)) # 4 chunks, the last one partial
    dut.keyed.value = 0
    dut.key.value = 0

    blocks = [data[i:i + 64] for i in range(0, len(data), 64)]
    for n, block in enumerate(blocks):
        await send_block(dut, block, n == len(blocks) - 1)

    dut.in_valid.value = 1 # the next message's first block is already waiting
    dut.in_last.value = 0

    cycles = 0
    while int(dut.hash_valid.value) != 1:
        assert int(dut.in_ready.value) == 0, f"in_ready high {cycles} cycles after the last block, before hash_valid"
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 1000, "hash_valid never went high"

    got = b"".join(w.to_bytes(4, "little") for w in unpack(int(dut.hash_out.value), 8))
    assert got == expected_hash(data, bytes(32), False), "wrong hash"

    dut.in_valid.value = 0
    await FallingEdge(dut.clk)
    assert int(dut.hash_valid.value) == 0, "hash_valid lasted more than one cycle"
    assert int(dut.in_ready.value) == 1, "in_ready not high again after the hash"