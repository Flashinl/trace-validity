"""Contentless-goal rates: the pass set, its complement, and FormalStep at large.

Task 3 asks what fraction of *verified* steps assert nothing. The committed
answer is 14 of 37 at T=0.0. That number cannot carry the weight the paper puts
on it, for a reason that is not sample size: all six committed verification
passes are the SAME 50 problems, so pooling them raises the distinct denominator
from 37 to 38 and no further.

The fix is not more runs. The probes replace the model's proof entirely -- they
interrogate the DATASET's goal, not the model's work -- so the same battery runs
over any FormalStep row with no GPU and no generation. That makes the real
quantity measurable:

  pass set        contentless share among goals the model proved
  complement      contentless share among the same 50 that it never proved
  population      contentless share over the first step of all 500 problems,
                  the identical construction to the eval set at stride 1

The enrichment ratio (pass / population) is the finding. A ratio near 1 means
`valid step` is a uniform category and the Compiler-Bypass Rate's denominator is
sound. A ratio well above 1 means passes are drawn preferentially from goals
that assert nothing, and the denominator is contaminated -- which is a claim
14/37 alone cannot support, because it has no baseline to be enriched against.

Phase 0 re-probes the two Stage B rows that carry outcome=statement_error with
the detail "verification exceeded 60s", under the repaired three-state
statement_is_broken() and a longer timeout.

Run: python tests/audit/contentless_rates.py --population-limit 500
"""
import argparse, io, json, os, re, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import GOEDEL_LEAN4_HEADER
from verifier import LeanVerifier, BROKEN, NOT_BROKEN, UNKNOWN
from vacuity_scan import PROBES, classify, split_statement, stmt_with, ok

H = GOEDEL_LEAN4_HEADER
J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]

# Classes 1-4 assert nothing. 5 is real arithmetic with no inference and is
# reported as its own column -- which side it falls on is the paper's call, not
# this script's, so it is never folded into either bucket here.
CONTENTLESS = ("1_goal_is_True", "2_hypotheses_contradictory",
               "3_goal_restates_a_hypothesis", "4_syntactic_tautology")
GROUND = ("5_ground_computation",)


def probe_one(v, stmt):
    """The full battery on one statement. Returns (class, probes, contra)."""
    binders, goal = split_statement(stmt)
    p = {name: ok(v, stmt_with(stmt, tac)) for name, tac in PROBES}
    contra = False
    if binders.strip():
        for tac in ("simp_all", "omega", "norm_num at *"):
            if ok(v, f"{H}theorem contra_probe {binders} : False := by\n  {tac}\n"):
                contra = True
                break
    return classify(p, contra), p, contra, goal


def tally(rows):
    t = {}
    for r in rows:
        t[r["class"]] = t.get(r["class"], 0) + 1
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--population-limit", type=int, default=500)
    ap.add_argument("--stageb-timeout", type=int, default=300,
                    help="longer budget for the two statement_error re-probes")
    ap.add_argument("--out", default="results/contentless_rates.json")
    args = ap.parse_args()

    t0 = time.perf_counter()
    v = LeanVerifier(setup=False, verbose=False)
    print(f"[setup] verifier ready in {time.perf_counter()-t0:.0f}s\n", flush=True)

    out = {"probe_timeout": None, "phases": {}}

    def flush():
        """Write after every phase. The first run lost a completed phase 0 and
        phase 1 because the only write was after phase 2, which crashed."""
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        io.open(args.out, "w", encoding="utf-8", newline="\n").write(
            json.dumps(out, ensure_ascii=False, indent=1))

    # ---- phase 0: the two Stage B statement_error rows ---------------------
    print("=" * 78)
    print("PHASE 0  Stage B statement_error re-probe (3-state, longer budget)")
    print("=" * 78, flush=True)
    ev = {r["uuid"]: r for r in json.load(io.open("results/stage_b_evalset.json", encoding="utf-8"))}
    sb = J("results/stage_b_verified.jsonl")
    targets = [r for r in sb if r["outcome"] == "statement_error"]
    reprobe = []
    for r in targets:
        stmt = ev[r["uuid"]]["statement"]
        t = time.perf_counter()
        verdict, detail = v.statement_is_broken(stmt, timeout=args.stageb_timeout)
        el = time.perf_counter() - t
        reprobe.append({"uuid": r["uuid"], "band": r["band"],
                        "old_outcome": r["outcome"],
                        "old_detail": r.get("statement_error_detail"),
                        "verdict": verdict, "detail": detail,
                        "seconds": round(el, 1)})
        print(f"  {r['uuid'][:8]}  {r['band']:<7} was={r.get('statement_error_detail')!r}")
        print(f"            now={verdict}  ({el:.0f}s)  {detail[:90]}", flush=True)
    out["phases"]["stage_b_reprobe"] = reprobe
    flush()

    # ---- phase 1: the 50 sampled FormalStep problems -----------------------
    print("\n" + "=" * 78)
    print("PHASE 1  All 50 sampled FormalStep problems (pass set AND complement)")
    print("=" * 78, flush=True)
    traces = {r["sample_index"]: r for r in J("traces/temp0.0_n50_1each/traces.jsonl")}
    passed = set()
    for p in ("results/verify_temp0.0.jsonl", "results/verify_temp0.2.jsonl",
              "results/verify2_temp0.0.jsonl", "results/verify2_temp0.2.jsonl",
              "results/verify3_temp0.0.jsonl", "results/verify3_temp0.2.jsonl"):
        for r in J(p):
            if r["outcome"] == "valid":
                passed.add(r["sample_index"])
    print(f"  union of passing sample_index across all 6 committed runs: {len(passed)}")

    fifty = []
    for i in sorted(traces):
        stmt = traces[i]["formal_statement"]
        cls, p, contra, goal = probe_one(v, stmt)
        fifty.append({"sample": i, "class": cls, "passed": i in passed,
                      "contra": contra, "goal": goal[:80],
                      "level": traces[i].get("level"), **p})
        print(f"  {i:<4}{'PASS' if i in passed else '   .':<6}{cls:<30}{goal[:44]}", flush=True)
    out["phases"]["formalstep_50"] = fifty
    flush()

    # ---- phase 2: population baseline, same construction at stride 1 -------
    print("\n" + "=" * 78)
    print("PHASE 2  Population baseline: first step of each problem, stride 1")
    print("=" * 78, flush=True)
    # FormalStepDataset validates and RAISES on a row that is not a theorem
    # (problem 378's first step is `def P : N -> Q := sorry`). That is right for
    # the generation path and wrong here, where one bad row must not abort a
    # 500-row scan. Load the split directly and filter, counting the skips.
    from datasets import load_dataset
    from data_loader import normalize_formal_statement, DatasetFieldError
    from config import DATASET_NAME, DATASET_SPLIT

    full = load_dataset(DATASET_NAME, split=DATASET_SPLIT)
    pids = full["problem_unique_id"]
    first_row_of = {}
    for idx, pid in enumerate(pids):
        if pid not in first_row_of:
            first_row_of[pid] = idx
    ordered = [first_row_of[pid] for pid in dict.fromkeys(pids)][:args.population_limit]
    print(f"  {len(first_row_of)} problems in split; taking the first step of "
          f"{len(ordered)}", flush=True)

    stmts, skipped = [], []
    for idx in ordered:
        raw = full[idx]
        try:
            stmt = normalize_formal_statement(raw.get("formal_statement"), index=idx)
        except DatasetFieldError as e:
            skipped.append({"row": idx, "pid": raw.get("problem_unique_id"),
                            "why": str(e)[:160]})
            continue
        stmts.append((idx, raw.get("problem_unique_id"), raw.get("state"),
                      raw.get("level"), stmt))
    print(f"  usable {len(stmts)}, skipped {len(skipped)} "
          f"(not a Lean statement)\n", flush=True)
    out["phases"]["population_skipped"] = skipped

    pop = []
    t_pop = time.perf_counter()
    for k, (idx, pid, state, level, stmt) in enumerate(stmts):
        try:
            cls, p, contra, goal = probe_one(v, stmt)
        except Exception as e:  # noqa: BLE001
            skipped.append({"row": idx, "pid": pid, "why": f"probe error: {type(e).__name__}"})
            continue
        pop.append({"row": idx, "pid": pid, "state": state, "level": level,
                    "class": cls, "contra": contra, "goal": goal[:80], **p})
        if (k + 1) % 25 == 0:
            el = time.perf_counter() - t_pop
            done = sum(1 for r in pop if r["class"] in CONTENTLESS)
            print(f"  [{k+1:>4}/{len(stmts)}] {el/60:>5.1f} min  "
                  f"contentless so far: {done}/{len(pop)}", flush=True)
            out["phases"]["formalstep_population"] = pop
            flush()
    out["phases"]["formalstep_population"] = pop
    flush()

    # ---- summary ------------------------------------------------------------
    def share(rows, bucket):
        n = sum(1 for r in rows if r["class"] in bucket)
        return n, len(rows)

    ps = [r for r in fifty if r["passed"]]
    ns = [r for r in fifty if not r["passed"]]
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for label, rows in (("pass set (50-sample)", ps), ("never passed", ns),
                        ("all 50 sampled", fifty), ("population (stride 1)", pop)):
        c, n = share(rows, CONTENTLESS)
        g, _ = share(rows, GROUND)
        print(f"  {label:<26} n={n:<5} contentless {c:>4}/{n:<5} = {100*c/n if n else 0:>5.1f}%"
              f"   ground-only {g:>4} ({100*g/n if n else 0:.1f}%)")
    print()
    for label, rows in (("pass set", ps), ("never passed", ns), ("population", pop)):
        print(f"  {label:<16} {tally(rows)}")

    os.makedirs("results", exist_ok=True)
    io.open(args.out, "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\nwrote {args.out}  ({(time.perf_counter()-t0)/60:.1f} min total)")


if __name__ == "__main__":
    main()
