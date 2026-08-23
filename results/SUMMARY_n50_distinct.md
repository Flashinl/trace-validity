# 50 distinct problems, temperature 0.0 vs 0.2

First trace set in this repo that samples more than one problem. All numbers
below come from real runs; nothing is estimated.

- Traces: `traces/temp0.0_n50_1each/`, `traces/temp0.2_n50_1each/` (+ `run_meta.json` each)
- Verification: `results/verify2_temp0.0.jsonl`, `results/verify2_temp0.2.jsonl`
- Analysis: `results/analysis_n50_corrected.json`, reproduced by `analyze_runs.py`
- Generation: Lambda A10, ~7 min per run, instance terminated after
- Verification: Lean 4.32.0, Mathlib `v4.32.0`, REPL `v1.3.18_lean-toolchain-v4.32.0`

**Samples.** One CoT step from each of 50 *different* problems
(`distinct_problems`, stride 10 over the 500 problems in FormalStep train, first
step of each). Deterministic, no RNG. Both runs use the same 50 samples, so the
temperature comparison is paired. The previous set — `traces/temp_0.jsonl` — was
50 consecutive steps of one problem, so its rates are not comparable to these.

**Supersedes an earlier verification pass.** `results/verify_temp0.0.jsonl` and
`verify_temp0.2.jsonl` are kept, but two verifier defects were fixed after them
and the numbers below come from the re-run (§3). Do not mix the two.

## 1. Outcome distribution

| outcome | T=0.0 | T=0.2 |
|---|---|---|
| `valid` | 37 (74.0%) | 37 (74.0%) |
| `compile_error` | 11 (22.0%) | 11 (22.0%) |
| `statement_error` | 2 (4.0%) | 2 (4.0%) |
| `has_sorry` / `empty_code` / `parse_failure` / `timeout` / `verifier_crash` | 0 | 0 |

**Validity rate: 37/48 = 77.1%** over traces that got a verdict, or 37/50 =
74.0% over all traces. The two `statement_error` traces are excluded from the
first denominator and are *not* counted as invalid — Lean rejected the goal, so
the model's proof was never judged (§3). Both denominators are always printed;
the gap between them is the uncertainty.

50 verifications in 33.5s (T=0.0) and 38.0s (T=0.2), ~0.7s each.

The old single-problem set scored 42% valid. The jump is a change of sample, not
an improvement in the model — 50 first-steps of different problems are easier
than 50 consecutive steps deep inside one problem.

## 2. Trace validity x dataset provability

The dataset's `state` field says whether FormalStep could prove the *statement*.
That is a different question from whether *this model's proof* compiles, and it
is the closest available second axis — see §6.

```
T = 0.0                Success of Proof   Failure of Proof   total
valid                                37                  0      37
not_valid                             1                 10      11
no_verdict                            1                  1       2
total                                39                 11      50
```

T = 0.2 gives the identical table.

**Zero false positives at both temperatures.** We never returned `valid` for a
statement the dataset could not prove — the direction that would most damage the
paper. Every one of the 10 unprovable statements that got a verdict was
rejected.

**The model failed exactly 1 provable statement**, down from 3 before the fixes
in §3 — one of the other two was our Lean configuration and one was a broken
dataset statement.

## 3. Two verifier defects found and fixed

Both were found by reading failures by hand, then demonstrated with controls
rather than argued. `tests/diagnose_statement_failures.py` reproduces all four
cases; it passes against the current verifier.

### 3a. `maxRecDepth` was never raised

The prompt header sets `maxHeartbeats 0` but says nothing about recursion depth,
so `Nat.choose 1996 4` exhausted Lean's default depth of 512 while unfolding and
was reported as `compile_error` — an environment limit dressed as a failed
proof.

| case | outcome |
|---|---|
| statement + a correct proof, depth 512 | `compile_error` — "maximum recursion depth has been reached" |
| identical, at `LEAN_MAX_REC_DEPTH = 10000` | **`valid`** |

Same statement, same proof; only the option differs. Fixed by injecting the
option **at verification time** (`config.LEAN_MAX_REC_DEPTH`). Deliberately not
added to `GOEDEL_LEAN4_HEADER`: that header is copied verbatim from the model's
official eval script and goes into the prompt, so changing it would change what
the model generates and make new traces incomparable with existing ones.

Effect: sample 12 went `compile_error` -> `valid`, which is the entire
difference between the old 36/50 and the new 37/50.

### 3b. Statement rejections were scored as proof failures

Two statements do not parse on Mathlib v4.32.0 at all: FormalStep writes
`∑ n in Finset.range 6`, and Mathlib retired `in` for `∈` in big operators.

| case | outcome |
|---|---|
| statement as shipped, **model's proof replaced by `sorry`** | `statement_error` — "unexpected token 'in'; expected ','" |
| same statement, `in` -> `∈`, still just `sorry` | `has_sorry` (parses) |

The first file contains **no model proof at all** and still fails, so that
outcome cannot be a verdict on the prover; the second differs by one character
and elaborates fine.

Fixed with a new outcome, `statement_error`. On a `compile_error`,
`verify_traces.py` re-verifies the statement alone with `sorry` as its proof
(`verifier.statement_is_broken()`); if that still fails, Lean rejected the goal
and the trace is recorded as `statement_error` with the Lean message. This is a
re-verification, not a regex over error text, so it generalises to any statement
Lean will not accept rather than just this one syntax change.

`statement_error` counts as *no verdict*, alongside `timeout`, `verifier_crash`
and `parse_failure`. Scoring it against the prover would measure the dataset's
compatibility with our Mathlib version.

Affected: samples 19 (provable) and 49 (unprovable), at both temperatures.

## 4. The one genuine model failure

**Sample 35, T=0.0.** Goal: given `total_ways = C(52,3)` and
`spade_ways = C(13,3)`, show both are `> 0`.

```lean
constructor
all_goals norm_num [Nat.choose_pos, Nat.choose_pos] at h₀ h₁ ⊢
<;> linarith
```
```
linarith failed to find a contradiction
h₀ : total_ways = choose 52 3
a✝ : total_ways ≤ 0
⊢ False
```

It normalised *the hypotheses* instead of rewriting the goal with them, so
`linarith` was left with `choose 52 3` as an opaque atom of unknown sign and
could not derive `False`. Substituting first would have evaluated it to 22100
and closed the goal immediately.

Worth noting for the paper: **the natural-language reasoning in this trace is
correct.** Its own comment concludes "both are positive, confirming the
theorem". It simply never proves positivity — it asserts it and expects the
tactics to absorb it. Valid reasoning, invalid formalisation, which is precisely
the gap trace validity is meant to detect.

At T=0.2 the genuine failure is a different sample (0, `unsolved goals`), and 35
succeeds.

## 5. Temperature 0.0 vs 0.2, paired

| | n |
|---|---|
| valid in both | 36 |
| valid only at T=0.0 | 1 (sample 35) |
| valid only at T=0.2 | 1 (sample 0) |
| valid in neither | 12 |

**Outcome changed on 2 of 50 samples.** Aggregate validity is identical (37/50)
and the two flips cancel. With n=50 and one trajectory per sample this is well
inside noise: nothing here supports a claim that temperature 0.2 differs from
greedy decoding. Distinguishing them needs multiple trajectories per sample at
T>0, which this round deliberately did not run.

## 6. Answer correctness is still not measured

The requested valid/invalid x correct/incorrect cross-tab cannot be produced from
this pipeline, and §2 is not a substitute for it. Goedel-Prover emits a Lean
proof, not a final answer, and FormalStep's `ground_truth` is the whole problem's
answer, identical for every step of that problem. The previous code set
`answer_correct = trace_valid and not has_sorry`, which is why `invalid_accuracy`
was identically 0.0 — the second axis was derived from the first. It has not
been silently redefined. Getting a real answer axis needs a separate solver
producing final answers per problem, which is its own round of work.

## 7. Known gaps — do not report these as done

- **One trajectory per sample.** Valid at T=0.0 (greedy is deterministic), but at
  T=0.2 a single sample per problem cannot separate model behaviour from
  sampling noise. The two flips in §5 are the whole temperature signal.
- **Single topic.** FormalStep train is entirely "Counting & Probability" across
  all 500 problems, so this is not a sample of mathematics generally.
- **First step of each problem.** Measured as harder than the median step
  (median statement 104 vs 66 chars, 11 vs 8 unprovable in 50), but it is still
  one fixed position in the CoT, not a sample over step depth.
- **`statement_error` is measured, not fixed.** The two affected statements are
  still untestable against Mathlib v4.32.0. Rewriting `in` -> `∈` in the dataset
  would recover them, but that edits the model's input and needs a decision.
- **A third malformed-statement flavour is unhandled by count.** Two failures
  report "Expected type must not contain free variables" — one declares `Finset`
  defaults in the binder list, the other references an identifier that appears
  nowhere in the statement. Both land on already-unprovable statements, so they
  change no total; `statement_is_broken()` would classify them if they ever land
  on a provable one.
- **`verifier_crash` remains untested** — no fixture exercises it.
- The 36 valid-in-both traces were not read by hand. Sample 15 of the earlier run
  showed a proof can be mathematically complete and still `compile_error` over a
  trailing no-op tactic; the converse case (compiles, proves less than it
  appears) has not been audited here.
