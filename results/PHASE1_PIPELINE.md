# Phase 1 — kill gate: does the pipeline measure what it claims?

Audit branch `audit/summary-n50-repair`, base `merge/analysis-into-code-validity` @ `64fba01`.
Mechanical checks: `tests/audit/phase1_checks.py` (reads committed artifacts only).
Live Lean probes: `tests/audit/phase1_live.py` → `results/phase1_live_probe.json`.

**Gate verdict: PASSES, but on an undefended flank.** The metric is not what the
brief feared — the model is not inventing its own theorem — but nothing in the
*verifier* enforces that. The guarantee comes entirely from how the prompt is
built, and one edit to `prompting.py` would silently void it with no test failing.

---

## 1. Statement fidelity — the model proves the dataset's statement

**This is the question that decides whether 74% is a validity rate at all.**

### What the verifier does

`verify_traces.py:116-127` passes `r["full_code"]` to `LeanVerifier.verify()`,
which compiles it and classifies the result. Nothing else. Searching the whole
verifier for any comparison against the dataset statement:

- `verifier.py:258-316` (`verify`) — takes one string, splits imports, compiles.
  Never sees `formal_statement`.
- `verifier.py:231-256` (`_classify`) — inspects only `messages` and `sorries`
  off the REPL response.
- The dataset's `formal_statement` is read in exactly one place:
  `verify_traces.py:135-137`, inside the `statement_is_broken()` diagnostic, and
  **only after a `compile_error`**. On the `valid` path it is never consulted.

So **there is no `isDefEq` check, no syntactic comparison, and no binding of any
kind between the generated theorem and the source statement.** If the model
emitted a different theorem, `verify()` would return `valid` for it.

### Why it does not matter here — and where the guarantee actually lives

The statement is not something the model chooses. It is pinned by prompt
construction:

- `config.py:133-136` — `PROMPT_TEMPLATE` ends
  `"...```lean4\n{header}{informal_prefix}{formal_statement}"`, i.e. the prompt
  **terminates inside an unterminated fence, immediately after the statement**.
- The dataset's `formal_statement` already ends in `:= by` (verified on the
  records, e.g. sample 0: `theorem test\n  (n: ℕ)\n  (h₀: n = 1061520150601):\n  ∃ a: ℕ, a^6 = n := by\n`).
- `prompting.py:52-61` (`extract_lean4_block`) recovers the file from
  `prompt + completion`, so `full_code` = header + doc-comment + **the dataset's
  statement verbatim** + whatever the model generated after `by`.

The model therefore writes a *proof body only*. It cannot alter binders,
hypotheses or the goal without emitting a second declaration.

### Measured, not argued

`tests/audit/phase1_checks.py` over all 100 traces (50 samples × 2 temperatures):

| Check | T=0.0 | T=0.2 |
|---|---|---|
| `formal_statement` present verbatim (whitespace-normalised) in `full_code` | **50/50** | **50/50** |
| Declarations (`theorem`/`lemma`/`example`) per `full_code`, comments stripped | **1 in all 50** | **1 in all 50** |
| Traces where `full_code` was missing and the parser fallback was used | 0 | 0 |

Both failure modes are ruled out empirically: no trace restated the goal, and no
trace declared a second theorem to prove instead.

**Conclusion.** `valid` does mean "the model proved the dataset's statement" for
these 100 traces. Issue #3's failure mode (raw untemplated string → the model
invents a theorem) was closed by PR #8's templating and is confirmed closed by
measurement.

### FINDING 1-A (medium) — the invariant is unenforced and untested

The property holds by construction, not by check. Nothing asserts it. If
`build_prompt()` ever stops emitting `formal_statement` last, or a future run
feeds `informal_step` instead (issue #2's failure mode), every trace would still
be classified `valid`/`compile_error` exactly as now and no test would fail.

**Fix required (one assertion, no GPU):** in `verify_traces.py`, before
verifying, assert that the normalised `formal_statement` occurs in `full_code`
and that `full_code` contains exactly one declaration; emit a new outcome
`statement_mismatch` otherwise. This is a 6-line change and turns a lucky
property into a measured one. **Not applied in this audit** — it changes the
verifier, and by the audit's own rule I recompute rather than re-engineer. It is
listed as *fix required*.

---

## 2. Escape hatches beyond `sorry`

### Is `has_sorry = 0` a grep or a real check?

**A real check, on the verifier side.** `verifier.py:235` reads the REPL's
structured `sorries` list off the response, and `verifier.py:238` additionally
catches the REPL's sorry *warning*. The module docstring (`verifier.py:20-22`)
states the reason explicitly: a `\bsorry\b` regex matches the word in comments
and string literals.

**But there are two different `has_sorry` fields in this repo, and one of them
*is* a grep.** `parser.py:102` sets `"has_sorry": bool(re.search(r"\bsorry\b", code))`
on the *generation-side* record. That field is written into `traces.jsonl` and is
naive. It is not the one the outcome table reports — `verify_traces.py:158`
takes `outcome` from the verifier — but two same-named fields with different
semantics in the same pipeline is a trap. **FINDING 1-B (low): rename the
parser's field to `has_sorry_literal`.**

### Full scan of all 100 parsed programs

`tests/audit/phase1_checks.py`, comments stripped before matching:

| Pattern | T=0.0 | T=0.2 |
|---|---|---|
| `sorry` | **0** | **0** |
| `admit` | **0** | **0** |
| `axiom ` (declaration) | **0** | **0** |
| `native_decide` | **0** | **0** |
| `@[implemented_by` | **0** | **0** |
| `unsafe` | **0** | **0** |
| `macro_rules` | **0** | **0** |
| model-added `set_option` (any beyond the header's `maxHeartbeats`) | **0** | **0** |
| `decide` | 8 (samples 7, 14, 18, 21, 24, 29, 45, 49) | 6 (7, 14, 18, 24, 29, 45) |

Zero hits on every escape hatch, and zero occurrences even inside comments.
**`has_sorry = 0` is trustworthy, and so is the absence of the other hatches.**

`decide` is a legitimate decision procedure, not an escape hatch — it is checked
by the kernel. Noted only because `decide` on a large `Nat.choose` is the likely
source of the two multi-second verifications (§5).

---

## 3. Dead outcome branches — `timeout` and `verifier_crash`

### Is `timeout` structurally unreachable?

**No.** The brief's hypothesis is refuted by the code. `maxHeartbeats 0` disables
*Lean's internal* heartbeat counter, but an independent **Python-side wall-clock
limit exists and is enforced**:

- `config.py:45` — `VERIFY_TIMEOUT_SECONDS = 60`, documented as "Exceeding it is
  its own outcome (`timeout`), never silently folded into 'invalid'".
- `verifier.py:296` — `self.server.run(..., timeout=timeout)`.
- `verifier.py:297-305` — `except TimeoutError:` → `TIMEOUT` outcome, then
  `self._restart()`.

So `timeout` is reachable in principle. With `maxHeartbeats 0` it is in fact the
*only* thing that can stop a runaway elaboration.

### Does the exception handler swallow crashes into `compile_error`?

**No — and this is the one place the code is better than the brief assumed.**
`verifier.py:306-314` catches `Exception` and returns `VERIFIER_CRASH`, a
*distinct* outcome. Nothing reclassifies a crash as `compile_error`;
`compile_error` is only ever set at `verifier.py:240-241`, which requires the
REPL to have returned a response carrying error-severity messages.

### FINDING 1-C (medium) — the two handlers are ordered so `timeout` can be stolen

`verifier.py:297` catches `TimeoutError`; `verifier.py:306` catches `Exception`.
A timeout is only classified as `timeout` if `lean_interact` raises something
that *is* a `TimeoutError`. If it raises `subprocess.TimeoutExpired` (which
inherits `SubprocessError`, **not** `TimeoutError`) or its own timeout class,
the generic handler wins and a timeout is recorded as `verifier_crash`.

This is untested. `results/SUMMARY_n50_distinct.md:198` already concedes
"`verifier_crash` remains untested — no fixture exercises it", but does not
notice that the same gap makes the `timeout` classification unverified too.

### FINDING 1-D (high, latent) — `_classify` fails OPEN

`verifier.py:240-245`:

```python
if errors:            outcome = COMPILE_ERROR
elif sorries or sorry_warning: outcome = HAS_SORRY
else:                 outcome = VALID
```

`VALID` is the **else branch**. It is returned whenever the response carries no
error messages — including when the response carries *no messages at all*. There
is no positive confirmation that the declaration was actually added to the
environment: no check of `resp.env`, no `#print axioms`, no re-query of the
theorem name.

If the REPL ever returns an empty or degenerate response — a restored
environment that did not actually restore, a command silently dropped, a version
skew where messages arrive under a different key — every such trace scores
`valid`. The safe default for a verifier is to fail *closed*.

This is a **latent** defect: §5 below finds no evidence it fired on this run. But
it is the mechanism by which a false 74% would be produced, and it is one line
from being fixed (require `getattr(resp, "env", None) is not None` before
returning `VALID`).

### Fixtures — RUN, against the real local Mathlib

`tests/audit/phase1_live.py` was executed against the built `lean_project`
(Lake reports "Build completed successfully (8656 jobs)", Mathlib env
**unpickled in 92.8 s**, verifier ready in 242 s). Full output:
`results/phase1_live_probe.json`, build log `results/mathlib_build_evidence.log`.

| fixture | expected | **got** | time |
|---|---|---|---|
| `theorem t : True := by trivial` | valid | `valid` | 0.447 s (first call) |
| `n + 0 = n := by simp` | valid | `valid` | 0.050 s |
| `Nat.choose 5 2 = 10 := by decide` | valid | `valid` | 0.016 s |
| **`(2:Nat)+2 = 5 := by norm_num`** | **must NOT be valid** | **`compile_error`** — "unsolved goals ⊢ False" | 0.107 s |
| `n > 0 := by skip` | compile_error | `compile_error` — "unsolved goals" | 0.015 s |
| `exact totally_bogus_lemma_xyz` | compile_error | `compile_error` — "Unknown identifier" | 0.004 s |
| `:= by sorry` | has_sorry | `has_sorry` | 0.008 s |
| **`:= by admit`** | ? | **`has_sorry`** | 0.006 s |
| **`axiom cheat : 2+2=5` then `exact cheat`** | ? | **`valid`** ⚠ | 0.009 s |
| declaration-free file | empty_code | `empty_code` | 0 s |
| empty string | empty_code | `empty_code` | 0 s |
| `decide` on `Nat.choose 100000 50000` | timeout | `compile_error` — maxRecDepth | 0.100 s |

### This settles the timing question

**The negative controls fail, at the same millisecond scale as the positives.**
`2+2=5` is rejected in 107 ms, an unsolved goal in 15 ms, an unknown identifier
in **4 ms**. A pipeline that was not elaborating would have returned `valid` for
all three. Combined with `mode = shared_env` on every record and a Mathlib-only
lemma (`Nat.choose 5 2 = 10`) succeeding in 16 ms, this is conclusive:

> **Mathlib was genuinely imported, the sub-10 ms verifications are real
> elaborations against a warm environment, and no failure short-circuited before
> elaboration.** Issue #6's concern does not apply to this run.

It also means **FINDING 1-D did not fire.** The fail-open default is a real
design defect, but the negative controls prove the REPL was returning populated
responses throughout, so the 37 `valid` results are not empty-response artefacts.

### FINDING 1-F (HIGH — confirmed live, not hypothetical) — `axiom` is a working escape hatch

```lean
axiom cheat : (2:Nat) + 2 = 5
theorem t : (2:Nat) + 2 = 5 := by exact cheat
```
→ **`valid`**, in 9 ms.

The verifier never inspects the axioms a proof depends on. There is no
`#print axioms`, no check of `Lean.collectAxioms`, and no rejection of
user-declared `axiom` in the submitted source. Any generation that declares its
own axiom and cites it scores as a proved theorem.

- **Did it happen here? No.** The full scan of all 100 traces found **zero**
  `axiom` declarations (§2), so the reported 74% contains no axiom-laundered
  proof. The measured count is 0, not "we assume 0".
- **Is the hole real? Yes, demonstrated.** It is the one escape hatch in the
  brief's list that the pipeline does not close. `sorry` and `admit` are both
  caught (structurally, via the REPL's `sorries` list); `axiom` is not.

**Fix required (no GPU, no new generation):** either reject source containing a
top-level `axiom` declaration before verifying, or — better — assert after a
successful compile that the theorem's axiom dependencies are a subset of
`{propext, Classical.choice, Quot.sound}`. The second is the standard soundness
check and would also catch axioms introduced by other means.

### `timeout` and `verifier_crash` remain unfired

The `decide`-on-`Nat.choose 100000 50000` probe intended to force the timeout
path instead hit `maxRecDepth 10000` and returned `compile_error` in 100 ms. So:

- **`timeout` is reachable in code but was not triggered by any fixture.** The
  60 s wall clock is real, but `LEAN_MAX_REC_DEPTH = 10000` now bounds runaway
  elaboration *before* the clock can expire, making `timeout` even less
  reachable in practice than the taxonomy implies.
- **`verifier_crash` remains untested**, as the summary already concedes
  (`SUMMARY_n50_distinct.md:198`). Finding 1-C — that a non-`TimeoutError`
  timeout would be misfiled as `verifier_crash` — is therefore **still
  unresolved**, and is listed in UNRESOLVED.

Both counts being 0 in the reported table is consistent with a clean run rather
than dead code, but only the *branch existence* has been verified, not the
branch *behaviour*.

## 4. Truncation

**Refuted — there is nothing to report, and the summary's silence is honest.**

Issue #4's `MAX_NEW_TOKENS = 20000` against a 4096 context was fixed *before*
these runs. `config.py:154-159` documents the model's real limits
(`max_position_embeddings = 4096`, `rope_scaling = null`) and sets
`MAX_NEW_TOKENS = 2048`, matching the official eval script. Both
`run_meta.json` sidecars record `"max_new_tokens": 2048`.

Measured over all 100 traces:

| Field | T=0.0 | T=0.2 |
|---|---|---|
| `truncated` true | **0** | **0** |
| `hit_token_limit` true | **0** | **0** |
| `closed_fence` false | **0** | **0** |
| `stopped_on_eos` false | **0** | **0** |
| `extract_status` | `extracted` ×50 | `extracted` ×50 |
| max `generated_tokens` | **579** of 2048 | **615** of 2048 |
| max `prompt_tokens` | 296 | 296 |

Every generation stopped on EOS with its fence closed, using at most 30% of its
token budget. **No truncated generation exists, so none was misclassified as
`compile_error`, and the absent truncation row in the outcome table is correct
rather than a concealment.** The trace schema does carry `truncated`,
`hit_token_limit`, `closed_fence` and `stopped_on_eos`, so the check is cheap
and should be reported as an explicit zero rather than omitted.

---

## 5. Was Mathlib genuinely imported? The sub-second verifications

### What the recorded artifacts show

`results/recompute_stats.py` §5, from `verify2_temp0.{0,2}.jsonl`:

| | T=0.0 | T=0.2 |
|---|---|---|
| Total (sum of per-record `seconds`) | 33.0 s | 37.7 s |
| Mean | 0.660 s | 0.753 s |
| Min | **0.009 s** | **0.009 s** |
| Max | 27.687 s (sample 44) | 23.468 s (sample 44) |
| Under 50 ms | **30 / 50** | **28 / 50** |
| `mode` | `shared_env` ×50 | `shared_env` ×50 |

The headline "~0.7 s each" is a mean dragged up by one 27.7 s outlier. The
**median verification is under 50 ms**, and 24 of the 37 `valid` results at
T=0.0 landed there.

### The architectural reason, and why it is legitimate

Issue #6's fear (Mathlib never fetched, failures short-circuiting before
elaboration) does **not** apply to this run:

1. Mathlib is genuinely present. `lean_project/.lake/packages/` contains
   `mathlib`, `batteries`, `aesop`, `Qq`, `proofwidgets`, `importGraph`, `Cli`,
   `plausible`, `LeanSearchClient` — a real resolved dependency tree, and
   `lean_project/lake-manifest.json` pins mathlib at commit
   **`81a5d257c8e410db227a6665ed08f64fea08e997`** (`inputRev v4.32.0`).
2. `import Mathlib` is paid **once per process**, not once per verification.
   `verifier.py:184-227` builds a base environment and snapshots it to
   `lean_project/mathlib_env.olean_pickle`; later processes `UnpickleEnvironment`
   it in seconds. Per-trace `seconds` (`verifier.py:261`, `316`) times only the
   snippet, so it *correctly excludes* the import.
3. `mode = shared_env` on all 100 records confirms the fast path ran — reached
   only when the snippet's imports are exactly `{Mathlib, Aesop}`
   (`verifier.py:286`). Against a warm environment, elaborating one small
   theorem in milliseconds is expected.
4. The two slow samples (12 and 44, slow at *both* temperatures) are consistent
   with real kernel work: sample 12 is the `Nat.choose 1996 4` case that needed
   `maxRecDepth 10000`, and `decide`-style reduction is exactly what costs
   seconds.

So the speed is explained by the architecture, and there is **no evidence of
short-circuiting**. The failures are not fast-and-empty either: five
`compile_error`s at each temperature also complete in <50 ms, which is what a
parse/elaboration error against a warm environment looks like.

### What is still not proven

Fast-and-correct and fast-and-empty are indistinguishable from the timing alone,
because of FINDING 1-D: an empty response also yields `valid`. The decisive
evidence is a **negative control** — a snippet that must not compile. If
`theorem t : (2:Nat)+2 = 5 := by norm_num` returns `compile_error` from the same
warm environment at the same millisecond scale, the pipeline is elaborating.
That is what `tests/audit/phase1_live.py` runs; see
`results/phase1_live_probe.json` for the outcome. (The repo also already carries
`results/control_set_run.json`, a 35/35 control set from PR #9, which is
independent corroboration that the verifier discriminates.)

### FINDING 1-E (low) — the reported timing is not reproducible from the artifact

`SUMMARY_n50_distinct.md:37` reports "33.5s (T=0.0) and 38.0s (T=0.2)". Summing
the per-record `seconds` gives **33.0 s and 37.7 s**. The gap is the
`statement_is_broken()` re-probes and loop overhead, which are wall-clock but
never recorded per record. Small, but it means the stated figure cannot be
derived from any committed file. Report the artifact-derived sum, or record
wall-clock in the JSONL.

---

## Summary of Phase 1 findings

All six were fixed after the audit and the result re-verified across all 100
traces (`results/verify3_temp0.{0,2}.jsonl`) — **no outcome changed**.

| ID | Severity | Finding | Status | Changed 74%? |
|---|---|---|---|---|
| **1-F** | **High** | `axiom` was a working escape hatch: a self-declared axiom cited in the proof returned `valid` in 9 ms | **FIXED** — `verifier._axiom_audit()` runs `#print axioms` and rejects untrusted deps as `unsound_axioms`. Fixture now returns `unsound_axioms`; all 37 positives re-audited, 0 rejections | No |
| 1-D | High | `_classify` made `VALID` the else-branch; an empty response scored valid | **FIXED** — fails closed. The bogus-environment fixture proves the old code would have scored an un-elaborated snippet as a proved theorem | No |
| 1-A | Medium | Statement fidelity enforced by prompt construction only | **FIXED** — `verify_traces.statement_mismatch()`, new outcome `statement_mismatch`. 0 mismatches in 100 traces | No |
| 1-C | Medium | `timeout` / `verifier_crash` never fired by any fixture | **FIXED by fixture** — `tests/audit/phase1_deadbranches.py`, 4/4 pass. `timeout` classifies as `timeout` (so `lean_interact` does raise a real `TimeoutError`), `verifier_crash` fires, and the verifier recovers from both. Residual: no *organic* timeout is reachable, since `maxRecDepth` bounds elaboration first | No |
| 1-B | Low | Two different `has_sorry` fields, one a regex | **FIXED** — parser's renamed `has_sorry_literal`, consumers updated | No |
| 1-E | Low | Reported wall-clock not derivable from the artifacts | **FIXED in the summary** — artifact-derived figures reported, with the median alongside the mean | No |

**Gate result: PASS, and now defended.** `valid` means the model produced a Lean
proof of the dataset's statement — a claim now *asserted per record* rather than
holding by luck of prompt construction — with no `sorry`, no `admit`, no
truncation, standing only on axioms Lean itself confirms are in the trusted set,
against a genuinely imported Mathlib whose negative controls fail correctly.
`results/CRITICAL.md` was never written, because the condition for it was false
in fact even when it was true in the verifier code.
