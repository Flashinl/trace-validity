"""Verify generated trajectories in Lean and record the full outcome taxonomy.

Separate command from generation: verification needs no GPU (CLAUDE.md).

  python verify_traces.py --traces traces/temp_0.jsonl --out results/verification_temp_0.jsonl
  python verify_traces.py --all          # every trajectory, not one per sample
  python verify_traces.py --resume
"""

import argparse
import json
import os
import sys

# Lean output contains math symbols (turnstile, blackboard bold). The Windows
# console defaults to cp1252 and raises UnicodeEncodeError on them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import time
from collections import Counter

import re

from config import RESULTS_DIR, VERIFY_TIMEOUT_SECONDS
from verifier import (
    LeanVerifier, OUTCOMES, PARSE_FAILURE, COMPILE_ERROR, STATEMENT_ERROR,
    STATEMENT_MISMATCH, has_declaration,
)

_DECL_COUNT_RE = re.compile(
    r"^[ \t]*(?:@\[[^\]]*\]\s*)?"
    r"(?:private\s+|protected\s+|noncomputable\s+)*"
    r"(?:theorem|lemma|example)\b", re.M)


def _strip_comments(code):
    code = re.sub(r"/-.*?-/", "", code, flags=re.S)
    return re.sub(r"--[^\n]*", "", code)


def _norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def statement_mismatch(full_code, formal_statement):
    """Is the compiled file actually a proof of the DATASET's statement?

    Nothing else in the pipeline checks this. `verify()` compiles a string and
    classifies the result; it never sees `formal_statement`, so a file that
    proves some *other* theorem compiles just as happily and scores `valid`.

    In practice the property holds, because PROMPT_TEMPLATE ends mid-fence
    immediately after the statement (which already ends `:= by`), so the model
    writes only a proof body -- measured 50/50 at both temperatures across the
    n50 runs. But it held by construction and was asserted nowhere: an edit to
    prompting.py would void it silently with no test failing. That is audit
    finding 1-A, and this is the assertion that closes it.

    Returns (mismatched: bool, detail: str).
    """
    stmt = _norm(formal_statement)
    if not stmt:
        return False, "no formal_statement on the record; cannot check"

    if stmt not in _norm(full_code):
        return True, "compiled file does not contain the dataset's formal_statement"

    n_decl = len(_DECL_COUNT_RE.findall(_strip_comments(full_code or "")))
    if n_decl != 1:
        return True, f"compiled file declares {n_decl} theorems; expected exactly 1"

    return False, "statement present verbatim, exactly one declaration"

DEFAULT_TRACES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces", "temp_0.jsonl"),
    r"C:\Users\vkris\lambda-ops\traces\temp_0.jsonl",
]


def find_traces(explicit=None):
    for p in ([explicit] if explicit else []) + DEFAULT_TRACES:
        if p and os.path.exists(p):
            return p
    raise FileNotFoundError(f"no trace file found; tried {DEFAULT_TRACES}")


def load_done(path):
    done = set()
    if not os.path.exists(path):
        return done
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                done.add((r["sample_index"], r["trajectory_index"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", type=str, default=None)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--timeout", type=float, default=VERIFY_TIMEOUT_SECONDS)
    ap.add_argument("--all", action="store_true",
                    help="verify every trajectory (default: one per sample, since "
                         "temperature-0 trajectories are byte-identical)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    path = find_traces(args.traces)
    out = args.out or os.path.join(RESULTS_DIR, "verification_temp_0.jsonl")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    if os.path.exists(out) and not args.resume:
        raise FileExistsError(
            f"{out} exists. Pass --resume, or choose a new path — results from "
            "real runs are never overwritten."
        )

    recs, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if not args.all:
                if r["sample_index"] in seen:
                    continue
                seen.add(r["sample_index"])
            recs.append(r)
    if args.limit:
        recs = recs[: args.limit]

    done = load_done(out) if args.resume else set()
    todo = [r for r in recs if (r["sample_index"], r["trajectory_index"]) not in done]
    print(f"trace file : {path}")
    print(f"to verify  : {len(todo)} ({len(done)} already done)")

    if not todo:
        print("nothing to do")
        return

    t_setup = time.perf_counter()
    v = LeanVerifier(timeout=args.timeout, verbose=False)
    print(f"verifier ready in {time.perf_counter()-t_setup:.1f}s "
          f"(Mathlib env {v.base_env_seconds:.1f}s)")

    counts = Counter()
    t0 = time.perf_counter()
    with open(out, "a", encoding="utf-8") as fh:
        for i, r in enumerate(todo, 1):
            # `full_code` is the fence-extracted file (header + theorem + proof).
            # If fence extraction failed we fall back to the parser, but if that
            # also yields nothing usable the failure happened BEFORE Lean ever
            # saw the code — that is `parse_failure`, not `compile_error`.
            full = r.get("full_code")
            code = full or r.get("parsed_code") or ""
            if not full and not has_declaration(code or ""):
                res = {
                    "outcome": PARSE_FAILURE, "valid": False,
                    "errors": ["fence extraction produced no code and the parser "
                               "fallback contains no declaration"],
                    "warnings": [], "num_errors": 0, "num_sorries": 0,
                    "seconds": 0.0, "mode": "none",
                }
            else:
                res = v.verify(code, timeout=args.timeout)

                # Before scoring a clean compile, confirm that what compiled is
                # a proof of the DATASET's statement and not of something the
                # generation wrote itself. Only meaningful on a pass: a file
                # that failed to compile was not a proof of anything.
                if res["valid"]:
                    bad, why = statement_mismatch(code, r.get("formal_statement"))
                    if bad:
                        res = dict(res, outcome=STATEMENT_MISMATCH, valid=False,
                                   statement_mismatch_detail=why)

                # A compile_error is a verdict on the model's proof only if the
                # goal was well-formed. Re-verify the statement on its own with
                # `sorry` for a proof; if that still fails, Lean rejected the
                # goal and never judged the model, so the outcome becomes
                # statement_error instead of being scored against the prover.
                if res["outcome"] == COMPILE_ERROR:
                    broken, detail = v.statement_is_broken(
                        r.get("formal_statement"), timeout=args.timeout
                    )
                    if broken:
                        res = dict(
                            res,
                            outcome=STATEMENT_ERROR,
                            valid=False,
                            statement_error_detail=detail,
                        )
            counts[res["outcome"]] += 1

            rec = {
                "sample_index": r["sample_index"],
                "trajectory_index": r["trajectory_index"],
                "temperature": r["temperature"],
                "problem_unique_id": r.get("problem_unique_id"),
                # Dataset provenance and the dataset's OWN provability label,
                # carried through so the analysis can cross-tabulate our verdict
                # against it without re-opening the dataset.
                "dataset_row": r.get("dataset_row"),
                "state": r.get("state"),
                "level": r.get("level"),
                "outcome": res["outcome"],
                "trace_valid": res["valid"],
                "num_errors": res["num_errors"],
                "num_sorries": res["num_sorries"],
                "errors": res["errors"][:5],
                "warnings": res["warnings"][:3],
                "seconds": res["seconds"],
                "mode": res["mode"],
                "statement_error_detail": res.get("statement_error_detail"),
                "statement_mismatch_detail": res.get("statement_mismatch_detail"),
                # What the proof actually stands on. `valid` is only evidence if
                # this is a subset of the trusted set (audit finding 1-F).
                "axioms": res.get("axioms"),
                # generation-side context, carried through for analysis
                "gen_extract_status": r.get("extract_status"),
                "gen_truncated": r.get("truncated"),
                "generated_tokens": r.get("generated_tokens"),
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

            print(f"  [{i:>3}/{len(todo)}] sample {r['sample_index']:<3} "
                  f"{res['outcome']:<14} {res['seconds']:>6.2f}s  {res['mode']}",
                  file=sys.stderr)

    elapsed = time.perf_counter() - t0
    print(f"\n{len(todo)} verifications in {elapsed:.1f}s "
          f"({elapsed/len(todo):.2f}s each)")
    print("\nOUTCOME DISTRIBUTION")
    for o in OUTCOMES:
        if counts[o]:
            print(f"  {o:<16} {counts[o]:>4}  ({counts[o]/len(todo):.1%})")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
