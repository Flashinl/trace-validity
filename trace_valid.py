import argparse
import json
import os
import sys

# Lean statements carry math symbols (ℕ, ℝ, ∑). The Windows console defaults to
# cp1252 and raises UnicodeEncodeError when printing them, which killed the dry
# run before it could render a prompt.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config import (
    RESULTS_DIR,
    NUM_SAMPLES,
    NUM_TRAJECTORIES,
    SAMPLE_STRATEGY,
    PROBLEM_STRIDE,
    STEP_SELECTION,
)
from data_loader import FormalStepDataset
from prompting import build_prompt, extract_lean4_block
from parser import parse_output
from generate import dry_run, run_generation, default_output_path


def run_experiment(temperature, num_samples=NUM_SAMPLES, num_trajectories=NUM_TRAJECTORIES):
    """Full pipeline: generate + verify. Needs a working Lean verifier."""
    from model import GoedelProver
    from verifier import LeanVerifier
    from analysis import compute_stats, print_report, plot_single_temperature

    os.makedirs(RESULTS_DIR, exist_ok=True)

    print(f"Loading dataset ({num_samples} samples)...")
    dataset = FormalStepDataset(num_samples=num_samples)

    print("Loading model...")
    prover = GoedelProver()

    print("Initializing Lean verifier...")
    verifier = LeanVerifier()

    results = []

    for idx in range(len(dataset)):
        sample = dataset[idx]
        prompt = build_prompt(sample)
        print(f"\n[{idx+1}/{len(dataset)}] Processing sample...")

        trajectories = prover.generate(
            prompt,
            temperature=temperature,
            num_trajectories=num_trajectories,
        )

        sample_result = {
            "index": idx,
            "problem": sample["problem"],
            "formal_statement": sample["formal_statement"],
            "reference_proof": sample["reference_proof"],
            "ground_truth": sample["ground_truth"],
            "temperature": temperature,
            "trajectories": [],
        }

        valid_count = 0
        for traj_idx, gen in enumerate(trajectories):
            raw_output = gen["text"]
            full_code = extract_lean4_block(prompt, raw_output)
            parsed = parse_output(raw_output, prompt=None)
            lean_code = full_code if full_code is not None else parsed["code"]

            verification = verifier.verify(lean_code)

            if verification["valid"]:
                valid_count += 1

            sample_result["trajectories"].append({
                "trajectory_index": traj_idx,
                "raw_output": raw_output,
                "parsed_code": lean_code,
                "theorem_name": parsed["theorem_name"],
                "truncated": gen["truncated"],
                "hit_token_limit": gen["hit_token_limit"],
                "has_sorry_literal": parsed["has_sorry_literal"],
                "outcome": verification["outcome"],
                "trace_valid": verification["valid"],
                "errors": verification["errors"],
            })

        best_traj = next(
            (t for t in sample_result["trajectories"] if t["trace_valid"]),
            sample_result["trajectories"][0],
        )

        sample_result["trace_valid"] = best_traj["trace_valid"]
        sample_result["outcome"] = best_traj["outcome"]
        # `answer_correct` REMOVED (audit finding 13).
        #
        # It was `trace_valid and not has_sorry` — derived entirely from
        # trace_valid, so the valid/invalid x correct/incorrect cross-tab it
        # implied was degenerate by construction and `invalid_accuracy` was
        # identically 0.0. A field that is emitted, documented, and named like a
        # measurement will be read as one, so it is deleted rather than renamed.
        #
        # Answer correctness is NOT measured by this pipeline and cannot be:
        # Goedel-Prover emits a Lean proof, not a final answer, and FormalStep's
        # `ground_truth` is the whole problem's answer, identical for every step
        # of that problem. Recovering a real answer axis needs a separate solver
        # producing per-problem answers. Do not re-add a placeholder.
        sample_result["valid_trajectory_count"] = valid_count

        results.append(sample_result)
        print(f"  Valid trajectories: {valid_count}/{num_trajectories}")

    output_path = os.path.join(RESULTS_DIR, f"results_temp_{temperature}.json")
    if os.path.exists(output_path):
        raise FileExistsError(
            f"{output_path} exists; results from real runs are never overwritten."
        )
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")

    stats = compute_stats(results)
    print_report(temperature, stats)
    plot_single_temperature(temperature)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Trace validity checker for CoT reasoning"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- generate (GPU; no Lean) -----------------------------------------
    g = sub.add_parser(
        "generate", help="Generate trajectories to JSONL. No Lean required."
    )
    # nargs="+" makes a temperature sweep a loop over one command rather than a
    # manual re-run per temperature. Each temperature gets its own run dir.
    g.add_argument("--temp", type=float, nargs="+", default=[0.0],
                   help="Sampling temperature(s); more than one runs a sweep")
    g.add_argument("--num-samples", type=int, default=NUM_SAMPLES)
    g.add_argument("--num-trajectories", type=int, default=NUM_TRAJECTORIES)
    g.add_argument("--out", type=str, default=None,
                   help="Output JSONL (default: traces/temp_{T}.jsonl)")
    g.add_argument("--resume", action="store_true",
                   help="Skip (sample, temp, trajectory) tuples already in --out")
    g.add_argument("--dry-run", action="store_true",
                   help="Render prompts and exercise the parser with no model loaded")
    g.add_argument("--show-sample", type=int, default=0,
                   help="Which sample's prompt to print in --dry-run")
    g.add_argument("--traj-batch", type=int, default=1,
                   help="Trajectories per generate() call (>1 is faster, "
                        "but per-trajectory timing becomes a batch average)")
    g.add_argument("--seed", type=int, default=None)
    g.add_argument("--sample-strategy", choices=("distinct_problems", "head"),
                   default=SAMPLE_STRATEGY,
                   help="distinct_problems: one step from each of N different "
                        "problems. head: the first N rows, which are N steps of "
                        "ONE problem (the original behaviour)")
    g.add_argument("--stride", type=int, default=PROBLEM_STRIDE,
                   help="Stride across the ordered problem list")
    g.add_argument("--step-selection", choices=("first", "median"),
                   default=STEP_SELECTION,
                   help="Which CoT step to take from each selected problem")
    g.add_argument("--allow-unseeded", action="store_true",
                   help="Permit sampling (temp>0) with no seed; records seed=null")

    # ---- run (GPU + Lean) -------------------------------------------------
    r = sub.add_parser("run", help="Full pipeline: generate + verify in Lean")
    r.add_argument("--temp", type=float, nargs="+", default=[0.0])
    r.add_argument("--num-samples", type=int, default=NUM_SAMPLES)
    r.add_argument("--num-trajectories", type=int, default=NUM_TRAJECTORIES)

    # ---- analyze (CPU) ----------------------------------------------------
    a = sub.add_parser("analyze", help="Analysis only, on existing results")
    a.add_argument("--temp", type=float, nargs="+", default=[0.0])

    args = parser.parse_args()

    if args.command == "generate":
        if args.dry_run:
            dry_run(
                num_samples=args.num_samples,
                show_sample=args.show_sample,
                temperature=args.temp[0],
                num_trajectories=args.num_trajectories,
                strategy=args.sample_strategy,
                stride=args.stride,
                step_selection=args.step_selection,
            )
            return

        if args.out and len(args.temp) > 1:
            parser.error("--out names a single file; drop it for a sweep so each "
                         "temperature gets its own run directory")

        for temp in args.temp:
            out = args.out or default_output_path(
                temp, args.num_samples, args.num_trajectories
            )
            if len(args.temp) > 1:
                print(f"\n{'#'*60}\n  temperature = {temp}\n{'#'*60}")
            run_generation(
                temperature=temp,
                output_path=out,
                num_samples=args.num_samples,
                num_trajectories=args.num_trajectories,
                resume=args.resume,
                traj_batch=args.traj_batch,
                seed=args.seed,
                strategy=args.sample_strategy,
                stride=args.stride,
                step_selection=args.step_selection,
                allow_unseeded=args.allow_unseeded,
            )
        return

    if args.command == "analyze":
        from analysis import plot_single_temperature, plot_temperature_sweep

        if len(args.temp) == 1:
            plot_single_temperature(args.temp[0])
        else:
            plot_temperature_sweep()
        return

    if args.command == "run":
        from analysis import plot_temperature_sweep

        for temp in args.temp:
            print(f"\n{'#'*60}")
            print(f"  Running experiment with temperature = {temp}")
            print(f"{'#'*60}")
            run_experiment(
                temp,
                num_samples=args.num_samples,
                num_trajectories=args.num_trajectories,
            )
        if len(args.temp) > 1:
            print("\nGenerating temperature sweep analysis...")
            plot_temperature_sweep()


if __name__ == "__main__":
    main()
