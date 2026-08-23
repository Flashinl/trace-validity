"""How much of FormalStep asserts something arithmetically false?

The sampled 50 are not the benchmark. `results/ARITHMETIC_FINDINGS.md` measured
false statements among the samples we happened to draw and among the failures we
happened to see; this pass measures the whole split -- every one of the 30,809
`formal_statement` rows across all 500 problems -- so the rate is a property of
the benchmark rather than of our sample.

Why it matters. A false statement damages the measurement in BOTH directions:

  * it cannot be proved, so the model fails and we log `compile_error` --
    scoring the dataset's error against the prover; measured at 36-62% of
    failures.
  * OR its hypotheses are mutually inconsistent, `False` follows, every goal
    follows, and a proof of it compiles -- so we log a PASS. Sample 42.

The second direction inflates the headline. This pass sizes the population it
can be drawn from.

Method. Reuses `provenance.analyse()`, which is the load-bearing part: it binds
every hypothesis of the form `var = <closed expr>` and re-evaluates every other
claim under that environment. `(x : N) (h0 : x = 101^2) : x = 10303` contains no
false equality until h0 is substituted. Arithmetic is exact -- Fraction/int,
never float -- because the literals run to 13 digits and a float round-trip
would silently agree with a wrong answer.

Scope and honesty about it. This finds statements whose CLOSED arithmetic is
false. It cannot see a statement that is false for a non-arithmetic reason, and
it says nothing about statements whose claims never close. Every row is
therefore labelled with which of those happened, and the denominators are
reported separately. `checkable` is the only honest denominator for a rate.

Reads only the dataset. No Lean, no GPU.
Run: python tests/audit/statement_truth_scan.py
"""

import collections
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provenance import analyse, domain_of, split_binders_goal  # noqa: E402
from data_loader import normalize_formal_statement  # noqa: E402
from stats import wilson, pct  # noqa: E402

OUT_JSON = os.path.join(ROOT, "results", "statement_truth_scan.json")

# Row labels. Ordered most-severe first; a row gets exactly one.
FALSE_HYP_AND_GOAL = "false_hypothesis_and_goal"
FALSE_HYPOTHESIS = "false_hypothesis"   # <- the vacuity-producing class
FALSE_GOAL = "false_goal"               # <- the unprovable class
TRUE_CHECKED = "checked_true"
NOT_CLOSED = "nothing_closed"           # no claim could be evaluated
NO_GOAL = "unparsed"                    # statement did not split


def _normalise(stmt):
    """data_loader's normalisation, but never fatal: a row that will not
    normalise is labelled, not raised on."""
    try:
        return normalize_formal_statement(stmt)
    except Exception:  # noqa: BLE001
        return stmt or ""



def label_row(stmt):
    """(label, detail, n_claims_checked).

    The statement is NORMALISED first. Raw FormalStep rows end `:= by sorry`,
    and split_binders_goal() only strips a trailing `:= by`, so an un-normalised
    row leaves `sorry` inside the goal, nothing evaluates, and the row is
    silently counted as `nothing_closed`. That is what the prover is actually
    given, too -- data_loader applies the same normalisation before prompting.
    """
    stmt = _normalise(stmt)
    try:
        props, goal = split_binders_goal(stmt)
    except Exception as e:  # noqa: BLE001
        return NO_GOAL, f"split failed: {type(e).__name__}", 0
    if not (goal or "").strip():
        return NO_GOAL, "no goal recovered", 0

    try:
        _env, bad_hyp, bad_goal, checked = analyse(stmt, domain_of(stmt))
    except Exception as e:  # noqa: BLE001
        return NO_GOAL, f"analyse failed: {type(e).__name__}", 0

    if checked == 0:
        return NOT_CLOSED, "no claim evaluated to a closed value", 0
    if bad_hyp and bad_goal:
        return FALSE_HYP_AND_GOAL, bad_hyp[0][:160], checked
    if bad_hyp:
        return FALSE_HYPOTHESIS, bad_hyp[0][:160], checked
    if bad_goal:
        return FALSE_GOAL, bad_goal[0][:160], checked
    return TRUE_CHECKED, "", checked


def main():
    from datasets import load_dataset

    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    print("loading liuchengwu/FormalStep ...")
    ds = load_dataset("liuchengwu/FormalStep", split="train")
    n = len(ds)
    print(f"{n} rows\n")

    stmts = ds["formal_statement"]
    pids = ds["problem_unique_id"]

    rows = []
    counts = collections.Counter()
    per_problem = collections.defaultdict(collections.Counter)

    for i, (stmt, pid) in enumerate(zip(stmts, pids)):
        label, detail, checked = label_row(stmt)
        counts[label] += 1
        per_problem[pid][label] += 1
        if label in (FALSE_HYPOTHESIS, FALSE_GOAL, FALSE_HYP_AND_GOAL):
            rows.append({"row": i, "problem_unique_id": pid, "label": label,
                         "detail": detail, "claims_checked": checked,
                         "statement": (stmt or "")[:400]})
        if (i + 1) % 5000 == 0:
            print(f"  {i + 1}/{n} ...")

    # The only honest denominator: rows where at least one claim closed.
    checkable = (counts[TRUE_CHECKED] + counts[FALSE_HYPOTHESIS]
                 + counts[FALSE_GOAL] + counts[FALSE_HYP_AND_GOAL])
    false_any = counts[FALSE_HYPOTHESIS] + counts[FALSE_GOAL] + counts[FALSE_HYP_AND_GOAL]
    false_hyp_any = counts[FALSE_HYPOTHESIS] + counts[FALSE_HYP_AND_GOAL]

    print("\n" + "=" * 70)
    print("ROW LABELS (all 30,809 statements)")
    for k in (FALSE_HYP_AND_GOAL, FALSE_HYPOTHESIS, FALSE_GOAL, TRUE_CHECKED,
              NOT_CLOSED, NO_GOAL):
        if counts[k]:
            print(f"  {k:<28}{counts[k]:>7}  ({pct(counts[k] / n)} of all rows)")

    print(f"\nCHECKABLE ROWS (>=1 claim closed): {checkable} of {n} "
          f"({pct(checkable / n)})")
    print("Rates below use `checkable` as the denominator -- a row whose claims")
    print("never close is not evidence either way and leaves both sides.\n")

    for label, k in (("statement asserts something FALSE", false_any),
                     ("  ...of which a FALSE HYPOTHESIS (vacuity risk)", false_hyp_any),
                     ("  ...of which only a FALSE GOAL (unprovable)", counts[FALSE_GOAL])):
        lo, hi = wilson(k, checkable) if checkable else (0, 0)
        print(f"  {label:<48}{k:>6}/{checkable} = {pct(k / checkable) if checkable else '-':>5}"
              f"   [{pct(lo)}-{pct(hi)}]")

    # Per problem: a problem is "affected" if any of its steps is false.
    affected = sum(1 for pid, c in per_problem.items()
                   if c[FALSE_HYPOTHESIS] or c[FALSE_GOAL] or c[FALSE_HYP_AND_GOAL])
    nprob = len(per_problem)
    lo, hi = wilson(affected, nprob)
    print(f"\nPER PROBLEM: {affected} of {nprob} problems have at least one "
          f"arithmetically false step = {pct(affected / nprob)}  [{pct(lo)}-{pct(hi)}]")

    doc = {
        "dataset": "liuchengwu/FormalStep",
        "split": "train",
        "rows": n,
        "problems": nprob,
        "row_labels": dict(counts),
        "checkable_rows": checkable,
        "false_any": false_any,
        "false_hypothesis_any": false_hyp_any,
        "false_goal_only": counts[FALSE_GOAL],
        "problems_with_a_false_step": affected,
        "false_rows": rows,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nwrote {OUT_JSON}  ({len(rows)} false statements recorded)")


if __name__ == "__main__":
    main()
