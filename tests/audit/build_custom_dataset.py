"""Phase 1: build the stratified custom dataset.

Spec: drop unmatchable and large-value answers, then stratified-sample 200
problems, 100 integer + 100 simple fraction, stratifying WITHIN each arm by
level proportional to the population.

Two things the spec could not know, both surfaced rather than worked around:

  1. There are 157 simple-fraction problems in the whole dataset (the brief says
     155; `\\frac19` and `\\dfrac34` are valid LaTeX and were being misfiled).
     Taking 100 is 64% of every fraction that exists -- close to a census, not a
     sample.
  2. Proportional level stratification of a 100-problem fraction arm is
     INFEASIBLE: it asks for more Level 1 and Level 2 fraction problems than
     exist. The script reports the shortfall per cell instead of quietly
     reallocating.

Emits data/custom_155.jsonl (Design C, balanced 77+78 -- the ACCEPTED design)
plus the alternative designs with realised cell counts, so the choice stays auditable.

No Lean, no GPU, no network.
Run: HF_HUB_OFFLINE=1 python tests/audit/build_custom_dataset.py
"""
import collections
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datasets import load_dataset  # noqa: E402

from answer_census import LARGE, classify  # noqa: E402

SEED = 20260902
LEVELS = ("Level 1", "Level 2", "Level 3", "Level 4", "Level 5")
P = print


def largest_remainder(total, shares, keys):
    """Apportion `total` over `keys` by `shares`, largest-remainder method."""
    raw = {k: total * shares[k] for k in keys}
    base = {k: int(raw[k]) for k in keys}
    rem = total - sum(base.values())
    order = sorted(keys, key=lambda k: raw[k] - base[k], reverse=True)
    for k in order[:rem]:
        base[k] += 1
    return base


def main():
    ds = load_dataset("liuchengwu/FormalStep", split="train")
    puid, gt, lvl, prev = (ds["problem_unique_id"], ds["ground_truth"],
                           ds["level"], ds["previous_steps"])

    problems, traj_n, step_n = {}, collections.Counter(), collections.Counter()
    seen = set()
    for i in range(len(ds)):
        problems[puid[i]] = {"ground_truth": gt[i], "level": lvl[i]}
        key = (puid[i], tuple(prev[i]))
        if key not in seen:
            seen.add(key)
            traj_n[puid[i]] += 1
            step_n[puid[i]] += len(prev[i])

    # ---- eligibility ------------------------------------------------------
    pool = {}
    drops = collections.Counter()
    for p, meta in problems.items():
        kind, val = classify(meta["ground_truth"])
        if kind == "other":
            drops["unmatchable"] += 1
            continue
        if abs(val) >= LARGE:
            drops["large_value"] += 1
            continue
        pool[p] = {**meta, "kind": kind, "value": val}

    P("=" * 78)
    P("PHASE 1  CUSTOM DATASET")
    P("=" * 78)
    P(f"  problems total       {len(problems)}")
    P(f"  dropped unmatchable  {drops['unmatchable']}")
    P(f"  dropped large-value  {drops['large_value']}")
    P(f"  eligible             {len(pool)}")
    arms = collections.Counter(v["kind"] for v in pool.values())
    P(f"  eligible by arm      {dict(arms)}")

    # ---- population level shares, PROBLEM level ---------------------------
    poplv = collections.Counter(m["level"] for m in problems.values())
    shares = {lv: poplv[lv] / len(problems) for lv in LEVELS}
    P("\n  population level shares (problem level, all 500):")
    for lv in LEVELS:
        P(f"    {lv}: {poplv[lv]:>4} = {100*shares[lv]:.1f}%")

    avail = {arm: {lv: [p for p, v in pool.items()
                        if v["kind"] == arm and v["level"] == lv]
                   for lv in LEVELS}
             for arm in ("integer", "simple_fraction")}
    P("\n  available eligible problems by arm x level:")
    P(f"    {'level':<10}{'integer':<10}{'fraction':<10}target/100")
    tgt = largest_remainder(100, shares, LEVELS)
    for lv in LEVELS:
        P(f"    {lv:<10}{len(avail['integer'][lv]):<10}"
          f"{len(avail['simple_fraction'][lv]):<10}{tgt[lv]}")

    # ---- feasibility ------------------------------------------------------
    P("\n" + "=" * 78)
    P("FEASIBILITY OF THE SPEC DESIGN (100 + 100, proportional within arm)")
    P("=" * 78)
    short = {}
    for arm in ("integer", "simple_fraction"):
        s = {lv: tgt[lv] - len(avail[arm][lv]) for lv in LEVELS
             if tgt[lv] > len(avail[arm][lv])}
        short[arm] = s
        if s:
            P(f"  {arm}: INFEASIBLE, short by {s} "
              f"(total shortfall {sum(s.values())})")
        else:
            P(f"  {arm}: feasible")

    def draw(arm, n, rng):
        """Proportional where possible; spill the shortfall into levels that
        have room, largest-pool-first. Every row records which rule applied."""
        want = largest_remainder(n, shares, LEVELS)
        got, rule = {}, {}
        deficit = 0
        for lv in LEVELS:
            have = avail[arm][lv]
            k = min(want[lv], len(have))
            deficit += want[lv] - k
            got[lv] = rng.sample(sorted(have), k)
            for p in got[lv]:
                rule[p] = f"{arm}|{lv}|proportional_target_{want[lv]}"
        while deficit > 0:
            room = sorted(LEVELS,
                          key=lambda l: len(avail[arm][l]) - len(got[l]),
                          reverse=True)
            placed = False
            for lv in room:
                spare = [p for p in avail[arm][lv] if p not in got[lv]]
                if spare:
                    p = rng.choice(sorted(spare))
                    got[lv].append(p)
                    rule[p] = f"{arm}|{lv}|spill_from_undersupplied_levels"
                    deficit -= 1
                    placed = True
                    break
            if not placed:
                break
        return got, rule, deficit

    # Design C (balanced_77_78) is the ACCEPTED design. The other two are kept
    # and reported so the choice stays auditable, but only C is shipped.
    CHOSEN = "balanced_77_78"
    designs = {
        "balanced_77_78": {"integer": 77, "simple_fraction": 78},
        "proportional_100_55": {"integer": 100, "simple_fraction": 55},
        "spec_100_100": {"integer": 100, "simple_fraction": 100},
    }
    summary = {}
    chosen_rows = None
    for name, sizes in designs.items():
        rng = random.Random(SEED)
        cells, rules, leftover = {}, {}, {}
        rows = []
        for arm, n in sizes.items():
            got, rule, deficit = draw(arm, n, rng)
            cells[arm] = {lv: len(got[lv]) for lv in LEVELS}
            leftover[arm] = deficit
            rules.update(rule)
            for lv in LEVELS:
                for p in got[lv]:
                    rows.append({
                        "problem_unique_id": p,
                        "level": lv,
                        "answer_type": arm,
                        "ground_truth": pool[p]["ground_truth"],
                        "ground_truth_value": str(pool[p]["value"]),
                        "n_trajectories": traj_n[p],
                        "n_steps": step_n[p],
                        "selection_rule": rules[p],
                        "design": name,
                        "seed": SEED,
                    })
        summary[name] = {"sizes": sizes, "cells": cells,
                         "unplaceable": leftover, "n_rows": len(rows)}
        if name == CHOSEN:
            chosen_rows = rows

        P(f"\n  --- design {name} (n={len(rows)}) ---")
        P(f"    {'level':<10}{'integer':<10}{'fraction':<10}total")
        for lv in LEVELS:
            a = cells["integer"][lv]
            b = cells["simple_fraction"][lv]
            P(f"    {lv:<10}{a:<10}{b:<10}{a+b}")
        P(f"    unplaceable after spill: {leftover}")
        frac_share = sizes["simple_fraction"] / arms["simple_fraction"]
        P(f"    fraction arm is {100*frac_share:.0f}% of every fraction problem "
          f"that exists ({sizes['simple_fraction']}/{arms['simple_fraction']})")

    dest = os.path.join(_ROOT, "data")
    os.makedirs(dest, exist_ok=True)
    out = os.path.join(dest, "custom_155.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for r in chosen_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    P(f"\n  wrote {out}  ({len(chosen_rows)} rows, design {CHOSEN} -- ACCEPTED)")

    js = os.path.join(_ROOT, "results", "custom_dataset.json")
    with open(js, "w", encoding="utf-8") as fh:
        json.dump({"seed": SEED, "chosen_design": CHOSEN,
                   "eligible": len(pool), "arms": dict(arms),
                   "drops": dict(drops), "population_level_shares": shares,
                   "designs": summary}, fh, indent=2)
    P(f"  wrote {js}")


if __name__ == "__main__":
    main()
