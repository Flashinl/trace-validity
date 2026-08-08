#!/usr/bin/env python3
"""trace-validity -- do invalid reasoning traces still reach correct answers?

Goedel-Prover-SFT on FormalStep, scored by Lean 4 + Mathlib.

The two expensive stages are independent on purpose: generation needs a GPU,
verification does not, and a Colab timeout in one must never destroy the other's
work. Each stage resumes from its own .jsonl, so re-running is cheap.

    python3 trace_valid.py --temp 0 --stage generate     # GPU
    python3 trace_valid.py --temp 0 --stage verify       # CPU + Lean
    python3 trace_valid.py --stage analyze --sweep 0 0.2 0.5 0.8 1
    python3 trace_valid.py --temp 0                      # all three
"""

from __future__ import annotations

import argparse
import sys

from src import config as C


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trace_valid.py",
        description=(
            "Study whether invalid chain-of-thought traces still produce correct "
            "answers, using Goedel-Prover-SFT on FormalStep with Lean 4 as the "
            "verifier. Stages are independently runnable and resume from disk."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 trace_valid.py --temp 0 --stage generate     # GPU only\n"
            "  python3 trace_valid.py --temp 0 --stage verify       # CPU + Lean only\n"
            "  python3 trace_valid.py --stage analyze --sweep 0 0.2 0.5 0.8 1\n"
            "  python3 trace_valid.py --temp 0                      # all three\n"
        ),
    )
    p.add_argument(
        "--stage",
        choices=["generate", "verify", "analyze", "all"],
        default="all",
        help="which stage to run (default: all). generate needs a GPU; "
             "verify needs a built Mathlib; analyze needs neither.",
    )
    p.add_argument(
        "--temp",
        type=float,
        default=None,
        help="sampling temperature for generate/verify. At temp 0 decoding is "
             f"greedy, so n_traj is forced to 1 (otherwise {C.N_TRAJ}).",
    )
    p.add_argument(
        "--sweep",
        type=float,
        nargs="+",
        default=None,
        help="temperatures to include in analyze (default: every "
             "results_temp*.json found). Can also be used with generate/verify "
             "to run several temperatures in sequence.",
    )
    p.add_argument(
        "--n-questions",
        type=int,
        default=C.N_QUESTIONS,
        help=f"first N rows of {C.DATASET_NAME}:{C.DATASET_SPLIT} "
             f"(default: {C.N_QUESTIONS})",
    )
    p.add_argument(
        "--n-traj",
        type=int,
        default=C.N_TRAJ,
        help=f"trajectories per question at temperature > 0 "
             f"(default: {C.N_TRAJ}; always 1 at temp 0, which is greedy)",
    )
    p.add_argument(
        "--mathlib-dir",
        default=C.MATHLIB_DIR,
        help=f"path to the built mathlib4 checkout used by verify "
             f"(default: {C.MATHLIB_DIR}; pinned tag {C.MATHLIB_TAG})",
    )
    return p


def temps_for(args, stage: str):
    """Which temperatures this invocation covers."""
    if args.sweep:
        return list(args.sweep)
    if args.temp is not None:
        return [args.temp]
    if stage == "analyze":
        return None  # analyze defaults to everything on disk
    return None


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    stages = ["generate", "verify", "analyze"] if args.stage == "all" else [args.stage]

    for stage in stages:
        temps = temps_for(args, stage)

        if stage in ("generate", "verify") and not temps:
            print(
                f"error: --stage {stage} needs --temp (or --sweep), e.g. "
                f"`--stage {stage} --temp 0`",
                file=sys.stderr,
            )
            return 2

        if stage == "generate":
            from src import generate
            for t in temps:
                generate.run(t, n_questions=args.n_questions, n_traj=args.n_traj)

        elif stage == "verify":
            from src import verify
            for t in temps:
                verify.run(t, mathlib_dir=args.mathlib_dir)

        elif stage == "analyze":
            from src import analysis
            analysis.run(temps)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
