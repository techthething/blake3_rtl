import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles

from blake3 import compress

def pack(words): # list of 32 bit words -> one integer
    value = 0
    for i, w in enumerate(words):
        value |= w << (32 * i)
    return value

def unpack(value, n): # one integer list of n 32-bit words
    return [(value >> (32 * i)) & 0xFFFFFFFF for i in range(n)]

async def start_and_reset(dut):
    Clock(dut.clk, 10, unit="ns").start() # start clock

    dut.rst_n.value = 0 # reset core
    dut.in_valid.value = 0 # don't want to accept values yet

    await ClockCycles(dut.clk, 2) # wait until we can confidently reset

    dut.rst_n.value = 1

    await FallingEdge(dut.clk)

def drive_inputs(dut, cv, block, counter, block_len, flags):
    dut.cv_in.value = pack(cv)
    dut.block_in.value = pack(block)

    dut.counter.value = counter
    dut.block_len.value = block_len
    dut.flags.value = flags

async def run_compress(dut, cv, block, counter, block_len, flags):
    drive_inputs(dut, cv, block, counter, block_len, flags) 
    dut.in_valid.value = 1

    await FallingEdge(dut.clk)
    dut.in_valid.value = 0

    cycles = 0 # how many cycles between core accepting request and out_valid going high

    while int(dut.out_valid.value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 20, "out_valid never went high"

    return unpack(int(dut.out.value), 16), cycles

@cocotb.test()
async def test_many_randoms(dut):
    await start_and_reset(dut)

    for n in range(1000):
        cv = [random.getrandbits(32) for _ in range(8)]
        block = [random.getrandbits(32) for _ in range(16)]
        counter = random.getrandbits(64)
        block_len = random.randint(0, 64)
        flags = random.randint(0, 127)

        got, cycles = await run_compress(dut, cv, block, counter, block_len, flags)

        expected = compress(cv, block, counter, block_len, flags)

        context = f"case {n}: counter={counter:#018x} block_len={block_len} flags={flags:#04x}"

        for i in range(16):
            assert got[i] == expected[i], f"{context}, current pos {i}, got {got[i]:#010x}, expected {expected[i]:#010x}"

        assert cycles == 7, f"{context}, actual cycles: {cycles}"

async def test_directed(dut):
    # Hand-picked edge cases that random inputs are unlikely to hit exactly:
    # all-zero and all-max inputs (every addition overflows), both ends of
    # block_len, each half of the 64-bit counter, and each flag bit on its own.
    await start_and_reset(dut)
 
    M32 = 0xFFFFFFFF
    cases = [
        # name,                cv,         block,       counter,      block_len, flags
        ("all zero",           [0] * 8,    [0] * 16,    0,            0,         0),
        ("all max",            [M32] * 8,  [M32] * 16,  2**64 - 1,    64,        127),
        ("block_len 0",        [M32] * 8,  [M32] * 16,  1,            0,         0),
        ("block_len 64",       [M32] * 8,  [M32] * 16,  1,            64,        0),
        ("counter high half",  [0] * 8,    [0] * 16,    1 << 32,      0,         0),
        ("counter low half",   [0] * 8,    [0] * 16,    1,            0,         0),
    ]
    for bit in range(7):
        cases.append((f"flag bit {bit}", [0] * 8, [0] * 16, 0, 0, 1 << bit))
 
    for name, cv, block, counter, block_len, flags in cases:
        got, cycles = await run_compress(dut, cv, block, counter, block_len, flags)
 
        expected = compress(cv, block, counter, block_len, flags)
 
        for i in range(16):
            assert got[i] == expected[i], f"{name}, current pos {i}, got {got[i]:#010x}, expected {expected[i]:#010x}"
 
        assert cycles == 7, f"{name}, actual cycles: {cycles}"
 
        dut._log.info(f"passed: {name}")
 
@cocotb.test()
async def test_inputs_change_after_accept(dut):
    # The core must copy everything it needs into its registers on the accept
    # edge. Here we scramble every input right after the accept; the result
    # must still match the original inputs. Catches, for example, the output
    # fold reading cv_in instead of cv_q, which the random tests cannot see.
    await start_and_reset(dut)
 
    cv = [random.getrandbits(32) for _ in range(8)]
    block = [random.getrandbits(32) for _ in range(16)]
    counter = random.getrandbits(64)
    block_len = random.randint(0, 64)
    flags = random.randint(0, 127)
 
    drive_inputs(dut, cv, block, counter, block_len, flags)
    dut.in_valid.value = 1
    await FallingEdge(dut.clk)              # the rising edge in between accepted it
    dut.in_valid.value = 0
 
    # Put completely different data on every input while the core is busy
    drive_inputs(dut,
                 [random.getrandbits(32) for _ in range(8)],
                 [random.getrandbits(32) for _ in range(16)],
                 random.getrandbits(64),
                 random.randint(0, 64),
                 random.randint(0, 127))
 
    cycles = 0
    while int(dut.out_valid.value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1
        assert cycles < 20, "out_valid never went high"
 
    got = unpack(int(dut.out.value), 16)
    expected = compress(cv, block, counter, block_len, flags)
 
    for i in range(16):
        assert got[i] == expected[i], f"current pos {i}, got {got[i]:#010x}, expected {expected[i]:#010x}"
 
    assert cycles == 7, f"actual cycles: {cycles}"
 
@cocotb.test()
async def test_requests_ignored_while_busy(dut):
    # While the core is busy, a request must be ignored, not restart it.
    # We keep in_valid high, with different data, for the whole compression.
    # The result must match the first request, which shows in_ready (and the
    # in_valid && in_ready check) is protecting the compression in progress.
    await start_and_reset(dut)
 
    cv = [random.getrandbits(32) for _ in range(8)]
    block = [random.getrandbits(32) for _ in range(16)]
    counter = random.getrandbits(64)
    block_len = random.randint(0, 64)
    flags = random.randint(0, 127)
 
    drive_inputs(dut, cv, block, counter, block_len, flags)
    dut.in_valid.value = 1
    await FallingEdge(dut.clk) # first request accepted
 
    # A second, different request, left valid the whole time the core is busy
    drive_inputs(dut,
                 [random.getrandbits(32) for _ in range(8)],
                 [random.getrandbits(32) for _ in range(16)],
                 random.getrandbits(64),
                 random.randint(0, 64),
                 random.randint(0, 127))
 
    cycles = 0
    while int(dut.out_valid.value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1
        assert cycles < 20, "out_valid never went high"
 
    dut.in_valid.value = 0
 
    got = unpack(int(dut.out.value), 16)
    expected = compress(cv, block, counter, block_len, flags)
 
    for i in range(16):
        assert got[i] == expected[i], f"current pos {i}, got {got[i]:#010x}, expected {expected[i]:#010x}"
 
    assert cycles == 7, f"actual cycles: {cycles}"
 
@cocotb.test()
async def test_handshake_timing(dut):
    # Checks the control signals cycle by cycle against the timing table:
    # in_ready is high when idle, low on every cycle of the compression,
    # high again when out_valid rises; out_valid is high for exactly one cycle.
    await start_and_reset(dut)
 
    assert int(dut.in_ready.value) == 1, "in_ready should be high when idle after reset"
    assert int(dut.out_valid.value) == 0, "out_valid should be low after reset"
 
    drive_inputs(dut,
                 [random.getrandbits(32) for _ in range(8)],
                 [random.getrandbits(32) for _ in range(16)],
                 random.getrandbits(64),
                 random.randint(0, 64),
                 random.randint(0, 127))
    dut.in_valid.value = 1                  # cycle 0: request presented
    await FallingEdge(dut.clk)              # accepted at the end of cycle 0
    dut.in_valid.value = 0
 
    # Cycles 1 to 7 (the seven rounds): busy, nothing ready yet
    for cycle in range(1, 8):
        assert int(dut.in_ready.value) == 0, f"in_ready high while busy (cycle {cycle})"
        assert int(dut.out_valid.value) == 0, f"out_valid high too early (cycle {cycle})"
        await FallingEdge(dut.clk)
 
    # Cycle 8: result ready, and the core is free again
    assert int(dut.out_valid.value) == 1, "out_valid not high in cycle 8"
    assert int(dut.in_ready.value) == 1, "in_ready not high when the result is ready"
 
    # Cycle 9: out_valid must have dropped (a one-cycle pulse)
    await FallingEdge(dut.clk)
    assert int(dut.out_valid.value) == 0, "out_valid lasted more than one cycle"
    assert int(dut.in_ready.value) == 1, "in_ready should stay high while idle"
 
@cocotb.test()
async def test_reset_midway(dut):
    # Reset in the middle of a compression must abandon it cleanly:
    # the core becomes ready, never reports the abandoned result, and the
    # next compression after reset gives the correct answer.
    await start_and_reset(dut)
 
    drive_inputs(dut,
                 [random.getrandbits(32) for _ in range(8)],
                 [random.getrandbits(32) for _ in range(16)],
                 random.getrandbits(64),
                 random.randint(0, 64),
                 random.randint(0, 127))
    dut.in_valid.value = 1
    await FallingEdge(dut.clk)              # accepted
    dut.in_valid.value = 0
 
    await ClockCycles(dut.clk, 3)           # partway through the rounds
 
    dut.rst_n.value = 0                     # reset for two edges
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)
 
    assert int(dut.in_ready.value) == 1, "in_ready not high after reset"
 
    # Watch long enough that the abandoned compression would have finished
    for _ in range(12):
        assert int(dut.out_valid.value) == 0, "out_valid went high after reset"
        await FallingEdge(dut.clk)
 
    # A fresh compression must work normally
    cv = [random.getrandbits(32) for _ in range(8)]
    block = [random.getrandbits(32) for _ in range(16)]
    counter = random.getrandbits(64)
    block_len = random.randint(0, 64)
    flags = random.randint(0, 127)
 
    got, cycles = await run_compress(dut, cv, block, counter, block_len, flags)
 
    expected = compress(cv, block, counter, block_len, flags)
 
    for i in range(16):
        assert got[i] == expected[i], f"current pos {i}, got {got[i]:#010x}, expected {expected[i]:#010x}"
 
    assert cycles == 7, f"actual cycles: {cycles}"