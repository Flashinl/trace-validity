"""Phase 2: derive every denominator from one stated exclusion rule.

The 1-of-39 error was excluding samples from the numerator while leaving them in
the denominator. The fix is not a different number, it is a RULE applied to both
sides, printed next to whatever it produces.

Run: python tests/audit/denominators.py
"""
import io, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from stats import rate, zero_event_upper, pct  # noqa: E402

J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]

# THE EXCLUSION RULE, stated once and applied to both sides of every fraction.
#
# A sample is TESTABLE iff the verifier reached a verdict on the MODEL'S PROOF.
# It is excluded -- from numerator AND denominator -- when the goal was never put
# to the model:
NO_VERDICT = {"statement_error",     # Lean rejected the goal; the proof was never judged
              "statement_mismatch",  # something compiled, but not the target theorem
              "parse_failure",       # nothing usable reached Lean
              "timeout", "verifier_crash"}
#
# `maxRecDepth` is NOT an exclusion. It is verifier configuration. Raising it
# turned sample 12 from a spurious failure into a genuine pass, so 12 stays in
# the denominator as a success. Excluding it would repeat the original error in
# the opposite direction.

SETS = [("T=0.0", "results/verify3_temp0.0.jsonl", "traces/temp0.0_n50_1each/traces.jsonl"),
        ("T=0.2", "results/verify3_temp0.2.jsonl", "traces/temp0.2_n50_1each/traces.jsonl")]

print("=" * 84)
print("PHASE 2 -- DENOMINATORS, DERIVED FROM ONE RULE")
print("=" * 84)
print("\nRULE: testable iff outcome not in", sorted(NO_VERDICT))
print("      excluded samples leave BOTH numerator and denominator")
print("      maxRecDepth is configuration, not an exclusion\n")

out = {}
for name, vp, tp in SETS:
    vers = {r["sample_index"]: r for r in J(vp)}
    traces = {r["sample_index"]: r for r in J(tp)}
    recs = [dict(r, problem_unique_id=traces[i].get("problem_unique_id"))
            for i, r in vers.items()]

    testable = {i: r for i, r in vers.items() if r["outcome"] not in NO_VERDICT}
    excluded = sorted(set(vers) - set(testable))

    prov = {i: r for i, r in vers.items() if r["state"] == "Success of Proof"}
    unprov = {i: r for i, r in vers.items() if r["state"] == "Failure of Proof"}
    prov_t = {i: r for i, r in prov.items() if i in testable}
    unprov_t = {i: r for i, r in unprov.items() if i in testable}

    prov_fail = sorted(i for i, r in prov_t.items() if r["outcome"] != "valid")
    certified_unprov = sorted(i for i, r in unprov_t.items() if r["outcome"] == "valid")

    print(f"--- {name} " + "-" * 68)
    print(f"  excluded (no verdict): {excluded}  -> {len(excluded)} of {len(vers)} untestable")
    for i in excluded:
        print(f"      s{i:<3} {vers[i]['outcome']:<18} state={vers[i]['state']}")
    print(f"  sample 12 outcome: {vers[12]['outcome']}  (kept in the denominator)")
    print()
    print(f"  headline validity          : {rate(sum(1 for r in vers.values() if r['outcome']=='valid'), len(vers), records=recs)}")
    print(f"  validity over testable     : {rate(sum(1 for r in testable.values() if r['outcome']=='valid'), len(testable), records=recs)}")
    print()
    print(f"  dataset-provable           : {len(prov)}   testable: {len(prov_t)}  (excluded: {sorted(set(prov)-set(prov_t))})")
    print(f"  FAILED a provable statement: {rate(len(prov_fail), len(prov_t), records=recs)}   samples={prov_fail}")
    print(f"  dataset-unprovable         : {len(unprov)}  testable: {len(unprov_t)}  (excluded: {sorted(set(unprov)-set(unprov_t))})")
    print(f"  certified an unprovable one: {len(certified_unprov)}/{len(unprov_t)}"
          f"   -> 0 events in n={len(unprov_t)}, 95% upper bound {pct(zero_event_upper(len(unprov_t)))}")
    print()
    out[name] = {"untestable": excluded, "prov_testable": len(prov_t),
                 "prov_fail": prov_fail, "unprov_testable": len(unprov_t),
                 "certified": certified_unprov}

print("=" * 84)
print("THE 1-OF-39 CORRECTION, WORKED")
print("=" * 84)
d = out["T=0.0"]
print(f"  published    : 1 of 39   -- 12 and 19 removed from the numerator, left in the denominator")
print(f"  task target  : 1 of 37   -- both removed from BOTH sides (correct PRE-maxRecDepth-fix)")
print(f"  correct now  : {len(d['prov_fail'])} of {d['prov_testable']}   -- only 19 is excluded; 12 is now a PASS and stays in")
print(f"                 {rate(len(d['prov_fail']), d['prov_testable'])}")
print()
print("  Untestable count, applied consistently with the same rule:")
print(f"    {len(d['untestable'])} of 50 (samples {d['untestable']}) -- both statement_error.")
print("    Sample 12 is NOT untestable: with maxRecDepth raised it produces a real")
print("    verdict, and that verdict is `valid`.")

json.dump(out, io.open("results/denominators.json", "w", encoding="utf-8"), indent=2)
print("\nwrote results/denominators.json")
