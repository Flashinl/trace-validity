"""The tactic oracle: for a `tactic_mismatch` failure, could ANY standard tactic
have closed the goal the model was handed?

`tactic_mismatch` means the statement elaborated, the goal stood, and the model's
tactic did not close it. Those rows are scored `compile_error` and the trace is
scored invalid -- so prover weakness is being counted as trace invalidity. This
measures how much of that there is.

METHOD. Keep the header and the statement byte-for-byte as the model saw them
(`full_code` truncated at the end of the statement, which preserves the Goedel
header AND the `informal_prefix` doc comment). Throw away the model's proof body.
Try a FIXED ladder of standard tactics, in order, and record the first that
closes the goal.

HONESTY RULES, enforced in code:
  * The ladder is a module constant. It is identical for every sample and is
    never chosen per-sample.
  * The statement is never edited. Only the text after `:= by` changes.
  * Every close is followed by the vacuity probe -- the same contradiction
    tactics vacuity_scan.py uses, on a corrected binder split. A goal
    closed because its hypotheses are contradictory is NOT a recovery -- it is
    another sample 42 -- and is counted in its own row.
  * The per-attempt wall clock is config.VERIFY_TIMEOUT_SECONDS, the same budget
    the main verifier applies. Exceeding it is `budget`, never `none_closed`.

Run: python tests/audit/tactic_oracle.py [--limit N] [--out PATH]
"""
import argparse, io, json, os, re, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import VERIFY_TIMEOUT_SECONDS, GOEDEL_LEAN4_HEADER  # noqa: E402
from verifier import LeanVerifier, VALID, TIMEOUT, VERIFIER_CRASH  # noqa: E402
import tactic_common as tc  # noqa: E402

# --------------------------------------------------------------------------- #
# THE LADDER. Fixed in advance, identical for every sample, ordered cheapest
# first. Rungs 1-10 are the audit's pre-registered list, verbatim.
#
# Rung 6 is reproduced exactly as specified even though `sq_nonneg _` leaves an
# unsolved placeholder that Lean cannot synthesise from the goal; it is kept so
# the pre-registered ladder is run as written and its behaviour is on the record.
# Rung 6b is the same rung with the hints dropped -- the only form of
# `nlinarith` that is sample-independent, since any concrete hint term would
# have to be read off the individual goal, which is exactly the per-sample
# tuning this audit forbids. 6b is applied identically to every sample.
# --------------------------------------------------------------------------- #
LADDER = [
    ("norm_num",        "norm_num"),
    ("decide",          "decide"),
    ("omega",           "omega"),
    ("ring_nf",         "ring_nf"),
    ("positivity",      "positivity"),
    ("nlinarith_hint",  "nlinarith [sq_nonneg _, sq_nonneg _]"),
    ("nlinarith",       "nlinarith"),
    ("field_simp_ring", "field_simp; ring"),
    ("simp_arith",      "simp_arith"),
    ("aesop",           "aesop"),
    ("norm_num_choose", "norm_num [Nat.choose, Nat.factorial]"),
]

# The contradictory-hypothesis probe. The three tactics are exactly the ones
# vacuity_scan.py uses, so the two audits agree on what "vacuous" means. The
# binder/goal split below differs from vacuity_scan's in one respect: it cuts at
# the FIRST depth-0 colon, not the last. `theorem t : ∀ a : ℕ, P a` has a
# depth-0 colon inside the quantifier, and cutting at the last one hands the
# probe `∀ a` as its binder list, which does not parse. Same bug goal_shape._cut
# documents.
CONTRA_TACTICS = ("simp_all", "omega", "norm_num at *")
PROBE_TIMEOUT = 15

_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+[\w.]+[ \t]*$", re.M)


def statement_prefix(sample):
    """Header + informal_prefix + statement, exactly as the model received it.

    Returns None when `full_code` is absent or does not contain the statement
    (the parse_failure rows); those are excluded rather than reconstructed, so
    that no sample is run against a header it never saw.
    """
    stmt = _IMPORT_RE.sub("", sample["formal_statement"] or "").strip()
    fc = sample["full_code"] or ""
    if not stmt or not fc:
        return None
    i = fc.find(stmt)
    if i < 0:
        return None
    prefix = fc[: i + len(stmt)]
    if not re.search(r"\bby\s*\Z", prefix):
        prefix = prefix.rstrip() + (" by" if prefix.rstrip().endswith(":=") else " := by")
    return prefix


def split_binders(stmt):
    """(binders, goal) for the contradiction probe. Cuts at the FIRST depth-0
    colon; see the note above CONTRA_TACTICS for why not the last."""
    s = re.sub(r":=\s*by\s*$", "", re.sub(r"\s+", " ", stmt or "")).strip()
    m = re.match(r"^(?:theorem|lemma|example)\s*(\S*)\s*(.*)$", s)
    body = m.group(2) if m else s
    depth, cut = 0, None
    for i, ch in enumerate(body):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif ch == ":" and depth == 0:
            cut = i
            break
    return ("", body) if cut is None else (body[:cut].strip(), body[cut + 1:].strip())


def hypotheses_contradictory(v, statement):
    """Can `False` be derived from the binders alone? -> the close is vacuous."""
    binders, _ = split_binders(statement)
    if not binders.strip():
        return False, "no binders"
    for tac in CONTRA_TACTICS:
        code = "%stheorem contra_probe %s : False := by\n  %s\n" % (
            GOEDEL_LEAN4_HEADER, binders, tac)
        try:
            if v.verify(code, timeout=PROBE_TIMEOUT)["outcome"] == VALID:
                return True, "False derived by `%s`" % tac
        except Exception:  # noqa: BLE001 - a crashed probe is not evidence
            continue
    return False, "no contradiction found by %s" % "/".join(CONTRA_TACTICS)


def run_sample(v, sample, timeout):
    prefix = statement_prefix(sample)
    rec = {
        "set": sample["set"], "pipeline": sample["pipeline"], "id": sample["id"],
        "band": sample["band"], "shape": sample["shape"],
        "model_primary": sample["primary"], "model_tactics": sample["tactics"],
        "goal": sample["goal"][:200],
    }
    if prefix is None:
        rec.update(verdict="excluded_no_code", rung=None, attempts=[])
        return rec

    attempts, hit_budget = [], False
    for name, tac in LADDER:
        t0 = time.perf_counter()
        try:
            res = v.verify(prefix + "\n  " + tac + "\n", timeout=timeout)
        except Exception as e:  # noqa: BLE001
            res = {"outcome": VERIFIER_CRASH, "errors": ["%s: %s" % (type(e).__name__, e)],
                   "seconds": round(time.perf_counter() - t0, 3)}
        head = (res.get("errors") or [""])[0]
        attempts.append({"rung": name, "outcome": res["outcome"],
                         "seconds": res.get("seconds"),
                         "error_head": " ".join(str(head).split())[:160]})
        if res["outcome"] == TIMEOUT:
            hit_budget = True
        if res["outcome"] == VALID:
            vac, why = hypotheses_contradictory(v, sample["statement"])
            rec.update(verdict="vacuous_close" if vac else "recovered",
                       rung=name, tactic=tac, vacuity=why, attempts=attempts)
            return rec

    rec.update(verdict="budget" if hit_budget else "none_closed",
               rung=None, attempts=attempts)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=os.path.join(_ROOT, "results", "tactic_oracle.jsonl"))
    ap.add_argument("--timeout", type=int, default=VERIFY_TIMEOUT_SECONDS)
    args = ap.parse_args()

    samples = tc.load_samples()
    order = {s: i for i, s in enumerate(tc.SET_ORDER)}
    samples.sort(key=lambda s: (order.get(s["set"], 99), str(s["id"])))
    if args.limit:
        samples = samples[: args.limit]

    done = set()
    if os.path.exists(args.out):
        for r in tc.J(args.out):
            done.add((r["set"], str(r["id"])))
        print("[oracle] resuming; %d already done" % len(done))

    t0 = time.perf_counter()
    v = LeanVerifier(setup=False, verbose=False)
    print("[oracle] verifier ready in %.0fs; %d samples, per-attempt budget %ds"
          % (time.perf_counter() - t0, len(samples), args.timeout))
    print("[oracle] ladder: " + " -> ".join(n for n, _ in LADDER))

    fh = io.open(args.out, "a", encoding="utf-8")
    for k, s in enumerate(samples, 1):
        if (s["set"], str(s["id"])) in done:
            continue
        t1 = time.perf_counter()
        rec = run_sample(v, s, args.timeout)
        rec["wall_seconds"] = round(time.perf_counter() - t1, 1)
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        print("  [%3d/%3d] %-22s %-38s %-16s %-16s %5.1fs"
              % (k, len(samples), s["set"], str(s["id"])[:36], rec["verdict"],
                 rec.get("rung") or "-", rec["wall_seconds"]), flush=True)
    fh.close()
    print("[oracle] wrote %s in %.0fs" % (args.out, time.perf_counter() - t0))


if __name__ == "__main__":
    main()
