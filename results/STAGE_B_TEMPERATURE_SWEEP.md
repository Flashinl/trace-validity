# Stage B temperature sweep: T = 0.0 vs T = 0.7

Goedel-Prover-SFT on the committed 90-problem NuminaMath Number Theory eval set
(30 per Kimina win-rate band, binder fixes applied, 90/90 elaborating). One
trajectory per problem, seed 0, both temperatures generated in a single process
so the model loaded once.

**Token budget held constant at 2048 across both arms**, deliberately. It is the
documented Goedel eval budget (the upstream vLLM script uses
`SamplingParams(max_tokens=2048)`), and holding it fixed is what lets the paired
comparison isolate temperature. Truncation behaviour then becomes an observation
rather than a confound — see §5.

- Generation: Lambda A10, instance `840ebf116e0a40518b199454d78fa419`, 57.3 min
  for both arms, terminated and confirmed via the API before verification began.
- Traces: `results/stage_b_traces_temp{0.0,0.7}.jsonl`
  (sha256 verified on both ends; `5a7dc374…`, `3e5e660c…`)
- Verification: `results/stage_b_verified_temp{0.0,0.7}.jsonl`, Lean 4.32.0, CPU only
- Report: `results/STAGE_B_SWEEP.json`

---

## 1. Reproduction check

T = 0.0 is greedy with a fixed seed, so it should reproduce the committed run
exactly. It does:

- **90/90 byte-identical generations** vs `results/stage_b_traces.jsonl`, on a
  freshly provisioned A10.
- **88/90 identical verdicts.** The two that differ are exactly the two rows the
  `statement_is_broken()` repair targeted: `statement_error → compile_error`,
  now carrying `statement_probe="unknown"`. See `AUTOFORMALIZATION_NOISE.md` §4.
- Valid count unchanged: 28 both times.

`statement_mismatch` fired **0 times at both temperatures** — the documented
alarm is silent, which is the expected state after PR #23.

---

## 2. Pass rates

Denominators stated. `parse_failure` (truncation) and `timeout` are **not
verdicts on the model's proof**, so a judged-only column is given alongside.

### T = 0.0

| | rate | 95% CI |
|---|---|---|
| compiling proof of the target (all 90) | 28/90 = 31.1% | [22.5–41.3] |
| over judged attempts only | 28/80 = 35.0% | [25.5–45.9] |

10 not a verdict: 6 timeout, 4 parse_failure.
Outcomes: `compile_error` 52, `valid` 28, `timeout` 6, `parse_failure` 4.

| band | all attempted | judged only |
|---|---|---|
| easy | 18/30 = 60.0% [42.3–75.4] | 18/27 = 66.7% [47.8–81.4] |
| medium | 7/30 = 23.3% [11.8–40.9] | 7/26 = 26.9% [13.7–46.1] |
| hard | 3/30 = 10.0% [3.5–25.6] | 3/27 = 11.1% [3.9–28.1] |

### T = 0.7

| | rate | 95% CI |
|---|---|---|
| compiling proof of the target (all 90) | 26/90 = 28.9% | [20.5–39.0] |
| over judged attempts only | 26/84 = 31.0% | [22.1–41.5] |

6 not a verdict: 5 timeout, 1 parse_failure.
Outcomes: `compile_error` 58, `valid` 26, `timeout` 5, `parse_failure` 1.

| band | all attempted | judged only |
|---|---|---|
| easy | 16/30 = 53.3% [36.1–69.8] | 16/27 = 59.3% [40.7–75.5] |
| medium | 6/30 = 20.0% [9.5–37.3] | 6/29 = 20.7% [9.8–38.4] |
| hard | 4/30 = 13.3% [5.3–29.7] | 4/28 = 14.3% [5.7–31.5] |

---

## 3. Which bands actually separate

**Easy separates from the rest. Medium and hard do not separate from each
other.** This reproduces the earlier finding.

At T = 0.0, easy [42.3–75.4] barely clears medium [11.8–40.9], and medium
[11.8–40.9] overlaps hard [3.5–25.6] across most of its range. At T = 0.7 the
picture is the same, and medium (20.0%) and hard (13.3%) are within noise of
each other in both directions — at T = 0.7 hard is *nominally above* its T = 0.0
value while medium is below, which is exactly what non-separation looks like.

The Kimina win-rate banding therefore gives us **two** usable difficulty levels,
not three. Any per-band claim should be made as easy-vs-rest.

---

## 4. Paired comparison

McNemar exact on the 90 matched problems — the correct test, since both
temperatures see the identical eval set.

| | count |
|---|---|
| both pass | 19 |
| only T = 0.0 passes | 9 |
| only T = 0.7 passes | 7 |
| neither passes | 55 |

**16 discordant pairs, McNemar exact p = 0.8036.** (6 discordant pairs is the
minimum at which a two-sided exact test *can* reach α = 0.05, so the test was
not underpowered by design — it simply found nothing.)

**Temperature does not move the pass rate on this eval set.** The 31.1% → 28.9%
difference is well inside noise, and the churn beneath it is substantial: 16 of
90 problems changed outcome while the totals barely moved.

Per band: easy 5 lost / 3 gained, medium 3 / 2, hard 1 / 2. No band shows a
directional effect.

### The 16 samples that changed

| uuid | band | T=0.0 | T=0.7 |
|---|---|---|---|
| 009e6379 | hard | compile_error | **valid** |
| 01f553d0 | easy | compile_error | **valid** |
| 024ee395 | medium | compile_error | **valid** |
| 02524791 | easy | **valid** | compile_error |
| 02f5af73 | easy | compile_error | **valid** |
| 03bc6582 | easy | compile_error | **valid** |
| 04f77b5a | easy | **valid** | compile_error |
| 05586642 | easy | **valid** | timeout |
| 05f52ec2 | hard | **valid** | timeout |
| 064daf4b | medium | **valid** | compile_error |
| 07aae92f | medium | **valid** | compile_error |
| 082c0e7e | easy | **valid** | compile_error |
| 08f69b4a | medium | timeout | **valid** |
| 0978a628 | easy | **valid** | compile_error |
| 09dc389f | hard | parse_failure | **valid** |
| 0b58d370 | medium | **valid** | compile_error |

Two of the nine T=0.0-only "losses" (05586642, 05f52ec2) went to `timeout`, not
to a wrong proof — those are non-verdicts, so the true proof-side loss is 7, not
9. Two of the seven T=0.7 gains came *from* non-verdicts (08f69b4a from timeout,
09dc389f from parse_failure).

---

## 5. Truncation went **down** at the higher temperature

| | truncated (hit the 2048 budget) | median generated tokens | max |
|---|---|---|---|
| T = 0.0 | 4/90 = 4.4% [1.7–10.9] | 414 | 2048 |
| T = 0.7 | **1/90 = 1.1%** [0.2–6.0] | 430 | 2048 |

This is the reportable observation the constant budget bought, and it runs
against the intuition that motivated raising the budget in the first place.

Greedy decoding is the arm that gets stuck in repetition loops and runs to the
token limit; sampling at 0.7 breaks out of them. The median generation length is
essentially unchanged (414 vs 430), so this is not "0.7 writes shorter proofs" —
it is a small number of degenerate greedy generations disappearing.

The intervals overlap, so this is suggestive rather than established (3/90
difference). But it removes the case for raising the budget to chase
truncations: at T = 0.7 there is one truncation in 90, and truncations are
`parse_failure` — excluded from verdicts either way.

---

## 6. Axiom audit

| | passes | axiom sets |
|---|---|---|
| T = 0.0 | 28 | 17 × `Classical.choice, Quot.sound, propext`; 7 × `Quot.sound, propext`; 4 × `propext` |
| T = 0.7 | 26 | 20 × `Classical.choice, Quot.sound, propext`; 3 × `Quot.sound, propext`; 3 × `propext` |

**Zero passes at either temperature depend on an axiom outside the trusted set**
(`Classical.choice`, `Quot.sound`, `propext`). No `sorryAx`, no custom axioms.

Zero-event upper bounds: ≤ 10.1% over 28 passes (T=0.0), ≤ 10.9% over 26
(T=0.7). The audit is clean, but with fewer than 30 passes per arm it could not
have detected a rare axiom leak — state the bound, not "no leaks exist."

Note that a clean axiom audit is **not** evidence of a contentful proof: the
documented FormalStep false positive (sample 42, a false goal proved from
contradictory premises) also audits clean at `propext`. See
`CONTENTLESS_STEPS.md` §8.

---

## 7. Failure taxonomy

Denominator is `compile_error` rows only; non-verdicts are excluded.

| failure_kind | T=0.0 (n=52) | T=0.7 (n=58) |
|---|---|---|
| tactic_failed | 26 (50%) | 23 (40%) |
| unsolved_goals | 8 (15%) | 10 (17%) |
| unknown_identifier | 9 (17%) | 8 (14%) |
| tactic_no_progress | 6 (12%) | 8 (14%) |
| elaboration_error | 1 (2%) | 2 (3%) |
| type_mismatch | 1 (2%) | 2 (3%) |
| no_goals | 1 (2%) | 1 (2%) |
| goal_is_false | 0 | **1 (2%)** |
| other | 0 | 3 (5%) |

The distribution is broadly stable. `tactic_failed` dominates at both
temperatures. T = 0.7 spreads slightly further into the long tail (`other` 3,
`goal_is_false` 1), consistent with sampling producing more varied malformed
output.

The `arithmetic` axis reads `unknown` for 100% of failures at both temperatures
**by design** — provenance labels come from `tests/audit/provenance.py` and are
joined in afterwards by `classify_results.py`. Stage B has never been run
through the provenance labeller, so no arithmetic-provenance claim may be made
about these 110 failures. See `AUTOFORMALIZATION_NOISE.md` §5.

---

## 8. What this run licenses, and what it does not

**Licensed:**
- Temperature 0.0 vs 0.7 makes no detectable difference to the pass rate on this
  eval set (McNemar p = 0.80, 16 discordant of 90).
- Easy separates from medium and hard; medium and hard do not separate.
- No pass at either temperature rests on an untrusted axiom, to within a ~10%
  zero-event bound.
- The T = 0.0 pipeline reproduces byte-exactly on fresh hardware.

**Not licensed:**
- Nothing about `proof_false` — the provenance labeller has never been run on
  Stage B, and on FormalStep it has evaluated **1** proof-side claim across 55
  failure records.
- No comparison to FormalStep's 74%. Different formalization pipelines,
  different units, and Stage B's contentless share is 0 while FormalStep's is
  30.5%.
- Nothing about single-trajectory pass@1 generalising to pass@k; this is one
  trajectory per problem.
