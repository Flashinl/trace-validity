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

`tests/fixtures/control_set.jsonl` (35 hand-labelled snippets), `results/control_set_run.json`

```
               |    valid empty_co has_sorr compile_  timeout
---------------------------------------------------------------
valid          |       12        .        .        .        .
empty_code     |        .        5        .        .        .
has_sorry      |        .        .        5        .        .
compile_error  |        .        .        .       12        .
timeout        |        .        .        .        .        1
---------------------------------------------------------------
agreement: 35/35 = 100.0%    35 verifications in 185.8s (5.31s each)
```

The 185.8s total is dominated by the single deliberate `timeout` fixture (52.1s);
the other 34 took ~3.9s combined.

Every outcome in the taxonomy is now exercised by at least one fixture except
`verifier_crash`:

| outcome | covered | by |
|---|---|---|
| `valid` | yes | 12 fixtures |
| `compile_error` | yes | 12 fixtures |
| `has_sorry` | yes | 5 fixtures |
| `empty_code` | yes | 5 fixtures |
| `timeout` | **yes** | `timeout_01`, fired at 52.1s |
| `parse_failure` | partly | `parse_01/02` reach `empty_code` via the verifier; the `parse_failure` label itself is emitted by `verify_traces.py` when fence extraction yields nothing |
| `verifier_crash` | **no** | untested |

**The timeout path is confirmed working.** `timeout_01` (`decide` on a 10-digit
primality goal with raised `maxRecDepth`) was killed at the 45s budget and
recorded as `timeout`, not `compile_error`. Fixtures 33–35 ran *after* it and
passed, which also confirms the post-timeout REPL restart works — previously
untested.

An earlier run scored 30/32 with two mismatches; **both were bad labels of mine,
not verifier bugs** (a mis-transcribed proof in `pipeline_01`, and a `timeout`
fixture that failed fast on recursion depth instead of hanging). Both fixtures
were corrected and now pass.

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

### 3a. Provability, measured rather than assumed

`results/reference_proofs.json`. "Has a reference proof" is the dataset's claim.
`tests/verify_reference_proofs.py` compiles those proofs so the ground-truth axis
is measured. This also exercises the verifier on code no model wrote, so a
failure here would implicate our setup rather than the prover.

| | n | % |
|---|---|---|
| reference proof compiles | 26 | 96.3% |
| reference proof fails | 1 | 3.7% |

**26/27 compiling is strong evidence the pinning and headers are correct** — a
broken setup would fail most of them, not one.

The single failure is **sample 14** (`simp` made no progress), and it is one of
the six "model failed on a provable statement" cases. Its statement's provability
is therefore **UNKNOWN**, not provable: the dataset's proof is likely stale for
Mathlib v4.32.0. Corrected partition:

| | n |
|---|---|
| statement provable (verified) AND our verdict `valid` | 21 |
| statement provable (verified), model's proof failed | 5 |
| statement provability UNKNOWN (ref proof stale) | 1 (sample 14) |
| no reference proof — statement presumed unprovable | 23 |

So the model failed on **5** verified-provable statements, not 6.

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

- **`verifier_crash` path is untested.** Nothing has exercised it. Every other
  outcome in the taxonomy now has at least one passing fixture.
- **Only 1 of 10 trajectories per sample verified.** Sound only because
  temperature-0 trajectories are byte-identical (measured 50/50). **Not valid for
  temperature > 0** — a sweep must verify all trajectories.
- **`invalid_accuracy` is still degenerate in the code.** Documented at the source
  lines with a guard assertion; deliberately not silently redefined. Corrected
  definition proposed in the PR body, awaiting a decision.
- **`state` is not carried into trace records**, so provability comes from
  `reference_proof` rather than the dataset's explicit label. Fixing this touches
  the generation path, out of scope for this session.
- **Sample 15's verdict is a judgement call, not a fact** (see §4). If the project
  decides trailing no-op tactics should not invalidate a trace, the `valid` count
  becomes 22/50 rather than 21/50.
- **Sample 27 is not fully understood.** The outcome is right but the underlying
  `rw` failure on a visibly-present numeral is unexplained.
- Single temperature (0), 50 samples, one model. No sweep, no baseline.

## 8. Reproducing

```bash
python tests/test_verifier.py --out results/control_set_run.json   # confusion matrix
python verify_traces.py --out results/verification_temp_0.jsonl    # 50 traces
python tests/crosscheck_dataset.py                                 # vs dataset
python tests/verify_reference_proofs.py                            # compile dataset proofs
python tests/trace_pipeline.py --n 5                               # per-stage dump
```

Each script pays a one-time ~6 min Mathlib load (≈128s of which is restoring the
environment snapshot, the rest `lake build` re-checking) before its
sub-second-per-verification work. On Windows the Defender exclusions in the
README are mandatory, not optional.
