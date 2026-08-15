#!/bin/bash
# One-time Lean 4 + Mathlib setup.
#
# This script used to install leanprover/lean4:v4.32.0-rc1, run `lake new
# lean_project math`, and then `lake build` — which compiles Mathlib from
# source. That is the ~3 hour cold start. It also disagreed with config.py,
# which pins v4.32.0 (no rc): an rc toolchain has no matching Mathlib tag and no
# matching REPL tag, which is the "unexpected token" / "unknown constant"
# failure mode documented in config.py.
#
# The pins now come from config.py, and Mathlib is fetched from the prebuilt
# cache. Never add a `lake build` that would compile Mathlib itself.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Resolve an interpreter that actually runs. On Windows/git-bash `python3` is
# the Microsoft Store stub, which prints "Python was not found" and exits 9009,
# so testing for the name alone is not enough — each candidate has to be run.
PYTHON_OVERRIDE="${PYTHON:-}"
PYTHON=""
for candidate in "$PYTHON_OVERRIDE" python3 python py; do
    [ -n "$candidate" ] || continue
    if "$candidate" -c 'import sys' >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "No working Python interpreter found (tried \$PYTHON, python3, python, py)." >&2
    exit 1
fi

# Single source of truth for the pins — never hardcode them here.
LEAN_TOOLCHAIN="$("$PYTHON" -c 'import config; print(config.LEAN_TOOLCHAIN)')"
MATHLIB_REV="$("$PYTHON" -c 'import config; print(config.MATHLIB_REV)')"
LEAN_PROJECT="$("$PYTHON" -c 'import config; print(config.LEAN_PROJECT_DIR)')"

# Shared build cache. Override MATHLIB_CACHE_DIR to relocate it; the point is
# that it survives between clones so the multi-GB download is paid once.
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
MATHLIB_CACHE_DIR="${MATHLIB_CACHE_DIR:-$XDG_CACHE_HOME/mathlib}"
mkdir -p "$MATHLIB_CACHE_DIR"

echo "=== Pins (from config.py) ==="
echo "  python    : $PYTHON ($("$PYTHON" --version 2>&1))"
echo "  toolchain : $LEAN_TOOLCHAIN"
echo "  mathlib   : $MATHLIB_REV"
echo "  project   : $LEAN_PROJECT"
echo "  cache     : $MATHLIB_CACHE_DIR"

echo "=== Installing elan ==="
if ! command -v elan >/dev/null 2>&1; then
    curl https://elan.lean-lang.org/elan-init.sh -sSf | sh -s -- -y
fi
# shellcheck disable=SC1091
. "$HOME/.elan/env" 2>/dev/null || export PATH="$HOME/.elan/bin:$PATH"

echo "=== Installing toolchain $LEAN_TOOLCHAIN ==="
# `elan toolchain install` exits 1 with "is already installed" on a second run,
# and under `set -e` that aborts setup on every machine that has already been
# set up once. Setup has to be safe to re-run, so install only when absent.
if elan toolchain list 2>/dev/null | grep -qF "$LEAN_TOOLCHAIN"; then
    echo "  already installed"
else
    elan toolchain install "$LEAN_TOOLCHAIN"
fi
# Without a default, `lake` outside the project dir fails with
# "no default toolchain configured". The project's own lean-toolchain still
# wins inside lean_project/.
elan default "$LEAN_TOOLCHAIN"

echo "=== Creating the pinned Lean project ==="
# verifier.setup_lean_project() writes lean-toolchain and lakefile.toml from
# config.py, runs `lake update`, then `lake exe cache get` BEFORE `lake build`,
# so Mathlib is downloaded rather than compiled. Reusing it here keeps setup and
# verification from drifting apart.
"$PYTHON" -c "import verifier; verifier.setup_lean_project(verbose=True)"

echo "=== Lean setup complete ==="
lean --version
lake --version
echo
echo "Next: python tests/test_verifier.py    # 35 fixtures, prints a confusion matrix"
