"""Unit tests for failure_taxonomy.py.

Every error string below is VERBATIM from a committed results file -- see the
inventory in issue #14. The categories were derived from those strings, not
invented ahead of the data, so these tests pin the classifier against real Lean
output rather than against a guess about what Lean emits.

Run: python tests/test_failure_taxonomy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from failure_taxonomy import (  # noqa: E402
    classify_compile_error, arithmetic_axis, summarize, record_failure_fields,
    FAILURE_KINDS, UNSOLVED_GOALS, TACTIC_NO_PROGRESS, TACTIC_FAILED,
    GOAL_IS_FALSE, REWRITE_FAILED, RFL_FAILED, UNKNOWN_IDENTIFIER,
    TYPE_MISMATCH, NO_GOALS, ELABORATION_ERROR, OTHER,
    ARITH_STATEMENT, ARITH_PROOF, ARITH_NONE, ARITH_UNKNOWN,
)

FAILURES = []


def check_eq(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<58} got={got!r}")
    if not ok:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


# --------------------------------------------------------------------------
print("classify_compile_error() -- verbatim strings from the committed runs")

CASES = [
    # (error string, expected kind)
    ("unsolved goals\n⊢ False", UNSOLVED_GOALS),
    ("linarith failed to find a contradiction\ncase a\n⊢ False", TACTIC_FAILED),
    ("omega could not prove the goal:\na possible counterexample", TACTIC_FAILED),
    ("`ring_nf` made no progress on the goal", TACTIC_NO_PROGRESS),
    ("`simp` made no progress", TACTIC_NO_PROGRESS),
    ("simp_all made no progress", TACTIC_NO_PROGRESS),
    ("Tactic `rewrite` failed: Did not find an occurrence of the pattern",
     REWRITE_FAILED),
    ("Tactic `rfl` failed: The left-hand side\n  x", RFL_FAILED),
    ("Tactic `rfl` failed: Expected the goal to be a binary relation", RFL_FAILED),
    ("Unknown constant `Real.sqrt_eq_iff_sq_eq`", UNKNOWN_IDENTIFIER),
    ("Type mismatch: After simplification, term", TYPE_MISMATCH),
    ("No goals to be solved", NO_GOALS),
    ("Expected type must not contain free variables", ELABORATION_ERROR),
    # Sample 30 of the T=0.2 run. The first-line inventory in issue #14 missed
    # this family; a generic "Tactic `X` failed" fallback covers it and any
    # other named tactic without growing a category per tactic name.
    ("Tactic `apply` failed: could not unify the conclusion of `@Eq.refl`",
     TACTIC_FAILED),
]
for err, want in CASES:
    check_eq(f"{err.splitlines()[0][:48]!r}", classify_compile_error([err]), want)

print("\n  `decide` proving the goal FALSE is not merely a failed tactic")
check_eq(
    "decide-proved-false -> goal_is_false",
    classify_compile_error(
        ["Tactic `decide` proved that the proposition\n  9! * 5! = 7257600\nis false"]
    ),
    GOAL_IS_FALSE,
)

print("\n  every kind is a declared member of FAILURE_KINDS")
for err, want in CASES:
    if want not in FAILURE_KINDS:
        FAILURES.append(f"{want} missing from FAILURE_KINDS")
check_eq("all expected kinds declared", True,
         all(w in FAILURE_KINDS for _, w in CASES))

print("\n  unrecognised text falls back to `other`, never to a guess")
check_eq("novel string -> other",
         classify_compile_error(["some Lean 5 diagnostic nobody has seen"]), OTHER)
check_eq("empty error list -> other", classify_compile_error([]), OTHER)

print("\n  precedence: the most diagnostic error in a record wins")
check_eq(
    "goal_is_false beats unsolved goals",
    classify_compile_error(["unsolved goals\n⊢ False",
                            "Tactic `decide` proved that the proposition\nis false"]),
    GOAL_IS_FALSE,
)
check_eq(
    "unknown_identifier beats unsolved goals",
    classify_compile_error(["unsolved goals", "Unknown constant `Foo.bar`"]),
    UNKNOWN_IDENTIFIER,
)
check_eq(
    "the generic tactic fallback still outranks unsolved goals",
    classify_compile_error(["unsolved goals", "Tactic `apply` failed: could not unify"]),
    TACTIC_FAILED,
)

# --------------------------------------------------------------------------
print("\narithmetic_axis() -- joined from arithmetic_provenance labels")
check_eq("statement_false -> statement arithmetic",
         arithmetic_axis("statement_false"), ARITH_STATEMENT)
check_eq("proof_false -> proof arithmetic",
         arithmetic_axis("proof_false"), ARITH_PROOF)
check_eq("tactic_mismatch -> not arithmetic",
         arithmetic_axis("tactic_mismatch"), ARITH_NONE)
check_eq("noop_tactic -> not arithmetic",
         arithmetic_axis("noop_tactic"), ARITH_NONE)
check_eq("parse_skew -> not arithmetic",
         arithmetic_axis("parse_skew"), ARITH_NONE)
check_eq("UNKNOWN -> unknown, not silently 'not arithmetic'",
         arithmetic_axis("UNKNOWN"), ARITH_UNKNOWN)
check_eq("missing label -> unknown", arithmetic_axis(None), ARITH_UNKNOWN)

# --------------------------------------------------------------------------
print("\nrecord_failure_fields() -- LOSSLESS, and count agrees with evidence")
res = {
    "outcome": "compile_error",
    "errors": [f"error number {i}" for i in range(9)],
    "warnings": [f"warning {i}" for i in range(7)],
    "num_errors": 9,
}
fields = record_failure_fields(res, provenance_label="tactic_mismatch")
check_eq("all 9 errors survive the record write", len(fields["errors"]), 9)
check_eq("all 7 warnings survive", len(fields["warnings"]), 7)
check_eq("num_errors agrees with the evidence carried",
         fields["num_errors"], len(fields["errors"]))
check_eq("failure_kind is set", fields["failure_kind"], OTHER)
check_eq("arithmetic axis is set", fields["arithmetic"], ARITH_NONE)

print("\n  a non-failure outcome carries no failure_kind")
ok = record_failure_fields({"outcome": "valid", "errors": [], "warnings": [],
                            "num_errors": 0}, provenance_label=None)
check_eq("valid -> failure_kind None", ok["failure_kind"], None)

# --------------------------------------------------------------------------
print("\nsummarize() -- counts and percentages per category")
recs = [
    {"outcome": "compile_error", "failure_kind": UNSOLVED_GOALS, "arithmetic": ARITH_NONE},
    {"outcome": "compile_error", "failure_kind": UNSOLVED_GOALS, "arithmetic": ARITH_NONE},
    {"outcome": "compile_error", "failure_kind": TACTIC_FAILED, "arithmetic": ARITH_STATEMENT},
    {"outcome": "valid", "failure_kind": None, "arithmetic": None},
]
s = summarize(recs)
check_eq("only failures counted", s["total_failures"], 3)
check_eq("unsolved_goals counted", s["kinds"][UNSOLVED_GOALS]["n"], 2)
check_eq("percentage is of failures, not of all records",
         s["kinds"][UNSOLVED_GOALS]["pct"], "67%")
check_eq("arithmetic split reported", s["arithmetic"][ARITH_STATEMENT]["n"], 1)
check_eq("table renders", isinstance(s["table"], str) and "unsolved_goals" in s["table"], True)

# --------------------------------------------------------------------------
print("\nrender_taxonomy() -- the end-of-run block, which shipped broken once")

from verify_traces import render_taxonomy  # noqa: E402

_fail = {"outcome": "compile_error", "failure_kind": UNSOLVED_GOALS,
         "arithmetic": ARITH_UNKNOWN}
_pass = {"outcome": "valid", "failure_kind": None, "arithmetic": None}

out = render_taxonomy([_pass, _fail, _fail], 3)
check_eq("renders a table when records were collected",
         "FAILURE TAXONOMY" in out and "unsolved_goals" in out, True)

# THE REGRESSION. The first version guarded on a `written` list that the run
# loop never appended to, so `if written:` was always False and the table
# silently never printed -- while every unit test here passed, because they
# covered summarize() and nothing covered the wiring. An n=3 live run caught it.
# A count mismatch must now be LOUD.
out = render_taxonomy([], 3)
check_eq("0 collected for 3 verified is reported as a bug, not as silence",
         "[warn]" in out and "collected 0 record(s) for 3" in out, True)
check_eq("  and it does not render an empty string", out.strip() != "", True)

out = render_taxonomy([_pass, _fail], 3)
check_eq("a partial collection is also reported", "[warn]" in out, True)

out = render_taxonomy([_pass, _pass], 2)
check_eq("all-pass run says so rather than printing an empty table",
         "no failures among 2 records" in out, True)

check_eq("a genuinely empty run renders nothing", render_taxonomy([], 0), "")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all failure-taxonomy tests pass")
