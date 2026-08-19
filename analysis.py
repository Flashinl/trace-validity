import json
import os
import glob

import matplotlib.pyplot as plt

from config import RESULTS_DIR
from stats import pct, rate


def load_results(temperature):
    path = os.path.join(RESULTS_DIR, f"results_temp_{temperature}.json")
    with open(path) as f:
        return json.load(f)


def compute_stats(results):
    """Outcome counts for a `trace_valid.py run` result file.

    ISSUE #5, RESOLVED. This function used to report `valid_accuracy`,
    `invalid_accuracy` and `overall_accuracy` off an `answer_correct` field that
    `trace_valid.py` defined as `trace_valid and not has_sorry`. Because
    answer_correct was DERIVED FROM trace_valid, every row in `invalid_traces`
    had answer_correct == False by construction, `invalid_accuracy` was
    identically 0.0, and the 2x2 contingency between "is the trace a valid
    proof" and "is the answer right" collapsed to a tautology.

    The field is now deleted at source rather than reinterpreted here, so the
    fake accuracy axis is gone with it. Answer correctness is NOT measured by
    this pipeline -- see the note in trace_valid.py. What remains below is the
    only thing this file ever legitimately measured: how many traces were valid.

    Prefer `analyze_runs.py`, which reports the full outcome taxonomy and is the
    authoritative entry point.
    """
    from collections import Counter

    valid_traces = [r for r in results if r["trace_valid"]]
    counts = Counter(r.get("outcome", "unknown") for r in results)

    return {
        "total": len(results),
        "valid_count": len(valid_traces),
        "invalid_count": len(results) - len(valid_traces),
        "validity_rate": len(valid_traces) / len(results) if results else 0.0,
        "outcome_counts": dict(counts),
        # Deliberately absent: valid_accuracy / invalid_accuracy /
        # overall_accuracy. There is no answer axis to compute them from.
        "answer_axis": None,
    }


def load_verification(path):
    """Load a verification JSONL produced by verify_traces.py."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def outcome_distribution(rows):
    """Distinct outcomes, never collapsed into a single boolean (issue #5)."""
    from collections import Counter

    counts = Counter(r["outcome"] for r in rows)
    total = len(rows)
    return {
        "total": total,
        "counts": dict(counts),
        "fractions": {k: v / total for k, v in counts.items()} if total else {},
    }


def print_outcome_report(path):
    rows = load_verification(path)
    dist = outcome_distribution(rows)
    print(f"\n{'='*60}")
    print(f"  Outcome distribution — {os.path.basename(path)}")
    print(f"{'='*60}")
    print(f"  total verified: {dist['total']}")
    for outcome, n in sorted(dist["counts"].items(), key=lambda kv: -kv[1]):
        print(f"    {outcome:<16} {n:>4}  ({pct(dist['fractions'][outcome])})")

    secs = [r["seconds"] for r in rows if "seconds" in r]
    if secs:
        print(f"\n  per-verification seconds: min {min(secs):.2f} "
              f"mean {sum(secs)/len(secs):.2f} max {max(secs):.2f}")
    print(f"{'='*60}\n")
    return dist


def print_report(temperature, stats):
    print(f"\n{'='*60}")
    print(f"  Temperature = {temperature}")
    print(f"{'='*60}")
    print(f"  Total samples:    {stats['total']}")
    print(f"  Valid traces:     {stats['valid_count']}  |  Invalid traces: {stats['invalid_count']}")
    print(f"  Validity rate:    {rate(stats['valid_count'], stats['total'])}")
    if stats["outcome_counts"]:
        print("  Outcomes:")
        for outcome, n in sorted(stats["outcome_counts"].items(), key=lambda kv: -kv[1]):
            print(f"    {outcome:<18} {n:>4}")
    print("  Answer correctness: NOT MEASURED — this pipeline has no answer axis.")
    print(f"{'='*60}\n")


def plot_single_temperature(temperature):
    results = load_results(temperature)
    stats = compute_stats(results)
    print_report(temperature, stats)

    # Was a validity x answer-correctness 2x2. That chart was a picture of a
    # tautology — answer_correct was derived from trace_valid, so two of its four
    # bars were structurally zero. Plot the real outcome distribution instead.
    counts = stats["outcome_counts"]
    labels = list(counts)
    values = [counts[k] for k in labels]
    palette = {"valid": "#2ecc71", "compile_error": "#e74c3c",
               "statement_error": "#95a5a6", "statement_mismatch": "#8e44ad",
               "unsound_axioms": "#c0392b", "has_sorry": "#e67e22"}
    colors = [palette.get(k, "#3498db") for k in labels]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(labels, values, color=colors)
    ax.set_ylabel("Count")
    ax.set_title(f"Verification outcome distribution (temp={temperature})")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_DIR, f"analysis_temp_{temperature}.png"), dpi=150)
    plt.close()


def plot_temperature_sweep():
    result_files = sorted(glob.glob(os.path.join(RESULTS_DIR, "results_temp_*.json")))
    if not result_files:
        print("No result files found.")
        return

    temps = []
    validity_rates = []

    for path in result_files:
        fname = os.path.basename(path)
        temp = float(fname.replace("results_temp_", "").replace(".json", ""))
        with open(path) as f:
            results = json.load(f)
        stats = compute_stats(results)
        print_report(temp, stats)

        temps.append(temp)
        validity_rates.append(stats["validity_rate"])

    fig, ax = plt.subplots(figsize=(10, 6))
    # The three "accuracy" series this used to plot were all functions of
    # trace_valid, so the chart showed one signal drawn three times. One line.
    ax.plot(temps, validity_rates, "o-", label="Validity rate", linewidth=2)
    ax.set_xlabel("Temperature")
    ax.set_ylabel("Validity rate")
    ax.set_title("Trace validity vs temperature (answer correctness not measured)")
    ax.legend()
    ax.set_xticks(temps)
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_DIR, "temperature_sweep.png"), dpi=150)
    plt.close()
    print(f"Saved sweep plot to {os.path.join(RESULTS_DIR, 'temperature_sweep.png')}")


if __name__ == "__main__":
    plot_temperature_sweep()
