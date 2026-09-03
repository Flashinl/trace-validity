# Phase 1 — the custom dataset

Built by `tests/audit/build_custom_dataset.py`, **seed 20260902**.
Output: `data/custom_200.jsonl` (200 rows), `results/custom_dataset.json`.
No Lean, no GPU, no network.

## Eligibility

| step | n |
|---|---|
| problems in FormalStep | 500 |
| dropped — unmatchable answer | 23 |
| dropped — value ≥ 10⁶ | 3 |
| **eligible** | **474** |
| — integer arm | 317 |
| — simple-fraction arm | **157** |

The three large values are `33,\!800,\!000`, `4,\!989,\!600`, `1,\!296,\!540`,
matching the brief's count of 3 exactly.

The brief's other two figures do not reproduce, and both matter:

- **157 fractions, not 155.** `\frac19` and `\dfrac34` are valid LaTeX — both
  `\frac` arguments are independently optional-braced. A regex requiring braces
  on the second argument misfiles #931 and #836 as unmatchable. I wrote that bug
  myself in the first pass of `answer_census.py` and caught it on inspection; it
  is the same shape as the `theorem test:` bug that once put 13,880 rows in
  UNKNOWN.
- **23 unmatchable, not 13.** Breakdown: 8 decimals, 3 percentages, 3 dollar
  amounts, 9 genuinely symbolic (`\text{B}`, `\frac{1}{N+1}`, `-2^{49}`, `n`,
  `\frac{\pi}{6}`, `\frac{\pi}{16}`, `k=3`, `240\text{ ways.}`, and the literal
  `" + string(n) + "`, an un-executed template string in the source data). If
  decimals, percentages and dollar amounts count as normalisable — which the
  Phase 2 checker handles anyway — genuinely unmatchable is **9**.

## The constraint the supervisor needs to know about

**100 fractions is 64% of every simple-fraction problem in the dataset
(100/157).** That arm is close to a census, not a sample. Two consequences:

1. It will not generalise the way the integer arm does. Resampling it gives
   almost the same problems, so its variance is understated by any interval that
   assumes sampling from a large population.
2. **Proportional level stratification of a 100-problem fraction arm is
   infeasible.** It asks for 17 Level 2 fractions and only 16 exist.

The shortfall is exactly 1 problem. It is absorbed by a documented spill rule
(reallocate to the level with the most spare capacity, largest-pool-first) and
every affected row carries `selection_rule = "...|spill_from_undersupplied_levels"`,
so nothing is silently reallocated.

## Level shares — the brief's figures are row shares, not problem shares

| level | brief (row share) | measured, problem level | problems |
|---|---|---|---|
| Level 1 | 5.9% | **7.2%** | 36 |
| Level 2 | 12.9% | **16.6%** | 83 |
| Level 3 | 17.7% | **21.4%** | 107 |
| Level 4 | 17.9% | **19.4%** | 97 |
| Level 5 | 45.6% | **35.4%** | 177 |

Stratifying a *problem* sample by *row* shares would over-weight Level 5 by ten
points, because harder problems have more steps per problem. The build uses
problem-level shares.

## Available supply, and the realised design

| level | integer available | fraction available | target per 100-arm |
|---|---|---|---|
| Level 1 | 27 | 8 | 7 |
| Level 2 | 61 | **16** | **17** ← short by 1 |
| Level 3 | 60 | 38 | 21 |
| Level 4 | 53 | 39 | 20 |
| Level 5 | 116 | 56 | 35 |

### Design A — `spec_100_100` (built, shipped as `data/custom_200.jsonl`)

| level | integer | fraction | total |
|---|---|---|---|
| Level 1 | 7 | 7 | 14 |
| Level 2 | 17 | 16 | 33 |
| Level 3 | 21 | 21 | 42 |
| Level 4 | 20 | 20 | 40 |
| Level 5 | 35 | 36 | 71 |
| **total** | **100** | **100** | **200** |

Fraction arm = 64% of all fractions. One Level 2 spill into Level 5.

### Design B — `proportional_100_55`

Keeps the fraction arm at the same 33% share of the eligible pool that it has in
the population, so the two arms are comparable rather than equal-sized.

| level | integer | fraction | total |
|---|---|---|---|
| Level 1 | 7 | 4 | 11 |
| Level 2 | 17 | 9 | 26 |
| Level 3 | 21 | 12 | 33 |
| Level 4 | 20 | 11 | 31 |
| Level 5 | 35 | 19 | 54 |
| **total** | **100** | **55** | **155** |

Fraction arm = 35% of all fractions. Fully feasible, no spill.

### Design C — `balanced_77_78`

| level | integer | fraction | total |
|---|---|---|---|
| Level 1 | 6 | 6 | 12 |
| Level 2 | 13 | 13 | 26 |
| Level 3 | 16 | 17 | 33 |
| Level 4 | 15 | 15 | 30 |
| Level 5 | 27 | 27 | 54 |
| **total** | **77** | **78** | **155** |

Fraction arm = 50% of all fractions. Fully feasible, no spill, and the two arms
are the same size so an integer-vs-fraction contrast is balanced.

**Recommendation: Design C** if the integer-vs-fraction contrast is the point,
because it is balanced and feasible without spill; **Design B** if the sample is
meant to represent the population. Design A is shipped as specified, but its
fraction arm should be described as a census of 64% of the stratum, not a sample.

## Category stratification is not available

Phase 0 Q3 established that the five paper-Table-2 category labels are not in the
release and no field carries them. The category × answer-type cell table cannot
be produced. Regenerating the labels needs one LLM call per row over 30,809 rows
and is a separate task.

## Row schema

Every row of `data/custom_200.jsonl`:

```json
{"problem_unique_id": "...", "level": "Level 3", "answer_type": "integer",
 "ground_truth": "101", "ground_truth_value": "101",
 "n_trajectories": 5, "n_steps": 61,
 "selection_rule": "integer|Level 3|proportional_target_21",
 "design": "spec_100_100", "seed": 20260902}
```

`n_trajectories` and `n_steps` are carried because they are the compute cost of
that row: the 200-problem design covers 993 trajectories and 11,974 steps.
