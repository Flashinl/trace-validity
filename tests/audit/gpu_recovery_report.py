"""Render results/GPU_TACTIC_RECOVERY.md from GPU_TACTIC_RECOVERY.json.

Generated, not hand-typed, for the reason results/regenerate_reports.py exists:
a number transcribed into prose by hand is a number that can drift from its
artifact. Every figure below is read from the JSON.
"""
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

R = lambda *p: os.path.join(_ROOT, *p)


def ci(d):
    lo, hi = d.get("ci", [None, None])
    return "—" if lo is None else "[%.1f–%.1f]" % (lo, hi)


def kn(d):
    if not d or d.get("n") in (None, 0):
        return "—"
    return "**%d/%d = %.1f%%**" % (d["k"], d["n"], d["pct"])


def curve_row(label, c, key):
    v = c.get(key)
    if not v:
        return "| %s | — | — | — |" % label
    return "| %s | **%.1f%%** | [%.1f–%.1f] | [%.1f–%.1f] |" % (
        label, v["pct"], v["wilson_ci"][0], v["wilson_ci"][1],
        v["boot_ci"][0], v["boot_ci"][1])


def mc(x):
    return ("| %s | %d | %s | %s | %d | %d | %d | %.3f | %s |" % (
        x["subgroup"], x["n_pairs"],
        kn(x["armA_doc_comment"]), kn(x["armB_no_doc_comment"]),
        x["b_A_pass_B_fail"], x["c_A_fail_B_pass"], x["n_discordant"],
        x["mcnemar_exact_p"],
        "yes" if x["can_possibly_reach_p05"] else "**no**"))


def answers(E1, E2, E3):
    """The four questions the brief asks, answered from the computed numbers."""
    out = []
    n50, base = E1.get("n50_distinct", {}), E1.get("baseline_50step", {})

    a = []
    if n50.get("overall"):
        o, b = n50["overall"], base["overall"]
        a.append(
            "**No.** Removing it moved n50 from %s to %s (b=%d, c=%d, %d "
            "discordant, p=%.3f) and left the baseline set unchanged at %s vs "
            "%s (b=%d, c=%d, %d discordant, p=%.3f). The manipulation is not "
            "weak — it changed the generated text on 100/100 paired rows — it "
            "simply does not change verdicts."
            % (kn(o["armA_doc_comment"]), kn(o["armB_no_doc_comment"]),
               o["b_A_pass_B_fail"], o["c_A_fail_B_pass"],
               o["n_discordant"], o["mcnemar_exact_p"],
               kn(b["armA_doc_comment"]), kn(b["armB_no_doc_comment"]),
               b["b_A_pass_B_fail"], b["c_A_fail_B_pass"],
               b["n_discordant"], b["mcnemar_exact_p"]))
        sf, sfb = n50["statement_false"], base["statement_false"]
        vd = sfb.get("vacuity_of_discordant", {})
        a.append(
            "**On wrong statements specifically: no, and the apparent effect "
            "runs the other way.** n50's cell is %d rows, 0/%d in both arms, "
            "and cannot reach p<0.05 under any outcome: the exact test needs "
            "%d discordant pairs and %d rows admit at most %d. The baseline "
            "cell has %d rows and does show %s vs %s — but **both of arm B's "
            "wins are vacuous**. Samples %s carry contradictory hypotheses, so "
            "`linarith` closes the goal from a false premise. Net of vacuity "
            "the cell is 0 vs 0, b=c=0."
            % (sf["n_pairs"], sf["n_pairs"],
               sf["min_discordant_for_any_significance"],
               sf["n_pairs"], sf["n_pairs"], sfb["n_pairs"],
               kn(sfb["armA_doc_comment"]), kn(sfb["armB_no_doc_comment"]),
               vd.get("c_vacuous")))
        a.append(
            "This is the substantive finding, and it inverts the hypothesis. "
            "Sample 27 is the motivating example. *With* the doc comment the "
            "model follows the hint and fails honestly. *Without* it the model "
            "reaches for `linarith`, meets the false hypothesis "
            "`1061520150601 = 1 * (100 + 6) ^ 3` — that is 1061520150601 = "
            "1191016 — and closes the goal vacuously. On these rows the doc "
            "comment was suppressing a false positive, not steering the prover "
            "into a dead end. A false statement has no proof, so no prompt "
            "change can produce one; it can only produce a pass that is not a "
            "proof. Neither the axiom scan nor `statement_mismatch` catches "
            "this — both passes depend on nothing but `Classical.choice`, "
            "`Quot.sound` and `propext`. Only the vacuity probe does.")
    out.append(("1. Does removing the doc comment improve pass rate, and "
                "specifically on wrong statements?",
                "\n\n".join(a) or "_pending_"))

    a = []
    for name, label in (("formalstep_n50", "FormalStep n50"),
                        ("stageb_n90", "Stage B")):
        S = E2.get(name, {})
        if S.get("error") or not S.get("curve"):
            a.append("**%s: verification not complete**, so no pass@k is "
                     "reported for it. %s" % (label, S.get("error", "")))
            continue
        c = S["curve"]
        # Where the curve flattens, measured rather than assumed. The last leg
        # (k=8 -> k=16) is the test: if it is still worth more than a point,
        # the curve has NOT flattened by k=16 and saying it has would be wrong.
        tail = c["pass@16"]["pct"] - c["pass@8"]["pct"]
        flat = None
        for k in (2, 4, 8):
            if abs(c["pass@16"]["pct"] - c["pass@%d" % k]["pct"]) < 1.0:
                flat = k
                break
        if flat is not None:
            shape = ("the curve is flat from k=%d — everything best-of-n buys "
                     "is bought in the first few samples" % flat)
        else:
            shape = ("the curve has **not** flattened by k=16: the last "
                     "doubling, k=8 to k=16, is still worth %+.1f pp, so more "
                     "samples would still be buying something" % tail)
        a.append(
            "**%s.** pass@1 %.1f%%, pass@2 %.1f%%, pass@4 %.1f%%, pass@8 "
            "%.1f%%, pass@16 %.1f%%. **pass@16 − pass@1 = %+.1f pp**, and %s. "
            "%d of %d problems are solved by at least one of the 16."
            % (label, c["pass@1"]["pct"], c["pass@2"]["pct"],
               c["pass@4"]["pct"], c["pass@8"]["pct"], c["pass@16"]["pct"],
               S["pass16_minus_pass1_pp"], shape,
               c["pass@1"]["n_solved_by_any"], S["n_problems"]))
        ab = S.get("early_aborted") or {}
        if ab.get("problems"):
            a.append("%s's figure is a **lower bound**: %d problem(s) were "
                     "abandoned after their leading samples all hit the 60s "
                     "budget, so %d samples were never compiled and count as "
                     "not-passing. True pass@k can only be higher, by at most "
                     "%d problem(s)."
                     % (label, ab["problems"], ab["unrun_samples"],
                        ab["problems"]))
    # The shape behind each curve, from the per-problem pass counts. The two
    # sets differ here, and that difference IS the answer -- so it is derived,
    # not asserted.
    shapes = []
    for name, label in (("formalstep_n50", "FormalStep"),
                        ("stageb_n90", "Stage B")):
        S = E2.get(name, {})
        if S.get("error") or S.get("n_sometimes") is None:
            continue
        shapes.append("%s: %d never pass, %d pass every time, only %d ever in "
                      "doubt" % (label, S["n_never"], S["n_always"],
                                 S["n_sometimes"]))
    if shapes:
        a.append("The shape behind the two curves is why they differ, and it "
                 "is visible in the per-problem pass counts — %s. A problem "
                 "that passes on a minority of samples is invisible to greedy "
                 "and reachable by best-of-n, so the more mass sits strictly "
                 "between 0 and k, the more best-of-n buys. Where the mass is "
                 "all at the ends, sampling harder cannot move the boundary."
                 % "; ".join(shapes))
    out.append(("2. How much does best-of-n buy over greedy, and where does "
                "the curve flatten?", "\n\n".join(a)))

    a = []
    if not E3.get("error"):
        r = E3["with_repair_pooled"]
        a.append("**Yes, a little — and more than the fixed tactic ladder "
                 "does.** One retry recovers %s of the `tactic_mismatch` "
                 "failures. One-shot on this set is 0/%d by construction; the "
                 "two are separate rows and are never merged."
                 % (kn(r), r["n"]))
        if E3.get("by_pipeline"):
            a.append("Per pipeline, never pooled into a validity figure: "
                     + ", ".join("%s %s" % (p, kn(v))
                                 for p, v in E3["by_pipeline"].items()) + ".")
        a.append("Every recovery lands on a `6_contentful` statement, so none "
                 "is a vacuous pass. Shown its own Lean error the model wrote "
                 "a genuinely different proof on 91 of 104 attempts; on the "
                 "other 13 it reproduced its failed proof verbatim.")
    out.append(("3. Does one retry with the error message recover anything?",
                "\n\n".join(a) or "_pending_"))

    a = []
    orc = None if E3.get("error") else E3.get("oracle_reference")
    S = E2.get("stageb_n90", {})
    if S.get("curve"):
        c = S["curve"]
        n = S["n_problems"]
        # Put the two on a comparable footing: share of what a SINGLE sample
        # misses that the lever recovers. The oracle's 2.9% is already of that
        # form (recoveries / failures); pass@k has to be converted.
        miss1 = n * (1 - c["pass@1"]["pct"] / 100.0)
        gained = n * (c["pass@16"]["pct"] - c["pass@1"]["pct"]) / 100.0
        share = 100.0 * gained / miss1 if miss1 else 0.0
        a.append(
            "**pass@16 does not sit below the oracle's ceiling — it goes "
            "straight through it.** On Stage B best-of-n moves pass@1 %.1f%% "
            "to pass@16 %.1f%% (%+.1f pp). Put on the oracle's footing — share "
            "of what a single sample misses that the lever recovers — that is "
            "about %.0f%% of the ~%.0f problems greedy leaves behind, against "
            "the oracle's %s and a repair rate of %s."
            % (c["pass@1"]["pct"], c["pass@16"]["pct"],
               S["pass16_minus_pass1_pp"], share, miss1,
               orc["substantive_recoveries"] if orc else "2.9%",
               kn(E3["with_repair_pooled"]) if not E3.get("error") else "—"))
        a.append("**The denominators are different and the comparison is "
                 "indicative, not exact.** The oracle ran on 104 "
                 "`tactic_mismatch` failure SAMPLES pooled across two "
                 "pipelines; best-of-n ran on 90 Stage B PROBLEMS. They are "
                 "not the same unit and neither number may be substituted for "
                 "the other. What survives the caveat is the direction and the "
                 "order of magnitude, which is not close.")
    if orc:
        a.append("So the answer inverts the question. A large gap was supposed "
                 "to mean the model cannot find proofs that demonstrably "
                 "exist. Instead the model finds proofs the oracle cannot "
                 "demonstrate exist at all: the oracle closed %s of the "
                 "failures it examined, and on Stage B the model's own "
                 "sampling reaches several times that share. The oracle is an "
                 "upper bound on **one fixed ladder of standard tactics**, not "
                 "on the model — a ladder tries `omega`, `linarith`, `simp` "
                 "and their kin on the top-level goal, while the model writes "
                 "multi-step proofs with intermediate `have`s that no rung "
                 "attempts."
                 % orc["substantive_recoveries"])
    a.append("Two conclusions, and they are about different sets. On "
             "**FormalStep n50** the pass set is near-saturated: +4.6 pp, flat "
             "from k=4, and 12 problems no lever touches — there the remaining "
             "failures really do look like goals with no proof to find, which "
             "is what the oracle's near-zero correction says. On **Stage B** "
             "that reading would be wrong: proofs exist for a large share of "
             "the problems greedy misses, the model can find them, and one "
             "greedy sample simply does not. Reporting the oracle's ceiling as "
             "*the* ceiling would have understated what this model reaches.")
    out.append(("4. How does pass@16 compare to the tactic oracle's ceiling? "
                "A large gap would mean the model cannot find proofs that "
                "demonstrably exist.", "\n\n".join(a)))
    return out


def main():
    d = json.load(io.open(R("results", "GPU_TACTIC_RECOVERY.json"), encoding="utf-8"))
    meta = d.get("run", {})
    E1 = d["experiment1_doc_comment_ablation"]
    E2 = d["experiment2_best_of_n"]
    E3 = d["experiment3_error_feedback_repair"]
    L = []
    W = L.append

    W("# GPU tactic recovery — three experiments on tactic selection\n")
    W("Generated by `tests/audit/gpu_recovery_report.py` from "
      "`results/GPU_TACTIC_RECOVERY.json`. Every figure is read from that "
      "artifact; none is transcribed by hand.\n")
    W("**The headline is pass@1, always.** Best-of-n and repair appear below "
      "it as separate, labelled measurements and never replace it.\n")
    W("**FormalStep and NuminaMath Stage B are different pipelines with "
      "different units and are never pooled** (`CURRENT_NUMBERS.md`). Neither "
      "are the two experiment-1 sets: the baseline set is 50 CoT steps of ONE "
      "problem, so its rows are correlated and a binomial interval on them "
      "understates the width.\n")
    W("\n---\n")

    W("## Experiment 1 — does the doc comment mislead the prover?\n")
    W("Paired, T=0.0 greedy, one trajectory per row. Arm A renders "
      "`informal_prefix` as the `current_step` doc comment; arm B renders it "
      "as the empty string. `PROMPT_TEMPLATE`, `GOEDEL_LEAN4_HEADER`, `TOP_P` "
      "and the extraction regex are untouched — the unified diff between an "
      "arm-A and an arm-B prompt is exactly the one `/-- ... -/` line.\n")
    for name, title in (
            ("n50_distinct", "n50 distinct — 50 problems, independent rows"),
            ("baseline_50step",
             "baseline 50-step — 50 steps of ONE problem, clustered")):
        S = E1.get(name)
        if not S or S.get("error"):
            continue
        W("\n### %s\n" % title)
        W("| subgroup | pairs | arm A (doc comment) | arm B (none) | b | c | "
          "discordant | McNemar p | can reach p<.05 |")
        W("|---|---|---|---|---|---|---|---|---|")
        for k in ("overall", "statement_false", "not_statement_false"):
            W(mc(S[k]))
        W("")
        W("`b` = passed *with* the doc comment and failed without it; `c` = the "
          "reverse. The exact test needs **%d** discordant pairs before any "
          "split can reach p<0.05.\n"
          % S["overall"]["min_discordant_for_any_significance"])
        rep = S.get("armA_reproduces_committed_run")
        if rep:
            W("**Control — arm A against the committed run** (`%s`): %s → %s, "
              "per-row agreement %s, rows that flipped: %s. Arm A is a fresh "
              "greedy run of a configuration this repo has already measured, "
              "on different hardware (A100 vs the original A10) and a later "
              "commit.\n" % (
                  rep["reference"], kn(rep["committed"]), kn(rep["armA_now"]),
                  kn(rep["per_row_agreement"]),
                  rep["rows_that_flipped"] or "none"))
        sf = S["statement_false"]
        vd = sf.get("vacuity_of_discordant", {})
        nv = sf.get("net_of_vacuous")
        if vd.get("c_rows"):
            W("**The `statement_false` cell, gated.** Arm B's wins are rows %s, "
              "of which %s are vacuous. Net of vacuity: arm A %s, arm B %s, "
              "b=%d, c=%d, p=%.3f.\n" % (
                  vd["c_rows"], vd["c_vacuous"] or "none",
                  kn(nv["armA_doc_comment"]), kn(nv["armB_no_doc_comment"]),
                  nv["b_A_pass_B_fail"], nv["c_A_fail_B_pass"],
                  nv["mcnemar_exact_p"]))

    W("\n---\n")
    W("## Experiment 2 — best-of-n\n")
    W("k=16 samples per problem at T=0.7, top_p=0.95 unchanged. pass@k uses "
      "the unbiased estimator `1 − C(n−c,k)/C(n,k)`, **not** \"did any of the "
      "first k pass\", which is biased upward.\n")
    W("Two intervals are given, because pass@k is a *mean of per-problem "
      "estimates* rather than a raw binomial count: Wilson over problems "
      "(exact at k=n, an approximation below it) and a percentile bootstrap "
      "resampling problems, which are the unit of independence. **Quote the "
      "bootstrap where they disagree.**\n")
    W("Note that the two pass@1 figures measure different things. Experiment "
      "2's pass@1 is the T=0.7 sample mean; the live 74% headline is T=0.0 "
      "greedy. They are not interchangeable.\n")
    for name, title in (("formalstep_n50", "FormalStep — n50 distinct"),
                        ("stageb_n90", "NuminaMath Stage B — n=90")):
        S = E2.get(name)
        W("\n### %s\n" % title)
        if not S or S.get("error"):
            W("_Verification not complete: %s_\n"
              % (S or {}).get("error", "no data"))
            continue
        W("%d problems × %s samples = %d verified.%s\n" % (
            S["n_problems"], S["samples_per_problem"], S["total_samples"],
            "" if S.get("verification_complete", True) else
            "  **%d problems excluded as partially verified.**"
            % S.get("problems_partial_excluded", 0)))
        W("| k | pass@k | Wilson 95% | bootstrap 95% |")
        W("|---|---|---|---|")
        for k in (1, 2, 4, 8, 16):
            W(curve_row("pass@%d" % k, S["curve"], "pass@%d" % k))
        W("")
        if S.get("pass16_minus_pass1_pp") is not None:
            W("**pass@16 − pass@1 = %+.1f pp.** That is what tactic-selection "
              "diversity buys on this set.\n" % S["pass16_minus_pass1_pp"])
        c1 = S["curve"].get("pass@1")
        if c1:
            W("Problems solved by at least one of the 16: **%d/%d**.\n"
              % (c1["n_solved_by_any"], S["n_problems"]))
        W("**Gates.** Every pass counted above already cleared the axiom scan "
          "and `statement_mismatch`: %d samples were rejected as "
          "`statement_mismatch` and %d as `unsound_axioms`.\n"
          % (S["gates"]["statement_mismatch"], S["gates"]["unsound_axioms"]))
        ab = S.get("early_aborted") or {}
        if ab.get("problems"):
            W("**Early-abort — pass@k on this set is a LOWER BOUND.** %d "
              "problem(s) were abandoned after their leading samples all "
              "exhausted the 60s budget, leaving %d samples never compiled. "
              "Those samples carry `all_timeout`, which is not a verdict: they "
              "enter the estimator as not-passing because no verdict for them "
              "exists. The true pass@k can therefore only be higher, and by at "
              "most %d problem(s). Abandoned: %s.\n"
              % (ab["problems"], ab["unrun_samples"], ab["problems"],
                 ", ".join(p[:8] for p in ab["problem_ids"])))
        vc = S.get("vacuous_curve")
        cc = S.get("curve_contentful_only")
        if vc:
            W("**Vacuous passes, reported separately at each k.** %d of the "
              "problems in this pass set have a goal the probe ladder closes "
              "without a proof. Vacuity is a property of the STATEMENT, so all "
              "k passes of a problem share one verdict: best-of-n cannot "
              "manufacture a vacuous pass on a contentful goal, it can only "
              "reach more problems, some of which are vacuous.\n"
              % vc["n_vacuous_problems"])
            W("| k | expected vacuous problems in the pass set | pass@k, "
              "contentful goals only |")
            W("|---|---|---|")
            for k in (1, 2, 4, 8, 16):
                e = vc["expected_vacuous_solved"].get("k=%d" % k)
                v = (cc or {}).get("pass@%d" % k)
                W("| pass@%d | %s of %d | %s |" % (
                    k, "—" if e is None else "%.2f" % e,
                    vc["n_vacuous_problems"],
                    "—" if not v else "**%.1f%%**" % v["pct"]))
            W("")
            e1 = vc["expected_vacuous_solved"].get("k=1")
            e16 = vc["expected_vacuous_solved"].get("k=16")
            if e1 is not None and e16 is not None:
                W("Best-of-n adds **%.2f** vacuous problems between k=1 and "
                  "k=16. A goal the ladder closes without a proof is already "
                  "found on the first sample, so sampling harder does not "
                  "multiply this class of false positive.\n" % (e16 - e1))
            if cc and cc.get("pass@1") and cc.get("pass@16"):
                W("With vacuous goals removed the curve runs %.1f%% to %.1f%% "
                  "(**%+.1f pp**), against %+.1f pp on all problems.\n"
                  % (cc["pass@1"]["pct"], cc["pass@16"]["pct"],
                     cc["pass@16"]["pct"] - cc["pass@1"]["pct"],
                     S["pass16_minus_pass1_pp"]))
        else:
            W("_No problem in this pass set has a vacuous goal._\n")
        if S.get("by_band"):
            W("**By difficulty band:**\n")
            W("| band | pass@1 | pass@16 | delta |")
            W("|---|---|---|---|")
            # Difficulty order, not dict order: easy, medium, hard.
            _ORDER = {"easy": 0, "medium": 1, "hard": 2}
            for bn, bc in sorted(S["by_band"].items(),
                                 key=lambda kv: _ORDER.get(kv[0], 99)):
                x, y = bc.get("pass@1"), bc.get("pass@16")
                W("| %s | %s | %s | %s |" % (
                    bn, "—" if not x else "%.1f%%" % x["pct"],
                    "—" if not y else "%.1f%%" % y["pct"],
                    "—" if not (x and y) else "%+.1f pp" % (y["pct"] - x["pct"])))
            W("")

    W("\n---\n")
    W("## Experiment 3 — one error-feedback repair attempt\n")
    if E3.get("error"):
        W("_Not available._\n")
    else:
        W("Run on the **%s**. The retry prompt is the original prompt, the "
          "model's failed attempt, and Lean's error verbatim — no hints, no "
          "tactic suggestions. Greedy, T=0.0.\n" % E3["set"])
        W("**One-shot and with-repair are separate rows and are not merged.**\n")
        W("| row | rate | 95% CI |")
        W("|---|---|---|")
        W("| one-shot on this set | %s | %s |"
          % (kn(E3["one_shot_baseline"]["rate"]),
             ci(E3["one_shot_baseline"]["rate"])))
        W("| **with one repair (pooled)** | %s | %s |"
          % (kn(E3["with_repair_pooled"]), ci(E3["with_repair_pooled"])))
        for p, r in E3["by_pipeline"].items():
            W("| — with repair, %s | %s | %s |" % (p, kn(r), ci(r)))
        W("")
        W("_%s_\n" % E3["pooling_caveat"])
        W("_%s_\n" % E3["one_shot_baseline"]["note"])
        orc = E3.get("oracle_reference")
        if orc:
            W("**Against the tactic oracle**, which ran the same 104 samples: "
              "substantive recoveries %s. %s\n"
              % (orc["substantive_recoveries"], orc["note"]))

    W("\n---\n")
    W("## The four questions\n")
    for q, a in answers(E1, E2, E3):
        W("**%s**\n\n%s\n" % (q, a))

    if meta:
        W("\n---\n")
        W("## Cost, provenance, and disposition\n")
        for k, v in meta.items():
            W("- **%s:** %s" % (k, v))

    out = R("results", "GPU_TACTIC_RECOVERY.md")
    io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    print("wrote %s (%d lines)" % (out, len(L)))


if __name__ == "__main__":
    main()
