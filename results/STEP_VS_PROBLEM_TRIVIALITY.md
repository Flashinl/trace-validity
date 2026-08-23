# Why step-level formalization manufactures trivial statements

The vacuity scan found that 14 of 37 passing traces assert nothing at all. That
count is a property of a sample. This document is about the **mechanism** behind
it, which is a property of the dataset — and which predicts, in advance, that a
whole-problem dataset cannot reproduce it.

Numbers below come from `tests/audit/pinned_hypothesis_scan.py` →
`results/pinned_hypothesis_scan.json`, `results/vacuity_scan.json`,
`results/vacuity_failures.json` and `results/stage_b_evalset.json`.

---

## 1. The pattern: a pinned hypothesis

A binder of the form `h₀ : var = <literal>` **pins** a variable to a constant.
Once one is present, substituting it can collapse the goal into `X = X`:

```lean
theorem test (friends teams : ℕ) (h₀ : friends = 6) (h₁ : teams = 3)
    : (3 ^ friends = 3 ^ 6) := by
```

Substitute `h₀` and the goal reads `3 ^ 6 = 3 ^ 6`. It is closed by
`subst_vars <;> with_reducible rfl` — no arithmetic, no reasoning, and `teams` is
never used at all. Lean will happily certify it, and our verifier will score it
`valid`, correctly: it *is* a proof of the stated theorem. The theorem is just
worthless.

This single pattern underwrites the two largest trivial classes:

- `4_syntactic_tautology` — 8 of the 14, exactly as above.
- `3_goal_restates_a_hypothesis` — 3 of the 14: `(n : ℕ) (h₀ : n = 6) : (n = 6)`,
  closed by `assumption`.

## 2. Why step-level formalization produces it, necessarily

FormalStep formalizes **one chain-of-thought step**. A step in the middle of a
solution consumes what earlier steps computed. For the formalized step to be a
self-contained Lean theorem, those inputs must be supplied — and the only way to
supply a value to a Lean theorem is as a hypothesis binding a variable to it.

**The pins are not sloppiness. They are what makes a single step
self-contained.** Any faithful step-level formalization scheme has to produce
them, and any scheme that produces them will sometimes produce a step whose
output is just its input rearranged.

## 3. Why whole-problem statements cannot

A problem statement has no preceding step. Nothing has been computed yet, so
there is nothing to pin. Its variables are universally quantified (`∀ n : ℕ`) or
fixed inside the goal:

```lean
theorem number_theory_84195 (n : ℕ) : 9 ∣ n^3 + (n + 1)^3 + (n + 2)^3 := by
```

There is no `h₀ : n = <literal>` to substitute, so the substitution-to-tautology
route is **structurally unavailable** — not merely absent from a sample.

## 4. The measurement, across whole datasets

This is the number that generalises. Not the 37 passes we sampled — every
statement in both corpora.

### FormalStep — step-level, one row per CoT step

| | | |
|---|---|---|
| statements with ≥1 pinned hypothesis | **11,884 / 30,809 = 39%** | [38%–39%] |
| problems with ≥1 such statement | **496 / 500 = 99%** | [98%–100%] |

**Practically every problem in the benchmark contains at least one statement
carrying the pattern**, and 39% of all statements do.

### NuminaMath-LEAN — problem-level, one row per whole problem

| | | |
|---|---|---|
| Number Theory + proof pool | **25 / 2,232 = 1%** | [1%–2%] |
| whole dataset | **4,760 / 104,155 = 5%** | [4%–5%] |

**39% versus 1% on the comparable pool** — a ~39× difference, and the residual 1%
is consistent with a handful of problems that genuinely state a constant.

## 5. The probe comparison

The same six probes, run against both. Each replaces the model's proof entirely,
so it interrogates the *dataset's goal*, never the model's work.

| probe | what it detects | FormalStep passes (37) | NuminaMath NT (90) |
|---|---|---|---|
| `P_decide` | decidable outright, hypotheses unused | 13 | **0** |
| `P_substrfl` | `X = X` after substituting own hypotheses | 11 | **0** |
| `P_rfl` | closes by kernel computation | 9 | **0** |
| `P_assum` | goal *is* a hypothesis, verbatim | 3 | **0** |
| `P_true` | goal is literally `True` | 2 | **0** |
| `P_redrfl` | syntactically `X = X` | 2 | **0** |

**Not one probe fired on any of the 90.** All 90 classify `6_contentful`. 87 of
the 90 have binders, so the contradiction probe genuinely ran — they are not
unprobed by default.

`with_reducible` is the load-bearing choice in `P_redrfl`: it closes `X = X` but
will *not* unfold `Nat.factorial 4` to `24`, which is what separates "asserts
nothing" from "asserts a real computation".

## 6. The selection effect, and how to quote the rate

Running the same probes over the **failing** traces (`vacuity_failures.json`):

| | asserts nothing | ground computation | contentful |
|---|---|---|---|
| FormalStep passes (37) | **14** | 9 | 14 |
| FormalStep failures (13) | **0** | 0 | **13** |
| NuminaMath eval set (90) | **0** | 0 | **90** |

Every failure is contentful; zero are trivial, at both temperatures. Triviality
is **entirely concentrated in the pass set**, which is exactly what the method
predicts: a trivially-true goal is one the model is overwhelmingly likely to have
closed. **Trivial goals are proved because they are trivial.**

So the 46% content rate describes **the pass set, not the benchmark**. Say "of
what we counted as passes, 46% assert something." Do not say "46% of FormalStep
is contentful" — the failure run is the evidence that would be wrong.

## 7. What follows

1. **The 74% / 46% / 28% ladder is a statement about what our passes were made
   of.** It does not transfer to another dataset, and it is not a capability
   measure.
2. **A step-level rate and a problem-level rate are different quantities.** A
   Stage B pass rate on NuminaMath is not comparable to 74%, both because the
   unit differs (one CoT step vs one whole problem) and because the step-level
   number is inflated by a triviality mode the problem-level dataset cannot
   produce. Report them separately, never side by side.
3. **This is a property of step-level formalization in general**, not a defect
   unique to FormalStep. Any dataset that slices solutions into individually
   formalized steps should be expected to carry it, and should be measured for
   it before a pass rate is quoted.

---

## Scope

The scan detects a **syntactic** pattern: a binder whose left side is an
identifier and whose right side looks closed (a numeral, a list, or a
constructor application). It is deliberately conservative — a false negative
understates the pattern, which is the safe direction for the claim being made.
It does not prove any individual statement is trivial; the Lean probes do that.
The two agree: the corpus where the pattern is at 39% is the corpus where the
probes fire, and the corpus where it is at 1% is the one where they never do.
