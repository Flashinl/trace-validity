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

---

## 2026-08-18T23:15Z — Phase 1 — kill gate

**Checked:** `verifier.py` (all 365 lines), `parser.py`, `verify_traces.py`,
`config.py`, `prompting.py`; then `tests/audit/phase1_checks.py` over all 100
committed traces.

**Found — GATE PASSES.**

1. **Statement fidelity holds, measured 50/50 at both temperatures.** The
   dataset `formal_statement` appears verbatim in `full_code` in every trace, and
   every `full_code` has exactly one declaration. Mechanism: `config.py:133-136`
   ends the prompt mid-fence right after the statement (which already ends
   `:= by`), and `prompting.py:52-61` rebuilds the file as `prompt + completion`.
   The model writes a proof body only. `results/CRITICAL.md` NOT written.
2. **1-A (medium):** but the verifier itself never compares — `verify_traces.py:116-127`
   compiles `full_code` and nothing else; `formal_statement` is read only at
   `verify_traces.py:135-137` inside the post-`compile_error` diagnostic. The
   invariant is unenforced and untested. Fix required, not applied.
3. **1-D (high, latent):** `verifier.py:240-245` makes `VALID` the *else* branch.
   No errors implies valid, including when the response carries no messages at
   all. No check that the declaration entered the environment. Fails open.
4. **Escape hatches: all zero.** Across 100 traces, comments stripped: 0 `sorry`,
   0 `admit`, 0 `axiom`, 0 `native_decide`, 0 `@[implemented_by]`, 0 `unsafe`,
   0 `macro_rules`, 0 model-added `set_option`. `decide` in 8 (T=0.0) / 6 (T=0.2),
   which is a kernel-checked tactic, not a hatch. `has_sorry = 0` is a structural
   REPL check (`verifier.py:235`), not a grep. **1-B (low):** `parser.py:102`
   defines a second, regex-based `has_sorry` on the generation record.
5. **`timeout` is NOT structurally unreachable** — brief hypothesis refuted.
   `config.py:45` sets a 60 s Python-side wall clock, enforced at
   `verifier.py:296` and handled at `verifier.py:297-305`. `maxHeartbeats 0`
   disables only Lean's internal counter. Crashes are NOT folded into
   `compile_error`: `verifier.py:306-314` returns a distinct `VERIFIER_CRASH`.
   **1-C (medium):** `except TimeoutError` precedes `except Exception`, so a
   timeout raised as anything other than a `TimeoutError` (e.g.
   `subprocess.TimeoutExpired`, which is not one) is recorded as
   `verifier_crash`. Neither branch has a fixture.
6. **Truncation: genuinely zero — brief hypothesis refuted.** 0 truncated,
   0 `hit_token_limit`, 0 unclosed fences, all `extract_status = extracted`, max
   579/615 generated tokens against a 2048 budget. Issue #4 was fixed before
   these runs (`config.py:154-159`, `run_meta.json` `max_new_tokens: 2048`). The
   missing truncation row is honest, though it should be an explicit zero.
7. **Mathlib was genuinely imported.** `lean_project/.lake/packages/` holds a
   real resolved tree; `lake-manifest.json` pins mathlib at
   `81a5d257c8e410db227a6665ed08f64fea08e997`. The sub-50 ms verifications
   (30/50 at T=0.0, min 9 ms) are explained by `verifier.py:184-227`: Mathlib is
   imported once per process and snapshotted, and per-record `seconds` times only
   the snippet. All 100 records ran in `shared_env` mode. **1-E (low):** the
   summary's 33.5 s / 38.0 s is not derivable from the artifacts, which sum to
   33.0 s / 37.7 s.

**Deliverable:** `results/PHASE1_PIPELINE.md`, `tests/audit/phase1_checks.py`.

---

## 2026-08-18T23:35Z — Phase 3 (recompute, run early) — every statistic

**Checked:** wrote `results/recompute_stats.py`, reading only committed JSONL/JSON.

**Found:**

1. All outcome counts reproduce exactly: 37 valid / 11 compile_error /
   2 statement_error at both temperatures; superseded pass 36/14.
2. **P3-1 (high) — the section-5 table transposes its two samples.**
   `SUMMARY_n50_distinct.md:158-159` says "valid only at T=0.0 → sample 35" and
   "valid only at T=0.2 → sample 0". Recomputed from
   `verify2_temp0.{0,2}.jsonl`: valid only at T=0.0 is **sample 0**; valid only
   at T=0.2 is **sample 35**. The document contradicts itself — section 4
   (line 150) correctly says "At T=0.2 the genuine failure is a different sample
   (0…), and 35 succeeds", which is the opposite of its own section-5 table.
3. **P3-2 (medium) — the "exactly 1 provable statement" claim has no
   denominator.** `SUMMARY_n50_distinct.md:64`. Recomputed: **1/38** provable
   statements that received a verdict (= 3%, 95% CI 0–13%). The brief's
   "1 of 39" error was already corrected in `64fba01`, but by deleting the
   denominator rather than fixing it.
4. **No confidence interval appears anywhere in the document.** Computed
   (Wilson): 37/50 = 74% [60–84%]; 37/48 = 77% [63–87%]; superseded 36/50 = 72%
   [58–83%]. The one-decimal precision ("74.0%", "77.1%") is false precision
   against a ±12 pp interval.
5. **P3-3 (medium) — "Zero false positives" (line 59) rests on n=10, not 11.**
   One of the 11 dataset-unprovable statements (sample 49) is a
   `statement_error` and never got a verdict. With 0 events in n=10 the exact
   one-sided 95% upper bound is **26%** (1 − 0.05^(1/10)).
6. **P3-4 (medium) — the "well inside noise" claim was untested.** McNemar exact
   on the discordant pairs (b=1, c=1): **p = 1.000, n=2 discordant**. Also
   computed: an all-one-way split needs **n ≥ 6** discordant pairs before
   two-sided p<0.05 is attainable at all, so this design cannot reject anything.
   Absence of evidence, not evidence of absence.
7. The `maxRecDepth` re-verification the brief demands **has already been done**
   by the author in `64fba01`; both passes are committed, so old and new numbers
   can be reported side by side without a new run.

**Deliverable:** `results/recompute_stats.py`, `results/recomputed_stats.json`.

---

## 2026-08-18T23:50Z — Phase 2 — the positives

**Checked:** `tests/audit/phase2_positives.py` over all 37 `valid` traces at
T=0.0; hand-read a random 10 (seed **20260818**, recorded at line 19 of the
script) → samples 8, 17, 20, 21, 26, 28, 33, 38, 42, 48.

**Found:**

1. **`restated` = 0 and `weakened` = 0 over the full 37, not sampled.** Both
   require changing the theorem, which the prompt construction forbids; verified
   37/37 statement-verbatim and 37/37 exactly-one-declaration.
2. **P2-1 (medium) — 1 of 37 positives is vacuous: sample 17's goal is literally
   `True`.** The trace is `valid` and establishes nothing. This is a *dataset*
   defect — FormalStep ships the statement with goal `True`, its own
   `reference_proof` proves `True`, and it is labelled `Success of Proof`.
   Treating it as untestable gives 36/47 = 77%, i.e. the headline does not move.
3. Hand-read result: **9 of 10 `proves_target`, 1 of 10 `vacuous`** — not
   extrapolated; the mechanical scan already covered all 37 for `True` goals and
   found exactly the same one.
4. **P2-2 (medium) — formalisation-quality ceiling.** Sample 38's goal reduces to
   `600 - 486 = 600 - 486` after substituting its own hypotheses: a tautology.
   Sample 20 formalises "probability 6/6 = 1" as natural-number division
   `6 / 6 = 1`. Caught by reading, not by script.
5. **Proof-shape distribution (all 37): 26 of 37 (70%) close a ground-arithmetic
   goal** — 9 by a single decision/normalisation tactic, 17 by
   substitute-then-normalise. Only 11 use structural tactics. `valid` on this
   sample largely measures decidable arithmetic, not proof search.
6. **Audited fraction, stated honestly: 37/37 mechanically, 10/37 (27%) by hand.**

**Deliverable:** `results/PHASE2_POSITIVES.md`, `results/phase2_positives.json`.
