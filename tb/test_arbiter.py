import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ClockCycles, Timer

from blake3 import compress

# Note on Timer(1, "ns"): in_ready depends on what BOTH sides drive. Values
# written at a falling edge only take effect after that instant, so the test
# waits 1 ns before reading in_ready, to see the result of both sides' writes.

# The test plays both controllers. "side" is "chunk" or "tree": the prefix of
# that controller's ports on the wrapper, e.g. dut.chunk_in_valid, dut.tree_in_valid.

def pack(words): # list of 32-bit words -> one integer
    value = 0
    for i, w in enumerate(words):
        value |= w << (32 * i)
    return value

def unpack(value, n): # one integer -> list of n 32-bit words
    return [(value >> (32 * i)) & 0xFFFFFFFF for i in range(n)]

def port(dut, side, name): # e.g. port(dut, "tree", "in_valid") -> dut.tree_in_valid
    return getattr(dut, f"{side}_{name}")

def random_request(): # one random compression request: (cv, block, counter, block_len, flags)
    cv = [random.getrandbits(32) for _ in range(8)]
    block = [random.getrandbits(32) for _ in range(16)]
    return cv, block, random.getrandbits(64), random.randint(0, 64), random.randint(0, 127)

async def start_and_reset(dut):
    Clock(dut.clk, 10, unit="ns").start() # start clock

    dut.rst_n.value = 0 # reset
    dut.chunk_in_valid.value = 0 # neither side is asking yet
    dut.tree_in_valid.value = 0

    await ClockCycles(dut.clk, 2) # wait until we can confidently reset

    dut.rst_n.value = 1

    await FallingEdge(dut.clk)

def drive_request(dut, side, request):
    # put one request on a side's ports and raise its in_valid
    cv, block, counter, block_len, flags = request

    port(dut, side, "cv_in").value = pack(cv)
    port(dut, side, "block_in").value = pack(block)
    port(dut, side, "counter").value = counter
    port(dut, side, "block_len").value = block_len
    port(dut, side, "flags").value = flags
    port(dut, side, "in_valid").value = 1

async def send_request(dut, side, request):
    # hold the request until this side sees in_ready, like a real controller does
    drive_request(dut, side, request)
    await Timer(1, "ns") # let both sides' writes take effect before reading in_ready

    cycles = 0
    while int(port(dut, side, "in_ready").value) != 1: # wait until the arbiter gives this side the core
        await FallingEdge(dut.clk)
        await Timer(1, "ns")
        cycles += 1

        assert cycles < 100, f"{side}_in_ready never went high"

    await FallingEdge(dut.clk) # the rising edge in between accepted it
    port(dut, side, "in_valid").value = 0

async def wait_for_result(dut, side):
    # wait until this side's out_valid is high; return the 16 output words
    cycles = 0
    while int(port(dut, side, "out_valid").value) != 1:
        await FallingEdge(dut.clk)
        cycles += 1

        assert cycles < 100, f"{side}_out_valid never went high"

    return unpack(int(port(dut, side, "out").value), 16)

def check_result(got, request, context):
    expected = compress(*request)

    for i in range(16):
        assert got[i] == expected[i], f"{context}, word {i}, got {got[i]:#010x}, expected {expected[i]:#010x}"

@cocotb.test()
async def test_one_side_at_a_time(dut):
    # 20 requests from the chunk side, then 20 from the tree side, with the
    # other side quiet. Each result must be correct, and the quiet side must
    # never see out_valid.
    await start_and_reset(dut)

    for side, other in [("chunk", "tree"), ("tree", "chunk")]:
        for n in range(20):
            request = random_request()
            await send_request(dut, side, request)

            while int(port(dut, side, "out_valid").value) != 1: # the other side must stay quiet
                assert int(port(dut, other, "out_valid").value) == 0, f"{other}_out_valid high for a {side} request"
                await FallingEdge(dut.clk)

            got = unpack(int(port(dut, side, "out").value), 16)
            check_result(got, request, f"{side} request {n}")

@cocotb.test()
async def test_both_ask_same_cycle(dut):
    # Both sides raise in_valid in the same cycle. The tree side has priority:
    # only it may see in_ready, its result comes back first and only to it,
    # and the chunk side is served right after.
    await start_and_reset(dut)

    for n in range(10):
        chunk_request = random_request()
        tree_request = random_request()

        drive_request(dut, "chunk", chunk_request)
        drive_request(dut, "tree", tree_request)
        await Timer(1, "ns") # let the writes take effect

        assert int(dut.tree_in_ready.value) == 1, "tree side should get the core first"
        assert int(dut.chunk_in_ready.value) == 0, "chunk side saw in_ready while the tree side was asking"

        await FallingEdge(dut.clk) # tree request accepted at this edge
        dut.tree_in_valid.value = 0 # chunk side keeps asking

        got = await wait_for_result(dut, "tree")
        assert int(dut.chunk_out_valid.value) == 0, "chunk_out_valid high for the tree's result"
        check_result(got, tree_request, f"round {n}, tree")

        assert int(dut.chunk_in_ready.value) == 1, "chunk side not served once the core is free"
        await FallingEdge(dut.clk) # chunk request accepted at this edge
        dut.chunk_in_valid.value = 0

        got = await wait_for_result(dut, "chunk")
        assert int(dut.tree_out_valid.value) == 0, "tree_out_valid high for the chunk's result"
        check_result(got, chunk_request, f"round {n}, chunk")

        await FallingEdge(dut.clk)

async def requester(dut, side, count):
    # one side's traffic: random pauses, then a request, then wait for its own result
    for n in range(count):
        await ClockCycles(dut.clk, random.randint(0, 12)) # random pause
        await FallingEdge(dut.clk)

        request = random_request()
        await send_request(dut, side, request)
        got = await wait_for_result(dut, side)
        check_result(got, request, f"{side} request {n}")

        await FallingEdge(dut.clk) # step past this side's out_valid cycle

@cocotb.test()
async def test_random_traffic(dut):
    # Both sides send 100 requests each at random times, running at the same
    # time, so they often collide. Each side checks that every result it gets
    # is the answer to its own request (a mixed-up owner would fail here), and
    # the two out_valids must never be high together.
    await start_and_reset(dut)

    chunk_task = cocotb.start_soon(requester(dut, "chunk", 100))
    tree_task = cocotb.start_soon(requester(dut, "tree", 100))

    while not (chunk_task.done() and tree_task.done()):
        assert not (int(dut.chunk_out_valid.value) and int(dut.tree_out_valid.value)), "both out_valids high at once"
        await FallingEdge(dut.clk)

    await chunk_task # re-raises any failed check from inside the task
    await tree_task