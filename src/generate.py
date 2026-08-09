"""Stage 1 (GPU): sample proof trajectories from Goedel-Prover-SFT.

Runs alone. Writes results/traj_temp{T}.jsonl one question at a time so a Colab
disconnect costs at most the question in flight, then consolidates to
results/traj_temp{T}.json. Nothing here touches Lean.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from . import config as C


# --- prompt construction -----------------------------------------------------


def strip_sorry(formal_statement: str) -> str:
    """Cut the dataset statement back to its `:= by`.

    FormalStep statements end in a `sorry` placeholder. We remove it so the
    prompt stops mid-proof and the model has something to continue. The prompt
    is deliberately left unclosed -- no trailing ``` -- for the same reason.
    """
    stmt = formal_statement.rstrip()
    if stmt.endswith("sorry"):
        stmt = stmt[: -len("sorry")].rstrip()
    return stmt


def build_parts(row: Dict[str, Any]) -> Dict[str, str]:
    """Return the informal comment, the trimmed statement, and the full prompt.

    Stage 2 re-uses `informal` and `statement` verbatim when it grafts a model
    tactic block back onto the *dataset's* theorem, so they are stored, not
    re-derived.
    """
    informal = "/-- " + str(row["problem"]).strip() + " -/\n"
    statement = strip_sorry(str(row["formal_statement"]))
    prompt = C.PROMPT_PREFIX + C.HEADER + informal + statement
    return {"informal": informal, "statement": statement, "prompt": prompt}


# --- dataset -----------------------------------------------------------------


def load_questions(n: int = C.N_QUESTIONS) -> List[Dict[str, Any]]:
    from datasets import load_dataset

    ds = load_dataset(C.DATASET_NAME, split=C.DATASET_SPLIT)
    rows = []
    for idx in range(min(n, len(ds))):
        row = ds[idx]
        parts = build_parts(row)
        rows.append(
            {
                "idx": idx,
                "dataset_id": str(row.get("id", row.get("name", idx))),
                "problem": row.get("problem", ""),
                "formal_statement": row.get("formal_statement", ""),
                **parts,
            }
        )
    return rows


# --- decode guard ------------------------------------------------------------

# Byte-level BPE surface markers: 'Ġ' (U+0120) stands for a space and 'Ċ'
# (U+010A) for a newline. They appear when token strings are joined directly
# -- convert_ids_to_tokens() + "".join() -- instead of being decoded. The
# result looks plausible and has zero real whitespace, so it sails through
# generation and only detonates in Lean.
BPE_MARKERS = ("Ġ", "Ċ")  # 'Ġ', 'Ċ'


def assert_decoded(texts: List[str]) -> List[str]:
    """Fail loudly if a completion is raw token surface rather than text."""
    for i, text in enumerate(texts):
        hits = [m for m in BPE_MARKERS if m in text]
        if hits:
            raise RuntimeError(
                f"completion {i} contains byte-level BPE markers {hits!r} -- it is "
                f"raw token surface, not decoded text. Generation must use "
                f"tokenizer.decode(..., skip_special_tokens=True) (or vLLM's "
                f"output.text), never convert_ids_to_tokens() + ''.join().\n"
                f"  offending prefix: {text[:120]!r}"
            )
    return texts


# --- model -------------------------------------------------------------------


def load_model():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    # device_map="auto" places the weights. Do NOT call
    # torch.set_default_device("cuda") -- it makes the tokenizer build its
    # outputs on the GPU and breaks the plain-Python ops around it.
    tokenizer = AutoTokenizer.from_pretrained(C.MODEL_NAME)
    model = AutoModelForCausalLM.from_pretrained(
        C.MODEL_NAME,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    model.eval()
    return tokenizer, model


def sample_completions(
    tokenizer, model, prompt: str, temp: float, n_traj: int = C.N_TRAJ
) -> List[str]:
    """Draw trajectories for one question and return only the new text."""
    import torch

    n = C.n_traj_for(temp, n_traj)
    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    prompt_len = inputs["input_ids"].shape[1]

    kwargs: Dict[str, Any] = {
        "max_new_tokens": C.MAX_NEW_TOKENS,
        "num_return_sequences": n,
        "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
    }
    if float(temp) == 0.0:
        kwargs["do_sample"] = False  # greedy; n is forced to 1 by n_traj_for
    else:
        kwargs.update(do_sample=True, temperature=float(temp), top_p=C.TOP_P)

    with torch.no_grad():
        out = model.generate(**inputs, **kwargs)

    texts = [
        tokenizer.decode(seq[prompt_len:], skip_special_tokens=True) for seq in out
    ]
    # Never let undecoded token surface reach disk again.
    return assert_decoded(texts)


# --- stage entrypoint --------------------------------------------------------


def run(
    temp: float,
    n_questions: int = C.N_QUESTIONS,
    n_traj: int = C.N_TRAJ,
) -> str:
    """Generate (or resume) all trajectories at one temperature."""
    C.ensure_dirs()
    jsonl_path = C.traj_jsonl_path(temp)

    questions = load_questions(n_questions)
    done = C.read_jsonl(jsonl_path)

    # A record written before the decode guard existed may hold raw token
    # surface. Treat those as NOT done so they regenerate -- otherwise the
    # resume logic quietly preserves exactly the output we are trying to fix.
    # consolidate() is last-write-wins per idx, so the fresh record supersedes
    # the poisoned one without editing the append-only log.
    poisoned = {
        r["idx"] for r in done
        if any(m in c for c in r.get("completions", []) for m in BPE_MARKERS)
    }
    done_idx = {r["idx"] for r in done} - poisoned
    if poisoned:
        print(f"[generate] {len(poisoned)} record(s) contain byte-level BPE "
              f"markers and will be regenerated: {sorted(poisoned)}")

    todo = [q for q in questions if q["idx"] not in done_idx]

    print(f"[generate] temp={C.fmt_temp(temp)} "
          f"n_traj={C.n_traj_for(temp, n_traj)} "
          f"questions={len(questions)} done={len(done_idx)} todo={len(todo)}")

    if todo:
        tokenizer, model = load_model()
        for i, q in enumerate(todo, 1):
            t0 = time.time()
            completions = sample_completions(
                tokenizer, model, q["prompt"], temp, n_traj
            )
            record = {
                **q,
                "temperature": float(temp),
                "n_traj": C.n_traj_for(temp, n_traj),
                "greedy": float(temp) == 0.0,
                "model": C.MODEL_NAME,
                "max_new_tokens": C.MAX_NEW_TOKENS,
                "completions": completions,
                "gen_seconds": round(time.time() - t0, 1),
            }
            C.append_jsonl(jsonl_path, record)
            print(f"  [{i}/{len(todo)}] idx={q['idx']} "
                  f"{len(completions)} traj in {record['gen_seconds']}s")
    else:
        print("[generate] nothing to do, all questions already present")

    return consolidate(temp, n_traj)


def consolidate(temp: float, n_traj: int = C.N_TRAJ) -> str:
    """Fold the resume log into the stable .json stage 2 reads."""
    jsonl_path = C.traj_jsonl_path(temp)
    json_path = C.traj_json_path(temp)
    rows = C.read_jsonl(jsonl_path)

    # Last write wins, then restore dataset order.
    by_idx = {r["idx"]: r for r in rows}
    ordered = [by_idx[k] for k in sorted(by_idx)]

    C.write_json(
        json_path,
        {
            "temperature": float(temp),
            "n_traj": C.n_traj_for(temp, n_traj),
            "greedy": float(temp) == 0.0,
            "model": C.MODEL_NAME,
            "dataset": C.DATASET_NAME,
            "n_questions": len(ordered),
            "questions": ordered,
        },
    )
    print(f"[generate] wrote {json_path} ({len(ordered)} questions)")
    return json_path
