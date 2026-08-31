"""Generation driver for the three GPU tactic-recovery experiments.

GPU only. No Lean here -- verification is a separate, CPU-only step, so the
instance can be terminated the moment the last generation lands.

Covers the two runs the committed CLI cannot express:

  exp2-stageb   k samples per NuminaMath problem at T>0. `stage_b_generate.py`
                does one trajectory per problem and writes no run_meta.json.
  exp3          one error-feedback repair attempt per `tactic_mismatch`
                failure, on exactly the set the tactic oracle ran on.

Experiment 1 (doc-comment ablation) and experiment 2 on FormalStep need no new
code: they are `trace_valid.py generate` with --no-informal / --num-trajectories.

PROMPT SHAPE. exp2-stageb reuses stage_b_generate.build_prompt verbatim, so its
prompts are byte-identical to the committed Stage B runs. exp3 necessarily uses
a NEW prompt shape -- it has to show the model its own failure and Lean's
complaint -- and it is assembled FROM the pinned constants, never by editing
them. Repair numbers are therefore reported as their own row and are not
comparable with one-shot numbers. That separation is the point of the
experiment, not a caveat on it.
"""
import argparse
import io
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import (GOEDEL_LEAN4_HEADER, PROMPT_TEMPLATE, MODEL_NAME, TOP_P,
                    LEAN4_BLOCK_PATTERN)
from prompting import build_informal_prefix, extract_lean4_block
from generate import git_state, environment_state, sha256_file

import stage_b_generate as sbg
import tactic_common as tc


# --------------------------------------------------------------------------- #
# run_meta.json -- non-negotiable. A run without its seed and its generating
# commit cannot be attributed to a code state, which is the exact provenance
# hole this repo has already been burned by.
# --------------------------------------------------------------------------- #
def write_meta(out_path, meta, status="running", extra=None):
    meta = dict(meta, status=status)
    if extra:
        meta.update(extra)
    path = os.path.splitext(out_path)[0] + ".run_meta.json"
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def base_meta(experiment, temp, seed, k, n_items, out_path, prompt_shape):
    return {
        "schema_version": 1,
        "experiment": experiment,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "finished_utc": None,
        "command": " ".join(sys.argv),
        "git": git_state(),
        "model": {"name": MODEL_NAME},
        "sampling": {
            "temperature": temp,
            "do_sample": temp > 0.0,
            "top_p": TOP_P if temp > 0.0 else None,
            "seed": seed,
            "samples_per_item": k,
            "n_items": n_items,
        },
        "prompt": prompt_shape,
        "environment": environment_state(),
        "output": {
            "traces": os.path.basename(out_path),
            "records_written": 0,
            "sha256": None,
            "elapsed_seconds": None,
        },
    }


def emit(fh, rec):
    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fh.flush()
    os.fsync(fh.fileno())


def finish(out_path, meta, written, t0):
    write_meta(out_path, meta, status="complete", extra={
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "output": dict(meta["output"], records_written=written,
                       sha256=sha256_file(out_path),
                       elapsed_seconds=round(time.perf_counter() - t0, 1)),
    })
    print("\n[done] %d records in %.1f min -> %s"
          % (written, (time.perf_counter() - t0) / 60, out_path), flush=True)


# --------------------------------------------------------------------------- #
# Experiment 2, Stage B: k samples per problem
# --------------------------------------------------------------------------- #
def cmd_exp2_stageb(args):
    rows = json.load(io.open(args.evalset, encoding="utf-8"))
    out = args.out
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    # Resume is keyed on (uuid, sample_index) so an interrupted run never
    # regenerates a sample it already has, and never double-counts one.
    done = set()
    if os.path.exists(out):
        for line in io.open(out, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                done.add((r["uuid"], r["sample_index"]))
        print("resuming: %d samples already present" % len(done), flush=True)

    meta = base_meta("exp2_stageb", args.temp, args.seed, args.k, len(rows), out,
                     {"shape": "stage_b_generate.build_prompt (verbatim)",
                      "informal_prefix": "carried in the NuminaMath statement itself",
                      "template": "config.PROMPT_TEMPLATE (verbatim upstream)"})
    print("[meta] " + write_meta(out, meta), flush=True)

    prover = sbg.GoedelProver(MODEL_NAME)
    t0 = time.perf_counter()
    written = 0
    with io.open(out, "a", encoding="utf-8") as fh:
        for i, r in enumerate(rows, 1):
            want = [j for j in range(args.k) if (r["uuid"], j) not in done]
            if not want:
                continue
            prompt = sbg.build_prompt(r)
            # One generate() call returns len(want) trajectories from a single
            # batched forward pass. The seed is per-problem, so the k samples of
            # a problem reproduce independently of iteration order.
            gens = prover.generate(prompt, temperature=args.temp,
                                   num_trajectories=len(want),
                                   batch=min(args.batch, len(want)),
                                   seed=args.seed + i * 1000)
            n_ok = 0
            for j, gen in zip(want, gens):
                full = extract_lean4_block(prompt, gen["text"])
                n_ok += bool(full)
                rec = {"uuid": r["uuid"], "sample_index": j, "band": r["band"],
                       "wr": r["wr"], "source": r["source"],
                       "binder_fixes": r["binder_fixes"],
                       "formal_statement": r["statement"], "prompt": prompt,
                       "raw_output": gen["text"], "full_code": full,
                       "extract_status": "ok" if full else "no_fence",
                       "temperature": args.temp, "top_p": TOP_P,
                       "seed": args.seed + i * 1000, "model": MODEL_NAME,
                       "experiment": "exp2_stageb"}
                for kk in ("generated_tokens", "truncated", "hit_token_limit",
                           "stopped_on_eos", "prompt_tokens", "closed_fence",
                           "max_new_tokens", "seconds"):
                    if kk in gen:
                        rec[kk] = gen[kk]
                emit(fh, rec)
                written += 1
            print("  [%3d/%d] %-7s %2d/%2d fenced  %.1fs"
                  % (i, len(rows), r["band"], n_ok, len(want),
                     gens[0].get("batch_seconds", 0.0)), flush=True)
    finish(out, meta, written, t0)


# --------------------------------------------------------------------------- #
# Experiment 3: one error-feedback repair attempt
# --------------------------------------------------------------------------- #
# The original prompt, the model's failed attempt, and Lean's error verbatim.
# Nothing else -- no hints, no tactic suggestions, no mention of what to try.
#
# The model is a prefix-completion prover, not a chat model: every prompt it has
# ever seen ends mid-fence, immediately after a statement. So the repair prompt
# closes the failed attempt's fence, states the error, and then re-opens the
# ORIGINAL prompt verbatim. The model's continuation therefore begins in exactly
# the position it was trained on, and extract_lean4_block picks up the last
# fence, which is the retry.
REPAIR_TEMPLATE = (
    "{original_prompt}{failed_body}\n```\n\n"
    "The proof above failed. Lean reported:\n\n"
    "{lean_error}\n\n"
    "Complete the following Lean 4 code with explanatory comments preceding "
    "each line of code:\n\n```lean4\n{header}{informal_prefix}{formal_statement}"
)

# Lean prints the full goal state on `unsolved goals`, which on a Finset
# statement can run to thousands of characters and crowd the 4096-token window.
# Truncating the MIDDLE keeps the first line (which names the failing tactic)
# and the tail (which names the goal), the two parts the model needs.
MAX_ERROR_CHARS = 1800


def clip_error(text):
    text = (text or "").strip()
    if len(text) <= MAX_ERROR_CHARS:
        return text, False
    head = text[: MAX_ERROR_CHARS * 2 // 3]
    tail = text[-(MAX_ERROR_CHARS // 3):]
    return head + "\n...\n" + tail, True


# --------------------------------------------------------------------------- #
# Extraction for the repair prompt
# --------------------------------------------------------------------------- #
# prompting.extract_lean4_block uses re.search, which returns the FIRST fenced
# block. Every one-shot prompt opens exactly one fence, so first == last there
# and it is correct. The repair prompt opens TWO: the failed attempt is quoted
# back inside a closed fence, and the original prompt is then re-opened for the
# retry. First-match extraction therefore recovers the FAILED PROOF, and the
# retry is silently discarded -- which reads as "the model reproduced its own
# proof 104/104 times" when in fact it wrote a new one every time.
#
# The retry is always the LAST complete block.
def extract_last_lean4_block(prompt, completion):
    blocks = re.findall(LEAN4_BLOCK_PATTERN, prompt + completion, re.DOTALL)
    return blocks[-1] if blocks else None


def build_repair_prompt(sample):
    """Assembled from the pinned constants; neither is modified.

    `original_prompt` is rebuilt rather than read back, because the FormalStep
    and Stage B trace files store it under different shapes. Both pipelines
    render through config.PROMPT_TEMPLATE, so rebuilding reproduces it.
    """
    stmt = sample["repair_statement"]
    informal = sample.get("repair_informal") or ""
    original = PROMPT_TEMPLATE.format(header=GOEDEL_LEAN4_HEADER,
                                      informal_prefix=informal,
                                      formal_statement=stmt)
    err, clipped = clip_error(sample["lean_error_joined"])
    prompt = REPAIR_TEMPLATE.format(
        original_prompt=original,
        failed_body=sample["body"] or "",
        lean_error=err or "(no error text recorded)",
        header=GOEDEL_LEAN4_HEADER,
        informal_prefix=informal,
        formal_statement=stmt,
    )
    return prompt, original, clipped


def load_repair_set():
    """The `tactic_mismatch` failures, joined to the Lean error each produced.

    Deliberately the SAME assembly the tactic oracle used
    (tactic_common.load_samples + attach_lean_errors), so repair and oracle are
    measured on one identical set and the two ceilings are comparable.
    """
    samples = tc.load_samples(_ROOT, label="tactic_mismatch")
    tc.attach_lean_errors(samples, _ROOT)
    ver = tc.load_verification(_ROOT)

    fs_traces = {
        "formalStep_baseline_50step_1problem":
            {r["sample_index"]: r
             for r in tc.J(os.path.join(_ROOT, "traces/temp_0.jsonl"))},
        "formalStep_n50_distinct_T0.0":
            {r["sample_index"]: r
             for r in tc.J(os.path.join(_ROOT, "traces/temp0.0_n50_1each/traces.jsonl"))},
        "formalStep_n50_distinct_T0.2":
            {r["sample_index"]: r
             for r in tc.J(os.path.join(_ROOT, "traces/temp0.2_n50_1each/traces.jsonl"))},
    }
    for s in samples:
        v = ver.get(s["set"], {}).get(s["id"], {})
        errs = v.get("errors") or []
        # FormalStep re-renders the doc comment from `current_step`; Stage B
        # carries the informal text inside the statement already, so its
        # informal_prefix slot stays empty -- exactly as the committed runs.
        if s["pipeline"] == "FormalStep":
            tr = fs_traces[s["set"]].get(s["id"], {})
            s["repair_informal"] = build_informal_prefix(tr.get("informal_step"))
            s["repair_statement"] = tr.get("formal_statement", "")
        else:
            s["repair_informal"] = ""
            s["repair_statement"] = sbg._IMPORT.sub("", s["formal_statement"]).lstrip()
        s["lean_errors"] = errs
        s["lean_error_joined"] = "\n\n".join(str(e) for e in errs)
    return samples


def cmd_exp3(args):
    samples = load_repair_set()
    out = args.out
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    def key(s):
        return "%s|%s" % (s["set"], s["id"])

    done = set()
    if os.path.exists(out):
        for line in io.open(out, encoding="utf-8"):
            if line.strip():
                done.add(json.loads(line)["repair_key"])
        print("resuming: %d already present" % len(done), flush=True)

    n_err = sum(1 for s in samples if s["lean_errors"])
    print("%d tactic_mismatch failures; %d carry recorded Lean errors"
          % (len(samples), n_err), flush=True)

    meta = base_meta("exp3_repair", args.temp, args.seed, 1, len(samples), out,
                     {"shape": "REPAIR_TEMPLATE: original prompt + failed attempt "
                               "+ Lean error verbatim, then the original prompt again",
                      "assembled_from": "config.PROMPT_TEMPLATE and "
                                        "GOEDEL_LEAN4_HEADER, both unmodified",
                      "max_error_chars": MAX_ERROR_CHARS,
                      "comparable_with_one_shot": False})
    print("[meta] " + write_meta(out, meta), flush=True)

    prover = sbg.GoedelProver(MODEL_NAME)
    t0 = time.perf_counter()
    written = 0
    with io.open(out, "a", encoding="utf-8") as fh:
        for i, s in enumerate(samples, 1):
            if key(s) in done:
                continue
            prompt, original, clipped = build_repair_prompt(s)
            gen = prover.generate(prompt, temperature=args.temp,
                                  num_trajectories=1,
                                  seed=args.seed + i * 1000)[0]
            full = extract_last_lean4_block(prompt, gen["text"])
            rec = {"repair_key": key(s), "set": s["set"], "pipeline": s["pipeline"],
                   "id": s["id"], "band": s.get("band"),
                   "original_outcome": s["outcome"], "label": "tactic_mismatch",
                   "lean_tactic": s.get("lean_tactic"),
                   "lean_kind": s.get("lean_kind"),
                   "n_lean_errors": len(s["lean_errors"]),
                   "had_error_text": bool(s["lean_errors"]),
                   "error_clipped": clipped,
                   "formal_statement": s["repair_statement"],
                   "failed_body": s["body"], "original_prompt": original,
                   "prompt": prompt, "raw_output": gen["text"],
                   "full_code": full,
                   "extract_status": "ok" if full else "no_fence",
                   "temperature": args.temp,
                   "top_p": TOP_P if args.temp > 0 else None,
                   "seed": args.seed + i * 1000, "model": MODEL_NAME,
                   "experiment": "exp3_repair"}
            for kk in ("generated_tokens", "truncated", "hit_token_limit",
                       "stopped_on_eos", "prompt_tokens", "closed_fence",
                       "max_new_tokens", "seconds"):
                if kk in gen:
                    rec[kk] = gen[kk]
            emit(fh, rec)
            written += 1
            print("  [%3d/%d] %-30s %-10s %5.1fs %s"
                  % (i, len(samples), s["set"][:30],
                     str(s.get("lean_tactic"))[:10],
                     gen.get("seconds", 0.0), "ok" if full else "NO-FENCE"),
                  flush=True)
    finish(out, meta, written, t0)


# --------------------------------------------------------------------------- #
def cmd_dry(args):
    samples = load_repair_set()
    print("repair set: %d samples" % len(samples))
    by_set = {}
    for s in samples:
        by_set[s["set"]] = by_set.get(s["set"], 0) + 1
    for k, v in sorted(by_set.items()):
        print("  %-40s %3d" % (k, v))
    print("  with recorded Lean error text: %d/%d"
          % (sum(1 for s in samples if s["lean_errors"]), len(samples)))
    n_clip = sum(1 for s in samples if clip_error(s["lean_error_joined"])[1])
    print("  error text clipped to %d chars: %d" % (MAX_ERROR_CHARS, n_clip))
    for s in samples[:args.n]:
        p, _, _ = build_repair_prompt(s)
        print("\n" + "=" * 78)
        print("%s  id=%s  lean_tactic=%s  prompt_chars=%d"
              % (s["set"], s["id"], s.get("lean_tactic"), len(p)))
        print("=" * 78)
        print(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("exp2-stageb")
    a.add_argument("--evalset",
                   default=os.path.join(_ROOT, "results/stage_b_evalset.json"))
    a.add_argument("--out",
                   default=os.path.join(_ROOT, "results/exp2_stageb_k16.jsonl"))
    a.add_argument("--temp", type=float, default=0.7)
    a.add_argument("--k", type=int, default=16)
    a.add_argument("--batch", type=int, default=16)
    a.add_argument("--seed", type=int, required=True)
    a.set_defaults(fn=cmd_exp2_stageb)

    b = sub.add_parser("exp3")
    b.add_argument("--out", default=os.path.join(_ROOT, "results/exp3_repair.jsonl"))
    b.add_argument("--temp", type=float, default=0.0)
    b.add_argument("--seed", type=int, required=True)
    b.set_defaults(fn=cmd_exp3)

    c = sub.add_parser("dry-run", help="Render prompts; load no model.")
    c.add_argument("--n", type=int, default=1)
    c.set_defaults(fn=cmd_dry)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
