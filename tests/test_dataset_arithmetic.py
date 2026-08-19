"""Mechanically check every numeric claim quoted in any report.

The reports assert arithmetic in prose. Prose is not checked by anything, so
these assertions are checked here, exactly, with integers and Fractions -- never
floats. The literals run to 13 digits and a float round-trip would silently agree
with a wrong answer.

BOTH DIRECTIONS MATTER. A checker that flags true statements is worse than no
checker, because it manufactures findings. The TRUE cases below are as much a
part of the suite as the false ones.

Run: python tests/test_dataset_arithmetic.py
"""
import os
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "audit"))
sys.path.insert(0, os.path.dirname(HERE))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lean_arith import evaluate  # noqa: E402

FAILURES = []

# (lhs, rhs, domain, expected_equal, note)
CLAIMS = [
    # --- claims the reports say are FALSE -------------------------------------
    ("101^2", "10301", "nat", False, "quoted in SUMMARY.md; truth is 10201"),
    ("1061520.150601", "10303 * 103", "field", False, "truth is 1061209"),
    ("1061520150601", "1.061520150601e9", "field", False, "off by 1000x"),
    ("100^3 + 3*100^2*6 + 10800", "1061520150601", "nat", False, "LHS is 1190800"),
    ("1061520150601", "(100 + 6)^6", "nat", False, "106^6 = 1418519112256"),
    ("9! * 5! * 2!", "7257600", "nat", False, "truth is 87091200"),
    ("8! * 6!", "40320", "nat", False, "truth is 29030400"),
    ("(9!*5!*2!)/(8!*6!)", "9", "nat", False, "truth is 3"),
    ("(11! / (9! + 2 * 8!))", "(11 * 10 / (9 + 2))", "nat", False, "90 vs 10"),
    ("(6! + 7!) / 5!", "8", "nat", False, "truth is 48"),
    ("5 / 6", "1 - 1 / 6", "nat", False, "true over Q, FALSE over N where 5/6 = 0"),

    # --- claims that are TRUE and must NOT be flagged -------------------------
    ("101^6", "1061520150601", "nat", True, "MUST NOT FLAG -- this one is right"),
    ("103^3", "1092727", "nat", True, "MUST NOT FLAG"),
    ("100^3 + 3*100^2*6 + 10800", "1190800", "nat", True, "true as written"),
    ("101^2", "10201", "nat", True, "the correct value"),
    ("5 / 6", "1 - 1 / 6", "field", True, "the same claim is TRUE over Q"),
    ("Nat.choose 52 3", "22100", "nat", True, ""),
    ("Nat.choose 8 4", "70", "nat", True, ""),
    ("Nat.factorial 4", "24", "nat", True, ""),
    ("Nat.factorial 9", "9*8*7*6*5*4*3*2*1", "nat", True, ""),
    ("Nat.choose 1996 4", "1996*1995*1994*1993/(4*3*2*1)", "nat", True, ""),
    ("(1/4)^3 * (3/4)^3", "27/4096", "field", True, ""),
]


def run():
    print(f"{'claim':<52}{'domain':<8}{'expect':<9}{'got':<9}result")
    for lhs, rhs, dom, want, note in CLAIMS:
        try:
            lv, rv = evaluate(lhs, dom), evaluate(rhs, dom)
            got = (lv == rv)
            detail = f"{lv} vs {rv}" if not got else str(lv)
        except Exception as e:  # noqa: BLE001
            got, detail = None, f"ERROR {type(e).__name__}: {e}"
        ok = got == want
        if not ok:
            FAILURES.append((lhs, rhs, want, got, detail))
        claim = f"{lhs} = {rhs}"
        print(f"{claim[:51]:<52}{dom:<8}{str(want):<9}{str(got):<9}"
              f"{'OK' if ok else '** MISMATCH **'}")
        if note and ok:
            print(f"{'':<52}{'':<8}-> {detail}   ({note})")

    print()
    n_false = sum(1 for c in CLAIMS if not c[3])
    n_true = sum(1 for c in CLAIMS if c[3])
    print(f"{n_false} claims asserted FALSE, {n_true} asserted TRUE "
          f"(the true ones guard against a checker that manufactures findings)")
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print("   ", f)
        return 1
    print(f"all {len(CLAIMS)} arithmetic claims verified")
    return 0


if __name__ == "__main__":
    sys.exit(run())
