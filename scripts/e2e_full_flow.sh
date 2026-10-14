#!/usr/bin/env sh
# Full real flow on a clean platform: PM creates a project -> BA scenario with the
# real LLM (wiki, 4 sections, validate, export) -> journey check -> Designer with
# the real LLM and OpenPencil (handoff, scope, spec review, build, final review)
# -> journey done -> storage check. An OpenPencil editor tab must be open.
set -eu
cd "$(dirname "$0")/.."
G=http://localhost:${PLATFORM_GATEWAY_PORT:-8080}
PM=${PM_USER:-pm.hoa}
py() { docker run --rm -i python:3.12-slim python -c "$1"; }
jar=$(mktemp)
curl -sf -c "$jar" -H 'Content-Type: application/json' -d "{\"username\":\"$PM\",\"password\":\"demo123\"}" "$G/api/core/auth/login" >/dev/null

echo "== 1. $PM creates a project"
PROJECT=$(curl -sf -b "$jar" -H 'Content-Type: application/json' \
  -d '{"name":"Kho v\u1eadt t\u01b0","description":"Y\u00eau c\u1ea7u v\u1eadt t\u01b0, ph\u00ea duy\u1ec7t m\u1ed9t ng\u01b0\u1eddi, pick-pack kho"}' \
  "$G/api/core/projects" | py "import json,sys;d=json.load(sys.stdin);print(d['id'])")
echo "project $PROJECT"

echo "== 2. BA scenario (real LLM)"
docker compose exec -T ba-api python -u -m demo._runner.run_demo demo/proj_warehouse \
  --base-url http://gateway/ba --ui-base "$G/ba" --project "$PROJECT" --login "$PM" --turn-timeout 600 | tee case-ba.log
FEATURE=$(grep -o 'session=[0-9a-f-]*' case-ba.log | head -n1 | cut -d= -f2)
echo "feature $FEATURE"

journey() {
  curl -sf -b "$jar" "$G/api/core/projects/$PROJECT/features/$FEATURE/journey" |
    py "import json,sys;d=json.load(sys.stdin);print(d['current'], sum(s['status']=='done' for s in d['steps']), 'pkg', d['ba_package'])"
}
echo "== 3. journey after BA: $(journey)"

echo "== 4. Designer (real LLM + OpenPencil)"
MSYS_NO_PATHCONV=1 docker run --rm --network platform_default -v "$PWD/scripts:/s:ro" python:3.12-slim \
  python -u /s/case_designer.py http://gateway "$PROJECT" "$FEATURE" "$PM" | tee case-designer.log

sleep 35   # let per-project logs flush to storage
echo "== 5. journey after Designer: $(journey)"
echo "== 6. storage"
docker compose exec -T core-api python -c "
from collections import Counter
from platform_core.storage import get_storage
s = get_storage()
keys = list(s.keys('projects/$PROJECT/'))
for k, n in sorted(Counter('/'.join(k.split('/')[2:4]) for k in keys).items()):
    print(f'  {k:28} {n}')
print('  shared/:', len(list(s.keys('shared/'))))
"
echo "PROJECT=$PROJECT FEATURE=$FEATURE"
