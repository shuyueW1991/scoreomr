#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p backups
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="backups/scoreomr-${STAMP}.db"

echo "==> Creating a consistent SQLite backup inside the api container"
docker compose exec -T api mkdir -p /data/backups
docker compose exec -T api python -m app.backup /data/backups/latest.db
docker compose cp api:/data/backups/latest.db "$OUT"
docker compose exec -T api rm -f /data/backups/latest.db

echo "Backup written to $OUT"
echo "Restore with:"
echo "  docker compose cp $OUT api:/data/scoreomr.db"
echo "  docker compose restart api worker"
