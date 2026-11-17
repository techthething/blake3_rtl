// blake3_assert.svh: the CHECK macro used by the assertions in each module.
//
// CHECK(condition, message) is an immediate SystemVerilog assertion. Each
// module puts its CHECKs inside `ifndef SYNTHESIS, so they are:
//   - in simulation (Icarus): checked every clock edge; a failure stops the
//     simulation with $fatal, so the cocotb test that caused it fails
//   - in formal verification (SymbiYosys, which defines FORMAL): proven for
//     every possible input sequence; failures produce a counterexample trace
//   - in synthesis (Yosys and Vivado define SYNTHESIS): left out entirely,
//     so they add no hardware
//
// Why immediate assertions inside clocked blocks, and no $past()?
// Open-source Yosys and Icarus do not accept concurrent properties such as
// assert property (@(posedge clk) a |=> b), and Icarus cannot run $past().
// Checks that need the previous cycle use a small helper register instead.

`ifndef BLAKE3_ASSERT_SVH
`define BLAKE3_ASSERT_SVH

`ifdef FORMAL
    `define CHECK(cond, msg) assert (cond);
`else
    `define CHECK(cond, msg) assert (cond) else $fatal(1, "%m: %s", msg);
`endif

`endif
