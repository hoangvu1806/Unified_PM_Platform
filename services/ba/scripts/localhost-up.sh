#!/usr/bin/env bash
# Host BA stack when Docker/runc is broken. Reuses July4 demo SQLite under /tmp by default.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
NODE="${CURSOR_NODE:-/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node}"
SYNC_DB="${BA_SYNC_DB:-/tmp/ba-july4-sync.db}"
ADK_DB="${BA_ADK_DB:-/tmp/ba-july4-adk.db}"
API_LOG="${BA_API_LOG:-/tmp/ba-july4-api.log}"
VITE_LOG="${BA_VITE_LOG:-/tmp/ba-july4-vite.log}"
API_PY="${BA_API_PY:-/tmp/ba-july4-api-start.py}"

cat >"$API_PY" <<PY
import os
from unittest.mock import PropertyMock, patch
from config.base_config import Settings
from managers.database.connection import configure_sync_engine, init_db

print("WIKI_MVP_ROOT", os.environ.get("WIKI_MVP_ROOT"))
configure_sync_engine("sqlite:///${SYNC_DB}")
init_db()
with patch.object(
    Settings,
    "database_url",
    new_callable=PropertyMock,
    return_value="sqlite+aiosqlite:///${ADK_DB}",
):
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, log_level="info")
PY

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Already listening on :8000"
else
  if [[ ! -f "$SYNC_DB" || ! -f "$ADK_DB" ]]; then
    echo "Missing $SYNC_DB or $ADK_DB — set BA_SYNC_DB/BA_ADK_DB." >&2
    exit 1
  fi
  set -a; source .env; set +a
  export WIKI_MVP_ROOT="${WIKI_MVP_ROOT:-$ROOT/../../mvp}"
  export LITELLM_API_BASE_URL="${LLM_GATE_API_BASE_URL:-}"
  export LITELLM_MODEL_NAME="${LLM_GATE_MODEL_NAME:-}"
  export LITELLM_MASTER_KEY="${LLM_GATE_API_KEY:-}"
  export PYTHONPATH=.
  : >"$API_LOG"
  nohup .venv/bin/python "$API_PY" >>"$API_LOG" 2>&1 &
  disown || true
  echo "API pid $! (log $API_LOG)"
fi

if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Already listening on :5173"
else
  if [[ ! -x "$NODE" ]]; then
    echo "Need arm64 node at CURSOR_NODE=$NODE (system x64 node breaks Rollup)." >&2
    exit 1
  fi
  : >"$VITE_LOG"
  (cd frontend && nohup "$NODE" node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 >>"$VITE_LOG" 2>&1 & disown) || true
  echo "Vite starting (log $VITE_LOG)"
fi

sleep 2
curl -sf http://127.0.0.1:8000/api/health && echo
curl -sI http://127.0.0.1:5173/ | head -1
echo "Chat (July4): http://127.0.0.1:5173/chat.html?session=349589dc-ccbe-4c91-b6c9-65b25bb1a182"
echo "Keep-alive: leave Cursor background terminals running, or: bash scripts/localhost-up.sh"
