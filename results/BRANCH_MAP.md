# Branch map — audit of `results/SUMMARY_n50_distinct.md`

Produced 2026-08-18 on branch `audit/summary-n50-repair`, forked from
`merge/analysis-into-code-validity` @ `64fba01`.

## Every branch

| Branch | HEAD SHA | Date | What it changes vs `master` |
|---|---|---|---|
| `master` / `origin/master` | `211d9f8` | 2026-08-08 | Baseline. "Replace pipeline with code from jerryfrancis-97/math-trace-validity". |
| `origin/code-validity` | `8560786` | 2026-08-15 | Colab-oriented fixes to `setup_lean.sh` / `colab_run.sh` / package install, plus a committed JSON. +719/-14 over 7 files. Does **not** contain the n50 work. |
| `fix/generation-input-path` | `21c6842` | 2026-08-15 | PR **#8**. Generation input path, prompt template, token budget (issues #2 #3 #4); adds `run_meta.json`, distinct-problem sampling, and the two n50 trace dirs. +2963/-51 over 14 files. |
| `fix/verifier-debug` | `2253334` | 2026-08-15 | PR **#9**. Verifier rebuild: Lean pinning, explicit outcome taxonomy, control set, `analyze_runs.py`, reference-proof provability measurement (issues #1 #6). Contains #8 merged in twice. +6712/-197 over 40 files. |
| `origin/merge/analysis-into-code-validity` | `852aec7` | 2026-08-16 01:09 | PR **#10**. Merge of `fix/verifier-debug` into `code-validity`. **This is the state the audit brief describes** (36/50 = 72.0%). |
| `merge/analysis-into-code-validity` (local) | `64fba01` | 2026-08-16 17:49 | Two **unpushed** commits on top of `852aec7`: `0bea18d` (demonstrate two compile_errors reject the statement) and `64fba01` (fix two verifier defects, re-verify → 37/48). |
| `audit/summary-n50-repair` | this branch | 2026-08-18 | This audit. |

Note: a local branch literally named `origin` exists at `211d9f8` (same as
`master`). It is a stray and shadows nothing; harmless but worth deleting.

## PR mapping (confirmed via `gh pr list`)

- **#8** → `fix/generation-input-path` → base `master`. "Fix generation input path, prompt template, and token budget (#2, #3, #4)". OPEN.
- **#9** → `fix/verifier-debug` → base `master`. "Debug the verifier: pin Lean, outcome taxonomy, and first result (#1, #6)". OPEN.
- **#10** → `merge/analysis-into-code-validity` → base `code-validity`. "Merge fix/verifier-debug into code-validity (resolved)". OPEN.

## FINDING P0-1 (high): the audited file has already moved

The brief audits the summary as it stands at `852aec7` (pushed, and what PR #10
shows). The local branch is **two commits ahead and unpushed**, and those commits
already rewrote the document: `36/50 = 72.0%` became `37/50 = 74.0%`, a
`statement_error` outcome was added, and `maxRecDepth` was raised. Several Phase 3
items in the brief (the 1-of-39 denominator, the 4-row/3-heading table, the
refusal to raise `maxRecDepth`) describe text that no longer exists locally.

Consequence: **PR #10 as a reviewer sees it presents numbers the author has
already superseded in unpushed work.** That is itself a reportable defect — the
pushed artifact and the working artifact disagree by 1 sample and one whole
outcome category.

This audit targets the *local* `64fba01` state, and re-derives its numbers from
scratch rather than trusting them.

## Which code state produced the numbers?

`traces/temp0.0_n50_1each/run_meta.json:9-13` and the T=0.2 sidecar both record:

```json
"git": { "sha": null, "branch": null, "dirty": null }
```

**No commit SHA was recorded by either generation run.** The runs executed from an
uploaded tar archive with no `.git`, so `git rev-parse` had nothing to answer
with. To the code's credit it recorded `null` rather than fabricating a value.

The gap is partially closed *by hand* in `traces/PROVENANCE.md:24-38`, which
attributes T=0.0 to commit `d857136` (clean tree) and T=0.2 to `3ec5361` minus a
later hunk — i.e. **T=0.2 ran code that matches no commit in this repository.**

Severity: this is a **provenance-by-assertion**, not provenance-by-record. The
T=0.0 attribution is plausible and checkable in principle (the archive is gone,
so not in practice); the T=0.2 attribution is explicitly to an uncommitted
intermediate state and is unverifiable by anyone but the author. The honest
statement for the summary is: *generation commit SHA is unrecorded; the
attribution in PROVENANCE.md is the author's recollection.*

Mitigation already in the tree: `git_state()` now falls back to a `CODE_VERSION`
file and records `git.source` (PROVENANCE.md:40-43). Verified present — see
Phase 4.

## Are the inputs actually committed?

Checked against `git ls-files` and `.gitignore`. **Yes, all of them:**

| Path | Committed? | Notes |
|---|---|---|
| `traces/temp0.0_n50_1each/traces.jsonl` + `run_meta.json` | ✅ tracked | |
| `traces/temp0.2_n50_1each/traces.jsonl` + `run_meta.json` | ✅ tracked | |
| `results/verify_temp0.0.jsonl`, `results/verify_temp0.2.jsonl` | ✅ tracked | superseded pass |
| `results/verify2_temp0.0.jsonl`, `results/verify2_temp0.2.jsonl` | ✅ tracked | the pass the summary reports |
| `results/analysis_n50_distinct.json` | ✅ tracked | via `!results/…` allowlist |

`.gitignore:12` has a blanket `results/*.json` but lines 13-16 re-allow the four
analysis deliverables, and `.jsonl` is never matched by `*.json`. So the
reproducibility claim is **structurally sound** — the inputs are in the repo.

**But the summary's cited analysis artifact is not in the repo.**
`SUMMARY_n50_distinct.md:8` cites `results/analysis_n50_corrected.json`. That
file **exists in the working tree** (3085 bytes, mtime 2026-08-16 17:48 — written
by the re-verification commit) but is **untracked and actively gitignored**:

```
$ git check-ignore -v results/analysis_n50_corrected.json
.gitignore:14:results/*.json   results/analysis_n50_corrected.json
$ git ls-files --error-unmatch results/analysis_n50_corrected.json
error: pathspec ... did not match any file(s) known to git
```

The `.gitignore` allowlist (lines 15-18) re-admits `control_set_run.json`,
`crosscheck.json`, `pipeline_trace.json` and `reference_proofs.json` — and
`analysis_n50_distinct.json` from the earlier pass — but was never extended to
the *corrected* analysis. So:

- The tracked `results/analysis_n50_distinct.json` is the **superseded** pass.
- The artifact the summary actually reports from is **invisible to any reviewer**
  who clones the repo.

This is finding **P0-2 (high)**: the single line in the document that asserts
reproducibility points at a file that does not ship. Every number in §1-§5 is
derived from an artifact a reader cannot obtain. Fix is one line in `.gitignore`
plus `git add`.
