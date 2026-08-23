"""Unit tests for verify_traces.statement_mismatch().

This is the guard that decides whether a compiled file is a proof of the
DATASET'S theorem or of something else. It is the check issue #11 was really
about, and 28 of the 90 Stage B passes rest on it being right.

It also had a real bug: it substring-matched the WHOLE statement, which silently
assumed the dataset's statement carries no preamble. FormalStep statements are
bare `theorem ... := by`, so that held for 100 records. NuminaMath statements
open with their own `import Mathlib` and a doc comment, and our header goes
between that import and the theorem line -- so the statement stopped being a
contiguous substring and 28 genuine passes were rejected.

The fix must not weaken the guard. These tests pin both directions: preamble
noise is ignored, and a file that proves something ELSE still fails.

Run: python tests/test_statement_mismatch.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from verify_traces import statement_mismatch, _declaration_part  # noqa: E402

FAILURES = []


def check(name, got_bad, want_bad, detail=""):
    ok = got_bad == want_bad
    verdict = "mismatch" if got_bad else "match"
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<56} -> {verdict}")
    if not ok:
        FAILURES.append(f"{name}: got bad={got_bad}, want bad={want_bad} ({detail})")


def check_true(name, got, detail=""):
    """For plain boolean assertions, where match/mismatch is not the question."""
    print(f"  {'PASS' if got else 'FAIL'}  {name:<56} -> {bool(got)}")
    if not got:
        FAILURES.append(f"{name} ({detail})")


OUR_HEADER = (
    "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\n"
    "open BigOperators Real Nat Topology Rat\n\n"
)

# ---------------------------------------------------------------------------
print("FormalStep shape -- bare statement, no preamble of its own")

FS_STMT = "theorem test (n : ℕ) (h₀ : n = 6) : (n = 6) := by"
compiled = OUR_HEADER + FS_STMT + "\n  exact h₀\n"
bad, why = statement_mismatch(compiled, FS_STMT)
check("bare statement matches", bad, False, why)

# ---------------------------------------------------------------------------
print("\nNuminaMath shape -- THE REGRESSION: statement carries its own preamble")

NM_STMT = (
    "import Mathlib\n\n"
    "/- Show that for any natural number n, n^3 + (n+1)^3 + (n+2)^3 is divisible by 9. -/\n"
    "theorem number_theory_84195 (n : ℕ) : 9 ∣ n^3 + (n + 1)^3 + (n + 2)^3 := by"
)
# What actually gets compiled: OUR header, their doc comment + theorem.
nm_compiled = (
    OUR_HEADER
    + "/- Show that for any natural number n, n^3 + (n+1)^3 + (n+2)^3 is divisible by 9. -/\n"
    + "theorem number_theory_84195 (n : ℕ) : 9 ∣ n^3 + (n + 1)^3 + (n + 2)^3 := by\n"
    + "  decide\n"
)
bad, why = statement_mismatch(nm_compiled, NM_STMT)
check("header inserted between their import and theorem still matches",
      bad, False, why)

print("\n  ...and it is not matching by accident: the theorem must still be there")
wrong_thm = (
    OUR_HEADER
    + "/- Show that for any natural number n, n^3 + (n+1)^3 + (n+2)^3 is divisible by 9. -/\n"
    + "theorem number_theory_84195 (n : ℕ) : 7 ∣ n^3 + (n + 1)^3 + (n + 2)^3 := by\n"
    + "  decide\n"
)
bad, why = statement_mismatch(wrong_thm, NM_STMT)
check("same doc comment but 9 changed to 7 -> mismatch", bad, True, why)

# ---------------------------------------------------------------------------
print("\nA genuinely different theorem must still fail")

other = OUR_HEADER + "theorem test (n : ℕ) (h₀ : n = 7) : (n = 7) := by\n  exact h₀\n"
bad, why = statement_mismatch(other, FS_STMT)
check("different binder value -> mismatch", bad, True, why)

renamed = OUR_HEADER + "theorem other_name (n : ℕ) (h₀ : n = 6) : (n = 6) := by\n  exact h₀\n"
bad, why = statement_mismatch(renamed, FS_STMT)
check("different theorem NAME -> mismatch", bad, True, why)

weaker = OUR_HEADER + "theorem test (n : ℕ) : True := by\n  trivial\n"
bad, why = statement_mismatch(weaker, FS_STMT)
check("proves `True` instead of the goal -> mismatch", bad, True, why)

empty = OUR_HEADER + "\n"
bad, why = statement_mismatch(empty, FS_STMT)
check("no declaration at all -> mismatch", bad, True, why)

# ---------------------------------------------------------------------------
print("\nMultiple declarations must still fail")

two = (OUR_HEADER
       + "theorem helper (a : ℕ) : a = a := by rfl\n\n"
       + FS_STMT + "\n  exact h₀\n")
bad, why = statement_mismatch(two, FS_STMT)
check("target plus a helper lemma -> mismatch", bad, True, why)

two_after = (OUR_HEADER + FS_STMT + "\n  exact h₀\n\n"
             + "lemma extra (a : ℕ) : a = a := by rfl\n")
bad, why = statement_mismatch(two_after, FS_STMT)
check("helper lemma AFTER the target -> mismatch", bad, True, why)

print("\n  a declaration inside a comment does not count")
commented = (OUR_HEADER
             + "/- theorem helper (a : ℕ) : a = a := by rfl -/\n"
             + FS_STMT + "\n  exact h₀\n")
bad, why = statement_mismatch(commented, FS_STMT)
check("commented-out lemma is ignored", bad, False, why)

# ---------------------------------------------------------------------------
print("\n_declaration_part() -- drops preamble, keeps the whole declaration")

got = _declaration_part(NM_STMT)
check_true("import line dropped", got.startswith("theorem number_theory_84195"), got[:40])
check_true("goal retained", "9 ∣ n^3 + (n + 1)^3 + (n + 2)^3 := by" in got)
check_true("text with no declaration returns unchanged",
           _declaration_part("import Mathlib\n") == "import Mathlib\n")
check_true("empty input is safe", _declaration_part("") == "")
check_true("None is safe", _declaration_part(None) == "")

# ---------------------------------------------------------------------------
print("\nAbsent statement is not a verdict")
bad, why = statement_mismatch(OUR_HEADER + FS_STMT, "")
check("no formal_statement -> cannot check, not a mismatch", bad, False, why)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all statement_mismatch tests pass")
