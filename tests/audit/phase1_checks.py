"""Phase 1 kill-gate checks. Reads only committed artifacts. No Lean, no GPU."""
import io, json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def jl(p):
    with io.open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

RUNS = {"0.0": "traces/temp0.0_n50_1each/traces.jsonl",
        "0.2": "traces/temp0.2_n50_1each/traces.jsonl"}
VER  = {"0.0": "results/verify2_temp0.0.jsonl", "0.2": "results/verify2_temp0.2.jsonl"}

DECL = re.compile(r"^[ \t]*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+|noncomputable\s+)*"
                  r"(?:theorem|lemma|example)\b", re.M)
HATCH = {
    "sorry":            re.compile(r"\bsorry\b"),
    "admit":            re.compile(r"\badmit\b"),
    "axiom_decl":       re.compile(r"^\s*axiom\s+", re.M),
    "native_decide":    re.compile(r"\bnative_decide\b"),
    "implemented_by":   re.compile(r"@\[implemented_by"),
    "decide":           re.compile(r"\bdecide\b"),
    "unsafe":           re.compile(r"^\s*unsafe\s+", re.M),
    "macro_rules":      re.compile(r"\bmacro_rules\b"),
}
SETOPT = re.compile(r"^\s*set_option\s+(\S+)\s+(\S+)", re.M)
# Options present in the prompt header itself; anything else was added by the model.
HEADER_OPTS = {"maxHeartbeats"}

def strip_comments(s):
    s = re.sub(r"/-.*?-/", "", s, flags=re.S)
    return re.sub(r"--[^\n]*", "", s)

def norm(s):
    """Whitespace-insensitive normalisation for statement comparison."""
    return re.sub(r"\s+", " ", (s or "")).strip()

out = {}
for T, path in RUNS.items():
    traces = {r["sample_index"]: r for r in jl(path)}
    vers   = {r["sample_index"]: r for r in jl(VER[T])}
    res = {"n_traces": len(traces), "n_verified": len(vers)}

    # ---- 1. statement fidelity -------------------------------------------
    fid = {"stmt_verbatim_in_full_code": 0, "stmt_missing": [], "multi_decl": [],
           "decl_counts": {}, "no_full_code": []}
    for i, r in sorted(traces.items()):
        fc = r.get("full_code") or ""
        if not r.get("full_code"):
            fid["no_full_code"].append(i)
        stmt = r.get("formal_statement") or ""
        if norm(stmt) and norm(stmt) in norm(fc):
            fid["stmt_verbatim_in_full_code"] += 1
        else:
            fid["stmt_missing"].append(i)
        nd = len(DECL.findall(strip_comments(fc)))
        fid["decl_counts"][nd] = fid["decl_counts"].get(nd, 0) + 1
        if nd != 1:
            fid["multi_decl"].append((i, nd))
    res["fidelity"] = fid

    # ---- 2. escape hatches ------------------------------------------------
    hatch = {k: [] for k in HATCH}
    hatch_incomment = {k: [] for k in HATCH}
    model_opts = {}
    for i, r in sorted(traces.items()):
        fc = r.get("full_code") or ""
        code = strip_comments(fc)
        for k, rx in HATCH.items():
            if rx.search(code):
                hatch[k].append(i)
            elif rx.search(fc):
                hatch_incomment[k].append(i)
        for name, val in SETOPT.findall(code):
            if name not in HEADER_OPTS:
                model_opts.setdefault(f"{name} {val}", []).append(i)
    res["escape_hatches"] = {k: v for k, v in hatch.items() if v}
    res["escape_hatches_comment_only"] = {k: v for k, v in hatch_incomment.items() if v}
    res["model_added_set_options"] = model_opts

    # ---- 3. truncation ----------------------------------------------------
    tr = {"truncated_true": [], "hit_token_limit": [], "closed_fence_false": [],
          "stopped_on_eos_false": [], "extract_status": {}}
    for i, r in sorted(traces.items()):
        if r.get("truncated"):            tr["truncated_true"].append(i)
        if r.get("hit_token_limit"):      tr["hit_token_limit"].append(i)
        if r.get("closed_fence") is False:tr["closed_fence_false"].append(i)
        if r.get("stopped_on_eos") is False: tr["stopped_on_eos_false"].append(i)
        st = r.get("extract_status")
        tr["extract_status"][st] = tr["extract_status"].get(st, 0) + 1
    # what outcome did the truncated ones receive?
    tr["outcome_of_truncated"] = {i: vers[i]["outcome"] for i in tr["truncated_true"] if i in vers}
    tr["outcome_of_token_limited"] = {i: vers[i]["outcome"] for i in tr["hit_token_limit"] if i in vers}
    res["truncation"] = tr

    # ---- 4. token budget --------------------------------------------------
    gt = [r.get("generated_tokens") or 0 for r in traces.values()]
    pt = [r.get("prompt_tokens") or 0 for r in traces.values()]
    res["tokens"] = {"max_generated": max(gt), "mean_generated": round(sum(gt)/len(gt), 1),
                     "max_prompt": max(pt), "max_new_tokens_setting":
                     sorted({r.get("max_new_tokens") for r in traces.values()})}

    # ---- 5. verification timing / modes ----------------------------------
    secs = [v.get("seconds") or 0 for v in vers.values()]
    modes, outcomes = {}, {}
    for v in vers.values():
        modes[v.get("mode")] = modes.get(v.get("mode"), 0) + 1
        outcomes[v["outcome"]] = outcomes.get(v["outcome"], 0) + 1
    res["timing"] = {"total_seconds": round(sum(secs), 1), "mean": round(sum(secs)/len(secs), 3),
                     "min": min(secs), "max": max(secs),
                     "under_0.05s": sum(1 for s in secs if s < 0.05)}
    res["modes"] = modes
    res["outcomes"] = outcomes
    out[T] = res

print(json.dumps(out, indent=2, ensure_ascii=False))
