# 50 distinct problems, temperature 0.0 vs 0.2

First trace set in this repo that samples more than one problem. All numbers
below come from real runs; nothing is estimated.

- Traces: `traces/temp0.0_n50_1each/`, `traces/temp0.2_n50_1each/` (+ `run_meta.json` each)
- Verification: `results/verify_temp0.0.jsonl`, `results/verify_temp0.2.jsonl`
- Analysis: `results/analysis_n50_distinct.json`, reproduced by `analyze_runs.py`
- Generation: Lambda A10, ~7 min per run, instance terminated after
- Verification: Lean 4.32.0, Mathlib `v4.32.0`, REPL `v1.3.18_lean-toolchain-v4.32.0`

**Samples.** One CoT step from each of 50 *different* problems
(`distinct_problems`, stride 10 over the 500 problems in FormalStep train, first
step of each). Deterministic, no RNG. Both runs use the same 50 samples, so the
temperature comparison is paired. The previous set — `traces/temp_0.jsonl` — was
50 consecutive steps of one problem, so its rates are not comparable to these.

## 1. Outcome distribution

| outcome | T=0.0 | T=0.2 |
|---|---|---|
| `valid` | 36 (72.0%) | 36 (72.0%) |
| `compile_error` | 14 (28.0%) | 14 (28.0%) |
| `has_sorry` | 0 | 0 |
| `empty_code` | 0 | 0 |
| `parse_failure` | 0 | 0 |
| `timeout` | 0 | 0 |
| `verifier_crash` | 0 | 0 |

**Validity rate 36/50 = 72.0% at both temperatures.** No trace failed to produce
a verdict, so the rate over verdicts and the rate over all traces coincide; there
is no denominator ambiguity to disclose in this run. 50 verifications in 26.5s
(0.53s each) per run.

The old single-problem set scored 42% valid. The jump to 72% is a change of
sample, not an improvement in the model — 50 first-steps of different problems
are easier than 50 consecutive steps deep inside one problem.

## 2. Trace validity x dataset provability

The dataset's `state` field says whether FormalStep could prove the *statement*.
That is a different question from whether *this model's proof* compiles, and it
is the closest available second axis — see §5.

```
T = 0.0                Success of Proof   Failure of Proof   total
valid                                36                  0      36
not_valid                             3                 11      14
no_verdict                            0                  0       0
total                                39                 11      50
```

T = 0.2 gives the identical table.

**Zero false positives at both temperatures.** We never returned `valid` for a
statement the dataset could not prove — the direction that would most damage the
paper. All 11 unprovable statements were rejected.

## 3. The 3 provable statements we failed are mostly not model failures

Read all of them by hand. Only one is the model's fault.

| sample | T=0.0 | T=0.2 | mechanism |
|---|---|---|---|
| 12 | fail | fail | **Lean limit, not a proof error.** `maximum recursion depth has been reached` elaborating `Nat.choose 1996 4`. Our header sets `maxHeartbeats 0` but never raises `maxRecDepth`. |
| 19 | fail | fail | **The dataset statement does not parse on our Mathlib.** `unexpected token 'in'; expected ','` — the statement uses `∑ n in Finset.range k`, the pre-v4.32 big-operator syntax, which now requires `∑ n ∈ …`. The model never had a well-formed goal. |
| 35 | fail | valid | Genuine: `linarith failed to find a contradiction`. |
| 0 | valid | fail | Genuine (the T=0.2 flip; see §4). |

So at T=0.0 the model genuinely failed **1 of 39** provable statements, not 3.
Sample 49 (an unprovable statement) also fails to parse for the same
big-operator reason, so **2 of 50 samples in this set are untestable against
Mathlib v4.32.0** — their outcome says something about dataset/Mathlib version
skew, not about the prover.

This is a false-negative mechanism not present in the earlier single-problem
run, which is precisely why sampling one problem hid it. Neither case is
currently distinguished from a real `compile_error` by the taxonomy.

## 4. Temperature 0.0 vs 0.2, paired

| | n |
|---|---|
| valid in both | 35 |
| valid only at T=0.0 | 1 (sample 0) |
| valid only at T=0.2 | 1 (sample 35) |
| valid in neither | 13 |

**Outcome changed on 2 of 50 samples.** Aggregate validity is identical (36/50)
and the two flips cancel. With n=50 and one trajectory per sample this is well
inside noise: nothing here supports a claim that temperature 0.2 differs from
greedy decoding. Distinguishing them needs multiple trajectories per sample at
T>0, which this round deliberately did not run.

## 5. Answer correctness is still not measured

The requested valid/invalid x correct/incorrect cross-tab cannot be produced from
this pipeline, and §2 is not a substitute for it. Goedel-Prover emits a Lean
proof, not a final answer; FormalStep's `ground_truth` is the whole problem's
answer and is identical for every step of that problem. The previous code set
`answer_correct = trace_valid and not has_sorry`, which is why `invalid_accuracy`
was identically 0.0 — the second axis was derived from the first. It has not
been silently redefined. Getting a real answer axis needs a separate solver
producing final answers per problem, which is its own round of work.

## 6. Known gaps — do not report these as done

- **`maxRecDepth` is not raised** in the Lean header, so a statement can fail for
  elaboration budget rather than mathematics (sample 12). One-line change, but it
  changes previously reported numbers, so it is not being made mid-analysis.
- **2 of 50 statements do not parse on Mathlib v4.32.0** (samples 19, 49) and are
  currently counted as `compile_error`. They deserve their own outcome; a trace
  whose *goal* does not parse was never a test of the prover.
- **One trajectory per sample.** Valid at T=0.0 (greedy is deterministic), but at
  T=0.2 a single sample per problem cannot separate model behaviour from
  sampling noise. The two flips in §4 are the whole temperature signal.
- **Single topic.** FormalStep train is entirely "Counting & Probability" across
  all 500 problems, so this is not a sample of mathematics generally.
- **First step of each problem.** Measured as harder than the median step
  (median statement 104 vs 66 chars, 11 vs 8 unprovable in 50), but it is still
  one fixed position in the CoT, not a sample over step depth.
- **`verifier_crash` remains untested** — no fixture exercises it.
- The 35 valid-in-both traces were not read by hand. Sample 15 of the earlier run
  showed a proof can be mathematically complete and still `compile_error` over a
  trailing no-op tactic; the converse case (compiles, proves less than it
  appears) has not been audited here.
