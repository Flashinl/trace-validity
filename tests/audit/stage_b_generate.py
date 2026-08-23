"""Stage B generation on the Lambda A10. THROWAWAY -- mirrors generate.py's
essentials for a NuminaMath eval set instead of FormalStep.

Prompt construction is deliberately identical in SHAPE to the committed runs:
prefix-completion, our pinned GOEDEL_LEAN4_HEADER, ending mid-fence right after
the theorem statement so the model writes only the tactic block.

One difference from FormalStep, and it is in the data, not the code: NuminaMath
statements already carry the informal problem text as a `/- ... -/` doc comment
above the theorem, which is exactly the slot FormalStep's `current_step` filled.
So the informal prefix is taken from the row rather than injected.
"""
import argparse, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import GOEDEL_LEAN4_HEADER, PROMPT_TEMPLATE, MODEL_NAME
from prompting import extract_lean4_block
from model import GoedelProver

_IMPORT = re.compile(r"^[ \t]*import[ \t]+[\w.]+[ \t]*$", re.M)


def build_prompt(row):
    """Our header + their (doc-comment + theorem). Ends mid-fence by design."""
    body = _IMPORT.sub("", row["statement"]).lstrip()
    return PROMPT_TEMPLATE.format(header=GOEDEL_LEAN4_HEADER,
                                  informal_prefix="", formal_statement=body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evalset", default="stage_b_evalset.json")
    ap.add_argument("--out", default="stage_b_traces.jsonl")
    ap.add_argument("--temp", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rows = json.load(open(args.evalset, encoding="utf-8"))
    print(f"{len(rows)} problems  |  temp={args.temp}  seed={args.seed}", flush=True)

    done = set()
    if os.path.exists(args.out):
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                done.add(json.loads(l)["uuid"])
        print(f"resuming: {len(done)} already generated", flush=True)

    prover = GoedelProver(MODEL_NAME)
    t0 = time.perf_counter()

    with open(args.out, "a", encoding="utf-8") as fh:
        for i, r in enumerate(rows, 1):
            if r["uuid"] in done:
                continue
            prompt = build_prompt(r)
            t = time.perf_counter()
            # generate() returns a LIST of trajectory dicts; one trajectory here.
            gen = prover.generate(prompt, temperature=args.temp,
                                  num_trajectories=1, seed=args.seed)[0]
            completion = gen["text"]
            full = extract_lean4_block(prompt, completion)
            rec = {
                "uuid": r["uuid"], "band": r["band"], "wr": r["wr"],
                "source": r["source"], "binder_fixes": r["binder_fixes"],
                "formal_statement": r["statement"],
                "prompt": prompt, "raw_output": completion,
                "full_code": full,
                "extract_status": "ok" if full else "no_fence",
                "seconds": round(gen.get("seconds", time.perf_counter() - t), 2),
                "temperature": args.temp, "seed": args.seed,
                "model": MODEL_NAME,
            }
            for k in ("generated_tokens", "truncated", "hit_token_limit",
                      "stopped_on_eos", "prompt_tokens", "closed_fence",
                      "max_new_tokens"):
                if k in gen:
                    rec[k] = gen[k]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush(); os.fsync(fh.fileno())
            print(f"  [{i:>3}/{len(rows)}] {r['band']:<7} {rec['seconds']:>6.1f}s "
                  f"{'ok' if full else 'NO-FENCE'}", flush=True)

    el = time.perf_counter() - t0
    print(f"\ndone in {el/60:.1f} min -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
