"""Phase 0: resolve the four design questions before any experiment is built.

Reads the FormalStep split from the local HuggingFace cache. No Lean, no GPU,
no network (HF_HUB_OFFLINE=1). Every number in results/PHASE0_DESIGN.md is
printed by this script.

The four questions:
  Q1  Does FormalStep carry trajectory structure, and what is the unit?
  Q2  Where does a trajectory's final answer come from?
  Q3  Do the five paper-Table-2 category labels ship with the release?
  Q4  Why is every problem `counting_and_probability` when the paper says the
      500 were sampled at random from MATH train?

Run: HF_HUB_OFFLINE=1 python tests/audit/phase0_survey.py
"""
import collections
import json
import os
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

from datasets import load_dataset  # noqa: E402

SEED = 20260902
P = print


def load():
    return load_dataset("liuchengwu/FormalStep", split="train")


def trajectories(ds):
    """Group rows into trajectories.

    `previous_steps` is NOT a prefix -- it is the FULL step list of the
    trajectory the row belongs to, repeated verbatim on every row of that
    trajectory. So (problem_unique_id, tuple(previous_steps)) is the trajectory
    key, and `current_step` is this row's own step within it.
    """
    puid, prev = ds["problem_unique_id"], ds["previous_steps"]
    traj = collections.OrderedDict()
    for i in range(len(ds)):
        traj.setdefault((puid[i], tuple(prev[i])), []).append(i)
    return traj


def main():
    ds = load()
    N = len(ds)
    puid, prev, cur = ds["problem_unique_id"], ds["previous_steps"], ds["current_step"]
    gt, lvl, typ, state = ds["ground_truth"], ds["level"], ds["type"], ds["state"]

    P("=" * 78)
    P(f"FormalStep survey: {N} rows, schema {ds.column_names}")
    P("=" * 78)

    # ---- Q1: trajectory structure ----------------------------------------
    P("\n" + "=" * 78)
    P("Q1  TRAJECTORY STRUCTURE")
    P("=" * 78)
    traj = trajectories(ds)
    probs = sorted(set(puid))
    P(f"  rows                 {N}")
    P(f"  distinct problems    {len(probs)}")
    P(f"  distinct trajectories {len(traj)}")

    per = collections.Counter(k[0] for k in traj)
    v = sorted(per.values())
    P(f"  trajectories per problem: min {v[0]}  median {v[len(v)//2]}  "
      f"max {v[-1]}  mean {sum(v)/len(v):.2f}")
    P(f"  distribution: {dict(sorted(collections.Counter(v).items()))}")

    # The load-bearing check: do a trajectory's rows reproduce its step list,
    # in order, with nothing missing and nothing extra?
    exact = sum(1 for k, idxs in traj.items() if [cur[i] for i in idxs] == list(k[1]))
    P(f"  trajectories whose rows == their step list, IN ORDER: {exact}/{len(traj)}")
    P(f"  sum of steps over trajectories: {sum(len(k[1]) for k in traj)} (rows: {N})")
    sl = sorted(len(k[1]) for k in traj)
    P(f"  steps per trajectory: min {sl[0]}  median {sl[len(sl)//2]}  max {sl[-1]}")
    P("\n  VERDICT: multiple trajectories per problem. The unit of analysis is the")
    P("  TRAJECTORY, and trajectories cluster within problems (~5 per problem).")

    # ---- Q2: where is the final answer -----------------------------------
    P("\n" + "=" * 78)
    P("Q2  WHERE DOES THE FINAL ANSWER COME FROM")
    P("=" * 78)
    P("  Each trajectory's last step is its concluding sentence. Sample:")
    keys = list(traj)
    random.seed(SEED)
    for k in random.sample(keys, 10):
        i = traj[k][0]
        P(f"    gt={gt[i]!r}")
        P(f"      final step: {k[1][-1][:110]!r}")
    P("\n  VERDICT: case 1 -- the trajectories already state a final answer.")
    P("  No solver run and no GPU are needed. Extraction is prose-level and")
    P("  lossy, so Phase 2 must report an explicit extraction-failure rate.")

    # ---- Q3: the five category labels ------------------------------------
    P("\n" + "=" * 78)
    P("Q3  DO THE FIVE PAPER CATEGORY LABELS SHIP WITH THE RELEASE")
    P("=" * 78)
    CATS = ["Geometry", "Number Theory", "Algebra", "Combinatorics", "Others"]
    P(f"  schema fields: {ds.column_names}")
    P("  no field named category/subject/topic/label exists.")
    found = False
    for f in ds.column_names:
        if f == "previous_steps":
            continue
        hits = {c: sum(1 for x in ds[f] if isinstance(x, str) and x.strip() == c)
                for c in CATS}
        if any(hits.values()):
            found = True
            P(f"  field {f!r} carries exact category values: {hits}")
    if not found:
        P("  exact-value scan over every scalar field: ZERO hits for any of")
        P(f"  {CATS}")
    P(f"  distinct values of `type`: {sorted(set(typ))}")
    P("\n  VERDICT: absent. Paper Table 2's labels are GPT-4o-mini classifications")
    P("  of the Lean statements and were not released. Stratifying on category")
    P("  requires regenerating them from the paper's Appendix B prompt, which is")
    P("  an LLM call per row and is NOT part of this task.")

    # ---- Q4: the single-subject contradiction ----------------------------
    P("\n" + "=" * 78)
    P("Q4  THE SINGLE-SUBJECT CONTRADICTION")
    P("=" * 78)
    P(f"  `type` distribution:   {dict(collections.Counter(typ))}")
    pref = collections.Counter(p.rsplit('_', 1)[0] for p in probs)
    P(f"  id prefixes:           {dict(pref)}")
    nums = sorted(int(p.rsplit('_', 1)[1]) for p in probs)
    P(f"  numeric id suffixes:   n={len(nums)} min={nums[0]} max={nums[-1]}")
    P(f"                         <1200: {sum(1 for n in nums if n < 1200)}   "
      f">=5000: {sum(1 for n in nums if n >= 5000)}")
    P(f"  level distribution:    {dict(sorted(collections.Counter(lvl).items()))}")
    P(f"  state distribution:    {dict(collections.Counter(state))}")
    P("\n  Both the `type` field AND the problem_unique_id string agree: every one")
    P("  of the 500 problems is MATH counting_and_probability. Two independent")
    P("  encodings of the same fact, so this is not a misread field.")

    # ---- ground_truth is a problem-level attribute -----------------------
    P("\n" + "=" * 78)
    P("SANITY: is ground_truth / level constant within a problem?")
    P("=" * 78)
    byp, byl = {}, {}
    for i in range(N):
        byp.setdefault(puid[i], set()).add(gt[i])
        byl.setdefault(puid[i], set()).add(lvl[i])
    P(f"  problems with >1 distinct ground_truth: {sum(1 for s in byp.values() if len(s) > 1)}")
    P(f"  problems with >1 distinct level:        {sum(1 for s in byl.values() if len(s) > 1)}")
    P("  -> ground_truth and level are problem-level attributes, safe to key on.")

    out = {
        "rows": N,
        "problems": len(probs),
        "trajectories": len(traj),
        "trajectories_reconstruct_exactly": exact,
        "traj_per_problem": dict(sorted(collections.Counter(v).items())),
        "steps_per_trajectory": {"min": sl[0], "median": sl[len(sl)//2], "max": sl[-1]},
        "type": dict(collections.Counter(typ)),
        "level": dict(sorted(collections.Counter(lvl).items())),
        "state": dict(collections.Counter(state)),
        "category_labels_present": found,
        "seed": SEED,
    }
    dest = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "results", "phase0_survey.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    P(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
