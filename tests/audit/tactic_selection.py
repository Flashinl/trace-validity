"""Phase 1: what tactic does the model reach for, and on what shape of goal?

Cross-tabulates the tactic Goedel-Prover actually wrote against the shape of the
goal it was written for, over every `tactic_mismatch` failure in the repo. No
Lean, no GPU -- this reads the errors the verifier already recorded.

There are TWO cross-tabs and they answer different questions.

  Table A (primary)   the tactic LEAN NAMES as having failed, against the shape
                      of the goal state LEAN PRINTED in that error. Exact
                      pairing: this tactic met this goal.
  Table B (secondary) the closing tactic in the model's proof body, against the
                      shape of the theorem's top-level goal. Wider coverage --
                      it has an entry for every sample, including those whose
                      error names no tactic -- but the pairing is inexact when
                      earlier tactics reshaped the goal first.

The cell that matters is `linarith` on a nonlinear goal. `linarith` decides
linear arithmetic over ordered fields; on `x ^ 6 = n` or `n * (n+1) * (n+2)` it
cannot succeed under any hint set, configuration, or timeout. That is a category
error, not a near miss, and it is reported separately.

Run: python tests/audit/tactic_selection.py
"""
import collections, io, json, os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tactic_common as tc  # noqa: E402
from stats import wilson  # noqa: E402

# (tactic, shape) pairs that are structurally impossible: the decision procedure
# has no representation for that class of goal, so no hint, timeout or retry
# changes the outcome.
STRUCTURAL = {
    ("linarith", "nonlinear"): "linarith seeks a degree-1 certificate; every nonlinear "
                               "monomial is abstracted to an opaque atom first, so the "
                               "fact that would close the goal is no longer expressible",
    ("nlinarith", "nonlinear"): None,  # nlinarith IS the nonlinear one -- never structural
    ("omega", "nonlinear"): "omega decides linear integer/ℕ arithmetic; a product of "
                            "variables is abstracted to a fresh atom, after which nothing "
                            "relates it to its factors",
    ("omega", "finset_bigop"): "omega has no theory of Finset cardinality or big operators",
    ("omega", "quantified"): "omega works on a quantifier-free linear fragment; it does "
                             "not instantiate or introduce quantifiers",
    ("omega", "linear_real_rat"): "omega is integer/ℕ only; it does not see ℝ or ℚ",
    ("linarith", "finset_bigop"): "linarith has no theory of Finset cardinality",
    ("ring", "nat_int_arith"): "ring proves commutative-ring identities; divisibility and "
                               "modular goals are not identities",
    ("ring_nf", "nat_int_arith"): "ring_nf normalises ring expressions; it decides nothing",
}
STRUCTURAL = {k: v for k, v in STRUCTURAL.items() if v}

SHAPE_LABEL = {
    "linear_real_rat": "linear ℝ/ℚ",
    "nonlinear": "nonlinear",
    "nat_int_arith": "ℕ/ℤ, divisibility, modular",
    "quantified": "quantified (∀,∃)",
    "finset_bigop": "Finset / card / big-op",
    "other": "other",
}

KIND_LABEL = {
    "tactic_failed": "a named tactic failed on a goal it could see",
    "unsolved_goals": "the proof block ended with the goal still open",
    "unknown_name": "the model cited a lemma that does not exist",
    "type_error": "the model wrote a term that does not typecheck",
    "other": "other",
}


def md(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def crosstab(samples, tkey, skey, L):
    cross = collections.Counter((x[tkey], x[skey]) for x in samples)
    by_t = collections.Counter(x[tkey] for x in samples)
    by_s = collections.Counter(x[skey] for x in samples)
    shapes = [s for s in tc.SHAPES if by_s[s]]
    tactics = [t for t, _ in by_t.most_common()]
    hdr = ["tactic"] + [SHAPE_LABEL[s] for s in shapes] + ["all"]
    rows = []
    for t in tactics:
        row = ["`%s`" % t if not t.startswith("(") else "_%s_" % t]
        for s in shapes:
            c = cross[(t, s)]
            row.append(("**%d**%s" % (c, " ⛔" if (t, s) in STRUCTURAL else "")) if c else "·")
        row.append("**%d**" % by_t[t])
        rows.append(row)
    rows.append(["**all**"] + ["**%d**" % by_s[s] for s in shapes] + ["**%d**" % len(samples)])
    L.append(md(hdr, rows))
    L.append("")
    return cross


def main():
    samples = tc.attach_lean_errors(tc.load_samples())
    n = len(samples)

    L = []
    A = L.append
    A("# Phase 1 — what tactic does the model pick, and for what goal?\n")
    A("Every `tactic_mismatch` failure in the repo: **%d** samples. Generated by "
      "`tests/audit/tactic_selection.py`; machine-readable copy in "
      "`results/tactic_selection.json`. No Lean was run for this phase — it reads "
      "the error text the verifier already recorded.\n" % n)
    A("`tactic_mismatch` is the arithmetic-provenance label for \"the statement "
      "elaborated, the goal stood, and the model's tactic did not close it\". It "
      "is 77.3% [68.6–84.1] of Stage B's judged failures, and those are false "
      "negatives on the research question: a valid reasoning step scored invalid "
      "because the prover picked the wrong tool.\n")

    # ---------------------------------------------------------------- sets
    A("## 0. Which trace sets\n")
    A("The audit brief says \"all three trace sets\". There are in fact **five "
      "labelled generation runs across two pipelines**, and `tactic_mismatch` "
      "appears in all five; all five are included. "
      "`results/stage_b_traces.jsonl` is byte-identical to the T=0.0 file "
      "(hashed on `full_code`), so Stage B is two arms, not three.\n")
    rows = [[tc.SET_LABEL[st], sum(1 for x in samples if x["set"] == st)]
            for st in tc.SET_ORDER]
    rows.append(["**total**", "**%d**" % n])
    A(md(["trace set", "tactic_mismatch failures"], rows))
    A("")
    A("**FormalStep and Stage B are different pipelines with different units and "
      "no rate is ever pooled across them.** They are pooled here only to count "
      "how often a tactic meets a goal shape, which is a property of the model "
      "rather than of either eval set. Every rate in this file is reported "
      "per-set as well.\n")

    # ---------------------------------------------------------------- kinds
    A("## 1. Not every `tactic_mismatch` is a tactic that lost\n")
    A("Before cross-tabulating, split the failures by what Lean actually "
      "complained about. `tactic_mismatch` is one label covering four different "
      "things, and two of them are not \"wrong decision procedure\" at all.\n")
    kinds = collections.Counter(x["lean_kind"] for x in samples)
    rows = []
    for k, c in kinds.most_common():
        lo, hi = wilson(c, n)
        rows.append([("`%s`" % k), KIND_LABEL.get(k, k), c,
                     "%.1f%%" % (100.0 * c / n), "[%.0f–%.0f]" % (100 * lo, 100 * hi)])
    A(md(["Lean's complaint", "what it means", "n", "share of %d" % n, "95% CI"], rows))
    A("")
    not_tactic = kinds["unknown_name"] + kinds["type_error"]
    lo, hi = wilson(not_tactic, n)
    A("> **%d/%d = %.1f%% [%.0f–%.0f] of `tactic_mismatch` failures are not a "
      "tactic-selection problem at all.** The model cited a lemma that does not "
      "exist (`Nat.odd_iff_not_even`, `Real.sqrt_eq_iff_sq_eq`) or wrote a term "
      "that does not typecheck. Changing which tactic is tried cannot fix those; "
      "they are recall failures about Mathlib's API, and a tactic oracle should "
      "be expected to rescue them only when the goal happens to be closable "
      "without the lemma.\n" % (not_tactic, n, 100.0 * not_tactic / n,
                                100 * lo, 100 * hi))

    # ---------------------------------------------------------------- table A
    A("## 2. Table A (primary) — the tactic Lean named × the goal Lean printed\n")
    A("For %d of %d samples Lean's error names the failing tactic; for %d it "
      "names none (`unsolved goals`, an unknown constant, a type error), and "
      "those are grouped as _(none named)_. Goal shape comes from the goal state "
      "printed in the error whenever one is printed (%d samples) and from the "
      "theorem statement otherwise (%d).\n"
      % (sum(1 for x in samples if x["lean_tactic"] != "(none named)"), n,
         sum(1 for x in samples if x["lean_tactic"] == "(none named)"),
         sum(1 for x in samples if x["lean_shape_source"] == "lean_goal_state"),
         sum(1 for x in samples if x["lean_shape_source"] == "statement")))
    A("Why not always the printed state: `omega could not prove the goal:` is "
      "followed by omega's own linear constraint system and a `where a := ↑n / 3` "
      "substitution table, which is omega's abstraction of the goal rather than "
      "the goal; `simp made no progress` prints nothing. Classifying either "
      "would measure the tactic's internal view instead of the mathematics.\n")
    A("For `linarith`/`nlinarith` the printed state is `⊢ False` with the negated "
      "goal moved into the hypotheses, so the shape is taken over the whole "
      "context, hypotheses included — which is correct, since linarith's language "
      "has to cover the hypotheses too.\n")
    crossA = crosstab(samples, "lean_tactic", "lean_shape", L)
    A("⛔ marks a cell where the tactic **cannot** decide that class of goal — "
      "not \"searched and lost\", but outside its language.\n")

    structA = sum(crossA[k] for k in STRUCTURAL)
    struct = [x for x in samples if x["structural"]]
    ns = len(struct)
    lo, hi = wilson(ns, n)
    A("### 2a. Structural category errors — direct evidence only\n")
    A("A cell in Table A is *suggestive*, not conclusive: 24 of the 36 `omega` "
      "failures are filed nonlinear on the strength of the theorem's top-level "
      "goal, and by the time omega ran the model may already have `intro`'d and "
      "destructured its way to something linear. So the structural claim is made "
      "here **only where Lean's own output settles it**, and everything else is "
      "left uncounted:\n")
    A("- **`linarith` on a nonlinear context.** `linarith` prints the entire "
      "context it held, hypotheses and `⊢ False` included. If a nonlinear term "
      "is in that printout, linarith was holding it.\n")
    A("- **`omega` with a nonlinear atom in its own `where` table.** omega prints "
      "the atoms it introduced. `e := ↑b * ↑k` is omega stating that it replaced "
      "a product of variables with an opaque symbol.\n")
    rows = []
    lin_e = [x for x in struct if x["lean_tactic"] == "linarith"]
    om_e = [x for x in struct if x["lean_tactic"] == "omega"]
    for nm, grp, ev in (("`linarith`", lin_e, "nonlinear term in linarith's printed context"),
                        ("`omega`", om_e, "product of variables in omega's `where` table")):
        if grp:
            rows.append([nm, len(grp), "%.1f%%" % (100.0 * len(grp) / n), ev])
    A(md(["tactic", "n", "share of %d" % n, "the evidence"], rows))
    A("")
    A("> **Structural category errors, on direct evidence: %d/%d = %.1f%% "
      "[%.0f–%.0f]** of all `tactic_mismatch` failures.\n"
      % (ns, n, 100.0 * ns / n, 100 * lo, 100 * hi))
    lo4, hi4 = wilson(structA, n)
    A("**And the number not to quote.** Reading Table A's ⛔ cells at face value "
      "gives %d/%d = %.0f%% [%.0f–%.0f], but %d of those rest on the top-level "
      "goal rather than on what the tactic held. That figure is an upper bound "
      "with a soft floor under it; **%d is the number this audit stands behind**, "
      "and the true value lies between them.\n"
      % (structA, n, 100.0 * structA / n, 100 * lo4, 100 * hi4, structA - ns, ns))
    om_lin = sum(1 for x in samples if x["lean_tactic"] == "omega"
                 and not x["omega_nonlinear_atom"])
    A("The %d `omega` failures with no nonlinear atom deserve their own note. "
      "omega did not choke on them: it built a linear constraint system, "
      "searched it, and reported *\"a possible counterexample may satisfy the "
      "constraints\"*. That is a decision, not a category error — the goal does "
      "not follow from the hypotheses omega could see. Either the model's own "
      "`have` chain had already gone somewhere unprovable, or the facts needed "
      "were nonlinear and got dropped further upstream. Phase 2 tests these "
      "directly by throwing the whole proof body away.\n" % om_lin)

    lin = crossA[("linarith", "nonlinear")]
    lo2, hi2 = wilson(lin, n)
    A("### 2b. The cell the brief asked to look at hardest\n")
    A("> **`linarith` on a nonlinear goal: %d/%d = %.1f%% [%.0f–%.0f]** of all "
      "`tactic_mismatch` failures, counted from Lean's own attribution.\n"
      % (lin, n, 100.0 * lin / n, 100 * lo2, 100 * hi2))
    A("`linarith` looks for a positive rational combination of the hypotheses "
      "that contradicts the negated goal — a degree-1 Positivstellensatz "
      "certificate. A context containing `x ^ 6`, `n * (n + 1) * (n + 2)`, or "
      "`Real.sqrt` admits no degree-1 certificate, so `linarith` fails on it by "
      "construction. Retrying, resampling, or raising the timeout changes "
      "nothing; only a different tactic can.\n")
    ex = [x for x in samples if x["lean_tactic"] == "linarith"
          and x["lean_shape"] == "nonlinear"]
    if ex:
        A("All %d, quoting the line **from linarith's own printed context** that "
          "carries the nonlinear term — not the theorem's goal, which in several "
          "of these looks perfectly linear until you see what linarith was "
          "holding:\n" % len(ex))
        for x in ex:
            line = ""
            for ln in x["lean_context"].splitlines():
                ln = ln.strip()
                if ln and ln != "⊢ False" and tc.goal_shape(ln, whole=ln) == "nonlinear":
                    line = ln
                    break
            A("- `%s` `%s` — `%s`" % (tc.SET_LABEL[x["set"]], str(x["id"])[:36],
                                      (line or x["goal"])[:110]))
        A("")

    # ---------------------------------------------------------------- table B
    A("## 3. Table B (secondary) — the closing tactic the model wrote × the "
      "theorem's top-level goal\n")
    A("Covers all %d samples, including those whose error names no tactic. The "
      "*closing* tactic, not every tactic in the body: `rw`, `have` and `intro` "
      "appear in nearly every proof and say nothing about which decision "
      "procedure the model was betting on (precedence in "
      "`tactic_common._CLOSERS`). Goal shape is first-match over the columns "
      "left to right, so a goal that is both nonlinear and quantified is filed "
      "nonlinear — that is what decides whether `linarith` could ever have "
      "worked.\n" % n)
    crossB = crosstab(samples, "primary", "shape", L)
    first = [x for x in samples if x["closer_first"]]
    structB = sum(crossB[k] for k in STRUCTURAL)
    A("**Table B's pairing is inexact, and that is why Table A leads.** If the "
      "model wrote `intro n; rcases h with ⟨k, hk⟩; linarith`, the `linarith` "
      "met a subgoal that may well be linear even though the theorem's goal is "
      "not. The pairing is certainly exact only when the closing tactic is the "
      "**first** tactic in the body, which holds for just %d of %d samples. "
      "Table B's structural total is %d/%d = %.0f%%, against Table A's %d — read "
      "the difference as the inflation the top-level-goal approximation "
      "introduces, and use Table A.\n"
      % (len(first), n, structB, n, 100.0 * structB / n, structA))

    # ---------------------------------------------------------------- top 5
    A("## 4. Top five tactic/goal-shape mismatches by frequency\n")
    A("From Table A. Cells whose tactic is _(none named)_ are excluded: they "
      "describe a proof that ran out without closing, not a tactic choice.\n")
    rows = []
    ranked = [(k, v) for k, v in crossA.most_common() if k[0] != "(none named)"]
    for i, ((t, s), c) in enumerate(ranked[:5], 1):
        cell = [x for x in samples if x["lean_tactic"] == t and x["lean_shape"] == s]
        ev = sum(1 for x in cell if x["structural"])
        rows.append([i, "`%s`" % t, SHAPE_LABEL[s], c, "%.1f%%" % (100.0 * c / n),
                     ("structural at face value, **%d of %d** on direct evidence"
                      % (ev, c)) if (t, s) in STRUCTURAL else "not structural"])
    A(md(["#", "tactic", "goal shape", "n", "share of %d" % n, "verdict"], rows))
    A("")
    face = crossA[("omega", "nonlinear")] + lin
    face_ev = sum(1 for x in samples
                  if x["structural"] and x["lean_shape"] == "nonlinear"
                  and x["lean_tactic"] in ("omega", "linarith"))
    A("The shape of the answer: **`omega` and `linarith` on goals classified "
      "nonlinear are %d of %d = %.0f%% of every `tactic_mismatch` failure in "
      "this repo** — two tactics making one mistake, reaching for a linear "
      "decision procedure on a nonlinear goal. Of those %d, **%d are backed by "
      "Lean's own output** (§2a); the rest rest on the top-level goal. **%d is "
      "the quotable figure and %d is the ceiling.** (§2a's total of %d is one "
      "higher: it counts a third `omega` sample whose statement-level shape "
      "falls in a different column, so it is outside these two cells.)\n"
      % (face, n, 100.0 * face / n, face, face_ev, face_ev, face, ns))

    # ---------------------------------------------------------------- vocab
    A("## 5. The model's raw tactic vocabulary\n")
    A("Every tactic named at the head of a line anywhere in a failing proof "
      "body, closing or not.\n")
    allt = collections.Counter()
    for x in samples:
        for t in x["tactics"]:
            allt[t] += 1
    tracked = ["linarith", "nlinarith", "norm_num", "decide", "simp", "ring",
               "ring_nf", "omega", "positivity", "rw", "field_simp", "aesop"]
    rows = [["`%s`" % t, allt.get(t, 0), "%.1f%%" % (100.0 * allt.get(t, 0) / n)]
            for t in sorted(tracked, key=lambda t: -allt.get(t, 0))]
    A(md(["tracked tactic", "proofs mentioning it", "share of %d" % n], rows))
    A("")
    other = [(t, c) for t, c in allt.most_common() if t not in tracked][:15]
    A("Other tactics that appear (top 15): "
      + ", ".join("`%s` %d" % (t, c) for t, c in other) + ".\n")
    never = [t for t in tracked if not allt.get(t)]
    if never:
        A("**Tracked tactics the model never writes: %s.** "
          % ", ".join("`%s`" % t for t in never)
          + "`positivity` is the standard tool for `0 < e` / `0 ≤ e` goals and "
            "Goedel-Prover-SFT never reaches for it. It would be tempting to "
            "call that a gap in the model's repertoire — **and Phase 2 shows it "
            "is not.** Run as a ladder rung against all 104 goals, `positivity` "
            "returned `not a positivity goal` 102 times out of 102 "
            "(`TACTIC_ORACLE.md` §3a). Nothing in this failure set is that "
            "shape, so the omission cost the model nothing. Absence from a "
            "vocabulary is not evidence of a missing capability, and this is the "
            "cross-check that says so.\n")

    # ---------------------------------------------------------------- per set
    A("## 6. Per-trace-set breakdown (Table A attribution)\n")
    tactics = [t for t, _ in collections.Counter(
        x["lean_tactic"] for x in samples).most_common()][:7]
    hdr = ["trace set"] + ["`%s`" % t for t in tactics] + ["other", "n"]
    rows = []
    for st in tc.SET_ORDER:
        sub = [x for x in samples if x["set"] == st]
        c = collections.Counter(x["lean_tactic"] for x in sub)
        row = [tc.SET_LABEL[st]] + [c[t] or "·" for t in tactics]
        row.append(sum(v for k, v in c.items() if k not in tactics) or "·")
        row.append(len(sub))
        rows.append(row)
    A(md(hdr, rows))
    A("")
    A("The two Stage B arms are near-identical in tactic distribution, which is "
      "consistent with the null temperature effect already measured (McNemar "
      "p = 0.80). FormalStep never reaches for `omega` — its goals are closed "
      "rational arithmetic, where `norm_num` and `linarith` are the natural "
      "first guesses.\n")

    # ---------------------------------------------------------------- limits
    A("## 7. What this phase does and does not establish\n")
    A("- It establishes that failures concentrate in a few tactic/goal-shape "
      "cells, and that **%d of %d (%.0f%%)** sit in cells where the chosen "
      "procedure could not have worked.\n" % (structA, n, 100.0 * structA / n))
    A("- It establishes that **%d of %d** are not tactic-selection failures at "
      "all but hallucinated lemma names or type errors.\n" % (not_tactic, n))
    A("- It does **not** establish that any of these are recoverable. \"This "
      "tactic was wrong\" is not \"a right tactic exists\". That is Phase 2's "
      "question and it is answered in `TACTIC_ORACLE.md`.\n")
    A("- Goal shape is assigned by regex over statement or error text, never by "
      "Lean's elaborated term. It is a bucketing aid, not a semantic "
      "classification, and a handful of borderline goals will be filed "
      "differently by a different set of patterns. Precedence is fixed in "
      "`tactic_common.SHAPES` and applied identically to every sample.\n")

    io.open(os.path.join(_ROOT, "results", "TACTIC_SELECTION.md"), "w",
            encoding="utf-8").write("\n".join(L) + "\n")

    data = {
        "n": n,
        "by_set": {st: sum(1 for x in samples if x["set"] == st) for st in tc.SET_ORDER},
        "lean_kind": dict(kinds),
        "not_tactic_selection": not_tactic,
        "crosstab_A_lean_attributed": {"%s|%s" % k: v for k, v in crossA.items()},
        "crosstab_B_body_attributed": {"%s|%s" % k: v for k, v in crossB.items()},
        "structural_direct_evidence": ns,
        "structural_direct_evidence_wilson": [round(lo, 4), round(hi, 4)],
        "structural_A_facevalue": structA, "structural_B_facevalue": structB,
        "omega_failures_with_nonlinear_atom":
            sum(1 for x in samples if x["omega_nonlinear_atom"]),
        "linarith_on_nonlinear_A": lin,
        "linarith_on_nonlinear_A_wilson": [round(lo2, 4), round(hi2, 4)],
        "vocabulary": dict(allt),
        "samples": [{k: x[k] for k in ("set", "id", "shape", "primary", "tactics",
                                        "lean_tactic", "lean_kind", "lean_shape",
                                        "lean_shape_source", "structural",
                                        "omega_nonlinear_atom", "goal", "outcome")}
                    for x in samples],
    }
    json.dump(data, io.open(os.path.join(_ROOT, "results", "tactic_selection.json"),
                            "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("wrote results/TACTIC_SELECTION.md and results/tactic_selection.json")
    print("n=%d  structural(direct)=%d  structural(facevalue)=%d  "
          "linarith-on-nonlinear=%d  not-tactic-selection=%d"
          % (n, ns, structA, lin, not_tactic))


if __name__ == "__main__":
    main()
