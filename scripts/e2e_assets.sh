#!/usr/bin/env sh
# Sprint 4 end-to-end: BA v1 -> handoff -> design published -> BA v2 -> design stale.
# Runs everything inside the platform containers. KEEP=1 keeps the data.
set -eu
cd "$(dirname "$0")/.."
G=http://localhost:${PLATFORM_GATEWAY_PORT:-8080}
DIR=scripts/e2e_assets
jar_an=$(mktemp); jar_binh=$(mktemp); jar_chi=$(mktemp)
login() { curl -sf -c "$1" -H 'Content-Type: application/json' -d "{\"username\":\"$2\",\"password\":\"demo123\"}" "$G/api/core/auth/login" >/dev/null; }
login "$jar_an" ba.an; login "$jar_binh" designer.binh; login "$jar_chi" ba.chi
# JSON parsing also runs in a container (nothing executes on the host Python).
py() { docker run --rm -i python:3.12-slim python -c "$1"; }
json() { py "import json,sys;print(json.load(sys.stdin)$1)"; }

FEATURE_ID=$(curl -sf -b "$jar_an" -H 'Content-Type: application/json' -d '{"title":"E2E assets feature","project_id":"PRJ-AURORA"}' "$G/ba/api/features" | json "['session_id']")
echo "feature $FEATURE_ID"
OUT=$(docker compose exec -T -e FEATURE_ID="$FEATURE_ID" ba-api python - < $DIR/1_ba_publish.py); echo "$OUT"
SESSION_ID=$(echo "$OUT" | tail -n1 | json "['session_id']")
OUT=$(docker compose exec -T -e SESSION_ID="$SESSION_ID" designer-api python - < $DIR/2_designer_publish.py); echo "$OUT"
DESIGN_ID=$(echo "$OUT" | tail -n1 | json "['design']")
docker compose exec -T -e FEATURE_ID="$FEATURE_ID" ba-api python - < $DIR/3_ba_v2.py

ARTS=$(curl -sf -b "$jar_binh" "$G/api/core/projects/PRJ-AURORA/artifacts")
STALE=$(echo "$ARTS" | py "import json,sys;a=[x for x in json.load(sys.stdin) if x['id']=='$DESIGN_ID'][0];print(a['stale'],a['derived_version'],a['derived_latest_version'])")
echo "design stale/derived/latest: $STALE"
[ "$STALE" = "True 1 2" ] || { echo "FAIL: design should be stale (from BA v1, latest v2)"; exit 1; }
BYTES=$(curl -sf -b "$jar_binh" "$G/api/core/artifacts/$DESIGN_ID/download")
[ "$BYTES" = "FIG-E2E-BYTES" ] || { echo "FAIL: design download"; exit 1; }
CODE=$(curl -s -o /dev/null -w '%{http_code}' -b "$jar_chi" "$G/api/core/artifacts/$DESIGN_ID/download")
[ "$CODE" = "404" ] || { echo "FAIL: non-member download should be 404, got $CODE"; exit 1; }
CODE=$(curl -s -o /dev/null -w '%{http_code}' -b "$jar_chi" "$G/api/core/projects/PRJ-AURORA/artifacts")
[ "$CODE" = "404" ] || { echo "FAIL: non-member artifacts should be 404, got $CODE"; exit 1; }
docker compose exec -T -e FEATURE_ID="$FEATURE_ID" -e DESIGN_ID="$DESIGN_ID" -e KEEP="${KEEP:-0}" core-api python - < $DIR/4_check_and_cleanup.py
if [ "${KEEP:-0}" != "1" ]; then
  curl -sf -b "$jar_an" -X DELETE "$G/ba/api/features/$FEATURE_ID" >/dev/null || true
  curl -sf -b "$jar_binh" -X DELETE "$G/designer/api/v1/sessions/$SESSION_ID" >/dev/null || true
fi
rm -f "$jar_an" "$jar_binh" "$jar_chi"
echo "E2E assets: PASS"
