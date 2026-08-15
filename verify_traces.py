"""Verify trace validity for pre-generated Goedel-Prover outputs.

Reads a JSONL file where each line is one trajectory record (with fields like
`sample_index`, `temperature`, `trajectory_index`, `raw_output`, `parsed_code`,
`full_code`, ...) and writes a results JSON in the same shape as
`trace_valid.run_experiment()` produces, so `analysis.py` and the
`--analyze-only` flag work without modification.

Usage:
    python3 verify_traces.py --input traces.jsonl --temp 0
    python3 verify_traces.py --input traces.jsonl --temp 0 0.5 1.0
"""

import argparse
import json
import os
from collections import defaultdict

from config import RESULTS_DIR
from parser import parse_output
from verifier import LeanVerifier


def load_traces(path):
    """Read a JSONL file and return a list of dicts."""
    records = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[warn] skipping line {lineno}: invalid JSON ({e})")
    return records


def group_by_sample(records, temperature):
    """Group records for a given temperature by sample_index, preserving order.

    Returns an ordered dict: {sample_index: [record, ...]} sorted by
    sample_index, with each list sorted by trajectory_index.
    """
    bucket = defaultdict(list)
    for r in records:
        if r.get("temperature") != temperature:
            continue
        bucket[r.get("sample_index", 0)].append(r)

    grouped = {}
    for idx in sorted(bucket):
        grouped[idx] = sorted(bucket[idx], key=lambda x: x.get("trajectory_index", 0))
    return grouped


def code_for_record(record, prompt):
    """Pick the best Lean code we have for this trajectory.

    Priority: `parsed_code` if it looks like valid Lean (contains a theorem/
    lemma/example declaration), else parse `raw_output` from scratch, else
    fall back to `full_code`.
    """
    parsed_code = record.get("parsed_code")
    if parsed_code and ("theorem" in parsed_code or "lemma" in parsed_code or "example" in parsed_code):
        return parsed_code, record.get("theorem_name"), record.get("truncated", False), record.get("has_sorry", False)

    raw = record.get("raw_output", "")
    if raw:
        parsed = parse_output(raw, prompt=prompt)
        return (
            parsed["code"],
            parsed["theorem_name"],
            parsed["truncated"],
            parsed["has_sorry"],
        )

    full = record.get("full_code", "")
    if full:
        return full, record.get("theorem_name"), record.get("truncated", False), record.get("has_sorry", False)

    return "", None, False, False


def run_for_temperature(records, temperature, verifier):
    grouped = group_by_sample(records, temperature)

    if not grouped:
        print(f"No records found for temperature={temperature}")
        return []

    results = []
    for sample_idx in sorted(grouped):
        trajs = grouped[sample_idx]
        first = trajs[0]
        prompt = first.get("prompt", "")
        problem = first.get("formal_statement") or first.get("problem") or ""
        ground_truth = first.get("reference_proof") or first.get("ground_truth") or ""

        print(f"\n[sample {sample_idx}] {len(trajs)} trajectories")

        sample_result = {
            "index": sample_idx,
            "problem": problem,
            "ground_truth": ground_truth,
            "temperature": temperature,
            "trajectories": [],
        }

        valid_count = 0
        for record in trajs:
            lean_code, thm_name, truncated, has_sorry_meta = code_for_record(record, prompt)

            verification = verifier.verify(lean_code) if lean_code else {"valid": False, "errors": ["empty code"], "num_errors": 1}

            if verification["valid"]:
                valid_count += 1

            sample_result["trajectories"].append({
                "trajectory_index": record.get("trajectory_index"),
                "raw_output": record.get("raw_output", ""),
                "parsed_code": lean_code,
                "theorem_name": thm_name,
                "truncated": truncated,
                "has_sorry": has_sorry_meta,
                "trace_valid": verification["valid"],
                "errors": verification["errors"],
            })

        best_traj = next(
            (t for t in sample_result["trajectories"] if t["trace_valid"]),
            sample_result["trajectories"][0] if sample_result["trajectories"] else None,
        )

        sample_result["trace_valid"] = bool(best_traj and best_traj["trace_valid"])
        sample_result["answer_correct"] = bool(best_traj and best_traj["trace_valid"] and not best_traj["has_sorry"])
        sample_result["valid_trajectory_count"] = valid_count

        results.append(sample_result)
        print(f"  Valid trajectories: {valid_count}/{len(trajs)}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Verify trace validity from a pre-generated JSONL of trajectories")
    parser.add_argument("--input", "-i", required=True, help="Path to JSONL file of trajectories")
    parser.add_argument("--temp", type=float, nargs="+", required=True,
                        help="Temperature(s) to verify, e.g. --temp 0 0.5 1.0")
    parser.add_argument("--out-prefix", default=None,
                        help="Output filename prefix (default: 'results'). Writes results_<prefix>_temp_<T>.json")
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    print(f"Loading traces from {args.input}...")
    records = load_traces(args.input)
    print(f"  Loaded {len(records)} records")

    print("Initializing Lean verifier...")
    verifier = LeanVerifier()

    prefix = args.out_prefix or "results"
    saved_paths = []
    for temp in args.temp:
        print(f"\n{'#'*60}\n  Verifying temperature = {temp}\n{'#'*60}")
        results = run_for_temperature(records, temp, verifier)
        if not results:
            continue

        out_path = os.path.join(RESULTS_DIR, f"{prefix}_temp_{temp}.json")
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        saved_paths.append(out_path)
        print(f"\nSaved {len(results)} samples to {out_path}")

    if saved_paths:
        print("\nFiles written:")
        for p in saved_paths:
            print(f"  {p}")
        print("\nYou can now run analysis with:")
        print(f"  python3 trace_valid.py --analyze-only --temp {' '.join(str(t) for t in args.temp)}")


if __name__ == "__main__":
    main()
