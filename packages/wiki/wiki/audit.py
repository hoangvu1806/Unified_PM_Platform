from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from wiki.models import Actor
from wiki.paths import audit_path, data_dir


def log_audit(
    root: Path,
    *,
    operation: str,
    actor: Actor,
    extra: dict | None = None,
) -> None:
    data_dir(root).mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "operation": operation,
        "actor": actor.actor,
        "actor_type": actor.actor_type,
        "project_id": actor.project_id,
        "agent_run_id": actor.agent_run_id,
        **(extra or {}),
    }
    with audit_path(root).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")
