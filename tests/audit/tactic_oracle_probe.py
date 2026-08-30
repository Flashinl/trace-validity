"""How much does each ORACLE RECOVERY actually assert?

The oracle recovered so few goals that each one carries real weight in the
headline, so each one gets the repo's full vacuity taxonomy rather than only the
contradictory-hypotheses probe Phase 2 requires. Probes and classification are
imported unchanged from `vacuity_scan.py`, which is where they are documented:

  P_true      goal is literally `True`
  P_assum     goal IS one of the hypotheses
  P_redrfl    goal is X = X syntactically
  P_substrfl  goal becomes X = X after substituting its own equations
  P_rfl       closes by kernel computation
  P_decide    decidable outright
  contra      hypotheses inconsistent -> everything vacuous

A recovery classified `6_contentful` is a recovery of a goal that asserts
something. Anything else is a recovery of a goal that did not need proving, and
that distinction is the whole point of counting recoveries at all.

Run: python tests/audit/tactic_oracle_probe.py
"""
import io, json, os, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from verifier import LeanVerifier  # noqa: E402
from vacuity_scan import PROBES, classify, ok, stmt_with  # noqa: E402
import tactic_common as tc  # noqa: E402
from tactic_oracle import split_binders, CONTRA_TACTICS, PROBE_TIMEOUT  # noqa: E402
from config import GOEDEL_LEAN4_HEADER  # noqa: E402


def main():
    oracle = {(r["set"], str(r["id"])): r
              for r in tc.J(os.path.join(_ROOT, "results", "tactic_oracle.jsonl"))}
    samples = [s for s in tc.load_samples()
               if oracle.get((s["set"], str(s["id"])), {}).get("verdict") == "recovered"]
    print("[probe] %d recoveries to characterise" % len(samples))

    t0 = time.perf_counter()
    v = LeanVerifier(setup=False, verbose=False)
    print("[probe] verifier ready in %.0fs" % (time.perf_counter() - t0))

    out = []
    for s in samples:
        stmt = s["statement"]
        p = {name: ok(v, stmt_with(stmt, tac)) for name, tac in PROBES}
        binders, _ = split_binders(stmt)
        contra = False
        if binders.strip():
            for tac in CONTRA_TACTICS:
                if ok(v, "%stheorem contra_probe %s : False := by\n  %s\n"
                      % (GOEDEL_LEAN4_HEADER, binders, tac)):
                    contra = True
                    break
        cls = classify(p, contra)
        rec = {"set": s["set"], "id": s["id"], "class": cls, "contra": contra,
               "rung": oracle[(s["set"], str(s["id"]))]["rung"],
               "tactic": oracle[(s["set"], str(s["id"]))]["tactic"],
               "goal": s["goal"][:200], "model_tactics": s["tactics"], **p}
        out.append(rec)
        print("  %-22s %-38s %-24s contra=%d  <- %s"
              % (s["set"], str(s["id"])[:36], cls, int(contra), rec["tactic"]),
              flush=True)

    json.dump(out, io.open(os.path.join(_ROOT, "results", "tactic_oracle_probe.json"),
                           "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("[probe] wrote results/tactic_oracle_probe.json")


if __name__ == "__main__":
    main()
