"""Live verifier probes: is a 9ms `valid` real elaboration, and do the dead
outcome branches fire? Requires a built lean_project. No GPU."""
import json, sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from config import GOEDEL_LEAN4_HEADER
from verifier import LeanVerifier

H = GOEDEL_LEAN4_HEADER
t0 = time.perf_counter()
v = LeanVerifier(setup=False, verbose=False)
print(f"[setup] verifier ready in {time.perf_counter()-t0:.1f}s; "
      f"base_env={v.base_env!r} source={v.base_env_source} in {v.base_env_seconds:.2f}s")

CASES = [
    # name, code, what we expect
    ("A_true_trivial",   H + "theorem t : True := by trivial", "valid"),
    ("B_real_mathlib",   H + "theorem t (n : Nat) : n + 0 = n := by simp", "valid"),
    # Positive control that Mathlib is genuinely loaded: a Mathlib-only lemma.
    ("C_mathlib_only",   H + "theorem t : Nat.choose 5 2 = 10 := by decide", "valid"),
    ("D_needs_mathlib",  H + "theorem t (s : Finset Nat) : s.card = s.card := by "
                             "exact Finset.card_def ▸ rfl", "either"),
    # NEGATIVE control: must NOT be valid. If this returns valid, the pipeline
    # is not elaborating at all.
    ("E_false",          H + "theorem t : (2 : Nat) + 2 = 5 := by norm_num", "compile_error"),
    ("F_unsolved",       H + "theorem t (n : Nat) : n > 0 := by skip", "compile_error"),
    ("G_unknown_ident",  H + "theorem t : True := by exact totally_bogus_lemma_xyz", "compile_error"),
    ("H_sorry",          H + "theorem t (n : Nat) : n > 0 := by sorry", "has_sorry"),
    ("I_admit",          H + "theorem t (n : Nat) : n > 0 := by admit", "has_sorry?"),
    ("J_axiom_hatch",    H + "axiom cheat : (2:Nat)+2 = 5\ntheorem t : (2:Nat)+2 = 5 := by exact cheat", "??"),
    ("K_no_decl",        H + "-- just a comment", "empty_code"),
    ("L_empty",          "", "empty_code"),
    # TIMEOUT probe: maxHeartbeats 0 means Lean will not stop itself.
    ("M_timeout",        H + "theorem t : Nat.choose 100000 50000 > 0 := by decide", "timeout?"),
]

out = []
for name, code, expect in CASES:
    to = 20 if name == "M_timeout" else None
    t = time.perf_counter()
    try:
        r = v.verify(code, timeout=to)
    except Exception as e:
        r = {"outcome": f"RAISED {type(e).__name__}", "seconds": 0, "mode": "-", "errors": [str(e)[:120]]}
    el = time.perf_counter() - t
    line = {"case": name, "expect": expect, "outcome": r["outcome"],
            "reported_s": r.get("seconds"), "wall_s": round(el, 3),
            "mode": r.get("mode"), "err": (r.get("errors") or [""])[0][:110].replace("\n", " ")}
    out.append(line)
    print(f"  {name:<18} expect={expect:<15} got={r['outcome']:<16} "
          f"{r.get('seconds')}s (wall {el:.3f}s) mode={r.get('mode')}  {line['err']}")

json.dump(out, open("results/phase1_live_probe.json", "w"), indent=2)
print("\nwrote results/phase1_live_probe.json")
