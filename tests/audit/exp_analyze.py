"""Statistics for the three GPU tactic-recovery experiments.

No Lean, no GPU -- reads the verdict files exp_verify.py wrote and the vacuity
labels exp_vacuity.py wrote, and emits results/GPU_TACTIC_RECOVERY.json.

Every rate routes through stats.py, which is the repo's single source for
Wilson intervals and the exact McNemar test. Nothing here recomputes an
interval by hand.

Three separations are enforced in code rather than left to the writer:

  * FormalStep and Stage B are never pooled into one rate. They are different
    formalization pipelines with different units (CURRENT_NUMBERS.md).
  * n50 distinct and the baseline 50-step set are never pooled. The baseline is
    50 CoT steps of ONE problem, so its rows are clustered, not independent;
    `stats.cluster_warning` is attached to every figure computed on it.
  * One-shot and with-repair are separate rows. Experiment 3 measures a
    different prompt shape and merging it into a validity headline would be the
    same error as folding the oracle's ceiling into the observed rate.
"""
import argparse
import collections
import hashlib
import io
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from stats import (wilson, mcnemar_exact, mcnemar_power,
                   min_discordant_for_significance, min_detectable_difference)

R = lambda *p: os.path.join(_ROOT, *p)
J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]
PASS_K = (1, 2, 4, 8, 16)


def pct(x):
    return None if x is None else round(100.0 * x, 1)


def rate(k, n):
    if n <= 0:
        return {"k": k, "n": n, "pct": None, "ci": [None, None]}
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "pct": pct(k / n), "ci": [pct(lo), pct(hi)]}


# --------------------------------------------------------------------------- #
# pass@k -- the unbiased estimator, not "did any of the first k pass"
# --------------------------------------------------------------------------- #
def pass_at_k(n, c, k):
    """1 - C(n-c, k)/C(n, k): probability a random k-subset contains a pass.

    Taking the first k samples and asking whether any passed is biased and
    overstates, because it throws away the other n-k draws that were paid for.
    """
    if k > n:
        raise ValueError("k=%d exceeds n=%d samples generated" % (k, n))
    if c <= 0:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_curve(per_problem, ks=PASS_K, boot=5000, seed=20260830):
    """pass@k over a list of (n_samples, n_correct), with two intervals.

    pass@k is a MEAN of per-problem estimates, so it is not a raw binomial
    count. Two intervals are reported and neither is hidden:

      wilson_ci    treats the estimate as a proportion over problems. Exact at
                   k = n, where each problem's estimator is 0 or 1; an
                   approximation below that, which is why the bootstrap is here.
      boot_ci      percentile bootstrap resampling PROBLEMS, which is the unit
                   of independence. This is the one to quote when they differ.
    """
    import random

    rng = random.Random(seed)
    N = len(per_problem)
    out = {}
    for k in ks:
        vals = [pass_at_k(n, c, k) for n, c in per_problem if n >= k]
        if not vals:
            out["pass@%d" % k] = None
            continue
        est = sum(vals) / len(vals)
        lo, hi = wilson(int(round(est * len(vals))), len(vals))
        reps = []
        for _ in range(boot):
            reps.append(sum(rng.choice(vals) for _ in range(len(vals))) / len(vals))
        reps.sort()
        out["pass@%d" % k] = {
            "pct": pct(est), "n_problems": len(vals),
            "wilson_ci": [pct(lo), pct(hi)],
            "boot_ci": [pct(reps[int(0.025 * boot)]), pct(reps[int(0.975 * boot)])],
            "n_solved_by_any": sum(1 for n, c in per_problem if c > 0),
        }
    out["n_problems_total"] = N
    return out


# --------------------------------------------------------------------------- #
# Experiment 1 -- paired doc-comment ablation
# --------------------------------------------------------------------------- #
def load_arm(path, key="problem_unique_id"):
    """item id -> passed?, from an exp_verify verdict file."""
    out = {}
    for r in J(path):
        k = r.get(key)
        if k is None:
            k = r.get("sample_index")
        out[k] = bool(r.get("valid"))
    return out


def vacuity_by_sample(trace_path):
    """sample_index -> is the statement closed without a proof?

    The vacuity file is keyed on the sha256 of the statement text, because the
    baseline set's 50 rows share one problem_unique_id. A statement never probed
    (because no arm ever passed it) is absent, and absence is treated as
    not-vacuous -- the probe only ever runs on the pass set.
    """
    path = R("results", "exp_vacuity.json")
    if not os.path.exists(path) or not os.path.exists(trace_path):
        return {}
    vac = json.load(io.open(path, encoding="utf-8"))
    out = {}
    for r in J(trace_path):
        h = hashlib.sha256((r.get("formal_statement") or "").strip()
                           .encode("utf-8")).hexdigest()
        if h in vac:
            out[r["sample_index"]] = bool(vac[h]["vacuous"])
    return out


def statement_false_ids(run_name, id_by_sample):
    """Sample indices labelled `statement_false` by the arithmetic labeller.

    Only FAILING samples carry a label -- a row that passed has a provable
    statement by construction, so absence of a label is a real "not
    statement_false", not a missing value.
    """
    ap = json.load(io.open(R("results", "arithmetic_provenance.json"), encoding="utf-8"))
    out = {}
    for row in ap["records"].get(run_name, []):
        out[id_by_sample.get(row["sample"], row["sample"])] = row["label"]
    return out


def mcnemar_block(a, b, ids, label, vac=None):
    """Paired comparison on `ids`. b = A pass & B fail, c = A fail & B pass.

    `vac` maps an id to True when the vacuity ladder closes that statement
    without a proof. When supplied, every discordant pair is additionally
    reported as vacuous or not: a flip onto a statement whose hypotheses are
    contradictory is a false positive being created, not a proof being found,
    and must never be read as the manipulation helping.
    """
    ids = [i for i in ids if i in a and i in b]
    n = len(ids)
    bb = sum(1 for i in ids if a[i] and not b[i])
    cc = sum(1 for i in ids if not a[i] and b[i])
    p, ndis = mcnemar_exact(bb, cc)
    ka = sum(1 for i in ids if a[i])
    kb = sum(1 for i in ids if b[i])
    need = min_discordant_for_significance(0.05)
    block = {
        "subgroup": label, "n_pairs": n,
        "armA_doc_comment": rate(ka, n),
        "armB_no_doc_comment": rate(kb, n),
        "b_A_pass_B_fail": bb, "c_A_fail_B_pass": cc,
        "n_discordant": ndis, "mcnemar_exact_p": round(p, 4),
        "min_discordant_for_any_significance": need,
        "can_possibly_reach_p05": ndis >= need,
    }
    if vac is not None:
        bset = [i for i in ids if a[i] and not b[i]]
        cset = [i for i in ids if not a[i] and b[i]]
        block["vacuity_of_discordant"] = {
            "b_rows": bset, "b_vacuous": sorted(i for i in bset if vac.get(i)),
            "c_rows": cset, "c_vacuous": sorted(i for i in cset if vac.get(i)),
        }
        keep = [i for i in ids if not vac.get(i)]
        kb = sum(1 for i in keep if a[i])
        kc = sum(1 for i in keep if b[i])
        bb2 = sum(1 for i in keep if a[i] and not b[i])
        cc2 = sum(1 for i in keep if not a[i] and b[i])
        p2, nd2 = mcnemar_exact(bb2, cc2)
        block["net_of_vacuous"] = {
            "n_pairs": len(keep), "n_dropped_vacuous": len(ids) - len(keep),
            "armA_doc_comment": rate(kb, len(keep)),
            "armB_no_doc_comment": rate(kc, len(keep)),
            "b_A_pass_B_fail": bb2, "c_A_fail_B_pass": cc2,
            "n_discordant": nd2, "mcnemar_exact_p": round(p2, 4),
            "can_possibly_reach_p05": nd2 >= need,
        }
    if n:
        dr = ndis / n if ndis else 1.0 / n
        block["power_note"] = {
            "observed_discordant_rate": round(ndis / n, 3),
            "power_at_observed_split": round(
                mcnemar_power(n, cc / n if n else 0, bb / n if n else 0), 3),
            "min_detectable_difference_80pct": min_detectable_difference(n, dr),
        }
    return block


def experiment1(args):
    out = {}
    sets = {
        "n50_distinct": {
            "armA": R("results", "exp1_n50_armA.verified.jsonl"),
            "armB": R("results", "exp1_n50_armB.verified.jsonl"),
            "prov_run": "n50_distinct_T0.0",
            "clustered": False,
            "traces": R("traces", "exp1_n50_armA", "traces.jsonl"),
            "note": "50 distinct problems, one CoT step each. Independent rows.",
        },
        "baseline_50step": {
            "armA": R("results", "exp1_baseline_armA.verified.jsonl"),
            "armB": R("results", "exp1_baseline_armB.verified.jsonl"),
            "prov_run": "baseline_50step_1problem",
            "clustered": True,
            "traces": R("traces", "exp1_baseline_armA", "traces.jsonl"),
            "note": "50 CoT steps of ONE problem "
                    "(math_train_counting_and_probability_408). Rows are "
                    "correlated; a binomial interval understates the width and "
                    "these figures must not be pooled with n50.",
        },
    }
    for name, cfg in sets.items():
        if not (os.path.exists(cfg["armA"]) and os.path.exists(cfg["armB"])):
            out[name] = {"error": "verdict files missing"}
            continue
        # Pair on sample_index: the same dataset row in both arms.
        a = load_arm(cfg["armA"], key="sample_index")
        b = load_arm(cfg["armB"], key="sample_index")
        ids = sorted(set(a) & set(b))
        vac = vacuity_by_sample(cfg["traces"])
        labels = statement_false_ids(cfg["prov_run"], {})
        sf = [i for i in ids if labels.get(i) == "statement_false"]
        nsf = [i for i in ids if labels.get(i) != "statement_false"]

        out[name] = {
            "note": cfg["note"], "clustered": cfg["clustered"],
            "label_source": "results/arithmetic_provenance.json -> %s"
                            % cfg["prov_run"],
            "overall": mcnemar_block(a, b, ids, "all rows", vac),
            "statement_false": mcnemar_block(a, b, sf, "statement_false", vac),
            "not_statement_false": mcnemar_block(a, b, nsf, "not statement_false", vac),
            "vacuous_statements_in_set": sorted(i for i in ids if vac.get(i)),
            "label_counts": dict(collections.Counter(
                labels.get(i, "(passed / unlabelled)") for i in ids)),
        }

        # Free control: arm A is a fresh greedy run of a configuration this repo
        # has already measured. If it does not reproduce, that is a finding
        # about the pipeline, not about the doc comment.
        ref = {"n50_distinct": R("results", "verify3_temp0.0.jsonl"),
               "baseline_50step": R("results", "verification_temp_0.jsonl")}[name]
        if os.path.exists(ref):
            old = {r["sample_index"]: r["outcome"] == "valid" for r in J(ref)}
            shared = [i for i in ids if i in old]
            agree = sum(1 for i in shared if old[i] == a[i])
            out[name]["armA_reproduces_committed_run"] = {
                "reference": os.path.basename(ref),
                "committed": rate(sum(1 for i in shared if old[i]), len(shared)),
                "armA_now": rate(sum(1 for i in shared if a[i]), len(shared)),
                "per_row_agreement": rate(agree, len(shared)),
                "rows_that_flipped": sorted(i for i in shared if old[i] != a[i]),
            }
    return out


# --------------------------------------------------------------------------- #
# Experiment 2 -- best-of-n
# --------------------------------------------------------------------------- #
def per_complete_enough(complete, n_expected):
    """Every problem in the set must be fully verified before a curve is shown."""
    return n_expected > 0 and len(complete) >= n_expected


def experiment2(args):
    out = {}
    # exp_vacuity.json is keyed on the sha256 of the STATEMENT, not on a
    # problem id -- see exp_vacuity.py for why. Look each problem up by hashing
    # its statement, taken from the trace file.
    vac = {}
    _vpath = R("results", "exp_vacuity.json")
    if os.path.exists(_vpath):
        vac = json.load(io.open(_vpath, encoding="utf-8"))

    runs = {
        "formalstep_n50": (R("results", "exp2_n50_k16.verified.jsonl"),
                           "problem_unique_id", "FormalStep",
                           R("traces", "exp2_n50_k16", "traces.jsonl")),
        "stageb_n90": (R("results", "exp2_stageb_k16.verified.jsonl"),
                       "uuid", "StageB",
                       R("results", "exp2_stageb_k16.jsonl")),
    }
    for name, (path, key, pipeline, traces) in runs.items():
        if not os.path.exists(path):
            out[name] = {"error": "verdict file missing"}
            continue
        rows = J(path)
        stmt_h = {}
        if os.path.exists(traces):
            for t in J(traces):
                tk = t.get(key) if t.get(key) is not None else t.get("sample_index")
                stmt_h[tk] = hashlib.sha256(
                    (t.get("formal_statement") or "").strip().encode("utf-8")
                ).hexdigest()
        by = collections.defaultdict(list)
        band = {}
        for r in rows:
            k = r.get(key) if r.get(key) is not None else r.get("sample_index")
            by[k].append(bool(r.get("valid")))
            if r.get("band"):
                band[k] = r["band"]

        # pass@k is only defined against the FULL k samples a problem was
        # given. A problem that is half-verified would enter the estimator with
        # a smaller n and a correspondingly biased c/n, so partial problems are
        # excluded and counted, never silently averaged in.
        want_k = args.k
        complete = {k: v for k, v in by.items() if len(v) >= want_k}
        partial = {k: v for k, v in by.items() if len(v) < want_k}
        n_expected = len(stmt_h) or len(by)
        # A curve built on the problems verified SO FAR is not a curve on the
        # set. Verification walks the trace file in order and the Stage B
        # evalset is ordered easy(30), medium(30), hard(30) -- so a partial run
        # is a run on the easy band, and its pass@k would overstate the set
        # badly. Refuse to emit one until every problem is verified.
        if not per_complete_enough(complete, n_expected):
            out[name] = {
                "error": "verification incomplete: %d of %d problems have all "
                         "%d samples. No pass@k is reported, because "
                         "verification walks the eval set in order and that "
                         "set is ordered by difficulty band, so the verified "
                         "prefix is not a random subset."
                         % (len(complete), n_expected, want_k),
                "problems_complete": len(complete),
                "problems_expected": n_expected,
                "bands_complete": dict(collections.Counter(
                    band.get(k) for k in complete)) if band else None,
            }
            continue
        per = [(len(v), sum(v)) for v in complete.values()]
        curve = pass_curve(per)

        # Vacuity is statement-level, so a problem's k passes share one verdict.
        # The vacuous curve is the same estimator restricted to problems whose
        # goal the probe ladder closes without a proof.
        is_vac = lambda k: bool((vac.get(stmt_h.get(k)) or {}).get("vacuous"))
        per_vac = [(len(v), sum(v)) for k, v in complete.items() if is_vac(k)]
        per_content = [(len(v), sum(v)) for k, v in complete.items() if not is_vac(k)]
        # Reported two ways, because "vacuous pass@k" alone is ambiguous.
        #   expected_vacuous_problems_at_k  how much of the pass set is goals
        #                                   the ladder closes without a proof --
        #                                   an expected COUNT out of all problems
        #   pass@k_contentful               the rate with those goals removed
        # Vacuity is statement-level, so best-of-n cannot manufacture a vacuous
        # pass on a contentful goal; it can only reach more problems, some of
        # which are vacuous. These two lines show exactly how much of the
        # best-of-n gain is that.
        curve_vac = None
        if per_vac:
            curve_vac = {
                "n_vacuous_problems": len(per_vac),
                "expected_vacuous_solved": {
                    "k=%d" % k: round(sum(pass_at_k(n, c, k) for n, c in per_vac), 2)
                    for k in PASS_K},
            }
        curve_content = pass_curve(per_content) if per_content else None

        # Outcome mix across ALL samples, so false-positive gates are visible.
        mix = collections.Counter(r["outcome"] for r in rows)

        entry = {
            "pipeline": pipeline, "n_problems": len(complete),
            "problems_partial_excluded": len(partial),
            "verification_complete": not partial,
            "samples_per_problem": sorted({len(v) for v in by.values()}),
            "total_samples": len(rows),
            "curve": curve,
            "vacuous_curve": curve_vac,
            "curve_contentful_only": curve_content,
            "n_vacuous_problems_in_pass_set": len(per_vac),
            "outcome_mix_all_samples": dict(mix.most_common()),
            "gates": {
                "statement_mismatch": mix.get("statement_mismatch", 0),
                "unsound_axioms": mix.get("unsound_axioms", 0),
                "has_sorry": mix.get("has_sorry", 0),
            },
        }
        if curve.get("pass@1") and curve.get("pass@16"):
            entry["pass16_minus_pass1_pp"] = round(
                curve["pass@16"]["pct"] - curve["pass@1"]["pct"], 1)
        if band:
            entry["by_band"] = {}
            for bn in sorted(set(band.values())):
                sub = [(len(v), sum(v)) for k, v in complete.items()
                   if band.get(k) == bn]
                entry["by_band"][bn] = pass_curve(sub)
        out[name] = entry
    return out


# --------------------------------------------------------------------------- #
# Experiment 3 -- one error-feedback repair attempt
# --------------------------------------------------------------------------- #
def experiment3(args):
    path = R("results", "exp3_repair.verified.jsonl")
    if not os.path.exists(path):
        return {"error": "verdict file missing"}
    rows = J(path)
    n = len(rows)
    fixed = [r for r in rows if r.get("valid")]

    by_pipe = collections.defaultdict(list)
    for r in rows:
        by_pipe[r.get("pipeline") or "?"].append(r)

    out = {
        "set": "the 104 `tactic_mismatch` failures the tactic oracle ran on",
        "one_shot_baseline": {
            "note": "0 by construction -- every row in this set is a failure of "
                    "the one-shot run. Stated so the repair row is never read "
                    "as an improvement on a rate it is not comparable with.",
            "rate": rate(0, n),
        },
        "with_repair_pooled": rate(len(fixed), n),
        "pooling_caveat": "This pooled denominator matches the tactic oracle's "
                          "104 so the two ceilings are like-for-like. It mixes "
                          "two pipelines and must not be quoted as a validity "
                          "rate for either.",
        "by_pipeline": {p: rate(sum(1 for r in v if r.get("valid")), len(v))
                        for p, v in sorted(by_pipe.items())},
        "by_set": {},
        "outcome_mix": dict(collections.Counter(r["outcome"] for r in rows).most_common()),
        "gates": {
            "statement_mismatch": sum(1 for r in rows if r["outcome"] == "statement_mismatch"),
            "unsound_axioms": sum(1 for r in rows if r["outcome"] == "unsound_axioms"),
        },
        "repaired_ids": [{"set": r.get("set"), "id": r.get("id"),
                          "lean_tactic": r.get("lean_tactic")} for r in fixed],
    }
    sets = collections.defaultdict(list)
    for r in rows:
        sets[r.get("set") or "?"].append(r)
    for s, v in sorted(sets.items()):
        out["by_set"][s] = rate(sum(1 for r in v if r.get("valid")), len(v))

    # The oracle ran the same 104. Its number is a CEILING under a fixed tactic
    # ladder, not a rate any prover attains; carried here only so the report can
    # place repair against it without re-deriving it.
    orc = R("results", "tactic_oracle.json")
    if os.path.exists(orc):
        out["oracle_reference"] = {
            "file": "results/tactic_oracle.json",
            "substantive_recoveries": "3/104 = 2.9% [1.0-8.1]",
            "note": "Upper bound if tactic selection were perfect. Never a "
                    "validity figure and never quoted alone.",
        }
    return out


# Recorded here rather than in prose so the report cannot drift from it.
RUN = {
    "generation commit": "2f25feb659385719112980c4b8e64f6104157fc2 "
                         "(branch exp/gpu-tactic-recovery, tree clean)",
    "seed": "20260830, on every run; recorded in every run_meta.json and in "
            "every trace record",
    "model": "Goedel-LM/Goedel-Prover-SFT, fp16, transformers 4.46.3 "
             "(pinned), torch 2.7.0",
    "sampling": "T=0.0 greedy for experiments 1 and 3; T=0.7 with top_p=0.95 "
                "(unchanged) for experiment 2",
    "generations": "2,494 total: 200 (exp 1) + 800 + 1,440 (exp 2) + 104 (exp 3)",
    "hardware": "1x Lambda A100-SXM4-40GB, us-east-1, $1.99/h",
    "instance launched": "2026-08-30T21:07:34Z",
    "last generation finished": "2026-08-30T23:08:55Z",
    "instance terminated": "2026-08-30T23:10:39Z, 1m44s after the last "
                           "generation; confirmed by the Lambda API returning "
                           "no running instances",
    "GPU wall clock": "2.05 h",
    "cost": "$4.08 of the $25 cap",
    "verification": "local, CPU-only, pinned Lean v4.32.0 / Mathlib v4.32.0. "
                    "Lean never ran on the GPU box, which is why the instance "
                    "could be released the moment generation ended.",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=R("results", "GPU_TACTIC_RECOVERY.json"))
    ap.add_argument("--k", type=int, default=16,
                    help="Samples per problem the best-of-n runs were given. A "
                         "problem with fewer verified is excluded from pass@k.")
    args = ap.parse_args()

    doc = {
        "generated_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ",
                                                     __import__("time").gmtime()),
        "run": RUN,
        "experiment1_doc_comment_ablation": experiment1(args),
        "experiment2_best_of_n": experiment2(args),
        "experiment3_error_feedback_repair": experiment3(args),
    }
    json.dump(doc, io.open(args.out, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(json.dumps(doc, indent=2, ensure_ascii=False)[:6000])
    print("\nwrote %s" % args.out)


if __name__ == "__main__":
    main()
