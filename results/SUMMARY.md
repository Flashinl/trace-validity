# Verifier debugging — first result

Issue #1 ("Debug the trajectory to lean4 code validity process"), covering #5 and #6.
Branch `fix/verifier-debug`. All numbers below come from real runs; nothing is estimated.

Environment: Lean 4.32.0, Mathlib `81a5d257c8e4` (tag `v4.32.0`), REPL
`augustepoiroux/repl v1.3.18_lean-toolchain-v4.32.0`, Windows 11, single process.

---

## 1. Outcome distribution — 50 generated traces

`results/verification_temp_0.jsonl`

| outcome | n | % |
|---|---|---|
| `valid` | 21 | 42.0% |
| `compile_error` | 29 | 58.0% |
| `has_sorry` | 0 | 0% |
| `empty_code` | 0 | 0% |
| `timeout` | 0 | 0% |
| `parse_failure` | 0 | 0% |
| `verifier_crash` | 0 | 0% |

**50 verifications in 7.7s (0.15s each.)**

One trajectory per sample was verified. At temperature 0 the 10 trajectories per
sample are byte-identical (measured: 50/50 samples), so verifying all 500 would
repeat each result 10x.

## 2. Control set — can the verifier be trusted?

`tests/fixtures/control_set.jsonl` (32 hand-labelled snippets), `results/control_set_run.json`

```
               |    valid empty_co has_sorr compile_  timeout
---------------------------------------------------------------
valid          |       11        .        .        1        .
empty_code     |        .        3        .        .        .
has_sorry      |        .        .        5        .        .
compile_error  |        .        .        .       11        .
timeout        |        .        .        .        1        .
---------------------------------------------------------------
agreement: 30/32 = 93.8%     32 verifications in 4.3s (0.14s each)
```

**Both mismatches were bad labels of mine, not verifier bugs.** Lean's judgement
was correct in all 32 cases.

- `pipeline_01` — I mis-transcribed the fixture as `use 101; rw [h₀]` when the
  model emitted `use 101; norm_num [h₀]`. My version genuinely does not close the
  goal. Fixture corrected.
- `timeout_01` — `decide` on a large prime failed fast with `maximum recursion
  depth` instead of hanging, so **the `timeout` path is still UNTESTED**. Fixture
  now raises `maxRecDepth`, but this remains unconfirmed and is marked
  `confidence: low`. Do not claim timeout handling works.

## 3. Cross-check against the dataset — independent of the model

`results/crosscheck.json`. FormalStep ships a reference `proof` only for steps it
could prove, so an empty one is the dataset's own statement that a step is not
provable. Note these are **different questions**: the dataset says whether the
*statement* is provable; we say whether *this model's proof* compiles.

| | n | % |
|---|---|---|
| agree, provable & we said `valid` | 21 | 42% |
| agree, unprovable & we said not-valid | 23 | 46% |
| model failed on a provable statement | 6 | 12% |
| **we certified an unprovable statement** | **0** | **0%** |

**Zero false positives.** We never returned `valid` for a statement the dataset
could not prove — the direction that would most damage the paper.

The 23 "agree_unprovable" cases are mostly CoT steps that are *mathematically
false*, so the formal statement is unprovable and `compile_error` is correct.
E.g. sample 2 claims `1061520150601 = 1.061520150601 × 10⁹` (off by 1000×) and
sample 4 claims `1061520.150601 = 10303 × 103` (actually 1,061,209).

## 4. Verdicts I believe may be wrong

Read all 6 "model failed on a provable statement" cases by hand.

**Sample 15 — DISPUTED. The proof is mathematically complete.**

```lean
rw [h₀, h₁, h₂]
norm_num
```
`rw` closes the goal by itself (it attempts `rfl` after rewriting), so `norm_num`
runs with nothing left and Lean errors `No goals to be solved`. The file does not
compile, so `compile_error` is *literally* right — but the model did prove the
theorem, and the only defect is one superfluous trailing tactic.

Sharpening it: the dataset's own reference proof is
`rw [h₀, h₁, h₂] <;> norm_num <;> linarith`. The `<;>` combinator applies to all
remaining goals — zero of them — so it does not error. **The difference between
valid and invalid here is `<;>` versus a newline.** Whether such a trace counts
as a faithful CoT is a research judgement, not a verifier bug, and it should be
decided deliberately rather than by accident of tactic separator.

**Samples 11, 14, 35, 44 — verdict correct.** Genuine model failures: unsolved
goals with nested radicals (11), a type mismatch from misapplying a hypothesis
(14), and `norm_num`/`linarith` failing to close (35, 44).

**Sample 27 — verdict correct, but worth a second look.** `rw [h₀]` failed with
"did not find an occurrence of the pattern `1061520150601` in the target
expression `a = 1061520150601`", which is surprising since the literal is visibly
present. Likely a numeral-elaboration subtlety in ℝ. The proof still fails either
way, so the outcome stands, but I am not fully confident I understand *why*.

## 5. False-negative and false-positive mechanisms found

Directly answering the supervisor's ask.

**Genuinely valid, reported invalid** — two mechanisms, both fixed:

1. **`sorry` detected by regex.** `\bsorry\b` over source text matches the word in
   comments, string literals and identifiers. Three control fixtures
   (`sorrylike_01..03`) are complete, correct proofs that the old regex would
   have marked `has_sorry`. Fixed by using the REPL's structured `sorries` list;
   all three now return `valid`.
2. **The parser drops the theorem.** `parse_output` runs on the *completion*, but
   the theorem statement lives in the *prompt*. Measured on 5/5 traced samples:
   `found_declaration=False`, `theorem_name=None`. Verifying the parser's output
   instead of fence-extracted `prompt + completion` would fail **every** trace —
   a 100% false-negative rate. `generate.py`'s `full_code` avoids this.

**Genuinely invalid, reported valid** — one mechanism, fixed:

3. **Declaration-free code compiles.** A header with no theorem compiles cleanly
   while proving nothing (`empty_03`). Previously that is `valid`; now
   `empty_code`.

## 6. Speed (issue #5, step 5)

| | before | after |
|---|---|---|
| Mathlib import | once per verification | once per process, then snapshotted |
| per verification | ~30 min reported | **0.14–0.15s** |
| 20 control verifies | — | **~3s** (target was <5 min) |

The fix is reusing one imported environment instead of re-importing Mathlib per
call. Remaining per-process overhead is ~356s (≈128s to restore the environment
snapshot, the rest `lake build` re-checking) — worth attacking next if the
verifier is invoked repeatedly.

Separately: on Windows, Defender scanning ~8,600 `.olean` files made Mathlib
effectively unloadable (measured 7 KB/s, 0% CPU). Directory exclusions took the
load from "hours, never completed" to 182s. This is environment setup, not code,
and belongs in the README.

## 7. Known gaps — do not report these as done

- **`timeout` outcome path is untested.** No fixture has yet produced one.
- **`parse_failure` and `verifier_crash` paths are untested.** No case exercised them.
- **Only 1 of 10 trajectories per sample verified** (the other 9 are identical at
  temperature 0). Untrue for temperature > 0.
- **`invalid_accuracy` is still degenerate.** Documented, not silently redefined;
  corrected definition proposed in the PR body.
- **`state` field is not carried into trace records**, so provability is inferred
  from `reference_proof` being empty rather than read from the dataset's label.
- Results here are a single temperature (0) on 50 samples. No sweep.
