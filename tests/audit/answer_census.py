"""Problem-level census of `ground_truth` answer types, and the compute envelope.

Feeds Phase 1 (how many integer / simple-fraction problems actually exist) and
the Phase 0 gate (how many step-proofs a trajectory-level run would cost).

No Lean, no GPU, no network.
Run: HF_HUB_OFFLINE=1 python tests/audit/answer_census.py
"""
import collections
import os
import re
import sys
from fractions import Fraction

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

from datasets import load_dataset  # noqa: E402

P = print

# A "simple fraction" is a single ratio of two integer literals, in any of the
# brace styles FormalStep uses. Anything with an operator, a radical, a symbol,
# a unit or prose is NOT simple and goes to `other`.
#
# BOTH \frac arguments are independently optional-braced: LaTeX takes a single
# character as a whole argument. So \frac19 is 1/9 and \dfrac34 is 3/4, not
# malformed. Requiring braces on the second argument misfiled #836 and #931 as
# `other` -- the same class of bug that once put 13880 rows in UNKNOWN here.
_ARG = r"(?:\{(-?\d+)\}|(\d))"
_FRAC = re.compile(r"^(-?)\\[dt]?frac" + _ARG + _ARG + r"$")
_SLASH = re.compile(r"^(-?\d+)/(\d+)$")
_INT = re.compile(r"^-?\d+$")

# Magnitude above which a value is "large" -- the supervisor's drop rule. Set
# from the data, not guessed: see the printed tail of the integer distribution.
LARGE = 10 ** 6


def strip_latex(s):
    """Cosmetic LaTeX only. Never changes the VALUE, only the spelling."""
    t = (s or "").strip()
    t = t.replace("\\!", "").replace("\\,", "").replace("\\;", "").replace("\\ ", "")
    t = t.replace("$", "").replace(" ", "")
    t = re.sub(r"^\\left", "", t)
    t = re.sub(r"\\right$", "", t)
    t = t.replace(",", "")          # 45,045 -> 45045 (thousands separator)
    return t


def classify(raw):
    """(kind, value) where kind is integer | simple_fraction | other."""
    t = strip_latex(raw)
    if _INT.fullmatch(t):
        return "integer", Fraction(int(t))
    m = _FRAC.match(t)
    if m:
        num = m.group(2) if m.group(2) is not None else m.group(3)
        den = m.group(4) if m.group(4) is not None else m.group(5)
        v = Fraction(int(num), int(den))
        return "simple_fraction", (-v if m.group(1) else v)
    m = _SLASH.match(t)
    if m:
        return "simple_fraction", Fraction(int(m.group(1)), int(m.group(2)))
    return "other", None


def main():
    ds = load_dataset("liuchengwu/FormalStep", split="train")
    puid, gt, lvl, prev = (ds["problem_unique_id"], ds["ground_truth"],
                           ds["level"], ds["previous_steps"])

    G, L = {}, {}
    traj = collections.OrderedDict()
    for i in range(len(ds)):
        G[puid[i]] = gt[i]
        L[puid[i]] = lvl[i]
        traj.setdefault((puid[i], tuple(prev[i])), 0)
        traj[(puid[i], tuple(prev[i]))] += 1

    P("=" * 78)
    P(f"ANSWER-TYPE CENSUS  ({len(G)} problems)")
    P("=" * 78)

    kinds, vals, examples = collections.Counter(), {}, collections.defaultdict(list)
    for p, raw in G.items():
        k, v = classify(raw)
        kinds[k] += 1
        vals[p] = (k, v)
        examples[k].append((p, raw))
    P(f"  {dict(kinds)}")

    big = [(p, G[p], v) for p, (k, v) in vals.items()
           if v is not None and abs(v) >= LARGE]
    P(f"\n  |value| >= {LARGE:,}: {len(big)}")
    for p, raw, v in sorted(big, key=lambda x: -abs(x[2])):
        P(f"    {p.replace('math_train_counting_and_probability_','#'):<8}{raw!r:<34}{float(v):.6g}")

    P(f"\n  the `other` bucket, all {kinds['other']}:")
    for p, raw in sorted(examples["other"]):
        P(f"    {p.replace('math_train_counting_and_probability_','#'):<8}{raw!r}")

    # ---- eligible pool after the supervisor's drop rules ------------------
    P("\n" + "=" * 78)
    P("ELIGIBLE POOL AFTER DROPS")
    P("=" * 78)
    elig = {p: kv for p, kv in vals.items()
            if kv[0] != "other" and abs(kv[1]) < LARGE}
    ec = collections.Counter(k for k, _ in elig.values())
    P(f"  dropped `other`      : {kinds['other']}")
    P(f"  dropped large-value  : {len(big)}")
    P(f"  eligible             : {len(elig)}   {dict(ec)}")

    P("\n  eligible by answer type x level:")
    P(f"    {'level':<10}{'integer':<10}{'fraction':<10}{'total':<8}pop share")
    poplv = collections.Counter(L.values())
    for lv in ("Level 1", "Level 2", "Level 3", "Level 4", "Level 5"):
        ni = sum(1 for p, (k, _) in elig.items() if k == "integer" and L[p] == lv)
        nf = sum(1 for p, (k, _) in elig.items() if k == "simple_fraction" and L[p] == lv)
        P(f"    {lv:<10}{ni:<10}{nf:<10}{ni+nf:<8}{100*poplv[lv]/len(G):.1f}%")

    P("\n  NOTE the population level shares quoted in the brief (L1 5.9 / L2 12.9 /")
    P("  L3 17.7 / L4 17.9 / L5 45.6) are ROW shares over all 30809 rows. The")
    P("  PROBLEM-level shares over 500 problems are:")
    for lv in ("Level 1", "Level 2", "Level 3", "Level 4", "Level 5"):
        P(f"    {lv}: {poplv[lv]:>4} problems = {100*poplv[lv]/len(G):.1f}%")

    # ---- compute envelope -------------------------------------------------
    P("\n" + "=" * 78)
    P("COMPUTE ENVELOPE for a TRAJECTORY-level trace-validity axis")
    P("=" * 78)
    steps_by_problem = collections.Counter()
    traj_by_problem = collections.Counter()
    for (p, steps), n in traj.items():
        steps_by_problem[p] += len(steps)
        traj_by_problem[p] += 1
    for label, pool in (("all 500 problems", list(G)),
                        ("eligible pool", list(elig))):
        st = sum(steps_by_problem[p] for p in pool)
        tj = sum(traj_by_problem[p] for p in pool)
        P(f"  {label:<20} problems {len(pool):<5} trajectories {tj:<6} steps {st}")
    P("")
    for n in (20, 200):
        pool = sorted(elig)[:n]
        st = sum(steps_by_problem[p] for p in pool)
        tj = sum(traj_by_problem[p] for p in pool)
        P(f"  first {n:<4} eligible: trajectories {tj:<5} steps {st:<6} "
          f"-> x2 temperatures = {2*st} step-proofs")


if __name__ == "__main__":
    main()
