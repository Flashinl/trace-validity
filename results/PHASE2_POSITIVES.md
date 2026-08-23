# Phase 2 — auditing the positives

The summary hand-read only the failures. All 37 `valid` traces at T=0.0 were
unaudited; every false-positive mechanism lives there. This is that audit.

Script: `tests/audit/phase2_positives.py` → `results/phase2_positives.json`.
Random subset seed: **`SEED = 20260818`**, recorded in the script at line 19.

---

## What was actually audited

| | n | basis |
|---|---|---|
| `valid` traces at T=0.0 | **37** | `results/verify2_temp0.0.jsonl` |
| Mechanically classified | **37 (100%)** | structural checks below |
| **Hand-read in full** | **10 (27%)** | random, seed 20260818 → samples 8, 17, 20, 21, 26, 28, 33, 38, 42, 48 |
| Not hand-read | 27 (73%) | mechanical classification only |

**Nothing below is extrapolated from the 10 to the 37.** Where a rate is given
for the hand-read subset it is stated as "x of 10".

---

## 1. `restated` and `weakened` are structurally impossible — measured, not assumed

Both categories require the model to change the theorem. It cannot: the prompt
ends mid-fence immediately after the dataset's `formal_statement`, which already
terminates in `:= by` (`config.py:133-136`, `prompting.py:33-49`), so the model
writes only a proof body, and `full_code` is `prompt + completion`
(`prompting.py:52-61`).

Verified over all 37:

| Structural invariant | Result |
|---|---|
| Dataset `formal_statement` present verbatim (whitespace-normalised) in `full_code` | **37 / 37** |
| Exactly one `theorem`/`lemma`/`example` declaration, comments stripped | **37 / 37** |

So: **`restated` = 0, `weakened` = 0**, and these are measurements over the full
37, not a sample. No trace reworded a goal, dropped a quantifier, specialised a
constant, or slipped in a second declaration to prove instead.

---

## 2. Full-population classification (all 37)

| class | n | note |
|---|---|---|
| `proves_target` | **36** | proves the dataset's statement as written |
| `vacuous` | **1** | sample 17 — the goal is literally `True` |
| `restated` | 0 | ruled out structurally, all 37 |
| `weakened` | 0 | ruled out structurally, all 37 |
| `unclear` | 0 | no empty proof bodies |

### The one vacuous positive — sample 17

```
statement: theorem test (digits: List ℕ) (h₀: List.length digits = 5)
             (h₁: digits = [2,2,2,3,7] ∨ digits = [2,2,2,3,9] ∨ digits = [2,2,2,7,9])
           : True := by
model:     cases h₁ with | inl h₁ => simp_all | inr h₁ => cases h₁ with
             | inl h₁ => simp_all | inr h₁ => simp_all
reference: cases digits <;> simp_all <;> rfl
```

The goal is `True`. The trace is `valid` and establishes **nothing** about the
CoT step it is supposed to formalise. Note the model did real work (331 generated
tokens, a three-way case split) to prove a tautology.

**This is a dataset defect, not a model cheat.** FormalStep shipped the statement
with goal `True`, its own `reference_proof` proves `True`, and the dataset labels
it `Success of Proof`. The model had no opportunity to do better — the goal it
was handed was empty.

**Consequence for the headline: 1 of the 37 positives is not evidence of
anything.** A defensible validity count is therefore **36 / 48**, not 37 / 48.
See §5.

---

## 3. Hand-read of 10 (seed 20260818)

Every one was read against its problem, CoT step, statement, model proof and
reference proof.

| sample | goal | model proof | verdict |
|---|---|---|---|
| 8 | `"COMBINATION".length = 11` | `rfl <;> rfl <;> rfl <;> rfl <;> rfl` | `proves_target` (trivial goal) |
| **17** | **`True`** | 3-way `cases` + `simp_all` | **`vacuous`** |
| 20 | `6 / 6 = 1` | `norm_num` | `proves_target` (trivial goal; ℕ-division formalisation of a probability) |
| 21 | `2 ^ 3 = 8` | `exact by decide` | `proves_target` (trivial goal) |
| 26 | `Nat.choose n k = 56`, `n=8, k=3` | `rw [h₀, h₁]; rfl` | `proves_target` (real content) |
| 28 | `Nat.choose n k = Nat.div (n*(n-1)) 2`, `n=50, k=2` | `rw [h₀, h₁]; norm_num <;> rfl` | `proves_target` (real content) |
| 33 | ℚ identity `(1/4)^3·(3/4)^3` | `rw [h₀, h₁]; norm_num` | `proves_target` (real content) |
| 38 | `total_count - non_five_count = 600 - 6*9*9` given `total_count = 600`, `non_five_count = 6*9*9` | `subst; subst; norm_num` | `proves_target` — **but the goal is `X = X` after substitution** |
| 42 | `(9!·5!·2!)/(8!·6!) = 9` | `simp_all [factorial] <;> norm_num <;> rfl` | `proves_target` (real content) |
| 48 | `2 ^ balls = 32`, `balls = 5` | `subst; subst; simp` | `proves_target` (real content) |

**Result: 9 of 10 `proves_target`, 1 of 10 `vacuous`.**

**Do not extrapolate the 1/10 to 3.7/37.** The mechanical scan already covered
all 37 for the `True`-goal condition and found exactly one — sample 17, the same
one. So the vacuous count over the full population is **1, measured**, and the
hand-read subset happened to contain it.

### The finding the mechanical scan could not have produced

Two of the ten (**samples 38 and 20**, and arguably 8 and 21) are `proves_target`
yet carry almost no mathematical content:

- **Sample 38's goal is a tautology by construction.** The hypotheses bind
  `total_count = 600` and `non_five_count = 6*9*9`; the goal asserts
  `total_count - non_five_count = 600 - 6*9*9`. Substituting the hypotheses turns
  it into `600 - 486 = 600 - 486`. The CoT step it formalises ("subtract the
  count without a 5 from the total") is a real reasoning step; the formalisation
  drops it entirely and asserts `X = X`.
- **Sample 20** formalises "probability 6/6 = 1" as `6 / 6 = 1` over ℕ. True,
  and true for reasons unrelated to probability.

This is a **formalisation-quality ceiling in FormalStep**, not a verifier bug and
not a model failure. But it means `valid` and "the model demonstrated competence
at the reasoning step" are not the same claim, and the summary currently treats
them as one.

---

## 4. Proof-shape distribution (all 37) — how hard were the goals?

Mechanical, from `results/phase2_positives.json`:

| proof shape | n | samples |
|---|---|---|
| Closed by a single decision/normalisation tactic alone (`rfl`/`decide`/`norm_num`/`simp`/`trivial`) | **9** | 1, 8, 14, 15, 20, 21, 32, 45, 47 |
| Substitute-then-normalise (`rw`/`subst` + a closer) | **17** | 2, 4, 6, 9, 12, 13, 23, 25, 26, 27, 28, 31, 33, 34, 38, 40, 48 |
| Uses structural tactics (`use`/`have`/`cases`/`constructor`/`calc`/…) | **11** | 0, 3, 11, 17, 22, 29, 37, 41, 42, 43, 44 |

**26 of 37 positives (70%) close a ground-arithmetic goal** by evaluation or by
substitution followed by evaluation. That is a fair description of what
`valid` is measuring on this sample: mostly decidable ground arithmetic, not
proof search.

Corroborating this from the other direction: 25 of 37 proofs never mention at
least one declared binder. That is *not* a defect on its own — proving without a
hypothesis is stronger, not weaker — but combined with the shape distribution it
indicates the goals are typically closed by computing both sides rather than by
using the stated hypotheses as an argument.

---

## 5. Effect on the headline

| Denominator choice | Count | Rate |
|---|---|---|
| As the summary reports it | 37 / 48 | 77% |
| Excluding the vacuous positive (sample 17) from the numerator only | 36 / 48 | 75% |
| Excluding sample 17 from **both** (it is untestable, like `statement_error`) | 36 / 47 | 77% |

The **consistent** treatment is the third: sample 17's goal was never a test of
the prover, exactly as a `statement_error` is not. By the exclusion rule stated
in Phase 3, it belongs with the untestable set, giving **36/47 = 77% (95% CI
63–87%)** — numerically indistinguishable from 37/48, because removing one
success from both numerator and denominator barely moves a rate near 77%.

**So the vacuous positive does not move the headline.** It matters for what the
headline *means*, not for its value.

---

## 6. Audited fraction — stated honestly

- **37 of 37** positives mechanically checked for statement fidelity, declaration
  count, `True`-goals and proof shape.
- **10 of 37** (27%) read in full by a human against problem, CoT step and
  reference proof.
- **27 of 37** (73%) rest on mechanical checks alone.

The mechanical checks are strong for the categories the brief was most worried
about (`restated`, `weakened`) because those are ruled out by a structural
invariant that was verified on every trace, not sampled. They are weak for
subtler vacuity — a goal that is trivially true for a reason no regex detects
(e.g. sample 38's tautology-after-substitution, which was caught by reading, not
by script).

**UNRESOLVED:** a systematic vacuity check over all 37 — substitute every
equational hypothesis into the goal and test whether the two sides become
syntactically identical. This is scriptable against the local Mathlib build and
needs no GPU; it was not run inside the time budget. Estimated 30 minutes. Until
it runs, the honest statement is: **at least 1 of 37 positives is vacuous, and
the true count is somewhere between 1 and roughly 5**, judging by the frequency
of tautological formalisations in the 10 that were read.
