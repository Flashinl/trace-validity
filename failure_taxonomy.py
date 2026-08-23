"""Sub-classify `compile_error` into failure kinds, and tag arithmetic vs not.

Issue #14. The outcome taxonomy in verifier.py answers "what KIND of result is
this" -- valid, has_sorry, statement_error, unsound_axioms and so on. It
deliberately stops at `compile_error`, which is correct as far as it goes: every
one of those is a genuine Lean failure and a verdict on the model's proof.

But it collapses failures that mean entirely different things. An unknown
constant is a hallucinated Mathlib lemma. `decide` reporting the proposition
false means THE GOAL IS FALSE. "made no progress" is tactic selection.
"unsolved goals" is an incomplete proof. Diagnosis needs them apart.

Two independent axes
--------------------
`failure_kind` reads the compiler's own words. `arithmetic` answers a different
question -- was a NUMBER wrong, and whose -- and is NOT re-derived here: it is
joined from the labels already computed by tests/audit/provenance.py into
results/arithmetic_provenance.json. That pass substitutes hypotheses before
evaluating, which no regex over error text can do. One source of truth for the
arithmetic question; this module only maps its labels onto the axis.

Categories were derived from the observed inventory across both committed runs
(issue #14), not invented ahead of the data. Anything unrecognised becomes
`other` -- never a guess.
"""

import re
from collections import Counter

# ---------------------------------------------------------------------------
# Axis 1: what did the compiler actually say?
# ---------------------------------------------------------------------------
UNSOLVED_GOALS = "unsolved_goals"
TACTIC_NO_PROGRESS = "tactic_no_progress"
TACTIC_FAILED = "tactic_failed"
GOAL_IS_FALSE = "goal_is_false"
REWRITE_FAILED = "rewrite_failed"
RFL_FAILED = "rfl_failed"
UNKNOWN_IDENTIFIER = "unknown_identifier"
TYPE_MISMATCH = "type_mismatch"
NO_GOALS = "no_goals"
ELABORATION_ERROR = "elaboration_error"
OTHER = "other"

FAILURE_KINDS = (
    GOAL_IS_FALSE, UNKNOWN_IDENTIFIER, ELABORATION_ERROR, TYPE_MISMATCH,
    REWRITE_FAILED, RFL_FAILED, NO_GOALS, TACTIC_NO_PROGRESS, TACTIC_FAILED,
    UNSOLVED_GOALS, OTHER,
)

# Ordered MOST DIAGNOSTIC FIRST. This ordering is the precedence rule for a
# record carrying several errors, and it is not arbitrary:
#
#   goal_is_false      Lean evaluated the proposition and it is FALSE. That is a
#                      fact about the problem, not about the proof attempt, and
#                      it outranks any tactic complaint in the same record.
#   unknown_identifier the model named a lemma that does not exist. Everything
#                      downstream of it is a consequence, not a separate fault.
#   elaboration_error  the file did not elaborate; later errors are noise.
#
# ...down to `unsolved_goals`, which is the least specific real failure: it says
# the proof ended early but nothing about why.
_RULES = [
    # `decide` / `native_decide` refuting the proposition outright.
    (GOAL_IS_FALSE, re.compile(
        r"(?:native_)?decide.{0,40}?proved\s+that\s+the\s+proposition|"
        r"\bis\s+false\b", re.I | re.S)),
    (UNKNOWN_IDENTIFIER, re.compile(
        r"\bunknown\s+(?:constant|identifier|declaration)\b", re.I)),
    (ELABORATION_ERROR, re.compile(
        r"expected\s+type\s+must\s+not\s+contain\s+free\s+variables|"
        r"\bunexpected\s+token\b", re.I)),
    (TYPE_MISMATCH, re.compile(
        r"\btype\s+mismatch\b|\bfailed\s+to\s+synthesize\b", re.I)),
    (REWRITE_FAILED, re.compile(r"rewrite.{0,3}\s+failed", re.I)),
    (RFL_FAILED, re.compile(r"rfl.{0,3}\s+failed", re.I)),
    (NO_GOALS, re.compile(r"\bno\s+goals\s+to\s+be\s+solved\b", re.I)),
    (TACTIC_NO_PROGRESS, re.compile(r"made\s+no\s+progress", re.I)),
    (TACTIC_FAILED, re.compile(
        r"\b(?:n?linarith|polyrith|positivity|omega|decide|aesop|norm_num|"
        r"field_simp|simp_all|ring_nf)\b[^\n]{0,60}?"
        r"(?:failed|could\s+not\s+prove)", re.I)),
    # Generic catch for any OTHER named tactic: "Tactic `apply` failed: ...".
    # Deliberately last and deliberately generic. `rewrite` and `rfl` get their
    # own kinds above because they were frequent enough in the inventory to be
    # worth separating; everything else lands here rather than growing a
    # category per tactic name. Found by sample 30 of the T=0.2 run, which the
    # first-line inventory in issue #14 missed.
    (TACTIC_FAILED, re.compile(r"tactic\s+.{0,20}?\s*failed", re.I)),
    (UNSOLVED_GOALS, re.compile(r"\bunsolved\s+goals\b", re.I)),
]

# `_RULES` order IS the precedence order. A kind may appear more than once (a
# specific pattern and a general fallback), so FIRST occurrence wins -- a plain
# dict comprehension would keep the last index and silently demote the kind
# below everything between the two entries.
_PRECEDENCE = {}
for _i, (_kind, _) in enumerate(_RULES):
    _PRECEDENCE.setdefault(_kind, _i)


def classify_one(error_text):
    """Classify a single Lean error string. Unrecognised text -> `other`."""
    text = error_text or ""
    for kind, pattern in _RULES:
        if pattern.search(text):
            return kind
    return OTHER


def classify_compile_error(errors):
    """Classify a record from its list of Lean errors.

    A record may carry several errors. The most diagnostic one wins -- see the
    ordering rationale on `_RULES`. An empty list is `other`, not a crash: a
    record with no evidence gets no verdict beyond "unrecognised".
    """
    kinds = [classify_one(e) for e in (errors or [])]
    real = [k for k in kinds if k != OTHER]
    if not real:
        return OTHER
    return min(real, key=lambda k: _PRECEDENCE[k])


# ---------------------------------------------------------------------------
# Axis 2: was a NUMBER wrong, and whose?
# ---------------------------------------------------------------------------
# Joined from results/arithmetic_provenance.json. Do not re-derive from error
# text: that pass substitutes hypotheses into the goal before evaluating, which
# is the only way to see that `(x : N) (h0 : x = 101^2) : x = 10303` is false.
ARITH_STATEMENT = "statement_arithmetic"   # the DATASET's number is wrong
ARITH_PROOF = "proof_arithmetic"           # a number the MODEL wrote is wrong
ARITH_NONE = "not_arithmetic"              # no false number on either side
ARITH_UNKNOWN = "unknown"                  # no label available -- say so

_ARITH_MAP = {
    "statement_false": ARITH_STATEMENT,
    "proof_false": ARITH_PROOF,
    "tactic_mismatch": ARITH_NONE,
    "noop_tactic": ARITH_NONE,
    "parse_skew": ARITH_NONE,
    "budget": ARITH_NONE,
}


def arithmetic_axis(provenance_label):
    """Map a provenance label onto the arithmetic axis.

    An unrecognised or absent label returns `unknown`, never `not_arithmetic`.
    Reporting "we did not measure this" as "we measured no arithmetic" is how a
    denominator quietly becomes wrong.
    """
    if not provenance_label:
        return ARITH_UNKNOWN
    return _ARITH_MAP.get(provenance_label, ARITH_UNKNOWN)


# ---------------------------------------------------------------------------
# Record fields
# ---------------------------------------------------------------------------
# Outcomes that are genuine failures of the model's proof and therefore carry a
# failure_kind. `statement_error` / `statement_mismatch` / `parse_failure` are
# not verdicts on the proof (see verifier.py), so they are not sub-classified.
FAILING_OUTCOMES = ("compile_error",)


def record_failure_fields(res, provenance_label=None):
    """Build the failure-related fields of a trace record.

    LOSSLESS by contract (issue #14). The previous writer truncated to
    `errors[:5]` / `warnings[:3]` while writing `num_errors` from the full list,
    so a record could claim 9 errors while carrying 5, with nothing marking the
    gap. Raw compiler output is the evidence; it is never discarded.
    """
    errors = list(res.get("errors") or [])
    warnings = list(res.get("warnings") or [])
    is_failure = res.get("outcome") in FAILING_OUTCOMES
    return {
        "errors": errors,
        "warnings": warnings,
        # Derived from what is actually carried, so the count can never
        # disagree with the evidence beside it.
        "num_errors": len(errors),
        "failure_kind": classify_compile_error(errors) if is_failure else None,
        "arithmetic": arithmetic_axis(provenance_label) if is_failure else None,
    }


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------
def _pct(k, n):
    return f"{round(100.0 * k / n):d}%" if n else "-"


def summarize(records):
    """Counts and percentages per category, over FAILING records only.

    The denominator is the number of failures, not the number of records: "45%
    of failures were tactic selection" is the useful statement, and dividing by
    all records would silently mix it with the pass rate.
    """
    failures = [r for r in records if r.get("failure_kind")]
    n = len(failures)

    kinds = Counter(r["failure_kind"] for r in failures)
    arith = Counter(r.get("arithmetic") or ARITH_UNKNOWN for r in failures)

    out = {
        "total_records": len(records),
        "total_failures": n,
        "kinds": {k: {"n": v, "pct": _pct(v, n)} for k, v in kinds.items()},
        "arithmetic": {k: {"n": v, "pct": _pct(v, n)} for k, v in arith.items()},
    }

    lines = [f"FAILURE TAXONOMY  ({n} failures of {len(records)} records)", ""]
    lines.append(f"  {'failure_kind':<22}{'n':>5}  {'share of failures':>18}")
    lines.append(f"  {'-' * 22}{'-' * 5}  {'-' * 18}")
    for k in FAILURE_KINDS:
        if kinds.get(k):
            lines.append(f"  {k:<22}{kinds[k]:>5}  {_pct(kinds[k], n):>18}")
    lines.append("")
    lines.append(f"  {'arithmetic':<22}{'n':>5}  {'share of failures':>18}")
    lines.append(f"  {'-' * 22}{'-' * 5}  {'-' * 18}")
    for k in (ARITH_STATEMENT, ARITH_PROOF, ARITH_NONE, ARITH_UNKNOWN):
        if arith.get(k):
            lines.append(f"  {k:<22}{arith[k]:>5}  {_pct(arith[k], n):>18}")
    out["table"] = "\n".join(lines)
    return out
