import random
import cocotb
from cocotb.triggers import Timer

from blake3 import g

async def check_g(dut, a, b, c, d, mx, my):
    dut.a.value  = a
    dut.b.value  = b
    dut.c.value  = c
    dut.d.value  = d
    dut.mx.value = mx
    dut.my.value = my
    
    await Timer(1, unit="ns")
            
    expected = [a, b, c, d]
    g(expected, 0, 1, 2, 3, mx, my)
            
    got_a = int(dut.a_out.value)
    assert got_a == expected[0], f"a_out: got {got_a:#010x}, expected {expected[0]:#010x}"
            
    got_b = int(dut.b_out.value)
    assert got_b == expected[1], f"b_out: got {got_b:#010x}, expected {expected[1]:#010x}"
            
    got_c = int(dut.c_out.value)
    assert got_c == expected[2], f"c_out: got {got_c:#010x}, expected {expected[2]:#010x}"
                    
    got_d = int(dut.d_out.value)
    assert got_d == expected[3], f"d_out: got {got_d:#010x}, expected {expected[3]:#010x}"

@cocotb.test()
async def test_g_random(dut): # test random inputs to g function, check verilog matches python result
    for _ in range(1000):
        await check_g(dut, random.getrandbits(32), random.getrandbits(32), random.getrandbits(32),
                      random.getrandbits(32), random.getrandbits(32), random.getrandbits(32))

@cocotb.test()
async def test_g_fixed(dut): # test if correct when 0x00000000 or 0xFFFFFFFF
    for value in [0x00000000, 0xFFFFFFFF]:
        await check_g(dut, value, value, value, value, value, value)