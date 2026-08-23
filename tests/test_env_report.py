"""Unit tests for scripts/env_report.py.

The report exists so that a results file can be traced back to the environment
that produced it. These tests pin the two things that would make it useless: a
silent failure to notice drift, and a crash that loses a verification run.

Run: python tests/test_env_report.py
"""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import env_report  # noqa: E402

FAILURES = []


def check_eq(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<58} got={got!r}")
    if not ok:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<58} {detail}")
    if not ok:
        FAILURES.append(name)


# --------------------------------------------------------------------------
print("_requirements_drift() -- the check the sync was missing")

drift = env_report._requirements_drift(
    {"transformers": "4.46.3", "datasets": "3.6.0", "accelerate": "1.1.1",
     "tokenizers": "0.20.3", "lean_interact": "0.11.5", "torch": "2.7.0"}
)
check_eq("an exactly-matching environment reports no drift", drift, [])

drift = env_report._requirements_drift(
    {"transformers": "4.52.4", "datasets": "3.6.0", "accelerate": None,
     "tokenizers": "0.20.3", "lean_interact": "0.11.5", "torch": "9.9.9"}
)
by_pkg = {d["package"]: d for d in drift}
check_eq("a version mismatch is caught", by_pkg["transformers"]["kind"],
         "version_mismatch")
check_eq("  and carries both versions",
         (by_pkg["transformers"]["pinned"], by_pkg["transformers"]["installed"]),
         ("4.46.3", "4.52.4"))
check_eq("a missing pinned package is caught", by_pkg["accelerate"]["kind"],
         "missing")
check("torch is NOT reported despite differing",
      "torch" not in by_pkg,
      "(deliberately unpinned so its CUDA build matches the host driver)")

# --------------------------------------------------------------------------
print("\n_requirements_pins() -- only `==` is a pin")
pins = env_report._requirements_pins()
check_eq("transformers is pinned", pins.get("transformers"), "4.46.3")
check_eq("lean_interact is pinned", pins.get("lean_interact"), "0.11.5")
check_eq("torch is present but unpinned", pins.get("torch", "MISSING"), None)
check("comments and blank lines are ignored",
      all(not k.startswith("#") and k.strip() == k for k in pins),
      f"({len(pins)} pins parsed)")

# --------------------------------------------------------------------------
print("\ncollect() -- the real environment")
report = env_report.collect()

check_eq("schema_version is recorded", report["schema_version"],
         env_report.SCHEMA_VERSION)
for key in ("host", "config_pins", "lean", "python_distributions",
            "code_version", "requirements_drift", "warnings"):
    check(f"report carries `{key}`", key in report)

proj = report["lean"]["project"]
check("every lake package carries an inputRev and a branch flag",
      all("inputRev" in p and "branch_input_rev" in p for p in proj["packages"]),
      f"({len(proj['packages'])} packages)")

check("branch-inputRev dependencies are detected and named",
      isinstance(proj["branch_input_rev_dependencies"], list),
      f"({len(proj['branch_input_rev_dependencies'])} on a branch inputRev)")

# These deps carry a branch inputRev but are pinned transitively by mathlib's
# own committed manifest at an immutable tag -- verified on a clean clone, see
# issue #16. Recording them is right; WARNING about them is not, because it
# trains the reader to ignore the warnings block.
check("a branch inputRev does NOT raise a warning",
      not any("floating inputRev" in w for w in report["warnings"]),
      "-- they are pinned via mathlib's manifest")

check("an immutable mathlib tag raises no pin warning",
      not any("not an immutable" in w for w in report["warnings"]),
      f"(MATHLIB_REV={report['config_pins']['MATHLIB_REV']})")

check_eq("declared toolchain matches the file on disk",
         report["config_pins"]["LEAN_TOOLCHAIN"],
         proj["lean_toolchain_file"])

# --------------------------------------------------------------------------
print("\nrender() -- readable, and complete")
text = env_report.render(report)
for needle in ("VERIFICATION ENVIRONMENT REPORT", "LEAN", "CONFIG PINS",
               "PYTHON DISTRIBUTIONS", "REQUIREMENTS DRIFT", "mathlib"):
    check(f"rendering includes {needle!r}", needle in text)

# --------------------------------------------------------------------------
print("\nwrite_beside() -- lands next to the results file")
with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, "results", "verify9_temp0.0.jsonl")
    path, doc = env_report.write_beside(out)
    check_eq("report path is derived from the results path",
             os.path.basename(path), "verify9_temp0.0.env.json")
    check("file exists on disk", os.path.exists(path))
    with io.open(path, encoding="utf-8") as f:
        reloaded = json.load(f)
    check_eq("round-trips as JSON", reloaded["schema_version"],
             env_report.SCHEMA_VERSION)

print("\n  a failure to write the report must never lose a verification run")
_orig = env_report.collect
try:
    env_report.collect = lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    path, doc = env_report.write_beside(os.path.join(tempfile.gettempdir(), "x.jsonl"))
    check_eq("returns (None, None) instead of raising", (path, doc), (None, None))
finally:
    env_report.collect = _orig

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all env-report tests pass")
