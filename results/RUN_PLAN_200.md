# Run plan — the full trajectory-level run (Design C, 155 problems)

**Purpose of this document: decide whether the GPU time is worth spending.**
It is deliberately written *before* any partial run, because a partial run on
non-comparable hardware would produce numbers that cannot be placed beside
anything already committed.

**Recommendation up front: run it, but only after fixing the allocation problem
in §5.** As currently specified the run buys less statistical power than its
cost implies, and one cheap change to the sampling roughly halves what it needs.

---

## 1. What is being asked for

The pilot measures trace validity on **one sampled step per problem**. The full
run measures it on **every step of every trajectory**, which is what licenses the
strict reading of cell b — "every step verified and the conclusion is still
wrong".

Design C (accepted): **155 problems, 764 trajectories, 9,065 steps.**

| | steps | × 2 temperatures |
|---|---|---|
| Design C (77 + 78) — accepted | 9,065 | **18,130 step-proofs** |
| the earlier 100+100 design | 11,974 | 23,948 |
| all 500 problems | 30,809 | 61,618 |

## 2. Hardware requirement — measured, not assumed

| | |
|---|---|
| **Minimum GPU memory** | **~22 GiB** |
| Evidence | the committed n50 runs — the ones this pilot rests on — ran on an **NVIDIA A10, 22.07 GiB total, 21.84 GiB free at start** (`traces/temp0.0_n50_1each/run_meta.json`) |
| Model | `Goedel-LM/Goedel-Prover-SFT`, 7B, fp16, `max_new_tokens` 2048, declared context 4096 |
| Also acceptable | A100-40GB (used for the k16 run), L4, A5000, RTX 4090 — anything ≥24 GiB |
| **Not** acceptable | the local RTX 4070 Laptop, **8.19 GiB** |

**Correction to an earlier statement in this repo's notes:** the figure "the
committed A100 runs used 39 GiB" was wrong. 39.49 GiB was the k16 box's *total*
memory and 39.08 GiB its *free memory at start* — neither is consumption. The
real proven requirement is the A10's 22.07 GiB, which makes this a
commodity-GPU job rather than an A100 job. That matters for cost and for
availability.

Lean/Mathlib verification needs **no GPU** and already runs on this machine, so
the two halves can be split across boxes if convenient.

## 3. Projected wall-clock and cost

Both figures below are extrapolated from committed `run_meta.json` timings, not
estimated from first principles.

### Generation

| source | hardware | batching | throughput |
|---|---|---|---|
| `temp0.0_n50_1each` | A10 | 1 trajectory/sample | 50 records / 356.2 s = **7.1 s/record** |
| `exp2_n50_k16` | A100 | 16 trajectories/sample | 800 records / 592.1 s = **0.74 s/record** |

The 10× gap is batching, not the card. The full run generates **one** proof per
step, so the batch must be formed **across steps** rather than across
trajectories of one step — a scheduling change, not a modelling one. Assuming it
achieves the batched throughput:

| | at 0.74 s/proof (batched) | at 7.1 s/proof (unbatched) |
|---|---|---|
| 18,130 step-proofs | **3.7 h** | 35.8 h |

**Plan for ~4–6 h of generation on a ≥24 GiB card**, and treat >12 h as a signal
that batching is not working rather than as the expected cost.

### Verification

Measured on the committed runs: mean **0.66–1.06 s** per record, median
0.02–0.04 s, p90 0.11 s, max 61 s. The mean is dominated by a small tail.

18,130 × ~0.8 s ≈ **4 h single-threaded**, and it parallelises across cores
almost perfectly. On this machine, with the Mathlib environment already built,
call it **1–2 h** with 4 workers.

### Total

**~6–8 h end to end**, split as ~4–6 h GPU + ~1–2 h CPU. At commodity cloud
rates for a 24 GiB card (roughly $0.50–$1.00/h), the GPU portion is **under
$10**. The cost of this run is scheduling and attention, not money.

## 4. What the pilot already establishes without it

These do **not** need the full run and should not be re-litigated by it:

1. **The two axes are independent** — enforced by assertion, static import
   check, and signature, each demonstrated against negative controls. Both
   off-diagonal cells are populated where the old design forced them to zero.
2. **The answer axis has real variance** — 61.0% [59.1–62.9] of all 2,459
   trajectories reach the correct answer, so it is neither degenerate nor
   trivially satisfied.
3. **The checker works** — 0.2% extraction failure, 0/20 hand-verified
   disagreements on an untuned seed, 58 passing tests.
4. **Cell b is non-empty even at n=50** — 8/50, of which 2 are the strong
   contentful form.
5. **Cell c is larger than cell b** — 10/50 vs 8/50. Trajectories reach right
   answers through steps our prover cannot verify.
6. **Trace validity shows no detectable association with answer correctness** —
   φ = +0.009 [−0.255, +0.309].
7. **Every structural fact about the corpus** — 2,459 trajectories, ~5 per
   problem, single MATH subject, no category labels, 157 fraction problems.

## 5. What the full run adds — and the problem with it as specified

### It genuinely adds

- **The strict reading of cell b.** Only the full run can say "*every* step
  verified and the conclusion is still wrong". That is the claim the study is
  for, and the pilot cannot make it.
- **Power.** This is the real argument. The pilot's binding constraint is
  n₀ = 13 invalid traces, and at that size **80% power is unreachable at any
  effect size** — even a hypothetical 100% vs 76.9% reaches only 75% power.
  Observed power was **3%**.

| to detect | n₀ needed | n₁ needed | total |
|---|---|---|---|
| 25 pp | 16 | 44 | 60 |
| 20 pp | 25 | 69 | 94 |
| 15 pp | 57 | 158 | 215 |
| 10 pp | 151 | 418 | 569 |

*(80% power, α = 0.05 two-sided, baseline 76.9%, allocation held at the observed
2.8:1)*

- **Clustering handled honestly.** 764 trajectories over 155 problems is ~5 per
  problem. The pilot avoided this by having exactly one trajectory per problem;
  the full run must compute at the problem level or use a cluster-robust
  interval. This is a reporting requirement, not an obstacle.

### The problem: the strict axis will be badly unbalanced

A trajectory counts as valid only if **all** its steps verify, and trajectories
have a median of 10 steps.

Measured on Design C using FormalStep's own per-step labels — a free upper bound,
since its 82.0% per-step success rate is more permissive than our pipeline's 74%:

> **199 of 764 trajectories (26.0%) have every step succeed.**

Our per-step rate is 8 points lower, so the strict top row will be **below 26%** —
plausibly 10–20%, i.e. **n₁ ≈ 75–150 against n₀ ≈ 610–690**. That is the mirror
image of the pilot's imbalance, and the binding constraint becomes n₁.

Either way the run clears the 20 pp threshold (n₁ ≈ 75–150 vs the 69 needed) and
probably the 15 pp one, but it does **not** reach 10 pp. **Do not expect the full
run to resolve a small association.** If the true effect is ~5 pp — which the
pilot's point estimate suggests — this run will also return "not detectable",
having cost a day.

### The cheap fix: stratify the sample on the trace axis

Nothing requires drawing trajectories blind. Because the dataset's own per-step
`state` is free and correlates with our validity axis, the trajectories can be
**pre-stratified into likely-all-valid and likely-not** and sampled to a balanced
allocation. Balanced allocation at the same total n reaches a given effect size
with roughly half the sample of a 2.8:1 split.

This changes the sampling frame, not the measurement — validity is still measured
by actually running the prover, and the answer axis never sees `state` (the
independence guard rejects that field by name). It should be decided before the
run, not after.

## 6. Recommendation

**Run it, with three conditions:**

1. **Balance the allocation** (§5). Otherwise a large fraction of the GPU time
   buys observations in the already-saturated arm.
2. **Batch across steps, not trajectories** (§3). The difference is 3.7 h vs
   35.8 h.
3. **Pre-register the reporting**: problem-level or cluster-robust intervals; the
   full 3×3 table with reconciling denominators; both vacuity cuts; and the
   power calculation stated alongside the result, so a null is not read as an
   absence of effect.

**Do not run it to answer question 4** ("does validity predict correctness").
Even at 764 trajectories the design cannot detect an effect below ~10 pp, and the
pilot's estimate is smaller than that. Run it for the **strict cell b**, which is
a claim the pilot genuinely cannot make and which does not depend on power.

## 7. What is still out of scope afterwards

- Generalisation beyond MATH counting_and_probability — the corpus is
  single-subject.
- Category-stratified analysis — the labels are not in the release.
- Anything about whether *our prover* affects the answer axis. It cannot; see
  §0 of `TWO_AXIS_EXPERIMENT.md`.
