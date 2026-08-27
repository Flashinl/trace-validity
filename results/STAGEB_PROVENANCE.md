# Provenance on Stage B's 110 judged failures

**Verdict: unknown, not zero.** The labeller returns `statement_false` 0/110,
but it evaluated **zero arithmetic claims** on Stage B, so that 0% is a detector
that never fired — not a measurement that the dataset is clean.

Source: `tests/audit/stage_b_provenance.py` → `results/stage_b_provenance.json`.

---

## 1. Gate: the fields were there, so this is a join, not a re-run

Stage B split the fields the same way the earlier pipeline did — statements and
code in the *trace* JSONL, error strings in the *verification* JSONL — so the
labeller was fed by joining on `uuid` (90/90 overlap at both temperatures).

| field | where it lives | present |
|---|---|---|
| `full_code` | trace | 86/90 (T=0.0), 89/90 (T=0.7) |
| `formal_statement` | trace | 90/90 |
| `errors`, `failure_kind` | verification | 90/90 |
| `kimina_proof` (Stage B's reference proof) | `stage_b_evalset.json` | 90/90 |

`reference_proof` is absent from Stage B traces by name; `kimina_proof` in the
eval set is its equivalent and was joined in. The `full_code` gaps are exactly
the `parse_failure` rows, which are excluded as non-verdicts anyway.

**No new generation was required.**

---

## 2. Labels — every failure gets exactly one, and they sum

`parse_failure` and `timeout` excluded as non-verdicts, matching the sweep
report: 52 judged of 62 failures at T=0.0, 58 of 64 at T=0.7.

| label | T=0.0 (n=52) | T=0.7 (n=58) | combined (n=110) | 95% CI |
|---|---|---|---|---|
| **statement_false** | 0 (0.0%) | 0 (0.0%) | **0 (0.0%)** | [0.0–3.4] |
| proof_false | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | [0.0–3.4] |
| tactic_mismatch | 40 (76.9%) | 45 (77.6%) | **85 (77.3%)** | [68.6–84.1] |
| parse_skew | 2 (3.8%) | 2 (3.4%) | 4 (3.6%) | [1.4–9.0] |
| **budget** | 2 (3.8%) | 1 (1.7%) | 3 (2.7%) | [0.9–7.7] |
| noop_tactic | 2 (3.8%) | 2 (3.4%) | 4 (3.6%) | [1.4–9.0] |
| UNKNOWN | 6 (11.5%) | 8 (13.8%) | 14 (12.7%) | [7.7–20.2] |
| **sum** | **52 = 52** ✅ | **58 = 58** ✅ | **110 = 110** ✅ | |

The `budget` label was included this time and it fired **3 times** — those are
`maximum recursion depth` / `deterministic timeout` failures that the earlier
run's table had no bucket for. They are resource limits, not verdicts on
anything.

---

## 3. The finding that matters: the labeller has no reach on Stage B

```
labeller reach, statement claims evaluated:
  Stage B        0 claims across   0/90 statements
  FormalStep n50 29 claims across 26/50 statements
```

**It evaluated nothing.** Not one arithmetic claim, on either side, on any of
the 110 failures. `statement_false = 0` and `proof_false = 0` are therefore both
undefined-in-practice, not measured zeros.

### Why, and it connects straight to the filter question

The labeller is a **calculation checker**: `analyse()` substitutes hypotheses
and evaluates closed numeric claims. It needs closed arithmetic to work on. Run
the Phase 1 goal-shape classifier over both sets:

| set | proof-shaped | calculation-shaped | labeller reach |
|---|---|---|---|
| **Stage B (90)** | 82 (+1 mixed) | **1** | **0/90 statements** |
| **FormalStep n50 (50)** | 20 | **28** | **26/50 statements** |

Stage B is olympiad number theory — `∀ n, ...`, divisibility, existence claims.
There is almost no closed arithmetic in it for the labeller to check. FormalStep
train is Counting & Probability, which is full of `x = 1061520150601`.

**The arithmetic provenance labeller is structurally inapplicable to Stage B.**
That is a property of the instrument meeting a different kind of statement, not
evidence about Stage B's data quality.

---

## 4. Cross-tab: old taxonomy against new label

Where they disagree the provenance label is the more informative one, but both
are shown. Combined across temperatures:

| old `failure_kind` | tactic_mismatch | parse_skew | budget | noop_tactic | UNKNOWN |
|---|---|---|---|---|---|
| tactic_failed | 42 | 0 | 3 | 0 | 4 |
| unsolved_goals | 18 | 0 | 0 | 0 | 0 |
| unknown_identifier | 14 | 1 | 0 | 2 | 0 |
| tactic_no_progress | 9 | 0 | 0 | 0 | 5 |
| elaboration_error | 0 | 3 | 0 | 0 | 0 |
| type_mismatch | 1 | 0 | 0 | 0 | 2 |
| no_goals | 0 | 0 | 0 | 2 | 0 |
| goal_is_false | 1 | 0 | 0 | 0 | 0 |
| other | 0 | 0 | 0 | 0 | 3 |

**The cross-tab is nearly diagonal, and that is the disappointment.** The
premise of running the labeller was that it would cut *across* the taxonomy —
that some `tactic_failed` rows would turn out to be `statement_false`. None did.
`tactic_failed` maps almost entirely onto `tactic_mismatch`, which is close to a
relabelling rather than new information.

Three places it did add something:

- **`elaboration_error` → `parse_skew` (3/3).** The error text is a parse
  problem, not an elaboration one.
- **`no_goals` → `noop_tactic` (2/2).** Correctly identified as the model
  emitting a tactic after the goal was already closed.
- **`tactic_failed` → `budget` (3).** Resource exhaustion pulled out of a bucket
  that otherwise reads as a reasoning failure.

The one `goal_is_false` row (T=0.7) is worth a note: Lean itself reported the
goal false, but the labeller filed it `tactic_mismatch` because it could not
evaluate the arithmetic to confirm. That is the reach problem in miniature —
Lean saw something the labeller could not.

---

## 5. One-line verdict

> **What share of Stage B failures are the dataset's arithmetic being wrong?
> Unknown. The measured value is 0 of 110 [0.0–3.4%], but the labeller evaluated
> 0 arithmetic claims on these statements, so the instrument had no opportunity
> to find anything. The number is not evidence of a clean dataset.**

What is genuinely established: **77.3% [68.6–84.1] of Stage B's judged failures
are `tactic_mismatch`** — the goal stood, and the model's tactic did not close
it. Plus 2.7% resource limits and 3.6% parse skew.

---

## 6. What would resolve it

The arithmetic labeller cannot be made to work here; the statements have no
closed arithmetic. A different instrument is needed. In rough order of cost:

1. **Cheapest, no GPU:** negate the goal and ask Lean to prove the negation. For
   the 110 failures, `theorem t <binders> : ¬(goal) := by decide/norm_num/simp`.
   Anything that closes proves the dataset's statement false. Bounded by
   Lean-only compute, ~1–2 h on the existing verifier. This is the direct
   analogue of what `analyse()` does symbolically, done by the kernel instead.
2. Counterexample search over small numeric instantiations of the binders — a
   `Finset`-bounded `decide` sweep. Catches false ∀-claims, misses false ∃.
3. Compare against `kimina_proof`: 90/90 Stage B rows carry one. If Kimina's own
   proof of a statement fails under our pinned Mathlib, that is evidence about
   the statement rather than about our model. **This is the cheapest real
   check** and needs only the verifier.

Logged as `requires-a-new-run`: nothing here, all three are Lean-only over
existing artifacts. Option 3 is the one to do next.
