"""Walk real trajectories through every pipeline stage, dumping intermediate
state at each boundary (issue #1, step 3).

  raw_output -> parse_output -> extracted code -> what the REPL actually gets
             -> raw REPL response -> recorded outcome

False negatives hide at these boundaries: a parser that drops the last line
turns a valid proof into a compile_error.

  python tests/trace_pipeline.py --n 5
  python tests/trace_pipeline.py --n 5 --traces path/to/temp_0.jsonl
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import parse_output  # noqa: E402
from prompting import extract_lean4_block  # noqa: E402
from verifier import LeanVerifier, split_prelude, has_declaration, BASE_IMPORTS  # noqa: E402

DEFAULT_TRACES = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "traces", "temp_0.jsonl"),
    r"C:\Users\vkris\lambda-ops\traces\temp_0.jsonl",
]


def find_traces(explicit=None):
    for p in ([explicit] if explicit else []) + DEFAULT_TRACES:
        if p and os.path.exists(p):
            return p
    raise FileNotFoundError(f"no trace file found; tried {DEFAULT_TRACES}")


def show(label, text, limit=1200):
    print(f"\n--- {label} " + "-" * max(0, 68 - len(label)))
    if text is None:
        print("  <None>")
        return
    if not str(text).strip():
        print("  <empty>")
        return
    s = str(text)
    body = s if len(s) <= limit else s[:limit] + f"\n  ... [{len(s)-limit} more chars]"
    for line in body.split("\n"):
        print("  | " + line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--traces", type=str, default=None)
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    path = find_traces(args.traces)
    print(f"trace file: {path}")

    recs = []
    seen = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            # one trajectory per sample; at temp 0 the other 9 are identical
            if r["sample_index"] in seen:
                continue
            seen.add(r["sample_index"])
            recs.append(r)
            if len(recs) >= args.n:
                break

    print(f"selected {len(recs)} trajectories (distinct samples)\n")

    v = LeanVerifier(timeout=args.timeout, verbose=False)
    print(f"verifier ready (Mathlib env built in {v.base_env_seconds:.1f}s)")

    report = []
    for r in recs:
        idx = r["sample_index"]
        print("\n" + "=" * 78)
        print(f"SAMPLE {idx}  ({r['problem_unique_id']})")
        print("=" * 78)

        # stage 1: raw model output
        show("STAGE 1  raw_output (verbatim from model)", r["raw_output"])

        # stage 2: parser.parse_output on the completion
        parsed = parse_output(r["raw_output"], prompt=None)
        show("STAGE 2  parser.parse_output -> ['code']", parsed["code"])
        print(f"\n  parser flags: found_declaration={parsed['found_declaration']} "
              f"truncated={parsed['truncated']} has_sorry={parsed['has_sorry']} "
              f"theorem_name={parsed['theorem_name']}")

        # stage 3: fence extraction over prompt+completion (what generate.py stored)
        full = extract_lean4_block(r["prompt"], r["raw_output"])
        show("STAGE 3  extract_lean4_block(prompt+completion) -> full_code", full)

        agree = (full or "").strip() == (r.get("full_code") or "").strip()
        print(f"\n  matches stored full_code: {agree}")

        # Does the parser's code differ from the fence-extracted code?
        p_body = (parsed["code"] or "")
        missing_decl = not has_declaration(p_body)
        print(f"  parser output contains a declaration: {not missing_decl}")
        if missing_decl:
            print("  >> PARSER LOSES THE THEOREM: parse_output sees only the "
                  "completion, and the theorem statement lives in the PROMPT.")

        # stage 4: what actually reaches the REPL
        target = full if full else p_body
        imports, rest = split_prelude(target or "")
        use_base = bool(imports) and set(imports) <= set(BASE_IMPORTS)
        mode = "shared_env" if use_base else "fresh"
        show(f"STAGE 4  sent to REPL (mode={mode}, imports={imports})",
             rest if use_base else target)

        # stage 5: raw REPL response
        res = v.verify(target, timeout=args.timeout)
        print(f"\n--- STAGE 5  raw REPL verdict " + "-" * 44)
        print(f"  outcome     : {res['outcome']}")
        print(f"  num_errors  : {res['num_errors']}   num_sorries: {res['num_sorries']}")
        print(f"  seconds     : {res['seconds']}   mode: {res['mode']}")
        for e in res["errors"][:4]:
            print(f"  ERROR  : {str(e)[:300]}")
        for w in res["warnings"][:3]:
            print(f"  WARNING: {str(w)[:200]}")

        # stage 6: the boolean the old pipeline would have recorded
        print(f"\n--- STAGE 6  recorded value " + "-" * 46)
        print(f"  new taxonomy outcome : {res['outcome']}")
        print(f"  old boolean would be : trace_valid={res['valid']}")

        report.append({
            "sample_index": idx,
            "parser_lost_theorem": missing_decl,
            "fence_matches_stored": agree,
            "outcome": res["outcome"],
            "num_errors": res["num_errors"],
            "num_sorries": res["num_sorries"],
            "seconds": res["seconds"],
            "mode": res["mode"],
            "first_error": (res["errors"][0][:400] if res["errors"] else None),
        })

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for r in report:
        print(f"  sample {r['sample_index']:<3} {r['outcome']:<14} "
              f"errs={r['num_errors']} sorries={r['num_sorries']} "
              f"{r['seconds']:>6.2f}s  parser_lost_theorem={r['parser_lost_theorem']}")

    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
