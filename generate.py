"""Generation driver: FormalStep -> Goedel-Prover prompt -> trajectories on disk.

Generation is deliberately separate from verification (Lean needs no GPU).
Every trajectory is appended to JSONL the moment it is produced, so an
interrupted run loses nothing.
"""

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

from config import (
    MODEL_NAME,
    NUM_SAMPLES,
    NUM_TRAJECTORIES,
    TRACES_DIR,
    MODEL_MAX_CONTEXT,
    MAX_NEW_TOKENS,
    TOP_P,
    DATASET_NAME,
    DATASET_SPLIT,
    SAMPLE_STRATEGY,
    PROBLEM_STRIDE,
    STEP_SELECTION,
)

META_FILENAME = "run_meta.json"
META_SCHEMA_VERSION = 1
from data_loader import FormalStepDataset
from prompting import build_prompt, extract_lean4_block
from parser import parse_output


# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------
# A run whose configuration is not written down is a run that cannot be cited.
# traces/temp_0.jsonl has no seed, no top_p, no git SHA and no dataset revision
# recorded anywhere, so its provenance had to be reconstructed by reading the
# records. Every run now writes run_meta.json beside its JSONL — once at start
# (status "running") so an interrupted run still leaves its config on disk, and
# again at the end with the realised counts and the output hash.

def _git(*args):
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


CODE_VERSION_FILE = "CODE_VERSION"


def git_state():
    """Commit the code was run from, and whether the tree was dirty.

    The generation host runs from an uploaded archive with no .git, so `git`
    returns nothing there and the first A10 run recorded sha=null — the exact
    provenance hole run_meta.json exists to close. Deploy writes a CODE_VERSION
    file next to the source; it is read when git is unavailable. `source` says
    which of the two answered, so a recorded SHA is never mistaken for a live
    repository check.
    """
    sha = _git("rev-parse", "HEAD")
    if sha:
        status = _git("status", "--porcelain")
        return {
            "source": "git",
            "sha": sha,
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            # None means "could not determine", which is not "clean".
            "dirty": None if status is None else bool(status.strip()),
        }

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        CODE_VERSION_FILE)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            recorded = json.load(f)
        return dict(recorded, source="code_version_file")

    return {"source": None, "sha": None, "branch": None, "dirty": None}


def environment_state():
    env = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    for mod in ("torch", "transformers", "datasets"):
        try:
            env[mod] = __import__(mod).__version__
        except Exception:  # noqa: BLE001 - a missing version is recorded as such
            env[mod] = None
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            env["gpu"] = torch.cuda.get_device_name(0)
            env["gpu_total_gib"] = round(total / 1024 ** 3, 2)
            env["gpu_free_gib_at_start"] = round(free / 1024 ** 3, 2)
        else:
            env["gpu"] = None
    except Exception:  # noqa: BLE001
        env["gpu"] = None
    return env


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def meta_path_for(output_path):
    return os.path.join(os.path.dirname(os.path.abspath(output_path)), META_FILENAME)


def write_run_meta(output_path, meta):
    path = meta_path_for(output_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    return path


def build_run_meta(dataset, temperature, num_trajectories, seed, output_path,
                   resume=False):
    do_sample = temperature > 0.0
    return {
        "schema_version": META_SCHEMA_VERSION,
        "status": "running",
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finished_utc": None,
        "command": " ".join(sys.argv),
        "resumed": bool(resume),
        "git": git_state(),
        "model": {
            "name": MODEL_NAME,
            "max_new_tokens": MAX_NEW_TOKENS,
            "declared_context": MODEL_MAX_CONTEXT,
        },
        "sampling": {
            "temperature": temperature,
            "do_sample": do_sample,
            # top_p only reaches the model when sampling; recording it for a
            # greedy run would imply it had an effect.
            "top_p": TOP_P if do_sample else None,
            "seed": seed,
            "greedy_deterministic": not do_sample,
            "num_samples": len(dataset),
            "num_trajectories_per_sample": num_trajectories,
        },
        "dataset": {
            "name": getattr(dataset, "name", DATASET_NAME),
            "split": getattr(dataset, "split", DATASET_SPLIT),
            "fingerprint": getattr(dataset, "fingerprint", None),
            "rows_in_split": getattr(dataset, "num_rows_in_split", None),
            "selection": getattr(dataset, "selection", None),
        },
        "environment": environment_state(),
        "output": {
            "traces": os.path.basename(output_path),
            "records_written": 0,
            "records_expected": len(dataset) * num_trajectories,
            "sha256": None,
            "elapsed_seconds": None,
        },
    }


def traj_key(sample_index, temperature, trajectory_index):
    """Stable identity of one trajectory, used for --resume."""
    return f"{int(sample_index)}|{float(temperature):.4f}|{int(trajectory_index)}"


def load_done_keys(path):
    """Keys already present in an output file. Tolerates a truncated last line."""
    done = set()
    if not os.path.exists(path):
        return done
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                print(
                    f"[resume] {path}:{lineno} is not valid JSON (likely a partial "
                    "write from an interrupted run); ignoring that line.",
                    file=sys.stderr,
                )
                continue
            try:
                done.add(
                    traj_key(
                        rec["sample_index"], rec["temperature"], rec["trajectory_index"]
                    )
                )
            except (KeyError, TypeError, ValueError):
                print(f"[resume] {path}:{lineno} has no usable key; ignoring.",
                      file=sys.stderr)
    return done


class JsonlWriter:
    """Append-only writer that flushes and fsyncs after every record."""

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._repair_torn_tail(path)
        self._f = open(path, "a", encoding="utf-8")

    @staticmethod
    def _repair_torn_tail(path):
        """Terminate a partial final line left by an interrupted run.

        A process killed mid-write leaves a line with no trailing newline. If we
        just append, the next record is glued onto that fragment and BOTH lines
        become unparseable — so an interrupt would cost us the next trajectory
        too. Close the fragment off first; load_done_keys() then skips it.
        """
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            last = f.read(1)
        if last != b"\n":
            print(
                f"[resume] {path} ends mid-line (interrupted run); terminating "
                "the partial record before appending.",
                file=sys.stderr,
            )
            with open(path, "ab") as f:
                f.write(b"\n")
                f.flush()
                os.fsync(f.fileno())

    def write(self, record):
        self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._f.flush()
        os.fsync(self._f.fileno())

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def build_record(sample, prompt, gen, temperature, trajectory_index, seed=None):
    """Assemble one JSONL record from a raw generation result."""
    completion = gen["text"]
    full_code = extract_lean4_block(prompt, completion)
    parsed = parse_output(completion, prompt=None)

    if gen["hit_token_limit"]:
        extract_status = "truncated_token_limit"
    elif full_code is None:
        extract_status = "no_closing_fence"
    else:
        extract_status = "extracted"

    return {
        # identity
        "sample_index": sample["index"],
        "temperature": temperature,
        "trajectory_index": trajectory_index,
        "problem_unique_id": sample["problem_unique_id"],
        "model": MODEL_NAME,
        # provenance: which dataset row this came from, and the decode config
        # that produced it. Per-record as well as in run_meta.json, so a trace
        # separated from its sidecar is still self-describing.
        "dataset_row": sample.get("dataset_row"),
        "state": sample.get("state"),
        "level": sample.get("level"),
        "type": sample.get("type"),
        "top_p": TOP_P if temperature > 0.0 else None,
        "seed": seed,
        # inputs
        "prompt": prompt,
        "formal_statement": sample["formal_statement"],
        "informal_step": sample["informal_step"],
        "reference_proof": sample["reference_proof"],
        # NL metadata, never fed to the model as the goal
        "problem": sample["problem"],
        "ground_truth": sample["ground_truth"],
        # outputs
        "raw_output": completion,
        "full_code": full_code,
        "parsed_code": parsed["code"],
        "theorem_name": parsed["theorem_name"],
        "found_declaration": parsed["found_declaration"],
        "has_sorry_literal": parsed["has_sorry_literal"],
        # explicit generation-side failure modes (issue #4)
        "extract_status": extract_status,
        "truncated": gen["truncated"],
        "hit_token_limit": gen["hit_token_limit"],
        "closed_fence": gen["closed_fence"],
        "stopped_on_eos": gen["stopped_on_eos"],
        "prompt_tokens": gen["prompt_tokens"],
        "generated_tokens": gen["generated_tokens"],
        "max_new_tokens": gen["max_new_tokens"],
        "seconds": round(gen["seconds"], 3),
    }


# ---------------------------------------------------------------------------
# dry run — no model is loaded
# ---------------------------------------------------------------------------

def dry_run(num_samples, show_sample=0, temperature=0.0, num_trajectories=1,
            strategy=SAMPLE_STRATEGY, stride=PROBLEM_STRIDE,
            step_selection=STEP_SELECTION):
    dataset = FormalStepDataset(
        num_samples=num_samples,
        strategy=strategy,
        stride=stride,
        step_selection=step_selection,
    )
    print(f"Loaded {len(dataset)} samples. Columns: {dataset.columns}\n")
    sel = dataset.selection
    print("SAMPLE SELECTION")
    print(f"  strategy                  : {sel['strategy']}")
    if sel["strategy"] == "distinct_problems":
        print(f"  stride / step             : {sel['stride']} / {sel['step_selection']}")
        print(f"  problems in split         : {sel['problems_in_split']}")
    print(f"  distinct problems selected: {sel['distinct_problems_in_selection']}"
          f" / {len(dataset)} samples")
    print(f"  levels                    : {sel['levels']}")
    print(f"  dataset states            : {sel['states']}")
    print(f"  dataset rows              : {sel['dataset_rows'][:8]} ...\n")
    if sel["distinct_problems_in_selection"] < len(dataset):
        print("  [WARN] these samples are CoT steps of the same problem, not "
              "independent samples.\n")

    tokenizer = None
    try:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    except Exception as e:  # noqa: BLE001 - tokenizer is a nicety here, not required
        print(f"[dry-run] tokenizer unavailable ({e}); skipping token counts.\n",
              file=sys.stderr)

    prompts = []
    for idx in range(len(dataset)):
        sample = dataset[idx]
        prompts.append((sample, build_prompt(sample)))

    sample, prompt = prompts[show_sample]

    print("=" * 78)
    print(f"FULLY RENDERED PROMPT — sample {show_sample} "
          f"({sample['problem_unique_id']})")
    print("=" * 78)
    print(prompt, end="")
    print("<<<END OF PROMPT (no trailing newline beyond what is shown)>>>")
    print("=" * 78)

    print("\nPrompt tail, exact repr (shows the unterminated ```lean4 fence):")
    print("  " + repr(prompt[-220:]))

    print("\nStructural checks:")
    checks = [
        ("starts with the documented instruction",
         prompt.startswith("Complete the following Lean 4 code with explanatory "
                           "comments preceding each line of code:")),
        ("opens a ```lean4 fence", "```lean4\n" in prompt),
        ("fence left open for completion", prompt.count("```") == 1),
        ("contains the Lean header import", "import Mathlib" in prompt),
        ("contains the FORMAL statement",
         sample["formal_statement"].strip() in prompt),
        ("formal statement ends ':= by'", prompt.rstrip().endswith(":= by")),
        ("no trailing 'sorry' handed to the model",
         not prompt.rstrip().endswith("sorry")),
        ("NL prose is NOT the proof goal",
         sample["problem"].strip() not in prompt.replace(
             sample["formal_statement"], "") or not sample["problem"].strip()),
    ]
    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    if tokenizer is not None:
        lengths = [len(tokenizer(p)["input_ids"]) for _, p in prompts]
        longest = max(lengths)
        print(f"\nPrompt tokens: min={min(lengths)} mean={sum(lengths)//len(lengths)} "
              f"max={longest}  (context window {MODEL_MAX_CONTEXT})")
        print(f"Headroom for generation on the longest prompt: "
              f"{MODEL_MAX_CONTEXT - longest} tokens "
              f"(MAX_NEW_TOKENS={MAX_NEW_TOKENS})")
        over = [i for i, n in enumerate(lengths) if n >= MODEL_MAX_CONTEXT]
        if over:
            print(f"  [FAIL] {len(over)} prompt(s) exceed the context window: {over[:10]}")

    # Parser exercise. There is no model output in a dry run, so we feed the
    # parser the dataset's own reference proof as a stand-in completion. This is
    # a parser smoke test, NOT a trajectory, and nothing is written to disk.
    print("\n" + "=" * 78)
    print("PARSER SMOKE TEST (input = dataset reference proof, not model output)")
    print("=" * 78)
    stats = {"extracted": 0, "no_closing_fence": 0, "found_declaration": 0}
    for s, p in prompts:
        body = s["reference_proof"].strip()
        # Emulate what a well-behaved completion looks like: the proof body
        # continuing the open fence, then the closing fence.
        stand_in = body.split(":= by", 1)[-1] + "\n```"
        code = extract_lean4_block(p, stand_in)
        parsed = parse_output(stand_in, prompt=None)
        stats["extracted" if code is not None else "no_closing_fence"] += 1
        stats["found_declaration"] += int(parsed["found_declaration"])
    print(f"  fence extraction succeeded : {stats['extracted']}/{len(prompts)}")
    print(f"  no closing fence           : {stats['no_closing_fence']}/{len(prompts)}")

    s0, p0 = prompts[show_sample]
    stand_in0 = s0["reference_proof"].strip().split(":= by", 1)[-1] + "\n```"
    print(f"\n  Reconstructed Lean file for sample {show_sample} "
          "(prompt + stand-in completion):")
    print("  " + "-" * 74)
    for line in (extract_lean4_block(p0, stand_in0) or "<extraction failed>").split("\n"):
        print("  | " + line)
    print("  " + "-" * 74)

    print(f"\nDry run complete. No model was loaded and nothing was written to disk.")
    print(f"Would generate {len(dataset)} samples x {num_trajectories} trajectories "
          f"at temperature {temperature}.")
    return prompts


# ---------------------------------------------------------------------------
# real generation
# ---------------------------------------------------------------------------

# One model per process, shared across every temperature in a sweep.
#
# Constructing a second GoedelProver while the first is still resident fails the
# VRAM preflight: the weights are ~12.9 GiB on a 22 GiB A10, so the second
# instance sees ~9 GiB free against 15.5 GiB required and correctly refuses to
# offload to CPU. That is exactly what happened to `--temp 0 0.2`: temperature 0
# finished, temperature 0.2 died before generating anything. Temperature is a
# per-call argument, not a property of the loaded model, so one load serves all
# of them — and a sweep no longer pays a 13.8 GB reload per temperature.
_PROVER = None


def load_prover():
    global _PROVER
    if _PROVER is None:
        from model import GoedelProver  # late import: --dry-run needs no CUDA

        print("Loading model...", file=sys.stderr)
        t_load = time.perf_counter()
        _PROVER = GoedelProver()
        print(f"Model loaded in {time.perf_counter() - t_load:.1f}s", file=sys.stderr)
    else:
        print("Reusing the already-loaded model.", file=sys.stderr)
    return _PROVER

def run_generation(
    temperature,
    output_path,
    num_samples=NUM_SAMPLES,
    num_trajectories=NUM_TRAJECTORIES,
    resume=False,
    traj_batch=1,
    seed=None,
    strategy=SAMPLE_STRATEGY,
    stride=PROBLEM_STRIDE,
    step_selection=STEP_SELECTION,
    allow_unseeded=False,
):
    # Sampling without a seed cannot be reproduced. Greedy decoding can, so a
    # seed is only mandatory when the run actually samples.
    if temperature > 0.0 and seed is None and not allow_unseeded:
        raise ValueError(
            f"temperature={temperature} samples, so the run is unreproducible "
            "without a seed. Pass --seed, or --allow-unseeded to record "
            "seed=null deliberately."
        )

    dataset = FormalStepDataset(
        num_samples=num_samples,
        strategy=strategy,
        stride=stride,
        step_selection=step_selection,
    )
    sel = dataset.selection
    print(
        f"Loaded {len(dataset)} samples from FormalStep "
        f"[{sel['strategy']}]: {sel['distinct_problems_in_selection']} distinct "
        f"problem(s), levels {sel['levels']}, states {sel['states']}",
        file=sys.stderr,
    )
    if sel["distinct_problems_in_selection"] < len(dataset):
        print(
            f"[warn] {len(dataset)} samples span only "
            f"{sel['distinct_problems_in_selection']} distinct problem(s) — "
            "these are CoT steps of the same problem, not independent samples.",
            file=sys.stderr,
        )

    done = load_done_keys(output_path) if resume else set()
    if resume:
        print(f"[resume] {len(done)} trajectories already in {output_path}",
              file=sys.stderr)
    elif os.path.exists(output_path):
        raise FileExistsError(
            f"{output_path} already exists. Pass --resume to continue it, or "
            "choose a new path — existing trajectory files are never overwritten."
        )

    # Written before the model loads: an interrupted run still leaves a sidecar
    # describing exactly what it was trying to do.
    meta = build_run_meta(dataset, temperature, num_trajectories, seed,
                          output_path, resume=resume)
    print(f"[meta] {write_run_meta(output_path, meta)}", file=sys.stderr)

    # Load the model only once we know there is work to do.
    total_wanted = len(dataset) * num_trajectories
    if len(done) >= total_wanted:
        print(f"[resume] nothing to do: {len(done)}/{total_wanted} present.",
              file=sys.stderr)
        return output_path

    prover = load_prover()

    if temperature == 0.0 and num_trajectories > 1:
        print(
            f"[warn] temperature=0 is greedy decoding: all {num_trajectories} "
            "trajectories for a sample will be identical.",
            file=sys.stderr,
        )

    written = 0
    skipped = 0
    t_run = time.perf_counter()

    with JsonlWriter(output_path) as writer:
        for idx in range(len(dataset)):
            sample = dataset[idx]
            prompt = build_prompt(sample)

            wanted = [
                t for t in range(num_trajectories)
                if traj_key(idx, temperature, t) not in done
            ]
            skipped += num_trajectories - len(wanted)
            if not wanted:
                continue

            print(
                f"[{idx + 1}/{len(dataset)}] {sample['problem_unique_id']} "
                f"-> {len(wanted)} trajectory(ies)",
                file=sys.stderr,
            )

            gens = prover.generate(
                prompt,
                temperature=temperature,
                num_trajectories=len(wanted),
                batch=traj_batch,
                seed=None if seed is None else seed + idx * 1000,
            )

            for traj_index, gen in zip(wanted, gens):
                record = build_record(sample, prompt, gen, temperature, traj_index,
                                      seed=seed)
                writer.write(record)
                written += 1
                print(
                    f"    traj {traj_index}: {gen['seconds']:.2f}s  "
                    f"{gen['generated_tokens']} tok  "
                    f"status={record['extract_status']}",
                    file=sys.stderr,
                )

    elapsed = time.perf_counter() - t_run

    present = len(load_done_keys(output_path))
    meta["status"] = "complete" if present >= total_wanted else "incomplete"
    meta["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["output"].update(
        records_written=present,
        sha256=sha256_file(output_path),
        elapsed_seconds=round(elapsed, 1),
    )
    write_run_meta(output_path, meta)

    print(
        f"\nWrote {written} trajectories ({skipped} skipped) to {output_path} "
        f"in {elapsed:.1f}s"
        + (f" ({elapsed / written:.2f}s per trajectory)" if written else ""),
        file=sys.stderr,
    )
    print(f"[meta] status={meta['status']} "
          f"{present}/{total_wanted} records, sha256={meta['output']['sha256'][:16]}",
          file=sys.stderr)
    return output_path


def run_dir_name(temperature, num_samples, num_trajectories):
    """Directory name that states the config it holds.

    Temperature sweeps write to sibling directories rather than overwriting one
    another, which is also why nothing here ever includes a bare "temp_0".
    """
    return f"temp{temperature}_n{num_samples}_{num_trajectories}each"


def default_output_path(temperature, num_samples=NUM_SAMPLES,
                        num_trajectories=NUM_TRAJECTORIES):
    return os.path.join(
        TRACES_DIR,
        run_dir_name(temperature, num_samples, num_trajectories),
        "traces.jsonl",
    )
