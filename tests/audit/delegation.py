"""Phase 3: does the model hand-compute arithmetic, or delegate it to a tactic?

A Lean prover should generally not write large intermediate values by hand. It
should state the goal and let `norm_num` / `decide` / `omega` evaluate. If
hand-computing proofs fail materially more often, that is actionable at
inference time -- prompting or few-shot examples -- with no retraining.

Measured over ALL samples in each set, not just the failures, so the
cross-tabulation has both margins.

Run: python tests/audit/delegation.py
"""
import io, json, math, re, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]

SETS = [
    ("baseline", "traces/temp_0.jsonl", "results/verification_temp_0.jsonl"),
    ("n50 T=0.0", "traces/temp0.0_n50_1each/traces.jsonl", "results/verify3_temp0.0.jsonl"),
    ("n50 T=0.2", "traces/temp0.2_n50_1each/traces.jsonl", "results/verify3_temp0.2.jsonl"),
]

# Tactics that evaluate arithmetic for you.
DELEGATE = re.compile(r"\b(norm_num|decide|native_decide|omega|simp_arith|ring|ring_nf|"
                      r"linarith|nlinarith|positivity|field_simp|rfl)\b")
# A multi-digit literal the PROOF wrote that the STATEMENT did not supply.
LIT = re.compile(r"(?<![\w.])(\d{2,})(?![\w.])")


def strip_comments(s):
    s = re.sub(r"/-.*?-/", "", s or "", flags=re.S)
    return re.sub(r"--[^\n]*", "", s)


def proof_body(full_code):
    m = re.search(r":=\s*by\b", full_code or "")
    return full_code[m.end():] if m else ""


def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return (float("nan"),) * 2
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def fmt(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100*k/n:.0f}% [{100*lo:.0f}-{100*hi:.0f}%]" if n else "n/a"


print("=" * 88)
print("PHASE 3 -- HAND-COMPUTED ARITHMETIC vs DELEGATED, CROSS-TABBED AGAINST OUTCOME")
print("=" * 88)

for name, tp, vp in SETS:
    traces = {}
    for r in J(tp):
        traces.setdefault(r["sample_index"], r)
    vers = {r["sample_index"]: r for r in J(vp)}

    cells = {}   # (hand, valid) -> count
    hand_samples = []
    for i, v in vers.items():
        t = traces.get(i)
        if not t:
            continue
        body = strip_comments(proof_body(t.get("full_code") or ""))
        stmt_lits = set(LIT.findall(t.get("formal_statement") or ""))
        prompt_lits = set(LIT.findall(t.get("prompt") or ""))
        new_lits = set(LIT.findall(body)) - stmt_lits - prompt_lits
        hand = bool(new_lits)
        valid = v["outcome"] == "valid"
        cells[(hand, valid)] = cells.get((hand, valid), 0) + 1
        if hand:
            hand_samples.append((i, sorted(new_lits)[:4], v["outcome"]))

    nh = cells.get((True, True), 0) + cells.get((True, False), 0)
    nd = cells.get((False, True), 0) + cells.get((False, False), 0)
    vh = cells.get((True, True), 0)
    vd = cells.get((False, True), 0)

    print(f"\n{name}   n={nh+nd}")
    print(f"  {'':<34}{'valid':>8}{'not valid':>12}{'total':>8}")
    print(f"  {'hand-wrote a new literal':<34}{vh:>8}{nh-vh:>12}{nh:>8}")
    print(f"  {'delegated to a tactic':<34}{vd:>8}{nd-vd:>12}{nd:>8}")
    print(f"  validity | hand-computed : {fmt(vh, nh)}")
    print(f"  validity | delegated     : {fmt(vd, nd)}")
    if nh and nd:
        print(f"  difference: {100*(vh/nh - vd/nd):+.0f} pp")
    dele = sum(1 for i, t in traces.items()
               if i in vers and DELEGATE.search(strip_comments(proof_body(t.get("full_code") or ""))))
    print(f"  proofs invoking an arithmetic tactic at all: {dele}/{len(vers)}")
    if hand_samples:
        print(f"  hand-computing samples: "
              + ", ".join(f"s{i}({o[:4]},{','.join(l[:2])})" for i, l, o in hand_samples[:10]))
