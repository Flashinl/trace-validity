"""Dump every version-bearing component of the VERIFICATION environment.

Issue #16. `requirements.txt` matching is not sufficient. The Lean side has its
own dependency graph -- toolchain, Mathlib, seven transitive Lean packages, the
REPL -- and none of it is visible to pip. Two machines can agree on every Python
package and still verify against different `aesop` revisions.

This module answers one question: *which environment produced this results
file?* `verify_traces.py` writes the report beside its output on every run, so
the answer survives after the fact.

  python scripts/env_report.py              # human-readable
  python scripts/env_report.py --json       # machine-readable
  python scripts/env_report.py --out PATH   # write JSON to PATH

What this is for
----------------
Not drift detection on a hunch -- the record itself. This module was built on the
theory that Mathlib's transitive deps float because seven of them carry a branch
`inputRev`. Running it disproved that: mathlib is required at an immutable tag
and commits its own manifest, so lake resolves those deps from THAT manifest.
Measured on a clean clone with aesop `master` upstream at 18889deb, `lake update`
still produced a7dbf0c6 and left our manifest byte-identical (issue #16).

The report earns its place anyway, and that episode is the argument for it: the
resolved revisions are now written down, so the next claim about them can be
checked instead of assumed.
"""

import argparse
import io
import json
import os
import platform
import re
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

# elan installs lean/lake outside a non-login shell's PATH; verifier.py fixes
# this at import for the same reason. Do it here too so `lean --version` works
# from a Colab cell, a notebook kernel or a CI step.
_ELAN_BIN = os.path.expanduser("~/.elan/bin")
if os.path.isdir(_ELAN_BIN) and _ELAN_BIN not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _ELAN_BIN + os.pathsep + os.environ.get("PATH", "")

# Distributions that can change a verification result. Not `pip freeze`: a full
# freeze buries the load-bearing four in ~200 lines of transitive noise, and the
# point of this report is that someone reads it.
TRACKED_DISTRIBUTIONS = (
    "lean_interact", "transformers", "datasets", "torch", "accelerate",
    "tokenizers", "matplotlib",
)

SCHEMA_VERSION = 1


def _run(args, cwd=None):
    """Best effort: a missing tool is reported, never raised."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}
    out = (p.stdout or "").strip() or (p.stderr or "").strip()
    return {"ok": p.returncode == 0, "returncode": p.returncode, "output": out}


def _distributions(extra=()):
    from importlib import metadata
    out = {}
    # dict.fromkeys preserves order and de-duplicates: everything named in
    # requirements.txt must be queried too, or the drift check has nothing to
    # compare against.
    for name in dict.fromkeys(tuple(TRACKED_DISTRIBUTIONS) + tuple(extra)):
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def _requirements_pins():
    """Parse `name==version` pins out of requirements.txt.

    Only `==` is a pin. A bare requirement (`torch`, deliberately unpinned so
    its CUDA build can match the host driver) is recorded as None so the check
    below does not report it as a mismatch.
    """
    path = os.path.join(HERE, "requirements.txt")
    pins = {}
    if not os.path.exists(path):
        return pins
    for line in io.open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" in line:
            name, _, version = line.partition("==")
            pins[name.strip()] = version.strip()
        else:
            pins[line] = None
    return pins


def _requirements_drift(installed):
    """Installed versions that disagree with the pins in requirements.txt.

    This is the check the sync was missing. "Both machines install from the same
    requirements.txt" is a statement about the FILE, not about the environment:
    a box that installed before a pin was tightened, or that resolved a
    dependency conflict by upgrading, satisfies that sentence and still differs.
    """
    drift = []
    for name, pinned in _requirements_pins().items():
        if pinned is None:
            continue  # deliberately unpinned
        actual = installed.get(name)
        if actual is None:
            drift.append({"package": name, "pinned": pinned, "installed": None,
                          "kind": "missing"})
        elif actual != pinned:
            drift.append({"package": name, "pinned": pinned, "installed": actual,
                          "kind": "version_mismatch"})
    return drift


def _config_pins():
    """What config.py DECLARES. Compared against what is resolved on disk."""
    try:
        import config
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    return {
        "LEAN_VERSION": config.LEAN_VERSION,
        "LEAN_TOOLCHAIN": config.LEAN_TOOLCHAIN,
        "MATHLIB_REV": config.MATHLIB_REV,
        "VERIFY_TIMEOUT_SECONDS": config.VERIFY_TIMEOUT_SECONDS,
        "BASE_ENV_TIMEOUT_SECONDS": config.BASE_ENV_TIMEOUT_SECONDS,
        "LEAN_MAX_REC_DEPTH": config.LEAN_MAX_REC_DEPTH,
        "MODEL_NAME": config.MODEL_NAME,
        "DATASET_NAME": config.DATASET_NAME,
        "DATASET_SPLIT": config.DATASET_SPLIT,
    }


def _lean_project(project_dir):
    """Resolved Lean state: the toolchain file and every dependency revision."""
    info = {"project_dir": project_dir}

    tc = os.path.join(project_dir, "lean-toolchain")
    info["lean_toolchain_file"] = (
        io.open(tc, encoding="utf-8").read().strip() if os.path.exists(tc) else None
    )

    manifest_path = os.path.join(project_dir, "lake-manifest.json")
    packages, floating = [], []
    if os.path.exists(manifest_path):
        try:
            manifest = json.load(io.open(manifest_path, encoding="utf-8"))
            for pkg in manifest.get("packages", []):
                entry = {
                    "name": pkg.get("name"),
                    "rev": pkg.get("rev"),
                    "inputRev": pkg.get("inputRev"),
                    # `inputRev` is a BRANCH name. This looks like a drift
                    # vector and is not one: mathlib is required at an immutable
                    # tag and commits its own manifest, so lake resolves these
                    # from THAT manifest rather than re-resolving the branch.
                    # Measured: with aesop `master` upstream at 18889deb, a
                    # `lake update` on a clean clone still produced a7dbf0c6.
                    # Recorded because the resolved rev is what matters, and
                    # naming it is how a future divergence gets caught.
                    "branch_input_rev": pkg.get("inputRev") in ("main", "master", None),
                }
                packages.append(entry)
                if entry["branch_input_rev"]:
                    floating.append(entry["name"])
            info["manifest_version"] = manifest.get("version")
        except (ValueError, OSError) as e:
            info["manifest_error"] = f"{type(e).__name__}: {e}"
    else:
        info["manifest_error"] = "lake-manifest.json not found"

    info["packages"] = packages
    info["branch_input_rev_dependencies"] = floating
    info["mathlib_rev"] = next(
        (p["rev"] for p in packages if p["name"] == "mathlib"), None
    )
    info["mathlib_input_rev"] = next(
        (p["inputRev"] for p in packages if p["name"] == "mathlib"), None
    )

    env_pickle = None
    try:
        import config
        env_pickle = config.ENV_PICKLE_PATH
    except Exception:  # noqa: BLE001
        pass
    info["env_snapshot"] = {
        "path": env_pickle,
        "exists": bool(env_pickle and os.path.exists(env_pickle)),
    }
    return info


def _code_version():
    """git SHA/branch/dirty, or the CODE_VERSION file where git cannot answer.

    A host running from an uploaded archive has no git. The committed
    traces/*/run_meta.json has `git.sha: null` for exactly that reason, which is
    why the fallback exists and why the source is recorded.
    """
    r = _run(["git", "rev-parse", "HEAD"], cwd=HERE)
    if r.get("ok"):
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE)
        status = _run(["git", "status", "--porcelain"], cwd=HERE)
        return {
            "source": "git",
            "sha": r["output"],
            "branch": branch.get("output") if branch.get("ok") else None,
            "dirty": bool(status.get("output")) if status.get("ok") else None,
        }
    path = os.path.join(HERE, "CODE_VERSION")
    if os.path.exists(path):
        try:
            d = json.load(io.open(path, encoding="utf-8"))
            d["source"] = "CODE_VERSION"
            return d
        except ValueError as e:
            return {"source": "CODE_VERSION", "error": str(e)}
    return {"source": None, "sha": None, "branch": None, "dirty": None}


def collect(project_dir=None):
    """Everything that can change a verification result."""
    if project_dir is None:
        try:
            import config
            project_dir = config.LEAN_PROJECT_DIR
        except Exception:  # noqa: BLE001
            project_dir = os.path.join(HERE, "lean_project")

    lean_v = _run(["lean", "--version"])
    lake_v = _run(["lake", "--version"])

    report = {
        "schema_version": SCHEMA_VERSION,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "python_executable": sys.executable,
            # Colab sets this; the sync believed generation ran in Colab and it
            # did not. Record it rather than assuming either way.
            "in_colab": "google.colab" in sys.modules
            or bool(os.environ.get("COLAB_RELEASE_TAG")),
        },
        "config_pins": _config_pins(),
        "lean": {
            "lean_version": lean_v.get("output") if lean_v.get("ok") else None,
            "lake_version": lake_v.get("output") if lake_v.get("ok") else None,
            "lean_available": lean_v.get("ok", False),
            "project": _lean_project(project_dir),
        },
        "python_distributions": _distributions(_requirements_pins().keys()),
        "code_version": _code_version(),
    }

    report["requirements_drift"] = _requirements_drift(report["python_distributions"])
    report["warnings"] = _warnings(report)
    return report


def _warnings(report):
    """Anything that makes this run less reproducible than it looks."""
    out = []
    proj = report["lean"]["project"]
    pins = report["config_pins"]

    # Deliberately NOT a warning. These dependencies carry a branch `inputRev`
    # but are pinned transitively by mathlib's own committed manifest at an
    # immutable tag -- verified empirically, see issue #16. Warning about them
    # would train readers to ignore the warnings block.
    if pins.get("MATHLIB_REV") and not re.match(r"^v\d+\.\d+\.\d+$",
                                                str(pins["MATHLIB_REV"])):
        out.append(
            f"config.MATHLIB_REV is {pins['MATHLIB_REV']!r}, which is not an "
            f"immutable vX.Y.Z tag. The transitive Lean dependencies are pinned "
            f"only because mathlib is pinned to a tag; a branch or moving ref "
            f"here would make them float for real."
        )

    declared = pins.get("LEAN_TOOLCHAIN")
    on_disk = proj.get("lean_toolchain_file")
    if declared and on_disk and declared != on_disk:
        out.append(
            f"lean-toolchain on disk ({on_disk}) does not match "
            f"config.LEAN_TOOLCHAIN ({declared})."
        )

    if pins.get("MATHLIB_REV") and proj.get("mathlib_input_rev") \
            and pins["MATHLIB_REV"] != proj["mathlib_input_rev"]:
        out.append(
            f"Mathlib inputRev in the manifest ({proj['mathlib_input_rev']}) "
            f"does not match config.MATHLIB_REV ({pins['MATHLIB_REV']})."
        )

    if not report["lean"]["lean_available"]:
        out.append("`lean` is not on PATH; the Lean versions above are unknown.")

    if report["code_version"].get("sha") is None:
        out.append(
            "No git SHA and no CODE_VERSION file: this run is not traceable to "
            "a code revision."
        )
    elif report["code_version"].get("dirty"):
        out.append("Working tree is dirty; the SHA does not describe the code that ran.")

    if report["python_distributions"].get("lean_interact") is None:
        out.append("lean_interact is not installed; verification cannot run.")

    for d in report.get("requirements_drift") or []:
        if d["kind"] == "missing":
            out.append(f"{d['package']} is pinned to {d['pinned']} in "
                       f"requirements.txt but is NOT INSTALLED.")
        else:
            out.append(f"{d['package']} is pinned to {d['pinned']} in "
                       f"requirements.txt but {d['installed']} is installed.")

    return out


def render(report):
    """Human-readable rendering. The JSON is the record; this is for reading."""
    L = []
    a = L.append
    a("VERIFICATION ENVIRONMENT REPORT")
    a("=" * 60)

    h = report["host"]
    a(f"host          {h['hostname']}  ({h['platform']})")
    a(f"python        {h['python']}  [{h['python_executable']}]")
    a(f"colab         {h['in_colab']}")

    cv = report["code_version"]
    a(f"code          {str(cv.get('sha'))[:12]} on {cv.get('branch')} "
      f"(dirty={cv.get('dirty')}, source={cv.get('source')})")

    lean = report["lean"]
    proj = lean["project"]
    a("")
    a("LEAN")
    a(f"  lean            {lean['lean_version']}")
    a(f"  lake            {lean['lake_version']}")
    a(f"  lean-toolchain  {proj.get('lean_toolchain_file')}")
    a(f"  mathlib         rev={str(proj.get('mathlib_rev'))[:12]} "
      f"inputRev={proj.get('mathlib_input_rev')}")
    snap = proj.get("env_snapshot") or {}
    a(f"  env snapshot    exists={snap.get('exists')}")
    a("")
    a("  lake dependencies (resolved)")
    a(f"    {'package':<20}{'rev':<14}{'inputRev':<12}{'pinned via'}")
    for p in proj.get("packages", []):
        via = "mathlib manifest" if p["branch_input_rev"] else "tag"
        a(f"    {str(p['name']):<20}{str(p['rev'])[:12]:<14}"
          f"{str(p['inputRev']):<12}{via}")

    a("")
    a("CONFIG PINS")
    for k, v in (report["config_pins"] or {}).items():
        a(f"  {k:<28}{v}")

    a("")
    a("PYTHON DISTRIBUTIONS")
    for k, v in report["python_distributions"].items():
        a(f"  {k:<28}{v if v else '-- not installed --'}")

    drift = report.get("requirements_drift") or []
    a("")
    if drift:
        a(f"REQUIREMENTS DRIFT ({len(drift)})")
        a(f"  {'package':<20}{'pinned':<14}{'installed'}")
        for d in drift:
            a(f"  {d['package']:<20}{d['pinned']:<14}"
              f"{d['installed'] or '-- not installed --'}")
    else:
        a("REQUIREMENTS DRIFT  none")

    a("")
    if report["warnings"]:
        a(f"WARNINGS ({len(report['warnings'])})")
        for w in report["warnings"]:
            a(f"  ! {w}")
    else:
        a("WARNINGS  none")
    return "\n".join(L)


def write_beside(out_path, project_dir=None):
    """Write the report next to a results file. Never raises.

    Called from verify_traces.py. A failure to write the report must not lose a
    verification run, so this reports the problem and returns None.
    """
    try:
        report = collect(project_dir=project_dir)
        base = os.path.splitext(out_path)[0]
        path = base + ".env.json"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return path, report
    except Exception as e:  # noqa: BLE001
        print(f"[env_report] could not write report: {type(e).__name__}: {e}")
        return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--out", type=str, default=None, help="write JSON to PATH")
    ap.add_argument("--project-dir", type=str, default=None)
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    report = collect(project_dir=args.project_dir)

    if args.out:
        with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"wrote {args.out}")

    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report))

    # A report that had to warn is still a successful report.
    return 0


if __name__ == "__main__":
    sys.exit(main())
