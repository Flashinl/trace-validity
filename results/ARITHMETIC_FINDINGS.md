# Whose arithmetic is wrong — the dataset's or the prover's?

Every number below is computed from a committed artifact by
`tests/audit/provenance.py` → `results/arithmetic_provenance.json`.
Method and self-tests: `results/ARITHMETIC_LOG.md`. Contamination checks:
`results/PIPELINE_RULED_OUT.md`.

---

## Verdict

**The false arithmetic is the dataset's.** Across all 55 failing samples in
all three trace sets, 26 fail because a numeric literal in the *statement* is
arithmetically wrong, and **0 fail because of a number the model wrote**.

- statement-side: **26/55 = 47%** [35–60%] of all failures
- proof-side: 0/55. With 0 events in n=55, the exact one-sided
  95% upper bound on the proof-side rate is **5%** — it is bounded, not proven zero.

On those samples `compile_error` is the **correct** verdict. The verifier is
catching CoT steps that were already wrong. That is the tool working.

---

## Provenance table

### baseline (50 steps of ONE problem)

50 samples, 29 failing.

| label | n | share of failures | share of all samples |
|---|---|---|---|
| `statement_false` | 18 | **18/29 = 62%** [44–77%] | **18/50 = 36%** [24–50%] |
| `proof_false` | 0 | **0/29 = 0%** [0–12%] | **0/50 = 0%** [0–7%] |
| `tactic_mismatch` | 10 | **10/29 = 34%** [20–53%] | **10/50 = 20%** [11–33%] |
| `noop_tactic` | 1 | **1/29 = 3%** [1–17%] | **1/50 = 2%** [0–10%] |
| `UNKNOWN` | 0 | **0/29 = 0%** [0–12%] | **0/50 = 0%** [0–7%] |

### n50 distinct problems, T=0.0

50 samples, 13 failing.

| label | n | share of failures | share of all samples |
|---|---|---|---|
| `statement_false` | 4 | **4/13 = 31%** [13–58%] | **4/50 = 8%** [3–19%] |
| `proof_false` | 0 | **0/13 = 0%** [0–23%] | **0/50 = 0%** [0–7%] |
| `tactic_mismatch` | 5 | **5/13 = 38%** [18–64%] | **5/50 = 10%** [4–21%] |
| `parse_skew` | 4 | **4/13 = 31%** [13–58%] | **4/50 = 8%** [3–19%] |
| `UNKNOWN` | 0 | **0/13 = 0%** [0–23%] | **0/50 = 0%** [0–7%] |

### n50 distinct problems, T=0.2

50 samples, 13 failing.

| label | n | share of failures | share of all samples |
|---|---|---|---|
| `statement_false` | 4 | **4/13 = 31%** [13–58%] | **4/50 = 8%** [3–19%] |
| `proof_false` | 0 | **0/13 = 0%** [0–23%] | **0/50 = 0%** [0–7%] |
| `tactic_mismatch` | 4 | **4/13 = 31%** [13–58%] | **4/50 = 8%** [3–19%] |
| `parse_skew` | 4 | **4/13 = 31%** [13–58%] | **4/50 = 8%** [3–19%] |
| `UNKNOWN` | 1 | **1/13 = 8%** [1–33%] | **1/50 = 2%** [0–10%] |

---

## What this does to the headline number

The reported validity rate blends two different things: how good the prover is,
and how many of the dataset's CoT steps are already wrong. Separating them:

| set | reported validity | statements that were never a fair test | **prover rate on testable statements** |
|---|---|---|---|
| baseline (50 steps of ONE problem) | **21/50 = 42%** [29–56%] | 18 | **21/32 = 66%** [48–80%] |
| n50 distinct problems, T=0.0 | **37/50 = 74%** [60–84%] | 8 | **37/42 = 88%** [75–95%] |
| n50 distinct problems, T=0.2 | **37/50 = 74%** [60–84%] | 8 | **37/42 = 88%** [75–95%] |

The middle column is `statement_false` + `parse_skew`: statements that are
arithmetically false, or that do not elaborate on Mathlib v4.32.0 at all. In
neither case was the model's proof ever judged.

**Both numbers must be reported, and neither alone is the story.** The left
column is what the pipeline currently prints; the right column is the prover's
performance; the gap between them is a measurement of FormalStep's error rate,
which is a finding in its own right and arguably the more interesting one.

Note how much of the difference between the two trace sets this explains. The
baseline set looks far worse (42% vs 74%) — but 36% of its samples carry a
false statement, against 8% for the n50 set. On testable statements the gap
narrows sharply. The baseline set is not a harder test of the prover; it is a
more broken slice of the dataset, because all 50 of its steps come from one
problem whose CoT goes wrong early and stays wrong.

---

## The dataset agrees

Two signals the arithmetic checker never saw, both confirming it:

| | n50 T=0.0 | n50 T=0.2 |
|---|---|---|
| `statement_false` samples | 4 | 4 |
| …labelled `Failure of Proof` by FormalStep | **4/4** | **4/4** |
| …shipping with an empty `reference_proof` | **4/4** | **4/4** |

FormalStep could not prove these statements either. An arithmetic checker
working only from the numbers reached the same verdict as the dataset's own
provability label, independently.

---

## The failures, named

### baseline (50 steps of ONE problem) — `statement_false`

| sample | the false claim |
|---|---|
| 2 | goal `n = 1.061520150601 * 10^9` is FALSE: 1061520150601 vs 1061520150601/1000 |
| 3 | goal `x = (1061520.150601)^3 * 10^2` is FALSE: 1061520150601 vs 1196147475686664860781049986817531801/10000000000000000 |
| 4 | goal `1061520.150601 = x` is FALSE: 1061520150601/1000000 vs 1061209 |
| 6 | goal `x = 10303` is FALSE: 10201 vs 10303 |
| 7 | hypothesis `1061520.150601 = (101^2 * 103)^3` is FALSE: 1061520150601/1000000 vs 1159951729605778927 |
| 27 | hypothesis `1061520150601 = 1 * (100 + 6) ^ 3` is FALSE: 1061520150601 vs 1191016 |
| 31 | goal `1061520150601 = (100^3 + 3 * 100^2 * 6 + 3 * 100 * 6^2 + 6^3)` is FALSE: 1061520150601 vs 1191016 |
| 32 | goal `100^3 + 3 * (100^2) * 6 + 3 * 100 * (6^2) = 1061520150601` is FALSE: 1190800 vs 1061520150601 |
| 34 | goal `100^3 + 3 * 100^2 * 6 + 108 * 100 = 1061520150601` is FALSE: 1190800 vs 1061520150601 |
| 35 | hypothesis `1061520150601 = a + b + c` is FALSE: 1061520150601 vs 1190800 |
| 36 | goal `1061520150601 = (100^3 + 3 * 100^2 * 6 + 10800)` is FALSE: 1061520150601 vs 1190800 |
| 37 | goal `1 * (1 * 100^3 + 3 * 100^2 * 6 + 10800) = 1061520150601` is FALSE: 1190800 vs 1061520150601 |
| 38 | goal `1061520150601 = (100 + 6)^6` is FALSE: 1061520150601 vs 1418519112256 |
| 39 | goal `1061520150601 = (100 + 6)^6` is FALSE: 1061520150601 vs 1418519112256 |
| 42 | goal `1061520150601 = 1 * (100 + 6)^6` is FALSE: 1061520150601 vs 1418519112256 |
| 44 | contradictory bindings for `x`: 1191016 and 1061520150601 |
| 46 | goal `1061520150601 = (100 + 6)^6` is FALSE: 1061520150601 vs 1418519112256 |
| 49 | goal `n = 1030301 * 10^6 + 1 * 10^6` is FALSE: 1061520150601 vs 1030302000000 |

### n50 distinct problems, T=0.0 — `statement_false`

| sample | the false claim |
|---|---|
| 5 | goal `5 / 6 = 1 - 1 / 6` is FALSE: 0 vs 1 |
| 7 | goal `(11! / (9! + 2 * 8!)) = (11 * 10 / (9 + 2))` is FALSE: 90 vs 10 |
| 16 | goal `total_cubes - interior_cubes = 36` is FALSE: 56 vs 36 |
| 36 | goal `(6! + 7!) / 5! = 8` is FALSE: 48 vs 8 |

### n50 distinct problems, T=0.2 — `statement_false`

| sample | the false claim |
|---|---|
| 5 | goal `5 / 6 = 1 - 1 / 6` is FALSE: 0 vs 1 |
| 7 | goal `(11! / (9! + 2 * 8!)) = (11 * 10 / (9 + 2))` is FALSE: 90 vs 10 |
| 16 | goal `total_cubes - interior_cubes = 36` is FALSE: 56 vs 36 |
| 36 | goal `(6! + 7!) / 5! = 8` is FALSE: 48 vs 8 |

---

## Limits

- **Proof-side denominator is small, by nature of the data.** Only 1 proof-side
  equality was assertable across all 55 failures, because the model hardly ever
  hand-writes arithmetic (Phase 3: 2, 1 and 0 proofs out of 50 do). The
  `proof_false = 0` result is therefore bounded at ≤5% rather than established as exactly zero.
- **`tactic_mismatch` is a residual, not a diagnosis.** 19 samples land there.
  Each has correct-looking arithmetic and a tactic that could not close the
  goal; whether the goal was provable at all is not established for every one.
- **`UNKNOWN` count: 1** of 55.
- The baseline set has no dataset `state` field (older schema), so the
  independent-label corroboration is available only for the two n50 sets.
- n is 50 per set. Every interval above is wide; do not read one-decimal
  precision into any of them.
