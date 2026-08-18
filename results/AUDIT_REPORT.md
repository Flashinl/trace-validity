# Audit report — `results/SUMMARY_n50_distinct.md`

Branch `audit/summary-n50-repair`, forked from `merge/analysis-into-code-validity`
@ `64fba01`. Conducted 2026-08-18. Method and evidence:
`results/PHASE1_PIPELINE.md`, `results/PHASE2_POSITIVES.md`,
`results/BRANCH_MAP.md`, `results/BRANCH_COMPARISON.md`, `results/AUDIT_LOG.md`.
All statistics recomputed by `results/recompute_stats.py`.

---

## Headline answer

**The kill gate passes.** `valid` really does mean "the model produced a Lean
proof of the dataset's statement" — verified on 50/50 traces at both
temperatures, with zero `sorry`, zero `admit`, zero `axiom`, zero truncation, and
against a genuinely imported Mathlib whose negative controls fail correctly at
millisecond scale.

**No finding moves the rate.** The audited figure was already 74% (37/50) on the
local branch, not the 72% the brief describes — the author had superseded that in
two unpushed commits before the audit began. Nothing found here changes it
further.

**What does change is the precision and the framing.** 74% carries a 95% CI of
**60–84%**. The "zero false positives" claim rests on n=10 and is consistent with
a disagreement rate up to 26%. The temperature comparison has no power. And one
of the 37 positives proves a goal that is literally `True`.

---

## Findings by severity

### 1. P0-3 — Generation commit SHA was never recorded — **HIGH**

**Evidence:** `traces/temp0.0_n50_1each/run_meta.json:9-13` and the T=0.2
sidecar, both `"git": {"sha": null, "branch": null, "dirty": null}`.

The reported numbers **cannot be attributed to any code state by record**. The
generation host ran from a tar archive with no `.git`. `traces/PROVENANCE.md:24-38`
attributes the runs by hand to `d857136` (T=0.0) and to `3ec5361` *minus a later
hunk* for T=0.2 — a state matching **no commit in this repository**. The Lambda
instance is terminated, so this can never be checked.

To the code's credit it recorded `null` rather than fabricating a SHA, and
`generate.py:62-93` now provides a `CODE_VERSION` fallback with a `git.source`
field so it cannot recur.

**Fix applied:** stated plainly in the rewritten summary's reproducibility table
as UNRECORDED, with the PROVENANCE attribution labelled as recollection rather
than record. **Fix required:** none possible — requires a new run.

**Changes 74%?** No. It changes what may be *claimed* about 74%: the number is
real, its provenance is asserted.

### 2. 1-F — `axiom` is a working escape hatch — **HIGH (confirmed live)**

**Evidence:** `results/phase1_live_probe.json`, case `J_axiom_hatch`.

```lean
axiom cheat : (2:Nat) + 2 = 5
theorem t : (2:Nat) + 2 = 5 := by exact cheat
```
→ **`valid`**, in 9 ms.

The verifier never inspects axiom dependencies — no `#print axioms`, no
`Lean.collectAxioms`, no rejection of top-level `axiom` in submitted source
(`verifier.py:231-256`). `sorry` and `admit` are both caught structurally via the
REPL's `sorries` list; `axiom` is not.

**Measured impact: zero.** The full scan of all 100 traces found 0 `axiom`
declarations (`tests/audit/phase1_checks.py`).

**Fix required (no GPU, no new generation):** after a successful compile, assert
the theorem's axiom dependencies ⊆ `{propext, Classical.choice, Quot.sound}`.
Not applied — it changes the verifier, and the audit's rule is recompute-or-delete.

**Changes 74%?** No — measured 0 occurrences.

### 3. 1-D — `_classify` fails open — **HIGH (design)**

**Evidence:** `verifier.py:240-245`. `VALID` is the *else* branch: no error
messages ⇒ valid, including when the response carries no messages at all. There
is no check that the declaration entered the environment.

**Did it fire? No.** The negative controls settle this: `2+2=5` →
`compile_error` in 107 ms, unsolved goals in 15 ms, unknown identifier in 4 ms,
all against the same warm environment that produced the 9 ms `valid` results. The
REPL was returning populated responses throughout.

**Fix required:** require `getattr(resp, "env", None) is not None` before
returning `VALID`. One line. Not applied.

**Changes 74%?** No on this run; would invalidate it entirely if it ever fired.

### 4. P0-2 — The cited analysis artifact did not ship — **HIGH**

**Evidence:** the previous summary line 8 cited `results/analysis_n50_corrected.json`.
`git check-ignore -v` → matched by `.gitignore:14` (`results/*.json`);
`git ls-files --error-unmatch` → not tracked. The tracked
`analysis_n50_distinct.json` is the **superseded** pass.

The single line asserting reproducibility pointed at a file no reviewer could
obtain.

**Fix applied:** allowlisted in `.gitignore` and committed, along with the audit's
own outputs.

**Changes 74%?** No.

### 5. P3-1 — §5's table transposed its two samples — **HIGH (internal contradiction)**

**Evidence:** previous summary lines 158-159 said "valid only at T=0.0 → sample
35" and "valid only at T=0.2 → sample 0". Recomputed from
`verify2_temp0.{0,2}.jsonl` (`recompute_stats.py [4]`): valid only at T=0.0 is
**sample 0**; valid only at T=0.2 is **sample 35**.

The document contradicted itself — §4 line 150 correctly stated "At T=0.2 the
genuine failure is a different sample (0…), and 35 succeeds", the exact opposite
of its own §5 table.

**Fix applied:** table corrected against the artifacts, with a note.

**Changes 74%?** No — the totals were right, only the labels were swapped.

### 6. P0-1 — PR #10 shows numbers the author has already superseded — **HIGH (process)**

**Evidence:** `origin/merge/analysis-into-code-validity` = `852aec7`; local branch
= `64fba01`, two commits ahead and unpushed. `git show 852aec7:results/SUMMARY_n50_distinct.md:22`
reports `36 (72.0%)`; the local file reports 37 (74.0%) with a whole new outcome
category.

The brief's Phase 3 arithmetic items (the 1-of-39 denominator, the
4-row/3-heading table, §6 declining to raise `maxRecDepth`) describe text that no
longer exists locally — the author fixed them in `64fba01`. **A reviewer of PR
#10 is reviewing a stale artifact.**

**Fix required:** push. The author's call.

**Changes 74%?** No — but it means the number under review in the PR is 72%.

### 7. P2-1 — One vacuous positive — **MEDIUM**

**Evidence:** `results/phase2_positives.json`, sample 17. Goal is literally
`True`. The trace is `valid` and establishes nothing about the CoT step. This is
a **dataset defect**: FormalStep ships the statement with goal `True`, its own
`reference_proof` proves `True`, and it is labelled `Success of Proof`.

Exactly 1 such goal across all 37 positives (mechanically checked, full
population).

**Fix applied:** documented in §3 of the rewritten summary with the consistent
alternative arithmetic (36/47 = 77%).

**Changes 74%?** **No.** Removing one success from both numerator and denominator
gives 36/47 = 77%, indistinguishable from 37/48 = 77%.

### 8. Missing uncertainty throughout — **MEDIUM**

**Evidence:** no confidence interval appeared anywhere in the previous document,
while rates were quoted to one decimal ("74.0%", "77.1%").

**Fix applied**, computed in `recompute_stats.py`:

| claim | recomputed |
|---|---|
| 37/50 | 74%, Wilson 95% CI **60–84%** |
| 37/48 | 77%, Wilson 95% CI **63–87%** |
| superseded 36/50 | 72%, 95% CI 58–83% |
| "zero false positives" | 0/**10** (not 11), exact one-sided 95% upper bound **26%** |
| 1 provable failure | 1/**38** = 3%, 95% CI 0–13% |
| temperature difference | McNemar exact b=1 c=1 → **p = 1.000**, n=2 discordant; n≥6 needed for p<0.05 to be attainable |

Precision reduced to whole percents throughout.

**Changes 74%?** No — it bounds it.

### 9. P3-3 / framing — "false positive" language on an agreement measure — **MEDIUM**

The previous §2 correctly noted that the dataset `state` field answers a
different question, then used "false positive" language anyway. A false positive
requires ground truth about *this* proof.

**Fix applied:** section renamed to "Agreement with the dataset's provability
label", false-positive framing removed rather than reworded, bolding dropped, and
the 26% upper bound stated next to the zero count.

### 10. P2-2 — Formalisation-quality ceiling — **MEDIUM**

**Evidence:** hand-read of 10 positives. Sample 38's goal reduces to
`600 - 486 = 600 - 486` after substituting its own hypotheses — a tautology.
Sample 20 formalises "probability 6/6 = 1" as ℕ-division `6 / 6 = 1`.
Population-wide: 26 of 37 positives (70%) close a decidable ground goal.

**Fix applied:** stated in "What this does not measure" #5.

**Changes 74%?** No — changes what it means.

### 11. P3-2 — "exactly 1 provable statement" had no denominator — **MEDIUM**

The brief's "1 of 39" error was already corrected in `64fba01`, but by *deleting*
the denominator rather than fixing it. Recomputed: **1/38** provable statements
that received a verdict.

**Fix applied.**

### 12. §1's "change of sample" claim is asserted, and its stated mechanism fails — **MEDIUM**

**Evidence:** `recompute_stats.py [6]`. The two sets are certainly not
exchangeable (1 problem × 50 consecutive steps × 10 trajectories, vs 50 distinct
problems × 1). But median `formal_statement` length is **95 chars (old) vs 103
(new)** — no meaningful gap, and slightly *against* "first steps are easier". The
old set's `state` labels were never recorded, so its provability mix cannot be
compared at all.

**Fix applied:** relabelled explicitly as a hypothesis, with the length
measurement reported against it.

### 13. Branch drift — **MEDIUM**

- **`answer_correct` is still written** at `trace_valid.py:97`, and read in seven
  places in `analysis.py`. Documented, emitted, known-meaningless. *Mitigating
  fact:* the runs behind this summary used `generate`, not `run`, and no artifact
  behind the 74% contains the field. **Fix required, not applied.**
- **README omits `statement_error`** from its outcome list, and its worked
  example writes and analyses the **superseded** `verify_temp0.0.jsonl` — so
  following the documented commands reproduces 72%, not 74%. **Fix required.**
- Master's README drift (`answer_correct` schema, `results_temp_{T}.json`, 10
  trajectories, five-temperature sweep) is **real but confined to `master` and
  `code-validity`**; HEAD's README was already rewritten.

### 14. Lean pinning incomplete — **MEDIUM**

**Evidence:** `lean_project/lake-manifest.json` was gitignored by
`lean_project/*` despite `.gitignore:5-6` declaring the pins "the whole point of
issue #6". Seven of nine dependencies (batteries, aesop, Qq, proofwidgets,
importGraph, plausible, LeanSearchClient) declare floating `main`/`master`
inputRevs; only the manifest holds their resolved SHAs.

**Fix applied:** manifest now tracked (3 KB), with the rationale in `.gitignore`.
Mathlib commit `81a5d257c8e410db227a6665ed08f64fea08e997` is now a recoverable
fact and appears in the summary's reproducibility block.

### 15. 1-A — Statement fidelity unenforced — **MEDIUM**

Holds 50/50 by prompt construction, checked nowhere. An edit to `prompting.py`
would void it silently. **Fix required:** ~6 lines emitting a `statement_mismatch`
outcome. Not applied.

### 16. 1-C — `timeout` / `verifier_crash` behaviour unverified — **MEDIUM**

Both branches exist and are correctly wired; **neither could be fired by any
fixture**. The timeout probe hit `maxRecDepth` and returned `compile_error` in
100 ms. `except TimeoutError` precedes `except Exception`, so a timeout raised as
anything else (e.g. `subprocess.TimeoutExpired`, which is not a `TimeoutError`)
would be misfiled as `verifier_crash`. **Unresolved.**

### 17. 1-B — Two `has_sorry` fields — **LOW**

`parser.py:102` sets a regex-based `has_sorry` on the generation record;
`verifier.py:235` uses the REPL's structural `sorries` list. The reported outcome
uses the structural one. Rename the parser's field.

### 18. 1-E — Reported timing not derivable from artifacts — **LOW**

Summary said 33.5 s / 38.0 s; per-record `seconds` sum to 33.0 s / 37.7 s. The
gap is `statement_is_broken()` re-probes and loop overhead, never recorded.
**Fix applied:** the artifact-derived figures are now reported, with the median
(<50 ms) alongside the mean.

---

## Hypotheses in the brief that the evidence REFUTED

Worth recording, because three of the brief's five kill-gate concerns did not
survive contact with the code:

| Brief's concern | Finding |
|---|---|
| "The model invents its own theorem; `valid` means 'wrote compiling Lean'" | **Refuted.** Statement verbatim in `full_code` 50/50 both temps, exactly one declaration 50/50. Issue #3 was closed by PR #8's templating. |
| "`maxHeartbeats 0` makes `timeout` structurally unreachable" | **Refuted.** An independent 60 s Python wall clock exists (`config.py:45`, enforced `verifier.py:296`). `maxHeartbeats 0` disables only Lean's internal counter. |
| "The exception handler swallows crashes and reclassifies them as `compile_error`" | **Refuted.** `verifier.py:306-314` returns a distinct `VERIFIER_CRASH`; `compile_error` requires the REPL to have returned error-severity messages. |
| "`MAX_NEW_TOKENS = 20000` against a 4096 context; count truncated generations" | **Refuted for these runs.** Fixed to 2048 before generation (`config.py:159`, both `run_meta.json`). 0 truncated, 0 token-limited, max 579/615 tokens used. The missing truncation row was honest. |
| "0.53 s per verification is too fast for full Mathlib" | **Refuted.** Mathlib imported once and snapshotted (`verifier.py:184-227`); negative controls fail in 4–107 ms against the same warm env. Genuinely elaborating. |

And two the brief got right that the author had *already fixed* before the audit:
the 1-of-39 denominator and the 4-row/3-heading table, both corrected in
`64fba01` (though the first by deleting the denominator rather than fixing it —
now restored as 1/38).

---

## Does this change the headline?

**No finding moves the rate.** In order of what one might expect to:

| Finding | Effect on 74% |
|---|---|
| Vacuous positive (sample 17) | 36/47 = 77% vs 37/48 = 77% — **no change** |
| Axiom escape hatch | 0 occurrences measured — **no change** |
| Fail-open classifier | Did not fire (negative controls) — **no change** |
| Statement fidelity | Holds 50/50 — **no change** |
| Truncation | 0 — **no change** |
| Confidence intervals | 74% → 74% [60–84%] — **bounds it, does not move it** |

The only number that moved during this work moved *before* the audit: the
author's own `maxRecDepth` and `statement_error` fixes took 36/50 = 72% to
37/50 = 74%, and both passes are committed so the delta is auditable.

---

## After this audit, is 72% a number that can be reported?

**No — because 72% is the wrong number.** It is the superseded pass. The correct
figure from the corrected verifier is **74%**, and it *can* be reported, with
three conditions attached:

1. **Report it as 37/50 = 74%, 95% CI 60–84%** — or 37/48 = 77% [63–87%] over
   traces that got a verdict. Never to one decimal place. The interval is the
   result; the point estimate alone is not.

2. **Report it as "produced a compiling Lean proof of the dataset's statement",
   not as a capability claim.** 70% of the positives close decidable ground
   arithmetic, one proves a goal that is literally `True`, and answer correctness
   is not measured at all.

3. **State that the generation commit SHA is unrecorded.** The number is real and
   reproducible from committed artifacts; the *code that generated the traces* is
   attributable only by the author's recollection, and the instance is gone.

The claims that must **not** be carried forward as written: "zero false
positives" (it is an agreement measure, 0/10, upper bound 26%), and "well inside
noise" for the temperature comparison (n=2 discordant pairs — the design has no
power, so that is absence of evidence).

Two things I would fix before publishing, both cheap and neither needing a GPU:
the axiom-dependency check (finding 2) and the systematic vacuity scan
(UNRESOLVED #2). Neither is likely to move 74%; both determine whether the next
run's number can be trusted without another audit.
