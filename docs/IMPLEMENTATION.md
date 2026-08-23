# Implementation

How a problem becomes a verdict, what the words mean, and which versions are in
play. Written for someone joining the project cold.

The short version: we sample a formalized proof step, ask a prover model to
finish the Lean proof, compile the result against a pinned Lean + Mathlib, and
record a labelled outcome. Generation needs a GPU and no Lean. Verification
needs Lean and no GPU. They are separate commands on purpose.

---

## 1. Glossary — read this first

The call of 2026-08-20 lost time to these two terms being used
interchangeably. They are different objects, and every bug in the verifier so
far has lived in the gap between them.

### Theorem statement

The **goal** — what the verifier checks a proof *against*. It comes from the
dataset (`formal_statement`), not from the model. It is a complete Lean
declaration ending in `:= by`, for example:

```lean
theorem test (n : ℕ) (h₀ : n = 1061520150601) : ∃ a : ℕ, a^6 = n := by
```

The model never writes this and cannot change it. If Lean rejects *this*, the
model was never judged — that is the outcome `statement_error`, not a failed
proof.

### Proof object / tactic block

The **proof** — what the model generates. It is only the tactic script that
follows `:= by`:

```lean
  use 101
  norm_num [h₀]
```

On its own this is not a compilable Lean file. It has no imports, no `open`
declarations and no goal to attack. It is meaningless without the statement
above it.

### Compilation unit

The two, concatenated, with a header. This is what is actually sent to Lean:

```lean
import Mathlib                                    ┐
import Aesop                                      │ header
set_option maxHeartbeats 0                        │ (from GOEDEL_LEAN4_HEADER)
open BigOperators Real Nat Topology Rat           ┘

theorem test (n : ℕ) (h₀ : n = 1061520150601) :   ┐ theorem statement
    ∃ a : ℕ, a^6 = n := by                        ┘ (from the dataset)

  use 101                                         ┐ proof object
  norm_num [h₀]                                   ┘ (from the model)
```

**How the three get assembled is the part people get wrong.** There is no
`build_compilation_unit()` function, and there does not need to be, because the
prompt is a *prefix-completion* prompt rather than a chat prompt: it ends
mid-fence immediately after the theorem statement, and the model continues the
file. The complete unit is recovered by running the fence regex over
`prompt + completion` (`prompting.extract_lean4_block`). The header and the
statement are in the string because they were in the *prompt*.

This property is asserted, not assumed: `verify_traces.statement_mismatch()`
checks on every pass that the compiled file contains the dataset's statement
verbatim and declares exactly one theorem. It has never fired.

> Issue #11 was filed on the belief that the verifier receives the tactic block
> without the statement. It does not. See the closing comment on #11 for the
> evidence.

### A note on issue numbers in comments

Comments throughout the code cite `issue #2` through `issue #6` — the dataset
field, the prompt template, the token budget, the outcome taxonomy, the Lean
pinning. **Those issue numbers never existed in this repository.** GitHub
numbers issues and pull requests from one sequence, and #8, #9 and #10 were
taken by pull requests; #2–#6 were never created. Do not go hunting for them.
The comments that cite them explain themselves in full — the citation is the
only part that dangles.

Issue numbers cited from #11 onward are real.

### Outcome vs. failure kind

Two levels of classification, easy to confuse:

- **outcome** (`verifier.py`) — what kind of result this is: `valid`,
  `compile_error`, `has_sorry`, `statement_error`, `statement_mismatch`,
  `unsound_axioms`, `timeout`, `empty_code`, `parse_failure`,
  `verifier_crash`. Only `valid` means a proved theorem.
- **failure_kind** (`failure_taxonomy.py`) — *within* `compile_error`, what the
  compiler actually complained about: `unsolved_goals`, `tactic_failed`,
  `goal_is_false`, `unknown_identifier`, and so on.

### `has_sorry` vs `has_sorry_literal`

Also two different things, and the naming is deliberate.

- `has_sorry` — a verifier **outcome**, read from the REPL's structured
  `sorries` list. Authoritative.
- `has_sorry_literal` — a generation-side **flag**, a regex for `\bsorry\b`
  over the source. It also fires on the word inside comments and string
  literals. Never use it to decide validity.

---

## 2. The pipeline, end to end

### Generation (GPU, no Lean)

```bash
python trace_valid.py generate --temp 0 --num-samples 50 --num-trajectories 1
```

1. **Load the dataset.** `liuchengwu/FormalStep`, split `train`
   (`data_loader.py`). 30,809 rows, one row per chain-of-thought step, ~62 steps
   per problem, 500 problems.
2. **Select rows.** Default strategy `distinct_problems` takes one step from
   each of N *different* problems, striding across the ordered problem list
   (`PROBLEM_STRIDE = 10`) and taking the `first` step of each. Deterministic —
   no RNG. The `head` strategy reproduces the original behaviour, which took 50
   steps of a single problem.
   - **Note.** The train split is 100% `Counting & Probability`, all 500
     problems. There is no topic axis to stratify over; the level distribution
     is incidental, not designed.
3. **Validate fields.** `formal_statement` must be present and must parse as a
   Lean declaration. Absence is a hard error — generation without it is
   meaningless.
4. **Build the prompt** (`prompting.build_prompt`). Header + the CoT step as a
   `/-- ... -/` doc-comment + the theorem statement, inside an *unterminated*
   ```` ```lean4 ```` fence. The template is copied verbatim from the upstream
   `eval/step1_inference.py`. Do not substitute the tokenizer's
   `chat_template` — it is an inherited DeepSeek-Coder assistant template with
   nothing to do with theorem proving.
5. **Generate.** VRAM preflight, then sampling. Budget is 2048 new tokens
   inside a 4096-token total context.
6. **Recover the Lean file.** Fence regex over `prompt + completion`
   (`extract_lean4_block`). If the model never closed the fence the generation
   was cut off; the parser fallback in `parser.py` handles BPE artefacts and
   truncation heuristics.
7. **Write.** `traces/<config>/traces.jsonl`, plus `run_meta.json` recording
   git SHA, model, sampling parameters, dataset fingerprint, the realised
   selection, host and library versions, and an output sha256. A run directory
   is named for its config, so a later temperature never overwrites an earlier
   one.

### Verification (Lean, no GPU)

```bash
python verify_traces.py --traces traces/temp0.0_n50_1each/traces.jsonl \
    --out results/verify3_temp0.0.jsonl --all
```

8. **Write the environment report** (`scripts/env_report.py`) beside the output
   as `<out>.env.json`, *before* verifying, so a run that dies part-way still
   explains which environment it died in. Warnings print at the top of the run.
9. **Start the REPL.** `lean_interact` against the pinned local project.
   `import Mathlib` costs minutes, so it is imported once into a base
   environment and snapshotted to `lean_project/mathlib_env.olean_pickle`;
   later processes restore instead of importing.
10. **Compile each trace.** `set_option maxRecDepth 10000` is applied *by the
    verifier*, deliberately not added to the prompt header — verification
    config must never change what the model was asked. A snippet whose imports
    match the base set runs against the shared environment; anything else runs
    standalone so a missing import stays a real failure.
11. **Classify the outcome** (`verifier._classify`). Errors → `compile_error`.
    Structured `sorries` → `has_sorry`. No environment returned → `verifier_crash`,
    **failing closed**: a response with no messages and no environment used to
    score as a proved theorem.
12. **Audit the axioms** on a clean compile. `#print axioms <name>` must lie
    within `{propext, Classical.choice, Quot.sound}`. Asking Lean rather than
    grepping also catches an axiom pulled in through a lemma. A proof standing
    on `axiom cheat : 2 + 2 = 5` compiles perfectly and proves nothing.
13. **Check statement fidelity** on a pass — does the compiled file carry the
    dataset's statement, and exactly one declaration? Otherwise
    `statement_mismatch`.
14. **Re-test the statement** on a `compile_error`. The statement is re-verified
    alone with `sorry` as its proof. If *that* fails, Lean rejected the goal and
    never judged the model → `statement_error`, excluded from the rate rather
    than scored against the prover.
15. **Sub-classify the failure** (`failure_taxonomy.py`) into a `failure_kind`,
    and write the record **losslessly** — all errors, all warnings, with
    `num_errors` derived from what is carried.
16. **Print** the outcome distribution and the failure taxonomy table.

### Analysis

```bash
python analyze_runs.py results/verify3_temp0.0.jsonl results/verify3_temp0.2.jsonl
python classify_results.py     # failure taxonomy + arithmetic axis
```

17. **Rates** come from `stats.py` — one exclusion rule, one denominator, Wilson
    intervals. `timeout`, `verifier_crash`, `parse_failure`, `statement_error`
    and `statement_mismatch` are not verdicts on a proof: they leave **both**
    numerator and denominator, and the excluded count is always printed.
18. **Cross-tab** our verdict against the dataset's own `state` label. This is
    *not* an accuracy measurement — see the warning below.

---

## 3. What this pipeline cannot measure

**Answer correctness.** Goedel-Prover emits a Lean proof, not a final answer,
and FormalStep's `ground_truth` is the whole problem's answer, identical for
every step of that problem. The second axis of the cross-tab is the dataset's
`state` label — whether the *statement* is provable — which is a different
question from whether the model's proof compiles. Do not relabel it
"correctness".

**Whether a `valid` result is meaningful.** A proof can compile, prove the
stated goal, and stand on no untrusted axiom while still being worthless: if the
hypotheses are mutually inconsistent, `False` follows and every goal does.
Sample 42 is a confirmed instance (issue #13). 14 of 37 positives assert nothing
at all. **74% is a compile rate, not a reasoning rate**; the reasoning rate is
28%. See `results/TEMPERATURE_AND_VACUITY.md`.

---

## 4. Versions in use

### Prover model

| | |
|---|---|
| Name | `Goedel-LM/Goedel-Prover-SFT` |
| Architecture | Llama, ~6.9B parameters |
| Total context | 4096 tokens (`max_position_embeddings`, no rope scaling) |
| Generation budget | 2048 new tokens (`MAX_NEW_TOKENS`) |
| `top_p` | 0.95, from the official `eval/step1_inference.py` |
| Weights | ~13.8 GB in fp16, plus ~2.0 GB KV cache at full context |

### Where generation actually ran — correcting a standing belief

**Generation did not run in Colab.** The team currently believes otherwise. The
committed runs were produced on a **Lambda Labs A10 Linux box**, recorded in
`traces/temp0.0_n50_1each/run_meta.json`:

| | |
|---|---|
| hostname | `150-136-51-18` |
| platform | `Linux-6.8.0-60-generic-x86_64-with-glibc2.35` |
| GPU | NVIDIA A10, 22.07 GiB |
| Python | 3.10.12 |
| torch / transformers / datasets | 2.7.0 / 4.46.3 / 3.6.0 |

`colab_run.sh` exists and is maintained, but **no committed run used it**. If
you do run in Colab, note that Colab cells do not source the shell profile, so
`~/.elan/bin` is not on `PATH`; `verifier.py` prepends it at import and
`colab_run.sh` also symlinks `lake`, `lean` and `elan` into `/usr/local/bin`.

Verification is a separate host and needs no GPU. The committed verification
passes were produced on Windows 11 / Python 3.13.

### Lean toolchain and Mathlib

| Component | Pin | Resolved |
|---|---|---|
| Lean toolchain | `leanprover/lean4:v4.32.0` | Lean 4.32.0, commit `8c9756b28d64dab0` |
| Lake | — | 5.0.0-src+8c9756b |
| Mathlib | tag `v4.32.0` | `81a5d257c8e410db227a6665ed08f64fea08e997` |
| REPL | `augustepoiroux/repl` @ `v1.3.18` | tag `v1.3.18_lean-toolchain-v4.32.0` |
| `lean_interact` | `0.11.5` | |

**These three must move together.** `lean_interact` selects its REPL by checking
out `{repl_rev}_lean-toolchain-{lean_version}`. That rev publishes 94 such tags,
topping out at `v4.32.0` — there is **no `v4.32.2` tag**, so a project on Mathlib
v4.32.2 runs against a mismatched REPL and produces `unexpected token` /
`unknown constant`. A mathlib4 tag `vX.Y.Z` always declares
`leanprover/lean4:vX.Y.Z`, so naming the Mathlib tag after the Lean version is
what keeps all three aligned. The same argument rules out `-rc` toolchains.

### Not fully pinned — known gap

Mathlib pulls seven transitive Lean dependencies whose `inputRev` is a **branch**
rather than a tag: `aesop` and `Qq` on `master`; `batteries`, `plausible`,
`proofwidgets`, `importGraph` and `LeanSearchClient` on `main`. The committed
`lake-manifest.json` records the resolved revisions, so they hold as long as
nothing re-resolves them. `lake update` re-resolves and rewrites the manifest,
which is why `setup_lean_project()` now runs it **only when there is no manifest
to honour** (issue #16). `scripts/env_report.py` reports every resolved revision
and warns about the floating ones.

`aesop` matters most: the prompt header imports it, and its tactic behaviour can
change a verdict.

---

## 5. Setup notes that are not optional

**Windows: add Defender exclusions before loading Mathlib.** Mathlib is ~8,600
`.olean` files. With real-time protection scanning each read, loading measured
**7 KB/s at 0% CPU and never completed**. With exclusions it loads in ~182s.
This is worth about 2.6x — far more than the environment snapshot, which saves
only ~6% in an unexcluded path. See the README for the exact
`Add-MpPreference` commands. Linux needs none of this.

**Do not resolve a pip conflict by dropping a pin.** Unpinned,
`pip install transformers` resolves to 5.x on a fresh GPU image and the model
import dies with `Could not import module 'LlamaConfig'` before a single
trajectory is generated. `torch` is deliberately unpinned because its CUDA build
must match the host driver.

**Check for drift before trusting a comparison:**

```bash
python scripts/env_report.py
```

---

## 6. Where things live

| file | |
|---|---|
| `trace_valid.py` | CLI: `generate` / `run` / `analyze` |
| `config.py` | model, dataset, selection, Lean pins, token budget |
| `data_loader.py` | FormalStep loading and sample selection |
| `prompting.py` | prompt rendering, Lean-block extraction |
| `model.py` | VRAM preflight, generation, truncation flags |
| `parser.py` | BPE repair, truncation heuristics, fallback extraction |
| `generate.py` | trajectories → JSONL + `run_meta.json` |
| `verify_traces.py` | traces → verification JSONL |
| `verifier.py` | pinned project, shared Mathlib env, outcome taxonomy |
| `failure_taxonomy.py` | `compile_error` sub-classification + arithmetic axis |
| `classify_results.py` | re-classify committed runs, join provenance |
| `scripts/env_report.py` | every version-bearing component |
| `stats.py` | denominators, Wilson intervals, McNemar |
| `analyze_runs.py` | per-run report, cross-tab, paired comparison |
