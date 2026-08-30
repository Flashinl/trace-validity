"""Supplementary pass: re-run the ONE ladder rung that was dead on this toolchain.

`simp_arith` (rung 9 of the pre-registered ladder) is deprecated in Lean v4.32.0
and errors out before it ever sees a goal, so rung 9 tested nothing. Lean's own
deprecation message names the replacement: `simp +arith +decide`. Running that
is not tuning the ladder -- it is running the rung the brief asked for, on a
toolchain where the old spelling no longer exists.

This is deliberately a SEPARATE artifact and a SEPARATE number. The primary
result in TACTIC_ORACLE.md is the pre-registered ladder run as written. This pass
is reported beside it, never folded into it, because it was run after seeing that
the original rung was dead.

Rung 6 (`nlinarith [sq_nonneg _, sq_nonneg _]`) is also dead and is NOT repaired
here: its only sample-independent repair is bare `nlinarith`, which the ladder
already contains as rung 7.

Run: python tests/audit/tactic_oracle_repair.py
"""
import io, json, os, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import VERIFY_TIMEOUT_SECONDS  # noqa: E402
from verifier import LeanVerifier, VALID, TIMEOUT, VERIFIER_CRASH  # noqa: E402
import tactic_common as tc  # noqa: E402
from tactic_oracle import statement_prefix, hypotheses_contradictory  # noqa: E402

REPAIRED = [("simp_arith_repaired", "simp +arith +decide")]

# A second, unrelated question answered in the same Lean session because the
# session costs ~11 minutes to start and the probe costs milliseconds.
#
# `vacuity_scan.py`'s taxonomy has six probes and none of them covers
# `∃ x, x = e` -- an existential witnessed by its own right-hand side, which
# asserts nothing at all yet is not `True`, not a hypothesis, not `rfl`, and not
# `decide`-able. One of the oracle's four recoveries has exactly that shape and
# came back `6_contentful`, which would overstate it. `exact ⟨_, rfl⟩` settles
# it: if that closes the goal, the goal is witnessed by its own RHS.
EXISTS_EQ_PROBE = "exact ⟨_, rfl⟩"


def main():
    oracle = {(r["set"], str(r["id"])): r
              for r in tc.J(os.path.join(_ROOT, "results", "tactic_oracle.jsonl"))}
    samples = [s for s in tc.load_samples()
               if oracle.get((s["set"], str(s["id"])), {}).get("verdict")
               in ("none_closed", "budget")]
    print("[repair] %d samples the pre-registered ladder did not close" % len(samples))

    t0 = time.perf_counter()
    v = LeanVerifier(setup=False, verbose=False)
    print("[repair] verifier ready in %.0fs" % (time.perf_counter() - t0))

    out = []
    for k, s in enumerate(samples, 1):
        prefix = statement_prefix(s)
        rec = {"set": s["set"], "id": s["id"], "shape": s["shape"],
               "goal": s["goal"][:200]}
        if prefix is None:
            rec.update(verdict="excluded_no_code", attempts=[])
            out.append(rec)
            continue
        attempts, verdict, rung = [], "none_closed", None
        for name, tac in REPAIRED:
            try:
                res = v.verify(prefix + "\n  " + tac + "\n",
                               timeout=VERIFY_TIMEOUT_SECONDS)
            except Exception as e:  # noqa: BLE001
                res = {"outcome": VERIFIER_CRASH, "errors": ["%s: %s" % (type(e).__name__, e)],
                       "seconds": None}
            head = (res.get("errors") or [""])[0]
            attempts.append({"rung": name, "outcome": res["outcome"],
                             "seconds": res.get("seconds"),
                             "error_head": " ".join(str(head).split())[:160]})
            if res["outcome"] == TIMEOUT:
                verdict = "budget"
            if res["outcome"] == VALID:
                vac, why = hypotheses_contradictory(v, s["statement"])
                verdict = "vacuous_close" if vac else "recovered"
                rung, rec["vacuity"] = name, why
                break
        rec.update(verdict=verdict, rung=rung, attempts=attempts)
        out.append(rec)
        if verdict != "none_closed" or k % 25 == 0:
            print("  [%3d/%3d] %-22s %-38s %s"
                  % (k, len(samples), s["set"], str(s["id"])[:36], verdict), flush=True)

    # Second question: which recoveries are existentials witnessed by their own
    # right-hand side? See the note above EXISTS_EQ_PROBE.
    from vacuity_scan import ok, stmt_with  # noqa: E402
    witnessed = []
    for s in tc.load_samples():
        if oracle.get((s["set"], str(s["id"])), {}).get("verdict") != "recovered":
            continue
        hit = ok(v, stmt_with(s["statement"], EXISTS_EQ_PROBE))
        witnessed.append({"set": s["set"], "id": s["id"],
                          "witnessed_by_own_rhs": hit, "goal": s["goal"][:200]})
        print("  [exists_eq] %-22s %-38s %s"
              % (s["set"], str(s["id"])[:36],
                 "WITNESSED BY ITS OWN RHS" if hit else "not that shape"), flush=True)

    payload = {"repaired_rung": dict(REPAIRED), "rows": out,
               "exists_eq_probe": EXISTS_EQ_PROBE, "recoveries": witnessed}
    json.dump(payload, io.open(os.path.join(_ROOT, "results", "tactic_oracle_repair.json"),
                               "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    n_rec = sum(1 for r in out if r["verdict"] == "recovered")
    print("[repair] %d additional genuine recoveries; %d of %d recoveries are "
          "witnessed by their own RHS; wrote results/tactic_oracle_repair.json"
          % (n_rec, sum(1 for w in witnessed if w["witnessed_by_own_rhs"]),
             len(witnessed)))


if __name__ == "__main__":
    main()
