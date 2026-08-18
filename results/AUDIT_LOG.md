# Audit log — `results/SUMMARY_n50_distinct.md`

Append-only. Newest entries at the bottom. Branch `audit/summary-n50-repair`,
forked from `merge/analysis-into-code-validity` @ `64fba01`.

---

## 2026-08-18T22:25Z — Phase 0 — inventory and branch map

**Checked:** `git fetch --all`, full branch listing, `git log --graph --all`,
`gh pr list --state all`, `git ls-files`, `.gitignore`, both `run_meta.json`
sidecars, `traces/PROVENANCE.md`, and the target summary at both `852aec7`
(pushed) and `64fba01` (local HEAD).

**Found:**

1. **P0-1 (high) — the audited file has already moved.** The brief describes the
   summary at `852aec7` (36/50 = 72.0%, "1 of 39", 4-row/3-heading table, §6
   declining to raise `maxRecDepth`). Local HEAD `64fba01` is two *unpushed*
   commits ahead and has already rewritten all of that to 37/50 = 74.0% with a
   new `statement_error` outcome. Evidence: `git show 852aec7:results/SUMMARY_n50_distinct.md:22`
   (`| valid | 36 (72.0%) |`) vs `results/SUMMARY_n50_distinct.md:26`
   (`| valid | 37 (74.0%) |`). PR #10 therefore shows reviewers numbers the
   author has already superseded in work they cannot see.

2. **P0-2 (high) — the cited analysis artifact does not ship.**
   `results/SUMMARY_n50_distinct.md:8` cites `results/analysis_n50_corrected.json`.
   The file exists on disk but is untracked and matched by `.gitignore:14`
   (`results/*.json`). `git ls-files --error-unmatch` fails on it. The tracked
   `analysis_n50_distinct.json` is the *superseded* pass. The one line asserting
   reproducibility points at a file no reviewer can obtain.

3. **P0-3 (high) — no generation commit SHA was recorded.**
   `traces/temp0.0_n50_1each/run_meta.json:9-13` and the T=0.2 sidecar both carry
   `"git": {"sha": null, "branch": null, "dirty": null}`. The code recorded `null`
   rather than fabricating — correct behaviour — but the consequence stands: the
   reported numbers **cannot be attributed to any code state by record**.
   `traces/PROVENANCE.md:24-38` attributes them by hand to `d857136` (T=0.0) and
   to `3ec5361`-minus-a-later-hunk (T=0.2). The T=0.2 attribution is to a state
   that **matches no commit in this repository** and is unverifiable now that the
   Lambda instance is terminated.

4. **Good news — the trace and verification inputs *are* committed.**
   `traces/temp0.{0,2}_n50_1each/{traces.jsonl,run_meta.json}`,
   `results/verify_temp0.{0,2}.jsonl`, `results/verify2_temp0.{0,2}.jsonl` and
   `results/analysis_n50_distinct.json` are all tracked. `.gitignore`'s
   `results/*.json` never matches `.jsonl`. So the pipeline *is* re-runnable from
   committed inputs, modulo P0-2.

5. `run_meta.json:16` records `max_new_tokens: 2048` against
   `declared_context: 4096` — issue #4's `MAX_NEW_TOKENS = 20000` was **already
   fixed** before these runs. Noted for Phase 1.4.

**Deliverable:** `results/BRANCH_MAP.md`.
