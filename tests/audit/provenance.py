"""Phase 1: for every FAILING sample, is the false number in the statement or the proof?

Joins the verification records (outcome + Lean errors, no code) to the trace
records (`formal_statement`, `full_code`) on `sample_index`, splits each file at
`:= by`, and checks the arithmetic on each side of the split.

The load-bearing step is SUBSTITUTION. A statement like

    theorem test (x : ℕ) (h₀ : x = 101^2) : (x = 10303)

contains no false equality until `h₀` is substituted into the goal; only then
does it read `10201 = 10303`. Checking equalities in isolation finds nothing,
which is why this pass binds every hypothesis of the form `var = <closed expr>`
and re-evaluates every other claim under that environment.

Reads only committed artifacts. No Lean, no GPU.
Run: python tests/audit/provenance.py
"""
import io, json, os, re, sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lean_arith import evaluate, NotClosed  # noqa: E402

J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]

SETS = [
    ("baseline_50step_1problem", "traces/temp_0.jsonl", "results/verification_temp_0.jsonl"),
    ("n50_distinct_T0.0", "traces/temp0.0_n50_1each/traces.jsonl", "results/verify3_temp0.0.jsonl"),
    ("n50_distinct_T0.2", "traces/temp0.2_n50_1each/traces.jsonl", "results/verify3_temp0.2.jsonl"),
]

ERR_RULES = [
    ("parse_skew",  r"unexpected token|Expected type must not contain free variables"),
    ("budget",      r"maximum recursion depth|deterministic timeout|heartbeat"),
    ("noop_tactic", r"[Nn]o goals to be solved"),
]
TACTIC_PAT = (r"linarith failed|nlinarith failed|ring_nf|unsolved goals|simp made no progress|"
              r"`simp` made no progress|omega could not|Unknown constant|unknown constant|"
              r"Unknown identifier|failed to synthesize|rewrite` failed|`rfl` failed|"
              r"Type mismatch|decide` proved")
FIELD_HINT = re.compile(r"[ℝℚ]|Real|Rat|\d+\.\d")
IDENT = re.compile(r"^[A-Za-z_][\w₀-₉'’]*$")


def domain_of(text):
    return "field" if FIELD_HINT.search(text or "") else "nat"


def strip_comments(s):
    s = re.sub(r"/-.*?-/", "", s or "", flags=re.S)
    return re.sub(r"--[^\n]*", "", s)


def split_at_by(full_code):
    m = re.search(r":=\s*by\b", full_code or "")
    return (full_code[:m.end()], full_code[m.end():]) if m else (full_code or "", "")


def split_binders_goal(stmt):
    """(list of binder-prop strings, goal string) from a theorem statement."""
    s = re.sub(r"\s+", " ", strip_comments(stmt)).strip()
    s = re.sub(r":=\s*by\s*$", "", s).strip()
    # The name must not swallow the colon. `\S+` is greedy and matched "test:"
    # in `theorem test: 1061520150601 = ...`, which left no top-level colon and
    # produced an empty goal for every binder-free statement.
    s = re.sub(r"^(?:theorem|lemma|example)\s+[^\s:(\[{]+\s*", "", s)
    props, depth, buf, rest = [], 0, "", ""
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in "([{":
            if depth == 0:
                buf = ""
            depth += 1
            if depth == 1:
                i += 1
                continue
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                props.append(buf)
                i += 1
                continue
        elif ch == ":" and depth == 0:
            rest = s[i + 1:]
            break
        if depth >= 1:
            buf += ch
        i += 1
    # a binder is `names : prop`; keep the prop half
    out = []
    for p in props:
        if ":" in p:
            out.append(p.split(":", 1)[1].strip())
    return out, rest.strip()


def strip_outer_parens(s):
    """`(1061520.150601 = x)` -> `1061520.150601 = x`.

    FormalStep wraps most goals in parentheses. Without this the `=` sits at
    depth 1 and every such goal is invisible to eq_sides().
    """
    s = s.strip()
    while len(s) > 1 and s[0] == "(" and s[-1] == ")":
        depth = 0
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    return s          # the leading "(" closes early; not a wrapper
        s = s[1:-1].strip()
    return s


def eq_sides(prop):
    """Top-level `A = B` -> (A, B), else None."""
    prop = strip_outer_parens(prop)
    depth = 0
    for i, ch in enumerate(prop):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif ch == "=" and depth == 0:
            if i and prop[i - 1] in "<>≤≥!≠:" or (i + 1 < len(prop) and prop[i + 1] == "="):
                continue
            return prop[:i].strip(), prop[i + 1:].strip()
    return None


def try_eval(expr, dom, env):
    """Evaluate, substituting bound variables first."""
    e = expr
    for k, v in sorted(env.items(), key=lambda kv: -len(kv[0])):
        e = re.sub(r"(?<![\w₀-₉'])" + re.escape(k) + r"(?![\w₀-₉'])", f"({v})", e)
    if re.search(r"[A-Za-z](?![A-Za-z]*\s*\()", re.sub(
            r"\b(Nat|factorial|choose|div|sub|pow|succ|Finset|card|e|E)\b", "", e)):
        # a free identifier survives -> not closed
        pass
    return evaluate(e, dom)


def analyse(stmt, dom):
    """(bindings, false_hypotheses, false_goal, n_checked)."""
    props, goal = split_binders_goal(stmt)
    env, checked, bad_hyp = {}, 0, []

    # pass 1: collect var := closed-value bindings
    for p in props:
        s = eq_sides(p)
        if not s:
            continue
        l, r = s
        for a, b in ((l, r), (r, l)):
            if IDENT.match(a):
                try:
                    val = evaluate(b, dom)
                except (NotClosed, Exception):  # noqa: BLE001
                    continue
                if a in env and env[a] != val:
                    bad_hyp.append(f"contradictory bindings for `{a}`: {env[a]} and {val}")
                env.setdefault(a, val)
                break

    # pass 2: every hypothesis that is now closed must be true
    for p in props:
        s = eq_sides(p)
        if not s:
            continue
        l, r = s
        if IDENT.match(l.strip()) or IDENT.match(r.strip()):
            if not (l.strip() in env and r.strip() in env):
                # a pure binding, already consumed
                if IDENT.match(l.strip()) and l.strip() in env and not IDENT.match(r.strip()):
                    continue
                if IDENT.match(r.strip()) and r.strip() in env and not IDENT.match(l.strip()):
                    continue
        try:
            lv, rv = try_eval(l, dom, env), try_eval(r, dom, env)
        except (NotClosed, Exception):  # noqa: BLE001
            continue
        checked += 1
        if lv != rv:
            bad_hyp.append(f"hypothesis `{l} = {r}` is FALSE: {lv} vs {rv}")

    # pass 3: the goal
    bad_goal = []
    gs = eq_sides(goal)
    if gs:
        try:
            lv, rv = try_eval(gs[0], dom, env), try_eval(gs[1], dom, env)
            checked += 1
            if lv != rv:
                bad_goal.append(f"goal `{gs[0]} = {gs[1]}` is FALSE: {lv} vs {rv}")
        except (NotClosed, Exception):  # noqa: BLE001
            pass
    return env, bad_hyp, bad_goal, checked


# Every `A = B` the PROOF asserts, wherever it appears -- `show`, `have`,
# `rw [show ...]`, `norm_num [...]`, `calc` steps, `linarith [...]` hints.
#
# An earlier version matched only `show`/`have`, which checked ONE claim across
# all 55 failing samples. A denominator of 1 cannot support a "zero proof_false"
# finding, so the scan is now over every equality in the body.
_BODY_EQ = re.compile(r"([\w!.^*/+\-() ]{1,90}?)\s*=\s*([\w!.^*/+\-() ]{1,90}?)"
                      r"(?=\s*(?:[,;\]\)\n]|$|by\b|from\b|:=))")
# Numeric literals the proof writes down at all, used as the Phase 3 denominator.
_BODY_LIT = re.compile(r"(?<![\w.])\d{2,}(?![\w.])")


# Tactic keywords that sit immediately before an asserted equality and would
# otherwise be swallowed into its left-hand side, making it unevaluable.
_LEAD = re.compile(r"^(?:show|have|calc|exact|from|refine|suffices|convert|"
                   r"[A-Za-z_][\w₀-₉']*\s*:)\s+")


def _trim_lead(s):
    s = s.strip()
    prev = None
    while prev != s:
        prev = s
        s = _LEAD.sub("", s).strip()
    return s


def proof_claims(body, dom):
    """(false claims, claims checked, distinct multi-digit literals written)."""
    bad, checked = [], 0
    txt = strip_comments(body)
    for m in _BODY_EQ.finditer(txt):
        l, r = _trim_lead(m.group(1)), m.group(2).strip()
        if not l or not r or not (re.search(r"\d", l) and re.search(r"\d", r)):
            continue
        try:
            lv, rv = evaluate(l, dom), evaluate(r, dom)
        except (NotClosed, Exception):  # noqa: BLE001
            continue
        checked += 1
        if lv != rv:
            bad.append(f"proof asserts `{l} = {r}`, but {lv} vs {rv}")
    return bad, checked, sorted(set(_BODY_LIT.findall(txt)))


def classify(rec, trace):
    errs = " ".join(rec.get("errors") or [])
    _, body = split_at_by(trace.get("full_code") or "")
    stmt = trace.get("formal_statement") or ""
    dom = domain_of(stmt)

    env, bad_hyp, bad_goal, n_stmt = analyse(stmt, dom)
    bad_body, n_body, body_lits = proof_claims(body, dom)

    ev = {
        "domain": dom, "bindings": {k: str(v) for k, v in env.items()},
        "statement_claims_checked": n_stmt, "proof_claims_checked": n_body,
        "false_hypotheses": bad_hyp, "false_goal": bad_goal,
        "false_proof_literals": bad_body,
        "proof_written_literals": body_lits,
        "error_head": re.sub(r"\s+", " ", errs)[:200] or None,
    }

    # Arithmetic outranks error-string triage: a false literal in the statement
    # makes the goal unprovable (or the premises inconsistent) no matter what
    # Lean happened to complain about.
    if bad_hyp or bad_goal:
        ev["statement_false_because"] = "false hypothesis" if bad_hyp else "false goal"
        return "statement_false", ev
    for label, pat in ERR_RULES:
        if re.search(pat, errs):
            return label, ev
    if bad_body:
        return "proof_false", ev
    if re.search(TACTIC_PAT, errs):
        return "tactic_mismatch", ev
    return "UNKNOWN", ev


def main():
    results, summary = {}, {}
    for name, tp, vp in SETS:
        traces = {}
        for r in J(tp):
            traces.setdefault(r["sample_index"], r)
        vers = {r["sample_index"]: r for r in J(vp)}
        fails = sorted(i for i, r in vers.items() if r["outcome"] != "valid")

        rows, counts = [], {}
        for i in fails:
            if i not in traces:
                counts["UNKNOWN"] = counts.get("UNKNOWN", 0) + 1
                rows.append({"sample": i, "label": "UNKNOWN",
                             "evidence": {"error_head": "no matching trace record"}})
                continue
            label, ev = classify(vers[i], traces[i])
            counts[label] = counts.get(label, 0) + 1
            rows.append({"sample": i, "outcome": vers[i]["outcome"], "label": label,
                         "state": vers[i].get("state"),
                         "statement": re.sub(r"\s+", " ", traces[i].get("formal_statement") or "").strip(),
                         "evidence": ev})
        results[name] = rows
        summary[name] = {"n_total": len(vers), "n_failing": len(fails), "counts": counts}

        print("=" * 100)
        print(f"{name}   {len(fails)} failing of {len(vers)}")
        print("=" * 100)
        for r in rows:
            e = r["evidence"]
            why = (e.get("false_hypotheses") or e.get("false_goal") or
                   e.get("false_proof_literals") or [e.get("error_head") or ""])[0]
            print(f"  s{r['sample']:<4}{r['label']:<18}{why[:76]}")
        print(f"\n  COUNTS: {counts}\n")

    json.dump({"summary": summary, "records": results},
              io.open("results/arithmetic_provenance.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print("wrote results/arithmetic_provenance.json")


if __name__ == "__main__":
    main()
