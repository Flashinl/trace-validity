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

---

## 2026-08-19T00:35Z — Phase 4 — cross-branch comparison

**Checked:** `git show <branch>:{config,data_loader,verifier,trace_valid,README}`
across `master`, `origin/code-validity`, `fix/generation-input-path` (#8),
`fix/verifier-debug` (#9) and HEAD (#10), plus `git grep answer_correct`.

**Found:**

1. **`master` and `origin/code-validity` feed `item["problem"]`** — the English
   prose — to a theorem prover (`data_loader.py:17`). Issue #2, fatal. Both also
   carry `MAX_NEW_TOKENS = 20000` against a 4096-token context, no Lean pinning,
   and no outcome taxonomy. Verdict: **ignore** / **fix before merge**.
2. **PR #8 closes #2, #3, #4** (formal_statement input, PROMPT_TEMPLATE,
   MAX_NEW_TOKENS=2048 + MODEL_MAX_CONTEXT=4096). Verdict: **adopt**.
3. **PR #9 closes #1, #6** (7-outcome taxonomy, Lean pinning, control set,
   analyze_runs.py, CODE_VERSION fallback at generate.py:62-93). Strongest branch
   in the repo. Verdict: **adopt**.
4. **HEAD (#10)** is the best code state (8 outcomes, both verifier fixes) but
   verdict **fix before merge**: two commits unpushed, `answer_correct` still
   written, README drift.
5. **README drift resolved explicitly.** Master's drift (`answer_correct` schema,
   `results/results_temp_{T}.json`, 10 trajectories, five-temperature sweep) is
   real but **confined to `master` and `code-validity`** — HEAD's README was
   already rewritten. Two drifts remain on HEAD, both introduced by the audited
   commits: the outcome list omits `statement_error`, and the worked example
   writes/analyses the **superseded** `verify_temp0.0.jsonl`, so following the
   docs reproduces 72% rather than 74%.
6. **`answer_correct` IS still written** — `trace_valid.py:97`, read in seven
   places in `analysis.py`. Mitigating: the n50 runs used `generate`, not `run`,
   and no artifact behind the reported 74% contains the field (verified against
   the record schemas of `traces/*/traces.jsonl` and `results/verify2_*.jsonl`).
7. **Lean pinning was incomplete.** `lean_project/lake-manifest.json` was
   gitignored by `lean_project/*`, despite `.gitignore:5-6` calling the pins "the
   whole point of issue #6". Seven of nine deps declare floating `main`/`master`;
   only the manifest holds resolved SHAs. **Fixed** — manifest now tracked, and
   Mathlib `81a5d257c8e410db227a6665ed08f64fea08e997` is now recoverable.

**Deliverable:** `results/BRANCH_COMPARISON.md`.

---

## 2026-08-19T01:05Z — Phase 1 addendum — live Lean probes

**Checked:** `tests/audit/phase1_live.py` against the built local `lean_project`
(Lake: "Build completed successfully (8656 jobs)"; Mathlib env unpickled in
92.8 s; verifier ready in 242 s). 13 fixtures.

**Found:**

1. **The timing question is SETTLED.** Negative controls fail correctly and at
   the same millisecond scale as the positives: `(2:Nat)+2 = 5` →
   `compile_error` "unsolved goals ⊢ False" in 107 ms; `n > 0 := by skip` →
   `compile_error` in 15 ms; unknown identifier → `compile_error` in **4 ms**.
   A pipeline that was not elaborating would have returned `valid` for all three.
   Mathlib was genuinely imported; the sub-10 ms `valid` results are real.
   **Finding 1-D did not fire.**
2. **NEW FINDING 1-F (high, confirmed live): `axiom` is a working escape hatch.**
   `axiom cheat : (2:Nat)+2 = 5` followed by `theorem t : (2:Nat)+2 = 5 := by
   exact cheat` returns **`valid` in 9 ms**. No `#print axioms` /
   `Lean.collectAxioms` anywhere in `verifier.py`. Measured impact on this run:
   **zero** — 0 `axiom` declarations across all 100 traces.
3. **`admit` IS caught** → `has_sorry` (6 ms). Lean's `admit` produces a sorry,
   which the structural `sorries` check sees. So of the brief's escape-hatch
   list, only `axiom` is open.
4. **`timeout` could NOT be fired.** The `decide`-on-`Nat.choose 100000 50000`
   probe hit `maxRecDepth 10000` and returned `compile_error` in 100 ms instead.
   `LEAN_MAX_REC_DEPTH` now bounds runaway elaboration *before* the 60 s clock,
   making `timeout` even less reachable in practice. `verifier_crash` likewise
   unfired. **Finding 1-C stays unresolved.**

**Deliverable:** `results/phase1_live_probe.json`,
`results/mathlib_build_evidence.log`, updated `results/PHASE1_PIPELINE.md`.

---

## 2026-08-19T01:25Z — Phase 5 — rewrite

**Checked / applied:**

1. Rewrote `results/SUMMARY_n50_distinct.md`. "What this does NOT measure" is now
   the first section, above the results, and leads with the two items the brief
   named: whether the proved statement is the target statement, and the partial
   audit of positives.
2. Every rate now carries n and a Wilson 95% CI; precision reduced to whole
   percents. Every claim names the artifact it comes from.
3. Reproducibility block records toolchain, **Mathlib commit SHA
   `81a5d257c8e410db227a6665ed08f64fea08e997`**, `lake-manifest.json` sha256
   `62bff1a7…`, dataset fingerprint, seed, traces sha256, key library versions —
   and explicitly lists full `pip freeze` as UNRECOVERABLE and the generation
   commit SHA as UNRECORDED.
4. Corrected §5's transposed samples (P3-1); restored the 1/38 denominator
   (P3-2); replaced false-positive framing with agreement + the 26% one-sided
   bound (P3-3); added McNemar exact p=1.000 with the n≥6 power note (P3-4);
   relabelled the "change of sample" claim as a hypothesis and reported the
   median-length measurement that runs against its stated mechanism.
5. **Deleted rather than reworded** the §7 claim "measured as harder than the
   median step (median statement 104 vs 66 chars, 11 vs 8 unprovable)" — not
   reproducible from any committed artifact. Logged in UNRESOLVED #4 with what it
   would take.
6. Old and new verification passes reported side by side (72% [58–83%] vs
   74% [60–84%]), with the three samples that moved.
7. `UNRESOLVED` list of 9 items, each with the reason and an effort estimate.

**Deliverable:** rewritten `results/SUMMARY_n50_distinct.md`,
`results/AUDIT_REPORT.md`.

**Bottom line:** 74% can be reported, with a CI, framed as "produced a compiling
Lean proof of the dataset's statement", and with the unrecorded generation SHA
stated. 72% cannot — it is the superseded pass.

---

## 2026-08-19T02:40Z — Phase 6 — apply the fixes and re-verify

Not part of the original 3-hour brief. Undertaken after the audit, on request,
once the audited numbers were locked so any change would be visible.

**Applied — six pipeline defects:**

1. **1-F axiom escape hatch.** `verifier._axiom_audit()` runs `#print axioms
   <name>` against the post-compile environment and rejects any dependency
   outside `{propext, Classical.choice, Quot.sound}` as the new outcome
   `unsound_axioms`. Asks Lean rather than grepping, so it also catches an axiom
   pulled in through a lemma. Falls back to a static `axiom` check when there is
   no named theorem, and treats an un-auditable proof as a failure.
2. **1-D fail-open classifier.** `verifier._classify()` no longer makes `VALID`
   the bare `else`. A response with no error messages *and* no environment is now
   `verifier_crash`.
3. **1-A statement fidelity.** `verify_traces.statement_mismatch()` asserts, per
   record and before a pass is scored, that the dataset `formal_statement`
   appears verbatim and the file declares exactly one theorem; otherwise the new
   outcome `statement_mismatch`, classified as no-verdict.
4. **`answer_correct` deleted at source** (`trace_valid.py`), along with
   `valid_accuracy` / `invalid_accuracy` / `overall_accuracy` in `analysis.py`
   and the 2x2 chart whose two of four bars were structurally zero. Deleted, not
   renamed.
5. **1-B `has_sorry` ambiguity.** Parser's regex flag renamed
   `has_sorry_literal`; consumers updated in `generate.py`, `trace_valid.py`,
   `tests/trace_pipeline.py`.
6. **README drift.** All ten outcomes documented, the three non-verdict outcomes
   separated from `unsound_axioms` (which IS a verdict), and a table naming which
   of the three verification passes is canonical.

Also reframed `analyze_runs.py`'s crosstab report: "false positives" →
"DISAGREEMENT", with the real denominator (0/10, not 0/11) and the exact
one-sided 95% bound printed inline ("bounds the true rate at <=26%, NOT at 0").
The tool now refuses to overstate the same way the prose did.

**Re-verified — all 100 traces through the hardened verifier:**

`results/verify3_temp0.0.jsonl`, `results/verify3_temp0.2.jsonl`.

```
T=0.0: valid 37, compile_error 11, statement_error 2   (35.7s)
T=0.2: valid 37, compile_error 11, statement_error 2   (53.9s)
outcome changes vs verify2: NONE at either temperature
statement_mismatch: 0    unsound_axioms: 0
```

**The headline is unchanged: 37/50 = 74%, 37/48 = 77%.** The hardening does not
move this result; it changes whether the next one can be trusted without another
audit.

**Axiom audit results across the 37 positives** — this is now positive evidence,
not the absence of a grep hit. Lean reports the real transitive dependency set:

| dependency set | T=0.0 | T=0.2 |
|---|---|---|
| none at all | 10 | 8 |
| `propext` | 17 | 17 |
| `propext, Classical.choice, Quot.sound` | 10 | 11 |
| `propext, Quot.sound` | 0 | 1 |
| outside the trusted set | **0** | **0** |

**Regression check** (`results/phase1_live_probe.json`, re-run): the axiom
fixture went `valid` → **`unsound_axioms`** ("proof depends on untrusted
axiom(s): cheat"); the other 12 fixtures unchanged.

**1-C dead branches — now fired.** `tests/audit/phase1_deadbranches.py`, 4/4 pass
(`results/phase1_deadbranches.json`):

- Real elaboration under a 0.01 s budget → **`timeout`**, not `verifier_crash`.
  So `lean_interact` does raise a genuine `TimeoutError` and the handler ordering
  is safe on this path — the concern in finding 1-C is resolved for the observed
  case.
- Verification against a nonexistent environment id → **`verifier_crash`**, via
  the new fail-closed branch. **This proves finding 1-D was live, not
  theoretical:** the old classifier would have reached `else: outcome = VALID`
  and scored a snippet that was never elaborated at all as a proved theorem.
- A normal proof immediately after each → `valid`. `_restart()` works; one
  timeout does not poison the rest of a run.

Residual on 1-C, still open: no *organic* timeout is reachable, because
`LEAN_MAX_REC_DEPTH = 10000` bounds runaway elaboration before the 60 s clock can
expire (the heavy-`decide` probe returned `compile_error` in 208 ms).

**Still not fixed, and why:** the systematic vacuity scan over all 37 positives
(~30 min, would change what 74% means rather than its value); the 27 positives
not read by hand; the median-step comparison; anything needing a GPU; and
pushing the branch, which is the author's call.
