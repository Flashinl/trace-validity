"""Generate tests/fixtures/control_set.jsonl.

Ground truth for the verifier, independent of any model. Every snippet below was
hand-written and hand-labelled. `expected` uses the outcome taxonomy from
issue #5. `confidence` is honest: "high" means I am sure of the label, "medium"
means the label is right in principle but the exact Lean behaviour could differ
by version and should be reviewed against actual output.

Deliberately included are adversarial cases (the `sorry_lookalike` category)
where a naive `\\bsorry\\b` regex over the whole file produces a FALSE POSITIVE
on code that is genuinely valid. Those are the "genuinely valid but reported
invalid" cases the supervisor asked for.
"""

import json
import os

HEADER = (
    "import Mathlib\nimport Aesop\n\n"
    "set_option maxHeartbeats 400000\n\n"
    "open BigOperators Real Nat Topology Rat\n\n"
)

# The exact shape generate.py's `full_code` produces: Goedel header, an informal
# doc-comment, then the theorem with its proof body.
GOEDEL_HEADER = (
    "import Mathlib\nimport Aesop\n\n"
    "set_option maxHeartbeats 0\n\n"
    "open BigOperators Real Nat Topology Rat\n\n"
)

F = []


def add(fid, category, expected, code, note, confidence="high"):
    F.append({
        "id": fid,
        "category": category,
        "expected": expected,
        "lean_code": code,
        "note": note,
        "confidence": confidence,
    })


# ---------------------------------------------------------------- compiles ---
add("clean_01", "compiles_clean", "valid",
    HEADER + "theorem c01 (n : Nat) : n + 0 = n := by simp\n",
    "n + 0 = n is definitional; simp closes it.")

add("clean_02", "compiles_clean", "valid",
    HEADER + "theorem c02 : (2 : Nat) ^ 3 = 8 := by norm_num\n",
    "Closed numeric goal, norm_num evaluates it.")

add("clean_03", "compiles_clean", "valid",
    HEADER + "theorem c03 (a b : Nat) : a + b = b + a := by omega\n",
    "Linear Nat arithmetic; omega is complete for this fragment.")

add("clean_04", "compiles_clean", "valid",
    HEADER + "theorem c04 (n : Nat) (h : n = 3) : n + 1 = 4 := by subst h; rfl\n",
    "subst then rfl. Mirrors the subst/rfl pattern the model actually emits.")

add("clean_05", "compiles_clean", "valid",
    HEADER + "example : (10 : Nat) % 3 = 1 := by decide\n",
    "Small decidable goal; decide terminates instantly.")

# ------------------------------------------------------------ type errors ---
add("typeerr_01", "type_error", "compile_error",
    HEADER + "theorem e01 : (1 : Nat) = \"hello\" := rfl\n",
    "Nat vs String: type mismatch, cannot even elaborate.")

add("typeerr_02", "type_error", "compile_error",
    HEADER + "theorem e02 (n : Nat) : n + 0 = n := by exact True.intro\n",
    "True.intro : True, goal is an equality. Wrong type.")

add("typeerr_03", "type_error", "compile_error",
    HEADER + "theorem e03 : 2 + 2 = 5 := by norm_num\n",
    "Statement is false; norm_num reduces to False and fails.")

add("typeerr_04", "type_error", "compile_error",
    HEADER + "theorem e04 (x : Nat) : x < x := by omega\n",
    "x < x is false for all x; omega must fail.")

add("typeerr_05", "type_error", "compile_error",
    HEADER + "theorem e05 (n : Nat) : n = n := by ring_nf; exact absurd rfl (by simp)\n",
    "Nonsense tail after a goal that is already closed/mis-shaped.",
    confidence="medium")

# ------------------------------------------------------------------ sorry ---
add("sorry_01", "has_sorry", "has_sorry",
    HEADER + "theorem s01 (n : Nat) : n + 0 = n := by sorry\n",
    "Bare tactic sorry. Compiles with a warning - must NOT be counted valid.")

add("sorry_02", "has_sorry", "has_sorry",
    HEADER + "theorem s02 (n : Nat) : n * 1 = n := sorry\n",
    "Term-mode sorry.")

add("sorry_03", "has_sorry", "has_sorry",
    HEADER + "theorem s03 : 1 = 1 := by\n  have h : 2 + 2 = 4 := by sorry\n  rfl\n",
    "sorry nested in a have; top-level goal still closes. Easy to miss.")

add("sorry_04", "has_sorry", "has_sorry",
    HEADER + "theorem s04 (n : Nat) : n + 0 = n := by\n  induction n with\n  | zero => rfl\n  | succ k ih => sorry\n",
    "sorry in one branch only. Partially proved is still not proved.")

# ------------------------------- sorry lookalikes: MUST still be valid -------
add("sorrylike_01", "sorry_lookalike", "valid",
    HEADER + "-- sorry, this one is tricky\ntheorem sl01 (n : Nat) : n + 0 = n := by simp\n",
    "The word 'sorry' appears only inside a COMMENT. A regex over raw text "
    "flags this as has_sorry; the proof is genuinely complete. FALSE POSITIVE probe.")

add("sorrylike_02", "sorry_lookalike", "valid",
    HEADER + "theorem sl02 : (\"sorry\" : String) = \"sorry\" := rfl\n",
    "'sorry' inside a STRING LITERAL. Same false-positive trap.")

add("sorrylike_03", "sorry_lookalike", "valid",
    HEADER + "theorem sorry_free_lemma (n : Nat) : n + 0 = n := by simp\n",
    "Identifier contains 'sorry' as a substring. \\bsorry\\b should NOT match "
    "because '_' is a word char - verifies the word boundary actually works.")

# --------------------------------------------------- needs Mathlib import ---
add("import_01", "needs_mathlib", "valid",
    HEADER + "theorem i01 (x : ℝ) : x * 1 = x := by ring\n",
    "Real numbers require Mathlib. With the header present this must compile.")

add("import_02", "needs_mathlib", "valid",
    HEADER + "theorem i02 (n : ℕ) : Nat.gcd n n = n := by simp\n",
    "Nat.gcd simp lemma lives in Mathlib.")

add("import_03", "needs_mathlib", "compile_error",
    "theorem i03 (x : ℝ) : x + 0 = x := by ring\n",
    "SAME proof as import_01 but with NO import Mathlib. Unknown identifier "
    "must fail. Confirms imports are actually in effect.")

# ---------------------------------------------------- broken / truncated ---
add("trunc_01", "truncated", "compile_error",
    HEADER + "theorem t01 (n : Nat) : n + 0 = n := by\n  have h : n = n := by\n",
    "Truncated mid-proof: trailing 'by' with no tactic. Exactly what a "
    "token-limit cutoff produces.")

add("trunc_02", "truncated", "compile_error",
    HEADER + "theorem t02 : 1 = 1 := by\n  simp [\n",
    "Unclosed bracket.")

add("trunc_03", "truncated", "compile_error",
    HEADER + "theorem t03 (n : Nat\n",
    "Truncated signature; unbalanced paren.")

add("trunc_04", "truncated", "compile_error",
    HEADER + "theorem t04 (n : Nat) : n + 0 = n := by\n  induction n with\n  | zero =>\n",
    "Truncated inside a match arm.")

# ------------------------------------------------------------ empty input ---
add("empty_01", "empty", "empty_code", "",
    "Completely empty string. Must be empty_code, never valid.")

add("empty_02", "empty", "empty_code", "   \n\n  \n",
    "Whitespace only. Must be empty_code, never valid.")

add("empty_03", "empty", "empty_code", HEADER,
    "Header only, no declaration at all. Compiles fine but proves NOTHING - "
    "must not be reported valid. FALSE-VALID probe.")

# ------------------------- exact formatting our pipeline actually produces ---
add("pipeline_01", "pipeline_formatted", "valid",
    GOEDEL_HEADER
    + "/-- We can start by breaking down the number into its prime factors. -/\n"
      "theorem test\n  (n: ℕ)\n  (h₀: n = 1061520150601):\n"
      "  ∃ a: ℕ, a^6 = n := by\n"
      "  use 101\n  norm_num [h₀]\n",
    "Byte-for-byte the shape generate.py emits (Goedel header + doc-comment + "
    "theorem + tactic body). This is the real sample-0 proof, verbatim: "
    "`use 101` then `norm_num [h₀]`.",
    confidence="high")

add("pipeline_02", "pipeline_formatted", "valid",
    GOEDEL_HEADER
    + "/-- Verify the arithmetic. -/\ntheorem test (n : ℕ) (h₀ : n = 4) : n + 1 = 5 := by\n"
      "  subst h₀\n  norm_num\n",
    "Pipeline shape with subst/norm_num, the most common tactic pair observed.")

add("pipeline_03", "pipeline_formatted", "has_sorry",
    GOEDEL_HEADER
    + "/-- Placeholder. -/\ntheorem test (n : ℕ) : n + 0 = n := by\n  sorry\n",
    "Pipeline shape carrying a sorry. Must be has_sorry, not valid.")

add("pipeline_04", "pipeline_formatted", "compile_error",
    GOEDEL_HEADER
    + "/-- Truncated generation. -/\ntheorem test (n : ℕ) (h₀ : n = 4) : n + 1 = 5 := by\n"
      "  subst h₀\n  norm_num <;>\n",
    "Pipeline shape truncated after '<;>' - the trailing-operator cutoff the "
    "parser's _looks_truncated heuristic is meant to catch.")

# ---------------------------------------------------------------- timeout ---
add("timeout_01", "timeout", "timeout",
    HEADER + "set_option maxRecDepth 1000000 in\ntheorem to01 : Nat.Prime 1000000007 := by decide\n",
    "`decide` on a 10-digit primality goal via kernel reduction. Without the "
    "raised maxRecDepth this failed fast with a recursion-depth error instead "
    "of hanging, so the timeout path went untested. Label is about the HARNESS "
    "behaving, not about Lean semantics. UNCONFIRMED until observed.",
    confidence="low")

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "control_set.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for rec in F:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote {len(F)} fixtures to {out}")
    from collections import Counter
    print("by category:", dict(Counter(r["category"] for r in F)))
    print("by expected:", dict(Counter(r["expected"] for r in F)))
    print("confidence :", dict(Counter(r["confidence"] for r in F)))
