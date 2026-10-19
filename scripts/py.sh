#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/services/backend/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Python environment missing. Run: pnpm setup" >&2
  exit 1
fi
cd "$ROOT/services/backend"
exec "$PY" "$@"
