# Autoformalization noise as a rate

What §2.2 promises to quantify rather than assume away: of the verification
failures we report, what fraction are verdicts on the model's reasoning at all.

Two formalization pipelines are measured separately, because they are different
pipelines and they behave differently. **No figure here may be placed beside a
figure from the other set.**

- **FormalStep** — steps of Chain-of-Thought traces, autoformalized upstream by
  the dataset authors. Verification pass `results/verify3_temp0.0.jsonl`.
- **NuminaMath Stage B** — competition problems with Kimina-formalized
  statements, our own eval set of 90. Verification pass
  `results/stage_b_verified.jsonl`.

Every rate below carries its denominator. Wilson 95% intervals throughout.

---

## 1. The categories, and why two are not enough

The task was scoped as translation noise vs. dataset error. Measuring it showed
that split is not exhaustive, and the missing category is the largest one.

| category | what it means | whose fault |
|---|---|---|
| **translation noise** | the formalization is not a faithful or even well-formed rendering of the informal step | the autoformalizer |
| **dataset-intended negative** | the step is a *failed* CoT step and the dataset labels it so | nobody — this is FormalStep working as designed |
| **harness artifact** | our prompt or extraction, not the model or the data | us |
| **genuine proof failure** | the goal is well-formed and provable, and the model did not prove it | the model |

FormalStep carries failed proof steps deliberately. Its `state` field labels
each row `Success of Proof` or `Failure of Proof`, and 11 of our 50 sampled rows
are the latter. Counting those as autoformalization noise would inflate the
noise rate with rows where the dataset is behaving correctly and the model is
behaving correctly.

---

## 2. FormalStep — 13 failures of 50, at T=0.0

```
                                                    n/13    rate     95% CI
translation noise (Lean rejects the statement)      2/13    15.4%   [ 4-42%]
dataset-intended negative (state=Failure of Proof) 10/13    76.9%   [50-92%]
genuine proof-side failure on a provable row        1/13     7.7%   [ 1-33%]
                                                   -----
not a verdict on the model's reasoning             12/13    92.3%   [67-99%]
```

**Of 13 failures, 12 (92.3%, [67–99%]) are not verdicts on the model's
reasoning.** T=0.2 gives the identical split; only the identity of the single
genuine failure moves (sample 35 at T=0.0, sample 0 at T=0.2).

### The translation-noise rows are syntactic, not semantic

Samples 19 and 49 both fail with `unexpected token 'in'; expected ','` — Lean
will not parse the statement under our pinned Mathlib v4.32.0. These are the two
rows `denominators.json` calls `untestable`. They are formalization output that
is not well-formed Lean, which is the cleanest possible case of translation
noise.

These are **not** timeouts. That distinction is load-bearing and is the subject
of §4 below.

### The false-goal rows are inside the dataset-negative category, not beside it

Four failures (samples 5, 7, 16, 36) carry a goal that Lean can parse and that
is mathematically **false**. All four are on rows the dataset labels
`Failure of Proof`. Reading them against their informal steps shows three
distinct mechanisms, and only one is dataset error:

| sample | informal step | formal statement | mechanism |
|---|---|---|---|
| 5 | "probability of rolling a non-1 is 5/6" | `5 / 6 = 1 - 1 / 6` | **type error**: true over ℚ, formalized over ℕ, where it reads `0 = 1` |
| 7 | "Given expression: 11!/(9! + 2·8!)" — asserts nothing | `11!/(9!+2*8!) = 11*10/(9+2)` | **fabrication**: the formalizer invented an equation and dropped a factor (truth 90, claim 10) |
| 36 | "let's break it down step by step" — asserts nothing | `(6! + 7!)/5! = 8` | **fabrication**: truth 48, claim 8 |
| 16 | "there are 36 unit cubes with no painted faces" (a 4×4×4 cube has 8) | `total - interior = 36` | **dataset error**: the informal step is itself false |

So within the four: **three are translation noise** (one type error, two
fabrications from an informal step that makes no claim) and **one is dataset
error**. They are counted in the dataset-negative row above because the dataset
independently labels all four as failed steps; splitting them out would
double-count.

### The negative control passes

The model never proved a step the dataset labels a failure — at either
temperature.

```
                          our valid   our failure
dataset Success of Proof     37            2          (n=39)
dataset Failure of Proof      0           11          (n=11)
```

**0 of 11, both temperatures.** Zero-event upper bound ≤ 23.8%. On the rows the
dataset says are provable, the pass rate is 37/38 = 97.4% [87–100%] (excluding
the one untestable row).

This is the negative control, and it passes. It says the checker is sound: it
does not certify invalid steps. Read together with §3 of `CONTENTLESS_STEPS.md`,
the picture is a sound checker applied to a unit that carries very little
information.

---

## 3. NuminaMath Stage B — 62 failures of 90

```
                                                    n/62    rate     95% CI
statement-attributable (after the repair in §4)     0/62     0.0%   [ 0- 6%]
no Lean verdict: timeout                            6/62     9.7%   [ 5-20%]
no Lean verdict: parse_failure (truncation)         4/62     6.5%   [ 3-15%]
harness artifact: prompt ends at `:=`               2/62     3.2%   [ 1-11%]
                                                   -----
not a verdict on the model's reasoning             12/62    19.4%   [11-31%]
```

**Of 62 failures, 12 (19.4%, [11–31%]) are not verdicts on the model's
reasoning** — and **zero** of them are attributable to the statement.
Zero-event upper bound on statement-attributable failures: **≤ 4.7%**.

### The rates differ substantially between pipelines, and that is the finding

| | FormalStep | Stage B |
|---|---|---|
| failures | 13/50 | 62/90 |
| not a verdict on the model's reasoning | **92.3%** [67–99%] | **19.4%** [11–31%] |
| statement-attributable | 15.4% [4–42%] | **0.0%** [0–6%] |

The intervals do not overlap. Kimina-formalized competition statements survive a
pinned Mathlib elaboration essentially intact; FormalStep's step-level
autoformalization does not, and FormalStep additionally carries deliberate
negatives that dominate its failure set.

The practical consequence for the paper: a failure rate measured on FormalStep
is mostly not a measurement of the prover. On Stage B it mostly is.

### The harness artifact

Six of the 90 Stage B statements end `:=` rather than `:= by`, so the
prefix-completion prompt hands the model a **term-mode** position. Four
recovered by emitting `by` themselves. Two did not — they wrote a doc comment
and then tactic syntax, which Lean read as term-level identifiers:

```
076e5357   errors[0] = Unknown identifier `use`
08e7648a   errors[0] = Unknown identifier `refine'`
```

The tactic scripts are syntactically fine; tactic mode was never opened. This is
our bug, not the model's and not the formalizer's. It is left uncorrected in
this run so that the T=0.0 arm stays byte-comparable to the committed one, and
is reported here as its own category.

---

## 4. The repair this measurement depended on

`verifier.statement_is_broken()` returned a bare bool. Any probe outcome that
was neither `has_sorry` nor `valid` became `broken=True` — **including a
timeout**. Two Stage B rows therefore carried `outcome=statement_error` with the
detail `verification exceeded 60s`: absence of evidence recorded as evidence.

Since `statement_error` is a direct input to the rate above, the uncorrected
pipeline reported Stage B's statement-attributable share as 2/62 = 3.2% when the
measured value is 0/62.

Three independent confirmations that those two rows are sound statements:

1. The committed **prep** pass already recorded both as `elaborated=True`,
   `outcome=has_sorry`, `vacuity=6_contentful`. All 90 statements elaborate; a
   `statement_error` at verification time contradicts the eval set's own
   construction.
2. **Re-probed** under the repaired three-state verdict with a 300s budget: both
   return `not_broken` — *"statement elaborates; the failure is in the proof."*
   One took 114s, which is exactly why a 60s budget produced a timeout.
3. Both rows are in the `hard` band and in the six-statement term-mode cohort of
   §3, i.e. slow to elaborate for an independent and understood reason.

The fix adds a third verdict, `UNKNOWN`, distinct from `BROKEN` and
`NOT_BROKEN`. Callers leave the original outcome in place and record
`statement_probe="unknown"` so an unresolved probe is reported as unresolved
rather than counted on either side.

FormalStep's two `statement_error` rows are unaffected: both are genuine parse
rejections, not timeouts. The contamination was Stage B–specific.

---

## 5. What this does not license

- The provenance labeller has **no demonstrated power on the proof side**.
  Across the 55 committed FormalStep failure records, `proof_claims_checked`
  sums to **1**, and that single claim sits on a row already labelled
  `statement_false`. `proof_false = 0` is therefore **not a measured zero** —
  it is a detector that has essentially never fired on a denominator of 55.
  Stage B's 62 failures have never been run through the labeller at all, so any
  pooled "117 failures" figure mixes the two pipelines and should not be used.
- Truncations are `parse_failure`, not verdicts, and are excluded from the
  judged denominator wherever a judged denominator is reported.
- The single genuine FormalStep proof-side failure is **n=1**. Nothing about
  the model's reasoning can be concluded from FormalStep at this sample size.
  See `CONTENTLESS_STEPS.md` §4.
