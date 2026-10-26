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
