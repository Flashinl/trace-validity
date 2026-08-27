# Can FormalStep be filtered to proof steps rather than calculation steps?

**Yes. Comfortably.** 254 of 500 problems (50.8%, [46.4–55.2]) have a
proof-shaped first step, against a viability threshold of 75.

Source: `tests/audit/goal_shape.py` → `results/goal_shape.json`. Purely
syntactic, no Lean, no GPU, runs in seconds over the whole split.

---

## The numbers

### A. One step per problem (n = 500) — the denominator the decision is about

| class | k/n | rate | 95% CI |
|---|---|---|---|
| **proof** | 252/500 | **50.4%** | [46.0–54.8] |
| calculation | 226/500 | 45.2% | [40.9–49.6] |
| mixed | 2/500 | 0.4% | [0.1–1.4] |
| UNKNOWN | 20/500 | 4.0% | [2.6–6.1] |

**proof + mixed = 254/500 = 50.8% [46.4–55.2].**

### B. All rows in the split (n = 30,809)

| class | k/n | rate | 95% CI |
|---|---|---|---|
| proof | 9153/30809 | 29.7% | [29.2–30.2] |
| calculation | 20823/30809 | 67.6% | [67.1–68.1] |
| mixed | 232/30809 | 0.8% | [0.7–0.9] |
| UNKNOWN | 601/30809 | 2.0% | [1.8–2.1] |

### C. Coverage

- Problems with ≥1 proof-shaped step anywhere: **494/500 = 98.8%** [97.4–99.4]
- Proof-shaped rows across the whole split: **9385/30809 = 30.5%**

---

## The decision: VIABLE

The brief's threshold was that under ~15% of 500 (fewer than 75 steps) makes the
experiment underpowered before it starts.

**We are at 254, which is 3.4× the threshold.** The margin is wide enough that
the conclusion survives substantial classifier error: even if a third of the
proof labels were wrong, the filtered set would still hold ~170 steps.

Two ways to build the set, with different properties:

| construction | steps | distinct problems |
|---|---|---|
| first proof-shaped step per problem | **254** | 254 |
| all proof-shaped steps | **9385** | 494 |

**The binding constraint is problem diversity, not step count.** 9385 steps
sounds like a lot, but they come from 494 problems, and FormalStep's train split
is entirely "Counting & Probability" — so the ceiling on independent problems is
500 regardless of how many steps are drawn. A filtered set should sample one
step per problem to avoid clustering, which puts the practical ceiling at 254.

Recommended: **254 steps, one per problem, stratified by `level`.** That is
5× the current n50 eval and 2.8× Stage B's 90.

---

## What the classifier does

Splits each `formal_statement` at the binder/goal separator and classifies the
**goal**, not the hypotheses. A step whose binders introduce variables but whose
goal reduces to closed arithmetic is a calculation.

- **calculation** — numeric (in)equality between closed terms, or over variables
  the binders pin to numerals: `(5 + 4 + 3 + 2 + 1 = 15)`,
  `Nat.factorial 4 = 24`, `(balls = 4)`, `(steps_right + steps_down = 9)`
- **proof** — quantifier, divisibility, `Finset`/cardinality, set membership,
  `Prime`/`Odd`/`Even`, limits or big operators, negation, iff, implication, or
  an (in)equality over genuinely free variables: `∃ a : ℕ, a^6 = n`,
  `(b ≥ 50)`, `triplets.card = 3`, `(∃ y ∈ s, y = 3 * x)`
- **mixed** — conjunction/disjunction with one conjunct of each kind:
  `(n! = n * (n-1)!) ∧ (0! = 1)`
- **UNKNOWN** — no relation and no proof marker; in practice almost entirely
  goals that are literally `True`

---

## Two parser bugs found and fixed while doing this

Both were producing badly wrong counts, and both are worth knowing about because
the same idioms appear elsewhere in the repo.

1. **`theorem test:` has no space before the colon.** Matching the declaration
   name with `\S*` swallowed the colon, so the statement appeared to have no
   goal at all. This alone put **13,880 of 30,809 rows (45.1%)** in UNKNOWN.
   Fixed by matching the name as `[^\s:(){}\[\]]*`.

2. **Splitting on the *last* depth-0 colon strips quantifiers.**
   `theorem foo : ∀ a : ℕ, a^6 = n` has a depth-0 colon inside the quantifier,
   so the goal came out as `ℕ, a^6 = n` and was filed as a plain equation. The
   separator is the **first** depth-0 colon, not the last.

After both fixes UNKNOWN fell from 45.1% to 2.0% across the whole split
(4.0% on the 500 first-steps, which skew shorter).

---

## Caveats

- The classifier is **syntactic**. It does not elaborate anything, so it cannot
  tell whether a goal is *hard*, only whether it is shaped like a proof
  obligation.
- Residual imprecision is visible in the hypothesis-pinning heuristic:
  `(1061520.150601 = x)` is classified `calculation` while
  `(x = 1061520.150601)` is classified `proof`, because the binder-pinning regex
  only matches one orientation. This affects a minority of equation-shaped goals
  and pushes the proof count **up**, so the true proof share is likely somewhat
  below 50.4% — but nowhere near the 15% threshold.
- Proof-shape is not the same as contentfulness. `CONTENTLESS_STEPS.md` measures
  30.5% of goals asserting nothing; that scan and this one are orthogonal, and a
  filtered proof-step set should be re-run through the vacuity probes before
  use. **This is the single most important follow-up.**
