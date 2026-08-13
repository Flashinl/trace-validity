"""Lean 4 verification with an explicit outcome taxonomy (issues #5, #6).

Design notes
------------
Pinning (issue #6). Lean toolchain, Mathlib rev and the REPL must agree. We pin
a Mathlib *tag* whose name equals the Lean version (mathlib4 tag vX.Y.Z always
declares leanprover/lean4:vX.Y.Z), and lean_interact's REPL publishes a matching
`{repl_rev}_lean-toolchain-{lean_version}` tag. The historical failure was
Mathlib v4.32.2 against a REPL with no v4.32.2 tag -> "unexpected token" /
"unknown constant".

Speed (issue #5 / step 5). Importing Mathlib costs ~30s. We import it ONCE into
a base environment and run each snippet against that env, so per-verification
cost is just elaborating the declaration. Snippets whose imports differ from the
base fall back to a "fresh" run so that missing-import failures are still real
failures rather than being masked by the shared environment.

`sorry` detection. The REPL returns a structured `sorries` list. We use that,
NOT a regex over the source: `\\bsorry\\b` matches the word inside comments and
string literals and would mark genuinely complete proofs invalid.
"""

import os
import re
import subprocess
import time

from config import (
    LEAN_TOOLCHAIN,
    LEAN_PROJECT_DIR,
    MATHLIB_REV,
    VERIFY_TIMEOUT_SECONDS,
)

# The outcome taxonomy. Never collapse these into a bare boolean (issue #5).
VALID = "valid"
PARSE_FAILURE = "parse_failure"
EMPTY_CODE = "empty_code"
HAS_SORRY = "has_sorry"
COMPILE_ERROR = "compile_error"
TIMEOUT = "timeout"
VERIFIER_CRASH = "verifier_crash"

OUTCOMES = (VALID, PARSE_FAILURE, EMPTY_CODE, HAS_SORRY, COMPILE_ERROR, TIMEOUT, VERIFIER_CRASH)

# Only `valid` counts as a proved theorem. Everything else is a distinct failure.
BASE_IMPORTS = ("Mathlib", "Aesop")

_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+([\w.]+)[ \t]*$", re.M)
_DECL_RE = re.compile(
    r"^[ \t]*(?:@\[[^\]]*\]\s*)?"
    r"(?:private\s+|protected\s+|noncomputable\s+)*"
    r"(?:theorem|lemma|example|def|instance)\b",
    re.M,
)


def _lakefile_contents():
    return (
        "name = \"verification\"\n"
        "defaultTargets = [\"Verification\"]\n\n"
        "[[require]]\n"
        "name = \"mathlib\"\n"
        "git = \"https://github.com/leanprover-community/mathlib4.git\"\n"
        f"rev = \"{MATHLIB_REV}\"\n\n"
        "[[lean_lib]]\n"
        "name = \"Verification\"\n"
    )


def setup_lean_project(project_dir=LEAN_PROJECT_DIR, verbose=True):
    """Create/refresh the pinned Lean project. Idempotent and safe to re-run.

    Never builds Mathlib from source: `lake exe cache get` always runs first.
    """
    os.makedirs(project_dir, exist_ok=True)

    # Always (re)write the pins so a stale checkout cannot drift.
    with open(os.path.join(project_dir, "lean-toolchain"), "w", encoding="utf-8") as f:
        f.write(f"{LEAN_TOOLCHAIN}\n")
    with open(os.path.join(project_dir, "lakefile.toml"), "w", encoding="utf-8") as f:
        f.write(_lakefile_contents())

    verification_file = os.path.join(project_dir, "Verification.lean")
    if not os.path.exists(verification_file):
        with open(verification_file, "w", encoding="utf-8") as f:
            f.write("import Mathlib\n")

    # A stale lakefile.lean from the old `lake new` path shadows lakefile.toml.
    legacy = os.path.join(project_dir, "lakefile.lean")
    if os.path.exists(legacy):
        os.rename(legacy, legacy + ".disabled")
        if verbose:
            print(f"[setup] renamed legacy {legacy} -> {legacy}.disabled")

    manifest = os.path.join(project_dir, "lake-manifest.json")
    built = os.path.isdir(os.path.join(project_dir, ".lake", "packages", "mathlib"))

    def run(args, check=True):
        if verbose:
            print(f"[setup] $ {' '.join(args)}")
        return subprocess.run(args, cwd=project_dir, check=check)

    if not os.path.exists(manifest) or not built:
        run(["lake", "update"])

    # NEVER build Mathlib from source. Non-fatal: a project without Mathlib has
    # no `cache` executable.
    run(["lake", "exe", "cache", "get"], check=False)
    run(["lake", "build"])

    return project_dir


def split_prelude(code):
    """Return (imports, rest). `rest` keeps set_option/open and declarations."""
    imports = _IMPORT_RE.findall(code)
    rest = _IMPORT_RE.sub("", code)
    return imports, rest


def has_declaration(code):
    return bool(_DECL_RE.search(code))


class LeanVerifier:
    def __init__(
        self,
        project_dir=LEAN_PROJECT_DIR,
        timeout=VERIFY_TIMEOUT_SECONDS,
        setup=True,
        verbose=False,
    ):
        from lean_interact import Command, LeanREPLConfig, LeanServer
        from lean_interact.project import LocalProject

        self._Command = Command
        self.timeout = timeout
        self.project_dir = setup_lean_project(project_dir, verbose=verbose) if setup else project_dir

        project = LocalProject(directory=self.project_dir, auto_build=True)
        config = LeanREPLConfig(project=project, verbose=verbose)
        self.server = LeanServer(config)

        # Import Mathlib exactly once; reuse the resulting environment.
        t0 = time.perf_counter()
        prelude = "\n".join(f"import {m}" for m in BASE_IMPORTS)
        resp = self.server.run(Command(cmd=prelude), timeout=max(self.timeout, 300))
        self.base_env = getattr(resp, "env", None)
        self.base_env_seconds = time.perf_counter() - t0
        if self.base_env is None:
            raise RuntimeError(
                f"Could not build base environment from {prelude!r}: {resp}"
            )

    # ------------------------------------------------------------------ #

    def _classify(self, resp, elapsed, mode):
        messages = list(getattr(resp, "messages", []) or [])
        errors = [m for m in messages if getattr(m, "severity", None) == "error"]
        warnings = [m for m in messages if getattr(m, "severity", None) == "warning"]
        sorries = list(getattr(resp, "sorries", []) or [])

        # The REPL also reports sorry as a warning on the declaration.
        sorry_warning = any("sorry" in (getattr(w, "data", "") or "") for w in warnings)

        if errors:
            outcome = COMPILE_ERROR
        elif sorries or sorry_warning:
            outcome = HAS_SORRY
        else:
            outcome = VALID

        return {
            "outcome": outcome,
            "valid": outcome == VALID,
            "errors": [getattr(e, "data", str(e)) for e in errors],
            "warnings": [getattr(w, "data", str(w)) for w in warnings],
            "num_errors": len(errors),
            "num_sorries": len(sorries),
            "seconds": round(elapsed, 3),
            "mode": mode,
        }

    def verify(self, lean_code, timeout=None):
        """Verify one snippet. Always returns a dict carrying `outcome`."""
        timeout = self.timeout if timeout is None else timeout
        t0 = time.perf_counter()

        if lean_code is None or not lean_code.strip():
            return {
                "outcome": EMPTY_CODE, "valid": False, "errors": [], "warnings": [],
                "num_errors": 0, "num_sorries": 0, "seconds": 0.0, "mode": "none",
            }

        imports, rest = split_prelude(lean_code)

        if not has_declaration(rest):
            # Header-only or prose-only: nothing was proved. Not a Lean failure,
            # but emphatically not `valid` either.
            return {
                "outcome": EMPTY_CODE, "valid": False, "errors": [], "warnings": [],
                "num_errors": 0, "num_sorries": 0, "seconds": 0.0, "mode": "none",
            }

        # Fast path only when the snippet's imports are exactly the base set.
        # Otherwise run standalone so a missing import is a real failure rather
        # than being masked by the shared environment.
        use_base = bool(imports) and set(imports) <= set(BASE_IMPORTS)
        cmd = rest if use_base else lean_code
        env = self.base_env if use_base else None
        mode = "shared_env" if use_base else "fresh"

        try:
            resp = self.server.run(self._Command(cmd=cmd, env=env), timeout=timeout)
        except TimeoutError:
            elapsed = time.perf_counter() - t0
            self._restart()
            return {
                "outcome": TIMEOUT, "valid": False,
                "errors": [f"verification exceeded {timeout}s"], "warnings": [],
                "num_errors": 0, "num_sorries": 0,
                "seconds": round(elapsed, 3), "mode": mode,
            }
        except Exception as e:  # noqa: BLE001 - any REPL failure is a crash outcome
            elapsed = time.perf_counter() - t0
            self._restart()
            return {
                "outcome": VERIFIER_CRASH, "valid": False,
                "errors": [f"{type(e).__name__}: {e}"], "warnings": [],
                "num_errors": 0, "num_sorries": 0,
                "seconds": round(elapsed, 3), "mode": mode,
            }

        return self._classify(resp, time.perf_counter() - t0, mode)

    def _restart(self):
        """A timed-out REPL is killed by lean_interact; rebuild the session."""
        try:
            from lean_interact import Command, LeanREPLConfig, LeanServer
            from lean_interact.project import LocalProject

            project = LocalProject(directory=self.project_dir, auto_build=False)
            self.server = LeanServer(LeanREPLConfig(project=project, verbose=False))
            prelude = "\n".join(f"import {m}" for m in BASE_IMPORTS)
            resp = self.server.run(Command(cmd=prelude), timeout=300)
            self.base_env = getattr(resp, "env", None)
        except Exception as e:  # noqa: BLE001
            print(f"[verifier] restart failed: {type(e).__name__}: {e}")
            self.base_env = None
