# Phase 0 — design questions resolved before anything was built

Branch `exp/answer-correctness`, worktree isolated from the shared clone.
Every number below is printed by `tests/audit/phase0_survey.py` and
`tests/audit/answer_census.py`, both of which read the FormalStep split from the
local HuggingFace cache. No Lean, no GPU, no network.

**Gate verdict: PASS on question 2 — proceed.** The trajectories already state a
final answer, so no solver run is needed. Two design facts the brief did not
anticipate are surfaced in §5 and §6; neither blocks Phases 1–2, one constrains
Phase 3.

---

## Q1 — Does FormalStep carry trajectory structure? Yes, and the unit is the trajectory

`previous_steps` is **not** a growing prefix. It is the **full step list of the
trajectory the row belongs to, repeated verbatim on every row of that
trajectory**, and `current_step` is that row's own step within it. The field name
is actively misleading and reading it as a prefix would have produced a wrong
unit of analysis.

Grouping on `(problem_unique_id, tuple(previous_steps))`:

| quantity | value |
|---|---|
| rows | 30,809 |
| distinct problems | 500 |
| **distinct trajectories** | **2,459** |
| trajectories per problem | min 2, median 5, max 5, mean 4.92 |
| distribution | `{2: 1, 3: 6, 4: 26, 5: 467}` |
| steps per trajectory | min 1, median 11, max 101 |

The reconstruction is exact, not approximate:

- **2,459 / 2,459** trajectories have their rows equal to their step list, *in order*
- sum of steps over trajectories = **30,809** = the row count, with nothing left over

So the 62-steps-per-problem figure decomposes as ~5 trajectories × ~11 steps, not
as one finely-decomposed solution.

**Consequence for the design.** The row of the 2×2 grid is a **trajectory**, not
a problem. Trajectories cluster within problems at ~5 per problem, so they are
not independent draws — this must be declared, and any interval that treats
n = trajectories as n independent observations is overconfident. `ground_truth`
and `level` are constant within a problem (0 conflicts on both), so they are safe
to key on at the problem level.

---

## Q2 — Where does the final answer come from? Best case: it is already in the data

**Case 1 of the three.** Each trajectory's last step is its concluding sentence
and states the answer. No generation, no GPU, no separate solver run.

Ten trajectories drawn at seed 20260902:

| `ground_truth` | final step | verdict |
|---|---|---|
| `162` | "The value of q/p is 162." | correct |
| `\frac{5}{12}` | "So, the probability is $\frac{5}{12}$." | correct |
| `4970` | "…there are **36260** four-digit numbers…" | **wrong** |
| `929` | "…$m + n = 383 + 512 = **895**$." | **wrong** |
| `\frac{1}{10}` | "…the arrangement reads XOXOX is **0.1 or 10%**." | correct, different form |
| `59` | "The final answer is $7 + 52 = 59$." | correct |
| `\dfrac{1}{29,\!322,\!216}` | "…is **1 in 29,322,216**." | correct, prose form |
| `\frac{160}{2187}` | "…the Lakers win the seventh game is $\dfrac{1}{3}$." | **wrong** |
| `568` | "Running this code, we get the answer: 568." | correct |
| `6048` | "…the coefficient of $x^5$ … is $6048$." | correct |

This is the single most important result in Phase 0: **the trajectories contain
genuinely wrong final answers** — 3 of 10 in a blind draw. The answer axis will
have real variance and is not degenerate. Had every trajectory been correct, the
2×2 would have collapsed to a 2×1 and the study would have had nothing to
measure.

It also shows exactly why Phase 2's normaliser is mandatory rather than
cosmetic: `0.1 or 10%` must compare equal to `\frac{1}{10}`, and `1 in
29,322,216` must be recovered from prose. Extraction is prose-level and will
fail on some rows; those are `answer_unknown`, reported as a third column.

---

## Q3 — Do the five category labels ship with the dataset? No

The release schema is exactly:

```
problem, level, type, ground_truth, problem_unique_id,
previous_steps, current_step, formal_statement, proof, state
```

There is no category / subject / topic / label field. An exact-value scan across
every scalar field for `Geometry`, `Number Theory`, `Algebra`, `Combinatorics`,
`Others` returns **zero hits in every field**. `type` takes exactly one value,
`Counting & Probability`.

Paper Table 2's labels are GPT-4o-mini classifications of the **Lean statements**
and were not released. Regenerating them is one LLM call per row over 30,809
rows — out of scope here, and it is a prerequisite for any category-stratified
design.

**Consequence for Phase 1.** The category × answer-type cell table the brief asks
for "if the labels turn out to be available" **cannot be produced**. Phase 1
stratifies on level only. If the category axis is wanted, regenerating the labels
is its own task and should be costed separately.

---

## Q4 — The single-subject contradiction, resolved

It is not a misread field. **Two independent encodings agree:**

1. the `type` column is `Counting & Probability` on all 30,809 rows
2. every `problem_unique_id` is `math_train_counting_and_probability_<n>` — a
   string that has to be parsed, but parsed here only by splitting on the last
   underscore

A field-misreading bug would have to corrupt both a categorical column and a
string identifier in the same direction to produce this, which is not plausible.
This is the check the brief asked for given the repo's history with
`theorem test:` — the resolution does not rest on any regex over Lean source.

Further evidence that the release is complete rather than a partial shard:

- the HF snapshot is a **single file**, `FormalStep.jsonl`, with **30,809 lines** —
  no other split, config, or subject shard exists in the repo
- 30,809 is **exactly** the total of the paper's Table 2 (873 + 11,515 + 5,525 +
  9,414 + 3,482)

So the released corpus is the same corpus Table 2 describes, and it is
single-subject. The 500 problem ids span 1..5131 (428 below 1200, 72 at or above
5000), consistent with within-subject MATH file numbering.

**Resolution: the release differs from the paper's description of the sampling.**
The paper's claim that the 500 were drawn at random from MATH train cannot
produce a single-subject corpus; the 500 were drawn from within
counting_and_probability. Note this does *not* contradict Table 2's category
counts, because those label the Lean statement's mathematical content, not the
source MATH subject — a counting problem whose step reads `8! = 2^5 * 3^2 * n`
classifies as number theory quite reasonably.

**Consequence for the whole study.** Every result generalises to MATH
counting_and_probability only. Any claim about "MATH" or about mathematical
reasoning in general is unsupported by this dataset.

---

## §5 — A unit mismatch the brief does not address (surfaced, not worked around)

The two axes are **natively at different units**:

| axis | native unit | source |
|---|---|---|
| answer correctness | **trajectory** (its final step) | dataset, free |
| trace validity | **step** (one `formal_statement`'s generated proof) | existing pipeline |

To put both on one row, trace validity has to be aggregated over a trajectory's
steps, and that aggregation is a design choice with real consequences:

- **strict** — all steps of the trajectory verify. With a median of 11 steps and
  a per-step pass rate near 74%, almost no trajectory will be valid, and the top
  row of the grid empties for a reason that has nothing to do with the research
  question.
- **sampled-step** — validity of the one step we actually generated for. This is
  what the existing pipeline measures and what the pilot uses. "Valid trace" then
  means "the sampled step verified", which must be stated plainly and not
  quietly read as "the whole trajectory verified".

The brief's framing of cell b — "every step verified and the conclusion is still
wrong" — describes the **strict** reading. Under the sampled-step reading, cell b
is "the sampled step verified and the conclusion is still wrong", which is a
weaker but still meaningful claim. Phase 5 reports which reading is in force.

## §6 — The compute envelope, and what is runnable here

A trajectory-level strict axis requires generating and verifying a proof for
every step of every sampled trajectory:

| pool | problems | trajectories | steps | × 2 temperatures |
|---|---|---|---|---|
| all 500 | 500 | 2,459 | 30,809 | 61,618 |
| eligible after drops | 474 | 2,320 | 29,528 | 59,056 |
| **200-problem sample** | 200 | 993 | 11,974 | **23,948 step-proofs** |
| **20-problem pilot** | 20 | 98 | 1,346 | 2,692 step-proofs |

What this machine has:

- **Lean 4 + Mathlib: built and usable.** Verification runs locally.
- **GPU: RTX 4070 Laptop, 8.19 GiB.** Goedel-Prover-SFT is 7B. The committed
  n50 runs this pilot rests on ran on an **NVIDIA A10, 22.07 GiB total**
  (`traces/temp0.0_n50_1each/run_meta.json`), so ~22 GiB is the *measured*
  sufficient figure — not the 39 GiB of the k16 box, which was that machine's
  total memory rather than its consumption. 8.19 GiB is still far short.
  Quantising would change the model and break comparability with every existing
  result in the repo.

So **generation is not available locally**. It needs a box with ~22 GiB or more
of GPU memory. (Design C, 77+78, was subsequently accepted in place of the
200-problem design; its cost is **9,065 steps × 2 temperatures = 18,130
step-proofs**. See `results/RUN_PLAN_200.md`.)

**What is runnable now, end to end, on real data:** the committed n50 runs at
**T=0.0 and T=0.2** — the two temperatures the supervisor specified — carry real
Goedel-Prover proofs with real Lean verdicts (37/50 valid at each temperature)
and a `dataset_row` field that maps each sampled step back to its trajectory.
That is a genuine end-to-end pilot at n=50 on the sampled-step reading, and it
reconciles against the existing n50 numbers as Phase 4 requires.

Phases 1 and 2 need no compute at all and are unaffected.

---

## Corrections to figures quoted in the brief

Checked rather than assumed, because Phase 1's arm sizes depend on them.

| quantity | brief | measured | note |
|---|---|---|---|
| simple-fraction problems | 155 | **157** | `\frac19` and `\dfrac34` are valid LaTeX — both `\frac` arguments are independently optional-braced. Requiring braces on the second argument misfiles #931 and #836. I hit this bug myself and fixed it before it propagated. |
| unmatchable answers | 13 | **23** | full list in `tests/audit/answer_census.py` output |
| large-value answers | 3 | **3** | confirmed: 33,800,000 / 4,989,600 / 1,296,540 |
| level shares | L1 5.9 / L2 12.9 / L3 17.7 / L4 17.9 / L5 45.6 | L1 7.2 / L2 16.6 / L3 21.4 / L4 19.4 / L5 **35.4** | the brief's figures are **row** shares over 30,809 rows; stratifying a *problem* sample needs **problem** shares over 500 |

The 23 unmatchable break down as 8 decimals (`.039`, `22.5`, `3.5`, `49.6`,
`4.5`×2, `1.25`, `.6`), 3 percentages, 3 dollar amounts, and 9 genuinely
symbolic or broken values (`\text{B}`, `\frac{1}{N+1}`, `-2^{49}`, `n`,
`\frac{\pi}{6}`, `\frac{\pi}{16}`, `k=3`, `240\text{ ways.}`, and the literal
`" + string(n) + "` — an un-executed template string in the source data).

If the intended rule counts decimals, percentages and dollar amounts as
normalisable — which Phase 2's spec requires anyway, since `50\%` and `$101$`
are both in its table — then genuinely unmatchable is **9**, not 13 or 23. The
level-share discrepancy is the one that matters most: stratifying to the brief's
L5 share of 45.6% would over-weight Level 5 by ten points against the actual
problem population.
