"""Feature journey: one guided path from BA analysis to the reviewed design.

Computed on read from the module schemas (same database):
  ba.ba_packages / ba.ba_package_sections  -> steps 1-6
  designer.sessions / runs / reviews        -> steps 7-9
  core.artifacts                            -> BA package version, design stale flag

Nothing is stored here; the agents stay the source of truth.
"""

from __future__ import annotations

from typing import Any

BA_SECTIONS = [
    ("feature_definition", "Định nghĩa feature", "Mục tiêu, actor, phạm vi trong/ngoài."),
    ("business_rules", "Quy tắc nghiệp vụ", "Các quy tắc BR-xx mà hệ thống phải tuân theo."),
    ("workflow", "Quy trình", "Luồng chính và BPMN."),
    ("use_cases", "Use case", "User story và tiêu chí chấp nhận."),
]
DESIGN_PAST_SPEC = {"components", "binding", "assembly", "layout_check", "review_final", "finished"}


def _step(key: str, label: str, role: str, hint: str) -> dict[str, Any]:
    return {"key": key, "label": label, "role": role, "hint": hint, "status": "todo", "reason": None}


def _exists(conn, table: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL AS ok", (table,)).fetchone()["ok"]


def build_journey(conn, project_id: str, feature_id: str) -> dict[str, Any] | None:
    pkg = conn.execute(
        "SELECT session_id::text AS id, feature_title, feature_status, validation_status, updated_at "
        "FROM ba.ba_packages WHERE session_id::text = %s AND project_id = %s",
        (feature_id, project_id),
    ).fetchone()
    if not pkg:
        return None
    sections = {
        r["section_id"]: bool(r["is_completable"])
        for r in conn.execute(
            "SELECT section_id, is_completable FROM ba.ba_package_sections WHERE session_id::text = %s",
            (feature_id,),
        ).fetchall()
    }
    status = pkg["feature_status"] or "DRAFT"

    designer: dict[str, Any] | None = None
    runs: list[dict[str, Any]] = []
    reviews: set[tuple[str, str]] = set()
    if _exists(conn, "designer.sessions"):
        designer = conn.execute(
            "SELECT id, title, source_artifact_id FROM designer.sessions "
            "WHERE project_id = %s AND source_ref = %s ORDER BY created_at DESC LIMIT 1",
            (project_id, feature_id),
        ).fetchone()
        if designer:
            runs = conn.execute(
                "SELECT id, stage, status, revision, created_at FROM designer.runs WHERE session_id = %s "
                "ORDER BY created_at",
                (designer["id"],),
            ).fetchall()
            reviews = {
                (r["checkpoint"], r["decision"])
                for r in conn.execute(
                    "SELECT v.checkpoint, v.decision FROM designer.reviews v JOIN designer.runs r ON r.id = v.run_id "
                    "WHERE r.session_id = %s",
                    (designer["id"],),
                ).fetchall()
            }

    package = conn.execute(
        "SELECT id, version FROM core.artifacts WHERE kind = 'ba_package' AND source_ref = %s "
        "ORDER BY version DESC LIMIT 1",
        (feature_id,),
    ).fetchone() if _exists(conn, "core.artifacts") else None
    design = None
    used_version = None
    if designer and _exists(conn, "core.artifacts"):
        design = conn.execute(
            "SELECT id, version, storage_key FROM core.artifacts WHERE kind = 'designer_output' "
            "AND meta->>'session_id' = %s ORDER BY created_at DESC LIMIT 1",
            (designer["id"],),
        ).fetchone()
        if designer["source_artifact_id"]:
            src = conn.execute(
                "SELECT version FROM core.artifacts WHERE id = %s", (designer["source_artifact_id"],)
            ).fetchone()
            used_version = src["version"] if src else None

    steps: list[dict[str, Any]] = []
    for key, label, hint in BA_SECTIONS:
        s = _step(key, label, "BA", hint)
        s["status"] = "done" if sections.get(key) else "todo"
        steps.append(s)
    validate = _step("validate", "Kiểm tra", "BA", "Validation agent đối chiếu 4 section với wiki.")
    if status in {"VALIDATED", "EXPORTED"}:
        validate["status"] = "done"
    elif status == "VALIDATION_FAILED":
        validate.update(status="attention", reason="Validate chưa đạt: xem báo cáo và sửa các section.")
    steps.append(validate)
    export = _step("export", "Bàn giao BA package", "BA", "Xuất BA package có phiên bản vào Assets.")
    export["status"] = "done" if status == "EXPORTED" else "todo"
    steps.append(export)

    stages = {r["stage"] for r in runs}
    scope = _step("design_scope", "Phạm vi thiết kế", "DESIGNER", "Designer agent đề xuất màn hình, bạn chốt phạm vi và duyệt spec.")
    scope["status"] = "done" if ("specification", "approved") in reviews or stages & DESIGN_PAST_SPEC else "todo"
    build = _step("design_build", "Dựng màn hình", "DESIGNER", "Agent dựng màn hình trên OpenPencil (editor phải đang mở).")
    reviewed_final = any(cp == "final" for cp, _d in reviews)
    build["status"] = "done" if ("review_final" in stages or reviewed_final or design) else "todo"
    final = _step("design_review", "Duyệt thiết kế", "DESIGNER", "Duyệt bản cuối; thiết kế được lưu vào Assets.")
    # A stored "approved" review is not enough: the Designer can still reject it
    # (e.g. LAYOUT_NOT_VALID) and send the run back to review. Done = run finished.
    finished = any(r["stage"] == "finished" and r["status"] == "completed" for r in runs)
    final["status"] = "done" if finished or design else "todo"
    steps += [scope, build, final]

    # Order + locks: everything after the first unfinished step is locked.
    current = None
    for i, s in enumerate(steps):
        if s["status"] == "done":
            continue
        if current is None:
            current = s["key"]
            s["status"] = "attention" if s["status"] == "attention" else "current"
            continue
        prev = steps[i - 1]
        s["status"] = "locked"
        s["reason"] = f"Cần hoàn tất \"{prev['label']}\" trước."
    for s in steps[6:]:
        if s["status"] in {"current", "locked"} and status != "EXPORTED":
            s["status"] = "locked"
            s["reason"] = "Thiết kế mở sau khi BA package được bàn giao (bước 6)."
    if current in {"design_scope", "design_build", "design_review"} and status != "EXPORTED":
        current = "export"

    latest_run = runs[-1] if runs else None
    return {
        "project_id": project_id,
        "feature": {"id": pkg["id"], "title": pkg["feature_title"], "status": status},
        "current": current or "done",
        "role": "DESIGNER" if current in {"design_scope", "design_build", "design_review"} else "BA",
        "steps": steps,
        "ba_package": {
            "latest_version": package["version"] if package else None,
            "used_by_design": used_version,
            "stale": bool(used_version and package and package["version"] > used_version),
        },
        "designer": {
            "session_id": designer["id"] if designer else None,
            "latest_run": {"stage": latest_run["stage"], "status": latest_run["status"]} if latest_run else None,
            "design_artifact_id": design["id"] if design else None,
        },
        "sections": {key: sections.get(key, False) for key, _l, _h in BA_SECTIONS},
    }
