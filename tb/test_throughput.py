import random
import cocotb
from cocotb.triggers import FallingEdge, RisingEdge
from test_top import start_and_reset, send_block, expected_hash, unpack

@cocotb.test()
async def test_throughput(dut):
    # Hash one long message with the input always ready to go, and count the
    # cycles from the first block to hash_valid. Reports bytes per cycle.
    await start_and_reset(dut)

    length = 64 * 1024 # 64 chunks
    data = bytes(random.getrandbits(8) for _ in range(length))
    dut.keyed.value = 0
    dut.key.value = 0

    cycles = 0
    async def count():
        nonlocal cycles
        while True:
            await RisingEdge(dut.clk)
            cycles += 1
    counter = cocotb.start_soon(count())

    blocks = [data[i:i + 64] for i in range(0, length, 64)]
    for n, block in enumerate(blocks):
        await send_block(dut, block, n == len(blocks) - 1)
    while int(dut.hash_valid.value) != 1:
        await FallingEdge(dut.clk)
    counter.cancel()

    got = b"".join(w.to_bytes(4, "little") for w in unpack(int(dut.hash_out.value), 8))
    assert got == expected_hash(data, bytes(32), False)
    dut._log.info(f"{length} bytes in {cycles} cycles: {length / cycles:.3f} bytes/cycle, {cycles / (length // 64):.2f} cycles/block")