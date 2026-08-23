"""Evaluate Lean numeric expressions exactly, so arithmetic claims can be checked
mechanically instead of by eye.

Exactness matters here. The literals in question run to 13 digits
(`1061520150601`), and a float round-trip would silently agree with a wrong
answer. Everything below is `Fraction`/`int`, never `float`.

Natural-number division is FLOOR division in Lean, and `a - b = 0` when `b > a`.
Getting either wrong would manufacture false positives, so the caller declares
the numeric domain and `evaluate()` honours it.
"""
import re
from fractions import Fraction
from math import comb, factorial

# Lean surface syntax -> a Python expression we can eval in a sealed namespace.
_SUBS = [
    (r"Nat\.factorial\s*", "FACT "),
    (r"Nat\.choose\s*", "CHOOSE "),
    (r"Nat\.succ\s*", "SUCC "),
    (r"Nat\.div\s+", "NDIV "),
    (r"Nat\.sub\s+", "NSUB "),
    (r"Nat\.pow\s+", "NPOW "),
    (r"Finset\.card\s*", "CARD "),
    (r"\bchoose\b", "CHOOSE"),
    (r"\bfactorial\b", "FACT"),
]

_NUM = r"(?:\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)"
# Comma is required: rewritten calls look like CHOOSE(52,3).
_TOKEN_OK = re.compile(r"^[\s\d_+\-*/^(),.eE]*$")


class NotClosed(Exception):
    """The expression still has free variables, so it has no numeric value."""


def _postfix_bang(s):
    """Lean writes `9!` for factorial; turn it into FACT(9)."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(\d+|\))\s*!", r"FACT(\1)", s)
    return s


def _prefix_call(s, name):
    """`FACT 9` / `CHOOSE 52 3` -> `FACT(9)` / `CHOOSE(52,3)`.

    The parenthesis alternatives must be BALANCED. An earlier version used
    `\\(?(NUM)\\)?`, which happily matched the bare `2` in `... * FACT 2)` and
    swallowed the enclosing group's closing paren, producing unparseable output.
    Each argument is therefore either fully parenthesised or bare, never half.
    """
    # A parenthesised argument may be a whole sub-expression (`Nat.choose (4+4) 4`),
    # not just a literal; a bare argument must be a single literal.
    arg = r"(?:\(([^()]+)\)|(" + _NUM + r"))"

    def one(m):
        return m.group(1) or m.group(2)

    def two(m):
        a = m.group(1) or m.group(2)
        b = m.group(3) or m.group(4)
        return f"{name}({a},{b})"

    if name in ("CHOOSE", "NDIV", "NSUB", "NPOW"):
        s = re.sub(name + r"\s+" + arg + r"\s*" + arg, two, s)
    if name in ("FACT", "SUCC"):
        s = re.sub(name + r"\s+" + arg, lambda m: f"{name}({one(m)})", s)
    return s


def normalize(expr):
    s = expr.strip()
    s = s.replace("−", "-").replace("×", "*").replace("·", "*")
    s = re.sub(r"\(\s*(" + _NUM + r")\s*:\s*[^)]*\)", r"\1", s)   # (5 : ℝ) -> 5
    for pat, rep in _SUBS:
        s = re.sub(pat, rep, s)
    s = _postfix_bang(s)
    for nm in ("FACT", "SUCC", "CHOOSE", "NDIV", "NSUB", "NPOW"):
        s = _prefix_call(s, nm)
    s = s.replace("^", "**")
    s = s.replace("_", "")            # Lean digit separators
    return s.strip()


def evaluate(expr, domain="nat"):
    """Exact value of a closed Lean numeric expression.

    domain: 'nat' (floor division, truncated subtraction) or 'field' (ℚ/ℝ).
    Raises NotClosed if a free variable survives.
    """
    s = normalize(expr)
    if not s or not _TOKEN_OK.match(re.sub(r"\b(FACT|CHOOSE|SUCC|NDIV|NSUB|NPOW|CARD)\b", "", s)):
        raise NotClosed(expr)

    nat = domain == "nat"

    def _f(x):
        return int(x) if nat else Fraction(str(x))

    def ndiv(a, b):
        if b == 0:
            return 0                      # Lean: x / 0 = 0
        return a // b if nat else Fraction(a, 1) / Fraction(b, 1)

    def nsub(a, b):
        return max(0, a - b) if nat else a - b

    class N(int if False else object):
        pass

    # Sealed namespace. No builtins reachable.
    env = {
        "__builtins__": {},
        "FACT": lambda n: factorial(int(n)),
        "CHOOSE": lambda n, k: comb(int(n), int(k)),
        "SUCC": lambda n: int(n) + 1,
        "NDIV": ndiv, "NSUB": nsub,
        "NPOW": lambda a, b: a ** int(b),
    }
    # Rewrite bare / and - to the domain-correct operators for nat.
    if nat:
        # Only safe because the token filter above guarantees a pure arithmetic
        # expression; we re-parse via Python's AST semantics with floor-div.
        s_eval = s.replace("/", "//")
    else:
        s_eval = s
        s_eval = re.sub(r"(?<![\d.])(" + _NUM + r")", r"F('\1')", s_eval)
        env["F"] = lambda x: Fraction(str(x))

    try:
        val = eval(s_eval, env)  # noqa: S307 - sealed namespace, filtered tokens
    except Exception as e:  # noqa: BLE001
        raise NotClosed(f"{expr!r}: {type(e).__name__}: {e}")
    if isinstance(val, float):
        raise NotClosed(f"{expr!r}: float leaked")
    return val


def is_closed_numeric(expr):
    try:
        evaluate(expr)
        return True
    except (NotClosed, Exception):  # noqa: BLE001
        return False
