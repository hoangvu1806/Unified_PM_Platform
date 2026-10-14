#!/usr/bin/env bash
# Deploy BA Factory stack on Coder workspace (production docker).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE="docker compose -f docker-compose.prod.yml"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy from .env.example and set OPENAI_API_KEY"
  exit 1
fi

echo "==> Building and starting BA Factory (api :8010, web :5173)..."
$COMPOSE up -d --build

echo "==> Waiting for API health..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8010/api/health >/dev/null 2>&1; then
    echo "API healthy"
    break
  fi
  sleep 3
done

curl -sf http://127.0.0.1:8010/api/health | head -c 200 || true
echo
$COMPOSE ps
