"""Can FormalStep be filtered to PROOF steps rather than CALCULATION steps?

Classifies each `formal_statement` by the shape of its GOAL (the part after the
last top-level `:`), not by its hypotheses. A step whose binders introduce
variables but whose goal is a closed numeric identity is still a calculation.

  calculation  goal is a numeric (in)equality between closed terms -- no free
               variables and no binders in the GOAL. `x = 1061520150601` counts
               when `x` is pinned by a hypothesis, because the goal reduces to
               arithmetic once the hypothesis is substituted.
  proof        goal carries a quantifier, an inequality over a free variable,
               divisibility, a Finset/cardinality claim, set membership, or any
               other quantified or structural claim.
  mixed        goal is a conjunction/disjunction with one conjunct of each kind.
  UNKNOWN      no parseable goal.

Purely syntactic and deliberately so: no Lean, no GPU, runs over the whole split
in seconds. It answers a scoping question -- is a filtered eval set big enough
to be worth building -- not a semantic one.

Run: python tests/audit/goal_shape.py
"""
import argparse, collections, io, json, os, re, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from stats import wilson

CALCULATION, PROOF, MIXED, UNKNOWN = "calculation", "proof", "mixed", "UNKNOWN"

# --- goal extraction --------------------------------------------------------
_DECL = re.compile(r"^\s*(?:theorem|lemma|example)\b", re.M)


# The declaration name must NOT be matched with \S*: FormalStep writes
# `theorem test:` with no space, so \S* swallows the colon and every such row
# looks like it has no goal. That was 13880 of 30809 rows classified UNKNOWN.
_DECL_HEAD = re.compile(r"^(?:theorem|lemma|example)\s*([^\s:(){}\[\]]*)\s*")


def _body(stmt):
    s = re.sub(r":=\s*(?:by)?\s*(?:sorry)?\s*\Z", "", (stmt or "").strip())
    s = re.sub(r"\s+", " ", s).strip()
    m = _DECL_HEAD.match(s)
    return s[m.end():] if m else s


def _cut(body):
    """Index of the binder/goal separator: the FIRST depth-0 colon.

    Not the last. `theorem foo : forall a : N, a^6 = n` has a depth-0 colon
    inside the quantifier, and taking the last one returned `N, a^6 = n` --
    stripping the quantifier and misfiling the row as an equation.
    """
    depth = 0
    for i, ch in enumerate(body):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif ch == ":" and depth == 0:
            return i
    return None


def split_goal(stmt):
    """Return the goal: everything after the binder/goal separator."""
    body = _body(stmt)
    c = _cut(body)
    return body[c + 1:].strip() if c is not None else ""


# --- proof-shape markers ----------------------------------------------------
# Quantifiers, structure, and anything that ranges over more than a fixed value.
PROOF_PAT = [
    (r"[∀∃]", "quantifier"),
    (r"\\forall|\\exists", "quantifier"),
    (r"∣|\bDvd\b|\.dvd\b", "divisibility"),
    (r"\bFinset\b|\bSet\b|\bcard\b|\.card\b", "finset_or_card"),
    (r"[∈∉⊆⊂∪∩]", "set_relation"),
    (r"\bNat\.Prime\b|\bPrime\b|\bOdd\b|\bEven\b|\bCoprime\b", "predicate"),
    (r"\bTendsto\b|𝓝|\batTop\b|∑'|\b∑\b|\b∏\b", "limit_or_bigop"),
    (r"\bIrrational\b|\bMonotone\b|\bInjective\b|\bSurjective\b|\bBijective\b", "predicate"),
    (r"\bFunction\.", "predicate"),
    (r"¬", "negation"),
    (r"↔", "iff"),
    (r"→", "implication"),
]
_NUM = r"(?:\d+|\d+\.\d+)"
# A closed arithmetic term: numerals, operators, factorial, parens, Nat.xxx of numerals.
_CLOSED_TOKEN = re.compile(
    r"^(?:[\s\d\+\-\*/\^%!()\[\].,=<>≤≥≠]|"
    r"Nat\.factorial|Nat\.choose|Nat\.gcd|Nat\.lcm|Nat\.sqrt|"
    r"Int\.|Rat\.|Real\.|\bmod\b|\bdiv\b|choose|factorial)+$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_₀-₉'’.]*")
_KNOWN_FN = {"Nat", "Int", "Rat", "Real", "factorial", "choose", "gcd", "lcm",
             "sqrt", "mod", "div", "abs", "min", "max", "pow"}


def _idents(goal):
    """Identifiers in the goal that are not known arithmetic functions."""
    out = set()
    for m in _IDENT.finditer(goal):
        tok = m.group(0)
        head = tok.split(".")[0]
        if head in _KNOWN_FN:
            continue
        out.add(tok)
    return out


def classify_goal(goal, binders=""):
    if not goal.strip():
        return UNKNOWN, "no goal"

    hits = [name for pat, name in PROOF_PAT if re.search(pat, goal)]

    # Conjunctions: classify each side, then decide.
    parts = re.split(r"\s*[∧∨]\s*", goal) if re.search(r"[∧∨]", goal) else [goal]
    if len(parts) > 1:
        kinds = set()
        for p in parts:
            k, _ = classify_goal(p, binders)
            kinds.add(k)
        kinds.discard(UNKNOWN)
        if kinds == {CALCULATION, PROOF}:
            return MIXED, "conjunction of both kinds"
        if kinds == {PROOF}:
            return PROOF, "conjunction, all proof-shaped"
        if kinds == {CALCULATION}:
            return CALCULATION, "conjunction, all closed arithmetic"

    if hits:
        return PROOF, ",".join(sorted(set(hits)))

    # No proof markers. Closed arithmetic, or an (in)equality over free vars?
    if not re.search(r"[=<>≤≥≠]", goal):
        return UNKNOWN, "no relation and no proof marker"

    free = _idents(goal)
    if not free:
        return CALCULATION, "closed numeric relation"
    # Free identifiers present. If EVERY one is bound by a hypothesis equation
    # (`h : x = 3`), substituting makes the goal closed arithmetic -- still a
    # calculation. We cannot see hypotheses reliably here, so use the binder
    # text: a goal over variables the binders pin to numerals is a calculation.
    pinned = set(re.findall(r"([A-Za-z_][\w₀-₉'’]*)\s*[=:]\s*\d", binders or ""))
    if free and free <= pinned:
        return CALCULATION, "goal over hypothesis-pinned numerals"
    if re.search(r"[<>≤≥≠]", goal):
        return PROOF, "inequality over a free variable"
    return PROOF, "equation over free variables"


def split_binders(stmt):
    body = _body(stmt)
    c = _cut(body)
    return body[:c].strip() if c is not None else ""


def classify_statement(stmt):
    return classify_goal(split_goal(stmt), split_binders(stmt))


def report(rows, title, out):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    n = len(rows)
    ct = collections.Counter(r["class"] for r in rows)
    for k in (PROOF, CALCULATION, MIXED, UNKNOWN):
        c = ct.get(k, 0)
        lo, hi = wilson(c, n) if n else (0, 0)
        print(f"  {k:<13} {c:>6}/{n:<6} = {100*c/n if n else 0:>5.1f}%  "
              f"[{100*lo:>4.1f}-{100*hi:>5.1f}%]")
    out[title] = {k: ct.get(k, 0) for k in (PROOF, CALCULATION, MIXED, UNKNOWN)}
    out[title]["n"] = n
    out[title]["wilson"] = {k: list(wilson(ct.get(k, 0), n)) for k in
                            (PROOF, CALCULATION, MIXED, UNKNOWN)} if n else {}

    for k in (PROOF, CALCULATION, MIXED, UNKNOWN):
        ex = [r for r in rows if r["class"] == k][:5]
        if not ex:
            continue
        print(f"\n  --- {k} examples ---")
        for r in ex:
            print(f"    [{r['why']}] {r['goal'][:96]}")
    return ct


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/goal_shape.json")
    args = ap.parse_args()

    from datasets import load_dataset
    from config import DATASET_NAME, DATASET_SPLIT

    full = load_dataset(DATASET_NAME, split=DATASET_SPLIT)
    pids = full["problem_unique_id"]
    stmts = full["formal_statement"]
    print(f"{len(full)} rows, {len(set(pids))} problems")

    out = {}

    # (a) The 500-problem set: first step of each problem. This is the
    #     denominator the filtering decision is actually about.
    first = {}
    for i, p in enumerate(pids):
        if p not in first:
            first[p] = i
    rows500 = []
    for p, i in first.items():
        cls, why = classify_statement(stmts[i])
        rows500.append({"row": i, "pid": p, "class": cls, "why": why,
                        "goal": split_goal(stmts[i]), "stmt": stmts[i]})
    report(rows500, f"A. FIRST STEP OF EACH PROBLEM (n={len(rows500)})", out)

    # (b) The whole split, because a filter would not be limited to first steps.
    rowsall = []
    for i, s in enumerate(stmts):
        cls, why = classify_statement(s)
        rowsall.append({"row": i, "pid": pids[i], "class": cls, "why": why,
                        "goal": split_goal(s), "stmt": s})
    report(rowsall, f"B. ALL ROWS IN THE SPLIT (n={len(rowsall)})", out)

    # (c) problems that contain at least one proof-shaped step
    byp = collections.defaultdict(list)
    for r in rowsall:
        byp[r["pid"]].append(r["class"])
    with_proof = sum(1 for p, ks in byp.items() if PROOF in ks or MIXED in ks)
    lo, hi = wilson(with_proof, len(byp))
    print("\n" + "=" * 78)
    print("C. COVERAGE")
    print("=" * 78)
    print(f"  problems with >=1 proof-shaped step: {with_proof}/{len(byp)} = "
          f"{100*with_proof/len(byp):.1f}%  [{100*lo:.1f}-{100*hi:.1f}%]")
    n_proof_rows = sum(1 for r in rowsall if r["class"] in (PROOF, MIXED))
    print(f"  proof-shaped rows in the whole split: {n_proof_rows}/{len(rowsall)} = "
          f"{100*n_proof_rows/len(rowsall):.1f}%")
    out["coverage"] = {"problems_with_proof_step": with_proof, "problems": len(byp),
                       "proof_rows": n_proof_rows, "rows": len(rowsall)}

    # ---- the decision --------------------------------------------------------
    p500 = sum(1 for r in rows500 if r["class"] in (PROOF, MIXED))
    lo, hi = wilson(p500, len(rows500))
    print("\n" + "=" * 78)
    print("DECISION: is a proof-step-only eval set viable?")
    print("=" * 78)
    print(f"  proof-or-mixed, one step per problem: {p500}/{len(rows500)} = "
          f"{100*p500/len(rows500):.1f}%  [{100*lo:.1f}-{100*hi:.1f}%]")
    print(f"  threshold in the brief: 15% of 500 = 75 steps")
    verdict = "VIABLE" if p500 >= 75 else "UNDERPOWERED"
    print(f"  -> {verdict}: a one-step-per-problem filtered set yields {p500} steps.")
    print(f"  -> Drawing from ALL rows instead yields {n_proof_rows} proof-shaped "
          f"steps across {with_proof} problems,")
    print(f"     so the binding constraint is problem diversity "
          f"({with_proof} problems), not step count.")
    out["decision"] = {"proof_or_mixed_500": p500, "n": len(rows500),
                       "threshold": 75, "verdict": verdict}

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    io.open(args.out, "w", encoding="utf-8", newline="\n").write(
        json.dumps({"summary": out,
                    "rows500": [{k: r[k] for k in ("row", "pid", "class", "why", "goal")}
                                for r in rows500]}, ensure_ascii=False, indent=1))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
