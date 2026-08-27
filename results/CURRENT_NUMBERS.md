# Current numbers — one page, one source of truth

Every live figure in this repo, as of **2026-08-27**, branch
`pre-meeting/close-open-questions`. If a number is not on this page it is not
current.

**Two pipelines. FormalStep and NuminaMath Stage B are different formalization
pipelines with different units. No figure from one may be placed beside a figure
from the other.**

---

## FormalStep — n50 distinct problems

| figure | k/n | 95% CI | artifact | date |
|---|---|---|---|---|
| validity, all traces (T=0.0) | **37/50 = 74%** | [60–84] | `verify3_temp0.0.jsonl` | 08-16 |
| validity, all traces (T=0.2) | **37/50 = 74%** | [60–84] | `verify3_temp0.2.jsonl` | 08-16 |
| validity, testable only | 37/48 = 77% | [63–87] | `SUMMARY_n50_distinct.md` | 08-16 |
| pass rate on dataset-provable rows | 37/38 = 97.4% | [87–100] | `AUTOFORMALIZATION_NOISE.md` | 08-26 |
| pass rate on dataset-failure rows | **0/11 = 0%** | [0–26] | `AUTOFORMALIZATION_NOISE.md` | 08-26 |
| union of passing problems, all 6 runs | 38/50 | — | `contentless_rates.json` | 08-26 |
| genuine proof-side failures (T=0.0) | **1/13 = 7.7%** | [1–33] | `AUTOFORMALIZATION_NOISE.md` | 08-26 |
| failures that are NOT verdicts on reasoning | 12/13 = 92.3% | [67–99] | `AUTOFORMALIZATION_NOISE.md` | 08-26 |

## FormalStep — goal content (probes, model-independent)

| figure | k/n | 95% CI | artifact | date |
|---|---|---|---|---|
| **contentless goals, population** | **152/498 = 30.5%** | [26.6–34.7] | `contentless_rates.json` | 08-26 |
| contentless, pass set | 14/38 = 36.8% | [23.4–52.7] | `contentless_rates.json` | 08-26 |
| contentless, never-passed | 0/12 = 0% | [0–24.3] | `contentless_rates.json` | 08-26 |
| ground-computation, population | 68/498 = 13.7% | — | `contentless_rates.json` | 08-26 |
| P(pass \| contentless goal) | **14/14 = 100%** | [78.5–100] | `CONTENTLESS_STEPS.md` | 08-26 |
| P(pass \| ground goal) | 9/9 = 100% | [70.1–100] | `CONTENTLESS_STEPS.md` | 08-26 |
| P(pass \| contentful goal) | **15/27 = 55.6%** | [37.3–72.4] | `CONTENTLESS_STEPS.md` | 08-26 |
| Fisher, pass × contentless | p = 0.0119 | — | `CONTENTLESS_STEPS.md` | 08-26 |
| enrichment ratio pass/population | 1.21× | overlapping | `CONTENTLESS_STEPS.md` | 08-26 |

## FormalStep — goal shape (filtering decision)

| figure | k/n | 95% CI | artifact | date |
|---|---|---|---|---|
| **proof-shaped, one step per problem** | **254/500 = 50.8%** | [46.4–55.2] | `goal_shape.json` | 08-27 |
| calculation-shaped, one step per problem | 226/500 = 45.2% | [40.9–49.6] | `goal_shape.json` | 08-27 |
| proof-shaped, whole split | 9385/30809 = 30.5% | — | `goal_shape.json` | 08-27 |
| problems with ≥1 proof-shaped step | 494/500 = 98.8% | [97.4–99.4] | `goal_shape.json` | 08-27 |

## FormalStep — provenance of failures

| figure | k/n | 95% CI | artifact | date |
|---|---|---|---|---|
| `statement_false` across 3 runs | 26/55 failures | — | `arithmetic_provenance.json` | 08-23 |
| corroborated by dataset `state` | **23/26 = 88.5%** | [71.0–96.0] | `CORROBORATION.md` | 08-27 |
| — baseline arm | 15/18 = 83.3% | [60.8–94.2] | `corroboration.json` | 08-27 |
| — n50 arm | 8/8 = 100% | [67.6–100] | `corroboration.json` | 08-27 |
| baseline vs n50 difference | Fisher p = 0.529 | not significant | `CORROBORATION.md` | 08-27 |
| proof-side claims ever evaluated | **1 across 55 records** | — | `arithmetic_provenance.json` | 08-23 |

## NuminaMath Stage B — n=90, 30 per band

| figure | k/n | 95% CI | artifact | date |
|---|---|---|---|---|
| **pass rate T=0.0, all attempted** | **28/90 = 31.1%** | [22.5–41.3] | `stage_b_verified_temp0.0.jsonl` | 08-26 |
| **pass rate T=0.7, all attempted** | **26/90 = 28.9%** | [20.5–39.0] | `stage_b_verified_temp0.7.jsonl` | 08-26 |
| pass rate T=0.0, judged only | 28/80 = 35.0% | [25.5–45.9] | `STAGE_B_SWEEP.json` | 08-26 |
| pass rate T=0.7, judged only | 26/84 = 31.0% | [22.1–41.5] | `STAGE_B_SWEEP.json` | 08-26 |
| easy band, T=0.0 | 18/30 = 60.0% | [42.3–75.4] | `STAGE_B_SWEEP.json` | 08-26 |
| medium band, T=0.0 | 7/30 = 23.3% | [11.8–40.9] | `STAGE_B_SWEEP.json` | 08-26 |
| hard band, T=0.0 | 3/30 = 10.0% | [3.5–25.6] | `STAGE_B_SWEEP.json` | 08-26 |
| **temperature effect (McNemar)** | **p = 0.804**, 16 discordant | null | `STAGE_B_SWEEP.json` | 08-26 |
| truncation T=0.0 | 4/90 = 4.4% | [1.7–10.9] | `stage_b_traces_temp0.0.jsonl` | 08-26 |
| truncation T=0.7 | 1/90 = 1.1% | [0.2–6.0] | `stage_b_traces_temp0.7.jsonl` | 08-26 |
| untrusted axioms, either arm | **0/54 passes** | ≤10% | `STAGE_B_SWEEP.json` | 08-26 |
| contentless goals | **0/90 = 0%** | [0–4.0] | `contentless_rates.json` | 08-26 |
| statement-attributable failures | **0/62** | [0–6] | `AUTOFORMALIZATION_NOISE.md` | 08-26 |

## Stage B — provenance of the 110 judged failures

| figure | k/n | 95% CI | artifact | date |
|---|---|---|---|---|
| `tactic_mismatch` | **85/110 = 77.3%** | [68.6–84.1] | `stage_b_provenance.json` | 08-27 |
| UNKNOWN | 14/110 = 12.7% | [7.7–20.2] | `stage_b_provenance.json` | 08-27 |
| `parse_skew` | 4/110 = 3.6% | [1.4–9.0] | `stage_b_provenance.json` | 08-27 |
| `noop_tactic` | 4/110 = 3.6% | [1.4–9.0] | `stage_b_provenance.json` | 08-27 |
| `budget` (resource limits) | 3/110 = 2.7% | [0.9–7.7] | `stage_b_provenance.json` | 08-27 |
| `statement_false` | 0/110 | **see caveat** | `stage_b_provenance.json` | 08-27 |
| `proof_false` | 0/110 | **see caveat** | `stage_b_provenance.json` | 08-27 |

> ⚠️ **Caveat on the two zeros.** The labeller evaluated **0 arithmetic claims**
> on Stage B (0 claims across 0/90 statements, vs 29 across 26/50 on FormalStep).
> It is a calculation checker and Stage B is 82/90 proof-shaped. These are
> **detectors that never fired, not measured zeros.** Do not report Stage B's
> dataset as clean.

---

## DEAD — superseded, do not quote

| dead figure | replaced by | why | where it's marked |
|---|---|---|---|
| ~~36/50 = 72%~~ FormalStep validity | **37/50 = 74%** [60–84] | sample 12's `maxRecDepth` failure was infrastructure, fixed at `64fba01` | `STATS_CHANGELOG.md` |
| ~~14/37 = 38%~~ contentless share | **152/498 = 30.5%** [26.6–34.7] | all 6 runs are the same 50 problems; distinct denominator caps at 38 | `CONTENTLESS_STEPS.md` §7 |
| ~~2/62~~ Stage B statement_error | **0/62** | `statement_is_broken()` returned `broken=True` on a timeout | `AUTOFORMALIZATION_NOISE.md` §4 |
| ~~`proof_false = 0` as measured~~ | "1 claim ever evaluated across 55" | detector never fired | `AUTOFORMALIZATION_NOISE.md` §5 |
| ~~"117 failures" pooled~~ | 55 FormalStep + 110 Stage B, separately | pools two pipelines | `AUTOFORMALIZATION_NOISE.md` §5 |
| ~~`BRANCH_COMPARISON.md` "fix before merge"~~ | both items fixed on HEAD | README lists `statement_error` and points at `verify3` | `STATS_CHANGELOG.md` 08-27 |

---

## The three sentences that matter

1. **The instrument is weak, not broken.** The checker never certified a
   dataset-labelled failure (0/11, both temperatures), but 30.5% of FormalStep
   goals assert nothing and only **1** of 13 FormalStep failures is a genuine
   proof-side failure on a provable row. n=1 is the informative sample.
2. **Temperature does nothing** on Stage B (McNemar p = 0.80), while 16 of 90
   problems churn underneath a flat total.
3. **Filtering to proof steps is viable** — 254 of 500, 3.4× the viability
   threshold — and is the most direct fix for point 1.
