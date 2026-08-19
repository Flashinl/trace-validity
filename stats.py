"""The one place in this repo where a rate becomes a number.

Every reported percentage must come from here. Nothing else may divide two counts
and print the result, because the failure modes below are invisible at the call
site and this module is where they are caught:

  * Wald intervals. At this repo's sample sizes and extreme proportions the
    normal approximation is wrong -- 26/27 gives a Wald upper bound above 100%.
    `wilson()` is the only interval offered.
  * Zero counts. "Zero false positives" is not a rate of zero; it is a rate whose
    upper bound depends on n. `zero_event_upper()` supplies the bound.
  * Clustered observations. 50 consecutive CoT steps of ONE problem are not 50
    independent trials, and a binomial interval over them is invalid. `rate()`
    refuses to emit a bare interval for clustered records.
  * Duplicate rows. The baseline trace file holds 500 records but 50 distinct
    generations; a rate over 500 has an interval ~3x too narrow.
    `assert_deduplicated()` fails loudly.
  * Degenerate fields. `answer_correct` was defined as `trace_valid and not
    has_sorry`, so any accuracy derived from it is a function of the validity
    axis. `rate()` raises rather than compute it.

Precision rule: no rate on n < 100 is printed to finer than a whole percent.
"""
import math
from collections import Counter

Z95 = 1.96

# Fields whose definition makes any derived rate meaningless. See issue #5.
DEGENERATE_FIELDS = {"answer_correct", "invalid_accuracy", "valid_accuracy",
                     "overall_accuracy"}


class DegenerateMetric(ValueError):
    """Raised when asked to compute a rate from a structurally circular field."""


class DuplicateRecords(ValueError):
    """Raised when a rate would be computed over repeated observations."""


# --------------------------------------------------------------- intervals
def wilson(k, n, z=Z95):
    """Wilson score interval for a binomial proportion.

    Not Wald. Wald is `p +- z*sqrt(p(1-p)/n)`, which at 26/27 returns an upper
    bound of 1.03 -- outside the parameter space -- and at k=0 returns the
    degenerate [0, 0]. Wilson is well behaved at both extremes, which is where
    this repo's numbers live.

    Returns (low, high) as fractions.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= k <= n:
        raise ValueError(f"k={k} out of range for n={n}")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo, hi = centre - half, centre + half
    # At the extremes the bound is analytically exact; floating point leaves
    # residue of order 1e-18 that would otherwise print as a non-zero lower
    # bound for a count of zero.
    if k == 0:
        lo = 0.0
    if k == n:
        hi = 1.0
    return max(0.0, lo), min(1.0, hi)


def zero_event_upper(n, conf=0.95):
    """Upper bound on a rate when the event was observed ZERO times in n trials.

    Exact: the largest p for which P(0 events) >= 1-conf, i.e. 1 - (1-conf)^(1/n).
    (The familiar 3/n "rule of three" is its large-n approximation.)

    Observing zero does not mean the rate is zero. At n=11 the true rate could be
    as high as 24%.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    return 1 - (1 - conf) ** (1.0 / n)


# --------------------------------------------------------------- tests
def _binom_pmf(k, n, p=0.5):
    return math.comb(n, k) * p ** k * (1 - p) ** (n - k)


def mcnemar_exact(b, c):
    """Two-sided exact binomial McNemar test on discordant pairs.

    The correct test for a PAIRED design. An independent two-sample test is
    wrong when the same 50 problems are run at both temperatures: it discards
    the pairing and answers a question nobody asked.

    Only the b+c discordant pairs carry information; concordant pairs are
    uninformative about a difference and are excluded by construction.

    Returns (p_value, n_discordant).
    """
    n = b + c
    if n == 0:
        return 1.0, 0
    obs = _binom_pmf(b, n)
    p = sum(_binom_pmf(i, n) for i in range(n + 1) if _binom_pmf(i, n) <= obs + 1e-12)
    return min(1.0, p), n


def min_discordant_for_significance(alpha=0.05):
    """Fewest discordant pairs at which a two-sided exact test CAN reach alpha.

    Even a unanimous split cannot be significant below this count, so a study
    with fewer discordant pairs than this cannot reject regardless of the data.
    """
    n = 1
    while 2 * _binom_pmf(0, n) >= alpha:
        n += 1
        if n > 1000:
            return None
    return n


def mcnemar_power(n_pairs, p01, p10, alpha=0.05):
    """Exact power of the two-sided McNemar test.

    Enumerates the trinomial over (b, c) discordant counts and sums the
    probability of the rejection region.
    """
    p_conc = 1 - p01 - p10
    if p_conc < 0:
        raise ValueError("p01 + p10 must be <= 1")
    power = 0.0
    for m in range(n_pairs + 1):
        # probability that exactly m pairs are discordant
        p_d = p01 + p10
        if p_d == 0:
            continue
        p_m = math.comb(n_pairs, m) * p_d ** m * p_conc ** (n_pairs - m)
        if p_m < 1e-15:
            continue
        q = p10 / p_d
        for b in range(m + 1):
            pval, _ = mcnemar_exact(b, m - b)
            if pval < alpha:
                power += p_m * math.comb(m, b) * q ** b * (1 - q) ** (m - b)
    return power


def min_detectable_difference(n_pairs, discordant_rate, alpha=0.05, power=0.80):
    """Smallest |p10 - p01| detectable at the given power, holding the discordant
    rate fixed at its observed value.

    Returns None when NO difference is detectable -- which is the honest answer
    for a design whose expected discordant count is below
    `min_discordant_for_significance()`.
    """
    lo, hi = 0.0, discordant_rate
    if mcnemar_power(n_pairs, 0.0, discordant_rate, alpha) < power:
        return None                      # even a total split is underpowered
    for _ in range(40):
        mid = (lo + hi) / 2
        p10 = (discordant_rate + mid) / 2
        p01 = (discordant_rate - mid) / 2
        if mcnemar_power(n_pairs, p01, p10, alpha) >= power:
            hi = mid
        else:
            lo = mid
    return hi


def _norm_sf(x):
    return 0.5 * math.erfc(x / math.sqrt(2))


def two_proportion_z(k1, n1, k2, n2):
    """Pooled two-proportion z test. Returns (z, p_two_sided).

    VALID ONLY FOR INDEPENDENT SAMPLES DRAWN FROM THE SAME POPULATION. It is the
    wrong test for this repo's headline comparison (baseline vs n50), because
    those are different populations -- 50 consecutive steps inside one problem
    versus 50 first-steps of 50 problems. Callers must attach that confound;
    `compare_sets()` below refuses to report the p-value without it.
    """
    p1, p2 = k1 / n1, k2 / n2
    pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p2 - p1) / se
    return z, 2 * _norm_sf(abs(z))


# --------------------------------------------------------------- clustering
def cluster_warning(records, key="problem_unique_id"):
    """Are these records independent observations?

    Returns a dict with `clustered` True when the records concentrate in far
    fewer clusters than there are records. 50 CoT steps of ONE problem share a
    chain of arithmetic: when a value goes wrong at one step, later steps inherit
    it, so the outcomes are correlated and a binomial interval understates the
    uncertainty badly. The effective sample size is nearer the number of
    problems than the number of steps.
    """
    ids = [r.get(key) for r in records]
    known = [i for i in ids if i is not None]
    n = len(records)
    clusters = len(set(known)) if known else None
    if clusters is None:
        return {"clustered": None, "n": n, "clusters": None,
                "reason": f"no `{key}` on these records; independence unverifiable"}
    biggest = max(Counter(known).values()) if known else 0
    clustered = clusters < n
    return {
        "clustered": clustered, "n": n, "clusters": clusters,
        "largest_cluster": biggest,
        "effective_n": clusters,
        "reason": (f"{n} observations from only {clusters} problem(s); largest "
                   f"cluster {biggest}. Observations within a problem are "
                   f"correlated, so a binomial interval is not valid."
                   if clustered else
                   f"{n} observations from {clusters} distinct problems"),
    }


def assert_deduplicated(records, keys=("sample_index", "temperature")):
    """Fail loudly if a rate would be computed over repeated observations.

    The baseline trace file holds 500 rows but 50 distinct generations -- all 10
    trajectories per sample are byte-identical under greedy decoding. A rate over
    500 rows yields an interval about three times too narrow, built from 450
    duplicates.
    """
    seen = Counter(tuple(r.get(k) for k in keys) for r in records)
    dupes = {k: v for k, v in seen.items() if v > 1}
    if dupes:
        example = next(iter(dupes.items()))
        raise DuplicateRecords(
            f"{len(records)} records but {len(seen)} distinct {keys} keys; "
            f"{sum(dupes.values()) - len(dupes)} duplicate rows "
            f"(e.g. {example[0]} appears {example[1]}x). Deduplicate before "
            f"computing a rate -- an interval over duplicates is far too narrow."
        )
    return True


# --------------------------------------------------------------- reporting
def pct(x):
    """Whole percent. No rate on n < 100 in this repo earns a decimal place."""
    return f"{round(100 * x):.0f}%"


class Rate:
    """A rate that knows whether its own interval is trustworthy."""

    def __init__(self, k, n, label="", clustered=False, cluster_note="",
                 conditional_on=None):
        self.k, self.n, self.label = k, n, label
        self.clustered, self.cluster_note = clustered, cluster_note
        self.conditional_on = conditional_on
        self.point = k / n if n else float("nan")
        self.lo, self.hi = wilson(k, n) if n else (float("nan"),) * 2

    def __str__(self):
        if not self.n:
            return f"{self.k}/0 = n/a"
        base = f"{self.k}/{self.n} = {pct(self.point)}"
        if self.clustered:
            return (f"{base}  **CLUSTERED — interval not valid** "
                    f"({self.cluster_note})")
        s = f"{base} (95% CI {pct(self.lo)}–{pct(self.hi)})"
        if self.conditional_on:
            s += f"  [secondary analysis, conditional on: {self.conditional_on}]"
        return s

    def md(self):
        """Markdown table cell."""
        if not self.n:
            return "n/a"
        if self.clustered:
            return f"**{self.k}/{self.n} = {pct(self.point)}** — CLUSTERED, no valid CI"
        return f"**{self.k}/{self.n} = {pct(self.point)}** [{pct(self.lo)}–{pct(self.hi)}]"


def rate(k, n, label="", records=None, cluster_key="problem_unique_id",
         conditional_on=None, field=None):
    """The single entry point for turning two counts into a reported number.

    Pass `records` and the interval is suppressed when they are clustered.
    Pass `field` and a structurally degenerate metric raises instead of printing.
    """
    if field and field in DEGENERATE_FIELDS:
        raise DegenerateMetric(
            f"`{field}` is derived from trace_valid (answer_correct = trace_valid "
            f"and not has_sorry), so any rate computed from it is a function of "
            f"the validity axis, not a second measurement. It was identically 0.0 "
            f"for exactly this reason. Refusing to compute."
        )
    clustered, note = False, ""
    if records is not None:
        assert_deduplicated(records)
        cw = cluster_warning(records, key=cluster_key)
        if cw["clustered"]:
            clustered, note = True, cw["reason"]
    return Rate(k, n, label, clustered, note, conditional_on)
