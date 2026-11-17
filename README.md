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
