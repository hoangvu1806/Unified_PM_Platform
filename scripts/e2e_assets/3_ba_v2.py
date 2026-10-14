"""ba-api: publish a changed BA package (v2)."""
import json, os, sys

sys.path.insert(0, "/app")
from managers.service.assets import publish_ba_package  # noqa: E402

feature = os.environ["FEATURE_ID"]
v2 = publish_ba_package(feature, {"feature_id": feature, "payload": {"rules": ["R1", "R2"]}}, "ba.an")
assert v2["version"] == 2
print(json.dumps({"ba_v2": v2["id"]}))
