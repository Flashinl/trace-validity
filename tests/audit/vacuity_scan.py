"""How much does a `valid` trace actually assert? Both temperatures, every positive.

Each probe replaces the model's proof entirely, so we are interrogating the
DATASET's goal, not the model's work. Probes are ordered by how little the goal
demands, and each is chosen to be strictly weaker than the next:

  P_true      `exact True.intro`            goal is literally `True`
  P_assum     `assumption`                  goal IS one of the hypotheses, verbatim
  P_redrfl    `with_reducible rfl`          goal is X = X syntactically. `with_reducible`
                                            is the point: it will NOT unfold
                                            `Nat.factorial 4` to `24`, so it separates
                                            "asserts nothing" from "asserts a computation"
  P_substrfl  `subst_vars <;> with_reducible rfl`
                                            goal becomes X = X once its own equational
                                            hypotheses are substituted (the sample-38 case)
  P_rfl       `rfl`                         closes by kernel computation: real ground
                                            arithmetic, but no reasoning step
  P_decide    `decide`                      decidable outright, hypotheses unused
  P_contra    `<binders> : False`           hypotheses inconsistent -> everything vacuous

Run: python tests/audit/vacuity_scan.py
"""
import io, json, re, sys, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from config import GOEDEL_LEAN4_HEADER
from verifier import LeanVerifier, VALID

H = GOEDEL_LEAN4_HEADER
PROBE_TIMEOUT = 15
J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]
norm = lambda s: re.sub(r"\s+", " ", (s or "")).strip()


def split_statement(stmt):
    s = re.sub(r":=\s*by\s*$", "", norm(stmt)).strip()
    m = re.match(r"^(?:theorem|lemma|example)\s+\S+\s*(.*)$", s)
    body = m.group(1) if m else s
    depth, cut = 0, None
    for i, ch in enumerate(body):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif ch == ":" and depth == 0:
            cut = i
    return ("", body) if cut is None else (body[:cut].strip(), body[cut + 1:].strip())


def stmt_with(stmt, tac):
    s = stmt.rstrip()
    if not re.search(r"\bby\s*\Z", s):
        s += " := by" if not s.endswith(":=") else " by"
    return f"{H}{s}\n  {tac}\n"


def ok(v, code):
    try:
        return v.verify(code, timeout=PROBE_TIMEOUT)["outcome"] == VALID
    except Exception:  # noqa: BLE001
        return False


PROBES = [
    ("P_true",     "exact True.intro"),
    ("P_assum",    "assumption"),
    ("P_redrfl",   "with_reducible rfl"),
    ("P_substrfl", "subst_vars <;> with_reducible rfl"),
    ("P_rfl",      "rfl"),
    ("P_decide",   "decide"),
    # ---- added 2026-09-02, closing two holes found via the two-axis work ----
    # HOLE 1 (logged during the tactic-oracle work, never patched). `∃ x, x = e`
    # asserts nothing -- the witness is handed to you by the goal itself -- but
    # it is not `True`, not a hypothesis restatement, not `rfl` (the goal is an
    # existential, not an equation) and not `decide` (ℕ is infinite, so the
    # existential is not decidable). It therefore fell through every rung and
    # scored `6_contentful`.
    ("P_exists_refl", "exact ⟨_, rfl⟩"),
    # HOLE 2, found while hand-reading cell b of the two-axis grid. A goal that
    # is a CONJUNCTION of its own hypotheses restates them and asserts nothing,
    # but `assumption` cannot close a conjunction and `with_reducible rfl`
    # cannot either, so it also scored `6_contentful` (sample 3: goal
    # `hh = 2 ∧ ht = 3 ∧ th = 4 ∧ tt = 5` against exactly those four
    # hypotheses). `and_intros` splits the conjunction first.
    ("P_conj_assum",   "and_intros <;> assumption"),
    ("P_conj_substrfl", "subst_vars <;> and_intros <;> with_reducible rfl"),
    # HOLE 3, an internal inconsistency in the ladder itself. Rung 4 already
    # grants `subst_vars` for free (P_substrfl), but rung 5 did not: it offered
    # only bare `rfl` / `decide`, which cannot fire while the goal still
    # mentions variables pinned by hypotheses. So a goal demanding nothing but
    # substitution followed by kernel computation -- no reasoning at all --
    # fell past rung 5 and scored `6_contentful` (sample 9: `Nat.choose
    # (gold + silver) gold = 70` with `gold = 4`, `silver = 4`). Rung 5 now gets
    # the same substitution rung 4 already had.
    ("P_subst_rfl",    "subst_vars <;> rfl"),
    ("P_subst_decide", "subst_vars <;> decide"),
]

# Most-severe-first. Each label says what the GOAL demands, not what the model did.
#
# The 2026-09-02 patch keeps every existing class name and meaning so committed
# figures stay comparable, extends 3 and 4 to their conjunctive forms, and adds
# ONE new class, 4b, for the existential-with-given-witness case. Classes
# 1, 2, 3, 4 and 4b together are the "contentless" band.
def classify(p, contra):
    if p["P_true"]:
        return "1_goal_is_True"
    if contra:
        return "2_hypotheses_contradictory"
    if p["P_assum"] or p.get("P_conj_assum"):
        return "3_goal_restates_a_hypothesis"
    if p["P_redrfl"] or p["P_substrfl"] or p.get("P_conj_substrfl"):
        return "4_syntactic_tautology"
    if p.get("P_exists_refl"):
        return "4b_exists_given_witness"
    if (p["P_rfl"] or p["P_decide"]
            or p.get("P_subst_rfl") or p.get("P_subst_decide")):
        return "5_ground_computation"
    return "6_contentful"


# The contentless band, named once so every consumer agrees.
CONTENTLESS_CLASSES = (
    "1_goal_is_True",
    "2_hypotheses_contradictory",
    "3_goal_restates_a_hypothesis",
    "4_syntactic_tautology",
    "4b_exists_given_witness",
)


# A probe that has never been seen to FIRE is not known to work, and a probe
# that has never been seen to STAY SILENT is not known to be sound. Three gates
# in this repo returned clean zeros because they read the wrong thing. Every new
# rung therefore ships with a positive and a negative control, checked at the
# top of every run, and the scan ABORTS if any control misbehaves.
PREFLIGHT = [
    # (probe, must_fire, statement)
    ("P_exists_refl", True,
     "theorem pf (n : ℕ) (h : n = 5) : ∃ x, x = n := by"),
    ("P_exists_refl", True,
     "theorem pf : ∃ x : ℕ, x = 2 + 3 := by"),
    ("P_exists_refl", False,   # real content: the witness is NOT handed over
     "theorem pf (n : ℕ) (h : n = 64) : ∃ a : ℕ, a ^ 2 = n := by"),
    ("P_conj_assum", True,
     "theorem pf (a b : ℕ) (h0 : a = 2) (h1 : b = 3) : a = 2 ∧ b = 3 := by"),
    ("P_conj_assum", False,    # real content: second conjunct is not a hypothesis
     "theorem pf (a b : ℕ) (h0 : a = 2) (h1 : b = 3) : a = 2 ∧ a + b = 5 := by"),
    ("P_conj_substrfl", True,
     "theorem pf (a b : ℕ) (h0 : a = 2) (h1 : b = 3) : a = 2 ∧ b = 3 := by"),
    ("P_conj_substrfl", False,  # needs arithmetic, not just substitution
     "theorem pf (a b : ℕ) (h0 : a = 2) (h1 : b = 3) : a + b = 5 ∧ a = 2 := by"),
    ("P_subst_decide", True,
     "theorem pf (g s : ℕ) (h0 : g = 4) (h1 : s = 4) : Nat.choose (g + s) g = 70 := by"),
    ("P_subst_rfl", True,
     "theorem pf (a b : ℕ) (h0 : a = 2) (h1 : b = 3) : a + b = 5 := by"),
    ("P_subst_decide", False,   # genuinely open: no hypothesis pins n
     "theorem pf (n : ℕ) : n + 0 = n := by"),
]


def preflight(v):
    """Positive and negative controls for the new rungs. Returns False on any
    disagreement, which aborts the run rather than producing quiet numbers."""
    tac = dict(PROBES)
    print("=" * 92)
    print("PREFLIGHT  every new rung must fire on a positive control and stay "
          "silent on a negative")
    print("=" * 92)
    ok_all = True
    for name, must_fire, stmt in PREFLIGHT:
        got = ok(v, stmt_with(stmt, tac[name]))
        good = (got == must_fire)
        ok_all &= good
        print(f"  {'PASS' if good else 'FAIL'}  {name:<17}"
              f"expect={'fire':<7}" .replace('fire', 'fire' if must_fire else 'silent')
              + f"got={'fired' if got else 'silent':<8}{stmt[8:88]}", flush=True)
    print(f"\n  preflight: {'OK' if ok_all else 'FAILED'}\n", flush=True)
    return ok_all


def main():
    """Run the scan. Guarded so importing this module does NOT re-run it.

    This block used to sit at module level. `from vacuity_scan import PROBES,
    classify` therefore spun up a LeanVerifier, re-probed all 74 passes, and
    rewrote results/vacuity_scan.json as a side effect of the import -- roughly
    ten minutes of Lean per import, and a committed artifact overwritten by
    anything that wanted to reuse a constant from here.
    """
    t0 = time.perf_counter()
    v = LeanVerifier(setup=False, verbose=False)
    print(f"[setup] verifier ready in {time.perf_counter()-t0:.0f}s\n", flush=True)

    if not preflight(v):
        raise SystemExit("preflight failed -- refusing to produce numbers from "
                         "probes that do not behave as specified")

    out = {}
    for T in ("0.0", "0.2"):
        traces = {r["sample_index"]: r for r in J(f"traces/temp{T}_n50_1each/traces.jsonl")}
        vers = {r["sample_index"]: r for r in J(f"results/verify3_temp{T}.jsonl")}
        valid = sorted(i for i, r in vers.items() if r["outcome"] == "valid")
        print("=" * 92)
        print(f"T = {T}   probing {len(valid)} `valid` traces")
        print("=" * 92)
        print(f"  {'s':<4}{'class':<30}{'True':<6}{'assum':<7}{'rfl_r':<7}{'subst':<7}"
              f"{'rfl':<5}{'dec':<5}{'contra':<7} goal")

        rows = []
        for i in valid:
            stmt = traces[i]["formal_statement"]
            binders, goal = split_statement(stmt)
            p = {name: ok(v, stmt_with(stmt, tac)) for name, tac in PROBES}

            contra = False
            if binders.strip():
                for tac in ("simp_all", "omega", "norm_num at *"):
                    if ok(v, f"{H}theorem contra_probe {binders} : False := by\n  {tac}\n"):
                        contra = True
                        break

            cls = classify(p, contra)
            rows.append({"sample": i, "class": cls, "goal": goal[:80], "contra": contra,
                         "state": vers[i]["state"], "level": traces[i].get("level"), **p})
            print(f"  {i:<4}{cls:<30}{int(p['P_true']):<6}{int(p['P_assum']):<7}"
                  f"{int(p['P_redrfl']):<7}{int(p['P_substrfl']):<7}{int(p['P_rfl']):<5}"
                  f"{int(p['P_decide']):<5}{int(contra):<7} {goal[:48]}")

        out[T] = rows
        tally = {}
        for r in rows:
            tally[r["class"]] = tally.get(r["class"], 0) + 1
        print(f"\n  TALLY T={T}:")
        for k in sorted(tally):
            print(f"    {k:<32} {tally[k]:>3}")
        print()

    json.dump(out, io.open("results/vacuity_scan.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print("wrote results/vacuity_scan.json")



if __name__ == "__main__":
    main()
