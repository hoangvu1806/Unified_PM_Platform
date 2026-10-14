#!/usr/bin/env bash
# Quick health check for BA API and its LiteLLM Proxy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "==> Containers"
docker compose ps

echo "==> BA API readiness"
curl -fsS -m 5 http://127.0.0.1:8000/api/health
echo

echo "==> BA model endpoint"
docker compose exec -T api python3 -c "
from config.llm_resolve import resolve_llm_endpoint
e = resolve_llm_endpoint()
print(f'  provider={e.provider} model={e.model_name} base={e.api_base_url}')
"
