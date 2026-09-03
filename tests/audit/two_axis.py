"""Phase 3/4: the two-axis grid, trace validity x answer correctness.

The two axes are computed from DISJOINT sources and the separation is enforced,
not merely intended:

  axis 1  trace validity   <- results/verify3_temp{T}.jsonl  (Lean outcome)
  axis 2  answer correctness <- the FormalStep trajectory's own final step

The answer side is built from a record containing only `problem_unique_id`,
`level`, `ground_truth` and the trajectory's step texts. That record is passed
through `assert_no_lean_verdict`, which raises on any Lean field. There is no
code path by which `outcome`, `trace_valid`, `has_sorry` or the dataset's own
`state` can reach the answer verdict.

PILOT SCOPE. The committed n50 runs sample ONE step per problem (stride 10,
first step), and that step belongs to exactly one trajectory. So the unit here is
one trajectory per problem, n=50, and the rows do NOT cluster. "Trace valid"
means "the sampled step's generated proof compiled" -- not "every step of the
trajectory compiled". The strict reading needs a generation run that does not
fit on this machine; see results/PHASE0_DESIGN.md §6.

Run: HF_HUB_OFFLINE=1 python tests/audit/two_axis.py
"""
import collections
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datasets import load_dataset  # noqa: E402

from answer_correctness import assert_no_lean_verdict, score_trajectory  # noqa: E402
from stats import wilson  # noqa: E402

TEMPS = ("0.0", "0.2")
P = print
J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


def ci(k, n):
    if n == 0:
        return "0/0        --"
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100*k/n:5.1f}%  [{100*lo:4.1f}-{100*hi:4.1f}]"


def answer_side(ds_rows, dataset_row):
    """Axis 2 for one sampled step, from the dataset ALONE.

    Deliberately takes the dataset row index, not a trace or verification
    record, so a Lean verdict has no route in.
    """
    row = ds_rows[dataset_row]
    clean = {
        "problem_unique_id": row["problem_unique_id"],
        "level": row["level"],
        "ground_truth": row["ground_truth"],
        "steps": list(row["previous_steps"]),
    }
    assert_no_lean_verdict(clean, where="two_axis.answer_side")
    return score_trajectory(clean["steps"], clean["ground_truth"]), clean


BOOT = 20000
BOOT_SEED = 20260902

# Duplicated from vacuity_scan.CONTENTLESS_CLASSES rather than imported, because
# importing that module pulls in the Lean verifier. tests/test_two_axis_sync.py
# asserts the two stay identical.
CONTENTLESS_CLASSES = (
    "1_goal_is_True",
    "2_hypotheses_contradictory",
    "3_goal_restates_a_hypothesis",
    "4_syntactic_tautology",
    "4b_exists_given_witness",
)


def _phi(aa, bb, cc, dd):
    den = ((aa + bb) * (cc + dd) * (aa + cc) * (bb + dd)) ** 0.5
    return (aa * dd - bb * cc) / den if den else 0.0


def phi_with_ci(rows, mode, boot=BOOT, seed=BOOT_SEED):
    """phi and a percentile bootstrap interval over the 2x2 rows.

    A point estimate with no interval invites reading phi = +0.009 as "proved
    no association", which n=49 cannot support. Bootstrap rather than a closed
    form because cell d is 3 and the normal approximation is not trustworthy
    there.
    """
    import random as _r
    def bucket(r):
        if not r["trace_valid"]:
            return "invalid"
        excluded = r["vacuous_contra"] if mode == "strict" else r["contentless"]
        return "vacuous" if excluded else "valid"

    pts = [(bucket(r) == "valid", r["answer"] == "correct")
           for r in rows
           if bucket(r) in ("valid", "invalid") and r["answer"] in ("correct", "incorrect")]
    if not pts:
        return 0.0, 0.0, 0.0

    def phi_of(sample):
        aa = sum(1 for v, c in sample if v and c)
        bb = sum(1 for v, c in sample if v and not c)
        cc = sum(1 for v, c in sample if not v and c)
        dd = sum(1 for v, c in sample if not v and not c)
        return _phi(aa, bb, cc, dd)

    rng = _r.Random(seed)
    n = len(pts)
    vals = sorted(phi_of([pts[rng.randrange(n)] for _ in range(n)])
                  for _ in range(boot))
    lo = vals[int(0.025 * boot)]
    hi = vals[int(0.975 * boot) - 1]
    return phi_of(pts), lo, hi


def _power_at(n1, n0, p0, p1, alpha=0.05):
    """Power of a two-proportion z-test, normal approximation."""
    from scipy.stats import norm
    za = norm.ppf(1 - alpha / 2)
    pbar = (p1 * n1 + p0 * n0) / (n1 + n0)
    se0 = (pbar * (1 - pbar) * (1 / n1 + 1 / n0)) ** 0.5
    se1 = (p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0) ** 0.5
    if se1 == 0:
        return 1.0
    return float(norm.cdf((abs(p1 - p0) - za * se0) / se1))


def min_detectable_effect(n1, n0, p0, alpha=0.05, power=0.80):
    """(mde, max_achievable_power). mde is None if `power` is unreachable.

    Bisection on p1 above p0 rather than a closed form, so the unequal group
    sizes (n1=36 vs n0=13 here) are handled exactly as they are. With a small
    n0 the target power can be unreachable at ANY effect size -- even p1 = 100%
    -- and that is a more informative statement than a number, so it is
    returned rather than swallowed as nan.
    """
    top = _power_at(n1, n0, p0, 1.0, alpha)
    if top < power:
        return None, top
    lo, hi = p0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _power_at(n1, n0, p0, mid, alpha) >= power:
            hi = mid
        else:
            lo = mid
    return hi - p0, top


def required_n(p0, delta, ratio, alpha=0.05, power=0.80, cap=200000):
    """Smallest n0 (and matching n1 = ratio*n0) to detect p0 -> p0+delta."""
    p1 = min(1.0, p0 + delta)
    n0 = 2
    while n0 < cap:
        if _power_at(max(2, int(round(ratio * n0))), n0, p0, p1, alpha) >= power:
            return n0, int(round(ratio * n0))
        n0 += 1
    return None, None


def mcnemar(pairs):
    """Exact McNemar on paired binary outcomes [(a_i, b_i)]."""
    b = sum(1 for x, y in pairs if x and not y)
    c = sum(1 for x, y in pairs if y and not x)
    n = b + c
    if n == 0:
        return b, c, 1.0
    from math import comb
    tail = sum(comb(n, i) for i in range(0, min(b, c) + 1))
    p = min(1.0, 2 * tail / (2 ** n))
    return b, c, p


def main():
    ds = load_dataset("liuchengwu/FormalStep", split="train")
    # Materialise only the columns the answer axis is allowed to see.
    cols = ds.select_columns(["problem_unique_id", "level", "ground_truth",
                              "previous_steps"])
    ds_rows = {i: cols[i] for i in range(len(cols))}

    vac = json.load(io.open(os.path.join(_ROOT, "results", "vacuity_scan.json"),
                            encoding="utf-8"))

    P("=" * 84)
    P("PHASE 4 PILOT -- two-axis grid on the committed n50 runs")
    P("=" * 84)
    P("  unit: one trajectory per problem (the sampled step's trajectory), n=50")
    P("  rows do NOT cluster: each problem contributes exactly one trajectory")
    P("  'trace valid' = the SAMPLED STEP's generated proof compiled")

    allres = {}
    for T in TEMPS:
        traces = {r["sample_index"]: r
                  for r in J(os.path.join(_ROOT, "traces",
                                          f"temp{T}_n50_1each", "traces.jsonl"))}
        vers = {r["sample_index"]: r
                for r in J(os.path.join(_ROOT, "results", f"verify3_temp{T}.jsonl"))}
        vrows = {r["sample"]: r for r in vac[T]}

        rows = []
        for s in sorted(vers):
            v = vers[s]
            # ---- axis 1, Lean only ----------------------------------------
            valid = v["outcome"] == "valid"
            vrec = vrows.get(s, {})
            contra = bool(vrec.get("contra"))
            cls = vrec.get("class")
            # Kept in step with vacuity_scan.CONTENTLESS_CLASSES; a test asserts
            # the two agree, so adding a probe class there cannot silently leave
            # this grid classifying it as contentful.
            contentless = cls in CONTENTLESS_CLASSES
            # ---- axis 2, dataset only -------------------------------------
            score, clean = answer_side(ds_rows, traces[s]["dataset_row"])
            rows.append({
                "sample": s,
                "problem": clean["problem_unique_id"],
                "level": clean["level"],
                "dataset_row": traces[s]["dataset_row"],
                "trace_valid": valid,
                "outcome": v["outcome"],
                "vacuous_contra": contra,
                "contentless": bool(contentless),
                "vacuity_class": cls,
                "answer": score["verdict"],
                "extracted": score["extracted"],
                "ground_truth": clean["ground_truth"],
                "gt_normalized": score["gt_normalized"],
                "method": score["method"],
                "final_step": clean["steps"][-1] if clean["steps"] else None,
            })
        allres[T] = rows

        P("\n" + "=" * 84)
        P(f"TEMPERATURE {T}")
        P("=" * 84)

        # ---- the grid -----------------------------------------------------
        # Vacuous passes are pulled OUT of the valid row into their own row.
        # Two cuts, because they disagree and the difference matters:
        #   strict   -- the brief's rule: contradictory hypotheses only
        #   contentless -- the repo's existing probe: goal is True, restates a
        #                  hypothesis, is a syntactic tautology, or the
        #                  hypotheses are contradictory (classes 1-4)
        def make_bucket(mode):
            def bucket(r):
                if not r["trace_valid"]:
                    return "invalid"
                excluded = r["vacuous_contra"] if mode == "strict" else r["contentless"]
                return "vacuous" if excluded else "valid"
            return bucket

        n = len(rows)
        grids = {}
        ANSW = ("correct", "incorrect", "answer_unknown")
        for mode, title in (("strict", "vacuous = contradictory hypotheses (the brief's rule)"),
                            ("contentless", "vacuous = contentless goal (classes 1-4)")):
            bucket = make_bucket(mode)
            P(f"\n  FULL TABLE, n={n} -- {title}")
            P("  Rows are DISJOINT: a vacuous pass is removed from the valid row,")
            P("  not nested inside it. All nine cells sum to n.")
            P(f"  {'':<16}{'correct':>10}{'incorrect':>11}{'unknown':>10}{'ROW TOTAL':>12}")
            counts = {}
            for b in ("valid", "vacuous", "invalid"):
                sub = [r for r in rows if bucket(r) == b]
                cells = collections.Counter(r["answer"] for r in sub)
                counts[b] = cells
                label = {"valid": "trace valid", "vacuous": "vacuous pass",
                         "invalid": "trace invalid"}[b]
                P(f"  {label:<16}{cells['correct']:>10}{cells['incorrect']:>11}"
                  f"{cells['answer_unknown']:>10}{len(sub):>12}")
            P(f"  {'COLUMN TOTAL':<16}"
              + "".join(f"{sum(counts[b][a] for b in counts):>{w}}"
                        for a, w in zip(ANSW, (10, 11, 10)))
              + f"{n:>12}")
            total = sum(counts[b][a] for b in counts for a in ANSW)
            assert total == n, f"table sums to {total}, not {n}"

            P(f"\n  same table with 95% Wilson intervals, every cell over n={n}:")
            for b in ("valid", "vacuous", "invalid"):
                label = {"valid": "trace valid", "vacuous": "vacuous pass",
                         "invalid": "trace invalid"}[b]
                P(f"    {label:<15}" + "  ".join(
                    f"{a[:9]:>9} {ci(counts[b][a], n)}" for a in ANSW))

            g = tuple(counts[bk][av]
                      for bk, av in (("valid", "correct"), ("valid", "incorrect"),
                                     ("invalid", "correct"), ("invalid", "incorrect")))
            grids[mode] = g
            excl_vac = len([r for r in rows if bucket(r) == "vacuous"])
            excl_unk = sum(counts[b]["answer_unknown"] for b in counts)
            P(f"\n    2x2 restriction (a,b,c,d) = {g},  n={sum(g)} of {n}")
            P(f"    the {n - sum(g)} row(s) not in the 2x2: "
              f"{excl_vac} vacuous pass(es), {excl_unk} answer_unknown"
              f"  ({excl_vac} + {excl_unk} = {n - sum(g)})")

        bucket = make_bucket("strict")
        a, b_, c_, d_ = grids["strict"]

        # ---- marginals ----------------------------------------------------
        P(f"\n  marginals:")
        P(f"    trace valid           {ci(sum(1 for r in rows if r['trace_valid']), n)}")
        P(f"    of which vacuous      {ci(sum(1 for r in rows if r['vacuous_contra']), n)}")
        P(f"    of which contentless  {ci(sum(1 for r in rows if r['contentless']), n)}")
        ac = collections.Counter(r["answer"] for r in rows)
        P(f"    answer correct        {ci(ac['correct'], n)}")
        P(f"    answer incorrect      {ci(ac['incorrect'], n)}")
        P(f"    answer unknown        {ci(ac['answer_unknown'], n)}")

        # ---- effect size, for BOTH vacuity cuts ---------------------------
        from scipy.stats import fisher_exact
        P("\n  effect size -- does trace validity predict answer correctness?")
        P("  Point estimates come with intervals; an interval this wide means the")
        P("  study is UNDERPOWERED, not that the effect is null.")
        for mode in ("strict", "contentless"):
            g = grids[mode]
            aa, bb, cc, dd = g
            if not ((aa + bb) and (cc + dd)):
                continue
            n1, n0 = aa + bb, cc + dd
            p1, p0 = aa / n1, cc / n0
            rd = p1 - p0
            se = (p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0) ** 0.5
            orat = (f"{(aa*dd)/(bb*cc):.2f}" if bb * cc else "undefined (zero cell)")
            _o, pv = fisher_exact([[aa, bb], [cc, dd]])
            phi, plo, phi_hi = phi_with_ci(rows, mode)
            P(f"\n    [{mode}]")
            P(f"      P(correct | valid)    {ci(aa, n1)}")
            P(f"      P(correct | invalid)  {ci(cc, n0)}")
            P(f"      risk difference       {100*rd:+.1f} pp  "
              f"95% CI [{100*(rd-1.96*se):+.1f}, {100*(rd+1.96*se):+.1f}]")
            P(f"      odds ratio            {orat}")
            P(f"      phi                   {phi:+.3f}  "
              f"95% bootstrap CI [{plo:+.3f}, {phi_hi:+.3f}]  ({BOOT} resamples, seed {BOOT_SEED})")
            P(f"      Fisher exact          p = {pv:.3f}")
            mde, top = min_detectable_effect(n1, n0, p0)
            P(f"      power at observed     {100*_power_at(n1, n0, p0, p1):.0f}%"
              f"  (alpha=0.05 two-sided, baseline {100*p0:.1f}%, n1={n1} n0={n0})")
            if mde is None:
                P(f"      MDE at 80% power      NOT ACHIEVABLE at any effect size.")
                P(f"        Even p1 = 100% vs {100*p0:.1f}% reaches only "
                  f"{100*top:.0f}% power with n0={n0}.")
            else:
                P(f"      MDE at 80% power      {100*mde:.1f} pp")
            ratio = n1 / n0
            P(f"      n needed at 80% power (same {ratio:.1f}:1 allocation, "
              f"baseline {100*p0:.1f}%):")
            for delta in (0.10, 0.15, 0.20, 0.25):
                q0, q1 = required_n(p0, delta, ratio)
                if q0:
                    P(f"        to detect {100*delta:>4.0f} pp -> n0={q0:<5} n1={q1:<5} "
                      f"total {q0+q1}")

        # ---- cell b, hand-read -------------------------------------------
        cellb = [r for r in rows if bucket(r) == "valid" and r["answer"] == "incorrect"]
        P(f"\n  CELL b -- valid trace, wrong answer: {len(cellb)} case(s)")
        for r in cellb:
            P(f"    sample {r['sample']:<4}{r['problem'].replace('math_train_counting_and_probability_','#'):<8}"
              f"{r['level']:<9}gt={r['ground_truth']!r} extracted={r['extracted']!r}")
            P(f"      vacuity={r['vacuity_class']}  method={r['method']}")
            P(f"      final step: {(r['final_step'] or '')[:150]!r}")

    # ---- temperature comparison (paired) ----------------------------------
    P("\n" + "=" * 84)
    P("TEMPERATURE COMPARISON (paired -> McNemar, not a two-sample test)")
    P("=" * 84)
    r0 = {r["sample"]: r for r in allres["0.0"]}
    r2 = {r["sample"]: r for r in allres["0.2"]}
    common = sorted(set(r0) & set(r2))
    for axis, fn in (("trace_valid", lambda r: r["trace_valid"]),
                     ("answer correct", lambda r: r["answer"] == "correct")):
        pairs = [(fn(r0[s]), fn(r2[s])) for s in common]
        b, c, p = mcnemar(pairs)
        P(f"  {axis:<18}discordant b={b} c={c}   McNemar exact p = {p:.3f}")
    P("\n  NOTE the answer axis is TEMPERATURE-INVARIANT BY CONSTRUCTION: the")
    P("  trajectory is read from the dataset, not generated by our model, so")
    P("  temperature cannot move it and b=c=0 is forced. Its McNemar p is not")
    P("  evidence of a null effect -- there is no effect to have. Only the trace")
    P("  axis carries a real temperature comparison.")

    dest = os.path.join(_ROOT, "results", "two_axis.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(allres, fh, indent=2, ensure_ascii=False)
    P(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
