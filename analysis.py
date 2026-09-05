import json
import os
import glob
import re
from fractions import Fraction

import matplotlib.pyplot as plt

from config import RESULTS_DIR


def load_results(temperature):
    path = os.path.join(RESULTS_DIR, f"results_temp_{temperature}.json")
    with open(path) as f:
        return json.load(f)


def parse_number(s):
    """Convert a string to a float, handling commas and simple fractions."""
    if not s:
        return None
    s = s.strip().replace(",", "")
    try:
        if "/" in s:
            return float(Fraction(s))
        return float(s)
    except (ValueError, ZeroDivisionError):
        return None


def extract_number(text):
    """Extract a numerical answer from text using a priority-based search."""
    if not text:
        return None

    # Priority 1: \boxed{...}
    boxed = re.search(r"\\boxed\{([^{}]*)\}", text)
    if boxed:
        content = boxed.group(1)
        # Handle \frac{a}{b}
        frac = re.search(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", content)
        if frac:
            num = parse_number(frac.group(1))
            den = parse_number(frac.group(2))
            if num is not None and den is not None and den != 0:
                return num / den
        val = parse_number(content)
        if val is not None:
            return val

    # Priority 2: Keywords
    keywords = [
        r"the answer is\s*([-0-9./]+)",
        r"final answer\s*[:=]?\s*([-0-9./]+)",
        r"answer is\s*([-0-9./]+)",
    ]
    for pattern in keywords:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = parse_number(match.group(1))
            if val is not None:
                return val

    # Priority 3: Last number in text
    all_nums = re.findall(r"[-0-9./]+", text)
    if all_nums:
        val = parse_number(all_nums[-1])
        if val is not None:
            return val

    return None



def compute_stats(results):
    valid_traces = [r for r in results if r["trace_valid"]]
    invalid_traces = [r for r in results if not r["trace_valid"]]

    valid_correct = sum(1 for r in valid_traces if r["answer_correct"])
    invalid_correct = sum(1 for r in invalid_traces if r["answer_correct"])

    # Numerical Correctness
    num_correct = 0
    valid_num_correct = 0
    invalid_num_correct = 0

    for r in results:
        gt_val = extract_number(r.get("ground_truth", ""))

        # Find best trajectory for numerical answer
        best_traj = None
        if r["trajectories"]:
            # Prefer valid traces, then just the first one
            valid_trajs = [t for t in r["trajectories"] if t["trace_valid"]]
            best_traj = valid_trajs[0] if valid_trajs else r["trajectories"][0]

        if best_traj and gt_val is not None:
            model_val = extract_number(best_traj.get("raw_output", ""))
            if model_val is not None and abs(model_val - gt_val) < 1e-6:
                num_correct += 1
                if r["trace_valid"]:
                    valid_num_correct += 1
                else:
                    invalid_num_correct += 1

    return {
        "total": len(results),
        "valid_count": len(valid_traces),
        "invalid_count": len(invalid_traces),
        "valid_accuracy": valid_correct / len(valid_traces) if valid_traces else 0.0,
        "invalid_accuracy": invalid_correct / len(invalid_traces) if invalid_traces else 0.0,
        "overall_accuracy": (valid_correct + invalid_correct) / len(results) if results else 0.0,
        "numerical_accuracy": num_correct / len(results) if results else 0.0,
        "valid_num_accuracy": valid_num_correct / len(valid_traces) if valid_traces else 0.0,
        "invalid_num_accuracy": invalid_num_correct / len(invalid_traces) if invalid_traces else 0.0,
        "num_correct": num_correct,
        "valid_num_correct": valid_num_correct,
        "invalid_num_correct": invalid_num_correct,
        "valid_correct": valid_correct,
        "valid_incorrect": len(valid_traces) - valid_correct,
        "invalid_correct": invalid_correct,
        "invalid_incorrect": len(invalid_traces) - invalid_correct,
    }


def print_report(temperature, stats):
    print(f"\n{'='*60}")
    print(f"  Temperature = {temperature}")
    print(f"{'='*60}")
    print(f"  Total samples:    {stats['total']}")
    print(f"  Valid traces:     {stats['valid_count']}  |  Invalid traces: {stats['invalid_count']}")
    print(f"  Overall accuracy: {stats['overall_accuracy']:.2%}")
    print(f"  Numerical accuracy: {stats['numerical_accuracy']:.2%} ({stats['num_correct']}/{stats['total']})")
    print(f"    - Valid traces:   {stats['valid_num_accuracy']:.2%} ({stats['valid_num_correct']}/{stats['valid_count']})")
    print(f"    - Invalid traces: {stats['invalid_num_accuracy']:.2%} ({stats['invalid_num_correct']}/{stats['invalid_count']})")
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

    # Add numerical accuracy as a text box
    textstr = f"Numerical Accuracy: {stats['numerical_accuracy']:.2%}"
    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
    ax.text(0.05, 0.95, textstr, transform=ax.transAxes, fontsize=12,
            verticalalignment='top', bbox=props)

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
    num_accs = []

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
        num_accs.append(stats["numerical_accuracy"])

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(temps, valid_accs, "o-", label="Valid Trace Accuracy", linewidth=2)
    ax.plot(temps, invalid_accs, "s-", label="Invalid Trace Accuracy", linewidth=2)
    ax.plot(temps, overall_accs, "^--", label="Overall Accuracy", linewidth=2, alpha=0.6)
    ax.plot(temps, num_accs, "d-", label="Numerical Accuracy", linewidth=2, color="purple")
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
