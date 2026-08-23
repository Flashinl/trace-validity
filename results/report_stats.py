"""Every reported number in this repo, computed once, from artifacts, via stats.py.

Both reports import from here. Nothing in either document is hand-typed.

Run `python results/report_stats.py` to print the figures;
`python results/regenerate_reports.py` to re-emit the documents.
"""
import io, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from stats import (  # noqa: E402
    rate, wilson, zero_event_upper, mcnemar_exact, two_proportion_z,
    min_detectable_difference, min_discordant_for_significance,
    cluster_warning, pct,
)

J = lambda p: [json.loads(l) for l in io.open(os.path.join(ROOT, p), encoding="utf-8") if l.strip()]
L = lambda p: json.load(io.open(os.path.join(ROOT, p), encoding="utf-8"))

# The exclusion rule. Stated once; every denominator below derives from it.
NO_VERDICT = {"statement_error", "statement_mismatch", "parse_failure",
              "timeout", "verifier_crash"}
EXCLUSION_RULE = (
    "A sample is *testable* iff the verifier reached a verdict on the model's "
    "proof, i.e. `outcome ∉ {statement_error, statement_mismatch, parse_failure, "
    "timeout, verifier_crash}`. An excluded sample leaves **both** numerator and "
    "denominator. `maxRecDepth` is verifier configuration, not an exclusion."
)


def _load_n50(T):
    vers = {r["sample_index"]: r for r in J(f"results/verify3_temp{T}.jsonl")}
    traces = {r["sample_index"]: r for r in J(f"traces/temp{T}_n50_1each/traces.jsonl")}
    recs = [dict(r, problem_unique_id=traces[i].get("problem_unique_id"))
            for i, r in vers.items()]
    return vers, traces, recs


def n50(T):
    vers, traces, recs = _load_n50(T)
    counts = {}
    for r in vers.values():
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    testable = {i: r for i, r in vers.items() if r["outcome"] not in NO_VERDICT}
    excluded = sorted(set(vers) - set(testable))
    n_valid = counts.get("valid", 0)

    prov = {i: r for i, r in vers.items() if r["state"] == "Success of Proof"}
    unprov = {i: r for i, r in vers.items() if r["state"] == "Failure of Proof"}
    prov_t = {i: r for i, r in prov.items() if i in testable}
    unprov_t = {i: r for i, r in unprov.items() if i in testable}
    prov_fail = sorted(i for i, r in prov_t.items() if r["outcome"] != "valid")
    certified = sorted(i for i, r in unprov_t.items() if r["outcome"] == "valid")

    return {
        "T": T, "records": recs, "counts": counts, "excluded": excluded,
        "cluster": cluster_warning(recs),
        "headline": rate(n_valid, len(vers), records=recs),
        "testable": rate(n_valid, len(testable), records=recs),
        "prov_fail": rate(len(prov_fail), len(prov_t), records=recs),
        "prov_fail_samples": prov_fail,
        "n_prov": len(prov), "n_prov_t": len(prov_t),
        "n_unprov": len(unprov), "n_unprov_t": len(unprov_t),
        "certified": certified,
        "agree_bound_testable": zero_event_upper(len(unprov_t)),
        "agree_bound_all": zero_event_upper(len(unprov)),
        "crosstab": {
            band: {st: sum(1 for i, r in vers.items()
                           if r["state"] == st and (
                               "no_verdict" if r["outcome"] in NO_VERDICT
                               else ("valid" if r["outcome"] == "valid" else "not_valid")) == band)
                   for st in ("Success of Proof", "Failure of Proof")}
            for band in ("valid", "not_valid", "no_verdict")},
    }


def paired():
    a = {r["sample_index"]: r for r in J("results/verify3_temp0.0.jsonl")}
    b = {r["sample_index"]: r for r in J("results/verify3_temp0.2.jsonl")}
    both = only0 = only2 = neither = 0
    f0, f2 = [], []
    for i in sorted(set(a) & set(b)):
        x, y = a[i]["outcome"] == "valid", b[i]["outcome"] == "valid"
        if x and y:
            both += 1
        elif x:
            only0 += 1; f0.append(i)
        elif y:
            only2 += 1; f2.append(i)
        else:
            neither += 1
    n = len(set(a) & set(b))
    p, nd = mcnemar_exact(only0, only2)
    pi_d = nd / n
    return {"both": both, "only0": only0, "only2": only2, "neither": neither,
            "f0": f0, "f2": f2, "p": p, "n_discordant": nd, "n_pairs": n,
            "discordant_rate": pi_d,
            "mde": min_detectable_difference(n, pi_d),
            "mde_at_20pct": min_detectable_difference(n, 0.20),
            "min_disc": min_discordant_for_significance()}


def baseline():
    """The 50-consecutive-steps-of-ONE-problem set. Clustered; no valid CI."""
    vers = {r["sample_index"]: r for r in J("results/verification_temp_0.jsonl")}
    traces = {}
    for r in J("traces/temp_0.jsonl"):
        traces.setdefault(r["sample_index"], r)
    recs = [dict(r, problem_unique_id=traces[i].get("problem_unique_id"))
            for i, r in vers.items()]
    counts = {}
    for r in vers.values():
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    n_valid = counts.get("valid", 0)

    xc = L("results/crosscheck.json")["summary"]
    ref = L("results/reference_proofs.json")["counts"]
    n_ref = sum(ref.values())
    ref_ok = ref.get("valid", 0)

    # 6 -> 5 correction: sample 14's own reference proof does not compile, so its
    # provability is UNKNOWN and it cannot count as a failure on a provable one.
    verified_provable = xc["agree_provable"] + xc["model_failed_on_provable_stmt"] - 1
    failed_verified = xc["model_failed_on_provable_stmt"] - 1
    n_unprov = xc["agree_unprovable"]

    prov_json = L("results/arithmetic_provenance.json")["records"]["baseline_50step_1problem"]
    untestable = sum(1 for r in prov_json if r["label"] in ("statement_false", "parse_skew"))

    return {
        "records": recs, "counts": counts, "cluster": cluster_warning(recs),
        "headline": rate(n_valid, len(vers), records=recs),
        "n_all": len(vers), "n_valid": n_valid,
        "ref_compiles": rate(ref_ok, n_ref),
        "failed_verified_provable": rate(failed_verified, verified_provable, records=recs),
        "n_unprov": n_unprov,
        "agree_bound": zero_event_upper(n_unprov),
        "conditional": rate(n_valid, len(vers) - untestable, records=recs,
                            conditional_on="excluded statement_false + parse_skew"),
        "untestable": untestable,
        "n_raw_rows": len(J("traces/temp_0.jsonl")),
        "n_distinct": len({r["sample_index"] for r in J("traces/temp_0.jsonl")}),
    }


def cross_set_comparison(base, d00):
    """The 42% -> 74% comparison. Confounded; reported only with the confound."""
    z, p = two_proportion_z(base["n_valid"], base["n_all"],
                            d00["headline"].k, d00["headline"].n)
    return {"z": z, "p": p,
            "confound": ("different populations: 50 consecutive steps inside ONE "
                         "problem vs 50 first-steps of 50 different problems"),
            "clustered": base["cluster"]["clustered"]}


def all_figures():
    d00, d02 = n50("0.0"), n50("0.2")
    b = baseline()
    return {"n50_00": d00, "n50_02": d02, "paired": paired(), "baseline": b,
            "cross": cross_set_comparison(b, d00)}


if __name__ == "__main__":
    F = all_figures()
    print("=" * 80)
    print("EVERY REPORTED NUMBER, FROM stats.py")
    print("=" * 80)
    for k in ("n50_00", "n50_02"):
        d = F[k]
        print(f"\n--- n50 distinct problems, T={d['T']} ---")
        print(f"  cluster check      : {d['cluster']['reason']}")
        print(f"  headline validity  : {d['headline']}")
        print(f"  over testable      : {d['testable']}   (excluded {d['excluded']})")
        print(f"  failed a provable  : {d['prov_fail']}   samples={d['prov_fail_samples']}")
        print(f"  certified unprovable: {len(d['certified'])}/{d['n_unprov_t']}"
              f"  -> 95% upper bound {pct(d['agree_bound_testable'])}"
              f"  (on all {d['n_unprov']}: {pct(d['agree_bound_all'])})")
    p = F["paired"]
    print(f"\n--- paired temperature comparison ---")
    print(f"  both {p['both']}, only T=0.0 {p['only0']} {p['f0']}, only T=0.2 {p['only2']} {p['f2']}, neither {p['neither']}")
    print(f"  McNemar exact: p = {p['p']:.3f} on {p['n_discordant']} discordant pairs")
    print(f"  min discordant pairs for any significance: {p['min_disc']}")
    print(f"  minimum detectable difference at 80% power: {p['mde']}"
          f"  (UNATTAINABLE at the observed discordant rate {p['discordant_rate']:.2f})")
    print(f"  ...if the discordant rate were 20%: {p['mde_at_20pct']:.2f}"
          if p["mde_at_20pct"] else "")
    b = F["baseline"]
    print(f"\n--- baseline: 50 steps of ONE problem ---")
    print(f"  cluster check      : {b['cluster']['reason']}")
    print(f"  headline validity  : {b['headline']}")
    print(f"  conditional        : {b['conditional']}")
    print(f"  reference proofs   : {b['ref_compiles']}")
    print(f"  failed a VERIFIED-provable statement: {b['failed_verified_provable']}")
    print(f"  certified unprovable: 0/{b['n_unprov']} -> 95% upper bound {pct(b['agree_bound'])}")
    print(f"  raw rows {b['n_raw_rows']} vs distinct samples {b['n_distinct']}"
          f"  ({b['n_raw_rows']-b['n_distinct']} duplicates)")
    c = F["cross"]
    print(f"\n--- cross-set comparison (DO NOT REPORT BARE) ---")
    print(f"  z = {c['z']:.2f}, p = {c['p']:.4f}")
    print(f"  CONFOUND: {c['confound']}")
    print(f"  and the baseline arm is clustered: {c['clustered']}")
