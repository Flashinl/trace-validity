"""Phase 2: could the PIPELINE have manufactured the false numbers?

Three ways it could, each checked here. Reads only committed artifacts.
Run: python tests/audit/pipeline_checks.py
"""
import io, json, re, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]

SETS = [("baseline", "traces/temp_0.jsonl"),
        ("n50 T=0.0", "traces/temp0.0_n50_1each/traces.jsonl"),
        ("n50 T=0.2", "traces/temp0.2_n50_1each/traces.jsonl")]

DECL = re.compile(r"^[ \t]*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+|noncomputable\s+)*"
                  r"(?:theorem|lemma|example)\b", re.M)
LIT = re.compile(r"(?<![\w.])\d{4,}(?![\w.])")
norm = lambda s: re.sub(r"\s+", " ", (s or "")).strip()
sc = lambda s: re.sub(r"--[^\n]*", "", re.sub(r"/-.*?-/", "", s or "", flags=re.S))

print("1. PROMPT TEMPLATE / STATEMENT FIDELITY")
print("   Could the model have substituted its own theorem, putting bad numbers")
print("   in a statement we then blame on the dataset?")
for name, p in SETS:
    rs = J(p)
    verbatim = sum(1 for r in rs if norm(r["formal_statement"]) in norm(r["full_code"]))
    one = sum(1 for r in rs if len(DECL.findall(sc(r["full_code"]))) == 1)
    templ = sum(1 for r in rs if r["prompt"].startswith("Complete the following Lean 4 code"))
    print(f"   {name:<12} templated {templ}/{len(rs)}   statement verbatim {verbatim}/{len(rs)}"
          f"   one declaration {one}/{len(rs)}")

print("\n2. NUMERIC TOKENIZATION / BPE REPAIR")
print("   A dropped digit would look exactly like a model arithmetic error.")
fwd_n = fwd_bad = rev_n = rev_bad = 0
for name, p in SETS:
    rs = J(p)
    a = b = c = d = 0
    for r in rs:
        pl, fl = set(LIT.findall(r["prompt"])), set(LIT.findall(r["full_code"]))
        for L in fl - pl:                      # came from the completion
            a += 1
            if L not in r["raw_output"]:
                b += 1
        for L in set(LIT.findall(r["raw_output"])):
            c += 1
            if L not in r["full_code"] and L not in r["prompt"]:
                d += 1
    art = sum(1 for r in rs if any(ch in r["raw_output"] for ch in ("Ġ", "Ċ", "ĉ")))
    fwd_n, fwd_bad, rev_n, rev_bad = fwd_n + a, fwd_bad + b, rev_n + c, rev_bad + d
    print(f"   {name:<12} completion->raw {a - b}/{a} intact   raw->full_code {c - d}/{c} intact"
          f"   BPE artifact records {art}")
print(f"   TOTAL {fwd_n + rev_n} literal checks, {fwd_bad + rev_bad} corrupted")

print("\n3. TRUNCATION")
print("   Is the flag computed, and does it have headroom to be non-vacuous?")
for name, p in SETS:
    rs = J(p)
    gt = [r.get("generated_tokens") or 0 for r in rs]
    mnt = sorted({r.get("max_new_tokens") for r in rs})
    print(f"   {name:<12} max_new_tokens={mnt} max_generated={max(gt)} headroom={mnt[0]-max(gt)}"
          f"   truncated={sum(1 for r in rs if r.get('truncated'))}"
          f"   closed_fence_False={sum(1 for r in rs if r.get('closed_fence') is False)}"
          f"   eos={sum(1 for r in rs if r.get('stopped_on_eos'))}/{len(rs)}")
