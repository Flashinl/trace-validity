"""Stage 2 (CPU): check every sampled trajectory with Lean 4 + Mathlib.

Runs alone, reading only results/traj_temp{T}.json from stage 1. No GPU, no
model, no network beyond the Lean toolchain that setup already installed.

Two things dominate the runtime and are handled up front:
  * Mathlib is imported ONCE into a base environment which is then reused for
    every proof. Re-importing per proof costs 30-60s and there are ~500 proofs.
  * The `lake exe cache get` step (see README / scripts/setup_lean.sh) is what
    keeps Mathlib from being compiled from source.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from . import config as C


# --- byte-level BPE repair ---------------------------------------------------


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
    """Undo byte-level BPE surface form if the decoder left it in.

    Some decode paths hand back the raw token surface ('Ġ' for space, 'Ċ' for
    newline) instead of real text. Those two characters are the tell; without
    them the text is passed through untouched, because the mapping is lossy for
    genuine unicode (Lean source is full of ℝ, ∀, ≤).
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


# --- completion -> proof body ------------------------------------------------


def cut_at_fence(text: str) -> str:
    """Keep only what precedes the closing ``` of the code block."""
    idx = text.find("```")
    return text[:idx] if idx != -1 else text


def drop_dangling_comment(text: str) -> str:
    """Truncate at the first `/-` that is never closed.

    A completion cut off mid-comment would otherwise swallow the rest of the
    file and report as one big syntax error.
    """
    stack: List[int] = []
    i = 0
    while i < len(text) - 1:
        two = text[i : i + 2]
        if two == "/-":
            stack.append(i)
            i += 2
        elif two == "-/":
            if stack:
                stack.pop()
            i += 2
        else:
            i += 1
    if stack:
        return text[: stack[0]].rstrip()
    return text


def extract_body(completion: str) -> str:
    """Turn a raw completion into a tactic block ready to graft."""
    body = repair_bpe(completion)
    body = cut_at_fence(body)
    body = drop_dangling_comment(body)
    return body.rstrip()


def assemble(informal: str, statement: str, body: str) -> str:
    """Graft the model's tactics onto the DATASET's theorem.

    The model is free to restate the theorem in its completion, and sometimes
    restates it wrong (or weaker). Scoring that would be scoring a different
    problem, so the statement always comes from the dataset and only the tactic
    block comes from the model. Imports are already in the base env; the
    set_option is not, so it is re-emitted here.
    """
    return C.SET_OPTIONS + informal + statement + body + "\n"


# --- error classification ----------------------------------------------------

SYNTAX_RE = re.compile(
    r"unexpected (token|identifier|character|end of input)"
    r"|unterminated comment"
    r"|; expected\b"
    r"|(?:^|\n)\s*expected\b",
    re.IGNORECASE,
)
UNKNOWN_RE = re.compile(
    r"unknown (constant|identifier|namespace|declaration|tactic|free variable)",
    re.IGNORECASE,
)
UNSOLVED_RE = re.compile(r"unsolved goals", re.IGNORECASE)
SORRY_RE = re.compile(r"declaration uses 'sorry'", re.IGNORECASE)


def classify(errors: List[str]) -> Dict[str, bool]:
    blob = "\n".join(errors)
    return {
        "syntax_err": bool(SYNTAX_RE.search(blob)),
        "unknown_err": bool(UNKNOWN_RE.search(blob)),
        "unsolved_goals": bool(UNSOLVED_RE.search(blob)),
    }


# --- Lean server -------------------------------------------------------------


def _import_lean_interact():
    from lean_interact import AutoLeanServer, Command, LeanREPLConfig  # noqa: F401

    try:  # module layout moved between lean_interact releases
        from lean_interact.project import LocalProject, TempRequireProject
    except ImportError:  # pragma: no cover - depends on installed version
        from lean_interact import LocalProject, TempRequireProject  # type: ignore
    return AutoLeanServer, Command, LeanREPLConfig, LocalProject, TempRequireProject


class LeanChecker:
    """A Lean server with Mathlib imported exactly once."""

    def __init__(self, mathlib_dir: str = C.MATHLIB_DIR):
        (
            AutoLeanServer,
            Command,
            LeanREPLConfig,
            LocalProject,
            TempRequireProject,
        ) = _import_lean_interact()
        self._Command = Command

        if os.path.isdir(mathlib_dir):
            project = LocalProject(directory=mathlib_dir)
            print(f"[verify] using local Mathlib checkout at {mathlib_dir}")
        else:
            # Falls back to letting lean_interact provision Mathlib itself. This
            # is slow on a cold machine -- prefer the prebuilt checkout.
            # lean_version is a required keyword here (unlike LocalProject,
            # which reads it from the checkout), so it comes from the pin.
            project = TempRequireProject(
                lean_version=C.LEAN_VERSION, require="mathlib"
            )
            print("[verify] no local Mathlib checkout; provisioning a temp project")

        self.config = LeanREPLConfig(project=project)
        self.server = AutoLeanServer(self.config)
        self.mathlib_tag = read_mathlib_tag(mathlib_dir)

        t0 = time.time()
        resp = self.server.run(Command(cmd=C.BASE_IMPORTS), timeout=1200)
        self.base_env = getattr(resp, "env", None)
        if self.base_env is None:
            raise RuntimeError(f"failed to build base env from imports: {resp!r}")
        print(f"[verify] base env ready in {time.time() - t0:.0f}s "
              f"(env={self.base_env}, mathlib={self.mathlib_tag})")

    def check(self, code: str, timeout: int = 300) -> Dict[str, Any]:
        """Run one snippet against the base env and summarise the diagnostics."""
        try:
            resp = self.server.run(
                self._Command(cmd=code, env=self.base_env), timeout=timeout
            )
        except Exception as exc:  # server crash / timeout -> treat as an error
            return {
                "errors": [f"lean_interact exception: {type(exc).__name__}: {exc}"],
                "has_sorry": False,
                "timed_out": True,
            }

        errors: List[str] = []
        has_sorry = bool(getattr(resp, "sorries", None))

        msgs = getattr(resp, "messages", None)
        if msgs is None:
            # LeanError-shaped response: one hard failure, no message list.
            text = getattr(resp, "message", None) or repr(resp)
            errors.append(str(text))
        else:
            for m in msgs:
                sev, data = _msg_fields(m)
                if sev == "error":
                    errors.append(data)
                if SORRY_RE.search(data):
                    has_sorry = True

        return {"errors": errors, "has_sorry": has_sorry, "timed_out": False}

    def smoke_test(self) -> None:
        """Refuse to produce numbers from a Lean server that is not working.

        A server that answers everything with "no errors" would report 100%
        validity and 100% accuracy, which is why the negative case is checked
        too. (`#check norm_num` would not test anything -- norm_num is a
        tactic, not a term, so it fails for the wrong reason.)
        """
        good = self.check(C.SMOKE_GOOD)
        if good["errors"]:
            raise RuntimeError(
                f"smoke test failed: `{C.SMOKE_GOOD}` reported errors: {good['errors']}"
            )
        bad = self.check(C.SMOKE_BAD)
        if not bad["errors"]:
            raise RuntimeError(
                f"smoke test failed: `{C.SMOKE_BAD}` reported no errors, so the "
                "server is not actually checking proofs"
            )
        print("[verify] smoke test passed (2+2=4 clean, 2+2=5 errors)")


def _msg_fields(m: Any) -> Tuple[str, str]:
    if isinstance(m, dict):
        return str(m.get("severity", "")), str(m.get("data", ""))
    return str(getattr(m, "severity", "")), str(getattr(m, "data", ""))


def read_mathlib_tag(mathlib_dir: str = C.MATHLIB_DIR) -> str:
    """Record what Mathlib actually ran, not what we hoped ran.

    Lean results are not comparable across Mathlib versions, so the resolved
    toolchain is stored alongside every results file.
    """
    toolchain_path = os.path.join(mathlib_dir, "lean-toolchain")
    if os.path.exists(toolchain_path):
        with open(toolchain_path, "r", encoding="utf-8") as fh:
            return f"{C.MATHLIB_TAG} ({fh.read().strip()})"
    return C.MATHLIB_TAG


# --- stage entrypoint --------------------------------------------------------


def verify_question(checker: LeanChecker, q: Dict[str, Any]) -> Dict[str, Any]:
    """Check every trajectory of one question."""
    trajectories = []
    for j, completion in enumerate(q.get("completions", [])):
        body = extract_body(completion)
        code = assemble(q["informal"], q["statement"], body)
        out = checker.check(code)
        errors = out["errors"]
        flags = classify(errors)

        # With a formal verifier these two are not independent: end_correct
        # implies trace_valid, because a proof with a syntax or unknown-constant
        # error cannot also elaborate cleanly. See README.
        trace_valid = not flags["syntax_err"] and not flags["unknown_err"]
        end_correct = (
            len(errors) == 0 and not out["has_sorry"] and not out["timed_out"]
        )

        trajectories.append(
            {
                "traj_idx": j,
                "body": body,
                "code": code,
                "trace_valid": trace_valid,
                "end_correct": end_correct,
                **flags,
                "has_sorry": out["has_sorry"],
                "timed_out": out["timed_out"],
                "n_errors": len(errors),
                "errors": errors[:3],
            }
        )
    return {
        "idx": q["idx"],
        "dataset_id": q.get("dataset_id"),
        "problem": q.get("problem", ""),
        "formal_statement": q.get("formal_statement", ""),
        "trajectories": trajectories,
    }


def run(temp: float, mathlib_dir: str = C.MATHLIB_DIR) -> str:
    """Verify (or resume verifying) every trajectory at one temperature."""
    C.ensure_dirs()
    traj_path = C.traj_json_path(temp)
    if not os.path.exists(traj_path):
        raise FileNotFoundError(
            f"{traj_path} not found -- run `--stage generate --temp "
            f"{C.fmt_temp(temp)}` first (it needs a GPU)."
        )

    payload = C.read_json(traj_path)
    questions = payload["questions"]
    n_traj = payload.get("n_traj", C.n_traj_for(temp))

    jsonl_path = C.results_jsonl_path(temp)
    done = C.read_jsonl(jsonl_path)
    done_idx = {r["idx"] for r in done}
    todo = [q for q in questions if q["idx"] not in done_idx]

    print(f"[verify] temp={C.fmt_temp(temp)} questions={len(questions)} "
          f"done={len(done_idx)} todo={len(todo)}")

    # Left as None when there is nothing to do, so consolidate recovers the tag
    # the records were actually verified under rather than re-deriving it from
    # a machine that may not even have the checkout.
    mathlib_tag = None
    if todo:
        checker = LeanChecker(mathlib_dir)
        checker.smoke_test()
        mathlib_tag = checker.mathlib_tag
        for i, q in enumerate(todo, 1):
            t0 = time.time()
            record = verify_question(checker, q)
            record["mathlib_tag"] = mathlib_tag
            record["verify_seconds"] = round(time.time() - t0, 1)
            C.append_jsonl(jsonl_path, record)
            n_valid = sum(t["trace_valid"] for t in record["trajectories"])
            n_ok = sum(t["end_correct"] for t in record["trajectories"])
            print(f"  [{i}/{len(todo)}] idx={q['idx']} "
                  f"valid={n_valid}/{len(record['trajectories'])} "
                  f"correct={n_ok} ({record['verify_seconds']}s)")
    else:
        print("[verify] nothing to do, all questions already verified")

    return consolidate(temp, mathlib_tag, n_traj)


def consolidate(
    temp: float,
    mathlib_tag: Optional[str] = None,
    n_traj: Optional[int] = None,
) -> str:
    jsonl_path = C.results_jsonl_path(temp)
    json_path = C.results_json_path(temp)
    rows = C.read_jsonl(jsonl_path)

    by_idx = {r["idx"]: r for r in rows}
    ordered = [by_idx[k] for k in sorted(by_idx)]
    if mathlib_tag is None:
        tags = {r.get("mathlib_tag") for r in ordered if r.get("mathlib_tag")}
        mathlib_tag = sorted(tags)[0] if tags else C.MATHLIB_TAG

    C.write_json(
        json_path,
        {
            "temperature": float(temp),
            "n_traj": n_traj if n_traj is not None else C.n_traj_for(temp),
            "greedy": float(temp) == 0.0,
            "model": C.MODEL_NAME,
            "dataset": C.DATASET_NAME,
            # Lean verdicts are only meaningful against a stated Mathlib.
            "mathlib_tag": mathlib_tag,
            "n_questions": len(ordered),
            "questions": ordered,
        },
    )
    print(f"[verify] wrote {json_path} ({len(ordered)} questions)")
    return json_path
