"""Analysis over one or more verified runs.

  python analyze_runs.py results/verify_temp0.0.jsonl results/verify_temp0.2.jsonl \
      --out results/analysis.json

Reports, per run:
  * the full outcome distribution, never collapsed to a boolean
  * validity rate, stated twice with both denominators spelled out
  * trace validity x the dataset's own provability label (`state`)
and, across runs on the same samples, a paired per-sample comparison.

Three rules this file exists to enforce
---------------------------------------
1. `error` and `timeout` are NOT `invalid`. A trace we could not verify is a
   missing measurement, not a failed proof. They are excluded from the validity
   rate's denominator and reported separately, and the excluded count is always
   printed — a rate over a silently shrunken denominator is how a broken
   verifier reads as a good result.
2. Answer correctness is not available from this pipeline. Goedel-Prover emits
   a Lean proof, not a final answer, and FormalStep's `ground_truth` is the
   whole problem's answer, identical for every step of it. The second axis here
   is therefore the dataset's `state` ("Success of Proof" / "Failure of Proof"),
   i.e. whether the STATEMENT is provable — a different question from whether
   the model's proof of it compiles. Do not relabel this axis "correctness".
3. Nothing is imputed. A record with no `state` is counted as `unknown` rather
   than assumed provable.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from verifier import OUTCOMES, VALID, TIMEOUT, VERIFIER_CRASH, PARSE_FAILURE

# Outcomes that are a verdict about the proof.
PROOF_VERDICT = ("valid", "compile_error", "has_sorry", "empty_code")
# Outcomes that are the absence of a verdict. Never counted as invalid.
NO_VERDICT = (TIMEOUT, VERIFIER_CRASH, PARSE_FAILURE)

PROVABLE = "Success of Proof"
UNPROVABLE = "Failure of Proof"


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_run(verification_path):
    """A verification file plus, when present, the run_meta.json of its traces."""
    rows = load_jsonl(verification_path)
    meta = None
    meta_path = os.path.join(os.path.dirname(os.path.abspath(verification_path)),
                             "run_meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    return {"path": verification_path, "rows": rows, "meta": meta}


def summarise(rows):
    counts = Counter(r["outcome"] for r in rows)
    total = len(rows)
    verdicts = sum(counts[o] for o in PROOF_VERDICT)
    no_verdict = sum(counts[o] for o in NO_VERDICT)
    valid = counts[VALID]

    # Both denominators, always. The gap between them IS the uncertainty.
    return {
        "total": total,
        "counts": {o: counts[o] for o in OUTCOMES},
        "valid": valid,
        "verdicts": verdicts,
        "no_verdict": no_verdict,
        "validity_rate_over_verdicts": valid / verdicts if verdicts else None,
        "validity_rate_over_all": valid / total if total else None,
    }


def crosstab(rows):
    """Our verdict x the dataset's provability label."""
    table = defaultdict(Counter)
    for r in rows:
        state = r.get("state") or "unknown"
        if r["outcome"] == VALID:
            verdict = "valid"
        elif r["outcome"] in NO_VERDICT:
            verdict = "no_verdict"
        else:
            verdict = "not_valid"
        table[verdict][state] += 1
    return {k: dict(v) for k, v in table.items()}


def fmt_crosstab(table):
    states = [PROVABLE, UNPROVABLE, "unknown"]
    rows = ["valid", "not_valid", "no_verdict"]
    width = max(len(r) for r in rows) + 2
    out = [" " * width + "".join(f"{s:>20}" for s in states) + f"{'total':>8}"]
    for r in rows:
        cells = [table.get(r, {}).get(s, 0) for s in states]
        out.append(f"{r:<{width}}" + "".join(f"{c:>20}" for c in cells)
                   + f"{sum(cells):>8}")
    totals = [sum(table.get(r, {}).get(s, 0) for r in rows) for s in states]
    out.append(f"{'total':<{width}}" + "".join(f"{t:>20}" for t in totals)
               + f"{sum(totals):>8}")
    return "\n".join(out)


def report_run(run):
    rows, meta = run["rows"], run["meta"]
    s = summarise(rows)
    table = crosstab(rows)

    print("=" * 78)
    print(f"RUN  {run['path']}")
    print("=" * 78)
    if meta:
        smp, ds = meta["sampling"], meta["dataset"]
        sel = ds.get("selection") or {}
        print(f"  temperature {smp['temperature']}  "
              f"top_p {smp['top_p']}  seed {smp['seed']}  "
              f"{'greedy' if smp['greedy_deterministic'] else 'sampled'}")
        print(f"  {smp['num_samples']} samples x "
              f"{smp['num_trajectories_per_sample']} trajectory(ies)  |  "
              f"{sel.get('distinct_problems_in_selection', '?')} distinct problems "
              f"[{sel.get('strategy', '?')}]")
        print(f"  model {meta['model']['name']}  |  git "
              f"{(meta['git'].get('sha') or '?')[:8]}"
              f"{' DIRTY' if meta['git'].get('dirty') else ''}  |  "
              f"gpu {meta['environment'].get('gpu')}")
        print(f"  traces sha256 {(meta['output'].get('sha256') or '?')[:16]}  "
              f"status {meta.get('status')}")
    else:
        print("  [warn] no run_meta.json beside this verification file — the "
              "generating config is not recorded.")

    print("\n  OUTCOME DISTRIBUTION")
    for o in OUTCOMES:
        n = s["counts"][o]
        if n:
            tag = "   <- not a verdict" if o in NO_VERDICT else ""
            print(f"    {o:<16}{n:>5}  ({n/s['total']:6.1%}){tag}")

    print(f"\n  VALIDITY RATE")
    if s["validity_rate_over_verdicts"] is not None:
        print(f"    {s['valid']}/{s['verdicts']} = "
              f"{s['validity_rate_over_verdicts']:.1%}  over traces that got a "
              f"verdict")
    print(f"    {s['valid']}/{s['total']} = {s['validity_rate_over_all']:.1%}  "
          f"over all traces")
    if s["no_verdict"]:
        print(f"    {s['no_verdict']} trace(s) produced no verdict "
              f"(timeout/crash/parse_failure) and are excluded from the first "
              f"rate — NOT counted as invalid")
    else:
        print(f"    0 traces produced no verdict, so both rates coincide")

    print(f"\n  TRACE VALIDITY x DATASET PROVABILITY (`state`)")
    print("  " + fmt_crosstab(table).replace("\n", "\n  "))
    fp = table.get("valid", {}).get(UNPROVABLE, 0)
    print(f"\n    false positives (we said valid, dataset says unprovable): {fp}")
    print(f"    model failed a provable statement: "
          f"{table.get('not_valid', {}).get(PROVABLE, 0)}")
    print()
    return {"summary": s, "crosstab": table,
            "meta": {k: meta[k] for k in ("sampling", "git", "status")} if meta else None}


def compare(runs):
    """Paired per-sample comparison. Only meaningful on identical samples."""
    keyed = []
    for run in runs:
        keyed.append({(r["sample_index"], r["trajectory_index"]): r
                      for r in run["rows"]})
    shared = set(keyed[0])
    for k in keyed[1:]:
        shared &= set(k)

    labels = []
    for run in runs:
        m = run["meta"]
        labels.append(f"T={m['sampling']['temperature']}" if m
                      else os.path.basename(run["path"]))

    print("=" * 78)
    print("PAIRED COMPARISON")
    print("=" * 78)
    sizes = [len(k) for k in keyed]
    print(f"  {' vs '.join(labels)}")
    print(f"  records per run: {sizes}   shared (sample, trajectory) keys: "
          f"{len(shared)}")
    if len(shared) != max(sizes):
        print(f"  [warn] runs do not cover identical keys; comparing the "
              f"{len(shared)} shared ones only")
    if len(runs) != 2 or not shared:
        return None

    a, b = keyed[0], keyed[1]
    flips = Counter()
    changed = []
    for k in sorted(shared):
        oa, ob = a[k]["outcome"], b[k]["outcome"]
        flips[(oa == VALID, ob == VALID)] += 1
        if oa != ob:
            changed.append((k, oa, ob))

    print(f"\n  valid in both        : {flips[(True, True)]}")
    print(f"  valid only in {labels[0]:<8}: {flips[(True, False)]}")
    print(f"  valid only in {labels[1]:<8}: {flips[(False, True)]}")
    print(f"  valid in neither     : {flips[(False, False)]}")
    print(f"\n  outcome changed on {len(changed)}/{len(shared)} samples")
    for (si, ti), oa, ob in changed[:15]:
        print(f"    sample {si:<3} {oa:<14} -> {ob}")
    if len(changed) > 15:
        print(f"    ... and {len(changed) - 15} more")
    print()
    return {
        "labels": labels,
        "shared_keys": len(shared),
        "valid_both": flips[(True, True)],
        "valid_only_first": flips[(True, False)],
        "valid_only_second": flips[(False, True)],
        "valid_neither": flips[(False, False)],
        "changed": [{"sample_index": si, "trajectory_index": ti,
                     "from": oa, "to": ob} for (si, ti), oa, ob in changed],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("verifications", nargs="+",
                    help="verification JSONL file(s) from verify_traces.py")
    ap.add_argument("--out", default=None, help="write the report as JSON")
    args = ap.parse_args()

    runs = [load_run(p) for p in args.verifications]
    report = {"runs": []}
    for run in runs:
        report["runs"].append(dict(report_run(run), path=run["path"]))
    if len(runs) > 1:
        report["comparison"] = compare(runs)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        if os.path.exists(args.out):
            raise FileExistsError(
                f"{args.out} exists; analysis outputs are never overwritten."
            )
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
