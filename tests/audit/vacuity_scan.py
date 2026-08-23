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
]

# Most-severe-first. Each label says what the GOAL demands, not what the model did.
def classify(p, contra):
    if p["P_true"]:
        return "1_goal_is_True"
    if contra:
        return "2_hypotheses_contradictory"
    if p["P_assum"]:
        return "3_goal_restates_a_hypothesis"
    if p["P_redrfl"] or p["P_substrfl"]:
        return "4_syntactic_tautology"
    if p["P_rfl"] or p["P_decide"]:
        return "5_ground_computation"
    return "6_contentful"


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
    print(f"[setup] verifier ready in {time.perf_counter()-t0:.0f}s\n")

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
