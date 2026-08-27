# Statistics changelog

Every number that moved, old → new, with the reason. Branch `fix/statistics`.

---

## GATE — the 36-vs-37 contradiction, resolved

**The record was contradictory and the task's hypothesis was correct.**

Three verification passes exist over the same 50 T=0.0 generations:

| pass | file | outcomes |
|---|---|---|
| 1st | `results/verify_temp0.0.jsonl` | valid **36**, compile_error 14 |
| 2nd | `results/verify2_temp0.0.jsonl` | valid **37**, compile_error 11, statement_error 2 |
| 3rd | `results/verify3_temp0.0.jsonl` | valid **37**, compile_error 11, statement_error 2 |

Diffing pass 1 → pass 2 identifies every sample that moved:

| sample | old → new | old Lean error |
|---|---|---|
| **12** | `compile_error` → **`valid`** | `maximum recursion depth has been reached / use set_option maxRecDepth <num> to increase limit` |
| 19 | `compile_error` → `statement_error` | `unexpected token 'in'; expected ','` |
| 49 | `compile_error` → `statement_error` | `unexpected token 'in'; expected ','` |

Pass 2 → pass 3: **no outcome changed**.

**Cause, confirmed:** `config.py:60` sets `LEAN_MAX_REC_DEPTH = 10000`, injected at
verification time by `verifier.py:363` (`set_option maxRecDepth ...`). The commit
is `64fba01`. Sample 12's old error names the exact option that was raised, so
the attribution is not an inference.

**The true numerator is 37.** `maxRecDepth` was a legitimate fix — an environment
limit was being scored as a failed proof — but it changed a published figure and
was never declared. It is declared here.

| figure | old | new | reason |
|---|---|---|---|
| T=0.0 validity | **36/50 = 72%** [58%–83%] | **37/50 = 74%** [60%–84%] | sample 12: `maxRecDepth` raised from Lean's default 512 to 10000 |
| T=0.2 validity | 36/50 = 72% [58%–83%] | 37/50 = 74% [60%–84%] | same sample, same cause |
| outcome categories | 2 (`valid`, `compile_error`) | 3 (+ `statement_error`) | samples 19 and 49 reclassified: the *goal* does not parse on Mathlib v4.32.0, so the model's proof was never judged |

**Consequence for Phase 2 (this is why the gate came first).** The task specifies
the corrected provable-failure figure as *1 of 37*, reached by excluding samples
12 and 19 from both sides. That is correct **for the pre-fix state**, where 12 was
an infrastructure failure. Post-fix, sample 12 is not a failure at all — it is a
**pass** — so it belongs in the denominator as a success rather than being
excluded. Only sample 19 (no verdict) is excluded. See Phase 2 below.

---

## Phase 1 — `stats.py`

New module; no reported number moved yet. All reference values reproduce exactly
(`tests/test_stats.py`, 44 assertions):

| function | input | value |
|---|---|---|
| `wilson` | 21/50 | 42% [29.4%, 55.8%] |
| `wilson` | 36/50 | 72% [58.3%, 82.5%] |
| `wilson` | 26/27 | 96% [81.7%, 99.3%] |
| `wilson` | 22/50 | 44% [31.2%, 57.7%] |
| `zero_event_upper` | n=11 | 23.8% |
| `zero_event_upper` | n=23 | 12.2% |
| `zero_event_upper` | n=27 | 10.5% |
| `mcnemar_exact` | b=1, c=1 | p = 1.000 |
| `two_proportion_z` | 21/50 vs 36/50 | z = 3.030, p = 0.0024 |

One implementation detail worth recording: at `k=0` and `k=n` the Wilson bound is
analytically exact, but floating-point leaves residue of order 1e-18, which would
print a non-zero lower bound for a count of zero. Both extremes are now pinned.

---

## Phase 2 — denominators

| figure | old | new | reason |
|---|---|---|---|
| failed a provable statement (n50 T=0.0) | **1 of 39** | **1 of 38 = 3% [0%–13%]** | 39 excluded nothing; the published figure removed samples 12 and 19 from the numerator but left both in the denominator. Under the stated rule only 19 is excluded (no verdict). Sample 12 is a **pass** post-`maxRecDepth` and stays in as a success. |
| *(pre-`maxRecDepth` equivalent)* | 1 of 39 | 1 of 37 | what the corrected figure would have been had sample 12 still been failing — recorded so the two are not confused |
| untestable samples | "2 of 50" *and* sample 12 called "a Lean limit" | **2 of 50** (19, 49) | the same rule, applied consistently in both places. Sample 12 is not untestable: it now yields a real verdict, `valid`. |
| §3 table heading vs contents | heading said 3, table had 4 rows | split by temperature | sample 0 is a T=0.2 failure; T=0.0's is sample 35 |
| validity over testable | not reported | **37/48 = 77% [63%–87%]** | new; the exclusion rule makes it computable |

## Phase 3 — independence

| figure | old | new | reason |
|---|---|---|---|
| baseline validity | 21/50 = 42.0% | **21/50 = 42% — CLUSTERED, no valid CI** | 50 consecutive steps of ONE problem; observations correlated, effective n ≈ 1 problem. A binomial interval is invalid. Decimal place also dropped (n < 100). |
| baseline "prover rate on testable statements" | 66% [48%–80%] | **21/32 = 66% — CLUSTERED, no valid CI** | introduced by the provenance run with an interval it was not entitled to; same defect, smaller denominator |
| baseline failed-a-provable rate | 5 of 26 (no rate) | **5/26 = 19% — CLUSTERED, no valid CI** | |
| n50 conditional rate | 88% [75%–95%] | unchanged, but now labelled **secondary analysis** | conditioning on `statement_false`/`parse_skew` conditions on a variable correlated with the outcome; it is a post-hoc subgroup estimate, not the headline |
| baseline reference proofs | 26/27 = 96.3% | **26/27 = 96% [82%–99%]** | one observation per statement, not a chain — the one figure on this set with a valid interval. Decimal dropped. |
| control-set agreement | 35/35 = 100.0% | **35/35 = 100% [90%–100%]** | a perfect score on n=35 still admits a true rate of 90% |
| any rate over `traces/temp_0.jsonl` | possible on 500 rows | **raises `DuplicateRecords`** | 500 rows, 50 distinct samples, 450 exact duplicates; an interval over 500 is ~3× too narrow |

## Phase 4 — claims that needed tests

| claim | old | new | reason |
|---|---|---|---|
| "Zero false positives" (both reports) | asserted, bolded | **agreement with dataset provability**; 0 of 10 testable, upper bound **26%**; 0 of 11 → **24%**; baseline 0 of 23 → **12%** | the `state` field records whether a *statement* is provable, not whether *this proof* is correct. Renamed to what is measured; a zero count carries an interval. |
| "well inside noise" (temperature) | asserted, no test | **McNemar exact p = 1.000** on 2 discordant pairs | paired design: same 50 problems at both temperatures, so an independent two-sample test is the wrong instrument |
| temperature power | not reported | **minimum detectable difference: unattainable** | fewer than the 6 discordant pairs at which a two-sided exact test can reach 0.05 at all. Conclusion is "we cannot detect a difference", not "there is no difference". |
| 42% → 72% comparison | implied improvement | z = 3.24, p = 0.0012, **not usable** | different populations (50 steps of one problem vs 50 first-steps of 50 problems) *and* the baseline arm is clustered. Printed only so no reader recomputes it and mistakes it for a result. (The task's z = 3.03 / p = 0.0024 is for 21/50 vs **36**/50; against the corrected 37/50 it is 3.24 / 0.0012.) |
| `answer_correct` / `invalid_accuracy` | written to output | **`stats.rate()` raises `DegenerateMetric`** | `answer_correct = trace_valid and not has_sorry` makes the second axis a function of the first |

## Phase 6 — regeneration

Both reports now carry a generated statistics block, emitted by
`results/regenerate_reports.py` from `stats.py`. Duplicate rate tables were
removed rather than kept in sync: a number that appears twice is a number that
can disagree with itself, which is exactly how the 36-vs-37 contradiction
survived unnoticed.

---

## 2026-08-27 — re-verified pre-meeting: no live contradiction remains

Re-checked because the pre-meeting brief still described
`SUMMARY_n50_distinct.md` as reporting 36 valid / 14 failures. **It does not,
and has not since `776eebf`.** The brief's premise describes an older commit.

State on `pre-meeting/close-open-questions` (base `8978e94`):

| document | headline | status |
|---|---|---|
| `results/SUMMARY_n50_distinct.md` | 37/50 = 74% [60–84%] | live, correct |
| `README.md` §"Which verification pass" | marks `verify_temp0.*` **superseded**, `verify3_*` current | live, correct |
| `results/AUDIT_LOG.md` | "superseded 36/50 = 72%" | correctly marked dead |
| `results/AUDIT_REPORT.md` | "superseded 36/50" | correctly marked dead |
| `results/BRANCH_MAP.md`, `BRANCH_COMPARISON.md` | 36/50 as history | historical, describes an older HEAD |

**The sample that moved is 12.** Verified directly against the artifacts:

| sample | `verify_temp0.0` | `verify3_temp0.0` | old error |
|---|---|---|---|
| **12** | `compile_error` | **`valid`** | `maximum recursion depth has been reached / use set_option maxRecDepth <num>` |
| 19 | `compile_error` | `statement_error` | `unexpected token 'in'; expected ','` |
| 49 | `compile_error` | `statement_error` | `unexpected token 'in'; expected ','` |

Only sample 12 changes the numerator (36 → 37). Samples 19 and 49 move from
`compile_error` to `statement_error`, which changes the *testable* denominator
(50 → 48), not the count of passes.

**Cause and commit, both confirmed:** `maxRecDepth` was raised from Lean's
default 512 to 10000 in `verifier.py` at commit **`64fba01`**. Sample 12's old
error names the exact option that was raised, so the attribution is direct
rather than inferred.

### Two documentation drifts flagged in `BRANCH_COMPARISON.md` are now CLOSED

That document lists two items as "fix before merge". Both are fixed on HEAD and
it should not be read in a meeting as an open action:

1. *"README omits `statement_error` from the outcome list"* — **fixed.** The
   README lists `statement_error` (3 occurrences), including in the outcome
   enumeration.
2. *"README's worked example writes `results/verify_temp0.0.jsonl`, so following
   the documented commands reproduces 36/50 = 72%"* — **fixed.** The README now
   writes and analyses `results/verify3_temp0.0.jsonl` throughout, and carries an
   explicit table marking `verify_temp0.*` superseded.

**No action required. 37/50 = 74% [60–84%] is the single live value.**
