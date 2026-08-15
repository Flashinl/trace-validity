#!/bin/bash
set -e

pip install -r requirements.txt
bash setup_lean.sh

for tool in lake lean elan; do
    ln -sf "$HOME/.elan/bin/$tool" "/usr/local/bin/$tool"
done

echo "=== Running experiment ==="
# Single temperature
#python3 trace_valid.py --temp 0

# Full sweep
#python3 trace_valid.py --temp 0 0.2 0.5 0.8 1.0

#check for validity
python3 verify_traces.py --input /traces.jsonl --temp 0 

echo "=== Done ==="
