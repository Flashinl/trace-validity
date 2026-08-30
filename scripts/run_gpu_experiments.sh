#!/bin/bash
# All three GPU experiments, in one sequence, on the generation host.
#
# Generation ONLY. Lean never runs here, so the instance can be terminated the
# moment the last line of this script completes.
#
# Every run writes its own run_meta.json (seed + generating commit SHA). Each
# experiment-1 arm gets its own DIRECTORY because generate.py writes the sidecar
# as <dirname>/run_meta.json -- two arms in one directory would silently
# overwrite each other's provenance, and the arms are byte-identical apart from
# the doc-comment slot, so nothing else would distinguish them.
set -u

cd "$(dirname "$0")/.." || exit 1
SEED="${SEED:?SEED must be set and recorded}"
LOG=~/run_all.log
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

say() { echo -e "\n=== $* ===" | tee -a "$LOG"; }
run() { echo "+ $*" | tee -a "$LOG"; "$@" 2>&1 | tee -a "$LOG"; }

say "seed=$SEED  commit=$(cat CODE_VERSION)  started $(date -u +%FT%TZ)"

# --------------------------------------------------------------------------- #
# Experiment 1 -- doc-comment ablation. T=0.0 greedy, paired, 1 trajectory.
# Arm A: informal_prefix is the current_step doc comment. Arm B: empty string.
# Two sets, reported separately and never pooled: n50 distinct (the set the
# live 74% headline is measured on) and the baseline 50-step set (where the
# motivating sample 27 lives, and 18 of whose 29 failures are statement_false).
# --------------------------------------------------------------------------- #
for SET in n50 baseline; do
  if [ "$SET" = n50 ]; then STRAT=distinct_problems; else STRAT=head; fi
  for ARM in A B; do
    if [ "$ARM" = A ]; then INF=(); else INF=(--no-informal); fi
    D="traces/exp1_${SET}_arm${ARM}"
    mkdir -p "$D"
    say "exp1 $SET arm$ARM (strategy=$STRAT informal=$([ "$ARM" = A ] && echo on || echo off))"
    run python3 trace_valid.py generate \
        --temp 0.0 --num-samples 50 --num-trajectories 1 \
        --sample-strategy "$STRAT" --seed "$SEED" \
        --out "$D/traces.jsonl" --resume "${INF[@]}"
  done
done

# --------------------------------------------------------------------------- #
# Experiment 2 -- best-of-n. k=16 at T=0.7.
# --------------------------------------------------------------------------- #
say "exp2 FormalStep n50 distinct, k=16, T=0.7"
mkdir -p traces/exp2_n50_k16
run python3 trace_valid.py generate \
    --temp 0.7 --num-samples 50 --num-trajectories 16 --traj-batch 16 \
    --sample-strategy distinct_problems --seed "$SEED" \
    --out traces/exp2_n50_k16/traces.jsonl --resume

say "exp2 Stage B n90, k=16, T=0.7"
run python3 tests/audit/gpu_recovery.py exp2-stageb \
    --k 16 --batch 16 --temp 0.7 --seed "$SEED" \
    --out results/exp2_stageb_k16.jsonl

# --------------------------------------------------------------------------- #
# Experiment 3 -- one error-feedback repair attempt, greedy, on the 104
# tactic_mismatch failures the tactic oracle ran on.
# --------------------------------------------------------------------------- #
say "exp3 error-feedback repair, 104 tactic_mismatch failures, T=0.0"
run python3 tests/audit/gpu_recovery.py exp3 \
    --temp 0.0 --seed "$SEED" --out results/exp3_repair.jsonl

say "ALL GENERATION COMPLETE $(date -u +%FT%TZ)"
touch ~/GENERATION_COMPLETE
