#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v node >/dev/null || { echo "Node.js >= 22.12 is required"; exit 1; }
command -v pnpm >/dev/null || { echo "pnpm is required (corepack enable)"; exit 1; }

echo "==> Installing JavaScript dependencies"
pnpm install --frozen-lockfile

echo "==> Installing Python dependencies"
if command -v uv >/dev/null 2>&1; then
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/.uv-cache}"
  export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$ROOT/.uv-python}"
  cd services/backend
  uv sync --frozen --extra omr --extra dev
  if [[ "${WITH_HOMR:-0}" == "1" ]]; then
    echo "==> Installing homr into the local venv (models download on first run)"
    uv pip install --python .venv/bin/python 'homr==0.7.0'
  fi
else
  echo "uv not found; falling back to python3.12 venv + pip"
  command -v python3.12 >/dev/null || { echo "Install uv (recommended) or Python 3.12"; exit 1; }
  cd services/backend
  python3.12 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -e '.[omr,dev]'
  if [[ "${WITH_HOMR:-0}" == "1" ]]; then
    .venv/bin/pip install 'homr==0.7.0'
  fi
fi

echo
echo "Setup complete."
echo "  Web + API + worker : pnpm dev          (http://127.0.0.1:5173)"
echo "  Docker stack       : pnpm docker:up    (http://127.0.0.1:8080)"
echo "  Real engines       : OMR_MOCK=false pnpm dev  (needs Audiveris/homr)"
