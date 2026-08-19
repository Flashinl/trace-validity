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
