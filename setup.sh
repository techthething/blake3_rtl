#!/usr/bin/env bash
# setup.sh - one-time setup for the BLAKE3 RTL project.
# Run inside WSL Ubuntu, from this folder:   bash setup.sh
set -e
cd "$(dirname "$0")"

echo "== Installing simulator and tools (asks for your Ubuntu password) =="
sudo apt update
sudo apt install -y iverilog gtkwave make git python3-pip python3-venv

echo "== Creating Python environment in .venv =="
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo
echo "== Checking the setup =="
bash check_env.sh
