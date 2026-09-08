#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the AIcheck monorepo.
# Prepares the FastAPI backend virtualenv and the Vue/Vite frontend dependencies.
# Safe to run repeatedly; no dev servers are started here (see environment.json terminals).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- Backend (Python 3.11+/FastAPI) -----------------------------------------
# The default image ships python3.12 but the venv module can be missing; the
# environment build boots from a snapshot that already has it, and this guard
# keeps a fresh VM working too.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  echo "[install] python venv module missing; installing python3-venv"
  sudo apt-get update -qq
  sudo apt-get install -y "python3.12-venv" || sudo apt-get install -y python3-venv
fi

cd "$REPO_ROOT/backend"
if [ ! -x .venv/bin/python ]; then
  echo "[install] creating backend virtualenv"
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# --- Frontend (Node/pnpm) ----------------------------------------------------
cd "$REPO_ROOT/frontend"
pnpm install --frozen-lockfile

echo "[install] done"
