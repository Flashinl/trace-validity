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

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
# Repo root too: this script imports config/prompting/model from the top
# level, and sys.path[0] is the SCRIPT's directory, not the cwd. Running
# it as `python3 tests/audit/stage_b_generate.py` from the repo root died
# with ModuleNotFoundError: No module named 'config'.
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
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
    ap.add_argument("--evalset", default="results/stage_b_evalset.json")
    # One file per temperature. `{temp}` is substituted; keeping the runs in
    # separate files is what makes the uuid-keyed resume below correct.
    ap.add_argument("--out", default="results/stage_b_traces_temp{temp}.jsonl")
    # nargs="+": every temperature runs inside ONE process, so the ~7B model is
    # loaded once for the whole sweep instead of once per temperature.
    ap.add_argument("--temp", type=float, nargs="+", default=[0.0])
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rows = json.load(open(args.evalset, encoding="utf-8"))
    temps = list(args.temp)
    print(f"{len(rows)} problems  |  temps={temps}  seed={args.seed}", flush=True)

    # Load the model ONCE, before the temperature loop.
    prover = GoedelProver(MODEL_NAME)
    t_all = time.perf_counter()

    for temp in temps:
        out_path = args.out.format(temp=temp)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        run_one(prover, rows, temp, args.seed, out_path)

    print(f"\nsweep done in {(time.perf_counter()-t_all)/60:.1f} min", flush=True)


def run_one(prover, rows, temp, seed, out_path):
    """One temperature -> one file. Resume is keyed on uuid WITHIN this file."""
    print(f"\n=== temp={temp} seed={seed} -> {out_path} ===", flush=True)

    done = set()
    if os.path.exists(out_path):
        for l in open(out_path, encoding="utf-8"):
            if l.strip():
                rec = json.loads(l)
                # Guard the invariant the filename asserts: if a file ever ends
                # up holding a different temperature, stop rather than resume
                # against records that are not comparable.
                if float(rec.get("temperature", temp)) != float(temp):
                    raise SystemExit(
                        f"{out_path} holds temperature {rec.get('temperature')} "
                        f"but this run is temp={temp}; refusing to append.")
                done.add(rec["uuid"])
        print(f"resuming: {len(done)} already generated", flush=True)

    args_temp, args_seed = temp, seed
    t0 = time.perf_counter()

    with open(out_path, "a", encoding="utf-8") as fh:
        for i, r in enumerate(rows, 1):
            if r["uuid"] in done:
                continue
            prompt = build_prompt(r)
            t = time.perf_counter()
            # generate() returns a LIST of trajectory dicts; one trajectory here.
            gen = prover.generate(prompt, temperature=args_temp,
                                  num_trajectories=1, seed=args_seed)[0]
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
                "temperature": args_temp, "seed": args_seed,
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
    print(f"done in {el/60:.1f} min -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
