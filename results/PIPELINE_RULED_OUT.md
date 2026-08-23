# Phase 2 — is the bad arithmetic our fault?

Before attributing false numbers to either the dataset or the model, three ways
the pipeline itself could manufacture them. **All three are ruled out.** The
Phase 1 finding is not contaminated.

Evidence script: `tests/audit/pipeline_checks.py`.

---

## 1. Prompt template (issue #3) — RULED OUT

If the model were handed a raw untokenized string, it could invent its own
theorem, and any bad numbers in that invented statement would be an artefact of
our prompting rather than anything about the dataset or the prover.

`PROMPT_TEMPLATE` is absent from `config.py` on `master` and present on
`fix/generation-input-path` (PR #8) and every branch after it. Both trace sets
were generated with it: the recorded `prompt` field of the first record of each
begins

```
Complete the following Lean 4 code with explanatory comments preceding each line of code:

```lean4
import Mathlib
import ...
```

which is `PROMPT_TEMPLATE` verbatim, in **both** `traces/temp_0.jsonl` and
`traces/temp0.0_n50_1each/traces.jsonl`.

The stronger check is whether the model *could* have substituted its own
statement. It could not:

| set | statement present verbatim in `full_code` | exactly one declaration |
|---|---|---|
| baseline `temp_0.jsonl` (500 records) | **500/500** | **500/500** |
| n50 T=0.0 | **50/50** | **50/50** |
| n50 T=0.2 | **50/50** | **50/50** |

600 of 600 records. The prompt ends mid-fence immediately after the dataset's
`formal_statement` (which already terminates in `:= by`), so the model writes a
proof body only. **Every statement analysed in Phase 1 is FormalStep's text, not
the model's.**

## 2. Numeric tokenization / BPE repair — RULED OUT

A dropped digit during BPE repair would look exactly like a model arithmetic
error, and `1061520150601` is 13 digits — many BPE tokens.

`parser.repair_bpe()` only acts when the byte-level artifact characters `Ġ`,
`Ċ` or `ĉ` are present (`parser.py:30-31`). Measured: **0 of 600 records contain
any of them.** The repair path is a no-op on this data.

Checked in both directions anyway, on every literal of 4+ digits:

| direction | checked | corrupted |
|---|---|---|
| literals in `full_code` but not in the prompt (so they came from the completion) → must appear in `raw_output` | **77** | **0** |
| literals in `raw_output` → must survive into `full_code` or the prompt | **541** | **0** |

618 checks, zero digit corruption. *(A first version of this check compared
against `formal_statement` rather than the whole `prompt` and appeared to show 90
corruptions. That was my error: `full_code` also contains the informal-step
doc-comment, which the prompt supplies. Against the full prompt the count is
zero.)*

## 3. Truncation (issue #4) — RULED OUT

`truncated` is genuinely computed, not hardcoded (`model.py:195-210`):

```python
stopped_on_eos  = n_gen < int(gen_tokens.shape[0])
hit_token_limit = (not stopped_on_eos) and n_gen >= max_new_tokens
closed_fence    = "```" in text
"truncated": hit_token_limit or not closed_fence,
```

It derives from tensor shapes and the decoded text. And it is not vacuously
false — there is real headroom:

| set | `max_new_tokens` | max generated | headroom | truncated | closed_fence |
|---|---|---|---|---|---|
| baseline (500) | 2048 | 660 | 1388 | 0 | 500/500 True |
| n50 T=0.0 | 2048 | 579 | 1469 | 0 | 50/50 True |
| n50 T=0.2 | 2048 | 615 | 1433 | 0 | 50/50 True |

Every generation stopped on EOS with its fence closed, using at most 32% of its
budget. Note the **baseline set also used 2048**, so it too post-dates issue #4's
fix — `MAX_NEW_TOKENS = 20000` never touched either set.

---

## Verdict

None of the three is implicated. The false numbers found in Phase 1 are in text
that FormalStep supplied, transmitted to the model intact, and returned intact.

One caveat worth stating rather than burying: these checks establish that the
pipeline did not *corrupt* the statements. They do not establish that the
statements were *well chosen* — sample 5's `5 / 6 = 1 - 1 / 6` is false only
because the formalisation omits a type ascription and Lean defaults to ℕ. That
is a defect in FormalStep's formalisation, not in our transmission of it, and it
is counted as `statement_false` for exactly that reason.
