#!/bin/bash
set -e

echo "=== Cloning repo and setting up ==="
# Replace with your actual repo URL
# git clone https://github.com/YOUR_USER/trace_validity.git
# cd trace_validity

pip install -r requirements.txt
bash setup_lean.sh

echo "=== Running experiment ==="
# Single temperature
# python3 trace_valid.py --temp 0

# Full sweep
python3 trace_valid.py --temp 0 0.2 0.5 0.8 1.0

echo "=== Done ==="
