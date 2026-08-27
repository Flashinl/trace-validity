"""External corroboration for all 26 `statement_false` labels.

The provenance finding rests on a classifier that reported 0 `statement_false`
before a hypothesis-substitution bug was fixed and 26 after. A result that swings
that far on one implementation detail needs a check from outside the classifier.

The only check so far covers 8 of the 26 -- the n50 cases, 4/4 at each
temperature carrying dataset `state = "Failure of Proof"` with an empty
`reference_proof`. The 18 baseline cases are 69% of the finding and have never
been checked.

Two independent signals, both from the DATASET rather than from us:

  state             FormalStep's own label for the step. "Failure of Proof"
                    means the dataset agrees the step is bad.
  reference_proof   empty/absent is weak corroboration -- the dataset had no
                    proof to offer for a step it marked failed.

Reported as a confusion matrix over all 26, split by run, not as one percentage:
the question is specifically whether baseline agreement is worse than n50's, and
a pooled figure would hide that.

Run: python tests/audit/corroborate_statement_false.py
"""
import argparse, collections, io, json, os, re, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from stats import wilson

J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]
norm = lambda s: re.sub(r"\s+", " ", (s or "")).strip()

SETS = [
    ("baseline_50step_1problem", "traces/temp_0.jsonl"),
    ("n50_distinct_T0.0", "traces/temp0.0_n50_1each/traces.jsonl"),
    ("n50_distinct_T0.2", "traces/temp0.2_n50_1each/traces.jsonl"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/corroboration.json")
    args = ap.parse_args()

    from datasets import load_dataset
    from config import DATASET_NAME, DATASET_SPLIT
    full = load_dataset(DATASET_NAME, split=DATASET_SPLIT)

    # Index the dataset by statement, normalised THE SAME WAY the pipeline
    # normalised it. Matching raw dataset text against a trace's
    # `formal_statement` finds nothing: the dataset ships `:= by sorry` and
    # normalize_formal_statement() rewrites that to `:= by` before the statement
    # is ever written to a trace. A raw match returned NOT_FOUND on all 26.
    from data_loader import normalize_formal_statement, DatasetFieldError

    def canon(s):
        """Normalise, then drop the trailing `:= by` so both sides agree."""
        try:
            s = normalize_formal_statement(s)
        except DatasetFieldError:
            pass
        return norm(re.sub(r":=\s*by\s*\Z", "", norm(s)))

    by_stmt = collections.defaultdict(list)
    for i, s in enumerate(full["formal_statement"]):
        by_stmt[canon(s)].append(i)
    states = full["state"]
    # The dataset column is `proof`; the trace field that mirrors it is
    # `reference_proof`. Same content, different name on each side.
    refs = full["proof"]
    print(f"dataset indexed: {len(by_stmt)} distinct statements over {len(full)} rows")

    prov = json.load(io.open("results/arithmetic_provenance.json", encoding="utf-8"))
    traces = {name: {r["sample_index"]: r for r in J(p)} for name, p in SETS}

    rows = []
    for name, _ in SETS:
        recs = [r for r in prov["records"][name] if r["label"] == "statement_false"]
        for r in recs:
            tr = traces[name].get(r["sample"], {})
            stmt = canon(tr.get("formal_statement") or r.get("statement"))
            hits = by_stmt.get(stmt, [])
            st = sorted({states[i] for i in hits}) if hits else []
            rp = [refs[i] for i in hits]
            # unambiguous only if every matching row agrees
            state = st[0] if len(st) == 1 else ("AMBIGUOUS" if st else "NOT_FOUND")
            ref_empty = (all(not (x or "").strip() for x in rp) if rp
                         else not (tr.get("reference_proof") or "").strip())
            rows.append({
                "run": name, "sample": r["sample"], "state": state,
                "n_dataset_rows": len(hits),
                "reference_proof_empty": bool(ref_empty),
                "why": (r["evidence"].get("false_goal") or
                        r["evidence"].get("false_hypotheses") or [""])[0][:90],
            })

    print(f"\n{len(rows)} statement_false records to corroborate\n")

    # ---- confusion matrix ---------------------------------------------------
    print("=" * 92)
    print("CONFUSION MATRIX  classifier says statement_false  x  dataset `state`")
    print("=" * 92)
    runs = [n for n, _ in SETS]
    allstates = sorted({r["state"] for r in rows})
    w = max(len(x) for x in runs) + 2
    print("  " + f"{'run':<{w}}" + "".join(f"{s[:22]:>24}" for s in allstates) + f"{'n':>6}")
    for name in runs:
        rr = [r for r in rows if r["run"] == name]
        cells = [sum(1 for r in rr if r["state"] == s) for s in allstates]
        print("  " + f"{name:<{w}}" + "".join(f"{c:>24}" for c in cells) + f"{len(rr):>6}")
    tot = [sum(1 for r in rows if r["state"] == s) for s in allstates]
    print("  " + f"{'TOTAL':<{w}}" + "".join(f"{c:>24}" for c in tot) + f"{len(rows):>6}")

    # ---- agreement rate per run --------------------------------------------
    print("\n" + "=" * 92)
    print("AGREEMENT: dataset independently marks the step a failure")
    print("=" * 92)
    out_runs = {}
    for name in runs:
        rr = [r for r in rows if r["run"] == name]
        k = sum(1 for r in rr if r["state"] == "Failure of Proof")
        n = len(rr)
        lo, hi = wilson(k, n) if n else (0, 0)
        e = sum(1 for r in rr if r["reference_proof_empty"])
        print(f"  {name:<28} state=Failure: {k:>2}/{n:<3} = "
              f"{100*k/n if n else 0:>5.1f}%  [{100*lo:>4.1f}-{100*hi:>5.1f}%]"
              f"    reference_proof empty: {e}/{n}")
        out_runs[name] = {"k": k, "n": n, "wilson": list(wilson(k, n)) if n else None,
                          "ref_empty": e}
    k = sum(1 for r in rows if r["state"] == "Failure of Proof")
    n = len(rows)
    lo, hi = wilson(k, n)
    print(f"  {'ALL 26':<28} state=Failure: {k:>2}/{n:<3} = {100*k/n:>5.1f}%  "
          f"[{100*lo:>4.1f}-{100*hi:>5.1f}%]")

    base = out_runs["baseline_50step_1problem"]
    n50k = sum(out_runs[r]["k"] for r in runs if r.startswith("n50"))
    n50n = sum(out_runs[r]["n"] for r in runs if r.startswith("n50"))
    print("\n" + "=" * 92)
    print("VERDICT")
    print("=" * 92)
    br = base["k"] / base["n"] if base["n"] else 0
    nr = n50k / n50n if n50n else 0
    print(f"  baseline (the 18, never checked): {base['k']}/{base['n']} = {100*br:.1f}%")
    print(f"  n50 (the 8, previously checked) : {n50k}/{n50n} = {100*nr:.1f}%")
    # Test it rather than thresholding it. An arbitrary "worse by 15 points"
    # rule flips on 3 records out of 18 while the two intervals overlap almost
    # entirely, which is not a finding about the classifier.
    from math import comb

    def fisher(a, b, c, d):
        n = a + b + c + d
        r1, c1 = a + b, a + c
        f = lambda x: comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)
        obs = f(a)
        return sum(f(x) for x in range(max(0, c1 - (n - r1)), min(r1, c1) + 1)
                   if f(x) <= obs + 1e-12)

    p = fisher(base["k"], base["n"] - base["k"], n50k, n50n - n50k)
    print(f"  Fisher two-sided p = {p:.4f}")
    if p >= 0.05:
        print("  -> NO evidence baseline agreement is worse. The intervals overlap")
        print("     almost entirely; the classifier is not tuned to n50 and the 47%")
        print("     figure does not need widening on this basis.")
    else:
        print("  -> baseline agreement IS significantly worse. The classifier looks")
        print("     tuned to n50 and the 47% figure needs widening.")

    print("\n  per-record detail:")
    for r in rows:
        print(f"    {r['run'][:26]:<28}s{r['sample']:<4}{r['state']:<20}"
              f"ref_empty={str(r['reference_proof_empty']):<6}{r['why'][:44]}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    io.open(args.out, "w", encoding="utf-8", newline="\n").write(
        json.dumps({"rows": rows, "per_run": out_runs}, ensure_ascii=False, indent=1))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
