"""core-api: verify bucket objects, then remove everything the run created."""
import json, os
from platform_core import artifacts
from platform_core.storage import get_storage

feature, design = os.environ["FEATURE_ID"], os.environ["DESIGN_ID"]
s = get_storage()
rows = [r for r in artifacts.list_for_project("PRJ-AURORA") if r["source_ref"] == feature or r["id"] == design]
missing = [r["storage_key"] for r in rows if not s.exists(r["storage_key"])]
assert not missing, f"objects missing in bucket: {missing}"
print(json.dumps({"bucket": getattr(s, "bucket", "local"), "objects_verified": len(rows)}))
if os.environ.get("KEEP") != "1":
    import psycopg
    from platform_core.db import database_url
    with psycopg.connect(database_url("core", "libpq")) as conn:
        for r in sorted(rows, key=lambda r: r["kind"] != "designer_output"):  # children first
            s.delete(r["storage_key"])
            conn.execute("DELETE FROM core.artifacts WHERE id=%s", (r["id"],))
    print("cleaned")
