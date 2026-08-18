"""Fire `timeout` and `verifier_crash` — the two outcomes that had never fired.

Audit finding 1-C: both branches exist and look correctly wired, but no fixture
had ever exercised them, so their *behaviour* was unverified. In particular
`verifier.py` catches `TimeoutError` before the generic `except Exception`, and a
timeout raised as anything else (`subprocess.TimeoutExpired` is NOT a
`TimeoutError`) would be silently misfiled as `verifier_crash`.

The earlier attempt to force a timeout with a heavy `decide` failed: it hit
`maxRecDepth 10000` and returned `compile_error` in 100 ms. Since
`LEAN_MAX_REC_DEPTH` now bounds runaway elaboration before the 60 s clock can
expire, a *natural* timeout is close to unreachable. So we test the
classification path directly, with a real computation and a tiny budget — which
is the thing actually in doubt.

Run: python tests/audit/phase1_deadbranches.py
"""
import json, sys, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from config import GOEDEL_LEAN4_HEADER
from verifier import LeanVerifier, TIMEOUT, VERIFIER_CRASH

H = GOEDEL_LEAN4_HEADER
results = []


def record(name, expected, got, detail="", elapsed=None):
    ok = got == expected
    results.append({"case": name, "expected": expected, "got": got,
                    "pass": ok, "detail": detail[:200], "seconds": elapsed})
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<26} expected={expected:<16} "
          f"got={got:<16} {detail[:70]}")
    return ok


t0 = time.perf_counter()
v = LeanVerifier(setup=False, verbose=False)
print(f"[setup] verifier ready in {time.perf_counter()-t0:.1f}s "
      f"(base env {v.base_env_seconds:.1f}s, {v.base_env_source})")
print()

# ---------------------------------------------------------------- 1. timeout
# A genuinely expensive elaboration under a budget it cannot possibly meet. The
# work is real (a large `decide`), so this is a wall-clock overrun, not a
# synthetic exception.
print("timeout branch:")
heavy = H + "theorem t : (List.range 2000).length = 2000 := by decide"
t = time.perf_counter()
r = v.verify(heavy, timeout=0.01)
el = time.perf_counter() - t
record("wall_clock_overrun", TIMEOUT, r["outcome"],
       (r["errors"] or [""])[0], round(el, 3))

# The verifier must survive its own timeout: `_restart()` rebuilds the session.
# If this second call fails, a single timeout poisons every later verification
# in the run — which would be far worse than the misclassification.
print("\nrecovery after timeout:")
r2 = v.verify(H + "theorem t : (2:Nat) + 2 = 4 := by norm_num")
record("verifier_usable_after_timeout", "valid", r2["outcome"],
       (r2["errors"] or [""])[0])

# --------------------------------------------------------- 2. verifier_crash
# Point the REPL at an environment index that does not exist. The server errors,
# lean_interact raises, and the generic handler must produce VERIFIER_CRASH —
# NOT `compile_error`, and NOT `valid`.
print("\nverifier_crash branch:")
saved = v.base_env
try:
    v.base_env = 10 ** 9  # no such environment
    t = time.perf_counter()
    r3 = v.verify(H + "theorem t : (2:Nat) + 2 = 4 := by norm_num")
    el = time.perf_counter() - t
    record("bogus_environment", VERIFIER_CRASH, r3["outcome"],
           (r3["errors"] or [""])[0], round(el, 3))
finally:
    v.base_env = saved

print("\nrecovery after crash:")
r4 = v.verify(H + "theorem t : (2:Nat) + 2 = 4 := by norm_num")
record("verifier_usable_after_crash", "valid", r4["outcome"],
       (r4["errors"] or [""])[0])

# ------------------------------------------------------------------- report
json.dump(results, open("results/phase1_deadbranches.json", "w"), indent=2)
n_pass = sum(1 for r in results if r["pass"])
print(f"\n{n_pass}/{len(results)} passed → results/phase1_deadbranches.json")
sys.exit(0 if n_pass == len(results) else 1)
