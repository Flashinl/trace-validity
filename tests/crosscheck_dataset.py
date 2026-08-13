"""Cross-check verifier outcomes against FormalStep's own provability signal.

FormalStep ships a `proof` (reference proof) only for steps it could prove. An
empty `reference_proof` is therefore the dataset's own statement that the step
is not provable -- typically because the natural-language CoT step is
mathematically false.

CAREFUL — the two signals are NOT the same question:

    dataset reference_proof  ->  is the STATEMENT provable?
    our outcome              ->  did THIS MODEL'S proof attempt compile?

A model can fail on a perfectly provable statement. That is a legitimate
`compile_error` and is the substantive research finding, NOT a verifier bug. So
"we said invalid where the dataset had a proof" is only a POSSIBLE false
negative -- each one must be read by hand to tell a real model failure from a
pipeline/parser defect.

The one direction that IS strong evidence of a verifier bug:

    we say `valid` but the statement is not provable -> FALSE POSITIVE, serious,
    because it means we certified a proof of something that cannot be proved.

  python tests/crosscheck_dataset.py
"""

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", default=os.path.join(ROOT, "traces", "temp_0.jsonl"))
    ap.add_argument("--verification",
                    default=os.path.join(ROOT, "results", "verification_temp_0.jsonl"))
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "crosscheck.json"))
    args = ap.parse_args()

    traces = {}
    with open(args.traces, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            traces.setdefault(r["sample_index"], r)

    verdicts = {}
    with open(args.verification, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            verdicts.setdefault(r["sample_index"], r)

    rows = []
    for idx in sorted(verdicts):
        t = traces.get(idx, {})
        v = verdicts[idx]
        has_ref = bool((t.get("reference_proof") or "").strip())
        we_valid = v["outcome"] == "valid"
        if has_ref and we_valid:
            agree = "agree_provable"
        elif not has_ref and not we_valid:
            agree = "agree_unprovable"
        elif has_ref and not we_valid:
            agree = "model_failed_on_provable_stmt"   # model failure OR pipeline bug
        else:
            agree = "WE_CERTIFIED_an_unprovable_stmt"  # FALSE POSITIVE - serious
        rows.append({
            "sample_index": idx,
            "outcome": v["outcome"],
            "dataset_has_reference_proof": has_ref,
            "agreement": agree,
            "informal_step": (t.get("informal_step") or "")[:160],
            "first_error": (v["errors"][0][:300] if v.get("errors") else None),
        })

    from collections import Counter
    c = Counter(r["agreement"] for r in rows)
    total = len(rows)

    print("=" * 78)
    print("CROSS-CHECK: verifier outcome vs FormalStep reference_proof presence")
    print("=" * 78)
    print(f"  samples compared: {total}")
    for k in ("agree_provable", "agree_unprovable",
              "model_failed_on_provable_stmt", "WE_CERTIFIED_an_unprovable_stmt"):
        if c[k]:
            print(f"    {k:<36} {c[k]:>3}  ({c[k]/total:.1%})")
    agreement = (c["agree_provable"] + c["agree_unprovable"]) / total if total else 0
    print(f"\n  overall agreement: {agreement:.1%}")

    fn = [r for r in rows if r["agreement"] == "model_failed_on_provable_stmt"]
    fp = [r for r in rows if r["agreement"] == "WE_CERTIFIED_an_unprovable_stmt"]

    if fn:
        print(f"\n  MODEL FAILED ON A PROVABLE STATEMENT ({len(fn)}).")
        print("  The statement IS provable (dataset has a reference proof) but this")
        print("  model's attempt did not compile. That is the expected research")
        print("  finding, NOT automatically a verifier bug. Each still needs a hand")
        print("  read to rule out a parser/pipeline defect.")
        for r in fn:
            print(f"    sample {r['sample_index']:<3} {r['outcome']}")
            print(f"      step : {r['informal_step']}")
            if r["first_error"]:
                print(f"      lean : {r['first_error'][:200]}")
    if fp:
        print(f"\n  WE CERTIFIED AN UNPROVABLE STATEMENT ({len(fp)}) — SERIOUS.")
        print("  We returned `valid` for a statement the dataset could not prove.")
        print("  Either a genuine verifier false positive, or our prover found a")
        print("  proof theirs missed. Must be read by hand before being reported.")
        for r in fp:
            print(f"    sample {r['sample_index']:<3} step: {r['informal_step']}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": dict(c), "agreement": agreement, "rows": rows}, f, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
