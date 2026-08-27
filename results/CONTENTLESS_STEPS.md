# Contentless verified steps, and what the Compiler-Bypass denominator should be

The Compiler-Bypass Rate is computed against step validity. If some fraction of
steps that pass Lean assert nothing, then "valid step" is not a uniform category
and the metric's denominator is contaminated.

This is a **measurement-validity issue for the metric, not a refutation of the
paper's hypothesis.** Nothing here says compiler bypass does not happen. It says
the denominator it is divided by needs a definition.

Probes: `tests/audit/vacuity_scan.py`, driven by `tests/audit/contentless_rates.py`
→ `results/contentless_rates.json`. Every probe replaces the model's proof
entirely, so it interrogates the **dataset's goal**, not the model's work.

---

## 1. Headline

> **30.5% of FormalStep goals assert nothing — 152 of 498 problems, 95% CI
> [26.6–34.7%].**

This is a property of the dataset, measured independently of any model, over the
first step of all 500 FormalStep problems (498 usable; 2 skipped because the row
is not a Lean statement — problem 378's first step is `def P : ℕ → ℚ := sorry`).

It supersedes the 14/37 figure as the number to cite. 14/37 was 37 distinct
problems with an interval of [23–53%]; this is 498 with an interval a third as
wide.

### It is not an easy-problem artifact

Contentless share is flat across FormalStep's difficulty levels:

| level | n | contentless | ground (5) | contentful |
|---|---|---|---|---|
| Level 1 | 36 | 7 (19.4%) | 8 | 21 |
| Level 2 | 83 | 28 (33.7%) | 15 | 40 |
| Level 3 | 107 | 34 (31.8%) | 13 | 60 |
| Level 4 | 97 | 27 (27.8%) | 16 | 54 |
| Level 5 | 175 | 56 (32.0%) | 16 | 103 |

The hardest level is as contaminated as the middle ones. Difficulty does not
protect the denominator.

---

## 2. The finding: condition on the goal, not on the outcome

| | P(model produces a compiling proof) |
|---|---|
| goal is **contentless** (classes 1–4) | **14/14 = 100%** [78.5–100] |
| goal is **ground computation** (class 5) | **9/9 = 100%** [70.1–100] |
| goal is **contentful** (class 6) | **15/27 = 55.6%** [37.3–72.4] |
| overall | 38/50 = 76.0% [62.6–85.7] |

Every contentless goal was proved. Every goal the model failed was contentful.
Fisher exact on the 2×2 (pass × contentless): **p = 0.0119**.

**The headline compile rate of 76% decomposes into 100% on goals that demand
nothing and 56% on goals that demand an inference.** That is the result.

---

## 3. The enrichment ratio is a NULL result — reported as one

It would be natural to expect the pass set to be *enriched* in contentless goals
relative to the population. It is barely enriched:

| set | n | contentless | 95% CI |
|---|---|---|---|
| pass set (union of 6 runs) | 38 | 14 = 36.8% | [23.4–52.7] |
| never passed | 12 | 0 = 0.0% | [0–24.3] |
| all 50 sampled | 50 | 14 = 28.0% | [17.5–41.7] |
| population | 498 | 152 = 30.5% | [26.6–34.7] |

> **Enrichment ratio: 36.8% / 30.5% = 1.21×. The intervals overlap heavily.
> This is a null result. It is not evidence that the denominator is
> contaminated, and it must not later be cited as support for that claim.**

The reason it is null is arithmetic, not surprising: the model passes 76% of
everything, so the pass set is most of the sample and inherits close to the
population's contentless share.

**Selection into the pass set is not the mechanism.** The unit is contaminated
before the model touches it. The contamination is a property of FormalStep's
step-level formalization, and it would be there for any model at any pass rate.

The pass-vs-never-passed contrast (36.8% vs 0.0%) is the same fact as §2 stated
backwards, and §2 is the form that carries the significance test. The ratio in
this section is reported so that it is on the record as null.

---

## 4. Stage B: zero

| set | n | contentless |
|---|---|---|
| NuminaMath Stage B | 90 | **0 = 0.0%** [0–4.0] |

Zero-event upper bound **≤ 3.3%**. This is a measurement, not a tautology:
`stage_b_prep.py` selects on Kimina win-rate band (`band.head(30)`) and measures
vacuity afterwards, on all 90.

Two formalization pipelines, 30.5% vs 0%. The intervals are nowhere near each
other. **No Stage B figure may be placed beside a FormalStep figure** — this is
the clearest illustration of why.

---

## 5. The negative control passes — the checker is sound, the unit is not

Stated beside the contentless finding rather than buried, because it is what
separates "the verifier is broken" from "the verifier is fine and the unit is
weak":

**0 of 11 dataset-labelled `Failure of Proof` steps were ever proved, at both
temperatures.** Zero-event upper bound ≤ 23.8%. On dataset-provable rows the
pass rate is 37/38 = 97.4% [87–100%].

The checker does not certify invalid steps. The problem is not soundness. The
problem is that roughly a third of what it is asked to certify cannot be
invalidated by anything.

---

## 6. The instrument has almost no power, and that belongs in the paper

Stated as directly as the pass rate is:

- Of 13 FormalStep failures at T=0.0, **exactly 1 is a genuine proof-side
  failure on a provable row.** (2 are statements Lean rejects; 10 are steps the
  dataset itself labels failures — see `AUTOFORMALIZATION_NOISE.md` §2.)
- **14 of 37 passes assert nothing.**

**The informative sample for anything about the model's reasoning is n = 1.**
The FormalStep eval as constituted has very little power. That is a finding
about the instrument, and it is not softened by the pass rate having a tidy
confidence interval — the interval describes a quantity that is mostly not about
the model.

---

## 7. Why the committed 14/37 could not be extended by re-running

All six committed FormalStep verification passes — `verify`, `verify2`,
`verify3` × T ∈ {0.0, 0.2} — are the **same 50 problems**. The union of passing
`problem_unique_id` across all six is **38**. Pooling them raises the distinct
denominator from 37 to 38 and no further.

The probes need no GPU and no generation, so the denominator was widened a
different way: the identical battery over all 500 problems, same construction as
the eval set (`distinct_problems`, `step_selection=first`) at stride 1 instead
of stride 10. That is where §1's 498 comes from.

---

## 8. Recommendation for the Compiler-Bypass denominator

**Exclude classes 1–4. Report class 5 as a separate column. Report the
all-steps denominator as a robustness row.**

Not "report it three ways and let the reader choose." There is a principled
line, it falls between 4 and 5, and the paper should assert it.

### The argument

The line is **discriminability**: can this goal be false?

Classes 1–4 **cannot be false**, so `valid` on them carries no information about
the model:

| class | example from the pass set | why it cannot discriminate |
|---|---|---|
| 1 `goal_is_True` | s15, s17: goal is literally `True` | true unconditionally |
| 2 `hypotheses_contradictory` | s42: `(9!*5!*2!)/(8!*6!) = 9` | premises inconsistent, so **everything** follows — and this goal is **false** (truth 3), yet it verifies |
| 3 `goal_restates_a_hypothesis` | s23: `n = 6` given `n = 6` | `assumption` closes it |
| 4 `syntactic_tautology` | s2: `3^friends = 3^6` given `friends = 6` | becomes `X = X` under its own hypotheses |

Class 5 **can** be false, and the checker would catch it:

> s1 `Nat.factorial 4 = 24` · s21 `2^3 = 8` · s8 `"COMBINATION".length = 11`

Write `2^3 = 9` and `rfl` fails. These are real checks on real arithmetic. They
test no *inference*, but the Compiler-Bypass Rate is not a claim about
inference — it is a claim about whether an invalid intermediate step co-occurs
with a correct final answer. A ground-arithmetic step is a genuine opportunity
for that to be detected. It belongs in the denominator.

Class 2 decides the other side. It does not merely fail to discriminate, it
**inverts**: s42 has every hypothesis arithmetically false *and a false goal*,
and it verifies `valid` with a clean axiom audit, because `simp_all` finds the
contradiction. Leaving class 2 in the denominator means a false statement proved
from inconsistent premises counts as a valid step. No reading of the metric
survives that.

### Why not a pure multi-denominator report

Reporting the rate under three denominators with no primary hands reviewers a
range and no claim, and invites each reader to select the most convenient one.
"Can this goal be false?" is not a matter of taste — it is a property the probe
battery already measures. Making the call is the paper's job.

What the multi-denominator instinct gets right is that the judgment must be
**visible**, not buried in a preprocessing sentence. That is what the separate
class-5 column and the all-steps robustness row are for.

### What it costs

| denominator | pass set | population |
|---|---|---|
| A. all verified steps | 38 | 498 |
| **B. exclude 1–4 (recommended)** | **24** (−37%) | **346** (−31%) |
| C. exclude 1–5 | 15 (−61%) | 278 (−44%) |

Under B, class 5 is 9 of 24 = **37.5%** of the primary denominator — large
enough that reporting it as its own column is not decoration.

### Suggested table shape

| | CBR | n | of which ground-only |
|---|---|---|---|
| primary (excl. classes 1–4) | … | 24 | 9 (37.5%) |
| robustness: all verified steps | … | 38 | — |
| robustness: excl. classes 1–5 | … | 15 | — |

For Stage B all three denominators coincide at n = 90, because its contentless
share is 0. Reporting it that way makes the FormalStep gap legible rather than
hiding it.

---

## 9. Scope

- FormalStep and Stage B are different formalization pipelines. No figure from
  one may be placed beside a figure from the other.
- FormalStep's current headline is **37/50 = 74% [60–84%]**. The superseded 72%
  (36/50) must not be used — `AUDIT_LOG.md` retired it.
- The population scan covers the **first step** of each problem, matching the
  eval set's construction. Whether later steps within a problem are more or less
  contentless than first steps is not measured here.
