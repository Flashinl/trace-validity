# Consolidated findings — verification audit, 2026-08-23

Written for a reader who has seen none of the underlying work. It consolidates
rather than repeats: each section states the finding and points at the document
that carries the full evidence.

**One claim previously reported to the team is retracted here.** See §4.

> **Where this work lives.** `master` sits at `7125705` and deliberately does not
> yet carry the audit work. The 2026-08-23 audit is staged on
> `ikra/audit-2026-08-23` (`d9117a5`) and lands via pull request with review
> assigned; this branch adds the Stage B artifacts on top of it. If you have
> checked out `master` and cannot find the documents linked below, that is why —
> read from this branch or from `ikra/audit-2026-08-23`.

## Reading order

| document | what it holds |
|---|---|
| this file | the through-line and the retraction |
| [`STEP_VS_PROBLEM_TRIVIALITY.md`](STEP_VS_PROBLEM_TRIVIALITY.md) | §1 in full — the mechanism, corpus scans, probe comparison |
| [`TEMPERATURE_AND_VACUITY.md`](TEMPERATURE_AND_VACUITY.md) | the 37 positives, sample 42, the 74/46/28 ladder |
| [`STAGE_B_NUMINAMATH.md`](STAGE_B_NUMINAMATH.md) | §3 in full — per-band rates, taxonomy, generation notes |
| [`ARITHMETIC_FINDINGS.md`](ARITHMETIC_FINDINGS.md) | statement-side arithmetic. **Its §Verdict is superseded by §4 below** |
| [`SUMMARY_n50_distinct.md`](SUMMARY_n50_distinct.md) | the n50 statistics, intervals, McNemar |
| [`AUDIT_REPORT.md`](AUDIT_REPORT.md) | the earlier process audit — 11 findings, 6 pipeline defects |
| [`../docs/IMPLEMENTATION.md`](../docs/IMPLEMENTATION.md) | pipeline, glossary, pinned versions |

---

## 1. The main finding: step-level formalization inflates pass rates structurally

**Formalizing a mid-solution chain-of-thought step requires pinning that step's
inputs as equality hypotheses**, because a Lean theorem must be self-contained
and the only way to supply a value is as a hypothesis. Those pins can make the
goal collapse under substitution:

```lean
theorem test (friends teams : ℕ) (h₀ : friends = 6) (h₁ : teams = 3)
    : (3 ^ friends = 3 ^ 6) := by
```

Substitute `h₀` and the goal reads `3 ^ 6 = 3 ^ 6`. `teams` is never used. Lean
certifies it and the verifier scores it `valid` — correctly. It *is* a proof of
the stated theorem. The theorem is worthless.

**The pins are not sloppiness.** They are what makes a single step stand alone.
Any faithful step-level formalization scheme produces them.

### How prevalent, measured across whole corpora

| | | |
|---|---|---|
| FormalStep — statements with ≥1 pinned `h : var = <literal>` | **11,884 / 30,809 = 39%** | [38%–39%] |
| FormalStep — problems with ≥1 such statement | **496 / 500 = 99%** | [98%–100%] |
| NuminaMath — Number Theory + proof pool | **25 / 2,232 = 1%** | [1%–2%] |
| NuminaMath — whole dataset | **4,760 / 104,155 = 5%** | [4%–5%] |

### What it produces downstream

Of 37 passing traces at T=0.0, **14 assert nothing at all** and only **14
require an inference step** — a reasoning rate of **28%** against a compile rate
of 74%.

Six Lean probes, each replacing the model's proof entirely so they interrogate
the *dataset's goal*:

| | FormalStep passes (37) | NuminaMath statements (90) |
|---|---|---|
| total probe firings | **40** | **0** |
| distinct statements with ≥1 hit | **22** | **0** |

Not one probe fired on any of the 90. 87 of them have binders, so the
contradiction probe genuinely ran.

### The claim is an interaction, not a pattern count

This correction was made during the work and must not be allowed to drift back.
**Pinning is neither necessary nor sufficient for triviality.**

- It does **not** predict passing: pinned in 20/37 passes vs 4/13 failures,
  z = −1.45, **p = 0.148**.
- `P(trivial | pinned)` = **10/20 = 50%**; `P(trivial | not pinned)` = **4/17 =
  24%**. Half of pinned passes are contentful.
- `P(pinned | trivial)` = **10/14**. Four trivial passes carry no pin at all —
  `(6 / 6 = 1)` and `(5 = 5)` have no binders; one goal is literally `True`; one
  has contradictory hypotheses.

**Triviality requires a pinned hypothesis *and* a goal expressible as a
syntactic identity in the pinned variables.** Pinning is the dominant single
route — 6 of 8 syntactic tautologies, all 3 restated-hypothesis cases — but on
its own it is roughly a doubling of the odds, not a diagnosis. The 39% figure is
an **upper bound on the reach of the mechanism, not a triviality rate.**

Full treatment: [`STEP_VS_PROBLEM_TRIVIALITY.md`](STEP_VS_PROBLEM_TRIVIALITY.md).

---

## 2. The benchmark asserts false things, in both directions

Evaluating the closed arithmetic of every FormalStep statement. 18,557 of 30,809
rows (60%) have at least one claim that evaluates to a closed value — the only
honest denominator, since a row whose claims never close is evidence either way.

| | n | share of checkable |
|---|---|---|
| asserts something **false** | 1,567 / 18,557 | **8%** |
| …**false goal** — unprovable, manufactures a *failure* | 1,352 | **7%** |
| …**false hypothesis** — can be inconsistent, manufactures a *pass* | 215 | **1%** |

**303 of 500 problems contain at least one arithmetically false step — 61%.**

**Both directions must be stated. This is not a single quality score.** A false
goal cannot be proved, so the model fails and the dataset's error is scored
against the prover — measured at 36–62% of failures. A false hypothesis can make
the premises inconsistent, in which case `False` follows, every goal follows, and
a proof of it compiles. That is sample 42, a confirmed false positive that every
existing check passes: it compiles, proves the stated goal, and stands on no
untrusted axiom.

The pass-manufacturing class is the smaller one, which is consistent with finding
exactly one vacuous pass in the sampled 50. It is not zero, and it scales with
the eval set.

---

## 3. Stage B is a control condition, not a result about number theory

**Its purpose is that whole-problem statements are the condition where the
pinning artifact structurally cannot occur.** All 90 statements classify
`6_contentful` under the same six probes, so the rates below need no
content-rate correction — they are already content rates.

90 whole problems, 30 from each Kimina-Prover-72B `win_rate` band, temperature 0,
single trajectory, verified against pinned Mathlib v4.32.0.

| band | ours | 95% Wilson | Kimina `win_rate` |
|---|---|---|---|
| easy | **18/30 = 60%** | [42%–75%] | 0.944 |
| medium | **7/30 = 23%** | [12%–41%] | 0.608 |
| hard | **3/30 = 10%** | [3%–26%] | 0.147 |
| **total** | **28/90 = 31%** | [22%–41%] | — |

### Three framing constraints

**(a) Two levels, not three.** `easy` separates from the rest (p = **0.0040**);
`medium` and `hard` **do not separate from each other** (p = **0.1659**). Report
a tractable band and a hard band. The underlying `win_rate` means differ across
all three, but n=30 cannot resolve the lower two.

**(b) The ceiling is a different quantity from our rate.** Kimina's `win_rate` is
an **RL rollout success rate** — repeated attempts during training. Ours is
**single-attempt pass@1**. These are not the same measurement, and ours is the
more pessimistic construction. On the hard band the two nearly overlap (10%
[3–26%] vs 14.7%), which is **more plausibly the unit mismatch than a real
finding** about relative capability. Do not read the ratio.

**(c) The 72% is comparable to nothing here.** It is FormalStep, step-level —
one row per CoT step, ~62 per problem — against problem-level figures. It is
additionally inflated by the §1 artifact, which this dataset structurally cannot
produce. **Never place it beside a Stage B number.**

Full treatment: [`STAGE_B_NUMINAMATH.md`](STAGE_B_NUMINAMATH.md).

---

## 4. Retracted: the arithmetic claim

**Previously reported:** *"Zero failures are caused by a number the model wrote"*
— `proof_false = 0/55`, presented with a 95% upper bound of 5%.

**This is retracted.** The zero was guaranteed by construction, not measured.

Counting what the labeller actually evaluated on the proof side:

| | failures | proof-side claims evaluated |
|---|---|---|
| Stage B (NuminaMath NT) | 62 | **0** |
| FormalStep n50 T=0.0 | 13 | **0** |
| FormalStep baseline | 29 | **1** |

**One closed proof-side claim has ever been evaluated, across 117 failures in
both datasets.** A detector that evaluates nothing cannot flag anything.

Two further points:

- A `%` misparse was found and fixed — `a^2 % 3 = 1` was read as `3 = 1`, which
  produced **9 `proof_false` labels on Stage B of which 9 were spurious**. The
  fix stops the labeller inventing flags; it does **not** create a denominator,
  because modular claims are now skipped rather than checked.
- **The single claim ever evaluated was false**: `101^2 = 10301`, a real model
  arithmetic error. It was outranked by a false statement in the same sample, so
  it never surfaced as `proof_false`.

`ARITHMETIC_FINDINGS.md` § Limits already recorded the thin denominator. Its
§ Verdict states the zero as a finding, and **that section is superseded by
this one.** The error in reporting was mine: the caveat was dropped every time
the figure was quoted upward.

**Report as unanswerable, not as a corrected zero.**

### The dataset-migration premise still fails — on different grounds

The premise was that the model is weak at multiplication and stronger at proof
structure, so the eval set should move to proof-style problems. That still does
not hold, but the reasoning has changed:

1. **Tactic selection dominates failures**, on both datasets — §5.
2. **The arithmetic failures that exist are the dataset's false statements**, not
   the model's computation (§2, and `ARITHMETIC_FINDINGS.md` statement-side
   figures, which are unaffected by this retraction).
3. **The zero was never load-bearing evidence** and should not have been cited
   as though it were.

---

## 5. Failure taxonomy

Stage B, 62 failures:

| failure_kind | n | share |
|---|---|---|
| `tactic_failed` | 25 | **50%** |
| `unknown_identifier` | 9 | **18%** |
| `unsolved_goals` | 8 | 16% |
| `tactic_no_progress` | 5 | 10% |
| others | 5 | 6% |

**`unknown_identifier` is a distinct mode that appears at competition
difficulty** — the model naming Mathlib lemmas that do not exist. **9 of 62
here, against 1 of 29 on the FormalStep baseline.** It is not a tactic failure
and not an arithmetic failure; more training on formalization would not
obviously address it.

FormalStep's own taxonomy: [`FAILURE_TAXONOMY.md`](FAILURE_TAXONOMY.md).

---

## 6. Method notes

**The Mathlib version gap did not materialise.** NuminaMath-LEAN targets Mathlib
v4.15.0; we pin v4.32.0. **90/90 statements elaborated** under our pin. This was
the main compatibility risk and it is retired for this eval set.

**Three of 90 rows needed the deprecated binder fix** — `∑ x in` → `∑ x ∈`,
required by Mathlib ≥ 4.32 — logged by uuid in
[`stage_b_evalset.json`](stage_b_evalset.json):
`055f4f94…`, `061481e9…`, `076e5357…`. Pool-wide the pattern affects **53 / 2,232
= 2%**. One of the three is the row that failed the earlier 30-sample probe; it
elaborates after the fix.

**Four generations hit the 2048-token limit** and are recorded as
`parse_failure` — not verdicts on the model's proof. They are excluded from the
testable-only denominators, which are **67% / 27% / 12%** by band. **The token
budget was tuned for step-level proofs**; whole-problem olympiad proofs run
longer (mean tokens 488 / 553 / 610 by band, rising with difficulty), so this
budget is a known constraint on this dataset rather than a neutral default.

---

## 7. Limits — which claims generalise and which do not

Every rate here rests on **500 problems in a single category** (FormalStep's
train split is 100% Counting & Probability), **one 6.9B prover**
(Goedel-Prover-SFT), and evaluations of **50 to 90 samples**. A reader should not
borrow confidence across the two columns below.

### Structural claims — generalise beyond this setup

These are about the *shape* of formalized statements and hold independently of
which model was run:

- Step-level formalization requires pinned hypotheses to make a step
  self-contained. This follows from what a Lean theorem is, not from a sample.
- Whole-problem statements structurally cannot produce the
  substitution-to-tautology mode. **0 / 90 probe hits, 0 / 90 pinned
  hypotheses.**
- Corpus prevalence: 39% of statements and 99% of problems in FormalStep;
  1% in the NuminaMath NT pool. These are censuses, not samples — no sampling
  interval applies.
- The `statement_mismatch` and `%` defects were real code defects, reproduced
  and covered by tests.

### Rate claims — do not generalise

These are properties of one model on one sample and should carry their intervals
whenever quoted:

- 74% / 46% / 28% on FormalStep, and 31% (60/23/10 by band) on Stage B.
- The 8% / 61% benchmark error rates — a census of FormalStep, but FormalStep is
  one category, so they say nothing about MATH or about formalized benchmarks
  generally.
- Everything about relative difficulty between the medium and hard bands, which
  the sample cannot resolve.
- Anything about `proof_false`, in either direction — see §4.

### Not measured at all

- **Answer correctness.** The prover emits a Lean proof, not an answer; the
  dataset's `ground_truth` is the whole problem's answer, identical for every
  step of that problem. The cross-tab's second axis is the dataset's
  *provability* label, which is a different question. Do not relabel it.
- **Whether a `valid` result is meaningful** beyond the vacuity classes probed.
  The probes detect the modes they were built for; a statement can be trivial in
  a way none of them catches.
- **Proof-side arithmetic**, per §4.

---

## 8. Corrections made during this work

These are part of the result, not footnotes to it. Each was found by checking a
claim rather than by a test failing.

| claim | what happened |
|---|---|
| "The verifier receives the tactic block without the theorem statement" | **Refuted.** The prompt is prefix-completion and ends after the statement; 50/50 traces carry it verbatim. Issue #11 closed with evidence. |
| "Mathlib's transitive deps float, explaining two-machine divergence" | **Disproven** on a clean clone. Mathlib is pinned to an immutable tag and commits its own manifest; `lake update` produced the pinned aesop rev even though `master` had moved. |
| "The pinned pattern underwrites 11 of 14 trivial passes" | **Overstated and miscounted.** Corrected to the interaction claim in §1. |
| "`proof_false` = 0" | **Retracted**, §4. |
| `statement_mismatch` rejecting 28 genuine Stage B passes | Real defect: the guard assumed the dataset statement carries no preamble. Fixed with 16 tests; committed FormalStep runs unaffected. |
| 9 `proof_false` labels on Stage B | All 9 spurious — `%` misparse. Fixed with 18 tests; FormalStep labels byte-identical after. |
| "24 probe hits on the 37 FormalStep passes" | **Miscounted.** The correct figures are **40 total probe firings across 22 distinct statements** — a single statement can fire several probes, so the two numbers answer different questions. Both are given in §1; neither is 24. |

The two-machine divergence that prompted the environment work **remains
unexplained and is not recorded in any committed artifact**. Every host string
in the repository is the single generation box. The likeliest explanation is
visible in git history rather than in the Lean toolchain: `requirements.txt` was
deleted on 2026-08-11 in favour of Colab's preinstalled packages and not restored
until 2026-08-15, so for that window the two environments were different by
construction.
