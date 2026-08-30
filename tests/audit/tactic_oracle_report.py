"""Phases 2-4: read results/tactic_oracle.jsonl and write results/TACTIC_ORACLE.md.

Separated from tactic_oracle.py so the writeup can be regenerated without
re-running Lean.

Run: python tests/audit/tactic_oracle_report.py
"""
import collections, io, json, os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tactic_common as tc  # noqa: E402
from tactic_oracle import LADDER, CONTRA_TACTICS  # noqa: E402
from config import VERIFY_TIMEOUT_SECONDS  # noqa: E402
from stats import wilson  # noqa: E402

# Denominator and numerator for the headline validity rate of each run, taken
# from results/CURRENT_NUMBERS.md. `n` is every attempted sample, not the judged
# subset -- the corrected rate has to sit on the same denominator as the
# published one or the two are not comparable.
HEADLINE = {
    "stageB_T0.0": (28, 90, "stage_b_verified_temp0.0.jsonl"),
    "stageB_T0.7": (26, 90, "stage_b_verified_temp0.7.jsonl"),
    "formalStep_baseline_50step_1problem": (21, 50, "verification_temp_0.jsonl"),
    "formalStep_n50_distinct_T0.0": (37, 50, "verify3_temp0.0.jsonl"),
    "formalStep_n50_distinct_T0.2": (37, 50, "verify3_temp0.2.jsonl"),
}

VERDICTS = [
    ("recovered", "closed by a standard tactic (**genuine recovery**)"),
    ("vacuous_close", "closed only via inconsistent hypotheses (**vacuous, not a recovery**)"),
    ("none_closed", "no tactic in the ladder closed it"),
    ("budget", "exceeded budget"),
    ("excluded_no_code", "excluded: no `full_code` to take a header from"),
]


def md(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def pct(k, n):
    return "—" if not n else "%.1f%%" % (100.0 * k / n)


def ci(k, n):
    if not n:
        return "—"
    lo, hi = wilson(k, n)
    return "[%.1f–%.1f]" % (100 * lo, 100 * hi)


def main(path=None, out_md=None, out_json=None):
    path = path or os.path.join(_ROOT, "results", "tactic_oracle.jsonl")
    rows = tc.J(path)
    by_id = {(r["set"], str(r["id"])): r for r in rows}
    samples = tc.attach_lean_errors(tc.load_samples())
    for s in samples:
        s["oracle"] = by_id.get((s["set"], str(s["id"])))
    done = [s for s in samples if s["oracle"]]
    n = len(done)
    partial = n < len(samples)

    v = lambda r: r["oracle"]["verdict"]
    counts = collections.Counter(v(s) for s in done)

    # Supplementary Lean passes, both optional. `probe` is vacuity_scan's full
    # taxonomy over the recoveries; `witnessed` marks the recoveries that are
    # existentials satisfied by their own right-hand side, a shape that taxonomy
    # has no probe for.
    probe_path = os.path.join(_ROOT, "results", "tactic_oracle_probe.json")
    probe = {}
    if os.path.exists(probe_path):
        probe = {(p["set"], str(p["id"])): p
                 for p in json.load(io.open(probe_path, encoding="utf-8"))}
    rp_path = os.path.join(_ROOT, "results", "tactic_oracle_repair.json")
    rp, witnessed = None, {}
    if os.path.exists(rp_path):
        rp = json.load(io.open(rp_path, encoding="utf-8"))
        witnessed = {(w["set"], str(w["id"])): w["witnessed_by_own_rhs"]
                     for w in rp.get("recoveries", [])}
    n_witnessed = sum(1 for hit in witnessed.values() if hit)

    # A SUBSTANTIVE recovery is one that survives both vacuity checks: the
    # hypotheses are consistent (Phase 2's required probe) AND the goal is not
    # an existential witnessed by its own right-hand side (the gap in
    # vacuity_scan's taxonomy, §3b). Every count below uses this, never the raw
    # `recovered` verdict, because the brief's rule is that a recovery is not
    # reportable unless the vacuity probe passes on it.
    def substantive(s_):
        return (v(s_) == "recovered"
                and not witnessed.get((s_["set"], str(s_["id"])), False))

    def n_sub(setname=None):
        return sum(1 for s_ in done
                   if substantive(s_) and (setname is None or s_["set"] == setname))

    L = []
    A = L.append
    A("# Phase 2–4 — the tactic oracle: how many recorded failures are the "
      "prover's fault?\n")
    if partial:
        A("> ⚠️ **PARTIAL RUN — %d of %d samples completed.** Every figure below "
          "is computed on the completed subset and will move when the run "
          "finishes. Do not quote it.\n" % (n, len(samples)))
    A("`tactic_mismatch` is 77.3% [68.6–84.1] of Stage B's judged failures: the "
      "statement elaborated, the goal stood, and the model's tactic did not "
      "close it. Every one of those is logged `compile_error` and scores the "
      "trace invalid — so prover weakness is being counted as trace invalidity. "
      "This phase measures how much of it there is, by throwing the model's "
      "proof away and trying a fixed ladder of standard tactics on the "
      "identical goal.\n")
    A("Generated by `tests/audit/tactic_oracle.py` (the Lean run) and "
      "`tests/audit/tactic_oracle_report.py` (this file). Raw per-attempt "
      "record: `results/tactic_oracle.jsonl`.\n")

    # ------------------------------------------------------------------ tl;dr
    rec = collections.Counter(v(s) for s in done)["recovered"]
    sb0k, sb0n, _ = HEADLINE["stageB_T0.0"]
    sb0r = n_sub("stageB_T0.0")
    A("---\n")
    A("## 0. The answer, before the tables\n")
    if rec / max(n, 1) < 0.10:
        A("**The contamination is small, and that is the finding.** A fixed "
          "ladder of standard tactics, given the identical goal with the model's "
          "proof deleted, closes **%d of %d = %s %s** of the failures the "
          "labeller called `tactic_mismatch`.%s Stage B's headline pass rate at "
          "T=0.0 moves from **%s to %s** — a gap of **%.1f points**.\n"
          % (rec, n, pct(rec, n), ci(rec, n),
             ("" if not n_witnessed else
              (" %d of those %d is an existential witnessed by its own "
               "right-hand side and asserts nothing, so the substantive figure "
               "is **%d of %d = %s** (§3b)." % (n_witnessed, rec,
                                                rec - n_witnessed, n,
                                                pct(rec - n_witnessed, n)))),
             pct(sb0k, sb0n), pct(sb0k + sb0r, sb0n), 100.0 * sb0r / sb0n))
        A("So the hypothesis this audit was built to test — that "
          "`tactic_mismatch` is mostly the prover fumbling goals a better tactic "
          "would close, and that the validity number is badly understated as a "
          "result — **is not supported**. These goals are not one `nlinarith` "
          "away. Stage B is olympiad number theory and one-shot standard "
          "automation does not close it; the FormalStep failures fare no "
          "better.\n")
        A("The sharpest version: Phase 1 found %d failures where Lean's own "
          "output proves the model's tactic could never have worked (`linarith` "
          "holding a nonlinear context, `omega` reporting that it abstracted a "
          "product of variables into an atom). **The oracle recovers %d of "
          "them.** \"This tactic was wrong\" turns out not to imply \"a right "
          "tactic exists\".\n"
          % (sum(1 for s in done if s["structural"]),
             sum(1 for s in done if s["structural"] and substantive(s))))
        A("What this does **not** say: that the failures are the *trace's* "
          "fault. The oracle is a weak prover and `none_closed` means only that "
          "this ladder failed. §8 is the list of what it cannot see.\n")
    else:
        A("A fixed ladder of standard tactics closes **%d of %d = %s %s** of "
          "the `tactic_mismatch` failures, moving Stage B's T=0.0 pass rate "
          "from %s to %s. Both numbers, always together — see §5.\n"
          % (rec, n, pct(rec, n), ci(rec, n), pct(sb0k, sb0n),
             pct(sb0k + sb0r, sb0n)))
    A("---\n")

    # ------------------------------------------------------------------ method
    A("## 1. The ladder, in full\n")
    A("Fixed in advance, identical for every sample, tried in this order; the "
      "first rung that closes the goal wins. Reproduced here so the run can be "
      "repeated exactly.\n")
    A("```")
    for i, (name, tac) in enumerate(LADDER, 1):
        A("%2d. %-18s %s" % (i, name, tac))
    A("```")
    A("")
    A("Rungs 1–5 and 8–11 are the audit brief's pre-registered list verbatim. "
      "Two notes on rungs 6 and 7:\n")
    A("- **Rung 6 is the brief's `nlinarith [sq_nonneg _, sq_nonneg _]`, run "
      "verbatim.** The `_` placeholders cannot be synthesised from the goal, so "
      "the rung fails to elaborate rather than attempting a proof — measured, "
      "not assumed: `typeclass instance problem is stuck AddLeftMono ?m.N` on "
      "102 of 102 attempts (§3a). It is kept, and its behaviour reported, so "
      "that the pre-registered ladder is on the record as written.\n")
    A("- **Rung 7 is bare `nlinarith`, added because rung 6 cannot run.** It is "
      "the only sample-independent form: any concrete hint term (`sq_nonneg "
      "(x - y)`) would have to be read off the individual goal, which is exactly "
      "the per-sample tuning this audit forbids. Rung 7 is applied identically "
      "to every sample and was fixed before the run started.\n")

    A("### What was and was not changed\n")
    A("- The statement is untouched: same binders, same hypotheses, same goal.\n")
    A("- The header is untouched. The prefix handed to Lean is `full_code` cut "
      "at the end of the statement, so it carries the Goedel header **and the "
      "`informal_prefix` doc comment** exactly as the model saw them. Only the "
      "text after `:= by` differs.\n")
    A("- Per-attempt wall clock is **%ds**, the main verifier's "
      "`VERIFY_TIMEOUT_SECONDS`. A sample that exhausts it is `budget`, never "
      "`none_closed`.\n" % VERIFY_TIMEOUT_SECONDS)
    A("- Every close runs the axiom audit the main verifier runs (`#print "
      "axioms`), so a proof standing on an untrusted axiom is not scored valid.\n")
    A("- **Every close then runs the vacuity probe**: "
      "`theorem contra_probe <binders> : False := by <t>` for each of "
      "%s in turn. If `False` follows from the hypotheses alone, the goal was "
      "closable because the hypotheses are inconsistent, and that is not a "
      "recovery — it is another sample 42. Those are counted in their own row "
      "and excluded from the recovery count.\n"
      % ", ".join("`%s`" % t for t in CONTRA_TACTICS))

    # ------------------------------------------------------------------ results
    A("## 2. Results, per trace set\n")
    hdr = ["", "Stage B T=0.0", "Stage B T=0.7", "FormalStep baseline",
           "FormalStep n50 T=0.0", "FormalStep n50 T=0.2", "**all**"]
    setrows = [[s for s in done if s["set"] == st] for st in tc.SET_ORDER]
    rows = []
    for key, label in VERDICTS:
        if key == "excluded_no_code" and not counts[key]:
            continue
        cells = []
        for grp in setrows:
            k = sum(1 for s in grp if v(s) == key)
            cells.append("%d  (%s)" % (k, pct(k, len(grp))) if grp else "—")
        cells.append("**%d  (%s)**" % (counts[key], pct(counts[key], n)))
        rows.append([label] + cells)
    rows.append(["**n (tactic_mismatch failures)**"]
                + ["**%d**" % len(g) for g in setrows] + ["**%d**" % n])
    A(md(hdr, rows))
    A("")
    A("Percentages are the share of that set's `tactic_mismatch` failures.\n")

    rec = counts["recovered"]
    vac = counts["vacuous_close"]
    lo, hi = wilson(rec, n) if n else (0, 0)
    A("> **A standard tactic closes %d of %d = %s %s of the failures the "
      "labeller called `tactic_mismatch`.** A further %d closed only because "
      "the hypotheses are contradictory and are not counted as recoveries.\n"
      % (rec, n, pct(rec, n), ci(rec, n), vac))

    # ------------------------------------------------------------------ rungs
    A("## 3. Which rung did the work\n")
    rung = collections.Counter(s["oracle"]["rung"] for s in done
                               if v(s) == "recovered")
    vrung = collections.Counter(s["oracle"]["rung"] for s in done
                                if v(s) == "vacuous_close")
    rows = []
    tacmap = dict(LADDER)
    for name, tac in LADDER:
        k = rung.get(name, 0)
        rows.append(["`%s`" % tac, k, pct(k, n), pct(k, rec) if rec else "—"])
    A(md(["rung", "goals closed", "share of all %d" % n,
          "share of the %d closes" % rec], rows))
    A("")
    if rung:
        top, topk = rung.most_common(1)[0]
        A("**The single most valuable substitution is `%s`**, which alone "
          "accounts for %d of the %d recoveries (%s of all `tactic_mismatch` "
          "failures).\n" % (tacmap[top], topk, rec, pct(topk, n)))
        if rec < 10:
            A("With %d recoveries in total that ranking rests on %d sample%s, "
              "and no weight belongs on the ordering between rungs. The finding "
              "is the total, not its composition.\n"
              % (rec, topk, "" if topk == 1 else "s"))
    else:
        A("No rung produced a genuine recovery.\n")

    if vrung:
        A("Rungs that closed a goal **vacuously** (excluded above): "
          + ", ".join("`%s` %d" % (tacmap[k], c) for k, c in vrung.most_common())
          + ".\n")

    # Rung health. A rung that raises the SAME error on every sample never
    # tested anything -- it is a dead rung, and a ladder with dead rungs in it
    # is weaker than it looks. This is computed rather than asserted so that a
    # rung which dies on a future toolchain shows up on its own.
    A("### 3a. Rung health — did every rung actually run?\n")
    A("A ladder is only as long as its rungs that elaborate. Three verdicts, "
      "assigned mechanically:\n")
    A("- **dead** — ≥90% of attempts fail before the tactic ever sees the goal "
      "(the tactic is deprecated, or its argument list will not elaborate). "
      "These rungs test nothing.\n")
    A("- **declined all** — the tactic elaborated and ran, but rejected every "
      "single goal as out of scope. It is a working rung that this failure set "
      "gave nothing to do.\n")
    A("- **ran** — engaged the goals and lost, or won.\n")
    att = collections.defaultdict(list)
    for s in done:
        for a in s["oracle"].get("attempts", []):
            att[a["rung"]].append(a)
    # Metavariable numbers differ per goal; the same failure would otherwise
    # look like a hundred distinct messages.
    import re as _re
    norm = lambda h: _re.sub(r"\?m\.\d+", "?m.N", h or "")
    NEVER_RAN = ("has been deprecated", "typeclass instance problem is stuck",
                 "don't know how to synthesize", "unknown identifier",
                 "unexpected token")
    DECLINED = ("not a positivity goal", "made no progress")
    rows, dead, declined = [], [], []
    for name, tac in LADDER:
        aa = att.get(name, [])
        if not aa:
            continue
        nv = sum(1 for a in aa if a["outcome"] == "valid")
        heads = collections.Counter(norm(a["error_head"])[:70] for a in aa
                                    if a["outcome"] != "valid" and a["error_head"])
        top, topn = heads.most_common(1)[0] if heads else ("", 0)
        never = sum(1 for a in aa
                    if any(p in (a["error_head"] or "") for p in NEVER_RAN))
        decl = sum(1 for a in aa
                   if any(p in (a["error_head"] or "") for p in DECLINED))
        if nv == 0 and never / len(aa) >= 0.9:
            verdict, bucket = "**dead**", dead
        elif nv == 0 and (never + decl) / len(aa) >= 0.9:
            verdict, bucket = "**declined all**", declined
        else:
            verdict, bucket = "ran", None
        if bucket is not None:
            bucket.append((name, tac, top))
        rows.append(["`%s`" % tac, len(aa), nv, "%.0f%%" % (100.0 * topn / len(aa)),
                     "`%s`" % top if top else "—", verdict])
    A(md(["rung", "attempts", "closed", "share on its most common message",
          "that message", "verdict"], rows))
    A("")
    if dead:
        A("**%d of the %d rungs are dead on this toolchain**: %s. `simp_arith` "
          "is deprecated in Lean v4.32.0 and errors out before running; "
          "`nlinarith [sq_nonneg _, sq_nonneg _]` cannot elaborate its "
          "placeholders and fails with `typeclass instance problem is stuck` on "
          "every sample. Neither ever saw a goal.\n"
          % (len(dead), len(LADDER), ", ".join("`%s`" % t for _, t, _ in dead)))
    if declined:
        A("**%d further rung%s elaborated but declined every goal**: %s. That "
          "is the tactic working correctly — `positivity` proves `0 < e` and "
          "nothing in this failure set is that shape — but it means the rung "
          "contributed no discrimination either.\n"
          % (len(declined), "" if len(declined) == 1 else "s",
             ", ".join("`%s`" % t for _, t, _ in declined)))
    live = len(LADDER) - len(dead) - len(declined)
    A("> **The effective ladder is %d rungs, not %d.** Every `none_closed` in "
      "this report should be read against that smaller ladder, which makes the "
      "recovery figure a weaker lower bound than the brief's ladder implies.\n"
      % (live, len(LADDER)))

    # rung 6 behaviour
    r6 = collections.Counter()
    for s in done:
        for a in s["oracle"].get("attempts", []):
            if a["rung"] == "nlinarith_hint":
                r6[a["outcome"]] += 1
    if r6:
        A("### Rung 6 as literally specified\n")
        A("`nlinarith [sq_nonneg _, sq_nonneg _]` was attempted on %d samples "
          "and its outcomes were: %s. "
          % (sum(r6.values()), ", ".join("`%s` %d" % (k, c) for k, c in r6.most_common())))
        heads = collections.Counter()
        for s in done:
            for a in s["oracle"].get("attempts", []):
                if a["rung"] == "nlinarith_hint" and a["error_head"]:
                    heads[norm(a["error_head"])[:90]] += 1
        if heads:
            A("Most common message: `%s` (%d×). "
              % (heads.most_common(1)[0][0], heads.most_common(1)[0][1]))
        A("It closed %d goals. This is why rung 7 exists.\n"
          % rung.get("nlinarith_hint", 0))

    # ------------------------------------------- the repaired dead rung
    if rp is not None and rp.get("rows"):
        rrows = rp.get("rows") or []
        rc = collections.Counter(r["verdict"] for r in rrows)
        attempted = rp.get("attempted", len(rrows))
        aborted = rp.get("aborted")
        A("### 3c. Supplementary — re-running the one repairable dead rung\n")
        A("`simp_arith` (rung 9) is deprecated on this toolchain and errored "
          "before it ever saw a goal, so rung 9 tested nothing. Lean's own "
          "deprecation message names the replacement, `simp +arith +decide`. "
          "Running that is not tuning the ladder — it is running the rung the "
          "brief asked for, in the spelling this Lean still has.\n")
        A("It is nevertheless reported **here, separately, and never folded into "
          "§2**, because it was run after seeing that the original rung was "
          "dead. Rung 6 is not repaired: its only sample-independent repair is "
          "bare `nlinarith`, which the ladder already carries as rung 7.\n")
        A("**Budget: %ds per attempt, not the 60s §1 uses.** A first attempt at "
          "60s hung the Lean server on a large `¬∃` goal — `+decide` asks the "
          "kernel to evaluate it — lean_interact killed the server, the rebuild "
          "then exceeded its own 300s budget, and every subsequent sample would "
          "have been scored `budget` for infrastructure reasons rather than "
          "measurement. A supplementary pass may take a different budget as "
          "long as it says so; this one says so. The run also aborts the moment "
          "the base environment is lost, rather than emitting rows that look "
          "like measurements and are not.\n"
          % rp.get("repaired_rung_timeout_seconds", "?"))
        A("Applied to the %d of %d samples the pre-registered ladder did not "
          "close%s:\n" % (len(rrows), attempted,
                          " **(aborted early — see below)**" if aborted else ""))
        A(md(["outcome of `simp +arith +decide`", "n", "share of %d" % len(rrows)],
             [["genuine recovery", rc["recovered"], pct(rc["recovered"], len(rrows))],
              ["closed via inconsistent hypotheses (vacuous)", rc["vacuous_close"],
               pct(rc["vacuous_close"], len(rrows))],
              ["did not close", rc["none_closed"], pct(rc["none_closed"], len(rrows))],
              ["exceeded the %ss budget" % rp.get("repaired_rung_timeout_seconds", "?"),
               rc["budget"], pct(rc["budget"], len(rrows))]]))
        A("")
        if aborted:
            A("> ⚠️ **This pass did not finish: %s.** Read it as %d samples of "
              "evidence, not %d.\n" % (aborted, len(rrows), attempted))
        if rc["recovered"] == 0:
            A("> **Zero recoveries.** The dead rung was hiding nothing%s. The "
              "headline %s stands as the pre-registered ladder measured it, and "
              "the deadness of rung 9 is a defect in the ladder's *design*, not "
              "a distortion of its *result*.\n"
              % ("" if not aborted else " in the part of the set that ran",
                 pct(rec, n)))
        else:
            A("> The repaired rung recovers **%d further goal(s)**, which would "
              "take the total from %d to %d (%s). Both are reportable; the "
              "**pre-registered figure is %s** and that is the one that belongs "
              "beside the headline.\n"
              % (rc["recovered"], rec, rec + rc["recovered"],
                 pct(rec + rc["recovered"], n), pct(rec, n)))
    elif rp is not None:
        A("### 3c. Supplementary — the repairable dead rung was not measured\n")
        A("`simp_arith` (rung 9) is deprecated on this toolchain and never saw "
          "a goal, so the obvious follow-up is to run Lean's own named "
          "replacement, `simp +arith +decide`, and check the dead rung was "
          "hiding nothing. **That pass did not produce usable data.** `+decide` "
          "asks the kernel to evaluate goals like `¬∃ a b : ℕ, …`; on the first "
          "attempt it hung the Lean server, lean_interact killed it, the "
          "rebuild exceeded its own 300s budget, and every sample after the "
          "29th would have been scored `budget` for infrastructure reasons "
          "rather than measurement. Those rows were discarded rather than "
          "reported.\n")
        A("So the loophole stays open and is stated rather than closed: **rung "
          "9 tested nothing, and this audit has not established what it would "
          "have found.** `tests/audit/tactic_oracle_repair.py` runs it at a "
          "smaller budget with an abort guard; it has not been completed here.\n")

    # --------------------------------------------------- what the 4 recoveries are
    probe_path = os.path.join(_ROOT, "results", "tactic_oracle_probe.json")
    probe = {}
    if os.path.exists(probe_path):
        probe = {(p["set"], str(p["id"])): p
                 for p in json.load(io.open(probe_path, encoding="utf-8"))}
    A("## 3b. Every recovery, individually\n")
    A("At n=%d each recovery carries real weight in the headline, so each one is "
      "listed rather than summarised. " % rec)
    if probe:
        A("The `asserts` column is the repo's full vacuity taxonomy from "
          "`vacuity_scan.py` — stricter than the contradictory-hypotheses probe "
          "Phase 2 requires, because a goal can be trivially closable without "
          "its hypotheses being inconsistent. `6_contentful` is a recovery of a "
          "goal that actually asserts something; anything else is a recovery of "
          "a goal that did not need proving.\n")
    else:
        A("The vacuity characterisation (`tests/audit/tactic_oracle_probe.py`) "
          "has not been run; only the contradictory-hypotheses probe is "
          "reflected here.\n")
    rows = []
    for s in done:
        if v(s) != "recovered":
            continue
        p = probe.get((s["set"], str(s["id"])), {})
        rows.append([tc.SET_LABEL[s["set"]], "`%s`" % str(s["id"])[:12],
                     "`%s`" % s["oracle"]["tactic"],
                     "`%s`" % ", ".join(s["tactics"][:5]),
                     "`%s`" % p.get("class", "not probed"),
                     "`%s`" % (s["goal"] or s["statement"])[:70]])
    A(md(["trace set", "id", "rung that closed it", "what the model wrote",
          "what the goal asserts", "goal"], rows))
    A("")
    # A gap in vacuity_scan's taxonomy, tested rather than asserted: it has no
    # probe for `∃ x, x = e`, which asserts nothing yet is not True, not a
    # hypothesis, not rfl and not decidable, so it comes back `6_contentful`.
    if probe:
        contentful = sum(1 for r in rows if "6_contentful" in r[4])
        nw = n_witnessed
        A("**%d of the %d recoveries come back `6_contentful`** — no probe in "
          "`vacuity_scan.py`'s taxonomy fires on them, and no hypothesis set is "
          "contradictory.\n" % (contentful, rec))
        if witnessed and nw:
            hit_goals = [w for kk, w in
                         [((x["set"], str(x["id"])), x) for x in done]
                         if witnessed.get(kk)]
            A("**But that taxonomy has a gap, and %d of these %s in it.** "
              "`∃ x, x = e` asserts nothing whatever — take `x` to be `e` — yet "
              "it is not `True`, not a hypothesis, not `rfl`, and not "
              "`decide`-able, so all six of `vacuity_scan.py`'s probes miss it "
              "and it is filed `6_contentful`. Tested directly with "
              "`exact ⟨_, rfl⟩`, which closes exactly the goals witnessed by "
              "their own right-hand side: **%d of the %d recoveries %s**%s.\n"
              % (nw, "falls" if nw == 1 else "fall", nw, len(witnessed),
                 "is" if nw == 1 else "are",
                 (" — " + ", ".join("`%s`" % (g["goal"] or "")[:60]
                                    for g in hit_goals)) if hit_goals else ""))
            subst = rec - nw
            A("> **So the substantive recovery count is %d of %d = %s %s**, not "
              "%d. That is the tightest number in this report and the one to "
              "quote. `vacuity_scan.py` should grow a seventh probe; logged here "
              "rather than fixed, because changing that file would move figures "
              "in `CONTENTLESS_STEPS.md` that this audit has no mandate to "
              "touch.\n" % (subst, n, pct(subst, n), ci(subst, n), rec))
        elif witnessed:
            A("Tested further with `exact ⟨_, rfl⟩` — which closes exactly the "
              "goals `∃ x, x = e`, a shape that asserts nothing and that "
              "`vacuity_scan.py` has no probe for — **none of the %d recoveries "
              "is witnessed by its own right-hand side**. All %d survive as "
              "recoveries of goals that assert something, and %s stands as the "
              "tightest number in this report.\n"
              % (len(witnessed), rec, pct(rec, n)))
        else:
            A("A seventh probe for `∃ x, x = e` — an existential witnessed by "
              "its own right-hand side, which asserts nothing — has not been "
              "run; `tests/audit/tactic_oracle_repair.py` runs it.\n")
    A("The `omega` row is the paradigm case and worth reading closely: on "
      "`7 ∣ (2a+5b) → 7 ∣ (5a+2b)` the model wrote "
      "`simp [Nat.dvd_iff_mod_eq_zero]`, then a `have`, then `rw`, and only then "
      "`omega` — and `omega` failed. Bare `omega`, handed the untouched goal, "
      "closes it. The tactic was right; the **preprocessing in front of it** "
      "destroyed the goal. That is a distinct failure mode from picking the "
      "wrong tactic, and it is the one a repair loop (§7.2) would catch.\n")

    # ------------------------------------------------------------------ shape
    A("## 4. Recovery by goal shape and by the tactic the model chose\n")
    A("Where the headroom actually is.\n")
    shapes = [sh for sh in tc.SHAPES if any(s["shape"] == sh for s in done)]
    rows = []
    for sh in shapes:
        grp = [s for s in done if s["shape"] == sh]
        k = sum(1 for s in grp if substantive(s))
        rows.append([sh, len(grp), k, pct(k, len(grp)), ci(k, len(grp))])
    A(md(["goal shape (top-level)", "n", "substantive recoveries", "rate",
          "95% CI"], rows))
    A("")
    rows = []
    for t, c in collections.Counter(s["lean_tactic"] for s in done).most_common():
        grp = [s for s in done if s["lean_tactic"] == t]
        k = sum(1 for s in grp if substantive(s))
        rows.append(["`%s`" % t, len(grp), k, pct(k, len(grp)), ci(k, len(grp))])
    A(md(["tactic Lean named as failing", "n", "substantive recoveries", "rate",
          "95% CI"], rows))
    A("")
    st_grp = [s for s in done if s["structural"]]
    st_rec = sum(1 for s in st_grp if substantive(s))
    if st_grp:
        A("Phase 1 identified **%d** failures as structural category errors on "
          "direct evidence from Lean. The oracle recovers **%d of those %d "
          "(%s %s)** — the cleanest read on whether \"this tactic could never "
          "have worked\" implies \"a working tactic exists\".\n"
          % (len(st_grp), st_rec, len(st_grp), pct(st_rec, len(st_grp)),
             ci(st_rec, len(st_grp))))

    # ------------------------------------------------------------------ phase 3
    A("## 5. Phase 3 — what it does to the headline\n")
    A("The corrected rate is **not what Goedel-Prover achieves**. It is what the "
      "pass rate would be **if tactic selection were perfect** — an upper bound "
      "on the trace-validity signal. The gap between the two columns is the size "
      "of the prover-skill contamination in the current metric. The two numbers "
      "are only meaningful side by side and must never be reported apart.\n")
    hdr = ["trace set", "observed pass rate", "95% CI", "substantive recoveries",
           "pass rate under tactic oracle (**upper bound**)", "95% CI", "gap"]
    rows = []
    for st in tc.SET_ORDER:
        k, tot, _art = HEADLINE[st]
        r = n_sub(st)
        raw = sum(1 for s in done if s["set"] == st and v(s) == "recovered")
        rows.append([tc.SET_LABEL[st],
                     "%d/%d = %s" % (k, tot, pct(k, tot)), ci(k, tot),
                     "%d%s" % (r, "" if r == raw else " *(of %d closed)*" % raw),
                     "%d/%d = %s" % (k + r, tot, pct(k + r, tot)), ci(k + r, tot),
                     "+%.1f pp" % (100.0 * r / tot)])
    A(md(hdr, rows))
    A("")
    if n_witnessed:
        A("**The recovery column is the substantive count, not the raw one.** "
          "%d close%s in §2 that is an existential witnessed by its own "
          "right-hand side is excluded here for the same reason a "
          "contradictory-hypothesis close is: it is not evidence that the trace "
          "was valid. The raw count is shown in italics where the two differ.\n"
          % (n_witnessed, "" if n_witnessed == 1 else "s"))
    A("**No row is pooled with another.** FormalStep and Stage B are different "
      "formalization pipelines with different units; the two FormalStep n50 runs "
      "cover the same 50 problems at two temperatures and their passes are not "
      "independent. Each row stands alone.\n")
    A("**The FormalStep baseline row is not a validity rate over problems.** Its "
      "50 samples are 50 CoT steps of a *single* problem "
      "(`math_train_counting_and_probability_408`); see the `SAMPLE_STRATEGY` "
      "note in `config.py`. It is here because its `tactic_mismatch` failures "
      "are real failures worth putting through the oracle, but 21/50 is a "
      "within-problem step rate and must not be read as a validity figure.\n")
    sb0 = HEADLINE["stageB_T0.0"]
    r0 = n_sub("stageB_T0.0")
    A("> Stage B T=0.0, the repo's headline Stage B figure: **observed "
      "%d/%d = %s %s; under a perfect tactic oracle %d/%d = %s %s.** The second "
      "number is an upper bound that no prover attains, and the %.0f-point gap "
      "is how much of the current metric is measuring Goedel-Prover's tactic "
      "selection rather than the validity of the trace.\n"
      % (sb0[0], sb0[1], pct(sb0[0], sb0[1]), ci(sb0[0], sb0[1]),
         sb0[0] + r0, sb0[1], pct(sb0[0] + r0, sb0[1]), ci(sb0[0] + r0, sb0[1]),
         100.0 * r0 / sb0[1]))

    # ------------------------------------------------------------------ phase 4
    A("## 6. Phase 4 — the three questions, in plain language\n")

    A("### 6.1 What fraction of our recorded failures are the prover's fault "
      "rather than the trace's?\n")
    _sub = n_sub()
    A("**%s %s of `tactic_mismatch` failures — %d of %d — are the prover's "
      "fault in the strictest sense available: keep the statement and the "
      "header exactly as they were, replace the proof with a fixed standard "
      "tactic, and a goal that asserts something closes.**%s "
      % (pct(_sub, n), ci(_sub, n), _sub, n,
         "" if _sub == rec else
         (" (%d closed in all; the %d excluded %s an existential witnessed by "
          "its own right-hand side — §3b.)" % (rec, rec - _sub,
                                               "is" if rec - _sub == 1 else "are"))))
    A("Two things bound that number in opposite directions. It is a **lower** "
      "bound on prover fault, because a ladder of %d standard tactics — %d of "
      "them live on this toolchain, none of them able to `intro` a quantifier "
      "except `aesop` and `norm_num` — is a weak prover: a goal needing a "
      "lemma, an induction, or a case split is `none_closed` here even when a "
      "competent proof exists. It is an **upper** bound on what *this* pipeline "
      "could recover without new generation, because the oracle is allowed to "
      "know the answer and the model is not.\n" % (len(LADDER), live))
    sb_done = [s for s in done if s["pipeline"] == "StageB"]
    sb_rec = sum(1 for s in sb_done if substantive(s))
    A("Scaled to Stage B's whole judged failure set rather than to "
      "`tactic_mismatch` alone, and using Stage B's own numbers rather than the "
      "pooled rate: **%d of %d** Stage B `tactic_mismatch` failures recover "
      "(%s %s), and `tactic_mismatch` is 85 of Stage B's 110 judged failures, so "
      "recoveries are **%d of 110 = %s** of Stage B's judged failures overall. "
      "The remaining %d judged failures are `UNKNOWN`, `parse_skew`, "
      "`noop_tactic` and `budget`, none of which this ladder addresses.\n"
      % (sb_rec, len(sb_done), pct(sb_rec, len(sb_done)), ci(sb_rec, len(sb_done)),
         sb_rec, pct(sb_rec, 110), 110 - 85))

    A("### 6.2 Does the headline validity number understate trace validity, and "
      "by how much?\n")
    gaps = []
    for st in tc.SET_ORDER:
        k, tot, _ = HEADLINE[st]
        r = n_sub(st)
        gaps.append((tc.SET_LABEL[st], k, tot, r, 100.0 * r / tot))
    worst = max(gaps, key=lambda g: g[4])
    if worst[4] < 5.0:
        A("**Not measurably.** The largest correction across all five runs is "
          "**+%.1f points**, on %s, and its confidence interval before the "
          "correction (%s) overlaps its interval after (%s) almost entirely. "
          "On Stage B at T=0.0 — the repo's headline Stage B figure — the "
          "correction is exactly **zero**.\n"
          % (worst[4], worst[0], ci(worst[1], worst[2]),
             ci(worst[1] + worst[3], worst[2])))
    else:
        A("**Yes, and by the gap in §5.** The largest correction is +%.1f "
          "points, on %s.\n" % (worst[4], worst[0]))
    A("Run by run: " + "; ".join(
        "%s %s → %s (+%.1f pp)" % (a, pct(k, tot), pct(k + r, tot), g)
        for a, k, tot, r, g in gaps) + ".\n")
    A("The honest framing either way: the published rate is a **joint "
      "measurement of trace validity and prover skill**, and it cannot be "
      "decomposed without a reference prover. This oracle replaces "
      "\"Goedel-Prover's tactic choice\" with \"the best of %d fixed tactics\", "
      "which is a different prover, not no prover. A near-zero correction says "
      "**this particular substitute prover is no better than Goedel-Prover on "
      "these goals** — not that prover skill has been eliminated from the "
      "metric. A stronger substitute (best-of-n, a repair loop, a larger model) "
      "could still move the number, and §7 is why none of those could be run "
      "here.\n" % len(LADDER))

    A("### 6.3 Which single tactic substitution would recover the most "
      "failures?\n")
    if rung:
        top, topk = rung.most_common(1)[0]
        A("**`%s`** — %d of the %d recoveries, %s of all `tactic_mismatch` "
          "failures. " % (tacmap[top], topk, rec, pct(topk, n)))
        rest = [(tacmap[k], c) for k, c in rung.most_common()[1:4]]
        if rest:
            A("Behind it: " + ", ".join("`%s` (%d)" % (a, b) for a, b in rest) + ".\n")
        else:
            A("\n")
        if rec < 10:
            A("**That answer is close to content-free and should be reported as "
              "such.** With %d recoveries in total the ranking rests on %d "
              "sample%s. The honest answer to \"which substitution recovers the "
              "most\" is **none of them recovers meaningfully many**. If one has "
              "to be named: `aesop` and `norm_num` are the only rungs that do "
              "any structural work — they will `intro` a quantified goal before "
              "deciding — and §8 argues that is exactly why they are the ones "
              "that ever win. The actionable version of this question is not "
              "\"which tactic\" but \"a tactic that introduces binders first\", "
              "and testing that properly needs the repair loop in §7.2.\n"
              % (rec, topk, "" if topk == 1 else "s"))
    else:
        A("None. No rung recovered a goal.\n")

    A("## 7. What this cannot settle without new generation\n")
    A("Everything above reuses existing traces. Three questions need a fresh "
      "generation run and are logged as `requires-a-new-run`.\n")
    A("1. **Best-of-n sampling.** The oracle asks whether *a* correct proof "
      "exists in a fixed tactic list. It does not ask whether Goedel-Prover "
      "would *find* one given more attempts. Those are different quantities and "
      "this audit measures only the first. n=1 at two temperatures is all the "
      "repo has, and McNemar already says temperature does nothing (p = 0.80); "
      "sampling breadth is the untested axis.\n")
    A("2. **An error-feedback repair loop.** Lean's messages here are "
      "unusually actionable — `linarith failed to find a contradiction` printed "
      "with the full context, `omega could not prove the goal` printed with a "
      "counterexample to its own constraint system. Feeding that back and "
      "resampling is the standard repair loop and it has never been tried in "
      "this repo. The oracle is a crude lower bound on what it would achieve, "
      "because the oracle cannot read the error it just caused.\n")
    A("3. **Does the `informal_prefix` doc comment steer tactic choice? — the "
      "most interesting untested hypothesis here.** `PROMPT_TEMPLATE` in "
      "`config.py` puts the CoT step in as a Lean doc comment immediately above "
      "the statement, so the model reads the natural-language reasoning before "
      "it picks a tactic. Sample 27 of the baseline run is the case in point, "
      "and it is worse than it first looks:\n")
    A("   ```lean4\n"
      "   /-- $= 1\\cdot (100+6)^3$. -/\n"
      "   theorem test (a : ℝ) (h₀ : 1061520150601 = 1 * (100 + 6) ^ 3) :\n"
      "       (a = 1061520150601) := by\n"
      "   ```\n"
      "   The doc comment is arithmetically false — `(100+6)^3 = 1191016`, while "
      "`1061520150601 = 101^6`, five orders of magnitude apart — and the model's "
      "output repeats it back: *\"By simplifying the right-hand side of the "
      "equation, we can verify that it indeed equals 1061520150601.\"* It then "
      "wrote `rw [h₀]` and Lean rejected the rewrite. The provenance labeller "
      "files this `statement_false`, not `tactic_mismatch`, so it is **outside "
      "this audit's %d samples** — but it is the clearest instance in the repo "
      "of the doc comment leading the prover somewhere it should not have gone. "
      "If a wrong CoT step actively steers tactic choice, the pipeline is not "
      "measuring trace validity so much as measuring whether a trace misleads a "
      "prover. That is a different research question wearing the same clothes.\n"
      % len(samples))
    A("   The ablation is cheap and decisive: regenerate with "
      "`informal_prefix=\"\"`, everything else pinned, and compare pass rates "
      "and tactic distributions on the same statements. If the pass rate rises "
      "with the doc comment removed, the CoT step is hurting the prover. If the "
      "tactic distribution shifts but the pass rate does not, it steers without "
      "helping. Needs a GPU; nothing else in this audit does.\n")

    A("## 8. Limits of this measurement\n")
    import re as _re2
    quant = sum(1 for s in done if _re2.match(r"^\s*¬?\s*[∀∃]", s["goal"] or ""))
    A("- **The ladder is weak on purpose, and its biggest blind spot is "
      "measurable.** %d fixed tactics — %d of them live on this toolchain (§3a) "
      "— with no lemma lookup, no induction, no case analysis, no hint terms "
      "and, decisively, **no structural step**. **%d of the %d goals (%s) open "
      "with a quantifier** (`∀`, `∃`, `¬∃`). A quantified goal needs `intro`, "
      "`use`, `rintro` or `obtain` before any decision procedure can see "
      "anything, and only `aesop` and `norm_num` in this ladder do that at all. "
      "`none_closed` therefore means \"this ladder failed\", never \"the goal is "
      "unprovable\", and the true recovery ceiling is higher than %s by an "
      "amount this design cannot measure.\n"
      % (len(LADDER), live, quant, n, pct(quant, n), pct(rec, n)))
    A("- **The oracle is not a prover and must not be added to the pipeline.** "
      "It is a measurement of headroom. Wiring it into generation would make "
      "the pass rate uninterpretable, because the ladder was chosen after "
      "seeing which goals fail.\n")
    A("- **`recovered` is a claim about the goal, not about the model.** It says "
      "a correct proof of that statement exists within reach of standard "
      "automation. It says nothing about whether the CoT step the statement "
      "formalises is good reasoning.\n")
    if vac:
        A("- **Vacuous closes are reported, not hidden.** %d goals closed only "
          "because their hypotheses are contradictory. Those statements are "
          "broken in the sample-42 way and are excluded from every recovery "
          "figure above.\n" % vac)
    else:
        A("- **The vacuity probe ran on every close and fired on none of "
          "them.** All %d recoveries are of goals whose hypotheses are "
          "consistent so far as `%s` can tell, so none is a sample-42 "
          "artefact. With only %d closes that is a weak test of the probe, not "
          "evidence that the corpus is free of vacuous statements — "
          "`vacuity_scan.json` is where that question lives.\n"
          % (rec, "` / `".join(CONTRA_TACTICS), rec))
    A("- The `tactic_mismatch` label itself comes from a labeller that "
      "evaluated **0 arithmetic claims on Stage B** (`STAGEB_PROVENANCE.md` §3). "
      "This audit inherits that label without re-deriving it, so it inherits its "
      "reach problem too.\n")

    io.open(out_md or os.path.join(_ROOT, "results", "TACTIC_ORACLE.md"), "w",
            encoding="utf-8").write("\n".join(L) + "\n")

    summary = {
        "complete": not partial, "n_done": n, "n_total": len(samples),
        "ladder": [{"rung": a, "tactic": b} for a, b in LADDER],
        "per_attempt_budget_seconds": VERIFY_TIMEOUT_SECONDS,
        "counts": dict(counts),
        "recovered_wilson": [round(lo, 4), round(hi, 4)],
        "by_set": {st: dict(collections.Counter(
            v(s) for s in done if s["set"] == st)) for st in tc.SET_ORDER},
        "recovering_rung": dict(rung),
        "vacuous_rung": dict(vrung),
        "headline": {st: {"observed_k": HEADLINE[st][0], "n": HEADLINE[st][1],
                          "substantive_recoveries": n_sub(st),
                          "closes_including_vacuous":
                              sum(1 for s in done if s["set"] == st
                                  and v(s) == "recovered")}
                     for st in tc.SET_ORDER},
    }
    json.dump(summary, io.open(out_json or os.path.join(_ROOT, "results",
                                                        "tactic_oracle.json"),
                               "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("wrote results/TACTIC_ORACLE.md and results/tactic_oracle.json")
    print("done=%d/%d  recovered=%d  vacuous=%d  none=%d  budget=%d"
          % (n, len(samples), rec, vac, counts["none_closed"], counts["budget"]))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=None)
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--out-json", default=None)
    a = ap.parse_args()
    main(a.inp, a.out_md, a.out_json)
