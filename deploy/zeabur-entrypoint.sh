#!/bin/sh
# ScoreOMR single-container entrypoint (root Dockerfile / Zeabur).
#
# One container = three roles:
#   node apps/web/server.mjs  web gateway: SPA + /api proxy, listens on $PORT
#   uvicorn                   FastAPI on 127.0.0.1:8000 (loopback only)
#   python -m app.worker      SQLite queue consumer (same data dir)
#
# The container starts as root so a mounted /data volume can be re-owned;
# every process is then dropped to uid 10001 (the app user).
set -e

PORT="${PORT:-3000}"
DATA_DIR="${DATA_DIR:-/data}"
echo "[zeabur] entry: PORT=${PORT} DATA_DIR=${DATA_DIR}"

mkdir -p "${DATA_DIR}"
chown -R 10001:10001 "${DATA_DIR}"
cd /app

echo "[zeabur] starting api on 127.0.0.1:8000"
setpriv --reuid=10001 --regid=10001 --init-groups \
  /opt/venv/bin/uvicorn app.main:create_app --factory \
  --host 127.0.0.1 --port 8000 \
  --proxy-headers --forwarded-allow-ips=127.0.0.1 &
API_PID=$!

echo "[zeabur] starting worker"
setpriv --reuid=10001 --regid=10001 --init-groups \
  /opt/venv/bin/python -m app.worker &

echo "[zeabur] starting web gateway on :${PORT}"
exec setpriv --reuid=10001 --regid=10001 --init-groups \
  node /app/apps/web/server.mjs --port "${PORT}"