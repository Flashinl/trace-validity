"""Validate vLLM against the committed HF-transformers baseline before adopting it.

Unbatched HF generation at ~7.12 s/prompt over 18,130 distinct prompts is the
entire reason the full run projects to 36 h. vLLM would cut that by ~10x, but
every committed result in this repo rests on HF transformers output, so vLLM is
only adoptable if it reproduces that output.

WHAT THIS COMPARES
  the committed `traces/temp0.0_n50_1each/traces.jsonl` (HF, greedy, fp16, n=50)
  against the same 50 prompts regenerated through vLLM under matched settings.

THREE BUCKETS, as asked:
  identical   byte-identical generated text
  same_verdict different text, same Lean outcome
  FLIPPED     different Lean outcome  <-- any of these stops adoption

FOUR THINGS THAT WOULD SILENTLY INVALIDATE THIS COMPARISON, all controlled here:

  1. dtype. `config.json` declares `torch_dtype: bfloat16`, but the committed
     baseline loads `dtype=torch.float16` (model.py:66). vLLM's default
     `dtype="auto"` reads the CONFIG and would load bfloat16 -- a different
     numeric format, not just different kernels. We pin `dtype="float16"`.
  2. The chat template. This tokenizer HAS a `chat_template`. The prompt is
     prefix-completion: it opens a ```lean4 fence and ends mid-fence after
     `:= by\\n` with no closing fence. Any path that applies the template
     destroys it. We use `LLM.generate()` with raw strings, never `LLM.chat()`,
     and assert the token ids match the HF tokenizer's.
  3. BOS. `add_bos_token: true`. Both paths must add exactly one BOS. Asserted.
  4. vLLM self-determinism. Continuous batching means batch composition varies
     between runs and some kernels are not batch-invariant, so vLLM can differ
     from ITSELF even at greedy. `--self-check` runs it twice and compares. If
     vLLM is not stable against itself, a 50/50 match against HF is luck, not a
     property.

Sampling seeds are NOT compared: vLLM's RNG differs from HF's, so T>0 will not
reproduce the k16 run by construction. Greedy is the only fair comparison, which
is what the baseline used (`do_sample: false`, `greedy_deterministic: true`).

Run on the GPU box (needs ~14 GiB VRAM for 7B fp16):
  python tests/audit/vllm_equivalence.py --stage generate
  python tests/audit/vllm_equivalence.py --stage compare      # + Lean verify
"""
import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

BASELINE = "traces/temp0.0_n50_1each/traces.jsonl"
OUT = "results/vllm_n50_temp0.0.jsonl"
MODEL = "Goedel-LM/Goedel-Prover-SFT"
MAX_NEW = 2048

J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]
P = print


def load_baseline():
    rows = {r["sample_index"]: r for r in J(os.path.join(_ROOT, BASELINE))}
    P(f"  baseline: {len(rows)} records from {BASELINE}")
    return rows


# --------------------------------------------------------------------------- #
# Pre-flight: prove the prompt survives vLLM's tokenisation unchanged
# --------------------------------------------------------------------------- #
def preflight(prompts):
    """Assert vLLM will see exactly the tokens HF saw. Runs before any GPU work."""
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)

    P("\n  PRE-FLIGHT")
    P(f"    tokenizer has chat_template : {tok.chat_template is not None}")
    if tok.chat_template is not None:
        P("      -> present, so LLM.chat() / apply_chat_template MUST NOT be used.")

    p0 = prompts[0]
    P(f"    prompt ends with closing fence: {p0.rstrip().endswith('```')}  (must be False)")
    assert not p0.rstrip().endswith("```"), "prompt has a closing fence; not prefix-completion"
    assert "```lean4" in p0, "prompt lost its opening fence"
    assert p0.rstrip().endswith(":= by") or p0.endswith(":= by\n"), \
        f"prompt does not end mid-fence after ':= by': {p0[-40:]!r}"

    ids_plain = tok(p0)["input_ids"]
    bos = tok.bos_token_id
    P(f"    add_bos_token={tok.add_bos_token}  first id={ids_plain[0]}  bos_id={bos}")
    assert ids_plain[0] == bos, "HF tokenisation did not prepend BOS"

    # What a chat template WOULD do, shown so the difference is on the record.
    try:
        chat_ids = tok.apply_chat_template([{"role": "user", "content": p0}],
                                           tokenize=True, add_generation_prompt=True)
        P(f"    len(plain ids)={len(ids_plain)}   len(chat-templated ids)={len(chat_ids)}"
          f"   -> differ by {len(chat_ids)-len(ids_plain)} tokens")
        assert chat_ids != ids_plain, "chat template is a no-op here (unexpected)"
    except Exception as e:  # noqa: BLE001
        P(f"    (chat template probe skipped: {type(e).__name__})")
    P("    PRE-FLIGHT OK\n")
    return tok


# --------------------------------------------------------------------------- #
# Generation through vLLM
# --------------------------------------------------------------------------- #
def stage_generate(args):
    base = load_baseline()
    order = sorted(base)
    prompts = [base[i]["prompt"] for i in order]
    tok = preflight(prompts)

    from vllm import LLM, SamplingParams
    P("  constructing LLM("
      f"dtype='float16', enforce_eager={args.enforce_eager}, seed=0) ...")
    llm = LLM(model=MODEL,
              dtype="float16",              # MATCH model.py:66, NOT config's bfloat16
              trust_remote_code=True,
              enforce_eager=args.enforce_eager,
              gpu_memory_utilization=args.gpu_mem,
              max_model_len=4096,
              seed=0)

    # Assert vLLM tokenises identically to HF -- this is the chat-template guard.
    vtok = llm.get_tokenizer()
    a, b = vtok(prompts[0])["input_ids"], tok(prompts[0])["input_ids"]
    assert a == b, ("vLLM tokenised the prompt differently from HF "
                    f"({len(a)} vs {len(b)} tokens) -- a template is being applied")
    P("    vLLM tokenisation == HF tokenisation  OK")

    sp = SamplingParams(temperature=0.0, top_p=1.0, max_tokens=MAX_NEW, seed=0)
    outs = llm.generate(prompts, sp)          # raw strings; never llm.chat()

    from prompting import extract_lean4_block
    recs = []
    for idx, o in zip(order, outs):
        text = o.outputs[0].text
        parsed, status = _extract(extract_lean4_block, base[idx]["prompt"], text)
        recs.append({
            "sample_index": idx,
            "problem_unique_id": base[idx].get("problem_unique_id"),
            "engine": "vllm", "dtype": "float16", "temperature": 0.0,
            "trajectory_index": 0,
            "raw_output": text,
            "parsed_code": parsed,
            "extract_status": status,
            "finish_reason": o.outputs[0].finish_reason,
            "generated_tokens": len(o.outputs[0].token_ids),
            "enforce_eager": args.enforce_eager,
        })
    dest = os.path.join(_ROOT, args.out)
    with io.open(dest, "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    P(f"  wrote {dest} ({len(recs)} records)")

    if args.self_check:
        P("\n  SELF-CHECK: second identical vLLM pass (batch-invariance)")
        outs2 = llm.generate(prompts, sp)
        same = sum(1 for o1, o2 in zip(outs, outs2)
                   if o1.outputs[0].text == o2.outputs[0].text)
        P(f"    vLLM vs vLLM identical text: {same}/{len(prompts)}")
        if same != len(prompts):
            P("    *** vLLM IS NOT DETERMINISTIC AGAINST ITSELF. A match against HF "
              "would be luck, not a property. Re-run with --enforce-eager. ***")


def _extract(fn, prompt, completion):
    try:
        r = fn(prompt, completion)
        if isinstance(r, tuple):
            return r[0], (r[1] if len(r) > 1 else "extracted")
        return r, "extracted"
    except Exception as e:  # noqa: BLE001
        return None, f"extract_error:{type(e).__name__}"


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #
def stage_compare(args):
    base = load_baseline()
    vl = {r["sample_index"]: r for r in J(os.path.join(_ROOT, args.out))}
    common = sorted(set(base) & set(vl))
    P(f"  comparing {len(common)} samples\n")

    identical = [i for i in common if base[i]["raw_output"] == vl[i]["raw_output"]]
    P(f"  TEXT identical           : {len(identical)}/{len(common)}")
    differing = [i for i in common if i not in set(identical)]
    P(f"  TEXT differs             : {len(differing)}/{len(common)}")

    # Verdicts. Baseline verdicts come from the committed verification; vLLM
    # outputs must be verified now, with the same pinned Lean toolchain.
    hf_ver = {r["sample_index"]: r for r in
              J(os.path.join(_ROOT, "results/verify3_temp0.0.jsonl"))}
    if args.verify:
        from verifier import LeanVerifier
        v = LeanVerifier(setup=False, verbose=False)
        vl_out = {}
        for i in common:
            code = vl[i].get("parsed_code") or ""
            vl_out[i] = v.verify(code, timeout=args.timeout)["outcome"]
        io.open(os.path.join(_ROOT, "results/vllm_n50_verdicts.json"), "w",
                encoding="utf-8").write(json.dumps(vl_out, indent=1))
    else:
        vp = os.path.join(_ROOT, "results/vllm_n50_verdicts.json")
        vl_out = {int(k): x for k, x in json.load(io.open(vp, encoding="utf-8")).items()}

    same_verdict, flipped = [], []
    for i in common:
        if hf_ver[i]["outcome"] == vl_out[i]:
            same_verdict.append(i)
        else:
            flipped.append(i)

    P(f"\n  VERDICT same             : {len(same_verdict)}/{len(common)}")
    P(f"  VERDICT FLIPPED          : {len(flipped)}/{len(common)}")

    P("\n  the three buckets asked for:")
    b1 = len(identical)
    b2 = len([i for i in differing if i in set(same_verdict)])
    b3 = len(flipped)
    P(f"    identical text                       {b1}/{len(common)}")
    P(f"    different text, SAME verdict         {b2}/{len(common)}")
    P(f"    FLIPPED verdict                      {b3}/{len(common)}")
    assert b1 + b2 + b3 == len(common), "buckets do not partition the sample"

    if flipped:
        P("\n  *** STOP: verdicts flipped. Do NOT adopt vLLM. ***")
        for i in flipped:
            P(f"    sample {i}: HF={hf_ver[i]['outcome']} vLLM={vl_out[i]}")
    else:
        from stats import wilson
        lo, hi = wilson(len(common), len(common))
        P(f"\n  no flips. Agreement {len(common)}/{len(common)}, "
          f"95% CI [{100*lo:.1f}-{100*hi:.1f}]%.")
        P("  NOTE n=50 bounds the true divergence rate at roughly "
          f"{100*(1-lo):.1f}% upper, not 0. 50/50 is necessary, not sufficient,")
        P("  evidence; it does not prove equivalence over 18,130 prompts.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("generate", "compare", "preflight"),
                    required=True)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--enforce-eager", action="store_true", default=True)
    ap.add_argument("--gpu-mem", type=float, default=0.90)
    ap.add_argument("--self-check", action="store_true", default=True)
    ap.add_argument("--verify", action="store_true", default=True)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    P("=" * 78)
    P(f"vLLM EQUIVALENCE, stage={args.stage}")
    P("=" * 78)
    if args.stage == "preflight":
        preflight([r["prompt"] for r in J(os.path.join(_ROOT, BASELINE))])
    elif args.stage == "generate":
        stage_generate(args)
    else:
        stage_compare(args)


if __name__ == "__main__":
    main()
