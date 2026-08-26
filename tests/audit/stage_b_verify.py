"""Verify the Stage B traces in Lean. THROWAWAY.

Mirrors verify_traces.py's decision sequence exactly so the verdicts mean the
same thing as the committed runs: fence-extraction check, compile, statement
fidelity on a pass, statement re-test on a compile_error, then failure_kind.
"""
import argparse, io, json, os, sys, time, collections

REPO = r"C:\Users\vkris\trace-validity"
sys.path.insert(0, REPO)
os.chdir(REPO)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from verifier import (LeanVerifier, PARSE_FAILURE, COMPILE_ERROR,
                      STATEMENT_ERROR, STATEMENT_MISMATCH, has_declaration,
                      BROKEN, UNKNOWN)
from verify_traces import statement_mismatch
from failure_taxonomy import record_failure_fields, summarize

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()
    IN, OUT, TIMEOUT = args.traces, args.out, args.timeout

    rows = [json.loads(l) for l in io.open(IN, encoding="utf-8") if l.strip()]
    print(f"{len(rows)} traces to verify\n", flush=True)

    t0 = time.perf_counter()
    v = LeanVerifier(timeout=TIMEOUT, verbose=False)
    print(f"[setup] verifier ready in {time.perf_counter()-t0:.0f}s\n", flush=True)

    out = []
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        for i, r in enumerate(rows, 1):
            code = r.get("full_code") or ""
            if not code or not has_declaration(code):
                res = {"outcome": PARSE_FAILURE, "valid": False,
                       "errors": ["fence extraction produced no usable code"],
                       "warnings": [], "num_errors": 0, "num_sorries": 0,
                       "seconds": 0.0, "mode": "none"}
            else:
                res = v.verify(code, timeout=TIMEOUT)
                if res["valid"]:
                    bad, why = statement_mismatch(code, r.get("formal_statement"))
                    if bad:
                        res = dict(res, outcome=STATEMENT_MISMATCH, valid=False,
                                   statement_mismatch_detail=why)
                if res["outcome"] == COMPILE_ERROR:
                    verdict, detail = v.statement_is_broken(
                        r.get("formal_statement"), timeout=TIMEOUT)
                    # Explicit comparison: "not_broken" is a truthy string.
                    if verdict == BROKEN:
                        res = dict(res, outcome=STATEMENT_ERROR, valid=False,
                                   statement_error_detail=detail)
                    elif verdict == UNKNOWN:
                        res = dict(res, statement_probe="unknown",
                                   statement_probe_detail=detail)

            rec = {"uuid": r["uuid"], "band": r["band"], "wr": r["wr"],
                   "source": r["source"], "outcome": res["outcome"],
                   "trace_valid": res["valid"],
                   "truncated": r.get("truncated"),
                   "generated_tokens": r.get("generated_tokens"),
                   "axioms": res.get("axioms"),
                   "statement_error_detail": res.get("statement_error_detail"),
                   "statement_probe": res.get("statement_probe"),
                   "statement_probe_detail": res.get("statement_probe_detail"),
                   **record_failure_fields(res, provenance_label=None)}
            out.append(rec)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
            print(f"  [{i:>3}/{len(rows)}] {r['band']:<7}{res['outcome']:<18}"
                  f"{res['seconds']:>6.2f}s", flush=True)

    print("\n" + "=" * 66)
    for b in ("easy", "medium", "hard"):
        s = [x for x in out if x["band"] == b]
        ok = sum(1 for x in s if x["trace_valid"])
        wr = sum(x["wr"] for x in s) / len(s)
        print(f"  {b:<8} ours {ok:>2}/{len(s)} = {100*ok/len(s):>3.0f}%   "
              f"Kimina ceiling {wr:.3f}")
        print(f"           {dict(collections.Counter(x['outcome'] for x in s))}")
    ok = sum(1 for x in out if x["trace_valid"])
    print(f"\n  TOTAL    {ok}/{len(out)} = {100*ok/len(out):.0f}%")
    print()
    print(summarize(out)["table"])
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
