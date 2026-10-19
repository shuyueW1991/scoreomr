#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: bash scripts/restore.sh backups/scoreomr-YYYYmmdd-HHMMSS.db" >&2
  exit 1
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
BACKUP="$1"
[[ -f "$BACKUP" ]] || { echo "Backup not found: $BACKUP" >&2; exit 1; }

echo "==> Stopping api and worker"
docker compose stop api worker

echo "==> Restoring into the scoreomr-data volume"
docker run --rm \
  -v scoreomr-data:/data \
  -v "$ROOT/backups:/backups:ro" \
  alpine:3.20 sh -c "rm -f /data/scoreomr.db /data/scoreomr.db-wal /data/scoreomr.db-shm && cp '/backups/$(basename "$BACKUP")' /data/scoreomr.db && chown 10001:10001 /data/scoreomr.db && chmod 600 /data/scoreomr.db"

echo "==> Starting api and worker"
docker compose start api worker
docker compose ps
