from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from wiki.models import Actor

_BASE_FIELDS = {"ts", "operation", "actor", "actor_type", "project_id", "agent_run_id"}


def log_audit(
    root: Path,
    *,
    operation: str,
    actor: Actor,
    extra: dict | None = None,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "operation": operation,
        "actor": actor.actor,
        "actor_type": actor.actor_type,
        "project_id": actor.project_id,
        "agent_run_id": actor.agent_run_id,
        **(extra or {}),
    }
    # Platform: audit rows live in wiki.audit_log (was data/audit.jsonl).
    from wiki.db import connect

    conn = connect(root)
    try:
        conn.execute(
            "INSERT INTO audit_log (ts, operation, actor, actor_type, project_id, agent_run_id, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record["ts"],
                record["operation"],
                record["actor"],
                record["actor_type"],
                record["project_id"],
                record["agent_run_id"],
                json.dumps({k: v for k, v in record.items() if k not in _BASE_FIELDS}, ensure_ascii=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()
