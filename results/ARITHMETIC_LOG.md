# Arithmetic provenance — running log

Append-only. Branch `audit/arithmetic-provenance`, forked from
`audit/summary-n50-repair` @ `3662aef`.

---

## 2026-08-19T02:10Z — Phase 0 — recover the source

**Checked:** field inventory of every trace and verification file on this branch.

**The stated blocker does not exist — but the diagnosis was half right.**
The task says "the existing trace JSONL does not retain the Lean code" and lists
the fields present. Those are exactly the fields of the **verification** JSONL
(`results/verify*.jsonl`, `results/verification_temp_0.jsonl`). The **trace**
JSONL is a different file and it *does* retain everything:

| file | n | code fields |
|---|---|---|
| `traces/temp_0.jsonl` | 500 | `full_code`, `parsed_code`, `formal_statement`, `reference_proof`, `raw_output` |
| `traces/temp0.0_n50_1each/traces.jsonl` | 50 | same |
| `traces/temp0.2_n50_1each/traces.jsonl` | 50 | same |
| `results/verification_temp_0.jsonl` | 50 | **none** |
| `results/verify3_temp0.{0,2}.jsonl` | 50 | **none** |

So no schema change, no re-verification and no new generation is needed: the two
sides join on `sample_index`. The real defect is narrower and worth recording —
**the verification record is not self-contained.** Anyone handed only a
`verify*.jsonl` cannot tell what was proved, which is exactly the trap this task
walked into. Recommended fix (not applied; it would rewrite committed artifacts):
carry `formal_statement` and a `full_code` sha256 into the verification record.

**Failing samples located:** baseline 29/50, n50 T=0.0 13/50, n50 T=0.2 13/50.

---

## 2026-08-19T02:35Z — Phase 1 — arithmetic checker

**Built** `tests/audit/lean_arith.py`: exact evaluation of Lean numeric syntax.
Everything is `int`/`Fraction`, never `float` — the literals run to 13 digits and
a float round-trip would silently agree with a wrong answer. Handles `^`, `!`,
`Nat.factorial`, `Nat.choose`, `Nat.div/sub/pow`, and honours the numeric domain:
ℕ division is floor and ℕ subtraction truncates at 0, so `5 / 6 = 0`.

**Self-test: 21/21 pass**, including every case the task specified:

| claim | verdict | value |
|---|---|---|
| `101^2 = 10301` | FALSE | 10201 |
| `1061520.150601 = 10303 * 103` | FALSE | 1061209 |
| `1061520150601 = 1.061520150601e9` | FALSE | off by 1000× |
| `100^3 + 3*100^2*6 + 10800 = 1061520150601` | FALSE | 1190800 |
| **`101^6 = 1061520150601`** | **TRUE — not flagged** | ✅ |

**Three bugs found in my own checker and fixed before trusting it:**

1. Missing comma in the token whitelist, so rewritten calls like `CHOOSE(52,3)`
   were rejected as unevaluable.
2. `\(?(NUM)\)?` matched a bare argument and swallowed the *enclosing* group's
   closing paren (`FACT 2)` ate the `)` of `(FACT 2 * FACT 2)`). Argument
   parentheses are now balanced-or-absent.
3. Greedy `\S+` in the theorem-name strip ate the colon in
   `theorem test: 1061520150601 = ...`, leaving an empty goal for every
   binder-free statement — which is most of the baseline set.

Plus one in the statement parser: FormalStep wraps most goals in parentheses, so
the top-level `=` sat at depth 1 and was invisible. `strip_outer_parens()` added.

**The load-bearing step is SUBSTITUTION.** `theorem test (x : ℕ) (h₀ : x = 101^2)
: (x = 10303)` contains no false equality until `h₀` is substituted into the
goal; only then does it read `10201 = 10303`. Before substitution the classifier
found **zero** `statement_false`; after, it found 26.

---

## 2026-08-19T03:05Z — Phase 1 — RESULT

`tests/audit/provenance.py` → `results/arithmetic_provenance.json`.

| label | baseline (29 fail) | n50 T=0.0 (13 fail) | n50 T=0.2 (13 fail) |
|---|---|---|---|
| `statement_false` | **18** | **4** | **4** |
| `proof_false` | **0** | **0** | **0** |
| `tactic_mismatch` | 10 | 5 | 4 |
| `parse_skew` | 0 | 4 | 4 |
| `noop_tactic` | 1 | 0 | 0 |
| `budget` | 0 | 0 | 0 |
| `UNKNOWN` | 0 | 0 | 1 |

**`proof_false` is zero in all three sets.**

**Corroboration from two independent signals.** For the n50 sets, all 4
`statement_false` samples carry dataset `state = "Failure of Proof"` — 4/4, no
exceptions — and 4/4 ship with an **empty `reference_proof`**. FormalStep itself
could not prove these statements. An arithmetic checker that never saw those
labels reached the same verdict from the numbers alone.

**Proof-side coverage, stated honestly.** Only **1** proof-side equality was
assertable across all 55 failing samples (s6, `101^2 = 10301`, false — but its
statement was already false). That is not a gap in the scan: **0 of 13 n50
failing proofs write any multi-digit literal at all.** The model routes
arithmetic through `norm_num`/`decide`/`linarith` instead of hand-computing, so
there is almost nothing on the proof side to be wrong. That is the Phase 3
answer arriving early.

**Verified my own false-positive risk on the four n50 cases by hand:**

- `5 / 6 = 1 - 1 / 6` — the *mathematics* is right; the *formalisation* omits the
  type, so Lean elaborates it over ℕ where `5/6 = 0` and `1 - 1/6 = 1`. False as
  written. Lean agrees: the recorded error is `unsolved goals ⊢ False`.
- `(11! / (9! + 2 * 8!)) = (11 * 10 / (9 + 2))` — 90 vs 10. False in any domain.
- `total_cubes - interior_cubes = 36` with `64` and `(4-2)^3 = 8` — 56 vs 36.
- `(6! + 7!) / 5! = 8` — 5760/120 = 48 vs 8. False in any domain.

**Deliverable:** `results/arithmetic_provenance.json`, `tests/audit/lean_arith.py`,
`tests/audit/provenance.py`.

---

## 2026-08-19T03:45Z — Phase 2 — pipeline ruled out

**Checked:** `tests/audit/pipeline_checks.py`.

1. **Prompt template — clean.** `PROMPT_TEMPLATE` is absent on `master`, present
   from PR #8 on. Both sets carry it (`prompt` field starts with the template
   verbatim). Stronger check: the statement appears verbatim in `full_code` and
   there is exactly one declaration in **600/600 records across all three sets**.
   The model could not have substituted its own theorem, so every statement
   analysed in Phase 1 is FormalStep's text.
2. **BPE / numeric tokenization — clean.** `repair_bpe()` only fires on `Ġ/Ċ/ĉ`,
   and **0 of 600 records contain any**. Checked anyway in both directions on
   every 4+ digit literal: **618 checks, 0 corrupted.** (My first version of this
   check compared against `formal_statement` instead of the whole `prompt` and
   appeared to show 90 corruptions — the informal-step doc-comment supplies
   literals too. Against the full prompt it is zero.)
3. **Truncation — clean and non-vacuous.** `truncated` is computed from tensor
   shapes at `model.py:195-210`, not hardcoded. Every generation stopped on EOS
   with a closed fence, max 660 of 2048 tokens, ≥1388 tokens of headroom. The
   **baseline set also used 2048**, so it too post-dates issue #4.

**Verdict: not contaminated.** The Phase 1 finding stands.

**Deliverable:** `results/PIPELINE_RULED_OUT.md`, `tests/audit/pipeline_checks.py`.

---

## 2026-08-19T04:05Z — Phase 3 — delegation hypothesis: NOT TESTABLE, and that is the answer

**Checked:** `tests/audit/delegation.py`, over ALL samples, not just failures. A
sample counts as hand-computing if its proof body writes a multi-digit literal
that appears in neither the statement nor the prompt.

| set | hand-computed | delegated | validity \| hand | validity \| delegated |
|---|---|---|---|---|
| baseline | **2**/50 | 48/50 | 1/2 = 50% [9–91%] | 20/48 = 42% [29–56%] |
| n50 T=0.0 | **1**/50 | 49/50 | 1/1 = 100% [21–100%] | 36/49 = 73% [60–84%] |
| n50 T=0.2 | **0**/50 | 50/50 | n/a | 37/50 = 74% [60–84%] |

**The hypothesis cannot be tested because the behaviour does not occur.** With
2, 1 and 0 hand-computing proofs, the cross-tab has no power — a 1/1 cell is not
evidence of anything.

But the negative result is itself the finding: **the model already does the right
thing.** It routes arithmetic through `norm_num`/`decide`/`linarith`/`rfl` rather
than writing intermediate values by hand, in 48/50, 49/50 and 50/50 proofs. There
is no prompting or few-shot fix to recommend here, because the failure mode the
hypothesis predicted is absent. Chasing it would be work against a problem that
does not exist in this data.

This also explains Phase 1's tiny proof-side denominator: only 1 proof-side
equality was assertable across all 55 failures, precisely because the model
hardly ever asserts one.

**Deliverable:** `tests/audit/delegation.py`.

---

## 2026-08-19T04:15Z — Phase 4 — repair loop: REQUIRES A NEW GENERATION RUN

Feeding the Lean error back for a retry needs Goedel-Prover-SFT (≈7B) loaded on a
GPU. `traces/PROVENANCE.md` records that the Lambda A10 instance was terminated
after the run, and this host has no GPU. **Not attempted.** Logged under
"requires a new run" per the ground rules.

Worth stating for whoever does run it: a repair loop cannot help the dominant
bucket. 26 of 55 failures are `statement_false` — the goal is arithmetically
false, so no retry can produce a proof, and any apparent gain would come from the
model finding a way to exploit contradictory hypotheses rather than from better
proving. The bucket a repair loop could legitimately move is `tactic_mismatch`
(10 + 5 + 4 = 19 samples), and that is the number to report against.
