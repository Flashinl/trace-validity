# Phase 4 — cross-branch comparison

Is any other branch doing this better, and is any doing it worse?
All rows verified with `git show <branch>:<file>` / `git grep <pattern> <branch>`.
Audit branch base: `merge/analysis-into-code-validity` @ `64fba01` ("HEAD" below).

---

## The matrix

| Check | `master` (`211d9f8`) | `code-validity` (`8560786`) | `fix/generation-input-path` PR #8 (`21c6842`) | `fix/verifier-debug` PR #9 (`2253334`) | **HEAD** PR #10 (`64fba01`) |
|---|---|---|---|---|---|
| **Dataset field fed to model** (issue #2) | ❌ **`item["problem"]`** — the English prose (`data_loader.py:17`) | ❌ **`item["problem"]`** — prose (`data_loader.py:17`) | ✅ `formal_statement`, normalised (`data_loader.py:35`) | ✅ same | ✅ same |
| **Prompt templating** (issue #3) | ❌ no `PROMPT_TEMPLATE` in `config.py` | ❌ none | ✅ `PROMPT_TEMPLATE` present, verbatim from upstream `step1_inference.py` | ✅ same | ✅ same |
| **Token budget** (issue #4) | ❌ `MAX_NEW_TOKENS = 20000` vs a 4096 context | ❌ `20000` | ✅ `2048`, `MODEL_MAX_CONTEXT = 4096` | ✅ same | ✅ same |
| **Lean pinning** (issue #6) | ❌ no `LEAN_VERSION` / `MATHLIB_REV` | ❌ none | ⚠️ `LEAN_VERSION = "v4.32.0"`, `MATHLIB_REV = LEAN_VERSION` — **tag only** | ⚠️ tag only | ⚠️ tag only → **fixed in this audit**, see below |
| **Outcome taxonomy** | ❌ none (boolean) | ❌ none | ❌ none | ✅ 7 outcomes | ✅ **8** (adds `statement_error`) |
| **`answer_correct` degenerate def** (issue #5) | ❌ present, documented in README schema | ❌ present + in `verify_traces.py` | ❌ still present | ⚠️ still **written** at `trace_valid.py:97` | ⚠️ **still written** at `trace_valid.py:97` |
| **Analysis entry point** | `analysis.py` only | `analysis.py` only | `analysis.py` only | ✅ `analyze_runs.py` (authoritative) | ✅ `analyze_runs.py` |
| **Seed handling for T>0** | ❌ not recorded | ❌ not recorded | ✅ `run_meta.json` records `seed: 0`, `top_p: 0.95`, `do_sample` | ✅ same | ✅ same |
| **Generation commit SHA** | ❌ not recorded | ❌ not recorded | ⚠️ `git_state()` added but recorded `null` on the actual runs | ✅ + `CODE_VERSION` fallback and `git.source` (`generate.py:62-93`) | ✅ same |

---

## Per-branch verdict

### `master` @ `211d9f8` — **IGNORE (do not merge, do not cite)**

Feeds `item["problem"]` — the natural-language problem text — to a theorem
prover as its Lean prompt (`data_loader.py:17`). This is issue #2, and it is
fatal: the model is asked to complete Lean 4 code and handed English prose. It
also carries `MAX_NEW_TOKENS = 20000` against a 4096-token context, no Lean
pinning of any kind, no outcome taxonomy, and the degenerate `answer_correct`
documented in its README output schema.

**Nothing on master is salvageable for this measurement.** Its only role is as
the merge base.

### `origin/code-validity` @ `8560786` — **FIX BEFORE MERGE**

Inherits every master defect above (prose input, 20000 tokens, no pinning) and
adds Colab-oriented environment fixes on top. Two things in it are genuinely
worth keeping and one is already ported:

- **Adopt (already ported):** the `~/.elan/bin` PATH prepend. `verifier.py:36-38`
  on HEAD carries it with the credit note "Ported from the code-validity branch,
  where it was found the hard way". This fixes `lake: command not found` for any
  non-login-shell entry point (Colab cells, notebook kernels, `nohup`, CI).
- **Adopt:** the `colab_run.sh` / `setup_lean.sh` Colab fixes, if Colab remains a
  target.
- **Reject:** everything touching generation. It is master's pipeline.

Note this branch is the **base of PR #10**, so merging #10 lands the verifier
work on top of a prose-input generation path. That is fine only because the
traces were generated on #8's code, not on #9's base.

### `fix/generation-input-path` @ `21c6842` (PR #8) — **ADOPT**

Closes issues #2, #3 and #4, each verified above. It is the branch that makes
generation meaningful at all, and it is the code state the T=0.0 traces were
generated from (per `traces/PROVENANCE.md:24-31`, commit `d857136`, which is on
this branch). It also introduces `run_meta.json` and distinct-problem sampling.

Remaining gaps at this branch: no outcome taxonomy, no `analyze_runs.py`, and
`answer_correct` still emitted.

### `fix/verifier-debug` @ `2253334` (PR #9) — **ADOPT**

Closes issues #1 and #6 as far as they can be closed without a re-run. Adds the
explicit outcome taxonomy, the control set (`results/control_set_run.json`,
35/35), the reference-proof provability measurement, `analyze_runs.py`, and the
`CODE_VERSION` provenance fallback. Its cold-vs-warm Mathlib measurement is the
evidence that the fast verifications are legitimate.

This is the strongest branch in the repo and PR #9 should merge.

### `merge/analysis-into-code-validity` @ `64fba01` (PR #10, local) — **FIX BEFORE MERGE**

Strictly the best code state: everything from #8 and #9, plus the two verifier
defects fixed in `0bea18d`/`64fba01` (`maxRecDepth` raised at verification time,
`statement_error` added as a distinct outcome).

But it must not merge as-is, for four reasons — three of them fixed in this
audit, one not:

1. **The two best commits are unpushed.** `origin/merge/analysis-into-code-validity`
   is `852aec7`; the local branch is two commits ahead. **PR #10 currently shows
   reviewers the 36/50 = 72% numbers that the author has already superseded with
   37/50 = 74%.** Push before merging or the PR is reviewing a stale artifact.
   *(Finding P0-1, not fixed by this audit — it is the author's to push.)*
2. **The cited analysis artifact did not ship.** `results/analysis_n50_corrected.json`
   was untracked and matched by `.gitignore:14`. **Fixed in this audit** —
   allowlisted and committed.
3. **`lake-manifest.json` was excluded.** See below. **Fixed in this audit.**
4. **`answer_correct` is still written.** See below. **Not fixed** — it is a
   behaviour change to the generation path and belongs to the author.

---

## Drift problem 1 — the README

The brief expects master's README drift (`answer_correct` in the schema,
`results/results_temp_{T}.json`, 10 trajectories per sample, a five-temperature
sweep). **That is still exactly true of `master` and `code-validity`** — verified:
`git show master:README.md` lines 55-57, 67, 103-113 document
`results/results_temp_{T}.json`, "5 JSON result files", "Generate 10 trajectories
per sample", and an `"answer_correct": true` schema field.

**But HEAD's README has already been rewritten** and does not have those
problems: it documents `analyze_runs.py`, the `traces/` layout, `run_meta.json`,
the `CODE_VERSION` deploy snippet, and one trajectory per sample. Grepping HEAD's
README for `answer_correct` and `results_temp` returns nothing.

Two drifts **do** remain on HEAD, both introduced by the audited commits:

- **README line ~207 lists only 7 outcomes** — `valid`, `compile_error`,
  `has_sorry`, `empty_code`, `parse_failure`, `timeout`, `verifier_crash` — and
  **omits `statement_error`**, which `64fba01` added and which the summary's
  outcome table reports. The documentation was not updated with the taxonomy.
- **The README's worked example writes and analyses `results/verify_temp0.0.jsonl`**
  (lines 201, 212) — the **superseded** verification pass. Anyone following the
  documented commands end-to-end reproduces **36/50 = 72%**, not the 74% the
  summary reports. This is the brief's "different pipeline than the one that
  produced this summary" concern, surviving in a subtler form.

**Verdict: fix before merge.** Both are one-line documentation edits. They are
listed as *fix required* rather than applied, because editing the README is
outside "recompute or delete" and the second one needs the author to decide
whether `verify2_*` becomes the canonical filename.

## Drift problem 2 — `answer_correct` is still being written

**Confirmed: yes.** `trace_valid.py:97` on HEAD still executes

```python
sample_result["answer_correct"] = best_traj["trace_valid"] and not best_traj["has_sorry"]
```

and writes it into `results/results_temp_{T}.json`. `analysis.py` on HEAD reads
it in seven places (lines 20-40), though to its credit it now carries a long
comment explaining *why* the field is degenerate and an assertion that fires if
`invalid_correct` ever becomes non-zero.

Section 6 of the summary admits the field is meaningless. The field is
nonetheless documented (on master), emitted (on HEAD), and named exactly like a
measurement. **A field that is emitted and known-meaningless will mislead anyone
reading raw results**, which is precisely issue #5.

**Mitigating fact, and it matters:** the `trace_valid.py run` path is **not** the
path that produced this summary. The n50 runs used `trace_valid.py generate`
(per `run_meta.json` `"command"`), and neither `traces/*/traces.jsonl` nor
`results/verify2_*.jsonl` contains an `answer_correct` field — verified by
inspecting the record schemas. So **no artifact behind the reported 74% carries
the degenerate field.** The hazard is to future users of the older `run`
subcommand, not to this result.

**Verdict: fix before merge.** Rename to `answer_correct_DEGENERATE_derived_from_trace_valid`,
or delete the field and the `analysis.py` code that reads it. Not applied here —
it changes pipeline output, which is beyond an audit's remit.

## Lean pinning — partially closed, and this audit closed the rest

`config.py:36-40` pins `LEAN_VERSION = "v4.32.0"` and `MATHLIB_REV = LEAN_VERSION`,
with a good rationale: a mathlib4 tag `vX.Y.Z` always declares
`leanprover/lean4:vX.Y.Z`, so naming the Mathlib tag after the Lean version keeps
toolchain, Mathlib and REPL in lockstep. `lakefile.toml` and `lean-toolchain` are
deliberately committed (`.gitignore:5-6`: "DO commit the pins: the toolchain and
Mathlib rev are the whole point of issue #6").

**But `lake-manifest.json` — the file holding the *resolved* SHAs — was
gitignored** by the blanket `lean_project/*` and never allowlisted. Reading the
local manifest shows why that matters:

| package | resolved rev | declared inputRev |
|---|---|---|
| **mathlib** | `81a5d257c8e410db227a6665ed08f64fea08e997` | `v4.32.0` (tag) |
| batteries | `023ce7d62a0531e22a5331e20b587817a80d49ff` | **`main`** |
| aesop | `a7dbf0c63b694e47f425f3dcddbc0e178bb432d3` | **`master`** |
| Qq | `38d591e778f100aec9762bb582f9c7f55f50e9dc` | **`master`** |
| proofwidgets | `6e311e2a844da9b2cc3971187df2fe0066947b93` | **`main`** |
| importGraph | `7e9612bf0b9ee66db3cb5b9988a35afc706f5a12` | **`main`** |
| plausible | `e12c1910fe855cbfc38803cd4e55543906d5fa62` | **`main`** |
| LeanSearchClient | `c5d5b8fe6e5158def25cd28eb94e4141ad97c843` | **`main`** |

Seven of nine dependencies are pinned to **floating branches**. Without the
manifest, a fresh `lake update` resolves them to whatever `main`/`master` points
at that day, and issue #6's exact failure mode — a version skew producing
"unexpected token" / "unknown constant" — reopens.

**Fixed in this audit:** `lean_project/lake-manifest.json` is now tracked
(3 KB), with the rationale written into `.gitignore`. The Mathlib commit SHA is
now a recoverable fact and appears in the rewritten summary's reproducibility
block.

---

## Bottom line

| Branch | Verdict | Reason |
|---|---|---|
| `master` | **Ignore** | Feeds English prose to a theorem prover (issue #2). Nothing salvageable for this measurement. |
| `code-validity` | **Fix before merge** | Master's generation defects + Colab fixes. Adopt only the elan PATH fix (already ported) and the Colab scripts. |
| `fix/generation-input-path` (#8) | **Adopt** | Closes #2, #3, #4. The code state the traces were generated from. |
| `fix/verifier-debug` (#9) | **Adopt** | Closes #1, #6. Outcome taxonomy, control set, `analyze_runs.py`, provenance fallback. Strongest branch in the repo. |
| `merge/analysis-into-code-validity` (#10) | **Fix before merge** | Best code state, but two commits unpushed so the PR shows superseded numbers; `answer_correct` still written; README omits `statement_error` and points at the superseded verification pass. |

**No other branch is doing any of this better than HEAD.** Every check HEAD
fails, the other branches fail worse or identically. The corrections needed are
all on HEAD itself.
