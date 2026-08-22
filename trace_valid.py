import argparse
import json
import os
import sys

from config import RESULTS_DIR, NUM_SAMPLES, NUM_TRAJECTORIES
from data_loader import FormalStepDataset
from model import GoedelProver
from parser import parse_output
from verifier import LeanVerifier
from analysis import compute_stats, print_report, plot_single_temperature, plot_temperature_sweep


def run_experiment(temperature, num_samples=NUM_SAMPLES, num_trajectories=NUM_TRAJECTORIES):
    os.makedirs(RESULTS_DIR, exist_ok=True)

    print(f"Loading dataset ({num_samples} samples)...")
    dataset = FormalStepDataset(num_samples=num_samples)

    print("Loading model...")
    prover = GoedelProver()

    print("Initializing Lean verifier...")
    verifier = LeanVerifier()

    results = []

    for idx in range(len(dataset)):
        problem, ground_truth = dataset[idx]
        print(f"\n[{idx+1}/{len(dataset)}] Processing sample...")

        trajectories = prover.generate(
            problem,
            temperature=temperature,
            num_trajectories=num_trajectories,
        )

        sample_result = {
            "index": idx,
            "problem": problem,
            "ground_truth": ground_truth,
            "temperature": temperature,
            "trajectories": [],
        }

        valid_count = 0
        for traj_idx, raw_output in enumerate(trajectories):
            parsed = parse_output(raw_output, prompt=problem)
            lean_code = parsed["code"]

            verification = verifier.verify(lean_code)

            if verification["valid"]:
                valid_count += 1
                print(f"    traj {traj_idx}: VALID")
            else:
                first_err = verification["errors"][0] if verification["errors"] else "unknown error"
                # Truncate to keep console output scannable.
                if len(first_err) > 120:
                    first_err = first_err[:117] + "..."
                print(f"    traj {traj_idx}: INVALID — {first_err}")

            sample_result["trajectories"].append({
                "trajectory_index": traj_idx,
                "raw_output": raw_output,
                "parsed_code": lean_code,
                "theorem_name": parsed["theorem_name"],
                "truncated": parsed["truncated"],
                "has_sorry": parsed["has_sorry"],
                "trace_valid": verification["valid"],
                "errors": verification["errors"],
            })

        best_traj = next(
            (t for t in sample_result["trajectories"] if t["trace_valid"]),
            sample_result["trajectories"][0],
        )

        sample_result["trace_valid"] = best_traj["trace_valid"]
        sample_result["answer_correct"] = best_traj["trace_valid"] and not best_traj["has_sorry"]
        sample_result["valid_trajectory_count"] = valid_count

        results.append(sample_result)
        print(f"  Valid trajectories: {valid_count}/{num_trajectories}")

    output_path = os.path.join(RESULTS_DIR, f"results_temp_{temperature}.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")

    stats = compute_stats(results)
    print_report(temperature, stats)
    plot_single_temperature(temperature)

    return results


def main():
    parser = argparse.ArgumentParser(description="Trace validity checker for CoT reasoning")
    parser.add_argument("--temp", type=float, nargs="+", default=[0.0],
                        help="Temperature(s) for generation. E.g. --temp 0 0.2 0.5 0.8 1")
    parser.add_argument("--num-samples", type=int, default=NUM_SAMPLES,
                        help=f"Number of dataset samples (default: {NUM_SAMPLES})")
    parser.add_argument("--num-trajectories", type=int, default=NUM_TRAJECTORIES,
                        help=f"Trajectories per sample (default: {NUM_TRAJECTORIES})")
    parser.add_argument("--analyze-only", action="store_true",
                        help="Skip inference, only run analysis on existing results")
    args = parser.parse_args()

    if args.analyze_only:
        if len(args.temp) == 1:
            plot_single_temperature(args.temp[0])
        else:
            plot_temperature_sweep()
        return

    for temp in args.temp:
        print(f"\n{'#'*60}")
        print(f"  Running experiment with temperature = {temp}")
        print(f"{'#'*60}")
        run_experiment(temp, num_samples=args.num_samples, num_trajectories=args.num_trajectories)

    if len(args.temp) > 1:
        print("\nGenerating temperature sweep analysis...")
        plot_temperature_sweep()


if __name__ == "__main__":
    main()
