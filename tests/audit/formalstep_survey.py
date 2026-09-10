"""Static survey of FormalStep. No Lean, no GPU, no generation.

Four questions, plus the cross-tabulation that decides whether the answer to the
first one silently reintroduces the bias the third one is about.

  1  ground_truth shape      -- how many problems have an exact-matchable answer,
                                at several thresholds rather than one
  2  categories              -- how many distinct problem categories exist, over
                                the WHOLE dataset and every split
  3  steps per problem       -- what a ">= N steps" filter excludes
  4  tactic invocations      -- how many proof bodies are a single tactic

Unit discipline. FormalStep is one row per CoT STEP, many steps per problem, so
"how many problems" and "how many rows" differ by ~60x. Question 1 is asked per
PROBLEM (an answer belongs to a problem), questions 3 and 4 per STEP or per
problem as noted on each table. Nothing is averaged across the two.

Run: python tests/audit/formalstep_survey.py
"""
import collections
import io
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

from stats import wilson  # noqa: E402

J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


# --------------------------------------------------------------------------- #
# Q1 -- what shape is the final answer?
# --------------------------------------------------------------------------- #
# FormalStep's ground_truth is LaTeX, not a number: `45,\!045` is 45045,
# `\frac1{216}` omits the numerator braces, `\$0.25` carries a currency escape,
# and one value is `\frac{\pi}{16}`, which no integer matcher should accept.
# Normalise first, classify second, and keep "looks numeric but is symbolic"
# out of the matchable buckets.
_STRIP = (
    (re.compile(r"\\!"), ""),          # LaTeX thin space inside 45,\!045
    (re.compile(r"\\,"), ""),
    (re.compile(r"\\\$|\$"), ""),      # currency
    (re.compile(r"\\text\{[^}]*\}"), ""),
    (re.compile(r"\s+"), ""),
    (re.compile(r"(?<=\d),(?=\d)"), ""),   # thousands separator only
)
_INT = re.compile(r"^-?\d+$")
_DEC = re.compile(r"^-?\d*\.\d+$")
# \frac{a}{b}, \dfrac{a}{b}, \tfrac{a}{b}, and the brace-less \frac1{216}
_FRAC = re.compile(r"^-?\\[dt]?frac\{?(-?\d+)\}?\{(-?\d+)\}$")
_PLAINFRAC = re.compile(r"^-?(\d+)/(\d+)$")


def normalise_gt(v):
    s = str(v)
    for pat, rep in _STRIP:
        s = pat.sub(rep, s)
    return s


def classify_gt(v):
    """(bucket, magnitude_or_None). Buckets are mutually exclusive."""
    s = normalise_gt(v)
    if not s:
        return "empty", None
    if _INT.match(s):
        return "integer", abs(int(s))
    if _DEC.match(s):
        return "decimal", abs(float(s))
    m = _FRAC.match(s) or _PLAINFRAC.match(s)
    if m:
        try:
            num, den = abs(int(m.group(1))), abs(int(m.group(2)))
        except ValueError:
            return "symbolic", None
        return "simple_fraction", max(num, den)
    if re.search(r"[a-zA-Z\\]", s):
        return "symbolic", None
    return "other", None


# --------------------------------------------------------------------------- #
# Q4 -- how many tactic invocations is a proof body?
# --------------------------------------------------------------------------- #
# Counts INVOCATIONS, not distinct tactic names: `intro n; omega` is two.
# Tactic position only -- start of a line, or after a sequencing combinator.
# Never after `[` or `(`, or `simp [Nat.pow_succ]` counts the lemma, and never
# after a bare `|`, which is far more often an rcases alternation
# (`rcases h with (a | b)`) than a `first | t1 | t2`.
_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_CASE_LABEL = re.compile(r"^\s*\|\s*[a-zA-Z_][\w'.]*(?:\s+\S+)*\s*=>\s*")
_SEQ = re.compile(r"<;>|;")
_NOT_TACTIC = {
    "theorem", "lemma", "example", "def", "instance", "import", "open",
    "set_option", "with", "at", "using", "this", "fun", "by", "do", "let",
    "if", "then", "else", "match", "sorry",
}
_IDENT = re.compile(r"^([a-zA-Z_][\w'.]*)")


def proof_body(proof, formal_statement):
    """Everything after the statement's `:= by`."""
    if not proof:
        return ""
    stmt = re.sub(r":=\s*by\s*sorry\s*\Z", "", (formal_statement or "").strip())
    stmt = stmt.strip()
    if stmt and stmt in proof:
        return proof[proof.find(stmt) + len(stmt):]
    m = re.search(r":=\s*by\b", proof)
    return proof[m.end():] if m else ""


def count_tactics(body):
    """Number of tactic invocations in a proof body."""
    b = _BLOCK_COMMENT.sub(" ", body or "")
    b = _LINE_COMMENT.sub(" ", b)
    n = 0
    for line in b.splitlines():
        line = _CASE_LABEL.sub("", line.strip())
        if not line:
            continue
        for piece in _SEQ.split(line):
            piece = piece.strip()
            if not piece:
                continue
            m = _IDENT.match(piece)
            if m and m.group(1) in _NOT_TACTIC:
                continue
            n += 1
    return n


def table(title, rows, headers):
    print("\n" + title)
    w = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h))
         for i, h in enumerate(headers)]
    print("  " + "  ".join(str(h).ljust(w[i]) for i, h in enumerate(headers)))
    print("  " + "  ".join("-" * w[i] for i in range(len(headers))))
    for r in rows:
        print("  " + "  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))


def pctf(k, n):
    return "%.1f%%" % (100.0 * k / n) if n else "-"


def main():
    from datasets import load_dataset
    ds = load_dataset("liuchengwu/FormalStep")
    splits = {k: len(v) for k, v in ds.items()}
    rows = ds[list(ds.keys())[0]]
    cols = {c: rows[c] for c in ("problem_unique_id", "ground_truth", "level",
                                 "type", "proof", "formal_statement", "state")}
    n_rows = len(cols["problem_unique_id"])
    by_problem = {}
    for i in range(n_rows):
        by_problem.setdefault(cols["problem_unique_id"][i], []).append(i)
    n_prob = len(by_problem)

    print("=" * 78)
    print("FormalStep static survey")
    print("=" * 78)
    print("splits: %s" % splits)
    print("rows (CoT steps): %d      distinct problems: %d      steps/problem: %.1f"
          % (n_rows, n_prob, n_rows / n_prob))

    # ------------------------------------------------------------------ Q2
    print("\n" + "=" * 78)
    print("Q2. CATEGORIES")
    print("=" * 78)
    print("Every split, not a slice: the dataset ships ONE split and it is all "
          "%d rows." % n_rows)
    types = collections.Counter(cols["type"])
    levels = collections.Counter(cols["level"])
    prefix = collections.Counter(
        re.sub(r"_\d+$", "", p).replace("math_train_", "")
        for p in by_problem)
    table("type field, all %d rows:" % n_rows,
          [[t, c, pctf(c, n_rows)] for t, c in types.most_common()],
          ["type", "rows", "share"])
    table("problem_unique_id prefix, all %d problems:" % n_prob,
          [[t, c, pctf(c, n_prob)] for t, c in prefix.most_common()],
          ["prefix", "problems", "share"])
    table("level field, all %d rows:" % n_rows,
          [[t, c, pctf(c, n_rows)] for t, c in sorted(levels.items())],
          ["level", "rows", "share"])
    print("\n  distinct types: %d      distinct id prefixes: %d      distinct levels: %d"
          % (len(types), len(prefix), len(levels)))

    # ------------------------------------------------------------------ Q1
    print("\n" + "=" * 78)
    print("Q1. GROUND_TRUTH SHAPE  (per PROBLEM, n=%d)" % n_prob)
    print("=" * 78)
    gt = {p: cols["ground_truth"][idx[0]] for p, idx in by_problem.items()}
    cls = {p: classify_gt(v) for p, v in gt.items()}
    buckets = collections.Counter(c for c, _ in cls.values())
    table("bucket:",
          [[b, c, pctf(c, n_prob)] for b, c in buckets.most_common()],
          ["bucket", "problems", "share"])
    ints = {p: m for p, (b, m) in cls.items() if b == "integer"}
    print("\n  integers by magnitude (cumulative, so Jerome can pick a threshold):")
    prev = 0
    for thr in (10, 100, 1000, 10 ** 4, 10 ** 6, 10 ** 12, 10 ** 18):
        k = sum(1 for m in ints.values() if m < thr)
        lo, hi = wilson(k, n_prob)
        print("     |x| < %-18s %4d problems  %6s  [%.1f-%.1f]  (+%d in this band)"
              % ("{:,}".format(thr), k, pctf(k, n_prob), 100 * lo, 100 * hi, k - prev))
        prev = k
    big = sorted(((m, p) for p, m in ints.items() if m >= 10 ** 6), reverse=True)[:6]
    print("\n  largest integer answers: %s"
          % ", ".join("%s (%s)" % ("{:,}".format(m), p.replace("math_train_", ""))
                      for m, p in big))
    fr = {p: m for p, (b, m) in cls.items() if b == "simple_fraction"}
    print("\n  simple fractions: %d problems; largest term < 100 in %d of them"
          % (len(fr), sum(1 for m in fr.values() if m < 100)))
    sym = [p for p, (b, _) in cls.items() if b in ("symbolic", "other", "empty")]
    print("  non-numeric / unmatchable: %d problems" % len(sym))
    if sym:
        print("     examples: %s" % ", ".join(repr(gt[p]) for p in sym[:6]))

    print("\n  EXACT-MATCHABLE TOTALS, the numbers to choose between:")
    for label, keep in (
            ("integers only, any size", lambda b, m: b == "integer"),
            ("integers |x| < 1000", lambda b, m: b == "integer" and m < 1000),
            ("integers |x| < 10^6", lambda b, m: b == "integer" and m < 10 ** 6),
            ("integers + simple fractions", lambda b, m: b in ("integer", "simple_fraction")),
            ("integers + fractions + decimals",
             lambda b, m: b in ("integer", "simple_fraction", "decimal")),
            ("everything except symbolic/other",
             lambda b, m: b not in ("symbolic", "other", "empty"))):
        k = sum(1 for b, m in cls.values() if keep(b, m))
        lo, hi = wilson(k, n_prob)
        print("     %-34s %3d / %d = %6s  [%.1f-%.1f]"
              % (label, k, n_prob, pctf(k, n_prob), 100 * lo, 100 * hi))

    # ------------------------------------------------------------------ Q3
    print("\n" + "=" * 78)
    print("Q3. STEPS PER PROBLEM, and what a >=N filter excludes")
    print("=" * 78)
    sizes = sorted(len(v) for v in by_problem.values())
    print("  min=%d  p25=%d  median=%d  p75=%d  max=%d  mean=%.1f"
          % (sizes[0], sizes[len(sizes) // 4], sizes[len(sizes) // 2],
             sizes[3 * len(sizes) // 4], sizes[-1], sum(sizes) / len(sizes)))
    hist = collections.Counter(sizes)
    table("steps-per-problem histogram (low end, where a filter bites):",
          [[k, hist.get(k, 0)] for k in range(1, 11)] +
          [[">=11", sum(c for k, c in hist.items() if k >= 11)]],
          ["steps", "problems"])
    print("\n  exclusion rate of a `>= N steps` filter:")
    for N in (2, 3, 4, 5, 10, 20):
        drop = sum(1 for s in sizes if s < N)
        lo, hi = wilson(drop, n_prob)
        print("     >= %-3d keeps %3d, excludes %3d of %d = %6s  [%.1f-%.1f]"
              % (N, n_prob - drop, drop, n_prob, pctf(drop, n_prob),
                 100 * lo, 100 * hi))

    # ------------------------------------------------------------------ Q4
    print("\n" + "=" * 78)
    print("Q4. TACTIC INVOCATIONS PER PROOF BODY")
    print("=" * 78)
    ref = []
    for i in range(n_rows):
        b = proof_body(cols["proof"][i], cols["formal_statement"][i])
        ref.append(count_tactics(b))
    def dist(counts, title, unit):
        c = collections.Counter(counts)
        n = len(counts)
        rows_ = [[k if k < 5 else ">=5", sum(v for kk, v in c.items()
                                             if (kk == k if k < 5 else kk >= 5)),
                  pctf(sum(v for kk, v in c.items()
                           if (kk == k if k < 5 else kk >= 5)), n)]
                 for k in (0, 1, 2, 3, 4, 5)]
        table("%s (n=%d %s):" % (title, n, unit), rows_,
              ["tactics", "count", "share"])
        srt = sorted(counts)
        print("     median=%d  mean=%.2f  p90=%d  max=%d"
              % (srt[len(srt) // 2], sum(srt) / len(srt),
                 srt[int(0.9 * len(srt))], srt[-1]))
        return c
    dist(ref, "FormalStep REFERENCE proofs (the dataset's own)", "steps")
    ex1 = [i for i in range(n_rows) if ref[i] == 1][:2]
    exN = sorted(range(n_rows), key=lambda i: -ref[i])[:2]
    print("\n  examples, single-tactic:")
    for i in ex1:
        print("     %s" % " ".join(proof_body(cols["proof"][i],
              cols["formal_statement"][i]).split())[:96])
    print("  examples, longest:")
    for i in exN:
        print("     [%d tactics] %s" % (ref[i], " ".join(proof_body(
            cols["proof"][i], cols["formal_statement"][i]).split())[:96]))

    gen_paths = [
        ("temp_0 baseline (1 problem)", os.path.join(_ROOT, "traces", "temp_0.jsonl")),
        ("n50 T=0.0", os.path.join(_ROOT, "traces", "temp0.0_n50_1each", "traces.jsonl")),
        ("n50 T=0.2", os.path.join(_ROOT, "traces", "temp0.2_n50_1each", "traces.jsonl")),
        ("exp2 n50 k=16", os.path.join(_ROOT, "traces", "exp2_n50_k16", "traces.jsonl")),
    ]
    gen_counts, gen_rows = [], []
    for label, path in gen_paths:
        if not os.path.exists(path):
            continue
        rs = J(path)
        cs = [count_tactics(proof_body(r.get("full_code") or "",
                                       r.get("formal_statement"))) for r in rs]
        gen_counts += cs
        gen_rows += [(r, c) for r, c in zip(rs, cs)]
        print("\n  loaded %-28s %5d generated proofs" % (label, len(rs)))
    if gen_counts:
        dist(gen_counts, "MODEL-GENERATED proofs (Goedel-Prover-SFT)", "samples")

    # ------------------------------------------------------- Q1 x Q4 crosstab
    print("\n" + "=" * 78)
    print("CROSS-TAB: does a simple answer imply a single-tactic proof?")
    print("=" * 78)
    simple = lambda p: cls.get(p, ("other", None))[0] == "integer" and \
        (cls[p][1] is not None and cls[p][1] < 1000)
    for src_label, pairs in (
            ("dataset reference proofs, per step",
             [(cols["problem_unique_id"][i], ref[i]) for i in range(n_rows)]),
            ("model-generated proofs, per sample",
             [(r.get("problem_unique_id"), c) for r, c in gen_rows
              if r.get("problem_unique_id")])):
        if not pairs:
            continue
        grid = collections.Counter()
        for p, c in pairs:
            grid[(simple(p), c == 1)] += 1
        n = sum(grid.values())
        a = grid[(True, True)]; b = grid[(True, False)]
        cc = grid[(False, True)]; d = grid[(False, False)]
        table("%s (n=%d):" % (src_label, n),
              [["simple answer (int <1000)", a, b, a + b,
                pctf(a, a + b) if a + b else "-"],
               ["other answer", cc, d, cc + d, pctf(cc, cc + d) if cc + d else "-"]],
              ["", "1 tactic", ">1 tactic", "total", "single-tactic rate"])
        if (a + b) and (cc + d):
            r1 = a / (a + b); r2 = cc / (cc + d)
            print("     single-tactic rate: %.1f%% simple vs %.1f%% other  "
                  "(ratio %.2f)" % (100 * r1, 100 * r2,
                                    (r1 / r2) if r2 else float("inf")))
            try:
                from scipy.stats import fisher_exact
                _, pv = fisher_exact([[a, b], [cc, d]])
                print("     Fisher exact p = %.3g" % pv)
            except Exception:
                pass


if __name__ == "__main__":
    main()
