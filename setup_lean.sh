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

# Single source of truth for the pins — never hardcode them here.
LEAN_TOOLCHAIN="$(python3 -c 'import config; print(config.LEAN_TOOLCHAIN)')"
MATHLIB_REV="$(python3 -c 'import config; print(config.MATHLIB_REV)')"
LEAN_PROJECT="$(python3 -c 'import config; print(config.LEAN_PROJECT_DIR)')"

# Shared build cache. Override MATHLIB_CACHE_DIR to relocate it; the point is
# that it survives between clones so the multi-GB download is paid once.
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
MATHLIB_CACHE_DIR="${MATHLIB_CACHE_DIR:-$XDG_CACHE_HOME/mathlib}"
mkdir -p "$MATHLIB_CACHE_DIR"

echo "=== Pins (from config.py) ==="
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
elan toolchain install "$LEAN_TOOLCHAIN"
# Without a default, `lake` outside the project dir fails with
# "no default toolchain configured". The project's own lean-toolchain still
# wins inside lean_project/.
elan default "$LEAN_TOOLCHAIN"

echo "=== Creating the pinned Lean project ==="
# verifier.setup_lean_project() writes lean-toolchain and lakefile.toml from
# config.py, runs `lake update`, then `lake exe cache get` BEFORE `lake build`,
# so Mathlib is downloaded rather than compiled. Reusing it here keeps setup and
# verification from drifting apart.
python3 -c "import verifier; verifier.setup_lean_project(verbose=True)"

echo "=== Lean setup complete ==="
lean --version
lake --version
echo
echo "Next: python tests/test_verifier.py    # 35 fixtures, prints a confusion matrix"
