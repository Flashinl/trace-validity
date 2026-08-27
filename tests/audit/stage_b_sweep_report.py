"""Stage B temperature sweep: pass rates, paired comparison, taxonomy, axioms.

Reads two verified JSONL files (one per temperature) over the SAME 90-problem
eval set and reports what the sweep actually licenses.

Denominators are stated everywhere and never silently narrowed. Three outcomes
are not verdicts on the model's proof and are reported as such rather than
folded into the failure count:

  parse_failure   generation hit the token limit; there was no proof to judge
  timeout         Lean returned no verdict within the budget
  statement_error the statement itself was rejected -- and after the
                  statement_is_broken() repair this can no longer be a timeout

The paired comparison is McNemar on the 90 matched problems, which is the right
test because the two temperatures see the identical eval set. A pass-rate
difference computed from two independent proportions would throw away the
pairing and understate the power.
"""
import argparse, collections, io, json, os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from stats import wilson, mcnemar_exact, zero_event_upper, min_discordant_for_significance
from failure_taxonomy import summarize

J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]
BANDS = ("easy", "medium", "hard")
# Outcomes that are not a verdict on the model's proof.
NON_VERDICT = ("parse_failure", "timeout", "statement_error")


def ci(k, n):
    if n == 0:
        return f"{'':>16}   n=0"
    lo, hi = wilson(k, n)
    return f"{k:>3}/{n:<3} = {100*k/n:>5.1f}%  [{100*lo:>4.1f}-{100*hi:>5.1f}%]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True,
                    help="temp=path pairs, e.g. 0.0=results/sb_verified_temp0.0.jsonl")
    ap.add_argument("--traces", nargs="*", default=[],
                    help="temp=path pairs for the trace files (truncation stats)")
    ap.add_argument("--out", default="results/STAGE_B_SWEEP.json")
    args = ap.parse_args()

    runs = {}
    for spec in args.runs:
        t, p = spec.split("=", 1)
        runs[t] = {r["uuid"]: r for r in J(p)}
    traces = {}
    for spec in args.traces:
        t, p = spec.split("=", 1)
        traces[t] = {r["uuid"]: r for r in J(p)}
    temps = list(runs)

    uuids = set.intersection(*[set(v) for v in runs.values()])
    print(f"matched problems across {temps}: {len(uuids)}")
    for t in temps:
        extra = set(runs[t]) - uuids
        if extra:
            print(f"  WARNING: temp {t} has {len(extra)} problems the other run lacks")

    out = {"temps": temps, "n_matched": len(uuids), "per_temp": {}, "paired": {}}

    # ---- per-temperature, overall and per band -----------------------------
    for t in temps:
        rows = [runs[t][u] for u in sorted(uuids)]
        n = len(rows)
        val = sum(1 for r in rows if r["trace_valid"])
        nonv = [r for r in rows if r["outcome"] in NON_VERDICT]
        judged = n - len(nonv)
        vj = sum(1 for r in rows if r["trace_valid"])
        print("\n" + "=" * 78)
        print(f"T = {t}")
        print("=" * 78)
        print(f"  compiling proof of the target   {ci(val, n)}   (all {n} attempted)")
        print(f"  ...over JUDGED attempts only    {ci(vj, judged)}   "
              f"({len(nonv)} not a verdict: "
              f"{dict(collections.Counter(r['outcome'] for r in nonv))})")
        print()
        print(f"  {'band':<8}{'pass rate (all attempted)':<34}{'judged-only':<30}")
        per_band = {}
        for b in BANDS:
            br = [r for r in rows if r["band"] == b]
            bv = sum(1 for r in br if r["trace_valid"])
            bn = len(br)
            bnv = [r for r in br if r["outcome"] in NON_VERDICT]
            bj = bn - len(bnv)
            print(f"  {b:<8}{ci(bv, bn):<34}{ci(bv, bj):<30}")
            per_band[b] = {"valid": bv, "n": bn, "judged": bj,
                           "wilson": wilson(bv, bn)}
        outcomes = dict(collections.Counter(r["outcome"] for r in rows))
        print(f"\n  outcomes: {outcomes}")

        # truncation, which is the thing a higher temperature is expected to move
        if t in traces:
            tr = [traces[t][u] for u in sorted(uuids) if u in traces[t]]
            trunc = sum(1 for r in tr if r.get("truncated"))
            gt = [r.get("generated_tokens", 0) for r in tr]
            print(f"  truncated (hit the 2048-token budget): {ci(trunc, len(tr))}")
            print(f"  generated tokens: median={sorted(gt)[len(gt)//2]}  max={max(gt)}")
            per_band["_truncated"] = {"k": trunc, "n": len(tr)}

        # axiom audit
        ax = collections.Counter()
        for r in rows:
            if r["trace_valid"]:
                ax[str(r.get("axioms"))] += 1
        print(f"\n  AXIOM AUDIT over the {val} passes:")
        for k, c in ax.most_common():
            print(f"    {c:>3}  {k}")
        trusted = {"Classical.choice", "Quot.sound", "propext"}
        untrusted = []
        for r in rows:
            if not r["trace_valid"]:
                continue
            a = (r.get("axioms") or "").replace("axioms:", "").strip()
            names = {x.strip() for x in a.split(",") if x.strip()}
            if names - trusted:
                untrusted.append((r["uuid"][:8], sorted(names - trusted)))
        print(f"    outside the trusted set (Classical.choice/Quot.sound/propext): "
              f"{len(untrusted)}")
        for u, names in untrusted:
            print(f"      {u}: {names}")
        if not untrusted:
            print(f"      zero-event upper bound over {val} passes: "
                  f"{100*zero_event_upper(val):.1f}%")

        print(f"\n  FAILURE TAXONOMY:")
        print(summarize(rows)["table"])

        out["per_temp"][t] = {"n": n, "valid": val, "judged": judged,
                              "wilson": wilson(val, n), "outcomes": outcomes,
                              "per_band": per_band,
                              "axioms": dict(ax), "untrusted_axioms": untrusted}

    # ---- paired comparison --------------------------------------------------
    if len(temps) == 2:
        a, b = temps
        print("\n" + "=" * 78)
        print(f"PAIRED COMPARISON  T={a} vs T={b}   (McNemar, n={len(uuids)} matched)")
        print("=" * 78)
        both = won = lost = neither = 0
        changed = []
        for u in sorted(uuids):
            ra, rb = runs[a][u], runs[b][u]
            va, vb = ra["trace_valid"], rb["trace_valid"]
            if va and vb:
                both += 1
            elif va and not vb:
                lost += 1
                changed.append((u, ra["band"], f"{a}:valid", f"{b}:{rb['outcome']}"))
            elif vb and not va:
                won += 1
                changed.append((u, rb["band"], f"{a}:{ra['outcome']}", f"{b}:valid"))
            else:
                neither += 1
        print(f"  both pass          {both}")
        print(f"  only T={a} passes   {lost}")
        print(f"  only T={b} passes   {won}")
        print(f"  neither passes     {neither}")
        disc = won + lost
        p, n_disc = mcnemar_exact(lost, won)
        print(f"\n  discordant pairs: {disc}   McNemar exact p = {p:.4f}")
        print(f"  minimum discordant pairs needed for significance at alpha=0.05: "
              f"{min_discordant_for_significance()}")
        if changed:
            print(f"\n  samples that changed outcome ({len(changed)}):")
            for u, band, x, y in changed:
                print(f"    {u[:8]}  {band:<7} {x:<22} -> {y}")
        else:
            print("\n  no sample changed outcome between temperatures.")
        out["paired"] = {"both": both, f"only_{a}": lost, f"only_{b}": won,
                         "neither": neither, "discordant": disc, "mcnemar_p": p,
                         "changed": changed}

        # per-band paired
        print(f"\n  per band:")
        for bd in BANDS:
            bu = [u for u in uuids if runs[a][u]["band"] == bd]
            w = sum(1 for u in bu if runs[b][u]["trace_valid"] and not runs[a][u]["trace_valid"])
            l = sum(1 for u in bu if runs[a][u]["trace_valid"] and not runs[b][u]["trace_valid"])
            print(f"    {bd:<8} n={len(bu):<4} only T={a}: {l}   only T={b}: {w}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    io.open(args.out, "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
