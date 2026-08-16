import json
import os
import glob

import matplotlib.pyplot as plt

from config import RESULTS_DIR


def load_results(temperature):
    path = os.path.join(RESULTS_DIR, f"results_temp_{temperature}.json")
    with open(path) as f:
        return json.load(f)


def compute_stats(results):
    valid_traces = [r for r in results if r["trace_valid"]]
    invalid_traces = [r for r in results if not r["trace_valid"]]

    valid_correct = sum(1 for r in valid_traces if r["answer_correct"])
    invalid_correct = sum(1 for r in invalid_traces if r["answer_correct"])

    # ISSUE #5 — `invalid_accuracy` below is DEGENERATE, always exactly 0.0.
    #
    #   trace_valid.py:  answer_correct = trace_valid and not has_sorry
    #   here:            invalid_traces = [r for r in results if not r["trace_valid"]]
    #                    invalid_correct = sum(... if r["answer_correct"])
    #
    # Every row in `invalid_traces` has trace_valid == False, so its
    # answer_correct is `False and ...` == False. invalid_correct is therefore
    # identically 0 and invalid_accuracy is identically 0.0 — it measures
    # nothing. The 2x2 contingency between "is the trace a valid proof" and "is
    # the answer right" collapses because answer_correct is DERIVED FROM
    # trace_valid instead of being an independent signal.
    #
    # Not silently redefined here: the corrected definition is proposed in the
    # PR body for review. See `outcome_distribution` below for reporting that
    # does not depend on this metric.
    assert invalid_correct == 0 or not invalid_traces, (
        "invalid_correct became non-zero — answer_correct is no longer derived "
        "from trace_valid, so the issue #5 note above needs updating."
    )

    return {
        "total": len(results),
        "valid_count": len(valid_traces),
        "invalid_count": len(invalid_traces),
        "valid_accuracy": valid_correct / len(valid_traces) if valid_traces else 0.0,
        "invalid_accuracy": invalid_correct / len(invalid_traces) if invalid_traces else 0.0,
        "overall_accuracy": (valid_correct + invalid_correct) / len(results) if results else 0.0,
        "valid_correct": valid_correct,
        "valid_incorrect": len(valid_traces) - valid_correct,
        "invalid_correct": invalid_correct,
        "invalid_incorrect": len(invalid_traces) - invalid_correct,
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
        print(f"    {outcome:<16} {n:>4}  ({dist['fractions'][outcome]:.1%})")

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
    print(f"  Overall accuracy: {stats['overall_accuracy']:.2%}")
    print(f"  Valid trace accuracy:   {stats['valid_accuracy']:.2%}  ({stats['valid_correct']}/{stats['valid_count']})")
    print(f"  Invalid trace accuracy: {stats['invalid_accuracy']:.2%}  ({stats['invalid_correct']}/{stats['invalid_count']})")
    print(f"{'='*60}\n")


def plot_single_temperature(temperature):
    results = load_results(temperature)
    stats = compute_stats(results)
    print_report(temperature, stats)

    labels = ["Valid\nCorrect", "Valid\nIncorrect", "Invalid\nCorrect", "Invalid\nIncorrect"]
    values = [stats["valid_correct"], stats["valid_incorrect"],
              stats["invalid_correct"], stats["invalid_incorrect"]]
    colors = ["#2ecc71", "#e74c3c", "#3498db", "#e67e22"]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(labels, values, color=colors)
    ax.set_ylabel("Count")
    ax.set_title(f"Trace Validity vs Answer Correctness (temp={temperature})")
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_DIR, f"analysis_temp_{temperature}.png"), dpi=150)
    plt.close()


def plot_temperature_sweep():
    result_files = sorted(glob.glob(os.path.join(RESULTS_DIR, "results_temp_*.json")))
    if not result_files:
        print("No result files found.")
        return

    temps = []
    valid_accs = []
    invalid_accs = []
    overall_accs = []

    for path in result_files:
        fname = os.path.basename(path)
        temp = float(fname.replace("results_temp_", "").replace(".json", ""))
        with open(path) as f:
            results = json.load(f)
        stats = compute_stats(results)
        print_report(temp, stats)

        temps.append(temp)
        valid_accs.append(stats["valid_accuracy"])
        invalid_accs.append(stats["invalid_accuracy"])
        overall_accs.append(stats["overall_accuracy"])

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(temps, valid_accs, "o-", label="Valid Trace Accuracy", linewidth=2)
    ax.plot(temps, invalid_accs, "s-", label="Invalid Trace Accuracy", linewidth=2)
    ax.plot(temps, overall_accs, "^--", label="Overall Accuracy", linewidth=2, alpha=0.6)
    ax.set_xlabel("Temperature")
    ax.set_ylabel("Accuracy")
    ax.set_title("Trace Validity & Accuracy vs Temperature")
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
