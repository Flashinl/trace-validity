# Phase 2 — the answer-correctness checker

Module `answer_correctness.py`; tests `tests/test_answer_correctness.py`
(**58 passing**); validation `tests/audit/answer_validate.py`.
No Lean, no GPU, no network.

## The independence mechanism

The brief's hard constraint is enforced by an assertion, not a convention.

- `assert_no_lean_verdict(record)` raises `LeanLeakError` on any of
  `trace_valid, outcome, has_sorry, valid, errors, num_errors, axioms,
  verify_seconds, verify_source, statement_probe, statement_mismatch_detail,
  statement_error_detail, vacuous, has_sorry_literal, failure_kind, state`.
- **`state` is in that list on purpose.** It is FormalStep's own Lean
  verification of its own reference proof. It is a Lean verdict, it correlates
  with our trace axis, and letting it into the answer path would couple the axes
  as surely as reading `outcome`.
- `score_trajectory(steps, ground_truth)` takes step **texts** and a ground
  truth. There is no parameter a verdict could ride in on, and a test pins the
  signature.
- A static AST test asserts `answer_correctness.py` imports nothing from
  `verifier, trace_valid, parser, config, model, generate, data_loader,
  failure_taxonomy`.

**The gate was made to fire on purpose** (this repo has had three gates return
clean zeros because they read the wrong thing):

| negative control | result |
|---|---|
| a module containing `import verifier` | caught → `['verifier']` |
| a module containing `from config import ...` | caught → `['config']` |
| the real `verifier.py` | caught → `['config']` |
| `answer_correctness.py` | clean → `[]` |

and one parametrised test asserts the guard raises on *every* forbidden field
individually.

## Normalisation rules, decided once

| rule | decision |
|---|---|
| fraction reduction | **yes** — compare by value; `\frac{2}{4}` → `1/2` |
| decimal/fraction equivalence | **yes, exact** — `Fraction("0.1")` is exactly 1/10. Never a float, so no epsilon and no rounding |
| negative signs | preserved, accepted outside or inside the macro: `-\frac{2}{3}` and `\frac{-2}{3}` both → `-2/3` |
| whitespace | removed, including `\!`, `\,`, `\;`, `\ `, `~`, and the `,` thousands separator |
| currency | `\$` stripped as a unit; `$` stripped as a math delimiter; in that order |
| percent | **two readings** — see below |
| non-rational values | cleaned string, compared by exact string equality only; never matched against a number |

Required table, all passing:

| raw | normalises to |
|---|---|
| `45,\!045` | `45045` |
| `\frac1{216}` | `1/216` |
| `\frac{1}{216}` | `1/216` |
| `\dfrac{3}{4}` | `3/4` |
| `\frac{2}{4}` | `1/2` |
| `101` | `101` |
| `$101$` | `101` |
| `0.5` vs `\frac{1}{2}` | compare **equal** |

### The percent rule is a genuine conflict in the source data

FormalStep stores the answer to a probability question **both** ways:

- `ground_truth` = `\frac{1}{10}`, trajectory says "0.1 or 10%" → `10%` must be **1/10**
- `ground_truth` = `15`, trajectory says "15%" → `15%` must be **15**

No single rule serves both. A percent literal is therefore matched permissively
against **either** reading (x/100 or x). This is a deliberate widening; its cost
is a false positive if a `ground_truth` of N is met by a trajectory saying "N%"
of something unrelated. That is rarer in this data than the miss the strict rule
produces, and it is stated rather than buried.

## Extraction, and the bug that mattered

`extract_answer(steps)` reads a trajectory's final step, falling back up to 2
steps earlier. Priority: `\boxed{}` → prose ratio ("1 in 29,322,216") → four
answer markers → `=` chain → last number.

**The first implementation took the last number in the sentence, and that was
wrong in a way that silently corrupted the study.** English maths prose states
the answer *first* and then restates the problem:

> "So, there are **15** ways to put **4** indistinguishable balls in **3**
> distinguishable boxes."

Last-number gives `3`; the answer is `15`. That scored a *correct* trajectory as
`incorrect`. Fixing it moved **133 trajectories** from incorrect to correct
(55.6% → 61.0% correct overall). Two rules now govern:

- if the answer span contains `=`, the result is what follows the **last** `=`
  ("the difference is 187 − 118 = **69**")
- otherwise the **first** numeric token in the span
- for the `therefore/so/thus` family the span starts after the **last** copula
  ("the remainder when the sum … is divided by 15 is **3**"), while the
  existential "there are X …" family — matched by an earlier, higher-priority
  marker — starts after the **first**

All eight of these cases are pinned as regression tests.

## Measured performance, over all 2,459 trajectories

| quantity | value |
|---|---|
| correct | 1,501 / 2,459 = 61.0% [59.1–62.9] |
| incorrect | 954 / 2,459 = 38.8% [36.9–40.7] |
| **`answer_unknown` (extraction failure)** | **4 / 2,459 = 0.2% [0.1–0.4]** |

On the eligible pool (2,330 trajectories) the split is 1,500 / 826 / 4.

`answer_unknown` is a **third category**. It is never folded into `incorrect`.

Extraction method mix (eligible pool): `marker3` 874, `marker2` 479, `eq_chain`
309, `last_number` 233, `boxed` 167, `marker1` 134, `marker0` 122,
`prose_ratio` 8.

The correctness rate falls monotonically with difficulty — Level 1 11% wrong,
Level 5 66% wrong — which is a sanity signal that the checker tracks something
real rather than noise.

## Hand verification

Four seeded samples of 20 were hand-read. The first two were used to *find*
bugs, so their disagreement counts are not the reported figure; after the last
change, a **fresh, untouched seed** was drawn and adjudicated.

| seed | when | verdict disagreements |
|---|---|---|
| 20260902 | normalisation table, 20 `ground_truth` values | 0/20 |
| 4242 | used for debugging — found last-number bug | (tuning set) |
| 555222 | used for debugging — found percent conflict | 1/20 after fixes |
| **31337** | **final, untouched by tuning** | **0/20** |

**Reported disagreement count: 0 of 20 on seed 31337; 1 of 40 (2.5%,
[0.4–13%]) pooling the two post-fix samples.** The one residual is a spurious
extraction from a trajectory whose final step is not a conclusion at all ("…5
other stamps that add up to 0 cents"), where `last_number` produced `0` and the
row should arguably have been `answer_unknown`.

`last_number` is the weakest path (233/2,330 = 10% of eligible rows) and
hand-reading found it the least reliable. It is reported separately rather than
being suppressed, because converting all of it to `answer_unknown` would inflate
the unknown rate on rows where it is in fact correct.

## Known residuals, quantified not hidden

- **Rounded decimal preferred over an exact fraction.** If a final step states
  both (`"…is 1/7 or approximately 0.143"`), extraction may take the decimal.
  Measured: of 2,330 eligible trajectories, **4** have a token in the final step
  that matches `ground_truth` while the extracted token does not; hand-reading
  those 4 shows **2** are genuine false negatives (the other 2 match a numeral
  from the problem restatement). ≈ 0.09%.
- **Answer stated before the final step.** Lookback is capped at 2 steps.
- **A trajectory that answers a different question** is scored `incorrect`, which
  is right for this study but is not the same as an arithmetic slip.
