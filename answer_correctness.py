"""Axis 2: does a trajectory's final answer match `ground_truth`?

This module is the whole of the answer-correctness path. It is deliberately
SEALED OFF from the Lean pipeline:

  * it imports nothing from verifier.py, trace_valid.py, parser.py or config.py
  * every public entry point runs `assert_no_lean_verdict()` on its input, which
    RAISES if the caller hands it a record carrying `trace_valid`, `outcome`,
    `has_sorry`, `valid`, `errors`, `axioms` or any other Lean result

That assertion is the mechanism, not a convention. The original design bug was
`answer_correct = trace_valid and not has_sorry`, which made axis 2 a function of
axis 1 and forced `invalid_accuracy` to 0.0 identically. A guard that can only be
satisfied by never seeing a Lean verdict cannot rebuild that bug.

Normalisation rules, decided once and applied everywhere
--------------------------------------------------------
1. FRACTION REDUCTION -- yes. Answers are compared by VALUE, so 2/4 == 1/2.
   The canonical string is `Fraction`'s lowest-terms form.
2. DECIMAL / FRACTION EQUIVALENCE -- yes, exactly. `0.5` and `\\frac{1}{2}` are
   both parsed to the exact rational 1/2. Decimals are read as exact rationals
   (`Fraction("0.1")` == 1/10), never as floats, so no epsilon is involved and
   no rounding is possible.
3. NEGATIVE SIGNS -- preserved, and accepted either outside or inside the
   fraction macro: `-\\frac{2}{3}`, `\\frac{-2}{3}` both give -2/3.
4. WHITESPACE -- all removed, including the LaTeX spacing macros `\\!`, `\\,`,
   `\\;` and `\\ `. The `,` thousands separator is removed too, so `45,\\!045`
   is 45045.
5. PERCENT -- converted to its value: `10\\%` is the rational 1/10, not 10.
   This is what the data requires: a trajectory ending "0.1 or 10%" must match a
   `ground_truth` of `\\frac{1}{10}`. The cost is that a `ground_truth` of
   `50\\%` will NOT match a trajectory that writes bare "50"; no such pair is in
   the eligible pool, and the rule is applied to both sides alike.
6. CURRENCY -- `\\$` is stripped as a unit. `$` used as a math delimiter is also
   stripped. These are different characters in the source and are handled in
   that order.

Values that are not rational (`\\text{B}`, `n`, `\\frac{\\pi}{6}`) normalise to a
cleaned string and compare by exact string equality, never by value.

No Lean, no GPU, no network.
"""
import re
from fractions import Fraction

# Anything a Lean verdict could arrive under. Presence of ANY of these in a
# record handed to this module is a design error, not a data error.
LEAN_VERDICT_FIELDS = frozenset({
    "trace_valid", "outcome", "has_sorry", "valid", "errors", "num_errors",
    "axioms", "verify_seconds", "verify_source", "statement_probe",
    "statement_mismatch_detail", "statement_error_detail", "vacuous",
    "has_sorry_literal", "failure_kind", "state",
})


class LeanLeakError(AssertionError):
    """The answer path was handed a Lean result. The two axes must not touch."""


def assert_no_lean_verdict(record, where="answer path"):
    """Raise if `record` carries anything the Lean pipeline produces.

    `state` is included in the forbidden set on purpose: it is FormalStep's own
    Lean verification result for the step's reference proof. It is a Lean
    verdict, it correlates with our trace-validity axis, and letting it into the
    answer path would couple the axes just as surely as reading `outcome`.
    """
    if record is None or not hasattr(record, "keys"):
        return
    leaked = sorted(LEAN_VERDICT_FIELDS.intersection(record.keys()))
    if leaked:
        raise LeanLeakError(
            f"{where} was handed Lean verdict field(s) {leaked}. The answer "
            "axis must be computable without any Lean result; see the "
            "`answer_correct = trace_valid and not has_sorry` bug this "
            "redesign exists to fix."
        )


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
# Both \frac arguments are INDEPENDENTLY optional-braced: LaTeX takes a single
# character as a whole argument. \frac19 is 1/9 and \frac1{216} is 1/216.
# Requiring braces on the second argument misfiles real answers as unparseable.
_ARG = r"(?:\{\s*(-?\d+)\s*\}|(-?\d))"
_FRAC = re.compile(r"^(-?)\\[dt]?frac" + _ARG + _ARG + r"$")
_SLASH = re.compile(r"^(-?\d+)\s*/\s*(\d+)$")
_INT = re.compile(r"^-?\d+$")
_DEC = re.compile(r"^-?\d*\.\d+$")
_PCT = re.compile(r"^(.*?)\\?%$")

_SPACE_MACROS = ("\\!", "\\,", "\\;", "\\:", "\\ ", "~")


def _strip_latex(raw):
    """Remove spelling, never value."""
    t = (raw or "").strip()
    for m in _SPACE_MACROS:
        t = t.replace(m, "")
    t = t.replace("\\left", "").replace("\\right", "")
    t = t.replace("\\$", "")          # currency, before math delimiters
    t = t.replace("$", "")            # math delimiters
    t = t.replace("\\dollar", "")
    t = re.sub(r"\\mbox\s*\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\text(?:bf|it|rm)?\s*\{([^}]*)\}", r"\1", t)
    t = t.replace(",", "")            # thousands separator
    t = t.replace(" ", "")
    return t.strip()


def answer_value(raw):
    """Exact rational value of an answer string, or None if it is not numeric.

    Never returns a float: decimals go through Fraction(str), so 0.1 is exactly
    1/10 and comparison is exact.
    """
    t = _strip_latex(raw)
    if not t:
        return None

    pct = _PCT.match(t)
    if pct and pct.group(1):
        inner = answer_value(pct.group(1))
        return None if inner is None else inner / 100

    if _INT.fullmatch(t):
        return Fraction(int(t))
    if _DEC.fullmatch(t):
        return Fraction(t)
    m = _FRAC.match(t)
    if m:
        num = m.group(2) if m.group(2) is not None else m.group(3)
        den = m.group(4) if m.group(4) is not None else m.group(5)
        if den is None or int(den) == 0:
            return None
        v = Fraction(int(num), int(den))
        return -v if m.group(1) == "-" else v
    m = _SLASH.fullmatch(t)
    if m and int(m.group(2)) != 0:
        return Fraction(int(m.group(1)), int(m.group(2)))
    return None


def normalize_answer(raw):
    """Canonical comparable form. Rationals become lowest-terms `a/b` or `a`."""
    v = answer_value(raw)
    if v is not None:
        return str(v)                 # Fraction.__str__ reduces; ints lose /1
    t = _strip_latex(raw)
    return t.lower() or None


def _percent_readings(raw):
    """Every value a percent literal could be intended to denote.

    FormalStep stores the answer to a probability question BOTH ways and the two
    conventions are irreconcilable by any single rule:

        ground_truth `\\frac{1}{10}`, trajectory "0.1 or 10%"  -> 10% must be 1/10
        ground_truth `15`,            trajectory "15%"          -> 15% must be 15

    So a percent literal is matched permissively: it denotes either its value
    (x/100) or its bare numeral (x). This is a deliberate widening. Its cost is
    a false positive whenever a `ground_truth` of N is met by a trajectory that
    says "N%" of something unrelated; that is rarer in this data than the miss
    the strict rule produces, and it is stated here rather than buried.
    """
    t = _strip_latex(raw)
    m = _PCT.match(t)
    if not m or not m.group(1):
        return None
    bare = answer_value(m.group(1))
    if bare is None:
        return None
    return {bare / 100, bare}


def answers_match(a, b):
    """True iff two answer strings denote the same answer.

    Numeric on both sides -> exact rational equality, except that a percent
    literal matches either of its two readings (see `_percent_readings`).
    Otherwise exact equality of the cleaned strings. A numeric and a
    non-numeric never match.
    """
    va, vb = answer_value(a), answer_value(b)
    if va is not None and vb is not None:
        if va == vb:
            return True
        pa, pb = _percent_readings(a), _percent_readings(b)
        if pa and vb in pa:
            return True
        if pb and va in pb:
            return True
        return False
    if va is not None or vb is not None:
        return False
    na, nb = normalize_answer(a), normalize_answer(b)
    return na is not None and na == nb


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
# Ordered most-specific first. Each returns the answer SPAN, not the sentence.
_MARKERS = [
    r"(?:final answer|the answer)\s*(?:is|:)\s*(.+?)\s*[.。]?\s*$",
    r"(?:answer|result|probability|value|total|sum|number of \w+)\s*(?:is|=|:)\s*(.+?)\s*[.。]?\s*$",
    # "There are 12 possible ways to ..." -- same answer-stated-first shape as
    # the therefore/so family, but with no leading connective.
    r"\bthere\s+(?:are|is)\s+(.+?)\s*[.。]?\s*$",
    # GREEDY `.*` on purpose: the answer follows the LAST copula, not the first.
    # "the remainder when the sum ... is divided by 15 is 3" answers 3, and a
    # lazy match returns 15. The existential "there are X ..." family, where the
    # answer follows the FIRST copula, is caught by the marker above this one
    # and never reaches here.
    r"(?:therefore|thus|so|hence)\b.*\b(?:is|are|=)\s*(.+?)\s*[.。]?\s*$",
]
_MARKERS = [re.compile(p, re.I | re.S) for p in _MARKERS]

# \boxed{...} is the strongest possible marker and outranks everything.
_BOXED = re.compile(r"\\boxed\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}")

# Within an answer span, an `=` chain means the RESULT is what follows the LAST
# `=`: "the difference is 187 - 118 = 69" answers 69. With no `=`, English maths
# prose states the answer FIRST and then restates the problem: "there are 15
# ways to put 4 balls in 3 boxes" answers 15, not 3. Taking the last token in
# both cases -- the obvious implementation -- gets the second family wrong and
# silently scores correct trajectories as `incorrect`, which is exactly the
# failure this module exists to avoid. Verified by hand against the sample in
# results/ANSWER_CHECKER.md.
_EQ_TAIL = re.compile(r"=(?!.*=)(.*)$", re.S)

# "1 in 29,322,216" -- a prose ratio, which appears in the data and would
# otherwise be extracted as the integer 1.
_PROSE_RATIO = re.compile(r"\b(\d[\d,\\!]*)\s+in\s+(\d[\d,\\!]*)\b", re.I)

# A maths span: $...$ or a bare fraction/number token.
_MATH_SPAN = re.compile(r"\$([^$]+)\$")
_NUM_TOKEN = re.compile(
    r"(?:-?\\[dt]?frac(?:\{\s*-?\d+\s*\}|-?\d)(?:\{\s*-?\d+\s*\}|-?\d)"
    r"|-?\d[\d,\\!]*(?:\.\d+)?\s*\\?%"
    r"|-?\d[\d,\\!]*\s*/\s*\d+"
    r"|-?\d[\d,\\!]*(?:\.\d+)?)"
)

MAX_LOOKBACK = 2


def _resolve_span(span):
    """The answer inside an already-isolated answer span.

    After the last `=` if the span is a computation chain; otherwise the FIRST
    numeric token, because the prose that follows restates the problem.
    """
    span = (span or "").strip().rstrip(".。")
    tail = _EQ_TAIL.search(span)
    if tail and tail.group(1).strip():
        toks = _NUM_TOKEN.findall(tail.group(1))
        if toks and answer_value(toks[0]) is not None:
            return toks[0]
    toks = _NUM_TOKEN.findall(span)
    for t in toks:
        if answer_value(t) is not None:
            return t
    return None


def _extract_from_step(text):
    """(answer_string, method) or (None, None) for one step's text."""
    if not text or not text.strip():
        return None, None
    s = text.strip()

    boxed = _BOXED.findall(s)
    if boxed:
        got = _resolve_span(boxed[-1]) or boxed[-1].strip()
        if answer_value(got) is not None:
            return got, "boxed"

    m = _PROSE_RATIO.search(s)
    if m and answer_value(m.group(2)) is not None:
        return f"\\frac{{{_strip_latex(m.group(1))}}}{{{_strip_latex(m.group(2))}}}", "prose_ratio"

    for i, pat in enumerate(_MARKERS):
        m = pat.search(s)
        if m:
            got = _resolve_span(m.group(1))
            if got is not None:
                return got, f"marker{i}"

    # No marker. An `=` chain still names its own result; otherwise fall back to
    # the last number, which is the weakest path and is reported separately.
    got = _resolve_span(s) if "=" in s else None
    if got is not None:
        return got, "eq_chain"

    toks = _NUM_TOKEN.findall(s)
    if toks and answer_value(toks[-1]) is not None:
        return toks[-1], "last_number"

    return None, None


def extract_answer(steps):
    """Extract a trajectory's final answer from its ordered list of steps.

    Takes the STEP TEXTS only -- never a dataset record -- so there is no path
    by which a Lean verdict could reach this function.

    Returns a dict: {answer, method, steps_back, ok}. `ok=False` means the
    trajectory is `answer_unknown`, which is a third category and must never be
    silently folded into `incorrect`.
    """
    if isinstance(steps, str):
        steps = [steps]
    steps = [s for s in (steps or [])]
    if not steps:
        return {"answer": None, "method": None, "steps_back": None, "ok": False}

    for back in range(0, min(MAX_LOOKBACK + 1, len(steps))):
        text = steps[len(steps) - 1 - back]
        ans, method = _extract_from_step(text)
        if ans is not None:
            return {"answer": ans, "method": method, "steps_back": back, "ok": True}

    return {"answer": None, "method": None, "steps_back": None, "ok": False}


def score_trajectory(steps, ground_truth):
    """The complete axis-2 verdict for one trajectory.

    Returns {verdict, extracted, normalized, gt_normalized, method, steps_back}
    where verdict is 'correct' | 'incorrect' | 'answer_unknown'.
    """
    ex = extract_answer(steps)
    if not ex["ok"]:
        return {"verdict": "answer_unknown", "extracted": None, "normalized": None,
                "gt_normalized": normalize_answer(ground_truth),
                "method": None, "steps_back": None}
    correct = answers_match(ex["answer"], ground_truth)
    return {
        "verdict": "correct" if correct else "incorrect",
        "extracted": ex["answer"],
        "normalized": normalize_answer(ex["answer"]),
        "gt_normalized": normalize_answer(ground_truth),
        "method": ex["method"],
        "steps_back": ex["steps_back"],
    }
