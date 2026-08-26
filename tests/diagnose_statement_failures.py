"""Evidence that some `compile_error`s are rejections of the STATEMENT, not the proof.

Answers a specific question: when a trace comes back `compile_error`, is Lean
judging the model's proof, or is it refusing the file before the proof is
reached? For two samples the answer is the latter, and this script demonstrates
it rather than asserting it.

  python tests/diagnose_statement_failures.py

Each case verifies a hand-built snippet, so nothing here depends on the model.
The control in every pair is the SAME statement with one thing changed.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import verifier as verifier_mod
from config import GOEDEL_LEAN4_HEADER
from verifier import LeanVerifier, BROKEN

# Sample 19's statement, verbatim from FormalStep. Note `∑ n in Finset.range 6`:
# Mathlib retired `in` for `∈` in big operators, so this does not parse on
# v4.32.0. The model's proof is deliberately replaced by `sorry` — if the file
# still fails, the failure cannot be the proof's fault.
S19 = """theorem test
  (f : ℕ → ℕ)
  (h₀ : ∀ n, f n = n^2)
  (p : ℕ → ℚ)
  (h₁ : ∀ n, p n = 1/6) :
  (∑ n {IN} Finset.range 6, p (n+1) * f (n+1)) = (1/6) * (1^2 + 2^2 + 3^2 + 4^2 + 5^2 + 6^2) := by
  sorry
"""

# Sample 12's statement. True, but evaluating Nat.choose 1996 4 by unfolding
# exceeds Lean's default recursion depth. maxHeartbeats is already unlimited in
# the header; maxRecDepth is not raised anywhere.
S12 = """{OPT}theorem test
  (n r : Nat)
  (h₀: n = 1996)
  (h₁: r = 4):
  Nat.choose n r = 1996 * 1995 * 1994 * 1993 / (4 * 3 * 2 * 1) := by
  subst h₀ h₁
  decide
"""

# depth=None means "leave config.LEAN_MAX_REC_DEPTH alone"; a number overrides
# what the verifier injects, so the 12a/12b pair still contrasts the old default
# against the configured value now that the fix is in place.
CASES = [
    ("19a  statement as shipped, proof replaced by `sorry`",
     GOEDEL_LEAN4_HEADER + S19.replace("{IN}", "in"), None,
     "statement_error", "rejected with NO model proof present"),
    ("19b  same statement, `in` -> `∈`, still just `sorry`",
     GOEDEL_LEAN4_HEADER + S19.replace("{IN}", "∈"), None,
     "has_sorry", "parses; only the sorry remains"),
    ("12a  correct proof, Lean's OLD default depth (512)",
     GOEDEL_LEAN4_HEADER + S12.replace("{OPT}", ""), 512,
     "compile_error", "recursion limit, not a wrong proof"),
    ("12b  identical, at the configured LEAN_MAX_REC_DEPTH",
     GOEDEL_LEAN4_HEADER + S12.replace("{OPT}", ""), None,
     "valid", "same proof compiles at the configured depth"),
]


def main():
    v = LeanVerifier(verbose=False)
    print(f"verifier ready (Mathlib env {v.base_env_seconds:.1f}s)\n")
    print(f"{'case':<52}{'expected':<16}{'got':<16}ok")
    print("-" * 94)

    failures = 0
    results = []
    for label, code, depth, expected, note in CASES:
        original = verifier_mod.LEAN_MAX_REC_DEPTH
        if depth is not None:
            verifier_mod.LEAN_MAX_REC_DEPTH = depth
        try:
            res = v.verify(code)
        finally:
            verifier_mod.LEAN_MAX_REC_DEPTH = original
        # 19a reaches statement_error only through verify_traces, which runs the
        # statement probe; verify() alone reports the underlying compile_error.
        if expected == "statement_error" and res["outcome"] == "compile_error":
            verdict, detail = v.statement_is_broken(
                code.split("Rat\n\n", 1)[-1].replace("\n  sorry\n", "")
            )
            if verdict == BROKEN:  # "not_broken" is a truthy string
                res = dict(res, outcome="statement_error",
                           statement_error_detail=detail)
        ok = res["outcome"] == expected
        failures += not ok
        results.append((label, expected, res, note))
        print(f"{label:<52}{expected:<16}{res['outcome']:<16}{'yes' if ok else 'NO'}")

    print("\n" + "=" * 94)
    for label, expected, res, note in results:
        print(f"\n{label}\n  -> {res['outcome']}  ({note})")
        for e in res["errors"][:1]:
            first = e.strip().splitlines()[0] if e.strip() else ""
            print(f"     lean: {first[:100]}")

    print("\n" + "=" * 94)
    print("""
Reading of the result
---------------------
19a vs 19b: the ONLY difference is `in` vs `∈`, and neither file contains a
proof. If 19a fails and 19b does not, the failure is the statement's syntax
against Mathlib v4.32.0 -- Lean never reaches a proof, so calling this outcome a
model failure is wrong.

12a vs 12b: the ONLY difference is `set_option maxRecDepth`. Same statement,
same proof. If 12b compiles, the outcome is a property of our Lean
configuration, not of the mathematics or the model.
""")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
