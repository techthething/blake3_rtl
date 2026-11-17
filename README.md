# BLAKE3 Hardware Accelerator

SystemVerilog implementation of the BLAKE3 hash function, verified with cocotb
against a Python reference model.

## Layout

| Path | Contents |
| --- | --- |
| `blake3.py` | Python reference model |
| `blake3_test.py` | Tests for the model against official BLAKE3 outputs |
| `rtl/` | SystemVerilog modules, one per file |
| `tb/` | cocotb testbenches and the simulator Makefile |
| `formal/` | Formal verification harness and SymbiYosys job for the arbiter |
| `synth/` | Yosys / nextpnr synthesis scripts for the Lattice ECP5 |
| `setup.sh` | One-time install of the tools |
| `check_env.sh` | Confirms the tools are installed |

## Every session

```
cd ~/blake3
source .venv/bin/activate
code .
```

## Running

- Python model tests: `pytest -q` (from this folder)
- An RTL test: `cd tb && make`
- Every RTL test: `cd tb && make regress`
- Two-cycle-round core tests: `cd tb && make regress_two_cycle`
- Formal proof of the arbiter: `cd formal && sby -f arbiter.sby`
  (needs Yosys, SymbiYosys and the Z3 solver)

## Assertions and formal verification

Every module carries SystemVerilog assertions describing rules it must never
break. They use one macro, `CHECK`, from `rtl/blake3_assert.svh`, and sit inside
`` `ifndef SYNTHESIS ``, so they are active in simulation and formal
verification but add no hardware.

| Module | What the assertions check |
| --- | --- |
| `blake3_compress` | round counter stays in rounds 0 to 6; the core is free when its result appears; block length at most 64 |
| `blake3_chunk` | only a chunk's last block may be partial; no new block while one is in the core; chunk value only on a core result; never the PARENT flag, ROOT only with CHUNK_END |
| `blake3_tree` | FSM stays in its 3 states; stack never pops when empty or pushes when full; one-entry input buffer never overflows; root only once the stack is empty |
| `blake3_arbiter` | tree priority holds; at most one side accepted per cycle; each result goes to exactly one side |
| `blake3_top` | only the message's last block may be partial; one hash per finished message; `hash_valid` is a one-cycle pulse |

In simulation, a failing assertion stops the run with `$fatal` and names the
broken rule, so the cocotb test fails. All 24 assertions hold across the full
regression.

The arbiter is also **formally proven** with SymbiYosys (`formal/`). The
harness lets the solver drive every input freely, assuming only that the
compression core behaves like the real one, and adds end-to-end checks written
purely from the handshakes: the core always receives exactly the accepted
side's request, and every result returns to the side that asked for it.

- **bmc**: no assertion can fail within 30 cycles of reset
- **prove**: k-induction proves the assertions hold for every cycle, forever
- **cover**: contention, results to each side, and back-to-back requests are all
  reachable, so the assumptions do not hide the interesting cases

Open-source Yosys and Icarus Verilog do not support concurrent properties
(`assert property (... |=> ...)`) or `$past()` in simulation, so the
assertions are immediate assertions in clocked blocks, with a helper register
where the previous cycle is needed.

## Microarchitecture trade-off: one round per cycle vs. two

`blake3_compress` has a parameter, `TWO_CYCLE_ROUND`, that selects between two
versions of the round datapath. Both produce bit-exact BLAKE3 output and pass
the same tests and assertions.

- **One cycle per round** (`TWO_CYCLE_ROUND = 0`, the default): 8 G functions,
  4 column G's feeding 4 diagonal G's, all in one cycle. 7 cycles per compression.
- **Two cycles per round** (`TWO_CYCLE_ROUND = 1`): 4 G functions shared between
  the column step and the diagonal step, with muxes choosing each G's state and
  message words, and a `phase_q` bit tracking which half of the round is next.
  14 cycles per compression, but each cycle has only half the logic.

Measured on the Lattice ECP5-25F (Yosys 0.71 + nextpnr, out of context, 3 placement
seeds each; cycles per block from a 64 KB message in simulation):

| | One cycle per round | Two cycles per round |
| --- | --- | --- |
| Max clock (mean of 3 seeds) | 28.2 MHz (27.8 – 28.7) | 45.5 MHz (44.2 – 46.4) |
| Cycles per 64-byte block | 9.44 | 16.87 |
| Throughput | **191 MB/s (1.53 Gbps)** | 173 MB/s (1.38 Gbps) |
| Latency per compression | 248 ns | 308 ns |
| Logic cells (TRELLIS_COMB) | 6,022 | 6,013 |
| Carry-chain cells (CCU2C) | 549 | 293 |
| Flip-flops | 1,899 | 1,900 |

The two-cycle version clocks 1.61× faster but needs 1.79× more cycles, so it
is about 10% slower overall. It would need at least 50.4 MHz to break even. Why
the faster clock falls short:

- **Logic halved, routing did not.** On the critical path, logic delay dropped
  from 11.9 ns to 6.6 ns as intended, but routing only from 22.4 ns to 14.5 ns.
  Each shared G's input muxes collect state words from across the whole 512-bit
  state register, so the wires stay long.
- **No area saved.** Sharing removes 4 G functions (the carry chains halve), but
  the 2:1 muxes that steer their inputs and outputs cost about as much FPGA logic
  as the adders they replace, so total logic is unchanged.
- **Tried and rejected: duplicating `phase_q`.** The critical path starts at
  `phase_q`, which drives over a thousand mux selects, so four copies (one per
  G lane) were tried to cut its fanout. The clock did not improve (42.9 – 45.3 MHz,
  within seed-to-seed variation), which showed the limit is the muxed datapath's
  wiring, not one overloaded signal. The copies were removed.

On this FPGA the one-cycle round is the better design. Sharing hardware pays off
when area is the constraint and muxes are cheap relative to the logic shared, or
when the core must meet a faster system clock regardless of throughput.

To reproduce: `cd synth`, run `yowasp-yosys synth_ecp5.ys` and
`yowasp-yosys synth_ecp5_two_cycle.ys`, then place and route each netlist with
`yowasp-nextpnr-ecp5 --25k --package CABGA381 --out-of-context --freq 100 --json <netlist>`.
Cycles per block: `cd tb && make TEST=top COCOTB_TEST_MODULES=test_throughput TWO_CYCLE_ROUND=0` (or `=1`).
