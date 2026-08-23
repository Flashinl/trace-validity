# What the 74% actually contains, and what temperature actually changed

Two questions the summary could not answer, now answered by asking Lean rather
than by reading.

- Vacuity scan: `tests/audit/vacuity_scan.py` → `results/vacuity_scan.json`
- This document: `tests/audit/temp_analysis.py`
- Verification pass: `results/verify3_temp0.{0,2}.jsonl`

---

## 1. HEADLINE: sample 42 is a false positive

Issue #1 asks the project to "debug for lean4 validity check (whether getting
false positives like invalid traces showing up as valid in the checker)".
**Here is one.**

```lean
theorem factorial_division
  (h₀ : 9! * 5! * 2! = 7257600)
  (h₁ : 8! * 6! = 40320)
  (h₂ : 7257600 / 40320 = 9) :
  (9! * 5! * 2!) / (8! * 6!) = 9 := by
```

Every hypothesis is arithmetically false, and so is the goal:

| claim | asserted | actual |
|---|---|---|
| `9! * 5! * 2!` | 7,257,600 | **87,091,200** |
| `8! * 6!` | 40,320 | **29,030,400** |
| `7257600 / 40320` | 9 | **180** |
| `(9!*5!*2!)/(8!*6!)` — **the goal** | 9 | **3** |

The premises are mutually inconsistent, so `False` follows from them and
therefore **every** goal does. Lean confirms it: the probe
`theorem contra (h₀ …) (h₁ …) (h₂ …) : False := by simp_all` succeeds. The
model's proof (`simp_all [factorial] <;> norm_num <;> rfl`) works precisely
because `simp_all` finds the contradiction.

- Our verdict: **`valid`**
- Dataset `state`: **Success of Proof**
- Axiom audit: `axioms: propext` — clean, so the axiom check cannot catch this

A trace proving a **false statement** from **contradictory premises** counts
toward the 74%, at both temperatures, and the dataset agrees it is a success.
This is the exact failure mode issue #1 was opened to find. No prior pass caught
it — the earlier hand-read of this sample classified it `proves_target`. Only
asking Lean whether the hypotheses are consistent found it.

---

## 2. Vacuity scan: what do the 37 positives assert?

Every probe replaces the model's proof entirely, so this measures the *dataset's
goal*, not the model's work. `with_reducible rfl` is the load-bearing choice: it
closes `X = X` but will not unfold `Nat.factorial 4` to `24`, which is what
separates "asserts nothing" from "asserts a real computation".

| class | T=0.0 | T=0.2 | what it means |
|---|---|---|---|
| `1_goal_is_True` | **2** | **2** | goal is literally `True` |
| `2_hypotheses_contradictory` | **1** | **1** | premises inconsistent — **anything** is provable |
| `3_goal_restates_a_hypothesis` | **3** | **3** | goal IS a hypothesis, verbatim (`assumption` closes it) |
| `4_syntactic_tautology` | **8** | **8** | substituting its own hypotheses makes the goal `X = X` |
| `5_ground_computation` | **9** | **9** | closed by `rfl`/`decide` — real arithmetic, no reasoning |
| `6_contentful` | **14** | **14** | needs the hypotheses in a non-trivial way |

**14 of 37 positives (38%) assert nothing at all.** Another 9 are ground
arithmetic. Only 14 of 37 (38%) require a real inference.

Rewritten as rates over all 50 samples:

| claim | count | rate |
|---|---|---|
| produced a compiling Lean proof of the target | 37/50 | **74%** |
| …of a goal that asserts *something* | 23/50 | **46%** |
| …of a goal needing more than ground arithmetic | 14/50 | **28%** |

**74% is a compile rate. The content rate is 46%, and the reasoning rate is 28%.**

The scan is deliberately conservative — it classifies only what it can *prove*
vacuous, so these are lower bounds. Two cases it under-called, found by reading:
sample 22's conclusion (`5*6*8 + 5*6*8 = 480`) uses none of its five bound
variables and none of the numbers in its own hypotheses; sample 3's goal is the
conjunction of its own four hypotheses. Both scored `6_contentful` because the
probes cannot strip an implication or split a conjunction.

### The vacuous ones, named

| sample | class | goal |
|---|---|---|
| 2 | `4_syntactic_tautology` | `(3 ^ friends = 3 ^ 6)` |
| 4 | `4_syntactic_tautology` | `(first_digit * second_digit = 12)` |
| 6 | `4_syntactic_tautology` | `slots = 6` |
| 13 | `4_syntactic_tautology` | `(boys * girls + girls * boys = 200)` |
| 15 | `1_goal_is_True` | `(True)` |
| 17 | `1_goal_is_True` | `True` |
| 20 | `4_syntactic_tautology` | `(6 / 6 = 1)` |
| 23 | `3_goal_restates_a_hypothesis` | `(n = 6)` |
| 25 | `4_syntactic_tautology` | `(total_outfits - same_color_outfits = 210)` |
| 31 | `3_goal_restates_a_hypothesis` | `(p = 1 / 6)` |
| 37 | `3_goal_restates_a_hypothesis` | `(edges_from_A = 3)` |
| 38 | `4_syntactic_tautology` | `(total_count - non_five_count = 600 - 6 * 9 * 9)` |
| 42 | `2_hypotheses_contradictory` | `(9! * 5! * 2!) / (8! * 6!) = 9` |
| 47 | `4_syntactic_tautology` | `(5 = 5)` |

---

## 3. Temperature: 80% of proofs were rewritten, 5% of verdicts moved

The summary reported McNemar p = 1.000 on 2 discordant pairs and called it
"no power". True, but incomplete: it never asked whether T=0.2 changed the
generations at all. It did, substantially.

| | n | % |
|---|---|---|
| generations byte-identical to T=0.0 | 10/50 | 20% |
| **generations materially different** | **40/50** | **80%** |
| …of those, verdict UNCHANGED | 38/40 | **95%** |
| …of those, verdict flipped | 2/40 | 5% |

Character-level similarity of the 40 differing pairs: median **0.717**,
minimum **0.448** (sample 13). These are not cosmetic reorderings —
the least similar pairs share under half their characters, i.e. genuinely
different proofs of the same goal.

**This turns the temperature result from an absence of evidence into a positive
one.** The model rewrote 80% of its proofs, often substantially, and
95% of those landed on the identical verdict. The outcome is robust to how
the proof is written.

### And section 2 explains why

The vacuity classification is **identical at both temperatures — all six counts
match exactly.** That is not coincidence. Temperature changes the *proof*; the
*goal* is fixed by the prompt; and section 2 shows the goal is what decides the
outcome. 14 of 37 goals cannot be failed and 9 more are closed by evaluation, so
there is very little left for sampling to move.

So "temperature makes no difference" is not a null result about the model. It is
a statement about **this benchmark**: the goals are too easy for decoding
strategy to matter.

### The two that flipped

- **Sample 0**: `valid` at T=0.0 → `compile_error` at T=0.2 (text similarity 0.629)
- **Sample 35**: `compile_error` at T=0.0 → `valid` at T=0.2 (text similarity 0.668)

Both are single samples with no replication, and they cancel exactly — which is
why the aggregate is 37/50 at both temperatures.

---

## 4. Trajectories: the 500-record baseline is 50 records

`traces/temp_0.jsonl` holds 500 records: 50 samples × 10 trajectories.

| | value |
|---|---|
| samples whose 10 trajectories are ALL byte-identical | **50/50** |
| distinct generations in the file | **50** of 500 |
| exact duplicates | **450** (90%) |

Greedy decoding is deterministic, so all ten trajectories per sample are the same
bytes. **90% of that file is duplication.** It cost 10× the generation time for
zero additional information, and any statistic computed over its 500 rows as if
they were independent has an effective n of 50, not 500.

That is why the current runs use one trajectory per sample — correct at T=0.0.
It is also why T=0.2 needs *more* than one: at T>0 trajectories genuinely differ
(section 3 measures how much), and multiple draws per sample is the only design
under which a temperature effect could be detected at all.

---

## What this changes

| claim | before | after |
|---|---|---|
| validity | 37/50 = 74% | unchanged — but it is a **compile** rate |
| content | not measured | **23/50 = 46%** assert something |
| reasoning | not measured | **14/50 = 28%** need more than arithmetic |
| false positives | "zero" | **at least one confirmed — sample 42** |
| vacuous positives | 1, hand-found | **14 of 37**, Lean-verified, a lower bound |
| temperature | "no power" | 80% of proofs rewritten, 95% same verdict |
| baseline set | 500 traces | **50 traces**, 90% duplication |
