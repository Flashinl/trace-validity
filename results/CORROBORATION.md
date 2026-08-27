# External corroboration of all 26 `statement_false` labels

**The corroboration held.** 23 of 26 agree directly with the dataset's own
label; the 3 apparent disagreements, on inspection, confirm the classifier
rather than contradict it. There is no evidence the classifier is tuned to n50.

Source: `tests/audit/corroborate_statement_false.py` → `results/corroboration.json`.

---

## Why this was needed

The classifier reported **0** `statement_false` before a hypothesis-substitution
bug was fixed and **26** after. A result that swings that far on one
implementation detail needs a check from outside the classifier. Until now only
8 of the 26 had one — the n50 cases. The 18 baseline cases are 69% of the
finding and had never been checked.

The external signal is FormalStep's own `state` field, which labels each step
`Success of Proof` or `Failure of Proof`, plus whether the dataset ships a
`proof` for the row.

---

## Confusion matrix

| run | `Failure of Proof` | `Success of Proof` | n |
|---|---|---|---|
| baseline_50step_1problem | **15** | 3 | 18 |
| n50_distinct_T0.0 | **4** | 0 | 4 |
| n50_distinct_T0.2 | **4** | 0 | 4 |
| **TOTAL** | **23** | **3** | **26** |

| run | agreement | 95% CI | dataset `proof` empty |
|---|---|---|---|
| baseline (the 18) | 15/18 = **83.3%** | [60.8–94.2] | 15/18 |
| n50 T=0.0 | 4/4 = 100% | [51.0–100] | 4/4 |
| n50 T=0.2 | 4/4 = 100% | [51.0–100] | 4/4 |
| **all 26** | 23/26 = **88.5%** | [71.0–96.0] | 23/26 |

**Fisher two-sided p = 0.5292** on baseline (15/18) vs n50 (8/8).

> **No evidence baseline agreement is worse.** The intervals overlap almost
> entirely — n50's 8/8 gives [67.6–100], which contains baseline's 83.3%. The
> classifier is not tuned to n50 and the 47% figure does not need widening on
> this basis.

The brief anticipated a single percentage might hide a split. It did not: the
split is 3 records, and the difference does not survive a test.

---

## The 3 disagreements confirm the classifier

All three are from the **same problem** — *"Determine ⁶√1061520150601 without a
calculator"* — and all three have a **non-empty** reference proof, unlike the
other 23.

The relevant arithmetic: `101^6 = 1061520150601`. The CoT went astray and
started expanding `(100+6)^3 = 1191016` instead.

| sample | informal step | formal statement | why the classifier flagged it |
|---|---|---|---|
| s27 | `= 1·(100+6)^3` | `h₀ : 1061520150601 = 1 * (100 + 6) ^ 3` | hypothesis false: 1061520150601 ≠ 1,191,016 |
| s35 | `= 1·(1·100³ + 3·100²·6 + 10800)` | goal `1061520150601 = 1 * (a + b + c)` | goal false: 1061520150601 ≠ 1,190,800 |
| s44 | same | goal `x = 1 * (100^3 + 3*100^2*6 + 10800)` | goal false: 1,191,016 ≠ 1,190,800 |

The classifier is **arithmetically correct on all three.** The statements are
false.

So why does the dataset call them `Success of Proof`? Because a proof exists.
Here is s27's shipped reference proof in full:

```lean
theorem test (a : ℝ) (h₀ : 1061520150601 = 1 * (100 + 6) ^ 3) :
  (a = 1061520150601) := by
  have h₁ : a = 1061520150601 := by linarith
  exact h₁
```

`h₀` is false, so the premises are inconsistent, so **everything follows** —
`linarith` closes a goal about a completely unconstrained `a`. The dataset's
`state` field records *"a proof compiles"*; the classifier records *"the
statement is true"*. Those two questions come apart exactly where vacuity lives.

**This is the class-2 `hypotheses_contradictory` case from
`CONTENTLESS_STEPS.md` §8, appearing independently in the corroboration.** It is
the same mechanism as sample 42, found by a different route. It strengthens the
argument for excluding class 2 from the Compiler-Bypass denominator: the dataset
itself will mark such a step a success.

Counting the 3 as agreements-at-a-deeper-level, effective agreement is **26/26**.
The conservative figure to quote is the direct one, **23/26 = 88.5%
[71.0–96.0]**.

---

## A join bug worth recording

The first run returned `NOT_FOUND` on all 26 and briefly looked like a total
corroboration failure. It was not: the dataset ships statements ending
`:= by sorry`, and `normalize_formal_statement()` rewrites that to `:= by`
before anything is written to a trace. Matching raw dataset text against a
trace's `formal_statement` therefore never matches.

The fix is to canonicalise both sides through the same normaliser before
joining. Anyone joining traces back to FormalStep needs to do this.

---

## Scope

- `state` is FormalStep's label, not ground truth. It answers "does a proof
  compile", which as shown above is not the same question as "is the statement
  true".
- The 3 disagreements are all one problem, so they are one mechanism observed
  three times, not three independent observations.
- This corroborates the `statement_false` label specifically. It says nothing
  about `proof_false`, which remains a detector that has evaluated 1 claim
  across 55 records.
