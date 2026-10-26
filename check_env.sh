#!/usr/bin/env bash
# check_env.sh - confirms every tool the project needs is installed.
# Run from this folder:   bash check_env.sh
cd "$(dirname "$0")"
[ -f .venv/bin/activate ] && source .venv/bin/activate

ok=true
check () {
  if "$@" > /dev/null 2>&1; then echo "  OK    $1"; else echo "  MISSING  $1"; ok=false; fi
}

echo "Tools:"
check iverilog -V
check gtkwave --version
check make --version
check git --version
check python3 --version
check cocotb-config --version
check pytest --version

echo
echo "Python reference model:"
python3 -m pytest -q blake3_test.py | tail -1

echo
if $ok; then
  echo "Environment ready. cocotb $(cocotb-config --version), $(iverilog -V 2>&1 | head -1)"
else
  echo "Something is missing: run   bash setup.sh"
fi
