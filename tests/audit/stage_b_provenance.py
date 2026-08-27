"""Run the arithmetic provenance labeller over Stage B's judged failures.

Stage B's sweep report leaves the `arithmetic` axis at 100% `unknown` because
these failures had never been through the labeller. This closes that: is a
failure the dataset's arithmetic being wrong, or the model's proof being wrong?

Joins three artifacts on `uuid` -- the labeller needs `full_code` and
`formal_statement`, which live in the TRACE file, while the error strings live
in the VERIFICATION file:

  results/stage_b_traces_temp{T}.jsonl     full_code, formal_statement
  results/stage_b_verified_temp{T}.jsonl   outcome, errors, failure_kind
  results/stage_b_evalset.json             kimina_proof (Stage B's reference proof)

`parse_failure` and `timeout` are excluded as non-verdicts, matching the sweep
report. Every remaining failure receives exactly one label and the labels must
sum to the judged-failure count.

Run: python tests/audit/stage_b_provenance.py
"""
import argparse, collections, io, json, os, re, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provenance import classify
from stats import wilson

J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]
NON_VERDICT = ("parse_failure", "timeout")
# Every label the labeller can emit. Pinned so a missing one is visible as 0
# rather than absent -- `budget` went unaccounted for in the earlier run.
LABELS = ("statement_false", "proof_false", "tactic_mismatch", "parse_skew",
          "budget", "noop_tactic", "UNKNOWN")


def ci(k, n):
    if not n:
        return "n=0"
    lo, hi = wilson(k, n)
    return f"{k:>3}/{n:<3} = {100*k/n:>5.1f}%  [{100*lo:>4.1f}-{100*hi:>5.1f}%]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temps", nargs="+", default=["0.0", "0.7"])
    ap.add_argument("--out", default="results/stage_b_provenance.json")
    args = ap.parse_args()

    ev = {r["uuid"]: r for r in json.load(io.open("results/stage_b_evalset.json",
                                                 encoding="utf-8"))}
    out, all_rows = {}, []

    for T in args.temps:
        traces = {r["uuid"]: r for r in J(f"results/stage_b_traces_temp{T}.jsonl")}
        vers = {r["uuid"]: r for r in J(f"results/stage_b_verified_temp{T}.jsonl")}

        fails = [u for u, r in vers.items() if not r["trace_valid"]]
        judged = [u for u in fails if vers[u]["outcome"] not in NON_VERDICT]
        excluded = [u for u in fails if vers[u]["outcome"] in NON_VERDICT]

        print("=" * 92)
        print(f"T = {T}   {len(fails)} failures, {len(judged)} judged, "
              f"{len(excluded)} excluded as non-verdicts "
              f"{dict(collections.Counter(vers[u]['outcome'] for u in excluded))}")
        print("=" * 92)

        rows = []
        for u in sorted(judged):
            tr, ver = traces.get(u), vers[u]
            if tr is None:
                rows.append({"uuid": u, "label": "UNKNOWN", "band": ver["band"],
                             "old_kind": ver.get("failure_kind"),
                             "evidence": {"error_head": "no matching trace record"}})
                continue
            label, evid = classify(ver, tr)
            rows.append({"uuid": u, "temp": T, "band": ver["band"],
                         "outcome": ver["outcome"], "label": label,
                         "old_kind": ver.get("failure_kind"),
                         "has_kimina_proof": bool(ev.get(u, {}).get("kimina_proof")),
                         "statement": re.sub(r"\s+", " ",
                                             tr.get("formal_statement") or "").strip()[:200],
                         "evidence": evid})
        all_rows += rows

        counts = collections.Counter(r["label"] for r in rows)
        n = len(rows)
        print(f"\n  PROVENANCE LABELS (n={n})")
        for L in LABELS:
            print(f"    {L:<18}{ci(counts.get(L, 0), n)}")
        assert sum(counts.values()) == n, "labels must sum to the judged count"
        print(f"    {'sum':<18}{sum(counts.values())} == {n}  OK")

        # Did the labeller actually look at the proof side?
        pcc = sum(r["evidence"].get("proof_claims_checked", 0) for r in rows
                  if "evidence" in r)
        scc = sum(r["evidence"].get("statement_claims_checked", 0) for r in rows
                  if "evidence" in r)
        print(f"\n  labeller reach: statement claims evaluated={scc}, "
              f"proof claims evaluated={pcc}")

        # Cross-tab: old taxonomy vs new provenance label.
        print(f"\n  CROSS-TAB  old failure_kind (rows) x provenance label (cols)")
        kinds = sorted({str(r["old_kind"]) for r in rows})
        present = [L for L in LABELS if counts.get(L, 0)]
        w = max(len(k) for k in kinds) + 2
        print("    " + "".join([" " * w] + [f"{L[:14]:>16}" for L in present]))
        for k in kinds:
            cells = [sum(1 for r in rows if str(r["old_kind"]) == k and r["label"] == L)
                     for L in present]
            print("    " + f"{k:<{w}}" + "".join(f"{c:>16}" for c in cells))

        out[T] = {"n_failures": len(fails), "n_judged": n,
                  "excluded": dict(collections.Counter(vers[u]["outcome"] for u in excluded)),
                  "counts": dict(counts),
                  "statement_claims_checked": scc, "proof_claims_checked": pcc,
                  "crosstab": {k: {L: sum(1 for r in rows
                                          if str(r["old_kind"]) == k and r["label"] == L)
                                   for L in present} for k in kinds}}
        print()

    # ---- combined ------------------------------------------------------------
    n = len(all_rows)
    cc = collections.Counter(r["label"] for r in all_rows)
    print("=" * 92)
    print(f"BOTH TEMPERATURES COMBINED  (n={n} judged failures)")
    print("=" * 92)
    for L in LABELS:
        print(f"  {L:<18}{ci(cc.get(L, 0), n)}")
    print(f"  {'sum':<18}{sum(cc.values())} == {n}")
    sf = cc.get("statement_false", 0)
    print(f"\n  VERDICT: {ci(sf, n)} of Stage B judged failures are the "
          f"DATASET's arithmetic being wrong.")
    out["combined"] = {"n": n, "counts": dict(cc),
                       "statement_false": sf, "wilson": list(wilson(sf, n))}

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    io.open(args.out, "w", encoding="utf-8", newline="\n").write(
        json.dumps({"summary": out, "rows": all_rows}, ensure_ascii=False, indent=1))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
