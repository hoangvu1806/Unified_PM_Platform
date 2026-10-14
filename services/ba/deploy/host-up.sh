#!/usr/bin/env bash
# Host-mode BA Factory on Coder (Docker api/web runc broken): uvicorn :8010 + Vite :5173.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Coder node toolchain (npm not always on default non-interactive PATH).
export PATH="${HOME}/.local/node/bin:${HOME}/.local/bin:${PATH}"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy from .env.example and set LLM keys"
  exit 1
fi

# Prefer explicit wiki checkout beside ba-factory; never leave WIKI_MVP_ROOT unset on host.
WIKI_DEFAULT="${WIKI_MVP_ROOT_DEFAULT:-$ROOT/../wiki-mvp}"
if [[ -f "$WIKI_DEFAULT/wiki/__init__.py" ]]; then
  # macOS tar often leaves AppleDouble junk that breaks PDF filename discovery.
  find "$WIKI_DEFAULT" -name '._*' -type f -delete 2>/dev/null || true
  if ! grep -q '^WIKI_MVP_ROOT=' .env 2>/dev/null; then
    echo "WIKI_MVP_ROOT=$WIKI_DEFAULT" >> .env
    echo "==> Appended WIKI_MVP_ROOT=$WIKI_DEFAULT to .env"
  else
    # Rewrite empty or missing-on-disk values to the synced checkout.
    python3 - <<PY
from pathlib import Path
env = Path(".env")
text = env.read_text(encoding="utf-8")
lines = text.splitlines()
root = Path("$WIKI_DEFAULT").resolve()
out = []
replaced = False
for line in lines:
    if line.startswith("WIKI_MVP_ROOT="):
        cur = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not cur or not (Path(cur).expanduser() / "wiki" / "__init__.py").is_file():
            out.append(f"WIKI_MVP_ROOT={root}")
            replaced = True
            continue
    out.append(line)
if not any(l.startswith("WIKI_MVP_ROOT=") for l in out):
    out.append(f"WIKI_MVP_ROOT={root}")
    replaced = True
if replaced:
    env.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"==> Updated WIKI_MVP_ROOT={root}")
PY
  fi
fi

export API_PROXY="${API_PROXY:-http://127.0.0.1:8010}"

# Prod compose does not publish Postgres to the host. Point host uvicorn at the
# container IP without rewriting .env (Docker api still wants DB_HOST=db).
resolve_db_host() {
  local ip=""
  if command -v docker >/dev/null 2>&1; then
    docker compose -f docker-compose.prod.yml up -d db >/dev/null 2>&1 || true
    ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ba-factory-db-1 2>/dev/null || true)"
  fi
  if [[ -n "$ip" ]] && nc -z "$ip" 5432 2>/dev/null; then
    echo "$ip"
    return 0
  fi
  if nc -z 127.0.0.1 5432 2>/dev/null; then
    echo "127.0.0.1"
    return 0
  fi
  echo "localhost"
}

export DB_HOST="$(resolve_db_host)"
echo "==> DB_HOST for host uvicorn: $DB_HOST"

mkdir -p "$ROOT/.run"
stop_port() {
  local port="$1"
  local pids
  pids="$(ss -ltnp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u || true)"
  if [[ -z "$pids" ]]; then
    pids="$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  fi
  if [[ -n "$pids" ]]; then
    echo "==> Stopping listeners on :$port ($pids)"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

stop_port 8010
stop_port 5173

if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv — create it before host-up"
  exit 1
fi

NPM_BIN="$(command -v npm || true)"
if [[ -z "$NPM_BIN" ]]; then
  echo "npm not found on PATH=$PATH"
  exit 1
fi

echo "==> Starting uvicorn :8010"
nohup env DB_HOST="$DB_HOST" .venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8010 \
  >"$ROOT/.run/uvicorn-8010.log" 2>&1 &
echo $! >"$ROOT/.run/uvicorn-8010.pid"

if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && "$NPM_BIN" install)
fi

# BPMN ELK layout helper (API shells out to node tools/bpmn_elk/layout.mjs).
# Always npm ci so Linux deps match the host (tar excludes local node_modules).
if [[ -f tools/bpmn_elk/package-lock.json ]]; then
  echo "==> Installing tools/bpmn_elk (bpmn-elk-layout via npm ci)"
  (cd tools/bpmn_elk && "$NPM_BIN" ci --omit=dev)
fi

echo "==> Starting Vite :5173 (API_PROXY=$API_PROXY npm=$NPM_BIN)"
nohup env PATH="$PATH" API_PROXY="$API_PROXY" "$NPM_BIN" --prefix frontend run dev -- --host 0.0.0.0 --port 5173 --strictPort \
  >"$ROOT/.run/vite-5173.log" 2>&1 &
echo $! >"$ROOT/.run/vite-5173.pid"

echo "==> Waiting for API health..."
for i in $(seq 1 45); do
  if curl -sf http://127.0.0.1:8010/api/health >/dev/null 2>&1; then
    echo "API healthy"
    break
  fi
  sleep 1
done

curl -sf http://127.0.0.1:8010/api/health | head -c 300 || true
echo
.venv/bin/python - <<'PY'
from factory_wiki.paths import ensure_mvp_importable, mvp_root
root = ensure_mvp_importable()
import wiki
print(f"wiki_ok root={mvp_root()} file={wiki.__file__}")
PY
