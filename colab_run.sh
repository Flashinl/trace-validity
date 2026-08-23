#!/bin/bash
# Quick start for Colab / a fresh Linux GPU box.
set -e

# Was `pip install --upgrade lean_interact`, which defeats the whole point of
# pinning: upgrading to whatever is newest is how this project ended up with
# transformers 5.x and a model that would not import. Install the pinned set.
pip install -r requirements.txt

bash setup_lean.sh

# elan puts lake/lean/elan on PATH via the shell profile, which Colab cells do
# not source. verifier.py also prepends ~/.elan/bin at import, but the symlinks
# make the binaries work from a bare `!lake` cell too.
for tool in lake lean elan; do
    ln -sf "$HOME/.elan/bin/$tool" "/usr/local/bin/$tool"
done

echo "=== Generating traces (GPU, no Lean) ==="
# Was `trace_valid.py --temp 0 0.2 0.5 0.8 1.0`, which no longer parses: the CLI
# takes a subcommand, and that invocation also launched a five-temperature
# generate+verify sweep by default. Generation and verification are separate
# steps on purpose, so run them separately and start with one temperature.
python3 trace_valid.py generate --temp 0 --num-samples 50 --num-trajectories 1

echo "=== Verifying in Lean (no GPU) ==="
python3 verify_traces.py \
    --traces traces/temp0.0_n50_1each/traces.jsonl \
    --out results/verify_temp0.0.jsonl --all

echo "=== Analysis ==="
python3 analyze_runs.py results/verify_temp0.0.jsonl \
    --meta traces/temp0.0_n50_1each/run_meta.json

echo "=== Done ==="
# For a sweep, add temperatures to the generate step (the model is loaded once)
# and verify each run directory:
#   python3 trace_valid.py generate --temp 0 0.2 0.5 --seed 0 \
#       --num-samples 50 --num-trajectories 1
