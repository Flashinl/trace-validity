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
   derived from the first. **That field has now been deleted at source**
   (`trace_valid.py`), along with the `valid_accuracy` / `invalid_accuracy` /
   `overall_accuracy` metrics in `analysis.py` that were computed from it and the
   2x2 chart that plotted it. No artifact behind the numbers below ever contained
   it. There is no answer axis; do not re-add a placeholder for one.

2. **The positives were only partially audited by hand.** All 37 `valid` traces
   were checked mechanically; **10 of 37 (27%) were read in full** (random, seed
   `20260818`). Nothing below extrapolates the hand-read subset to the whole.

3. **The proved theorem IS the target theorem — now checked, not assumed.** The
   verifier used to compile `full_code` without ever comparing it to the dataset
   statement; the property held only because the prompt ends mid-fence
   immediately after `formal_statement`. It is now asserted per record
   (`verify_traces.statement_mismatch()`, outcome `statement_mismatch`):
   statement present verbatim, exactly one declaration. **Measured 50/50 at both
   temperatures; 0 mismatches.**

4. **No proof stands on an untrusted axiom — now checked, not assumed.** The
   verifier previously accepted `axiom cheat : 2+2=5` + `exact cheat` as `valid`
   in 9 ms. It now asks Lean (`#print axioms`) after every clean compile and
   rejects anything outside `{propext, Classical.choice, Quot.sound}` as
   `unsound_axioms` (`verifier._axiom_audit()`). **All 37 positives audited at
   both temperatures; 0 rejections.** The observed dependency sets:

   | axioms the proof stands on | T=0.0 | T=0.2 |
   |---|---|---|
   | none at all | 10 | 8 |
   | `propext` | 17 | 17 |
   | `propext, Classical.choice, Quot.sound` | 10 | 11 |
   | `propext, Quot.sound` | 0 | 1 |
   | **outside the trusted set** | **0** | **0** |

   This is stronger than the earlier "no `axiom` keyword found": Lean reports the
   real transitive dependency set, so it also catches an axiom pulled in through
   a lemma.

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
- **Verification (canonical): `results/verify3_temp0.0.jsonl`, `results/verify3_temp0.2.jsonl`**
  — produced by the hardened verifier (axiom audit, statement-fidelity check,
  fail-closed classification)
- Analysis: `results/analysis_n50_corrected.json`; independently recomputed into
  `results/recomputed_stats.json` by `results/recompute_stats.py`
- Earlier passes, kept but **do not mix** (§6): `verify2_temp0.{0,2}.jsonl`
  (before the audit hardening — identical outcomes), `verify_temp0.{0,2}.jsonl`
  (before the `maxRecDepth`/`statement_error` fixes — 36/50)

**Samples.** One CoT step from each of 50 *different* problems
(`distinct_problems`, stride 10 over the 500 problems in FormalStep train, first
step of each). Deterministic, no RNG. Both runs use the same 50 samples, so the
temperature comparison is **paired**.

---

## 1. Outcome distribution

Source: `results/verify3_temp0.{0,2}.jsonl` via `recompute_stats.py [1]`.
Identical to the `verify2` pass: the audit hardening changed no outcome.

| outcome | T=0.0 | T=0.2 |
|---|---|---|
| `valid` | 37 | 37 |
| `compile_error` | 11 | 11 |
| `statement_error` | 2 | 2 |
| `has_sorry` | 0 | 0 |
| `empty_code` | 0 | 0 |
| `parse_failure` | 0 | 0 |
| `statement_mismatch` | 0 | 0 |
| `unsound_axioms` | 0 | 0 |
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
{statement_error, statement_mismatch, parse_failure, timeout, verifier_crash}`.
An excluded sample leaves **both** numerator and denominator. `maxRecDepth` is
verifier configuration, not an exclusion. Note `unsound_axioms` is deliberately
**not** on that list — a file that compiled was judged, and leaning on a
self-declared axiom is a failed attempt, not an untestable sample.

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

## Fixed during the audit

Each of these was a defect in the pipeline, not the prose. All were applied and
then **re-verified against all 100 traces**, which produced
`results/verify3_temp0.{0,2}.jsonl`: **outcome-for-outcome identical to the
previous pass.** The hardening changed nothing about this result; it changes what
the next run can be trusted to report.

| fix | where | effect on this run |
|---|---|---|
| Axiom audit — `#print axioms` after every clean compile, rejecting anything outside `{propext, Classical.choice, Quot.sound}` as `unsound_axioms` | `verifier._axiom_audit()` | 0 rejections; all 37 positives verified within the trusted set at both temperatures |
| Statement-fidelity assertion — statement verbatim + exactly one declaration, else `statement_mismatch` | `verify_traces.statement_mismatch()` | 0 mismatches |
| **Fail closed** — `VALID` is no longer the bare `else`; a response with no messages *and* no environment is now `verifier_crash`, not a proved theorem | `verifier._classify()` | no change (responses were populated throughout) |
| `answer_correct` and the three fake accuracy metrics deleted at source | `trace_valid.py`, `analysis.py` | none — no artifact here contained the field |
| `parser.has_sorry` renamed `has_sorry_literal`, so the naive regex flag cannot be mistaken for the verifier's structural `has_sorry` outcome | `parser.py` | none |
| README: documents all 10 outcomes, distinguishes verdict from non-verdict, and names which verification pass is canonical | `README.md` | none |

Regression check on the hardened verifier (`results/phase1_live_probe.json`):
the axiom fixture now returns `unsound_axioms` — "proof depends on untrusted
axiom(s): cheat" — where it previously returned `valid`, and the other 12
fixtures are unchanged.

---

## UNRESOLVED

Items the audit could not close, with what each would take.

1. **A natural `timeout` is close to unreachable, and that is now understood
   rather than fixed.** `LEAN_MAX_REC_DEPTH = 10000` bounds runaway elaboration
   before the 60 s wall clock can expire — the heavy-`decide` probe returned
   `compile_error` in 208 ms. The classification path is exercised by
   `tests/audit/phase1_deadbranches.py` (see `results/phase1_deadbranches.json`),
   but no *organic* timeout has ever been observed. Related risk, still open:
   `except TimeoutError` precedes `except Exception`, so a timeout raised as
   anything else — `subprocess.TimeoutExpired` is not a `TimeoutError` — would be
   filed as `verifier_crash`.

2. **Systematic vacuity check over all 37 positives.** Sample 17 (goal `True`)
   was caught mechanically, but sample 38's goal reduces to `600-486 = 600-486`
   after substituting its own hypotheses — a tautology caught only by reading.
   Scriptable against the local Mathlib build, no GPU. *~30 min. Expected to find
   1–5 vacuous positives; would change what 74% means, not its value.*

3. **27 of 37 positives (73%) were not read by hand.** Mechanical checks rule out
   `restated` and `weakened` over the full 37, so the residual risk is confined
   to subtle vacuity — item 2.

4. **The earlier §7 claim that first steps are "measured as harder than the
   median step" (104 vs 66 chars, 11 vs 8 unprovable)** could not be reproduced
   from any committed artifact and was **removed**, not reworded. *Would take: a
   dry run with `--step-selection median` over the same 50 problems. No GPU,
   ~15 min.*

5. **Generation cannot be re-run.** One trajectory per sample at T>0, the
   unrecorded generation SHA, and the missing `pip freeze` all need a GPU host
   that no longer exists.

6. **PR #10 still shows superseded numbers.** `origin/merge/analysis-into-code-validity`
   is at `852aec7` (36/50 = 72%); everything above is unpushed. *Fix: push.*

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
