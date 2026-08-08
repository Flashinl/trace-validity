#!/usr/bin/env bash
# Lean 4 + Mathlib setup for stage 2. Idempotent: safe to re-run after a
# disconnect, and a no-op once the build is in place.
#
# Usage:  bash scripts/setup_lean.sh [mathlib_dir]
set -euo pipefail

MATHLIB_DIR="${1:-mathlib4}"
MATHLIB_TAG="v4.19.0"
MATHLIB_REPO="https://github.com/leanprover-community/mathlib4.git"

# --- elan (the Lean toolchain manager) ---------------------------------------
export PATH="$HOME/.elan/bin:$PATH"
if ! command -v elan >/dev/null 2>&1; then
  echo "[lean] installing elan"
  curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- -y --default-toolchain none
  export PATH="$HOME/.elan/bin:$PATH"
else
  echo "[lean] elan already installed"
fi

# --- mathlib checkout at a PINNED tag ----------------------------------------
# The tag is pinned because Lean results are not comparable across Mathlib
# versions; it is also recorded into every results file.
if [ ! -d "$MATHLIB_DIR" ]; then
  echo "[lean] cloning mathlib4 @ $MATHLIB_TAG"
  git clone --depth 1 --branch "$MATHLIB_TAG" "$MATHLIB_REPO" "$MATHLIB_DIR"
else
  echo "[lean] $MATHLIB_DIR already present"
fi

cd "$MATHLIB_DIR"

# Let the repo's own lean-toolchain drive elan. Hand-writing that file gives
# "incompatible header" at import time.
echo "[lean] toolchain: $(cat lean-toolchain)"
elan toolchain install "$(cat lean-toolchain)"
elan override set "$(cat lean-toolchain)"

# --- prebuilt oleans ---------------------------------------------------------
# MANDATORY. Without `cache get`, lake compiles Mathlib from source: hours.
echo "[lean] fetching prebuilt cache (this is the step that saves hours)"
lake exe cache get

echo "[lean] lake build"
lake build

echo "[lean] done -- $MATHLIB_DIR is ready for --stage verify"
