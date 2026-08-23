"""Why FormalStep produces trivial statements and NuminaMath cannot.

The vacuity scan counted trivial passes. This measures the MECHANISM that makes
them possible, across whole datasets rather than across the 37 passes we happened
to sample -- which is the number that generalises.

The pattern
-----------
A binder of the form `h₀ : var = <literal>` PINS a variable to a constant. Once
present, substituting it can collapse the goal to `X = X`:

    theorem test (friends teams : ℕ) (h₀ : friends = 6) (h₁ : teams = 3)
        : (3 ^ friends = 3 ^ 6) := by      -- substitute h₀ -> `3^6 = 3^6`

That is `4_syntactic_tautology`, the largest trivial class in the pass set (8 of
14). `3_goal_restates_a_hypothesis` needs the same pattern.

Why step-level formalization produces it. FormalStep formalizes ONE chain-of-
thought step. A step's inputs are whatever earlier steps computed, so the
formalization has to supply them -- as equality hypotheses pinning each to its
value. The pins are not sloppiness; they are what makes a single step
self-contained.

Why whole-problem statements cannot. A problem statement quantifies over its
variables (`∀ n : ℕ`) or fixes them in the goal, because nothing earlier has
computed anything yet. There is no prior step whose output needs pinning, so the
substitution-to-tautology route is structurally unavailable.

Run: python tests/audit/pinned_hypothesis_scan.py
"""

import collections
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provenance import split_binders_goal  # noqa: E402
from data_loader import normalize_formal_statement  # noqa: E402
from stats import wilson, pct  # noqa: E402

OUT = os.path.join(ROOT, "results", "pinned_hypothesis_scan.json")
NUMINA_PARQUET = (
    os.path.expanduser("~/.cache/huggingface/hub/datasets--AI-MO--NuminaMath-LEAN"
                       "/snapshots/51fa67f1f647ae1ecd81eef9f19306aa8a7b3a94"
                       "/data/train-00000-of-00001.parquet"))

_IDENT = re.compile(r"^[A-Za-z_][\w₀-₉']*$")
# A right-hand side that looks CLOSED: a numeral, a list, or a constructor
# application. Deliberately conservative -- a false negative understates the
# pattern, which is the safe direction for the claim being made.
_LITERAL = re.compile(r"^\s*(?:-?\d|\[|Nat\.|Finset\.|\()")
_IMPORT = re.compile(r"^[ \t]*import[ \t]+[\w.]+[ \t]*$", re.M)


def count_pinned(stmt, normalise=True):
    """How many binders pin a variable to a closed literal."""
    text = stmt or ""
    if normalise:
        try:
            text = normalize_formal_statement(text)
        except Exception:  # noqa: BLE001
            pass
    text = _IMPORT.sub("", text).lstrip()
    try:
        props, _goal = split_binders_goal(text)
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    for p in props:
        if "=" not in p:
            continue
        lhs, _, rhs = p.partition("=")
        if _IDENT.match(lhs.strip()) and _LITERAL.match(rhs):
            n += 1
    return n


def scan_formalstep():
    from datasets import load_dataset
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    ds = load_dataset("liuchengwu/FormalStep", split="train")
    stmts, pids = ds["formal_statement"], ds["problem_unique_id"]
    rows_with, per_problem = 0, collections.defaultdict(int)
    for s, pid in zip(stmts, pids):
        if count_pinned(s) > 0:
            rows_with += 1
            per_problem[pid] += 1
    return {"rows": len(stmts), "rows_with_pinned": rows_with,
            "problems": len(set(pids)), "problems_with_pinned": len(per_problem)}


def scan_numinamath():
    import pandas as pd
    df = pd.read_parquet(NUMINA_PARQUET)
    pool = df[(df.problem_type == "Number Theory")
              & (df.question_type == "proof")
              & (df.formal_proof.fillna("").str.strip() != "")]
    n_pool = sum(1 for s in pool.formal_statement if count_pinned(s, normalise=False) > 0)
    n_all = sum(1 for s in df.formal_statement if count_pinned(s, normalise=False) > 0)
    return {"rows": int(len(df)), "rows_with_pinned": int(n_all),
            "nt_proof_pool": int(len(pool)), "nt_proof_pool_with_pinned": int(n_pool)}


def line(label, k, n):
    lo, hi = wilson(k, n)
    return f"  {label:<52}{k:>7,}/{n:<7,} = {pct(k/n):>4}  [{pct(lo)}-{pct(hi)}]"


def main():
    print("scanning FormalStep ...")
    fs = scan_formalstep()
    print("scanning NuminaMath-LEAN ...")
    nm = scan_numinamath()

    print("\n" + "=" * 78)
    print("`h : var = <literal>` PINNED HYPOTHESES")
    print("=" * 78)
    print("\nFormalStep (step-level: one row per chain-of-thought step)")
    print(line("statements with >=1 pinned hypothesis",
               fs["rows_with_pinned"], fs["rows"]))
    print(line("problems with >=1 such statement",
               fs["problems_with_pinned"], fs["problems"]))
    print("\nNuminaMath-LEAN (problem-level: one row per whole problem)")
    print(line("Number Theory + proof pool",
               nm["nt_proof_pool_with_pinned"], nm["nt_proof_pool"]))
    print(line("whole dataset", nm["rows_with_pinned"], nm["rows"]))

    doc = {"formalstep": fs, "numinamath": nm}
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
