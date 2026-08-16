# Trace provenance

Each run directory carries its own `run_meta.json`, written by the run itself.
This file records only what the runs could not record about themselves, and is
written by hand after the fact — treat `run_meta.json` as the primary record and
this as an annotation on it.

## Runs

| Run | Records | Temp | Seed | top_p | traces.jsonl sha256 | Status |
|---|---|---|---|---|---|---|
| `temp0.0_n50_1each` | 50 | 0.0 (greedy) | 0 | n/a | `8ed9e7a287d5bc07…` | complete |
| `temp0.2_n50_1each` | 50 | 0.2 | 0 | 0.95 | `f48dcc38a111f8c5…` | complete |

Both runs use the **same 50 samples**: `distinct_problems`, stride 10, first step
of each — one CoT step from each of 50 different problems, selected
deterministically (no RNG). The temperature comparison is therefore paired.

Generated 2026-08-15 on a Lambda Cloud `gpu_1x_a10` (NVIDIA A10, 22 GiB),
Goedel-LM/Goedel-Prover-SFT, torch 2.7.0 / transformers 4.46.3 / datasets 3.6.0.
The instance was terminated after the run.

## Why `git.sha` is null in both sidecars

The generation host ran from an uploaded tar archive with no `.git`, so
`git rev-parse` had nothing to answer with and `git_state()` recorded
`sha: null` rather than inventing one. The code that actually ran was:

- **temp0.0** — `git archive HEAD` of commit **d857136**
  ("Record every run config in run_meta.json; one run directory per config"),
  clean tree.
- **temp0.2** — the same archive with `generate.py` replaced by the version that
  loads the model once per process. That change is now committed as **3ec5361**;
  the file on the host was 3ec5361 *without* its later `git_state()` /
  CODE_VERSION hunk, which was written after this run had already started. The
  sampling, record-building and metadata paths were identical to 3ec5361.

Nothing else on the host was modified between the two runs.

**This will not recur.** `git_state()` now falls back to a `CODE_VERSION` file
written at deploy time, and records `git.source` so a SHA read from a file is
never mistaken for a live repository check. See the deploy snippet in the README.

## Relationship to `traces/temp_0.jsonl`

`temp_0.jsonl` (500 records, committed earlier) is **not** comparable to these
runs and is kept only as the historical baseline. Its 50 "samples" are 50
consecutive CoT steps of a single problem
(`math_train_counting_and_probability_408`, ground_truth `101`), because the
loader took the first 50 rows of a dataset that is ordered by problem. Its 10
trajectories per sample are byte-identical (measured 50/50) since temperature 0
is greedy. It also has no metadata sidecar; its config was reconstructed by
reading the records, which is what motivated `run_meta.json`.
