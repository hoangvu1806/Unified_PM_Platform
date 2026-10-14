"""ba-api: publish BA package v1 for FEATURE_ID (idempotent re-export), then hand off."""
import json, os, sys, urllib.request

sys.path.insert(0, "/app")
from managers.service.assets import publish_ba_package  # noqa: E402

feature = os.environ["FEATURE_ID"]
env1 = {"correlation_id": f"{feature}:e2e", "feature_id": feature, "payload": {"rules": ["R1"]}}
v1 = publish_ba_package(feature, env1, "ba.an")
again = publish_ba_package(feature, dict(env1, message_id="other"), "ba.an")
assert v1["version"] == 1 and again["id"] == v1["id"], "re-export of same payload must not create a version"
body = {"correlation_id": f"{feature}:designer-v2", "feature_id": feature, "prompt": "Analyze; ask approval.",
        "title": "E2E assets design", "project_id": "PRJ-AURORA", "requested_by": "ba.an"}
req = urllib.request.Request("http://designer-api:8282/api/v1/handoffs", data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json", "X-Agent-Secret": os.environ["DESIGNER_SHARED_SECRET"]})
resp = json.loads(urllib.request.urlopen(req).read())
print(json.dumps({"ba_v1": v1["id"], "session_id": resp["session_id"]}))
