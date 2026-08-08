"""Stage 3 (CPU, seconds): aggregate the verified results.

Reads every results/results_temp*.json that exists, so it works on a partial
sweep. Produces results/summary.csv, results/crosstab.csv, and two figures.
"""

from __future__ import annotations

import glob
import os
from typing import Any, Dict, List, Optional

from . import config as C

SUMMARY_CSV = "summary.csv"
CROSSTAB_CSV = "crosstab.csv"
SWEEP_PNG = "temp_sweep.png"
CROSSTAB_PNG = "crosstab.png"


def _rate(num: int, den: int) -> float:
    return float("nan") if den == 0 else num / den


def load_frame(temps: Optional[List[float]] = None):
    """One row per trajectory, across every temperature on disk."""
    import pandas as pd

    if temps is None:
        paths = sorted(glob.glob(os.path.join(C.RESULTS_DIR, "results_temp*.json")))
    else:
        paths = [C.results_json_path(t) for t in temps]
        paths = [p for p in paths if os.path.exists(p)]

    if not paths:
        raise FileNotFoundError(
            f"no results_temp*.json in {C.RESULTS_DIR} -- run `--stage verify` first"
        )

    rows: List[Dict[str, Any]] = []
    for path in paths:
        payload = C.read_json(path)
        temp = float(payload["temperature"])
        for q in payload["questions"]:
            for t in q["trajectories"]:
                rows.append(
                    {
                        "temperature": temp,
                        "greedy": bool(payload.get("greedy", temp == 0.0)),
                        "n_traj": payload.get("n_traj"),
                        "mathlib_tag": payload.get("mathlib_tag", C.MATHLIB_TAG),
                        "idx": q["idx"],
                        "traj_idx": t["traj_idx"],
                        "trace_valid": bool(t["trace_valid"]),
                        "end_correct": bool(t["end_correct"]),
                        "syntax_err": bool(t["syntax_err"]),
                        "unknown_err": bool(t["unknown_err"]),
                        "unsolved_goals": bool(t["unsolved_goals"]),
                        "n_errors": int(t["n_errors"]),
                    }
                )
    df = pd.DataFrame(rows)
    print(f"[analyze] loaded {len(df)} trajectories from {len(paths)} file(s): "
          f"{', '.join(os.path.basename(p) for p in paths)}")
    return df


def summarize(df) -> "Any":
    """One row per temperature."""
    import pandas as pd

    out = []
    for temp, g in df.groupby("temperature"):
        valid = g[g.trace_valid]
        invalid = g[~g.trace_valid]
        out.append(
            {
                "temperature": temp,
                "greedy": bool(g.greedy.iloc[0]),
                "n_questions": g.idx.nunique(),
                "n_traj_per_q": int(g.n_traj.iloc[0]) if g.n_traj.notna().all() else None,
                "n_trajectories": len(g),
                "trace_validity": _rate(int(g.trace_valid.sum()), len(g)),
                "accuracy": _rate(int(g.end_correct.sum()), len(g)),
                "acc_given_valid": _rate(int(valid.end_correct.sum()), len(valid)),
                "acc_given_invalid": _rate(int(invalid.end_correct.sum()), len(invalid)),
                "syntax_err_rate": _rate(int(g.syntax_err.sum()), len(g)),
                "unknown_err_rate": _rate(int(g.unknown_err.sum()), len(g)),
                "unsolved_goals_rate": _rate(int(g.unsolved_goals.sum()), len(g)),
                "mean_n_errors": g.n_errors.mean(),
                "mathlib_tag": g.mathlib_tag.iloc[0],
            }
        )
    return pd.DataFrame(out).sort_values("temperature").reset_index(drop=True)


def crosstab(df):
    """The 2x2: trace_valid x end_correct, pooled over temperatures."""
    import pandas as pd

    ct = pd.crosstab(df.trace_valid, df.end_correct, dropna=False)
    # Force all four cells to exist even when one is empty, which is the whole
    # point of looking at this table (see README: the invalid/correct cell is
    # empty by construction under formal verification).
    ct = ct.reindex(index=[False, True], columns=[False, True], fill_value=0)
    ct.index.name = "trace_valid"
    ct.columns.name = "end_correct"
    return ct


def plot_sweep(summary, path: str) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(summary.temperature, summary.trace_validity, marker="o",
            label="trace validity")
    ax.plot(summary.temperature, summary.accuracy, marker="s", label="accuracy")
    ax.set_xlabel("temperature")
    ax.set_ylabel("rate")
    ax.set_ylim(-0.02, 1.02)
    ax.set_title("Trace validity and accuracy vs temperature")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[analyze] wrote {path}")
    return path


def plot_crosstab(ct, path: str) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 2.8))
    ax.axis("off")
    # Built as a plain 3x3 grid rather than with rowLabels=/colLabels=, which
    # size the label column to the data column and clip the long names.
    cells = [["", "end_correct=False", "end_correct=True"]]
    for i in [False, True]:
        cells.append([f"trace_valid={i}"] + [str(ct.loc[i, c]) for c in [False, True]])
    table = ax.table(
        cellText=cells,
        cellLoc="center",
        colWidths=[0.34, 0.33, 0.33],
        bbox=[0.02, 0.05, 0.96, 0.74],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    ax.set_title("trace_valid x end_correct (all temperatures)", fontsize=11, pad=12)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[analyze] wrote {path}")
    return path


def run(temps: Optional[List[float]] = None) -> Dict[str, str]:
    C.ensure_dirs()
    df = load_frame(temps)
    summary = summarize(df)
    ct = crosstab(df)

    summary_path = os.path.join(C.RESULTS_DIR, SUMMARY_CSV)
    crosstab_path = os.path.join(C.RESULTS_DIR, CROSSTAB_CSV)
    summary.to_csv(summary_path, index=False)
    ct.to_csv(crosstab_path)

    print("\n=== summary (results/summary.csv) ===")
    print(summary.to_string(index=False))
    print("\n=== 2x2: trace_valid x end_correct ===")
    print(ct.to_string())
    if int(ct.loc[False, True]) == 0:
        print(
            "\nNote: the (trace_valid=False, end_correct=True) cell is 0. Under a\n"
            "formal verifier end_correct implies trace_valid, so this cell is empty\n"
            "by construction, not by measurement -- a design question about the\n"
            "study, not a bug. See README, 'Two things worth calling out'."
        )

    sweep_path = plot_sweep(summary, os.path.join(C.FIGS_DIR, SWEEP_PNG))
    ct_path = plot_crosstab(ct, os.path.join(C.FIGS_DIR, CROSSTAB_PNG))

    return {
        "summary": summary_path,
        "crosstab": crosstab_path,
        "sweep_fig": sweep_path,
        "crosstab_fig": ct_path,
    }
