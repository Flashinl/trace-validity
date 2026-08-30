"""Verify the GPU tactic-recovery traces in Lean. CPU only; no GPU is involved.

Mirrors verify_traces.py's decision sequence exactly, so a verdict here means
the same thing as in the committed runs:

    fence extraction -> compile -> statement fidelity on a pass
                                -> statement re-test on a compile_error

`valid` therefore already carries the axiom scan (verifier.py raises
UNSOUND_AXIOMS itself) and the `statement_mismatch` gate. The third gate the
brief requires -- the vacuity probe -- is a property of the STATEMENT, not of
any one proof, so it runs once per distinct statement in exp_vacuity.py rather
than once per passing sample.

Two differences from tests/audit/stage_b_verify.py, both deliberate:

  * No `os.chdir` to a hard-coded absolute repo path. That file pins
    C:\\Users\\vkris\\trace-validity, which in a worktree would silently verify
    into a DIFFERENT checkout than the one that generated the traces.
  * A content-addressed cache. Best-of-n at T=0.7 produces the same Lean file
    many times over -- identical source in an identical pinned environment has
    an identical verdict, so it is compiled once and the verdict is reused.
    `verify_source` on every record says whether it was compiled or reused.
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

from verifier import (LeanVerifier, PARSE_FAILURE, COMPILE_ERROR,
                      STATEMENT_ERROR, STATEMENT_MISMATCH, has_declaration,
                      BROKEN, UNKNOWN)
from verify_traces import statement_mismatch

# Fields worth carrying from the trace into the verdict record. Anything that
# identifies the sample or the arm it belongs to; never the generated text,
# which stays in the trace file.
CARRY = ("sample_index", "trajectory_index", "uuid", "problem_unique_id",
         "band", "temperature", "seed", "include_informal", "experiment",
         "repair_key", "set", "pipeline", "id", "lean_tactic", "lean_kind",
         "had_error_text", "state", "level", "extract_status", "truncated",
         "hit_token_limit", "generated_tokens")


def src_label(path):
    """A label that is unique per trace file even when basenames repeat."""
    d, b = os.path.split(os.path.abspath(path))
    return "%s/%s" % (os.path.basename(d), b) if b == "traces.jsonl" else b


def digest(code, formal_statement=""):
    """Cache key for one verification.

    The formal_statement is part of the key, not just the code. Two of the three
    steps in the decision sequence consult it -- `statement_mismatch` compares
    the model's declaration against it, and `statement_is_broken` re-elaborates
    it -- so a cache keyed on the generated code alone could hand back a verdict
    that was computed against a different statement.
    """
    h = hashlib.sha256(code.encode("utf-8"))
    h.update(b"|--formal-statement--|")
    h.update((formal_statement or "").encode("utf-8"))
    return h.hexdigest()


def record_key(rec, idx):
    """Stable identity of one trace record, for --resume.

    The source file is part of the key. Without it the doc-comment arms collide:
    arm A and arm B both contain (sample_index=0, trajectory_index=0), so a
    resumed run would skip every arm-B record as already done and the paired
    comparison would silently be arm A against itself.
    """
    src = rec.get("_src", "?")
    if rec.get("repair_key"):
        return "%s|%s" % (src, rec["repair_key"])
    if rec.get("uuid") is not None:
        return "%s|%s|%s" % (src, rec["uuid"], rec.get("sample_index", 0))
    if rec.get("sample_index") is not None:
        return "%s|%s|%s" % (src, rec["sample_index"], rec.get("trajectory_index", 0))
    return "%s|row%d" % (src, idx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True, nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--cache", default=os.path.join(_ROOT, "results", "exp_verify_cache.json"),
                    help="Content-addressed verdict cache, shared across runs.")
    # `statement_is_broken` is a SECOND Lean elaboration, run on every failing
    # sample to split compile_error into compile_error vs statement_error. At
    # T=0.7 most samples fail, so it doubles the Lean work, and re-elaborating a
    # broken statement is the single largest source of 60s timeouts -- each of
    # which costs a full REPL restart and `import Mathlib` on this host.
    #
    # It sub-classifies FAILURES ONLY. No sample's valid/invalid verdict depends
    # on it, so every pass count and every pass@k figure is identical with and
    # without it. Skipping it on the best-of-n runs buys a large speed-up and
    # costs only failure-taxonomy resolution, which best-of-n does not measure.
    ap.add_argument("--no-statement-probe", dest="statement_probe",
                    action="store_false", default=True,
                    help="Skip the statement_is_broken re-probe on failures. "
                         "Pass/fail verdicts are unaffected; compile_error is "
                         "simply not split out into statement_error.")
    args = ap.parse_args()

    rows = []
    for path in args.traces:
        n0 = len(rows)
        for line in io.open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                # Every experiment-1 arm's file is named traces.jsonl, so the
                # basename alone does not distinguish them; keep the parent dir.
                r["_src"] = src_label(path)
                rows.append(r)
        print("%-52s %5d traces" % (os.path.basename(path), len(rows) - n0))

    done = set()
    if os.path.exists(args.out):
        for line in io.open(args.out, encoding="utf-8"):
            if line.strip():
                done.add(json.loads(line)["key"])
        print("resuming: %d verdicts already present" % len(done))

    cache = {}
    if os.path.exists(args.cache):
        cache = json.load(io.open(args.cache, encoding="utf-8"))
        print("cache: %d distinct Lean files already compiled" % len(cache))

    todo = [(i, r) for i, r in enumerate(rows) if record_key(r, i) not in done]
    uniq = len({digest(r.get("full_code") or "", r.get("formal_statement"))
                for _, r in todo})
    print("\n%d traces, %d to verify, %d distinct Lean files among them\n"
          % (len(rows), len(todo), uniq), flush=True)
    if not todo:
        return

    t0 = time.perf_counter()
    v = LeanVerifier(timeout=args.timeout, verbose=False)
    print("[setup] verifier ready in %.0fs\n" % (time.perf_counter() - t0), flush=True)

    counts = collections.Counter()
    compiled = reused = 0
    t0 = time.perf_counter()
    with io.open(args.out, "a", encoding="utf-8", newline="\n") as fh:
        for n, (i, r) in enumerate(todo, 1):
            code = r.get("full_code") or ""
            h = digest(code, r.get("formal_statement"))
            src = "cache"
            if not code or not has_declaration(code):
                res = {"outcome": PARSE_FAILURE, "valid": False,
                       "errors": ["fence extraction produced no usable code"],
                       "warnings": [], "num_errors": 0, "num_sorries": 0,
                       "seconds": 0.0, "mode": "none"}
                src = "no_code"
            elif h in cache:
                res = dict(cache[h])
                reused += 1
            else:
                res = v.verify(code, timeout=args.timeout)
                # Same decision sequence as verify_traces.py, in the same order.
                if res["valid"]:
                    bad, why = statement_mismatch(code, r.get("formal_statement"))
                    if bad:
                        res = dict(res, outcome=STATEMENT_MISMATCH, valid=False,
                                   statement_mismatch_detail=why)
                if res["outcome"] == COMPILE_ERROR and args.statement_probe:
                    verdict, detail = v.statement_is_broken(
                        r.get("formal_statement"), timeout=args.timeout)
                    # "not_broken" is a truthy string; compare explicitly.
                    if verdict == BROKEN:
                        res = dict(res, outcome=STATEMENT_ERROR, valid=False,
                                   statement_error_detail=detail)
                    elif verdict == UNKNOWN:
                        res = dict(res, statement_probe="unknown",
                                   statement_probe_detail=detail)
                cache[h] = res
                compiled += 1
                src = "compiled"

            rec = {"key": record_key(r, i), "src_file": r["_src"],
                   "code_sha256": h, "verify_source": src,
                   "outcome": res["outcome"], "valid": bool(res.get("valid")),
                   "num_errors": res.get("num_errors"),
                   "errors": res.get("errors"),
                   "axioms": res.get("axioms"),
                   "statement_mismatch_detail": res.get("statement_mismatch_detail"),
                   "statement_error_detail": res.get("statement_error_detail"),
                   "statement_probe": res.get("statement_probe"),
                   "statement_probe_run": bool(args.statement_probe),
                   "verify_seconds": res.get("seconds")}
            for k in CARRY:
                if k in r:
                    rec[k] = r[k]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            counts[res["outcome"]] += 1

            if n % 25 == 0 or n == len(todo):
                el = time.perf_counter() - t0
                print("  [%5d/%d] %5.0fs  compiled=%d reused=%d  %s"
                      % (n, len(todo), el, compiled, reused,
                         " ".join("%s=%d" % kv for kv in counts.most_common())),
                      flush=True)
                json.dump(cache, io.open(args.cache, "w", encoding="utf-8"))

    json.dump(cache, io.open(args.cache, "w", encoding="utf-8"))
    print("\n%d verified in %.1f min (compiled %d, reused %d)"
          % (len(todo), (time.perf_counter() - t0) / 60, compiled, reused))
    for k, n in counts.most_common():
        print("  %-22s %5d" % (k, n))


if __name__ == "__main__":
    main()
