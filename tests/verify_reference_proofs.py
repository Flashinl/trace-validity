"""Compile FormalStep's OWN reference proofs in Lean.

The cross-check previously treated "reference_proof is non-empty" as meaning
"the statement is provable". That is the dataset's claim, not a measurement. This
script actually compiles those proofs, which turns the ground-truth axis into
something verified.

It also independently exercises the verifier on code no model produced, so a
disagreement here points at the verifier or the pinning rather than the prover.

  python tests/verify_reference_proofs.py
"""

import argparse
import json
import os
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import GOEDEL_LEAN4_HEADER  # noqa: E402
from verifier import LeanVerifier  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", default=os.path.join(ROOT, "traces", "temp_0.jsonl"))
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "reference_proofs.json"))
    ap.add_argument("--timeout", type=float, default=45)
    args = ap.parse_args()

    seen = {}
    with open(args.traces, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            seen.setdefault(r["sample_index"], r)

    with_proof = {i: r for i, r in seen.items() if (r.get("reference_proof") or "").strip()}
    print(f"samples: {len(seen)}   with a reference proof: {len(with_proof)}")

    v = LeanVerifier(timeout=args.timeout, verbose=False)
    print(f"verifier ready (env {v.base_env_seconds:.1f}s, source={v.base_env_source})")

    rows, counts = [], Counter()
    for idx in sorted(with_proof):
        proof = with_proof[idx]["reference_proof"].strip()
        # Reference proofs are bare declarations; give them the same header the
        # pipeline uses so they elaborate under identical conditions.
        code = GOEDEL_LEAN4_HEADER + proof + "\n"
        res = v.verify(code, timeout=args.timeout)
        counts[res["outcome"]] += 1
        rows.append({
            "sample_index": idx,
            "outcome": res["outcome"],
            "seconds": res["seconds"],
            "first_error": (res["errors"][0][:300] if res["errors"] else None),
        })
        print(f"  sample {idx:<3} {res['outcome']:<14} {res['seconds']:>6.2f}s")

    print("\nREFERENCE-PROOF OUTCOMES")
    for k, n in counts.most_common():
        print(f"  {k:<16} {n:>3}  ({n/len(rows):.1%})")

    bad = [r for r in rows if r["outcome"] != "valid"]
    if bad:
        print(f"\n  {len(bad)} reference proof(s) did NOT compile. Either the dataset's")
        print("  proof is stale for this Mathlib version, or our setup is wrong.")
        print("  Treat these samples' provability label as UNKNOWN, not provable.")
        for r in bad[:10]:
            print(f"    sample {r['sample_index']:<3} {r['outcome']}: "
                  f"{(r['first_error'] or '')[:150]}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"counts": dict(counts), "rows": rows}, f, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
