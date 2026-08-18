# 50 distinct problems, temperature 0.0 vs 0.2

First trace set in this repo that samples more than one problem.

**Every number below was recomputed from committed artifacts by
`results/recompute_stats.py`.** Run it to reproduce the whole document. Anything
that could not be derived from a committed file is marked `UNVERIFIED` and listed
in [UNRESOLVED](#unresolved).

*Audited 2026-08-18 on branch `audit/summary-n50-repair`. Findings, severities and
required fixes: `results/AUDIT_REPORT.md`. Method: `results/PHASE1_PIPELINE.md`,
`results/PHASE2_POSITIVES.md`, `results/BRANCH_COMPARISON.md`, `results/AUDIT_LOG.md`.*

---

## What this does NOT measure

Read this before the results, not after.

1. **Answer correctness is not measured at all.** Goedel-Prover emits a Lean
   proof, not a final answer, and FormalStep's `ground_truth` is the whole
   problem's answer, identical for every step of that problem. The requested
   valid/invalid × correct/incorrect cross-tab cannot be produced from this
   pipeline. The older code set `answer_correct = trace_valid and not has_sorry`,
   which is why `invalid_accuracy` was identically 0.0 — the second axis was
   derived from the first. **That field is still written by `trace_valid.py:97`**
   and should not be read as a measurement. No artifact behind the numbers below
   contains it (those runs used `generate`, not `run`).

2. **The positives were only partially audited by hand.** All 37 `valid` traces
   were checked mechanically; **10 of 37 (27%) were read in full** (random, seed
   `20260818`). Nothing below extrapolates the hand-read subset to the whole.

3. **The verifier never checks that the proved theorem is the target theorem.**
   It compiles `full_code` and classifies the result (`verify_traces.py:116-127`);
   there is no `isDefEq` or syntactic comparison against the dataset statement.
   *In fact the property holds* — the prompt ends mid-fence immediately after the
   dataset's `formal_statement`, so the model writes only a proof body, and this
   was verified on **50/50 traces at both temperatures** (statement present
   verbatim, exactly one declaration per file). But it holds by construction, not
   by check: an edit to `prompting.py` would void it silently with no test
   failing. See `results/PHASE1_PIPELINE.md` §1.

4. **A self-declared `axiom` would be scored `valid`.** Demonstrated live:
   `axiom cheat : 2+2=5` followed by `theorem t : 2+2=5 := by exact cheat`
   returns `valid` in 9 ms (`results/phase1_live_probe.json`). The verifier does
   not inspect axiom dependencies. **Measured impact on this run: zero** — no
   trace across all 100 declares an axiom. `sorry` and `admit` *are* both caught.

5. **`valid` on this sample mostly means ground arithmetic.** 26 of 37 positives
   (70%) close a decidable ground goal — 9 by a single decision/normalisation
   tactic, 17 by substitute-then-normalise. Only 11 use structural tactics. This
   is a property of FormalStep's first steps, not a verifier defect, but "74%
   valid" should not be read as 74% proof-search competence.

6. **One trajectory per sample.** Sound at T=0.0 (greedy is deterministic), but
   at T=0.2 a single sample per problem cannot separate model behaviour from
   sampling noise. See §5 — the design has no power to detect a temperature
   effect.

7. **Single topic.** FormalStep train is entirely "Counting & Probability" across
   all 500 problems. This is not a sample of mathematics generally.

8. **First step of each problem** — one fixed position in the CoT, not a sample
   over step depth.

---

## Artifacts

- Traces: `traces/temp0.0_n50_1each/`, `traces/temp0.2_n50_1each/` (+ `run_meta.json` each)
- Verification: `results/verify2_temp0.0.jsonl`, `results/verify2_temp0.2.jsonl`
- Analysis: `results/analysis_n50_corrected.json`; independently recomputed into
  `results/recomputed_stats.json` by `results/recompute_stats.py`
- Superseded verification: `results/verify_temp0.0.jsonl`, `results/verify_temp0.2.jsonl` — kept, do not mix (§6)

**Samples.** One CoT step from each of 50 *different* problems
(`distinct_problems`, stride 10 over the 500 problems in FormalStep train, first
step of each). Deterministic, no RNG. Both runs use the same 50 samples, so the
temperature comparison is **paired**.

---

## 1. Outcome distribution

Source: `results/verify2_temp0.{0,2}.jsonl` via `recompute_stats.py [1]`.

| outcome | T=0.0 | T=0.2 |
|---|---|---|
| `valid` | 37 | 37 |
| `compile_error` | 11 | 11 |
| `statement_error` | 2 | 2 |
| `has_sorry` | 0 | 0 |
| `empty_code` | 0 | 0 |
| `parse_failure` | 0 | 0 |
| `truncated generations` | **0** | **0** |
| `timeout` | 0 | 0 |
| `verifier_crash` | 0 | 0 |

**Validity rate, both temperatures:**

| denominator | rate | 95% CI (Wilson) |
|---|---|---|
| over traces that got a verdict (n=48) | **37/48 = 77%** | **63–87%** |
| over all traces (n=50) | **37/50 = 74%** | **60–84%** |

**The interval is ±12 points wide. Do not quote this to one decimal place.**
The earlier "74.0% / 77.1%" was false precision: at n=50 the data cannot
distinguish 74% from 65% or from 83%.

The two `statement_error` traces are excluded from the first denominator and are
**not** counted as invalid — Lean rejected the goal, so the model's proof was
never judged (§3). Both denominators are printed; the gap between them is the
uncertainty from untestable samples.

**Exclusion rule, stated once and applied everywhere:** a sample is *testable*
iff its outcome is a verdict on the model's proof, i.e. `outcome ∉
{statement_error, parse_failure, timeout, verifier_crash}`. An excluded sample
leaves **both** numerator and denominator. `maxRecDepth` is verifier
configuration, not an exclusion.

**Verification cost.** 33.0 s (T=0.0) and 37.7 s (T=0.2) summed over per-record
`seconds`; mean 0.66 s / 0.75 s, but the **median is under 50 ms** (30/50 and
28/50 records below 50 ms; min 9 ms; max 27.7 s on sample 44). The mean is
dragged by one outlier. Mathlib is imported once per process and snapshotted
(`verifier.py:184-227`), so per-record time excludes the import; all 100 records
ran in `shared_env` mode.

*That speed was checked, not assumed.* Negative controls against the same warm
environment fail correctly and just as fast: `(2:Nat)+2 = 5` → `compile_error`
in 107 ms, an unsolved goal in 15 ms, an unknown identifier in 4 ms
(`results/phase1_live_probe.json`). Mathlib was genuinely imported —
`lake-manifest.json` pins it at commit `81a5d257…`, and Lake reports 8656 build
jobs complete (`results/mathlib_build_evidence.log`).

**On the 42% → 74% jump from the old single-problem set: this is a HYPOTHESIS,
not a result.** The two sets are certainly not exchangeable — the old set is 50
consecutive steps of *one* problem with 10 trajectories each, the new set is 50
distinct problems with 1 each. But the stated mechanism does not hold up: median
`formal_statement` length is **95 chars (old) vs 103 chars (new)**, i.e. no
meaningful gap and, if anything, slightly *against* "first steps are easier". The
old set's dataset `state` labels were never recorded, so its provability mix
cannot be compared at all. No experiment holds the model fixed across matched
samples. Treat the sample-change explanation as plausible and untested.

---

## 2. Agreement with the dataset's provability label

**This section measures agreement between our verdict and FormalStep's `state`
field. It is not a false-positive rate.** A false positive requires ground truth
about *this proof*; `state` records whether FormalStep could prove the
*statement*, which is a different question with a different subject. The
false-positive framing has been removed rather than reworded.

```
T = 0.0 and T = 0.2 (identical)
                       Success of Proof   Failure of Proof   total
valid                                37                  0      37
not_valid                             1                 10      11
no_verdict                            1                  1       2
total                                39                 11      50
```

**We never returned `valid` for a statement the dataset could not prove: 0 of
10.** But a zero count from n=10 is weak evidence. The exact one-sided 95% upper
bound is **26%** (1 − 0.05^(1/10)) — the data are consistent with a true
disagreement rate anywhere from 0% to 26%. Note the denominator is **10, not 11**:
one of the 11 dataset-unprovable statements (sample 49) is a `statement_error`
and never received a verdict.

**The model failed 1 of 38 dataset-provable statements that received a verdict**
— 3%, 95% CI 0–13% (sample 35 at T=0.0; sample 0 at T=0.2). Down from 3 before
the fixes in §6: one was our Lean configuration and one was a broken dataset
statement.

---

## 3. Untestable samples

**2 of 50** at both temperatures — samples **19** (dataset-provable) and **49**
(dataset-unprovable), both `statement_error`, both "unexpected token 'in';
expected ','".

Consistent with the exclusion rule in §1: these two are removed from numerator
and denominator alike, giving n=48. **Sample 12 is not among them** — under the
corrected verifier it is testable and it *passes* (§6a), so counting it as
untestable would be wrong in the other direction.

**One further sample arguably belongs here.** Sample 17 is scored `valid`, but
its goal is literally `True`:

```
theorem test (digits: List ℕ) (h₀: List.length digits = 5)
  (h₁: digits = [2,2,2,3,7] ∨ digits = [2,2,2,3,9] ∨ digits = [2,2,2,7,9])
  : True := by
```

FormalStep ships it that way, its own `reference_proof` proves `True`, and it is
labelled `Success of Proof`. The trace is a real compiling proof of a vacuous
goal — it establishes nothing about the CoT step. **This is a dataset defect, not
a model cheat.** Treating it as untestable gives **36/47 = 77% (95% CI 63–87%)**,
i.e. **the headline does not move**; it changes what the headline means, not its
value. Only 1 such goal exists across all 37 positives (mechanically checked).

---

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
could not derive `False`. Substituting first would have evaluated it to 22100 and
closed the goal immediately.

Worth noting for the paper: **the natural-language reasoning in this trace is
correct.** Its own comment concludes "both are positive, confirming the theorem".
It simply never proves positivity — it asserts it and expects the tactics to
absorb it. Valid reasoning, invalid formalisation, which is precisely the gap
trace validity is meant to detect.

At T=0.2 the genuine failure is a different sample (**0**, `unsolved goals`), and
35 succeeds.

---

## 5. Temperature 0.0 vs 0.2, paired

Source: `recompute_stats.py [4]`.

| | n | samples |
|---|---|---|
| valid in both | 36 | |
| valid only at T=0.0 | 1 | **sample 0** |
| valid only at T=0.2 | 1 | **sample 35** |
| valid in neither | 12 | |

*(The previous version of this table had these two rows transposed, contradicting
§4 of this same document. Corrected against `verify2_temp0.{0,2}.jsonl`.)*

Outcome changed on **2 of 50** samples. Aggregate validity is identical (37/50 at
both temperatures, difference **+0.0 pp**) and the two flips cancel.

**McNemar's exact test on the discordant pairs (b=1, c=1): p = 1.000, n=2
discordant.**

**But the correct reading is "no power", not "no difference".** Only discordant
pairs carry information, and there are 2. An all-one-way split needs **n ≥ 6**
discordant pairs before two-sided p < 0.05 is attainable *at all*. With one
trajectory per sample at n=50, this design cannot detect the effect sizes at
issue. **p = 1.000 here is an absence of evidence, not evidence of absence.**
Distinguishing the two temperatures needs multiple trajectories per sample at
T>0, which this round deliberately did not run.

---

## 6. Two verifier defects found and fixed

Both were found by reading failures by hand, then demonstrated with controls
rather than argued. `tests/diagnose_statement_failures.py` reproduces all four
cases; it passes against the current verifier.

### 6a. `maxRecDepth` was never raised

The prompt header sets `maxHeartbeats 0` but says nothing about recursion depth,
so `Nat.choose 1996 4` exhausted Lean's default depth of 512 while unfolding and
was reported as `compile_error` — an environment limit dressed as a failed proof.

| case | outcome |
|---|---|
| statement + a correct proof, depth 512 | `compile_error` — "maximum recursion depth has been reached" |
| identical, at `LEAN_MAX_REC_DEPTH = 10000` | **`valid`** |

Same statement, same proof; only the option differs. Fixed by injecting the
option **at verification time** (`config.py:60`, applied at `verifier.py:281`).
Deliberately *not* added to `GOEDEL_LEAN4_HEADER`: that header is copied verbatim
from the model's official eval script and goes into the prompt, so changing it
would change what the model generates and make new traces incomparable.

### 6b. Statement rejections were scored as proof failures

Two statements do not parse on Mathlib v4.32.0 at all: FormalStep writes
`∑ n in Finset.range 6`, and Mathlib retired `in` for `∈` in big operators.

| case | outcome |
|---|---|
| statement as shipped, **model's proof replaced by `sorry`** | `statement_error` — "unexpected token 'in'; expected ','" |
| same statement, `in` → `∈`, still just `sorry` | `has_sorry` (parses) |

The first file contains **no model proof at all** and still fails, so that
outcome cannot be a verdict on the prover; the second differs by one character
and elaborates fine.

Fixed with a new outcome, `statement_error`. On a `compile_error`,
`verify_traces.py:134-144` re-verifies the statement alone with `sorry` as its
proof (`verifier.statement_is_broken()`); if that still fails, Lean rejected the
goal and the trace is recorded as `statement_error`. This is a re-verification,
not a regex over error text, so it generalises to any statement Lean will not
accept.

### Old and new numbers, side by side

Both verification passes are committed, so the effect of the fixes is auditable
without re-running anything:

| | superseded pass (`verify_temp*.jsonl`) | corrected pass (`verify2_temp*.jsonl`) |
|---|---|---|
| `valid` | 36 | **37** |
| `compile_error` | 14 | 11 |
| `statement_error` | — (outcome did not exist) | 2 |
| validity over all 50 | 72% (95% CI 58–83%) | **74% (95% CI 60–84%)** |
| validity over verdicts | 36/50 = 72% | **37/48 = 77% (63–87%)** |

Samples that moved, identical at both temperatures:
**12** `compile_error → valid` (the `maxRecDepth` fix),
**19** and **49** `compile_error → statement_error`.

The two intervals overlap almost completely. The fixes corrected a real
measurement bug; they did not produce a distinguishable change in the rate.

---

## Reproducibility

| item | value | status |
|---|---|---|
| Lean toolchain | `leanprover/lean4:v4.32.0` | ✅ committed (`lean_project/lean-toolchain`) |
| **Mathlib commit SHA** | **`81a5d257c8e410db227a6665ed08f64fea08e997`** | ✅ committed (`lean_project/lake-manifest.json`) |
| `lake-manifest.json` sha256 | `62bff1a7ce20e856be233dfcf82172d8efaf7f8b1f8cd9d6aa400fd494b46705` | ✅ committed |
| REPL | `v1.3.18_lean-toolchain-v4.32.0` | ✅ pinned in `config.py` |
| Transitive Lean deps | 7 of 9 declare floating `main`/`master`; resolved SHAs now captured in the manifest | ⚠️ pinned only via the manifest |
| Dataset | `liuchengwu/FormalStep` train, fingerprint `d5f1cb827b574582`, 30809 rows | ✅ in `run_meta.json` |
| Sampling seed | `0` (both runs); `top_p 0.95`, `do_sample true` at T=0.2; greedy at T=0.0 | ✅ in `run_meta.json` |
| `traces.jsonl` sha256 | T=0.0 `8ed9e7a287d5bc07…`, T=0.2 `f48dcc38a111f8c5…` | ✅ in `run_meta.json` |
| Key library versions | python 3.10.12, torch 2.7.0, transformers 4.46.3, datasets 3.6.0 | ✅ in `run_meta.json` |
| **Full `pip freeze`** | never captured | ❌ **UNRECOVERABLE** — instance terminated |
| **Generation commit SHA** | `run_meta.json` records `"git": {"sha": null, ...}` for **both** runs | ❌ **UNRECORDED** |

**On the generation SHA — read this before citing these traces.** Neither run
recorded a commit. The host ran from an uploaded tar archive with no `.git`, so
`git rev-parse` had nothing to answer with; to the code's credit it wrote `null`
rather than inventing a value. `traces/PROVENANCE.md:24-38` attributes the runs
by hand to `d857136` (T=0.0, clean tree) and, for T=0.2, to `3ec5361` *minus a
later hunk* — **a state that matches no commit in this repository**. That
attribution is the author's recollection, not a record, and the instance is
terminated so it can no longer be checked. Already mitigated for future runs:
`generate.py:62-93` now falls back to a `CODE_VERSION` file and records
`git.source`.

Hardware: Lambda Cloud `gpu_1x_a10` (NVIDIA A10, 22 GiB), ~7 min per run
(356 s / 368 s). Instance terminated after the run — **generation cannot be
re-run**.

---

## UNRESOLVED

Items the audit could not close within its budget, with what each would take.

1. **`verifier_crash` and `timeout` were never fired by any fixture.** The
   timeout probe (`decide` on `Nat.choose 100000 50000`) hit `maxRecDepth` and
   returned `compile_error` in 100 ms instead. Both branches exist and are
   correctly wired (`config.py:45`, `verifier.py:296-314`), but their *behaviour*
   is unverified. Related: `except TimeoutError` precedes `except Exception`, so
   a timeout raised as anything other than a `TimeoutError` — e.g.
   `subprocess.TimeoutExpired`, which is not one — would be filed as
   `verifier_crash`. *Would take: a fixture that kills the REPL process, plus one
   that blocks past 60 s without recursing. ~1 h.*

2. **Systematic vacuity check over all 37 positives.** Sample 17 (goal `True`)
   was caught mechanically, but sample 38's goal reduces to `600-486 = 600-486`
   after substituting its own hypotheses — a tautology caught only by reading.
   Scriptable against the local Mathlib build, no GPU. *~30 min. Expected to find
   between 1 and ~5 vacuous positives; would change what 74% means, not its
   value.*

3. **27 of 37 positives (73%) were not read by hand.** Mechanical checks rule out
   `restated` and `weakened` over the full 37 (statement verbatim 37/37, one
   declaration 37/37), so the residual risk is confined to subtle vacuity —
   item 2.

4. **§7's earlier claim that first steps are "measured as harder than the median
   step" (104 vs 66 chars, 11 vs 8 unprovable)** could not be reproduced from any
   committed artifact and has been **removed**, not reworded. *Would take: a dry
   run with `--step-selection median` over the same 50 problems. No GPU. ~15 min.*

5. **Statement-fidelity assertion is not in the pipeline.** The invariant holds
   50/50 but is unenforced. *Fix: ~6 lines in `verify_traces.py` emitting a
   `statement_mismatch` outcome. Not applied — it changes the verifier.*

6. **Axiom-dependency check is absent** (see "What this does not measure" #4).
   *Fix: assert the proved theorem's axioms ⊆ `{propext, Classical.choice,
   Quot.sound}` after a successful compile. Not applied.*

7. **The `answer_correct` field is still emitted** by `trace_valid.py:97`.
   *Fix: delete or rename. Not applied — it changes pipeline output.*

8. **README drift.** `README.md`'s outcome list omits `statement_error`, and its
   worked example writes and analyses `results/verify_temp0.0.jsonl` — the
   **superseded** pass. Following the documented commands reproduces 72%, not the
   74% above. *Fix: two one-line edits. Not applied — the second needs a decision
   on the canonical filename.*

9. **PR #10 shows superseded numbers.** `origin/merge/analysis-into-code-validity`
   is at `852aec7`; the two commits containing everything in §6 are unpushed.
   *Fix: push. The author's call.*

---

## Known gaps that remain by design

- **`statement_error` is measured, not fixed.** Samples 19 and 49 are still
  untestable against Mathlib v4.32.0. Rewriting `in` → `∈` in the dataset would
  recover them, but that edits the model's input and needs a decision.
- **A third malformed-statement flavour is unhandled by count.** Two failures
  report "Expected type must not contain free variables" — one declares `Finset`
  defaults in the binder list, the other references an identifier appearing
  nowhere in the statement. Both land on already-unprovable statements, so they
  change no total; `statement_is_broken()` would classify them if they ever
  landed on a provable one.
