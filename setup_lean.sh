#!/bin/bash
set -e

echo "=== Installing elan (Lean version manager) ==="
curl https://elan.lean-lang.org/elan-init.sh -sSf | sh -s -- -y

# Source elan env so lake/elan/lean are on PATH for the rest of this script.
. "$HOME/.elan/env" 2>/dev/null || export PATH="$HOME/.elan/bin:$PATH"

echo "=== Installing Lean toolchain ==="
# Stable release — RC toolchains often lack a Mathlib release tag.
LEAN_TOOLCHAIN="leanprover/lean4:v4.26.0"
elan toolchain install "$LEAN_TOOLCHAIN"

echo "=== Creating Lean math project ==="
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Pin the toolchain BEFORE lake new so the new project's lean-toolchain
# already matches the Lean we'll build with.
echo "$LEAN_TOOLCHAIN" > lean-toolchain
elan override set "$LEAN_TOOLCHAIN"

if [ ! -d "lean_project" ]; then
    lake new lean_project math
fi

cd lean_project

echo "=== Building Mathlib (this may take a while) ==="
lake build
echo "lake version: $(lake --version)"

echo "=== Lean setup complete ==="
lean --version
