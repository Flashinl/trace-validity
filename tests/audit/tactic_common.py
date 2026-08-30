"""Shared assembly for the tactic-oracle audit: which failures are `tactic_mismatch`,
what the model wrote, and what shape the goal has.

No Lean here. This module is pure joins + regex so that Phase 1 (characterisation)
and Phase 2 (the oracle) start from exactly the same sample list.

TRACE SETS. `tactic_mismatch` is a label from the arithmetic-provenance labeller,
which has been run over five generation runs across two pipelines:

  Stage B     T=0.0, T=0.7            results/stage_b_provenance.json
  FormalStep  baseline, n50 T=0.0,    results/arithmetic_provenance.json
              n50 T=0.2

`results/stage_b_traces.jsonl` is byte-identical to the T=0.0 file (verified by
hashing `full_code`), so Stage B is two arms, not three.
"""
import io, json, os, re, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from goal_shape import split_goal  # noqa: E402

_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+[\w.]+[ \t]*$", re.M)
_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.S)


def J(path):
    return [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]


def statement_only(formal_statement):
    """The `theorem ... := by` text with imports and doc comments removed."""
    s = _IMPORT_RE.sub("", formal_statement or "")
    s = _BLOCK_COMMENT.sub("", s)
    return s.strip()


# --------------------------------------------------------------------------- #
# Goal shape buckets, in the order the audit specifies. First match wins, so the
# order encodes precedence: a nonlinear goal that also quantifies is filed
# nonlinear, because that is what decides whether `linarith` could ever work.
# --------------------------------------------------------------------------- #
SHAPES = ("nonlinear", "finset_bigop", "nat_int_arith", "quantified",
          "linear_real_rat", "other")

_NONLINEAR = [
    r"\^\s*\(?\s*[2-9]",                 # x^2 .. x^9
    r"\^\s*\(?\s*[a-zA-Z]",              # x^n  (symbolic exponent)
    r"Real\.sqrt|Real\.rpow|NNReal\.sqrt",
    r"Real\.(log|exp|sin|cos|tan)",
    # Product / quotient of two VARIABLES. `3 * x` is linear and must not match,
    # so the left operand has to start with a letter, not a digit.
    r"[a-zA-Z_][a-zA-Z0-9_']*\s*[*/]\s*[↑(]?[a-zA-Z_]",
    r"[)\]⌋⌉}]\s*[*/]\s*[↑(]?[a-zA-Z_⌊⌈]",  # (a + b) * c,  ⌊x⌋ * (x - ⌊x⌋)
]
_FINSET = [r"Finset", r"BigOperators", r"Multiset", r"List\.", r"ncard", r"\.card"]
_NAT_INT = [r"Nat\.", r"Int\.", r"ZMod", r"gcd|lcm", r"Prime", r"factorial",
            r"choose", r":\s*ℕ", r":\s*ℤ", r"∣", r"%"]
_QUANT = [r"∀", r"∃", r"\bforall\b", r"\bexists\b"]
_REAL_RAT = [r":\s*ℝ", r":\s*ℚ", r"\bReal\b", r"\bRat\b"]


def _any(pats, s):
    return any(re.search(p, s) for p in pats)


def goal_shape(statement, whole=None):
    """Bucket the GOAL. `whole` (the full statement incl. binders) supplies the
    type ascriptions, which almost always live in the binders rather than the goal."""
    goal = split_goal(statement) or statement
    ctx = whole if whole is not None else statement
    if _any(_NONLINEAR, goal):
        return "nonlinear"
    if _any(_FINSET, goal) or _any(_FINSET, ctx):
        return "finset_bigop"
    if _any(_NAT_INT, goal) or _any(_NAT_INT, ctx):
        return "nat_int_arith"
    if _any(_QUANT, goal):
        return "quantified"
    if _any(_REAL_RAT, goal) or _any(_REAL_RAT, ctx):
        return "linear_real_rat"
    return "other"


# --------------------------------------------------------------------------- #
# Tactics the model actually wrote
# --------------------------------------------------------------------------- #
# We do NOT parse Lean. We take identifiers in tactic-head position, which is
# enough to cross-tabulate. Comments and doc blocks are stripped first so that
# prose inside `/- ... -/` is never counted as a tactic.
_LINE_COMMENT = re.compile(r"--[^\n]*")
# Tactic POSITION only: start of line, or after a sequencing combinator.
#
# Three things it must NOT match, each of which put a non-tactic in the published
# vocabulary table:
#   `[`  -> `simp [Nat.pow_succ]` reported `Nat.pow_succ` as a tactic
#   `(`  -> `rcases h with ⟨x, hx⟩` reported `x`
#   `|`  -> `rcases this with (h | h | h)` reported `h`, 14 times. `|` is a real
#           tactic separator in `first | t1 | t2`, but it is far more often an
#           rcases alternation, so it is not worth the false positives.
_TACTIC_HEAD = re.compile(r"(?:^|<;>|;|·|\.\s)\s*([a-zA-Z_][a-zA-Z0-9_'.]*)")
# `| zero => simp` in an induction block: `zero` is a case label, `simp` is the
# tactic. Strip the label and keep the body -- skipping the whole line would
# lose a real tactic.
_CASE_LABEL = re.compile(r"^\s*\|\s*[a-zA-Z_][a-zA-Z0-9_'.]*(?:\s+\S+)*\s*=>\s*")

# Words that appear in tactic-head position but are not tactics.
_NOT_TACTICS = {
    "theorem", "lemma", "example", "def", "instance", "import", "open",
    "set_option", "with", "at", "using", "this", "fun", "by", "do", "let",
    "if", "then", "else", "match", "sorry", "all_goals", "any_goals",
    "first", "try", "repeat", "focus", "next", "case", "intro_pat",
}


def proof_body(full_code, formal_statement):
    """Everything after the statement's `:= by`. '' when it cannot be located."""
    stmt = _IMPORT_RE.sub("", formal_statement or "").strip()
    if not stmt or not full_code:
        return ""
    i = full_code.find(stmt)
    if i < 0:
        return ""
    return full_code[i + len(stmt):]


def tactics_used(body):
    """Ordered list of distinct tactic identifiers written in the proof body."""
    b = _BLOCK_COMMENT.sub(" ", body or "")
    b = _LINE_COMMENT.sub(" ", b)
    out, seen = [], set()
    for line in b.splitlines():
        line = _CASE_LABEL.sub("", line.strip())
        if not line:
            continue
        for m in _TACTIC_HEAD.finditer(line):
            name = m.group(1)
            if name in _NOT_TACTICS or name in seen:
                continue
            seen.add(name)
            out.append(name)
    return out


# The tactics the audit tracks by name; anything else is reported under `other`.
TRACKED = ["linarith", "nlinarith", "norm_num", "decide", "simp", "simp_all",
           "ring", "ring_nf", "omega", "positivity", "rw", "field_simp",
           "aesop", "decide", "constructor", "exact", "apply", "use",
           "interval_cases", "subst", "have", "calc", "show", "unfold",
           "rcases", "obtain", "induction", "cases"]

# Tactic that actually attempts to CLOSE the goal, most-specific first. `rw`,
# `have` and friends are structural and say little about the decision procedure
# the model chose, so they only win when nothing else is present.
_CLOSERS = ["nlinarith", "linarith", "omega", "decide", "positivity",
            "field_simp", "norm_num", "ring_nf", "ring", "aesop",
            "simp_all", "simp", "interval_cases", "exact", "apply", "rw"]


def primary_tactic(tactics):
    """The tracked tactic the model leaned on to close the goal."""
    for t in _CLOSERS:
        if t in tactics:
            return t
    return tactics[0] if tactics else "none"


# --------------------------------------------------------------------------- #
# The joined sample list
# --------------------------------------------------------------------------- #
def load_samples(root=_ROOT, label="tactic_mismatch"):
    """Every failure carrying `label`, with statement, header and model body."""
    out = []

    prov = json.load(io.open(os.path.join(root, "results/stage_b_provenance.json"),
                             encoding="utf-8"))
    traces = {
        "0.0": {r["uuid"]: r for r in J(os.path.join(root, "results/stage_b_traces_temp0.0.jsonl"))},
        "0.7": {r["uuid"]: r for r in J(os.path.join(root, "results/stage_b_traces_temp0.7.jsonl"))},
    }
    for row in prov["rows"]:
        if row["label"] != label:
            continue
        t = str(row["temp"])
        tr = traces[t].get(row["uuid"], {})
        out.append({
            "set": "stageB_T%s" % t, "pipeline": "StageB", "id": row["uuid"],
            "band": row.get("band"), "outcome": row["outcome"],
            "old_kind": row.get("old_kind"),
            "formal_statement": tr.get("formal_statement", ""),
            "full_code": tr.get("full_code") or "",
        })

    ap = json.load(io.open(os.path.join(root, "results/arithmetic_provenance.json"),
                           encoding="utf-8"))
    fs_traces = {
        "baseline_50step_1problem":
            {r["sample_index"]: r for r in J(os.path.join(root, "traces/temp_0.jsonl"))},
        "n50_distinct_T0.0":
            {r["sample_index"]: r for r in J(os.path.join(root, "traces/temp0.0_n50_1each/traces.jsonl"))},
        "n50_distinct_T0.2":
            {r["sample_index"]: r for r in J(os.path.join(root, "traces/temp0.2_n50_1each/traces.jsonl"))},
    }
    for run, rows in ap["records"].items():
        for row in rows:
            if row["label"] != label:
                continue
            tr = fs_traces[run].get(row["sample"], {})
            out.append({
                "set": "formalStep_" + run, "pipeline": "FormalStep", "id": row["sample"],
                "band": None, "outcome": row["outcome"], "old_kind": None,
                "formal_statement": tr.get("formal_statement", ""),
                "full_code": tr.get("full_code") or "",
            })

    for s in out:
        s["statement"] = statement_only(s["formal_statement"])
        s["goal"] = split_goal(s["statement"])
        s["shape"] = goal_shape(s["statement"], whole=s["statement"])
        s["body"] = proof_body(s["full_code"], s["formal_statement"])
        s["tactics"] = tactics_used(s["body"])
        s["primary"] = primary_tactic(s["tactics"])
        # Did the closing tactic meet the TOP-LEVEL goal, or a subgoal some
        # earlier tactic had already reshaped? Only when it is the first tactic
        # in the body can the cross-tab's (tactic, goal shape) pair be read as
        # "this procedure was applied to this goal". See TACTIC_SELECTION.md §2.
        s["closer_first"] = bool(s["tactics"]) and s["tactics"][0] == s["primary"]
    return out


# --------------------------------------------------------------------------- #
# What LEAN says failed, and on what goal
# --------------------------------------------------------------------------- #
# The cross-tab in §1 pairs a tactic with the shape of the *top-level* goal, and
# that pairing is only exact when the tactic ran first. Lean's own error text
# does better: it names the tactic that failed AND prints the goal state that
# tactic actually faced. This block parses it.
VERIFICATION_FILES = {
    "stageB_T0.0": ("results/stage_b_verified_temp0.0.jsonl", "uuid"),
    "stageB_T0.7": ("results/stage_b_verified_temp0.7.jsonl", "uuid"),
    "formalStep_baseline_50step_1problem": ("results/verification_temp_0.jsonl", "sample_index"),
    "formalStep_n50_distinct_T0.0": ("results/verify3_temp0.0.jsonl", "sample_index"),
    "formalStep_n50_distinct_T0.2": ("results/verify3_temp0.2.jsonl", "sample_index"),
}

# Ordered: first pattern that matches the error's first line wins.
_ERROR_TACTIC = [
    (re.compile(r"^(\w+) could not prove the goal"), lambda m: m.group(1)),
    (re.compile(r"^(\w+) failed to find a contradiction"), lambda m: m.group(1)),
    (re.compile(r"^(\w+) made no progress"), lambda m: m.group(1)),
    (re.compile(r"^`(\w+)` made no progress"), lambda m: m.group(1)),
    (re.compile(r"^Tactic `(\w+)` (?:failed|proved)"), lambda m: m.group(1)),
    (re.compile(r"^(\w+) failed"), lambda m: m.group(1)),
]

# Failures that are NOT a decision procedure losing: the model named a lemma
# that does not exist, or wrote something that does not typecheck. A different
# tactic does not fix these; they are their own category.
_NAME_ERROR = re.compile(r"^Unknown (constant|identifier)")
_TYPE_ERROR = re.compile(r"^(Type mismatch|failed to synthesize)")
_UNSOLVED = re.compile(r"^unsolved goals")


def load_verification(root=_ROOT):
    out = {}
    for st, (path, key) in VERIFICATION_FILES.items():
        out[st] = {r[key]: r for r in J(os.path.join(root, path))}
    return out


def classify_error(err):
    """(failing_tactic, kind, context) for one Lean error message.

    `kind` is one of: tactic_failed | unsolved_goals | unknown_name |
    type_error | other. `context` is the goal state Lean printed, when it
    printed one -- hypotheses included, because `linarith` negates the goal into
    the hypothesis set and its language must cover those too.
    """
    text = str(err or "")
    first = text.splitlines()[0].strip() if text.strip() else ""
    if _NAME_ERROR.match(first):
        return None, "unknown_name", first
    if _TYPE_ERROR.match(first):
        return None, "type_error", first
    if _UNSOLVED.match(first):
        return None, "unsolved_goals", text
    for pat, get in _ERROR_TACTIC:
        m = pat.match(first)
        if m:
            return get(m), "tactic_failed", text
    return None, "other", first


def attach_lean_errors(samples, root=_ROOT):
    """Add `lean_tactic`, `lean_kind`, `lean_shape` from the recorded errors."""
    ver = load_verification(root)
    for s in samples:
        v = ver.get(s["set"], {}).get(s["id"], {})
        errs = v.get("errors") or []
        s["n_errors"] = len(errs)
        tac = kind = ctx = None
        for e in errs:
            t, k, c = classify_error(e)
            if tac is None and t:            # first error that names a tactic
                tac, kind, ctx = t, k, c
        if tac is None and errs:
            _, kind, ctx = classify_error(errs[0])
        s["lean_tactic"] = tac or "(none named)"
        s["lean_kind"] = kind or "other"
        s["lean_context"] = (ctx or "")[:4000]
        # Only trust the error text for goal shape when it actually PRINTS a
        # goal state. `omega could not prove the goal:` follows with its internal
        # linear constraints and a `where a := ↑n / 3` substitution table, which
        # is omega's normalised view and not the Lean goal; classifying that
        # would report the shape of omega's abstraction rather than the maths.
        # `simp made no progress` prints nothing at all. Both fall back to the
        # statement.
        # omega prints, after `where`, the atoms it introduced. An atom defined
        # as a product or power of variables is omega telling us in its own words
        # that it discarded nonlinear structure -- direct evidence of a category
        # error, where the statement's shape would only have been a guess.
        s["omega_nonlinear_atom"] = False
        if tac == "omega":
            m = re.search(r"\bwhere\b(.*)\Z", ctx or "", re.S)
            tbl = m.group(1) if m else ""
            s["omega_nonlinear_atom"] = bool(
                re.search(r":=.*[a-zA-Z_][a-zA-Z0-9_₀-₉]*\s*[*^]\s*[↑(]?[a-zA-Z_]", tbl))
        printed_goal = bool(ctx) and "⊢" in (ctx or "")
        s["lean_shape"] = goal_shape(s["lean_context"], whole=s["lean_context"]) \
            if printed_goal else s["shape"]
        s["lean_shape_source"] = "lean_goal_state" if printed_goal else "statement"
        s["structural"], s["structural_why"] = structural_verdict(s)
    return samples


# A structural category error is claimed ONLY on direct evidence from Lean's own
# output -- never from the shape of the top-level statement, because the tactic
# may have run on a subgoal that had already been reshaped.
def structural_verdict(s):
    """(is_structural, why). Direct evidence only; the default is False."""
    t = s["lean_tactic"]
    if t in ("linarith",) and s["lean_shape_source"] == "lean_goal_state" \
            and s["lean_shape"] == "nonlinear":
        return True, ("linarith printed its whole context and it contains a nonlinear "
                      "term; linarith seeks a degree-1 certificate and abstracts every "
                      "nonlinear monomial to an opaque atom, so no configuration of it "
                      "could have closed this goal")
    if t == "omega" and s["omega_nonlinear_atom"]:
        return True, ("omega's own `where` table defines an atom as a product of "
                      "variables — omega is reporting that it discarded the nonlinear "
                      "structure the goal depends on")
    return False, ""


SET_ORDER = ["stageB_T0.0", "stageB_T0.7", "formalStep_baseline_50step_1problem",
             "formalStep_n50_distinct_T0.0", "formalStep_n50_distinct_T0.2"]

SET_LABEL = {
    "stageB_T0.0": "Stage B T=0.0",
    "stageB_T0.7": "Stage B T=0.7",
    "formalStep_baseline_50step_1problem": "FormalStep baseline",
    "formalStep_n50_distinct_T0.0": "FormalStep n50 T=0.0",
    "formalStep_n50_distinct_T0.2": "FormalStep n50 T=0.2",
}
