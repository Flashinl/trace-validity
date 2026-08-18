"""Recompute every statistic in SUMMARY_n50_distinct.md from committed artifacts.

Reads ONLY:
  traces/temp0.{0,2}_n50_1each/traces.jsonl   (+ run_meta.json)
  results/verify2_temp0.{0,2}.jsonl           (the corrected verification pass)
  results/verify_temp0.{0,2}.jsonl            (the superseded pass, for the delta)

Emits every number the summary reports, each with an n and a Wilson 95% CI.
No network, no GPU, no Lean.  Run:  python results/recompute_stats.py
"""
import io, json, math, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
J = lambda p: [json.loads(l) for l in io.open(os.path.join(ROOT, p), encoding="utf-8") if l.strip()]
LOAD = lambda p: json.load(io.open(os.path.join(ROOT, p), encoding="utf-8"))

NEW = {"0.0": "results/verify2_temp0.0.jsonl", "0.2": "results/verify2_temp0.2.jsonl"}
OLD = {"0.0": "results/verify_temp0.0.jsonl",  "0.2": "results/verify_temp0.2.jsonl"}
TR  = {"0.0": "traces/temp0.0_n50_1each/traces.jsonl", "0.2": "traces/temp0.2_n50_1each/traces.jsonl"}
MET = {"0.0": "traces/temp0.0_n50_1each/run_meta.json", "0.2": "traces/temp0.2_n50_1each/run_meta.json"}

# Outcomes that are NOT a verdict on the model's proof.
NO_VERDICT = {"statement_error", "parse_failure", "timeout", "verifier_crash"}


# ---------------------------------------------------------------- statistics
def wilson(k, n, z=1.959963984540054):
    """Wilson score interval. Correct at k=0 and k=n, unlike the normal approx."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate(k, n, label=""):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n if n else float("nan")),
            "ci95": [lo, hi], "label": label}


def fmt(r):
    if r["n"] == 0:
        return "%d/0 = n/a" % r["k"]
    return "%d/%d = %.0f%% (95%% CI %.0f-%.0f%%)" % (
        r["k"], r["n"], 100 * r["rate"], 100 * r["ci95"][0], 100 * r["ci95"][1])


def rule_of_three_upper(n, alpha=0.05):
    """One-sided 95% upper bound on p when 0 events were seen in n trials.
    Exact: 1 - alpha**(1/n).  (The 3/n rule is its large-n approximation.)"""
    return 1 - alpha ** (1.0 / n) if n else float("nan")


def binom_pmf(k, n, p=0.5):
    return math.comb(n, k) * p ** k * (1 - p) ** (n - k)


def mcnemar_exact(b, c):
    """Two-sided exact (binomial) McNemar on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0, n
    obs = binom_pmf(b, n)
    p = sum(binom_pmf(i, n) for i in range(n + 1) if binom_pmf(i, n) <= obs + 1e-12)
    return min(1.0, p), n


# ---------------------------------------------------------------- load
new = {T: {r["sample_index"]: r for r in J(p)} for T, p in NEW.items()}
old = {T: {r["sample_index"]: r for r in J(p)} for T, p in OLD.items()}
tr = {T: {r["sample_index"]: r for r in J(p)} for T, p in TR.items()}
meta = {T: LOAD(p) for T, p in MET.items()}

R = {}
print("=" * 74)
print("RECOMPUTED FROM COMMITTED ARTIFACTS -- results/recompute_stats.py")
print("=" * 74)

# ---------------------------------------------------------------- 1. outcomes
print("\n[1] OUTCOME DISTRIBUTION")
for T in ("0.0", "0.2"):
    v = new[T]
    counts = {}
    for r in v.values():
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    n_all = len(v)
    n_verdict = sum(1 for r in v.values() if r["outcome"] not in NO_VERDICT)
    k = counts.get("valid", 0)
    R["outcomes_" + T] = counts
    R["valid_over_all_" + T] = rate(k, n_all)
    R["valid_over_verdicts_" + T] = rate(k, n_verdict)
    print("  T=%s: %s" % (T, ", ".join("%s=%d" % (o, c) for o, c in sorted(counts.items()))))
    print("     validity over ALL traces       : " + fmt(R["valid_over_all_" + T]))
    print("     validity over traces w/ VERDICT: " + fmt(R["valid_over_verdicts_" + T]))

print("\n[1b] SUPERSEDED PASS (verify_temp*.jsonl) -- the 72% the pushed summary reports")
for T in ("0.0", "0.2"):
    o = old[T]
    c = {}
    for r in o.values():
        c[r["outcome"]] = c.get(r["outcome"], 0) + 1
    k = c.get("valid", 0)
    R["old_valid_" + T] = rate(k, len(o))
    print("  T=%s: %s   validity %s" % (T, c, fmt(R["old_valid_" + T])))
    moved = sorted(i for i in o if o[i]["outcome"] != new[T][i]["outcome"])
    print("     outcome changed old->new: " + ", ".join(
        "%d(%s->%s)" % (i, o[i]["outcome"], new[T][i]["outcome"]) for i in moved))

# ---------------------------------------------------------------- 2. crosstab
print("\n[2] VERDICT x DATASET PROVABILITY (state) -- AGREEMENT, not ground truth")
for T in ("0.0", "0.2"):
    v = new[T]
    ct = {}
    for r in v.values():
        band = ("no_verdict" if r["outcome"] in NO_VERDICT
                else ("valid" if r["outcome"] == "valid" else "not_valid"))
        ct.setdefault(band, {}).setdefault(r["state"], 0)
        ct[band][r["state"]] += 1
    R["crosstab_" + T] = ct
    print("  T=%s" % T)
    print("    %-12s%18s%18s%8s" % ("", "Success of Proof", "Failure of Proof", "total"))
    for band in ("valid", "not_valid", "no_verdict"):
        s = ct.get(band, {}).get("Success of Proof", 0)
        f_ = ct.get(band, {}).get("Failure of Proof", 0)
        print("    %-12s%18d%18d%8d" % (band, s, f_, s + f_))

    unprov_verdict = sum(1 for r in v.values()
                         if r["state"] == "Failure of Proof" and r["outcome"] not in NO_VERDICT)
    fp = sum(1 for r in v.values()
             if r["state"] == "Failure of Proof" and r["outcome"] == "valid")
    ub = rule_of_three_upper(unprov_verdict)
    R["disagree_" + T] = {"k": fp, "n": unprov_verdict, "one_sided_95_upper": ub}
    print("    valid-on-dataset-unprovable: %d/%d. With 0 events in n=%d, the one-sided"
          % (fp, unprov_verdict, unprov_verdict))
    print("      95%% upper bound on that rate is %.0f%%." % (100 * ub))

    prov_verdict = sum(1 for r in v.values()
                       if r["state"] == "Success of Proof" and r["outcome"] not in NO_VERDICT)
    prov_fail = sum(1 for r in v.values()
                    if r["state"] == "Success of Proof" and r["outcome"] == "compile_error")
    R["provable_fail_" + T] = rate(prov_fail, prov_verdict)
    fails = sorted(i for i, r in v.items()
                   if r["state"] == "Success of Proof" and r["outcome"] == "compile_error")
    print("    failed a dataset-provable statement THAT GOT A VERDICT: %s  samples=%s"
          % (fmt(R["provable_fail_" + T]), fails))

# ---------------------------------------------------------------- 3. denominators
print("\n[3] DENOMINATORS -- explicit exclusion rule")
print("  RULE: a sample is 'testable' iff its outcome is a verdict on the model's")
print("        proof, i.e. outcome NOT in {statement_error, parse_failure, timeout,")
print("        verifier_crash}. Exclusions leave BOTH numerator and denominator.")
print("        maxRecDepth is verifier configuration, not an exclusion: sample 12")
print("        is testable under the corrected verifier and it PASSES.")
for T in ("0.0", "0.2"):
    v = new[T]
    unt = sorted(i for i, r in v.items() if r["outcome"] in NO_VERDICT)
    R["untestable_" + T] = unt
    print("  T=%s: untestable = %s (%d of %d); testable n = %d"
          % (T, unt, len(unt), len(v), len(v) - len(unt)))
    for i in unt:
        print("        sample %-3d %-16s state=%-18s %s"
              % (i, v[i]["outcome"], v[i]["state"],
                 (v[i].get("statement_error_detail") or "")[:60]))

# ---------------------------------------------------------------- 4. paired
print("\n[4] TEMPERATURE COMPARISON, PAIRED (same 50 samples)")
common = sorted(set(new["0.0"]) & set(new["0.2"]))
both = only0 = only2 = neither = 0
f0, f2 = [], []
for i in common:
    a = new["0.0"][i]["outcome"] == "valid"
    b = new["0.2"][i]["outcome"] == "valid"
    if a and b:
        both += 1
    elif a:
        only0 += 1; f0.append(i)
    elif b:
        only2 += 1; f2.append(i)
    else:
        neither += 1
p, ndisc = mcnemar_exact(only0, only2)
R["paired"] = {"both": both, "only_T0.0": only0, "only_T0.2": only2,
               "neither": neither, "mcnemar_exact_p": p, "n_discordant": ndisc}
print("  valid in both      : %d" % both)
print("  valid only T=0.0   : %d  samples=%s" % (only0, f0))
print("  valid only T=0.2   : %d  samples=%s" % (only2, f2))
print("  valid in neither   : %d" % neither)
print("  McNemar exact (b=%d, c=%d): p = %.3f  [discordant pairs n=%d]" % (only0, only2, p, ndisc))
print("  Difference in validity rate: %+.1f pp"
      % (100 * (R["valid_over_all_0.0"]["rate"] - R["valid_over_all_0.2"]["rate"])))
print("  POWER: with 50 paired samples and 1 trajectory each, only the discordant")
print("  pairs carry information. n=2 discordant pairs cannot reject anything;")
print("  p=1.0 here is an ABSENCE OF EVIDENCE, not evidence of no difference.")
need = next((n for n in range(1, 60) if 2 * binom_pmf(0, n) < 0.05), None)
print("  For reference: an all-one-way split needs n>=%d discordant pairs before"
      " two-sided p<0.05 is attainable at all." % need)

# ---------------------------------------------------------------- 5. timing
print("\n[5] VERIFICATION TIMING (sum of per-record seconds)")
for T in ("0.0", "0.2"):
    s = [r["seconds"] for r in new[T].values()]
    fast = sum(1 for x in s if x < 0.05)
    R["timing_" + T] = {"total": round(sum(s), 1), "mean": round(sum(s) / len(s), 3),
                        "min": min(s), "max": max(s), "under_50ms": fast}
    print("  T=%s: total %.1fs over %d verifications, mean %.3fs, min %ss, max %ss; "
          "%d/%d completed in <50ms" % (T, sum(s), len(s), sum(s) / len(s), min(s), max(s),
                                        fast, len(s)))
    modes = {}
    for r in new[T].values():
        modes[r["mode"]] = modes.get(r["mode"], 0) + 1
    print("        modes: %s  (shared_env = run against the pre-imported Mathlib env)" % modes)

# ---------------------------------------------------------------- 6. sample shift
print("\n[6] IS THE 42%->74% JUMP 'A CHANGE OF SAMPLE'?  (the asserted claim)")
try:
    base = J("traces/temp_0.jsonl")
    seen, blen = set(), []
    for r in base:
        if r["sample_index"] in seen:
            continue
        seen.add(r["sample_index"])
        blen.append(len(r.get("formal_statement") or ""))
    nlen = [len(tr["0.0"][i].get("formal_statement") or "") for i in sorted(tr["0.0"])]
    med = lambda x: sorted(x)[len(x) // 2]
    bstates = {}
    for r in base:
        if r["trajectory_index"] == 0:
            bstates[r["state"]] = bstates.get(r["state"], 0) + 1
    nstates = meta["0.0"]["dataset"]["selection"]["states"]
    R["sample_shift"] = {"old_median_stmt_chars": med(blen), "new_median_stmt_chars": med(nlen),
                         "old_states": bstates, "new_states": nstates,
                         "old_distinct_problems": len({r.get("problem_unique_id") for r in base})}
    print("  OLD set (traces/temp_0.jsonl): %d samples, %d distinct problem(s), median"
          " formal_statement %d chars, states %s"
          % (len(seen), R["sample_shift"]["old_distinct_problems"], med(blen), bstates))
    print("  NEW set: 50 samples, 50 distinct problems, median formal_statement %d chars,"
          " states %s" % (med(nlen), nstates))
    print("  -> The two sets differ in problem coverage and statement length, so they are")
    print("     not exchangeable. This SUPPORTS the 'change of sample' reading but does")
    print("     not test it: no experiment holds the model fixed across matched samples.")
except Exception as e:
    print("  UNVERIFIED -- could not load the baseline set: %s: %s" % (type(e).__name__, e))

# ---------------------------------------------------------------- 7. hygiene
print("\n[7] GENERATION HYGIENE (from traces.jsonl)")
for T in ("0.0", "0.2"):
    t = tr[T]
    print("  T=%s: truncated=%d, hit_token_limit=%d, closed_fence=False:%d, max"
          " generated_tokens=%d of budget %s"
          % (T,
             sum(1 for r in t.values() if r.get("truncated")),
             sum(1 for r in t.values() if r.get("hit_token_limit")),
             sum(1 for r in t.values() if r.get("closed_fence") is False),
             max(r.get("generated_tokens") or 0 for r in t.values()),
             sorted({r.get("max_new_tokens") for r in t.values()})))
    print("        recorded generation git sha: %r" % (meta[T]["git"]["sha"],))

json.dump(R, io.open(os.path.join(ROOT, "results", "recomputed_stats.json"), "w",
                     encoding="utf-8"), indent=2, ensure_ascii=False)
print("\nwrote results/recomputed_stats.json")
