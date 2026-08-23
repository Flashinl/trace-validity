"""Run the vacuity probes over the FAILING samples, not just the passes.

`vacuity_scan.py` measured what the 37 passes assert. That leaves an obvious
question unanswered: is the 46% content rate a property of the BENCHMARK, or of
the pass set specifically?

There is a selection effect to expect. Every probe replaces the model's proof
entirely, so it interrogates the DATASET's goal. A goal that is trivially true
is one the model is very likely to have closed -- so trivial goals should be
enriched among passes and depleted among failures, purely by construction. If
the failures come back mostly `6_contentful`, that confirms the selection effect
and means the 46% describes the pass set, NOT the benchmark.

Same probes, same classifier, same verifier as vacuity_scan.py -- imported
rather than re-implemented so the two runs cannot drift apart.

Run: python tests/audit/vacuity_failures.py
"""

import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import GOEDEL_LEAN4_HEADER  # noqa: E402
from verifier import LeanVerifier, VALID  # noqa: E402

# Reuse, do not re-implement. Safe to import only because vacuity_scan.py now
# guards its scan behind main(); before that fix this line silently spun up a
# LeanVerifier, re-probed all 74 passes, and rewrote results/vacuity_scan.json
# as a side effect of the import.
from vacuity_scan import PROBES, classify, split_statement, stmt_with  # noqa: E402

H = GOEDEL_LEAN4_HEADER
PROBE_TIMEOUT = 15
J = lambda p: [json.loads(l) for l in io.open(os.path.join(ROOT, p), encoding="utf-8")
               if l.strip()]
OUT = os.path.join(ROOT, "results", "vacuity_failures.json")


def ok(v, code):
    try:
        return v.verify(code, timeout=PROBE_TIMEOUT)["outcome"] == VALID
    except Exception:  # noqa: BLE001
        return False


def main():
    t0 = time.perf_counter()
    v = LeanVerifier(setup=False, verbose=False)
    print(f"[setup] verifier ready in {time.perf_counter() - t0:.0f}s\n")

    out = {}
    for T in ("0.0", "0.2"):
        traces = {r["sample_index"]: r for r in J(f"traces/temp{T}_n50_1each/traces.jsonl")}
        vers = {r["sample_index"]: r for r in J(f"results/verify3_temp{T}.jsonl")}
        failing = sorted(i for i, r in vers.items() if r["outcome"] != VALID)

        print("=" * 92)
        print(f"T = {T}   probing {len(failing)} FAILING traces")
        print("=" * 92)

        rows = []
        for i in failing:
            stmt = traces[i]["formal_statement"]
            binders, goal = split_statement(stmt)
            p = {name: ok(v, stmt_with(stmt, tac)) for name, tac in PROBES}

            contra = False
            if binders.strip():
                for tac in ("simp_all", "omega", "norm_num at *"):
                    if ok(v, f"{H}theorem contra_probe {binders} : False := by\n  {tac}\n"):
                        contra = True
                        break

            cls = classify(p, contra)
            rows.append({"sample": i, "class": cls, "goal": goal[:80],
                         "contra": contra, "outcome": vers[i]["outcome"], **p})
            print(f"  {i:<4}{cls:<30}{vers[i]['outcome']:<16} {goal[:44]}")

        out[T] = rows

    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
