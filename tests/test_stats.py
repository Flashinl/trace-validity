"""Unit tests for stats.py against independently computed reference values.

The reference intervals below were supplied with the task and computed
independently of this implementation. They test the FUNCTION, not the repo's
current counts -- wilson(36, 50) returns this interval whether or not 36 is
still the right numerator.

Run: python tests/test_stats.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from stats import (  # noqa: E402
    wilson, zero_event_upper, mcnemar_exact, cluster_warning, assert_deduplicated,
    min_discordant_for_significance, min_detectable_difference, mcnemar_power,
    two_proportion_z, rate, pct, DegenerateMetric, DuplicateRecords,
)

FAILURES = []


def check(name, got, want, tol=0.0005):
    ok = abs(got - want) <= tol
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<52} got={got:.5f} want={want:.5f}")
    if not ok:
        FAILURES.append(name)


def check_eq(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<52} got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(name)


print("wilson() -- reference intervals")
for k, n, point, lo, hi in [(21, 50, 0.42, 0.294, 0.558),
                            (36, 50, 0.72, 0.583, 0.825),
                            (26, 27, 0.963, 0.817, 0.993),
                            (22, 50, 0.44, 0.312, 0.577)]:
    l, h = wilson(k, n)
    check(f"wilson({k},{n}) point", k / n, point, 0.001)
    check(f"wilson({k},{n}) low", l, lo, 0.001)
    check(f"wilson({k},{n}) high", h, hi, 0.001)

print("\nwilson() -- boundary behaviour Wald gets wrong")
l, h = wilson(27, 27)
check_eq("wilson(27,27) upper stays in [0,1]", h <= 1.0, True)
check_eq("wilson(27,27) lower is not 1.0", l < 1.0, True)
l, h = wilson(0, 27)
check_eq("wilson(0,27) lower is 0", l == 0.0, True)
check_eq("wilson(0,27) upper is not 0", h > 0.0, True)

print("\nzero_event_upper() -- reference values")
check("zero_event_upper(11)", zero_event_upper(11), 0.238, 0.001)
check("zero_event_upper(23)", zero_event_upper(23), 0.122, 0.001)
check("zero_event_upper(27)", zero_event_upper(27), 0.105, 0.001)

print("\nmcnemar_exact() -- reference value")
p, nd = mcnemar_exact(1, 1)
check("mcnemar_exact(1,1) p", p, 1.000, 0.0005)
check_eq("mcnemar_exact(1,1) discordant", nd, 2)
p, nd = mcnemar_exact(0, 0)
check("mcnemar_exact(0,0) p (no discordant pairs)", p, 1.0)
p, _ = mcnemar_exact(6, 0)
check_eq("mcnemar_exact(6,0) reaches significance", p < 0.05, True)
p, _ = mcnemar_exact(5, 0)
check_eq("mcnemar_exact(5,0) does NOT", p < 0.05, False)
check_eq("min_discordant_for_significance() == 6", min_discordant_for_significance(), 6)

print("\npower")
check_eq("mcnemar_power with 2 expected discordant is ~0",
         mcnemar_power(50, 0.0, 0.04) < 0.20, True)
mde = min_detectable_difference(50, 0.04)
check_eq("min_detectable_difference(50, pi_d=0.04) is unattainable", mde, None)
mde2 = min_detectable_difference(50, 0.40)
check_eq("min_detectable_difference(50, pi_d=0.40) is attainable", mde2 is not None, True)

print("\ntwo_proportion_z() -- the comparison that should not be made")
z, p = two_proportion_z(21, 50, 36, 50)
check("two_proportion_z(21/50 vs 36/50) z", z, 3.030, 0.005)
check("two_proportion_z(21/50 vs 36/50) p", p, 0.0024, 0.0005)

print("\ncluster_warning()")
one_problem = [{"problem_unique_id": "P408", "sample_index": i} for i in range(50)]
fifty = [{"problem_unique_id": f"P{i}", "sample_index": i} for i in range(50)]
cw = cluster_warning(one_problem)
check_eq("50 steps of 1 problem -> clustered", cw["clustered"], True)
check_eq("  effective_n == 1", cw["effective_n"], 1)
cw = cluster_warning(fifty)
check_eq("50 distinct problems -> not clustered", cw["clustered"], False)
check_eq("  effective_n == 50", cw["effective_n"], 50)
check_eq("missing key -> None, not False", cluster_warning([{"a": 1}])["clustered"], None)

print("\nassert_deduplicated()")
dupes = [{"sample_index": i // 10, "temperature": 0.0} for i in range(500)]
try:
    assert_deduplicated(dupes)
    check_eq("500 rows / 50 keys raises", False, True)
except DuplicateRecords as e:
    check_eq("500 rows / 50 keys raises", True, True)
    print(f"        message: {str(e)[:96]}...")
check_eq("50 distinct keys pass",
         assert_deduplicated([{"sample_index": i, "temperature": 0.0} for i in range(50)]), True)

print("\nrate() integration")
r = rate(21, 50, records=one_problem)
check_eq("clustered rate suppresses the CI", "CLUSTERED" in str(r), True)
r = rate(37, 50, records=fifty)
check_eq("unclustered rate emits a CI", "95% CI" in str(r), True)
check_eq("  and no decimals on n<100", str(r).count("."), 0)
r = rate(37, 42, records=fifty, conditional_on="excluded statement_false + parse_skew")
check_eq("conditional rate is labelled secondary", "secondary analysis" in str(r), True)
try:
    rate(0, 50, field="answer_correct")
    check_eq("answer_correct raises", False, True)
except DegenerateMetric:
    check_eq("answer_correct raises", True, True)

print("\npct() precision rule")
check_eq("pct rounds to whole percent", pct(0.7708333), "77%")
check_eq("pct(0.42)", pct(0.42), "42%")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {FAILURES}")
    sys.exit(1)
print("all stats tests pass")
