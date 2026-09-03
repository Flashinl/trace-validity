"""Phase 2 validation: extraction failure rate, and a hand-checkable sample.

Runs the answer-correctness axis over ALL 2,459 FormalStep trajectories and
reports:
  * the extraction failure rate (`answer_unknown`), by method and by level
  * a seeded sample of 20 ground_truth values with the normaliser's output, for
    hand verification
  * a seeded sample of extracted-vs-ground-truth pairs in each verdict bucket

Nothing here reads a Lean verdict; the dataset record never reaches the scorer,
only its step texts do.

Run: HF_HUB_OFFLINE=1 python tests/audit/answer_validate.py
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

from datasets import load_dataset  # noqa: E402

from answer_correctness import (  # noqa: E402
    answer_value, normalize_answer, score_trajectory,
)
from stats import wilson  # noqa: E402

SEED = 20260902
P = print


def build_trajectories(ds):
    puid, prev, gt, lvl = (ds["problem_unique_id"], ds["previous_steps"],
                           ds["ground_truth"], ds["level"])
    traj = collections.OrderedDict()
    for i in range(len(ds)):
        k = (puid[i], tuple(prev[i]))
        if k not in traj:
            traj[k] = {"problem": puid[i], "steps": list(prev[i]),
                       "ground_truth": gt[i], "level": lvl[i]}
    return traj


def ci(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100*k/n:.1f}%  [{100*lo:.1f}-{100*hi:.1f}]"


def main():
    ds = load_dataset("liuchengwu/FormalStep", split="train")
    traj = build_trajectories(ds)
    P("=" * 78)
    P(f"PHASE 2 VALIDATION over all {len(traj)} trajectories")
    P("=" * 78)

    scored = {}
    for k, t in traj.items():
        # Only the step TEXTS and the ground truth cross this boundary.
        scored[k] = score_trajectory(t["steps"], t["ground_truth"])

    verdicts = collections.Counter(s["verdict"] for s in scored.values())
    n = len(scored)
    P(f"\n  verdicts: {dict(verdicts)}")
    for v in ("correct", "incorrect", "answer_unknown"):
        P(f"    {v:<16}{ci(verdicts[v], n)}")

    P(f"\n  EXTRACTION FAILURE RATE (answer_unknown): {ci(verdicts['answer_unknown'], n)}")
    P("  These are a third category. They are NOT folded into `incorrect`.")

    methods = collections.Counter(s["method"] for s in scored.values() if s["method"])
    P(f"\n  extraction method used: {dict(methods.most_common())}")
    backs = collections.Counter(s["steps_back"] for s in scored.values()
                                if s["steps_back"] is not None)
    P(f"  steps back from the end: {dict(sorted(backs.items()))}")

    P("\n  by level:")
    P(f"    {'level':<10}{'n':<7}{'correct':<11}{'incorrect':<11}unknown")
    for lv in ("Level 1", "Level 2", "Level 3", "Level 4", "Level 5"):
        sub = [s for k, s in scored.items() if traj[k]["level"] == lv]
        c = collections.Counter(s["verdict"] for s in sub)
        P(f"    {lv:<10}{len(sub):<7}{c['correct']:<11}{c['incorrect']:<11}"
          f"{c['answer_unknown']}")

    # ---- hand-verification sample: 20 ground_truth values ------------------
    P("\n" + "=" * 78)
    P(f"HAND-VERIFICATION SAMPLE A: 20 ground_truth values, seed {SEED}")
    P("=" * 78)
    P("  Check each row by eye: does `normalized` denote the same answer as `raw`?")
    P(f"  {'#':<4}{'raw':<34}{'normalized':<18}numeric?")
    probs = {}
    for t in traj.values():
        probs[t["problem"]] = t["ground_truth"]
    rng = random.Random(SEED)
    for i, p in enumerate(rng.sample(sorted(probs), 20), 1):
        raw = probs[p]
        P(f"  {i:<4}{raw!r:<34}{str(normalize_answer(raw)):<18}"
          f"{answer_value(raw) is not None}")

    # ---- hand-verification sample: extracted vs ground truth ---------------
    P("\n" + "=" * 78)
    P(f"HAND-VERIFICATION SAMPLE B: 8 per verdict bucket, seed {SEED}")
    P("=" * 78)
    rng = random.Random(SEED)
    for v in ("correct", "incorrect", "answer_unknown"):
        pool = [k for k, s in scored.items() if s["verdict"] == v]
        P(f"\n  --- {v}  (n={len(pool)}) ---")
        for k in rng.sample(pool, min(8, len(pool))):
            s, t = scored[k], traj[k]
            P(f"    gt={t['ground_truth']!r}  extracted={s['extracted']!r}  "
              f"({s['normalized']} vs {s['gt_normalized']})  via {s['method']}")
            P(f"      final step: {t['steps'][-1][:104]!r}")

    out = {
        "seed": SEED,
        "trajectories": n,
        "verdicts": dict(verdicts),
        "extraction_failure_rate": verdicts["answer_unknown"] / n,
        "methods": dict(methods),
    }
    dest = os.path.join(_ROOT, "results", "answer_validation.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    P(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
