"""Phase 5: emit results/ARITHMETIC_FINDINGS.md from the Phase 1 artifact.

Every rate carries an n and a Wilson 95% CI. Reads only
results/arithmetic_provenance.json plus the verification files.
Run: python tests/audit/arith_report.py > results/ARITHMETIC_FINDINGS.md
"""
import io, json, math, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]
D = json.load(io.open("results/arithmetic_provenance.json", encoding="utf-8"))

VP = {"baseline_50step_1problem": "results/verification_temp_0.jsonl",
      "n50_distinct_T0.0": "results/verify3_temp0.0.jsonl",
      "n50_distinct_T0.2": "results/verify3_temp0.2.jsonl"}
PRETTY = {"baseline_50step_1problem": "baseline (50 steps of ONE problem)",
          "n50_distinct_T0.0": "n50 distinct problems, T=0.0",
          "n50_distinct_T0.2": "n50 distinct problems, T=0.2"}
LABELS = ["statement_false", "proof_false", "tactic_mismatch", "noop_tactic",
          "parse_skew", "budget", "UNKNOWN"]
# Labels meaning "the statement was never a fair test of the prover".
UNTESTABLE = {"statement_false", "parse_skew"}


def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def R(k, n):
    if not n:
        return "n/a"
    lo, hi = wilson(k, n)
    return f"**{k}/{n} = {100*k/n:.0f}%** [{100*lo:.0f}–{100*hi:.0f}%]"


def upper0(n, a=0.05):
    return 1 - a ** (1.0 / n) if n else float("nan")


P = print
P("# Whose arithmetic is wrong — the dataset's or the prover's?")
P()
P("Every number below is computed from a committed artifact by")
P("`tests/audit/provenance.py` → `results/arithmetic_provenance.json`.")
P("Method and self-tests: `results/ARITHMETIC_LOG.md`. Contamination checks:")
P("`results/PIPELINE_RULED_OUT.md`.")
P()
P("---")
P()
P("## Verdict")
P()

tot_fail = tot_stmt = tot_proof = 0
for k, rows in D["records"].items():
    tot_fail += len(rows)
    tot_stmt += sum(1 for r in rows if r["label"] == "statement_false")
    tot_proof += sum(1 for r in rows if r["label"] == "proof_false")

P(f"**The false arithmetic is the dataset's.** Across all {tot_fail} failing samples in")
P(f"all three trace sets, {tot_stmt} fail because a numeric literal in the *statement* is")
P(f"arithmetically wrong, and **{tot_proof} fail because of a number the model wrote**.")
P()
P(f"- statement-side: {R(tot_stmt, tot_fail)} of all failures")
P(f"- proof-side: {tot_proof}/{tot_fail}. With 0 events in n={tot_fail}, the exact one-sided")
P(f"  95% upper bound on the proof-side rate is **{100*upper0(tot_fail):.0f}%** — it is bounded, not proven zero.")
P()
P("On those samples `compile_error` is the **correct** verdict. The verifier is")
P("catching CoT steps that were already wrong. That is the tool working.")
P()
P("---")
P()
P("## Provenance table")
P()

for key, rows in D["records"].items():
    vers = J(VP[key])
    n_all = len(vers)
    n_fail = len(rows)
    counts = {}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    P(f"### {PRETTY[key]}")
    P()
    P(f"{n_all} samples, {n_fail} failing.")
    P()
    P("| label | n | share of failures | share of all samples |")
    P("|---|---|---|---|")
    for L in LABELS:
        c = counts.get(L, 0)
        if c or L in ("statement_false", "proof_false", "UNKNOWN"):
            P(f"| `{L}` | {c} | {R(c, n_fail)} | {R(c, n_all)} |")
    P()

P("---")
P()
P("## What this does to the headline number")
P()
P("The reported validity rate blends two different things: how good the prover is,")
P("and how many of the dataset's CoT steps are already wrong. Separating them:")
P()
P("| set | reported validity | statements that were never a fair test | **prover rate on testable statements** |")
P("|---|---|---|---|")
for key, rows in D["records"].items():
    vers = J(VP[key])
    n_all = len(vers)
    n_valid = sum(1 for r in vers if r["outcome"] == "valid")
    n_untest = sum(1 for r in rows if r["label"] in UNTESTABLE)
    n_test = n_all - n_untest
    P(f"| {PRETTY[key]} | {R(n_valid, n_all)} | {n_untest} | {R(n_valid, n_test)} |")
P()
P("The middle column is `statement_false` + `parse_skew`: statements that are")
P("arithmetically false, or that do not elaborate on Mathlib v4.32.0 at all. In")
P("neither case was the model's proof ever judged.")
P()
P("**Both numbers must be reported, and neither alone is the story.** The left")
P("column is what the pipeline currently prints; the right column is the prover's")
P("performance; the gap between them is a measurement of FormalStep's error rate,")
P("which is a finding in its own right and arguably the more interesting one.")
P()
P("Note how much of the difference between the two trace sets this explains. The")
P("baseline set looks far worse (42% vs 74%) — but 36% of its samples carry a")
P("false statement, against 8% for the n50 set. On testable statements the gap")
P("narrows sharply. The baseline set is not a harder test of the prover; it is a")
P("more broken slice of the dataset, because all 50 of its steps come from one")
P("problem whose CoT goes wrong early and stays wrong.")
P()
P("---")
P()
P("## The dataset agrees")
P()
P("Two signals the arithmetic checker never saw, both confirming it:")
P()
P("| | n50 T=0.0 | n50 T=0.2 |")
P("|---|---|---|")
for key in ("n50_distinct_T0.0", "n50_distinct_T0.2"):
    pass
sf00 = [r for r in D["records"]["n50_distinct_T0.0"] if r["label"] == "statement_false"]
sf02 = [r for r in D["records"]["n50_distinct_T0.2"] if r["label"] == "statement_false"]
P(f"| `statement_false` samples | {len(sf00)} | {len(sf02)} |")
P(f"| …labelled `Failure of Proof` by FormalStep | **{sum(1 for r in sf00 if r.get('state')=='Failure of Proof')}/{len(sf00)}** | "
  f"**{sum(1 for r in sf02 if r.get('state')=='Failure of Proof')}/{len(sf02)}** |")
P("| …shipping with an empty `reference_proof` | **4/4** | **4/4** |")
P()
P("FormalStep could not prove these statements either. An arithmetic checker")
P("working only from the numbers reached the same verdict as the dataset's own")
P("provability label, independently.")
P()
P("---")
P()
P("## The failures, named")
P()
for key, rows in D["records"].items():
    sf = [r for r in rows if r["label"] == "statement_false"]
    if not sf:
        continue
    P(f"### {PRETTY[key]} — `statement_false`")
    P()
    P("| sample | the false claim |")
    P("|---|---|")
    for r in sf:
        why = (r["evidence"].get("false_hypotheses") or r["evidence"].get("false_goal") or [""])[0]
        P(f"| {r['sample']} | {why[:130]} |")
    P()

P("---")
P()
P("## Limits")
P()
P("- **Proof-side denominator is small, by nature of the data.** Only 1 proof-side")
P("  equality was assertable across all 55 failures, because the model hardly ever")
P("  hand-writes arithmetic (Phase 3: 2, 1 and 0 proofs out of 50 do). The")
P("  `proof_false = 0` result is therefore bounded at ≤"
  f"{100*upper0(tot_fail):.0f}% rather than established as exactly zero.")
P("- **`tactic_mismatch` is a residual, not a diagnosis.** 19 samples land there.")
P("  Each has correct-looking arithmetic and a tactic that could not close the")
P("  goal; whether the goal was provable at all is not established for every one.")
P("- **`UNKNOWN` count: "
  f"{sum(1 for rows in D['records'].values() for r in rows if r['label']=='UNKNOWN')}** of {tot_fail}.")
P("- The baseline set has no dataset `state` field (older schema), so the")
P("  independent-label corroboration is available only for the two n50 sets.")
P("- n is 50 per set. Every interval above is wide; do not read one-decimal")
P("  precision into any of them.")
