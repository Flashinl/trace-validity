"""Shared configuration for the trace-validity study.

Everything that both stages need to agree on lives here: the prompt format, the
dataset slice, the sampling budget, and the on-disk layout. The two stages never
talk to each other except through these file paths.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

# --- dataset / model ---------------------------------------------------------

DATASET_NAME = "liuchengwu/FormalStep"
DATASET_SPLIT = "train"
N_QUESTIONS = 50

MODEL_NAME = "Goedel-LM/Goedel-Prover-SFT"

# --- prompt ------------------------------------------------------------------

# Goedel-Prover-SFT is a *formal* prover. It expects a partial Lean 4 file and
# continues it. Handing it the natural-language `problem` field on its own makes
# it invent its own theorem statement, which then cannot be scored against the
# dataset's statement.
BASE_IMPORTS = "import Mathlib\nimport Aesop"
SET_OPTIONS = "set_option maxHeartbeats 400000\n"
HEADER = BASE_IMPORTS + "\n\n" + SET_OPTIONS
PROMPT_PREFIX = "Complete the following Lean 4 code:\n\n```lean4\n"

# --- sampling ----------------------------------------------------------------

N_TRAJ = 10
# The model's context is 4096 tokens total; the prompt already eats a chunk of
# it. 1536 new tokens is a working ceiling, not a knob to raise to 20000.
MAX_NEW_TOKENS = 1536
TOP_P = 0.95

# --- Lean -------------------------------------------------------------------

# Lean results are not comparable across Mathlib versions. This tag is pinned
# here, recorded into every results file, and must match the checkout that
# verify actually ran against.
MATHLIB_TAG = "v4.19.0"
MATHLIB_REPO = "https://github.com/leanprover-community/mathlib4.git"
# Toolchain that goes with MATHLIB_TAG. Only used by the no-local-checkout
# fallback, where lean_interact requires it explicitly; the normal path reads
# the version out of the checkout's own lean-toolchain instead. Move it with
# MATHLIB_TAG.
LEAN_VERSION = "v4.19.0"
MATHLIB_DIR = os.environ.get("MATHLIB_DIR", "mathlib4")

# `BASE_IMPORTS` above is also what stage 2 runs once to build the environment
# every proof is then checked against.

# The smoke test that must pass before any real verification happens.
# (`#check norm_num` is NOT a valid probe -- norm_num is a tactic, not a term.)
SMOKE_GOOD = "example : (2:ℝ) + 2 = 4 := by norm_num"
SMOKE_BAD = "example : (2:ℝ) + 2 = 5 := by norm_num"

# --- paths -------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.environ.get("RESULTS_DIR", os.path.join(REPO_ROOT, "results"))
FIGS_DIR = os.environ.get("FIGS_DIR", os.path.join(REPO_ROOT, "figs"))


def fmt_temp(temp: float) -> str:
    """Canonical string for a temperature, used in every filename.

    0 -> "0", 0.2 -> "0.2", 1.0 -> "1". Stable so that a rerun at the same
    temperature finds and resumes its own files.
    """
    return f"{float(temp):g}"


def ensure_dirs() -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(FIGS_DIR, exist_ok=True)


def traj_jsonl_path(temp: float) -> str:
    """Stage 1 append-as-you-go file (the resume log)."""
    return os.path.join(RESULTS_DIR, f"traj_temp{fmt_temp(temp)}.jsonl")


def traj_json_path(temp: float) -> str:
    """Stage 1 consolidated output, the input to stage 2."""
    return os.path.join(RESULTS_DIR, f"traj_temp{fmt_temp(temp)}.json")


def results_jsonl_path(temp: float) -> str:
    """Stage 2 append-as-you-go file (the resume log)."""
    return os.path.join(RESULTS_DIR, f"results_temp{fmt_temp(temp)}.jsonl")


def results_json_path(temp: float) -> str:
    """Stage 2 consolidated output, the input to stage 3."""
    return os.path.join(RESULTS_DIR, f"results_temp{fmt_temp(temp)}.json")


# --- byte-level BPE repair ---------------------------------------------------
#
# Lives here because BOTH stages need it: generation repairs before writing,
# and verification repairs again when reading older files that were written
# before the fix.


def _bytes_to_unicode() -> Dict[int, str]:
    """GPT-2's byte<->unicode table (the same one the tokenizer uses)."""
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    cs = bs[:]
    n = 0
    for b in range(2 ** 8):
        if b not in bs:
            bs.append(b)
            cs.append(2 ** 8 + n)
            n += 1
    return dict(zip(bs, (chr(c) for c in cs)))


_BYTE_DECODER = {v: k for k, v in _bytes_to_unicode().items()}


def repair_bpe(text: str) -> str:
    """Undo byte-level BPE surface form.

    This tokenizer's byte decoder is broken: plain
    `tokenizer.decode(..., skip_special_tokens=True)` returns token surface
    ('Ġ' for space, 'Ċ' for newline) with zero real whitespace. Confirmed
    independently outside this repo, so the repair runs on the generation side
    rather than being treated as a defensive nicety.

    Those two characters are the tell; without them the text is passed through
    untouched, because the mapping is lossy for genuine unicode (Lean source is
    full of ℝ, ∀, ≤). That no-op path is what makes this safe to keep once a
    future tokenizer version decodes correctly.
    """
    if "Ġ" not in text and "Ċ" not in text:
        return text
    buf = bytearray()
    for ch in text:
        if ch in _BYTE_DECODER:
            buf.append(_BYTE_DECODER[ch])
        else:
            buf.extend(ch.encode("utf-8"))
    return buf.decode("utf-8", errors="replace")


# --- jsonl helpers -----------------------------------------------------------
#
# Both stages use the same resume protocol: append one JSON object per unit of
# work to a .jsonl as soon as it is done, and consolidate to a .json at the end.
# A half-written last line (killed mid-flush) is skipped on read rather than
# taken as a reason to start over.


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # truncated tail from a hard kill
    return rows


def append_jsonl(path: str, record: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def n_traj_for(temp: float, n_traj: int = N_TRAJ) -> int:
    """Trajectories to draw at this temperature.

    At temperature 0 decoding is greedy, so 10 samples would be 10 identical
    strings. We take 1 and record that the run was greedy.
    """
    return 1 if float(temp) == 0.0 else int(n_traj)
