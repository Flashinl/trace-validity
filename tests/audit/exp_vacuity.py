"""The vacuity gate for the GPU tactic-recovery runs. CPU only.

Reuses vacuity_scan.py's probe ladder and classifier unmodified, so a label here
means what it means in results/vacuity_scan.json.

Why this runs once per STATEMENT and not once per passing sample: every probe
replaces the model's proof entirely. It interrogates the dataset's goal, not the
model's work. Vacuity is therefore a property of the problem, and every passing
sample of a problem inherits one verdict.

Keyed on the sha256 of the statement text, not on a row id. Two reasons:

  * The baseline experiment-1 set is 50 CoT steps of ONE problem, so all 50 rows
    share a `problem_unique_id`. Keying on that id would collapse 50 distinct
    statements into one and probe a single arbitrary representative.
  * The same statement recurs across arms and across experiments. Keying on its
    text probes it once and reuses the verdict everywhere, which matters when a
    verifier start-up costs ~15 minutes on this host.

What this gate catches that the others do not: a goal closed from CONTRADICTORY
HYPOTHESES. That pass compiles, declares the right theorem, and depends on
nothing but Lean's three standard axioms, so neither the axiom scan nor
`statement_mismatch` sees anything wrong with it. Only `P_contra` does.
"""
import argparse
import collections
import hashlib
import io
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from verifier import LeanVerifier
from vacuity_scan import PROBES, classify, split_statement, stmt_with, ok, H

CONTRA_TACTICS = ("simp_all", "omega", "norm_num at *")
# Anything but 5_ground_computation / 6_contentful means the goal demands less
# than a proof. Ground computation is real arithmetic and is NOT counted vacuous
# here, matching CONTENTLESS_STEPS.md's treatment.
VACUOUS_CLASSES = ("1_goal_is_True", "2_hypotheses_contradictory",
                   "3_goal_restates_a_hypothesis", "4_syntactic_tautology")


def skey(stmt):
    return hashlib.sha256((stmt or "").strip().encode("utf-8")).hexdigest()


def row_key(r):
    """How a verdict row points back at its statement's trace row."""
    if r.get("repair_key"):
        return ("repair", r["repair_key"])
    if r.get("uuid") is not None:
        return ("uuid", r["uuid"])
    return ("srcidx", r.get("src_file"), r.get("sample_index"))


def trace_key(r, src):
    if r.get("repair_key"):
        return ("repair", r["repair_key"])
    if r.get("uuid") is not None:
        return ("uuid", r["uuid"])
    return ("srcidx", src, r.get("sample_index"))


def src_label(path):
    d, b = os.path.split(os.path.abspath(path))
    return "%s/%s" % (os.path.basename(d), b) if b == "traces.jsonl" else b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True, nargs="+")
    ap.add_argument("--verdicts", required=True, nargs="+",
                    help="exp_verify.py output; only PASSING rows are probed.")
    ap.add_argument("--out", default=os.path.join(_ROOT, "results", "exp_vacuity.json"))
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    # trace identity -> statement
    stmt_by = {}
    for path in args.traces:
        src = src_label(path)
        for line in io.open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                stmt_by[trace_key(r, src)] = r.get("formal_statement") or ""

    # every distinct statement that reached a pass
    want = {}
    missing = 0
    for path in args.verdicts:
        for line in io.open(path, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("valid"):
                continue
            s = stmt_by.get(row_key(r))
            if not s:
                missing += 1
                continue
            want.setdefault(skey(s), s)

    done = {}
    if os.path.exists(args.out):
        done = json.load(io.open(args.out, encoding="utf-8"))
        print("resuming: %d statements already probed" % len(done))
    todo = [h for h in want if h not in done]
    print("%d distinct statements reached a pass; %d to probe; %d passing rows "
          "could not be matched to a statement\n" % (len(want), len(todo), missing),
          flush=True)
    if todo:
        t0 = time.perf_counter()
        v = LeanVerifier(setup=False, verbose=False)
        print("[setup] verifier ready in %.0fs\n" % (time.perf_counter() - t0), flush=True)

        for n, h in enumerate(todo, 1):
            stmt = want[h]
            binders, goal = split_statement(stmt)
            p = {name: ok(v, stmt_with(stmt, tac)) for name, tac in PROBES}
            contra = False
            if binders.strip():
                for tac in CONTRA_TACTICS:
                    if ok(v, "%stheorem contra_probe %s : False := by\n  %s\n"
                            % (H, binders, tac)):
                        contra = True
                        break
            cls = classify(p, contra)
            done[h] = {"class": cls, "contra": contra, "goal": goal[:160],
                       "statement": stmt[:600], "vacuous": cls in VACUOUS_CLASSES, **p}
            print("  [%3d/%d] %-32s %s" % (n, len(todo), cls, goal[:60]), flush=True)
            json.dump(done, io.open(args.out, "w", encoding="utf-8"),
                      indent=2, ensure_ascii=False)

    json.dump(done, io.open(args.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    _tally({h: done[h] for h in want if h in done})
    print("\nwrote %s" % args.out)


def _tally(done):
    t = collections.Counter(v["class"] for v in done.values())
    print("\nTALLY (%d statements in this run's pass set)" % len(done))
    for k in sorted(t):
        mark = "   <- counted vacuous" if k in VACUOUS_CLASSES else ""
        print("  %-34s %3d%s" % (k, t[k], mark))
    print("  %-34s %3d" % ("TOTAL VACUOUS",
                           sum(1 for v in done.values() if v["vacuous"])))


if __name__ == "__main__":
    main()
