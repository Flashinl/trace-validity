"""Split the combined verdict file into one file per experiment run.

exp_verify.py appends every verdict to a single --out file so that one Lean
start-up (~11 min on this host) serves several trace files. exp_analyze.py
reads one file per run. This is the seam between them.

Run it before exp_analyze.py whenever verification has advanced; it is a pure
re-projection of exp2_all.verified.jsonl and holds no state of its own, so it is
safe to re-run at any time, including while verification is still appending.
"""
import collections
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

R = lambda *p: os.path.join(_ROOT, *p)

# src_file label -> the per-run verdict file exp_analyze expects.
ROUTES = {
    "exp2_n50_k16/traces.jsonl": "exp2_n50_k16.verified.jsonl",
    "exp2_stageb_k16.jsonl": "exp2_stageb_k16.verified.jsonl",
    "exp3_repair.fixed.jsonl": "exp3_repair.verified.jsonl",
    "exp1_n50_armA/traces.jsonl": "exp1_n50_armA.verified.jsonl",
    "exp1_n50_armB/traces.jsonl": "exp1_n50_armB.verified.jsonl",
    "exp1_baseline_armA/traces.jsonl": "exp1_baseline_armA.verified.jsonl",
    "exp1_baseline_armB/traces.jsonl": "exp1_baseline_armB.verified.jsonl",
}

SOURCES = ("exp2_all.verified.jsonl", "exp1_all.verified.jsonl")


def main():
    by = collections.defaultdict(list)
    for src in SOURCES:
        p = R("results", src)
        if not os.path.exists(p):
            continue
        for line in io.open(p, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                by[r.get("src_file")].append(r)

    if not by:
        raise SystemExit("no combined verdict file found in results/")

    for label, rows in sorted(by.items()):
        out = ROUTES.get(label)
        if out is None:
            print("  %-34s %5d rows  (no route; skipped)" % (label, len(rows)))
            continue
        with io.open(R("results", out), "w", encoding="utf-8",
                     newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        n_valid = sum(1 for r in rows if r.get("valid"))
        n_unrun = sum(1 for r in rows if r.get("outcome") == "all_timeout")
        print("  %-34s %5d rows  valid=%-4d never-compiled=%-4d -> %s"
              % (label, len(rows), n_valid, n_unrun, out))


if __name__ == "__main__":
    main()
