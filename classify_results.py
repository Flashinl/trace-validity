"""Re-classify committed verification results into the failure taxonomy.

Issue #14. `verify_traces.py` sets `failure_kind` live, but leaves the
arithmetic axis `unknown`: the provenance labels come from
tests/audit/provenance.py, which substitutes hypotheses into the goal before
evaluating and runs over committed artifacts rather than inside the verify loop.
This pass joins the two and writes the tables.

Reads only committed artifacts. No Lean, no GPU.

  python classify_results.py                 # all runs, write JSON + Markdown
  python classify_results.py --stdout        # print, write nothing

A note on the committed inputs. Records written before this change carry
`errors[:5]` -- truncated. That does not affect any number below: the maximum
`num_errors` in any committed results file is 3, so nothing was actually
dropped. Runs after this change are lossless by contract.
"""

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from failure_taxonomy import (  # noqa: E402
    classify_compile_error, arithmetic_axis, summarize, FAILURE_KINDS,
    ARITH_STATEMENT, ARITH_PROOF, ARITH_NONE, ARITH_UNKNOWN, FAILING_OUTCOMES,
)

HERE = os.path.dirname(os.path.abspath(__file__))
PROVENANCE = os.path.join(HERE, "results", "arithmetic_provenance.json")

# Same three sets as tests/audit/provenance.py, keyed identically so the join
# cannot silently line up the wrong run against the wrong labels.
SETS = [
    ("baseline_50step_1problem", "results/verification_temp_0.jsonl",
     "baseline -- 50 consecutive steps of ONE problem"),
    ("n50_distinct_T0.0", "results/verify3_temp0.0.jsonl",
     "n50 distinct problems, T=0.0"),
    ("n50_distinct_T0.2", "results/verify3_temp0.2.jsonl",
     "n50 distinct problems, T=0.2"),
]


def _read_jsonl(path):
    with io.open(os.path.join(HERE, path), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def load_provenance():
    with io.open(PROVENANCE, encoding="utf-8") as f:
        doc = json.load(f)
    return {k: {r["sample"]: r["label"] for r in v}
            for k, v in doc["records"].items()}


def classify_run(key, results_path):
    """Return (records, summary) with failure_kind and arithmetic attached."""
    prov = load_provenance().get(key, {})
    out = []
    for r in _read_jsonl(results_path):
        rec = dict(r)
        if r.get("outcome") in FAILING_OUTCOMES:
            rec["failure_kind"] = classify_compile_error(r.get("errors") or [])
            rec["arithmetic"] = arithmetic_axis(prov.get(r["sample_index"]))
            rec["provenance_label"] = prov.get(r["sample_index"])
        else:
            rec["failure_kind"] = None
            rec["arithmetic"] = None
            rec["provenance_label"] = None
        out.append(rec)
    return out, summarize(out)


def _md_table(summary, title):
    n = summary["total_failures"]
    lines = [f"### {title}", "",
             f"{n} failures of {summary['total_records']} records.", "",
             "| failure_kind | n | share of failures |", "|---|---|---|"]
    for k in FAILURE_KINDS:
        cell = summary["kinds"].get(k)
        if cell:
            lines.append(f"| `{k}` | {cell['n']} | {cell['pct']} |")
    lines += ["", "| arithmetic | n | share of failures |", "|---|---|---|"]
    for k in (ARITH_STATEMENT, ARITH_PROOF, ARITH_NONE, ARITH_UNKNOWN):
        cell = summary["arithmetic"].get(k)
        if cell:
            lines.append(f"| `{k}` | {cell['n']} | {cell['pct']} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true",
                    help="print only; write no files")
    args = ap.parse_args()

    doc, md = {}, []
    for key, path, title in SETS:
        if not os.path.exists(os.path.join(HERE, path)):
            print(f"[skip] {path} not found")
            continue
        records, summary = classify_run(key, path)
        doc[key] = {"source": path, "title": title, "summary": summary,
                    "records": [
                        {"sample_index": r["sample_index"],
                         "outcome": r["outcome"],
                         "failure_kind": r["failure_kind"],
                         "arithmetic": r["arithmetic"],
                         "provenance_label": r["provenance_label"],
                         "errors": r.get("errors") or []}
                        for r in records if r["failure_kind"]]}
        md.append(_md_table(summary, title))
        print(f"\n=== {title}  ({path}) ===")
        print(summary["table"])

    if args.stdout:
        return

    out_json = os.path.join(HERE, "results", "failure_taxonomy.json")
    with io.open(out_json, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")

    out_md = os.path.join(HERE, "results", "FAILURE_TAXONOMY.md")
    header = (
        "# What the failures actually are\n\n"
        "Generated by `classify_results.py` from committed artifacts. No number\n"
        "below is hand-typed. Categories were derived from the observed Lean\n"
        "output across both runs (issue #14), not invented ahead of the data.\n\n"
        "**Two axes.** `failure_kind` reads the compiler's own words.\n"
        "`arithmetic` answers a different question -- was a NUMBER wrong, and\n"
        "whose -- and is joined from `results/arithmetic_provenance.json`, which\n"
        "substitutes hypotheses before evaluating. It is not re-derived from\n"
        "error text, because no regex over error text could do it.\n\n"
        "`statement_arithmetic` means the DATASET's number is wrong;\n"
        "`proof_arithmetic` means a number the MODEL wrote is wrong.\n\n"
    )
    with io.open(out_md, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + "\n\n".join(md) + "\n")

    print(f"\nwrote {out_json}")
    print(f"wrote {out_md}")


if __name__ == "__main__":
    main()
