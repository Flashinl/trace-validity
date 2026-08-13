"""Run the hand-labelled control set through the verifier and print a
confusion matrix.

This is ground truth independent of any model: it answers "can the verifier be
trusted at all", separately from "is the model any good".

  python tests/test_verifier.py
  python tests/test_verifier.py --timeout 30 --out results/control_set_run.json
"""

import argparse
import json
import os
import sys

# Lean output contains math symbols (turnstile, blackboard bold). The Windows
# console defaults to cp1252 and raises UnicodeEncodeError on them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import VERIFY_TIMEOUT_SECONDS  # noqa: E402
from verifier import LeanVerifier, OUTCOMES  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "control_set.jsonl")


def load_fixtures(path=FIXTURES):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def print_confusion(rows):
    """rows: list of (expected, actual). Prints an expected x actual matrix."""
    labels = [o for o in OUTCOMES if any(e == o or a == o for e, a in rows)]
    counts = Counter(rows)

    w = max(len(l) for l in labels) + 2
    print("\nCONFUSION MATRIX  (rows = expected / hand label, cols = actual / verifier)")
    print("-" * (w + 1 + len(labels) * 9))
    print(" " * w + "|" + "".join(f"{l[:8]:>9}" for l in labels))
    print("-" * (w + 1 + len(labels) * 9))
    for exp in labels:
        row = f"{exp:<{w}}|"
        for act in labels:
            n = counts.get((exp, act), 0)
            row += f"{(str(n) if n else '.'):>9}"
        print(row)
    print("-" * (w + 1 + len(labels) * 9))

    correct = sum(n for (e, a), n in counts.items() if e == a)
    total = len(rows)
    print(f"\nagreement: {correct}/{total} = {correct/total:.1%}")
    return correct, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=VERIFY_TIMEOUT_SECONDS)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--filter", type=str, default=None, help="only ids containing this")
    args = ap.parse_args()

    fixtures = load_fixtures()
    if args.filter:
        fixtures = [f for f in fixtures if args.filter in f["id"]]
    print(f"loaded {len(fixtures)} fixtures from {FIXTURES}")

    t_setup = time.perf_counter()
    v = LeanVerifier(timeout=args.timeout, verbose=False)
    setup_s = time.perf_counter() - t_setup
    print(f"verifier ready in {setup_s:.1f}s "
          f"(base Mathlib env built in {v.base_env_seconds:.1f}s)")

    rows = []
    records = []
    mismatches = []
    t0 = time.perf_counter()

    for i, fx in enumerate(fixtures, 1):
        res = v.verify(fx["lean_code"], timeout=args.timeout)
        actual = res["outcome"]
        expected = fx["expected"]
        ok = actual == expected
        rows.append((expected, actual))
        rec = {
            "id": fx["id"],
            "category": fx["category"],
            "expected": expected,
            "actual": actual,
            "match": ok,
            "confidence": fx["confidence"],
            "seconds": res["seconds"],
            "mode": res["mode"],
            "num_errors": res["num_errors"],
            "num_sorries": res["num_sorries"],
            "errors": res["errors"][:3],
            "note": fx["note"],
        }
        records.append(rec)
        if not ok:
            mismatches.append(rec)
        flag = "ok " if ok else "MISS"
        print(f"  [{i:>2}/{len(fixtures)}] {flag} {fx['id']:<16} "
              f"exp={expected:<14} act={actual:<14} {res['seconds']:>6.2f}s {res['mode']}")

    total_s = time.perf_counter() - t0
    print(f"\n{len(fixtures)} verifications in {total_s:.1f}s "
          f"({total_s/len(fixtures):.2f}s each)")

    correct, total = print_confusion(rows)

    if mismatches:
        print(f"\nMISMATCHES ({len(mismatches)}) — each is a verifier bug or a bad label:")
        for m in mismatches:
            print(f"\n  {m['id']} [{m['category']}] confidence={m['confidence']}")
            print(f"    expected {m['expected']}, got {m['actual']}")
            print(f"    why labelled: {m['note']}")
            if m["errors"]:
                print(f"    lean said: {m['errors'][0][:200]}")
    else:
        print("\nNo mismatches.")

    by_cat = defaultdict(lambda: [0, 0])
    for r in records:
        by_cat[r["category"]][1] += 1
        if r["match"]:
            by_cat[r["category"]][0] += 1
    print("\nby category:")
    for cat, (ok, tot) in sorted(by_cat.items()):
        print(f"  {cat:<22} {ok}/{tot}")

    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({
                "setup_seconds": round(setup_s, 2),
                "base_env_seconds": round(v.base_env_seconds, 2),
                "total_seconds": round(total_s, 2),
                "agreement": f"{correct}/{total}",
                "records": records,
            }, f, indent=2)
        print(f"\nwrote {args.out}")

    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
