"""Unit tests for provenance.proof_claims() -- the `proof_false` detector.

This decides whether a failure was caused by a number the MODEL wrote. On
FormalStep it reported 0/55 across three runs, which is a load-bearing finding.

On NuminaMath Number Theory it reported 9 `proof_false` labels, and all 9 were
spurious: the left-hand pattern could not cross a `%`, so it began matching
AFTER the modulo and captured the modulus alone.

    a^2 % 3 = 1   ->  read as `3 = 1`
    x^2 % 8 = 4   ->  read as `8 = 4`
    n % 7 = 6     ->  read as `7 = 6`

Nine flags, nine false positives -- no demonstrated precision on modular
arithmetic, which is pervasive in number theory and nearly absent from
FormalStep's Counting & Probability content.

These tests pin the fix in both directions: modular expressions must not be
misread, and a genuinely false arithmetic claim must still be caught.

Run: python tests/test_provenance_claims.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "audit"))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provenance import proof_claims  # noqa: E402

FAILURES = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<58} got={got!r}")
    if not ok:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def n_false(body, dom="nat"):
    bad, _checked, _lits = proof_claims(body, dom)
    return len(bad)


def flagged(body, dom="nat"):
    bad, _c, _l = proof_claims(body, dom)
    return bad


# --------------------------------------------------------------------------
print("THE REGRESSION -- modular case splits must not be misread")

MOD_CASES = [
    ("have h : a^2 % 3 = 0 ∨ a^2 % 3 = 1 := by omega\n", "a^2 % 3"),
    ("have : x^2 % 8 = 0 ∨ x^2 % 8 = 1 ∨ x^2 % 8 = 4 := by decide\n", "x^2 % 8"),
    ("have h : n % 7 = 0 ∨ n % 7 = 1 ∨ n % 7 = 6 := by omega\n", "n % 7"),
    ("interval_cases c <;> simp [Nat.pow_mod] <;> omega\n", "no equality"),
]
for body, what in MOD_CASES:
    check(f"{what:<12} -> no false claim", n_false(body), 0)

print("\n  a closed modular claim is SKIPPED, not flagged")
# 17 % 5 = 2 is TRUE; 17 % 5 = 3 is FALSE. Neither may be flagged, because
# lean_arith does not implement `%` -- skipping is the safe direction.
check("closed true modulo not flagged", n_false("have : 17 % 5 = 2 := by decide\n"), 0)
check("closed FALSE modulo not flagged either (skipped, not checked)",
      n_false("have : 17 % 5 = 3 := by decide\n"), 0)

# --------------------------------------------------------------------------
print("\nGenuinely false arithmetic must STILL be caught")

check("2 + 2 = 5 is flagged", n_false("have h : 2 + 2 = 5 := by norm_num\n"), 1)
check("101^2 = 10303 is flagged", n_false("have h : 101^2 = 10303 := by norm_num\n"), 1)
check("9! * 5! = 7257600 is flagged",
      n_false("have h : 9! * 5! = 7257600 := by decide\n"), 1)

print("\n  ...and true arithmetic is not")
check("2 + 2 = 4 not flagged", n_false("have h : 2 + 2 = 4 := by norm_num\n"), 0)
check("101^2 = 10201 not flagged", n_false("have h : 101^2 = 10201 := by norm_num\n"), 0)

print("\n  the flag text names the actual claim")
f = flagged("have h : 2 + 2 = 5 := by norm_num\n")
check("flag mentions both sides", bool(f) and "2 + 2" in f[0] and "5" in f[0], True)

# --------------------------------------------------------------------------
print("\nMixed body: a real error alongside modular case splits")

mixed = (
    "have h₁ : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega\n"
    "have h₂ : 6 * 7 = 41 := by norm_num\n"
    "have h₃ : x^2 % 4 = 1 := by omega\n"
)
check("only the genuinely false claim is flagged", n_false(mixed), 1)
f = flagged(mixed)
check("  and it is the 6 * 7 one", bool(f) and "6 * 7" in f[0], True)

# --------------------------------------------------------------------------
print("\nNon-numeric and open claims are skipped, not flagged")
check("free variables -> skipped", n_false("have : a + b = c := by ring\n"), 0)
check("empty body -> nothing", n_false(""), 0)
check("comments only -> nothing", n_false("-- 2 + 2 = 5 in a comment\n"), 0)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES:")
    for f_ in FAILURES:
        print(f"  - {f_}")
    sys.exit(1)
print("all provenance-claim tests pass")
