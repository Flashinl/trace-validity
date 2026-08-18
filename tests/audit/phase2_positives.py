"""Phase 2: mechanically classify the T=0.0 `valid` traces.

Categories (from the audit brief):
  proves_target  proves the dataset's statement as written
  restated       proves a syntactically different statement
  weakened       proves something strictly weaker
  vacuous        goal trivially true, or hypotheses contradictory
  unclear        needs a human

Reads only committed artifacts. No Lean, no GPU.
"""
import io, json, os, random, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
J = lambda p: [json.loads(l) for l in io.open(os.path.join(ROOT, p), encoding="utf-8") if l.strip()]

SEED = 20260818          # recorded, fixed
SAMPLE_N = 10

tr = {r["sample_index"]: r for r in J("traces/temp0.0_n50_1each/traces.jsonl")}
ve = {r["sample_index"]: r for r in J("results/verify2_temp0.0.jsonl")}
valid = sorted(i for i, r in ve.items() if r["outcome"] == "valid")

DECL = re.compile(r"^[ \t]*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+|noncomputable\s+)*"
                  r"(?:theorem|lemma|example)\b", re.M)


def strip_comments(s):
    s = re.sub(r"/-.*?-/", "", s, flags=re.S)
    return re.sub(r"--[^\n]*", "", s)


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def split_statement(stmt):
    """Return (binders, goal) from a `theorem name (binders) : goal := by` string."""
    s = norm(stmt)
    s = re.sub(r":=\s*by\s*$", "", s).strip()
    m = re.match(r"^(?:theorem|lemma|example)\s+\S+\s*(.*)$", s)
    body = m.group(1) if m else s
    # goal is after the LAST top-level colon that is not inside brackets
    depth, cut = 0, None
    for i, ch in enumerate(body):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif ch == ":" and depth == 0:
            cut = i
    if cut is None:
        return body, body
    return body[:cut].strip(), body[cut + 1:].strip()


def binder_names(binders):
    """Hypothesis / variable names declared in the binder list."""
    names = []
    for grp in re.findall(r"[(\[{]([^:()\[\]{}]+):", binders):
        for nm in grp.split():
            nm = nm.strip()
            if nm and re.match(r"^[A-Za-z_₀-₉ₐ-ₜ'ℓ][A-Za-z0-9_₀-₉ₐ-ₜ'!?]*$", nm):
                names.append(nm)
    return names


def proof_body(full_code, stmt):
    """Everything the model wrote after the statement."""
    n_fc, n_st = norm(full_code), norm(stmt)
    i = n_fc.find(n_st)
    return n_fc[i + len(n_st):] if i != -1 else n_fc


# ------------------------------------------------------------------ classify
TRIVIAL_GOAL = re.compile(r"^\s*(True|trivial)\s*$", re.I)
CONTRA = re.compile(r"\b(False|0\s*=\s*1|1\s*=\s*0)\b")
rows = []
for i in valid:
    r = tr[i]
    stmt = r["formal_statement"]
    fc = strip_comments(r["full_code"] or "")
    binders, goal = split_statement(stmt)
    names = binder_names(binders)
    body = proof_body(fc, stmt)
    used = [n for n in names if re.search(r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])", body)]
    unused = [n for n in names if n not in used]

    flags = []
    cls = "proves_target"
    # restated / weakened are impossible if the statement is verbatim and unique
    if norm(stmt) not in norm(r["full_code"] or ""):
        cls = "restated"; flags.append("statement not verbatim in full_code")
    if len(DECL.findall(fc)) != 1:
        cls = "restated"; flags.append("declaration count != 1")
    if TRIVIAL_GOAL.match(goal):
        cls = "vacuous"; flags.append("goal is literally True")
    if CONTRA.search(binders):
        cls = "vacuous"; flags.append("binder mentions False/0=1 — possible contradictory hypotheses")
    if not body.strip():
        cls = "unclear"; flags.append("empty proof body")

    rows.append({
        "sample": i, "state": ve[i]["state"], "level": r.get("level"),
        "class": cls, "flags": flags,
        "goal": goal[:110], "binders_n": len(names),
        "unused_binders": unused, "body": body.strip()[:150],
        "gen_tokens": r.get("generated_tokens"), "verify_s": ve[i]["seconds"],
    })

print("=" * 78)
print("PHASE 2 — MECHANICAL CLASSIFICATION OF ALL %d `valid` TRACES AT T=0.0" % len(valid))
print("=" * 78)
tally = {}
for w in rows:
    tally[w["class"]] = tally.get(w["class"], 0) + 1
print("\nAuto-classification over ALL %d:" % len(rows))
for k, v in sorted(tally.items()):
    print("  %-16s %d" % (k, v))

print("\nStructural invariants (the basis for ruling out restated/weakened):")
print("  statement verbatim in full_code : %d/%d"
      % (sum(1 for w in rows if "statement not verbatim in full_code" not in w["flags"]), len(rows)))
print("  exactly one declaration         : %d/%d"
      % (sum(1 for w in rows if "declaration count != 1" not in w["flags"]), len(rows)))
print("  goal literally `True`           : %d"
      % sum(1 for w in rows if "goal is literally True" in w["flags"]))

unused_any = [w for w in rows if w["unused_binders"]]
print("\nTraces with binders never mentioned in the proof body: %d/%d"
      % (len(unused_any), len(rows)))
for w in unused_any:
    print("  sample %-3d unused=%s" % (w["sample"], w["unused_binders"]))
print("  NOTE: an unused hypothesis makes the proof STRONGER, not weaker. It is")
print("  flagged only because it can also indicate the goal was closed by")
print("  evaluation rather than by the intended argument.")

# ------------------------------------------------------------------ hand-read
rnd = random.Random(SEED)
pool = [w["sample"] for w in rows]
picked = sorted(rnd.sample(pool, min(SAMPLE_N, len(pool))))
print("\n" + "=" * 78)
print("HAND-READ SUBSET — random %d of %d, seed=%d" % (len(picked), len(pool), SEED))
print("picked: %s" % picked)
print("=" * 78)
for i in picked:
    w = next(x for x in rows if x["sample"] == i)
    r = tr[i]
    print("\n" + "-" * 78)
    print("SAMPLE %d   state=%s  level=%s  verify=%ss  gen_tokens=%s"
          % (i, w["state"], w["level"], w["verify_s"], w["gen_tokens"]))
    print("PROBLEM      : %s" % norm(r.get("problem"))[:150])
    print("CoT STEP     : %s" % norm(r.get("informal_step"))[:150])
    print("STATEMENT    : %s" % norm(r["formal_statement"]))
    print("MODEL PROOF  : %s" % (w["body"] if w["body"] else "(none)"))
    print("REF PROOF    : %s" % norm(r.get("reference_proof"))[:200])
    print("auto-class   : %s   unused binders: %s" % (w["class"], w["unused_binders"] or "none"))

json.dump({"seed": SEED, "picked": picked, "rows": rows},
          io.open(os.path.join(ROOT, "results", "phase2_positives.json"), "w", encoding="utf-8"),
          indent=2, ensure_ascii=False)
print("\nwrote results/phase2_positives.json")
