"""Unit tests for the tactic-oracle audit's classifiers.

Every headline number in `TACTIC_SELECTION.md` and `TACTIC_ORACLE.md` rests on
four pieces of string handling, and each has a specific way of being wrong that
would silently move a published figure:

  goal_shape()        `3 * x` is LINEAR. An earlier pattern matched any `*` with
                      an identifier on the right, which filed 69 of 104 samples
                      nonlinear -- inflating the headline "linarith on a
                      nonlinear goal" cell with goals linarith handles fine.

  classify_error()    `tactic_mismatch` covers four different Lean complaints,
                      and two of them (unknown constant, type mismatch) are not
                      tactic selection at all. Collapsing them would have
                      reported 11 recall failures as wrong-tactic failures.

  statement_prefix()  The oracle's whole claim is "same statement, same header,
                      only the proof body changed". If the cut lands anywhere
                      but the end of `:= by`, the oracle is proving a different
                      theorem than the model was asked to.

  split_binders()     The vacuity probe needs the binders. Cutting at the LAST
                      depth-0 colon hands `∀ a` to Lean as a binder list for
                      `theorem t : ∀ a : ℕ, P a` -- which does not parse, so the
                      probe silently never fires and every close is scored a
                      genuine recovery.

  structural_verdict() Claims a category error ONLY on direct evidence from
                      Lean. It must stay silent when all it has is the
                      top-level goal.

Run: python tests/test_tactic_audit.py
"""
import os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (os.path.join(_HERE, "audit"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tactic_common as tc  # noqa: E402
from tactic_oracle import statement_prefix, split_binders  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print("  %-4s %-58s got=%r" % ("PASS" if ok else "FAIL", name, got))
    if not ok:
        FAILS.append("%s: got %r, want %r" % (name, got, want))


# --------------------------------------------------------------------------- #
print("goal_shape: a constant times a variable is LINEAR")
check("3 * x = 5 is not nonlinear",
      tc.goal_shape("theorem t (x : ℚ) : 3 * x = 5"), "linear_real_rat")
check("x * y is nonlinear",
      tc.goal_shape("theorem t (x y : ℚ) : x * y = 5"), "nonlinear")
check("x ^ 2 is nonlinear",
      tc.goal_shape("theorem t (x : ℚ) : x ^ 2 = 5"), "nonlinear")
check("x / 2 is not nonlinear",
      tc.goal_shape("theorem t (x : ℚ) : x / 2 = 5"), "linear_real_rat")
check("x / y is nonlinear",
      tc.goal_shape("theorem t (x y : ℚ) : x / y = 5"), "nonlinear")
check("⌊x⌋ * (x - ⌊x⌋) is nonlinear",
      tc.goal_shape("theorem t (x : ℚ) : ⌊x⌋ * (x - ⌊x⌋) = 1"), "nonlinear")
check("divisibility over ℕ",
      tc.goal_shape("theorem t (a b : ℕ) : 7 ∣ 5 * a + 2 * b"), "nat_int_arith")
check("Finset beats ℕ",
      tc.goal_shape("theorem t (n : ℕ) : (Finset.range n).card = n"), "finset_bigop")

print()
print("goal_shape: precedence is nonlinear first, and it is deliberate")
check("nonlinear beats divisibility",
      tc.goal_shape("theorem t (n m : ℕ) : 49 ∣ n * m"), "nonlinear")

# --------------------------------------------------------------------------- #
print()
print("classify_error: four Lean complaints, not one")
check("linarith names itself",
      tc.classify_error("linarith failed to find a contradiction\nx : ℕ\n⊢ False")[:2],
      ("linarith", "tactic_failed"))
check("omega names itself",
      tc.classify_error("omega could not prove the goal:\n  a ≥ 0")[:2],
      ("omega", "tactic_failed"))
check("backticked tactic name",
      tc.classify_error("`simp` made no progress")[:2], ("simp", "tactic_failed"))
check("Tactic `X` failed",
      tc.classify_error("Tactic `rfl` failed: The left-hand side")[:2],
      ("rfl", "tactic_failed"))
check("unknown constant is NOT a tactic failure",
      tc.classify_error("Unknown constant `Nat.odd_iff_not_even`")[:2],
      (None, "unknown_name"))
check("type mismatch is NOT a tactic failure",
      tc.classify_error("Type mismatch: After simplification, term")[:2],
      (None, "type_error"))
check("unsolved goals names no tactic",
      tc.classify_error("unsolved goals\n⊢ True")[:2], (None, "unsolved_goals"))

# --------------------------------------------------------------------------- #
print()
print("statement_prefix: header and statement survive byte-for-byte")
HDR = ("import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\n"
       "open BigOperators Real Nat Topology Rat\n\n")
DOC = "/- a doc comment the model was shown -/\n"
STMT = "theorem t (x : ℕ) (h : x > 0) : x ≥ 1 := by"
BODY = "\n  -- the model's proof\n  omega\n"
sample = {"formal_statement": "import Mathlib\n" + DOC + STMT,
          "full_code": HDR + DOC + STMT + BODY}
pre = statement_prefix(sample)
check("prefix ends at `:= by`", pre.endswith(":= by"), True)
check("prefix keeps the Goedel header", pre.startswith(HDR), True)
check("prefix keeps the informal_prefix doc comment", DOC in pre, True)
check("prefix drops the model's proof body", "omega" in pre, False)
check("prefix is a literal prefix of full_code",
      sample["full_code"].startswith(pre), True)
check("no full_code -> excluded, not reconstructed",
      statement_prefix({"formal_statement": STMT, "full_code": ""}), None)
check("statement not found in full_code -> excluded",
      statement_prefix({"formal_statement": "theorem other : True := by",
                        "full_code": HDR + STMT}), None)

# --------------------------------------------------------------------------- #
print()
print("split_binders: cut at the FIRST depth-0 colon, not the last")
check("quantified goal leaves the binders empty",
      split_binders("theorem t : ∀ a : ℕ, a ≥ 0 := by")[0], "")
check("...and the goal keeps its quantifier",
      split_binders("theorem t : ∀ a : ℕ, a ≥ 0 := by")[1], "∀ a : ℕ, a ≥ 0")
check("colons inside parens do not split",
      split_binders("theorem t (x : ℕ) (h : x > 0) : x ≥ 1 := by")[0],
      "(x : ℕ) (h : x > 0)")
check("...and the goal is what follows",
      split_binders("theorem t (x : ℕ) (h : x > 0) : x ≥ 1 := by")[1], "x ≥ 1")

# --------------------------------------------------------------------------- #
print()
print("structural_verdict: direct evidence only, never the top-level goal")
check("linarith holding a nonlinear context IS structural",
      tc.structural_verdict({"lean_tactic": "linarith",
                             "lean_shape_source": "lean_goal_state",
                             "lean_shape": "nonlinear",
                             "omega_nonlinear_atom": False})[0], True)
check("linarith on a shape guessed from the STATEMENT is not",
      tc.structural_verdict({"lean_tactic": "linarith",
                             "lean_shape_source": "statement",
                             "lean_shape": "nonlinear",
                             "omega_nonlinear_atom": False})[0], False)
check("omega with a nonlinear atom in its own table IS structural",
      tc.structural_verdict({"lean_tactic": "omega",
                             "lean_shape_source": "statement",
                             "lean_shape": "nonlinear",
                             "omega_nonlinear_atom": True})[0], True)
check("omega WITHOUT one is not -- it decided, it did not refuse",
      tc.structural_verdict({"lean_tactic": "omega",
                             "lean_shape_source": "statement",
                             "lean_shape": "nonlinear",
                             "omega_nonlinear_atom": False})[0], False)

# --------------------------------------------------------------------------- #
print()
print("tactics_used: prose and lemma arguments are not tactics")
tacs = tc.tactics_used("/- We use Nat.succ here -/\n  simp [Nat.pow_succ]\n"
                       "  rcases h with ⟨x, hx⟩\n  omega\n")
check("the closing tactic is found", "omega" in tacs, True)
check("simp is found", "simp" in tacs, True)
check("a lemma inside simp [...] is not a tactic", "Nat.pow_succ" in tacs, False)
check("a binder name from rcases is not a tactic", "x" in tacs, False)
check("a word from the doc comment is not a tactic", "We" in tacs, False)
alt = tc.tactics_used("  rcases this with (h | h | h) <;> simp [h, pow_two]\n")
check("an rcases alternation is not a tactic", "h" in alt, False)
check("...but the tactic after <;> is", "simp" in alt, True)
ind = tc.tactics_used("  induction n with\n  | zero => simp\n"
                      "  | succ n ih => omega\n")
check("an induction case label is not a tactic",
      "zero" in ind or "succ" in ind, False)
check("...and the tactic in the case body still is", "omega" in ind, True)

# --------------------------------------------------------------------------- #
print()
if FAILS:
    print("FAILURES (%d):" % len(FAILS))
    for f in FAILS:
        print("  " + f)
    sys.exit(1)
print("all tactic-audit tests pass")
