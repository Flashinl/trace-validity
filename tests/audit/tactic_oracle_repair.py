"""Two supplementary Lean questions, both run after seeing the main result and
both reported separately from it.

A. Is any recovery an existential witnessed by its own right-hand side?
   `vacuity_scan.py`'s six probes have no case for `∃ x, x = e` -- which asserts
   nothing at all, yet is not `True`, not a hypothesis, not `rfl` and not
   `decide`-able, so it comes back `6_contentful`. One of the oracle's four
   recoveries has that shape. `exact ⟨_, rfl⟩` settles it.

B. Does the one repairable dead rung change anything?
   `simp_arith` (rung 9 of the pre-registered ladder) is deprecated in Lean
   v4.32.0 and errors out before it ever sees a goal, so rung 9 tested nothing.
   Lean's own deprecation message names the replacement, `simp +arith +decide`.
   Running that is not tuning the ladder -- it is running the rung the brief
   asked for, in the spelling this Lean still has. It is nevertheless kept out
   of the headline, because it was run after seeing the original rung was dead.

   Rung 6 (`nlinarith [sq_nonneg _, sq_nonneg _]`) is also dead and is NOT
   repaired: its only sample-independent repair is bare `nlinarith`, which the
   ladder already carries as rung 7.

ORDER AND BUDGET, both learned the hard way. A first attempt ran B before A at
the main verifier's 60s budget; `+decide` on a large `¬∃` goal hung the Lean
server hard enough that lean_interact killed it, the rebuild then exceeded its
own 300s budget, and `base_env` was left None -- after which every remaining
sample was scored `budget` for infrastructure reasons rather than measurement.
So:

  * A runs FIRST and its result is flushed to disk before B starts, because A
    is the question that can move a published number and B is a loophole check.
  * B runs at REPAIR_TIMEOUT, not the main verifier's budget. A supplementary
    pass may use a different budget as long as it says so, and `+decide` needs
    one that does not kill the server.
  * B aborts the moment the base environment is gone. A dead REPL produces
    `budget` labels that look like measurements and are not.

Run: python tests/audit/tactic_oracle_repair.py
"""
import io, json, os, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from verifier import LeanVerifier, VALID, TIMEOUT, VERIFIER_CRASH  # noqa: E402
import tactic_common as tc  # noqa: E402
from tactic_oracle import statement_prefix, hypotheses_contradictory  # noqa: E402
from vacuity_scan import ok, stmt_with  # noqa: E402

REPAIRED = [("simp_arith_repaired", "simp +arith +decide")]
EXISTS_EQ_PROBE = "exact ⟨_, rfl⟩"
# Deliberately below config.VERIFY_TIMEOUT_SECONDS; see the module docstring.
REPAIR_TIMEOUT = 20
PROBE_TIMEOUT = 15

OUT = os.path.join(_ROOT, "results", "tactic_oracle_repair.json")


def write(payload):
    json.dump(payload, io.open(OUT, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)


def main():
    oracle = {(r["set"], str(r["id"])): r
              for r in tc.J(os.path.join(_ROOT, "results", "tactic_oracle.jsonl"))}
    samples = tc.load_samples()
    recovered = [s for s in samples
                 if oracle.get((s["set"], str(s["id"])), {}).get("verdict") == "recovered"]
    unclosed = [s for s in samples
                if oracle.get((s["set"], str(s["id"])), {}).get("verdict")
                in ("none_closed", "budget")]

    t0 = time.perf_counter()
    v = LeanVerifier(setup=False, verbose=False)
    print("[repair] verifier ready in %.0fs" % (time.perf_counter() - t0))

    # ----------------------------------------------------------------- A
    print("[A] exists_eq probe over %d recoveries" % len(recovered))
    witnessed = []
    for s in recovered:
        hit = ok(v, stmt_with(s["statement"], EXISTS_EQ_PROBE))
        witnessed.append({"set": s["set"], "id": s["id"],
                          "witnessed_by_own_rhs": hit, "goal": s["goal"][:200]})
        print("  [exists_eq] %-22s %-38s %s"
              % (s["set"], str(s["id"])[:36],
                 "WITNESSED BY ITS OWN RHS" if hit else "not that shape"), flush=True)

    payload = {"exists_eq_probe": EXISTS_EQ_PROBE, "recoveries": witnessed,
               "repaired_rung": dict(REPAIRED),
               "repaired_rung_timeout_seconds": REPAIR_TIMEOUT,
               "rows": None, "aborted": None}
    write(payload)  # flush A before risking the server on B
    print("[A] %d of %d witnessed by their own RHS; flushed to %s"
          % (sum(1 for w in witnessed if w["witnessed_by_own_rhs"]),
             len(witnessed), OUT), flush=True)

    # ----------------------------------------------------------------- B
    print("[B] `%s` over %d samples the ladder did not close, budget %ds"
          % (REPAIRED[0][1], len(unclosed), REPAIR_TIMEOUT))
    out, aborted = [], None
    for k, s in enumerate(unclosed, 1):
        if getattr(v, "base_env", None) is None:
            aborted = ("base environment lost after %d of %d samples; the "
                       "remaining rows would be `budget` for infrastructure "
                       "reasons rather than measurement, so they are not "
                       "reported" % (k - 1, len(unclosed)))
            print("[B] ABORT: " + aborted, flush=True)
            break
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
                res = v.verify(prefix + "\n  " + tac + "\n", timeout=REPAIR_TIMEOUT)
            except Exception as e:  # noqa: BLE001
                res = {"outcome": VERIFIER_CRASH,
                       "errors": ["%s: %s" % (type(e).__name__, e)], "seconds": None}
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
        if verdict == "recovered" or k % 20 == 0:
            print("  [%3d/%3d] %-22s %-38s %s"
                  % (k, len(unclosed), s["set"], str(s["id"])[:36], verdict), flush=True)
        payload["rows"], payload["aborted"] = out, aborted
        write(payload)  # incremental: a kill never loses the completed rows

    payload["rows"], payload["aborted"] = out, aborted
    payload["attempted"] = len(unclosed)
    write(payload)
    print("[repair] B: %d/%d samples scored, %d additional genuine recoveries%s"
          % (len(out), len(unclosed),
             sum(1 for r in out if r["verdict"] == "recovered"),
             "" if not aborted else " (ABORTED: %s)" % aborted))


if __name__ == "__main__":
    main()
