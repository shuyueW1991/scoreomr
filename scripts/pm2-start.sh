#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v pm2 >/dev/null || { echo "pm2 is required: npm i -g pm2"; exit 1; }
command -v docker >/dev/null || { echo "Docker is required for the api/worker containers"; exit 1; }
[[ -f .env ]] || { echo "Missing .env; copy .env.example and configure it first"; exit 1; }

API_PORT="$(grep -E '^API_HOST_PORT=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
API_PORT="${API_PORT:-8000}"

if [[ ! -d node_modules || ! -f apps/web/dist/index.html ]]; then
  echo "==> Installing frontend dependencies and building"
  pnpm install --frozen-lockfile
  pnpm build
else
  echo "==> Building frontend"
  pnpm build
fi

echo "==> Starting api + worker containers"
docker compose -f compose.yml -f compose.pm2.yml up -d --build api worker

echo "==> Waiting for API on 127.0.0.1:${API_PORT}"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:${API_PORT}/api/health" >/dev/null || {
  echo "API did not become healthy; run: docker compose -f compose.yml -f compose.pm2.yml logs api"
  exit 1
}

echo "==> Starting/reloading pm2 web process"
pm2 startOrReload ecosystem.config.cjs --update-env
pm2 save

echo
echo "ScoreOMR web process is managed by pm2 as 'scoreomr'."
echo "Check: pm2 status; pm2 logs scoreomr"
echo "If TLS_CERT_FILE/TLS_KEY_FILE are set, open the https URL on port 3015."
