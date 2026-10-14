"""Closed-cycle assertions for demo packs."""

from __future__ import annotations

from typing import Any


class ExpectError(AssertionError):
    pass


def _dig(obj: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def assert_expect(
    expect: dict[str, Any],
    *,
    feature: dict[str, Any],
    documents: dict[str, Any] | None = None,
    validate: dict[str, Any] | None = None,
    export: dict[str, Any] | None = None,
) -> None:
    errors: list[str] = []

    status = feature.get("feature_status") or feature.get("status")
    want_status = expect.get("feature_status")
    if want_status:
        allowed = want_status if isinstance(want_status, list) else [want_status]
        if status not in allowed:
            errors.append(f"feature_status={status!r} not in {allowed}")

    if expect.get("package_exported") is True:
        if not feature.get("package_exported"):
            errors.append("package_exported expected true")

    if expect.get("chat_frozen") is True:
        if not (feature.get("chat_frozen") or feature.get("package_exported")):
            errors.append("chat_frozen/package_exported expected")

    min_stories = int(expect.get("min_user_stories") or 0)
    if min_stories:
        sections = feature.get("sections") or {}
        uc = sections.get("use_cases") or {}
        data = uc.get("data") if isinstance(uc, dict) else {}
        stories: list[Any] = []
        if isinstance(data, dict):
            raw = (
                data.get("use_cases")
                or data.get("user_stories")
                or data.get("stories")
                or data.get("items")
                or []
            )
            if isinstance(raw, list):
                stories = raw
        elif isinstance(data, list):
            stories = data
        # also control artifact shape
        arts = feature.get("artifacts") or {}
        if not stories and isinstance(arts, dict):
            uc_art = arts.get("use_cases") or {}
            if isinstance(uc_art, dict):
                raw = uc_art.get("use_cases") or uc_art.get("user_stories") or uc_art.get("stories") or []
                if isinstance(raw, list):
                    stories = raw
            elif isinstance(uc_art, list):
                stories = uc_art
        if len(stories) < min_stories:
            errors.append(f"min_user_stories={min_stories}, got {len(stories)}")

    if documents is not None:
        min_company = int(expect.get("min_company_docs") or 0)
        min_project = int(expect.get("min_project_docs") or 0)
        company = documents.get("company_documents") or documents.get("company_approved") or []
        project = documents.get("project_documents") or documents.get("project_approved") or []
        # documents API uses company_documents / project_documents
        if not company and not project:
            company = [
                d
                for d in (documents.get("documents") or [])
                if (d.get("namespace") == "company")
            ]
            project = [
                d
                for d in (documents.get("documents") or [])
                if (d.get("namespace") != "company")
            ]
        if len(company) < min_company:
            errors.append(f"min_company_docs={min_company}, got {len(company)}")
        if len(project) < min_project:
            errors.append(f"min_project_docs={min_project}, got {len(project)}")

    if validate is not None and expect.get("validate_ok") is not False:
        last = validate.get("last_validation") if isinstance(validate.get("last_validation"), dict) else {}
        outcome = (
            validate.get("outcome")
            or validate.get("validation_outcome")
            or _dig(validate, "result", "outcome")
            or (last or {}).get("status")
            or feature.get("feature_status")
            or ""
        )
        # Accept passed / passed_with_warnings / VALIDATED; reject hard fail if require_pass
        if expect.get("require_validate_pass"):
            text = str(outcome).lower()
            ok = (
                "passed" in text
                or text in {"validated", "ok", "success"}
                or ("pass" in text and "fail" not in text)
            )
            if not ok:
                errors.append(f"validate outcome failed: {outcome!r}")

    if expect.get("skip_export"):
        pass
    elif export is not None and expect.get("export_ok", True):
        if export.get("ok") is False:
            errors.append(f"export not ok: {export}")

    if errors:
        raise ExpectError("; ".join(errors))
