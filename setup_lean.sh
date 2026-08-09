#!/bin/bash
set -e

echo "=== Installing elan (Lean version manager) ==="
curl https://elan.lean-lang.org/elan-init.sh -sSf | sh -s -- -y
export PATH="$HOME/.elan/bin:$PATH"

echo "=== Installing Lean toolchain ==="
elan toolchain install leanprover/lean4:v4.32.0-rc1

echo "=== Creating Lean math project ==="
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "lean_project" ]; then
    lake new lean_project math
fi

cd lean_project
echo "leanprover/lean4:v4.32.0-rc1" > lean-toolchain
elan override set leanprover/lean4:v4.32.0-rc1

echo "=== Building Mathlib (this may take a while) ==="
lake build

echo "=== Lean setup complete ==="
lean --version
