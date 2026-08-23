"""STAGE B PREP -- everything that does not need the prover model.

Generation is blocked (this box has 8 GiB VRAM; Goedel-Prover-SFT needs 15.5).
Everything else is Lean-only and runs here:

  1. select 30 problems from each Kimina win_rate band -> 90 total
  2. apply the deprecated-binder fix (`x in` -> `x ∈`) and LOG every row touched
  3. elaborate every statement under our pinned Mathlib v4.32.0
  4. run the FormalStep vacuity probes on all 90 -- verifying, not assuming,
     that whole-problem statements cannot be trivial in the `n = 6 given
     h₀ : n = 6` sense

Writes stage_b_evalset.json: the 90 selected rows, fixed statements, elaboration
verdicts and vacuity classes. Generation can be run against it later on a GPU.
"""
import io, json, os, re, sys, time

REPO = r"C:\Users\vkris\trace-validity"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests", "audit"))
os.chdir(REPO)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from config import GOEDEL_LEAN4_HEADER
from verifier import LeanVerifier, HAS_SORRY, VALID
from vacuity_scan import PROBES, classify, split_statement, stmt_with   # import-safe now

PARQUET = (r"C:\Users\vkris\.cache\huggingface\hub\datasets--AI-MO--NuminaMath-LEAN"
           r"\snapshots\51fa67f1f647ae1ecd81eef9f19306aa8a7b3a94\data\train-00000-of-00001.parquet")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stage_b_evalset.json")
PER_BAND, TIMEOUT = 30, 30
H = GOEDEL_LEAN4_HEADER

BANDS = [("easy", 0.80, 1.01), ("medium", 0.40, 0.80), ("hard", -0.01, 0.40)]
_IMPORT = re.compile(r"^[ \t]*import[ \t]+[\w.]+[ \t]*$", re.M)
# `∑ k in Finset.Icc ...` -> `∑ k ∈ Finset.Icc ...`. Anchored on a big operator
# so a bare `in` elsewhere is never touched.
_BINDER = re.compile(r"([∑∏⋃⋂⨆⨅][^,\n]{0,60}?)\bin\b")


def fix_binder(stmt):
    """Return (fixed, n_replacements)."""
    n = 0
    def sub(m):
        nonlocal n
        n += 1
        return m.group(1) + "∈"
    return _BINDER.sub(sub, stmt), n


def with_sorry(stmt):
    s = stmt.rstrip()
    if re.search(r"\bby\s*\Z", s):
        return s + "\n  sorry\n"
    return s + (" by\n  sorry\n" if s.endswith(":=") else " := by\n  sorry\n")


def main():
    df = pd.read_parquet(PARQUET)
    pool = df[(df.problem_type == "Number Theory")
              & (df.question_type == "proof")
              & (df.formal_proof.fillna("").str.strip() != "")].copy()
    pool["wr"] = pool.rl_data.apply(lambda d: d["win_rate"] if d is not None else None)
    pool = pool.dropna(subset=["wr"]).sort_values("uuid")     # deterministic order

    selected = []
    for name, lo, hi in BANDS:
        band = pool[(pool.wr >= lo) & (pool.wr < hi)]
        take = band.head(PER_BAND)
        print(f"band {name:<7} pool={len(band):<5} taking {len(take)}  "
              f"mean win_rate {take.wr.mean():.3f}")
        for _, r in take.iterrows():
            selected.append({"band": name, "uuid": r.uuid, "wr": float(r.wr),
                             "source": r.source, "raw": r.formal_statement or "",
                             "kimina_proof": r.formal_proof or ""})
    print(f"\nselected {len(selected)} problems\n")

    # ---- binder fix, logged -------------------------------------------------
    touched = []
    for s in selected:
        fixed, n = fix_binder(s["raw"])
        s["statement"] = fixed
        s["binder_fixes"] = n
        if n:
            touched.append(s)
    print(f"BINDER FIX: {len(touched)} of {len(selected)} rows touched")
    for s in touched:
        m = re.search(r"[∑∏⋃⋂⨆⨅][^,\n]{0,50}", s["statement"])
        print(f"   {s['band']:<7} {s['uuid']}  ({s['binder_fixes']} repl)  "
              f"now: {m.group(0)[:56] if m else '?'}")
    print()

    t0 = time.perf_counter()
    v = LeanVerifier(setup=False, verbose=False)
    print(f"[setup] verifier ready in {time.perf_counter()-t0:.0f}s\n")

    print(f"  {'#':<4}{'band':<8}{'elab':<6}{'vacuity class':<32}{'uuid'}")
    for i, s in enumerate(selected, 1):
        body = _IMPORT.sub("", s["statement"]).lstrip()
        res = v.verify(H + with_sorry(body), timeout=TIMEOUT)
        s["outcome"] = res["outcome"]
        s["elaborated"] = res["outcome"] in (HAS_SORRY, VALID)
        s["error"] = (res["errors"][0].strip()[:400] if res["errors"] else "")

        s["vacuity"] = None
        if s["elaborated"]:
            binders, goal = split_statement(body)
            p = {}
            for name, tac in PROBES:
                try:
                    p[name] = v.verify(H + stmt_with(body, tac),
                                       timeout=15)["outcome"] == VALID
                except Exception:
                    p[name] = False
            contra = False
            if binders.strip():
                for tac in ("simp_all", "omega", "norm_num at *"):
                    try:
                        if v.verify(f"{H}theorem contra_probe {binders} : False := by\n  {tac}\n",
                                    timeout=15)["outcome"] == VALID:
                            contra = True
                            break
                    except Exception:
                        pass
            s["vacuity"] = classify(p, contra)
            s["probes"] = p
        print(f"  {i:<4}{s['band']:<8}{'OK' if s['elaborated'] else 'FAIL':<6}"
              f"{str(s['vacuity']):<32}{s['uuid'][:8]}")

    io.open(OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(selected, ensure_ascii=False, indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
