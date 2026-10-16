"""Run one or all demo packs through the BA closed cycle."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from demo._runner.checks import ExpectError, assert_expect
from demo._runner.client import DemoClient, DemoClientError
from demo._runner.md_to_pdf import build_tree

DEMO_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def _ensure_pdfs(pack_dir: Path) -> None:
    shared = DEMO_ROOT / "_shared"
    if shared.exists():
        build_tree(shared)
    build_tree(pack_dir)


def _pdfs_in(dir_path: Path) -> list[Path]:
    if not dir_path.is_dir():
        return []
    return sorted(p for p in dir_path.glob("*.pdf") if p.is_file())


def _collect_wiki_pdfs(pack_dir: Path) -> tuple[list[Path], list[Path]]:
    company = _pdfs_in(DEMO_ROOT / "_shared" / "wiki" / "company")
    company += _pdfs_in(pack_dir / "wiki" / "company")
    project = _pdfs_in(pack_dir / "wiki" / "project")
    return company, project


def _should_approve_seed_page(page_id: str, *, namespace: str, project_rule_approved: bool) -> bool:
    """Approve glossary always; one project RULE page; skip section-bucket stubs.

    Firm V-WIKI checks treat bare numbers as thresholds — approving every
    CONS/ORG/CONV stub plus multiple RULE pages trips V-WIKI-01/03 and blocks Export.
    """
    pid = page_id or ""
    if pid.startswith("PG-GLOSS-"):
        return True
    if namespace == "project" and pid.startswith("PG-RULE-") and not project_rule_approved:
        return True
    return False


def _reset_project_wiki_only(client: DemoClient, *, project_id: str) -> None:
    """Delete this project's wiki pages only — never wipe company or other PRJ-* rows.

    Global /api/wiki/clear was nuking every pack's project docs, so older features
    only showed shared company glossary on wiki.html.
    """
    print(f"  wiki reset project-only {project_id}")
    try:
        listing = client.list_wiki(project_id)
    except DemoClientError as exc:
        print(f"    list skipped: {exc}")
        return
    victims = []
    for key in ("project_approved", "project_drafts", "drafts", "approved"):
        for row in listing.get(key) or []:
            if not isinstance(row, dict):
                continue
            if (row.get("namespace") or "") != "project":
                continue
            if (row.get("project_id") or "") != project_id:
                continue
            pid = row.get("page_id")
            if pid:
                victims.append(pid)
    # Stable unique
    seen: set[str] = set()
    deleted = 0
    for page_id in victims:
        if page_id in seen:
            continue
        seen.add(page_id)
        try:
            client.delete_wiki(page_id, project_id=project_id)
            deleted += 1
            print(f"    deleted {page_id}")
        except DemoClientError as exc:
            print(f"    delete {page_id} skipped: {exc}")
    print(f"    deleted {deleted} project page(s)")


def _seed_wiki(client: DemoClient, *, project_id: str, company: list[Path], project: list[Path]) -> list[str]:
    # Scope cleanup to this project_id only. Company wiki is shared (Nimbus) and
    # must survive across packs so each EXPORTED feature keeps its project docs.
    _reset_project_wiki_only(client, project_id=project_id)

    approved: list[str] = []
    project_rule_approved = False
    for path in company:
        print(f"  wiki upload company {path.name}")
        result = client.upload_wiki(path, namespace="company", project_id=project_id)
        print(
            f"    sort_status={result.get('sort_status')} "
            f"source_id={result.get('source_id')} "
            f"proposed={result.get('proposed_page_ids')}"
        )
        ids = result.get("proposed_page_ids") or []
        if not ids and result.get("sort_status") != "unchanged_existing_source":
            raise DemoClientError(
                f"company wiki upload produced empty proposed_page_ids for {path.name}: "
                f"sort_status={result.get('sort_status')} source_id={result.get('source_id')}"
            )
        for page_id in ids:
            if not _should_approve_seed_page(page_id, namespace="company", project_rule_approved=False):
                print(f"    skip approve {page_id} (leave draft)")
                continue
            row = client.approve_wiki(page_id, project_id=project_id)
            ns = (row or {}).get("namespace") or ""
            if ns != "company":
                raise DemoClientError(
                    f"company seed approve {page_id} landed in namespace={ns!r} "
                    f"project_id={(row or {}).get('project_id')!r} — expected company"
                )
            approved.append(page_id)
            print(f"    approved {page_id}")
    for path in project:
        print(f"  wiki upload project {path.name}")
        result = client.upload_wiki(path, namespace="project", project_id=project_id)
        print(
            f"    sort_status={result.get('sort_status')} "
            f"source_id={result.get('source_id')} "
            f"proposed={result.get('proposed_page_ids')}"
        )
        ids = result.get("proposed_page_ids") or []
        if not ids and result.get("sort_status") == "unchanged_existing_source":
            print(f"    dedup {result.get('source_id')} (no new drafts)")
        elif not ids:
            # The sorter found no rule/glossary content (e.g. a pure flow document): keep going,
            # the pack still needs one approved project RULE page (checked below).
            print(f"    WARN no wiki page proposed for {path.name} (sort_status={result.get('sort_status')})")
        for page_id in ids:
            if not _should_approve_seed_page(
                page_id, namespace="project", project_rule_approved=project_rule_approved
            ):
                print(f"    skip approve {page_id} (leave draft)")
                continue
            client.approve_wiki(page_id, project_id=project_id)
            approved.append(page_id)
            print(f"    approved {page_id}")
            if page_id.startswith("PG-RULE-"):
                project_rule_approved = True
    return approved


def _feature_blob(feature: dict[str, Any]) -> str:
    return json.dumps(feature, ensure_ascii=False)


def _use_case_ids(feature: dict[str, Any]) -> set[str]:
    """Ids from use_cases section data — not OQ / chat prose mentioning US-xx."""
    sections = feature.get("sections") or {}
    uc = sections.get("use_cases") or {}
    data = uc.get("data") if isinstance(uc, dict) else {}
    cases: list[Any] = []
    if isinstance(data, dict):
        raw = data.get("use_cases") or data.get("items") or data.get("user_stories") or []
        if isinstance(raw, list):
            cases = raw
    elif isinstance(data, list):
        cases = data
    return {str(c.get("id") or "") for c in cases if isinstance(c, dict) and c.get("id")}


def _needles_satisfied(feature: dict[str, Any], needles: list[str]) -> bool:
    """US-xx / BR-xx must exist as package ids; other needles stay substring checks."""
    uc_ids = _use_case_ids(feature)
    sections = feature.get("sections") or {}
    br = sections.get("business_rules") or {}
    br_data = br.get("data") if isinstance(br, dict) else {}
    rules: list[Any] = []
    if isinstance(br_data, dict):
        raw = br_data.get("business_rules") or br_data.get("items") or []
        if isinstance(raw, list):
            rules = raw
    elif isinstance(br_data, list):
        rules = br_data
    br_ids = {str(r.get("id") or "") for r in rules if isinstance(r, dict) and r.get("id")}
    blob = _feature_blob(feature)
    for n in needles:
        if re.fullmatch(r"US-\d{1,2}", n):
            # Normalize US-1 → also accept if stored as US-01 only when needle is US-01
            if n not in uc_ids and f"US-{int(n.split('-', 1)[1]):02d}" not in uc_ids:
                return False
        elif re.fullmatch(r"BR-\d{1,2}", n):
            if n not in br_ids and f"BR-{int(n.split('-', 1)[1]):02d}" not in br_ids:
                return False
        elif n not in blob:
            return False
    return True


def _wait_for(
    client: DemoClient,
    session_id: str,
    needles: list[str],
    *,
    timeout_s: float,
    strict: bool = False,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = client.get_feature(session_id)
        if _needles_satisfied(last, needles):
            return last
        time.sleep(2.0)
    msg = f"timeout waiting for {needles} in feature state"
    if strict:
        raise DemoClientError(msg)
    print(f"      WARN {msg} — continuing")
    return last


def _close_critical_oqs(client: DemoClient, session_id: str) -> None:
    feature = client.get_feature(session_id)
    open_critical = [
        oq
        for oq in (feature.get("open_questions") or [])
        if isinstance(oq, dict)
        and oq.get("status", "open") == "open"
        and oq.get("severity") == "critical"
    ]
    if not open_critical:
        return
    lines = [
        f"{oq.get('id')}: resolved for demo — use package BR/FD/WF as source of truth; close this OQ."
        for oq in open_critical
    ]
    msg = "Dong OQ critical con mo:\n" + "\n".join(lines) + "\nXac nhan dong tat ca OQ critical."
    print(f"  closing {len(open_critical)} critical OQ(s)…")
    for attempt in range(1, 3):
        try:
            client.chat(session_id, msg, active_section="feature_definition")
            break
        except DemoClientError as exc:
            if attempt < 2 and (exc.status in {500, 502, 503, 504} or "Timeout" in str(exc)):
                print(f"    retry OQ close after error: {exc}")
                time.sleep(3.0)
                continue
            raise
    time.sleep(0.5)


def _run_chat(client: DemoClient, session_id: str, chat_dir: Path, *, turn_timeout_s: float) -> None:
    files = sorted(chat_dir.glob("*.jsonl"))
    if not files:
        raise DemoClientError(f"no chat/*.jsonl in {chat_dir}")
    for path in files:
        # One-story / completeness gates often stick on open critical OQs.
        if "use_cases" in path.name or path.name.startswith("04"):
            _close_critical_oqs(client, session_id)
        print(f"  chat file {path.name}")
        for i, turn in enumerate(_load_jsonl(path), start=1):
            section = turn.get("active_section") or "feature_definition"
            message = turn["user_message"]
            print(f"    turn {i} [{section}] {message[:72]}…")
            resp = None
            for attempt in range(1, 3):
                try:
                    resp = client.chat(session_id, message, active_section=section)
                    break
                except DemoClientError as exc:
                    if exc.status == 409:
                        raise DemoClientError(
                            f"chat locked (409) on {path.name} turn {i}: {exc.body[:300]}"
                        ) from exc
                    # LLM gateway timeouts / transient 5xx — one retry.
                    if attempt < 2 and (exc.status in {500, 502, 503, 504} or "Timeout" in str(exc)):
                        print(f"      retry chat after error: {exc}")
                        time.sleep(3.0)
                        continue
                    raise
            assistant = ""
            if isinstance(resp, dict):
                assistant = str(
                    resp.get("assistant_message")
                    or resp.get("message")
                    or resp.get("reply")
                    or ""
                )[:200]
                if assistant:
                    print(f"      assistant: {assistant}…")
            wait_for = turn.get("wait_for") or []
            if wait_for:
                _wait_for(
                    client,
                    session_id,
                    list(wait_for),
                    timeout_s=turn_timeout_s,
                    strict=bool(turn.get("wait_strict")),
                )
            # Small pause so ADK state settles between turns
            time.sleep(0.5)


def run_pack(
    pack_dir: Path,
    *,
    base_url: str,
    ui_base: str,
    turn_timeout_s: float = 120.0,
    project: str | None = None,
    login: str | None = None,
    password: str = "demo123",
    core_url: str | None = None,
) -> dict[str, Any]:
    pack_dir = pack_dir.resolve()
    feature_cfg = _load_json(pack_dir / "feature.json")
    expect = _load_json(pack_dir / "expect.json") if (pack_dir / "expect.json").is_file() else {}

    client = DemoClient(base_url, timeout_s=max(180.0, turn_timeout_s))
    if login:
        # Platform: log in through core-api (gateway root) before calling BA.
        client.login(core_url or base_url.rsplit("/ba", 1)[0], login, password)
        print(f"  logged in as {login}")
    health = client.health()
    if health.get("status") not in {"ok", "healthy", None} and health.get("adk_ready") is False:
        raise DemoClientError(f"API not ready: {health}")

    print(f"==> pack {pack_dir.name}")
    _ensure_pdfs(pack_dir)
    company_pdfs, project_pdfs = _collect_wiki_pdfs(pack_dir)
    if not project_pdfs:
        raise DemoClientError(f"no project PDFs under {pack_dir / 'wiki' / 'project'}")

    created = client.create_feature(
        feature_cfg["title"],
        feature_cfg.get("description") or "",
        project_id=project,
    )
    session_id = created["session_id"]
    project_id = created.get("project_id") or ""
    if not project_id:
        feature = client.get_feature(session_id)
        project_id = feature.get("project_id") or ""
    print(f"  session={session_id}")
    print(f"  project_id={project_id}")

    _seed_wiki(client, project_id=project_id, company=company_pdfs, project=project_pdfs)

    chat_dir = pack_dir / "chat"
    _run_chat(client, session_id, chat_dir, turn_timeout_s=turn_timeout_s)

    # Close any leftover critical OQs so Validate gate can open (LLM often leaves one).
    _close_critical_oqs(client, session_id)

    print("  validate…")
    validate = client.validate(session_id)
    print(f"    validate={json.dumps(validate, ensure_ascii=False)[:240]}")

    skip_export = bool(expect.get("skip_export")) or expect.get("export_ok") is False
    export: dict[str, Any] | None
    if skip_export:
        print("  export skipped (expect.skip_export / export_ok=false)")
        export = None
    else:
        print("  export…")
        export = client.export(session_id)
        print(f"    export={json.dumps(export, ensure_ascii=False)[:240]}")

    feature = client.get_feature(session_id)
    documents = client.documents(session_id)
    assert_expect(
        expect,
        feature=feature,
        documents=documents,
        validate=validate,
        export=export,
    )

    chat_url = f"{ui_base.rstrip('/')}/chat.html?session={session_id}&project_id={project_id}"
    wiki_url = f"{ui_base.rstrip('/')}/wiki.html?session={session_id}&project_id={project_id}"
    print(f"  OK chat={chat_url}")
    print(f"  OK wiki={wiki_url}")
    return {
        "pack": pack_dir.name,
        "session_id": session_id,
        "project_id": project_id,
        "chat_url": chat_url,
        "wiki_url": wiki_url,
        "ok": True,
    }


def discover_packs(root: Path) -> list[Path]:
    packs = []
    for path in sorted(root.iterdir()):
        if path.name.startswith("_"):
            continue
        if path.is_dir() and (path / "feature.json").is_file():
            packs.append(path)
    return packs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run BA demo pack closed cycle")
    parser.add_argument("pack", nargs="?", help="Path to demo/proj_* (or omit with --all)")
    parser.add_argument("--all", action="store_true", help="Run every demo/proj_* pack")
    parser.add_argument("--continue", dest="continue_on_fail", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ui-base", default="http://127.0.0.1:5173")
    parser.add_argument("--turn-timeout", type=float, default=180.0)
    # Platform (gateway): --base-url http://gateway/ba --ui-base http://localhost:8080/ba
    parser.add_argument("--project", help="platform project id the feature belongs to")
    parser.add_argument("--login", help="platform username (needs BA; ADMIN to seed company wiki)")
    parser.add_argument("--password", default="demo123")
    parser.add_argument("--core-url", help="gateway root for core-api login (default: base-url without /ba)")
    args = parser.parse_args(argv)

    # Allow `python -m demo._runner.run_demo` from repo root
    repo_root = DEMO_ROOT.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    packs: list[Path] = []
    if args.all:
        packs = discover_packs(DEMO_ROOT)
    elif args.pack:
        packs = [Path(args.pack)]
    else:
        parser.error("provide a pack path or --all")

    results: list[dict[str, Any]] = []
    failed = 0
    for pack in packs:
        try:
            results.append(
                run_pack(
                    pack,
                    base_url=args.base_url,
                    ui_base=args.ui_base,
                    turn_timeout_s=args.turn_timeout,
                    project=args.project,
                    login=args.login,
                    password=args.password,
                    core_url=args.core_url,
                )
            )
        except (DemoClientError, ExpectError, OSError, json.JSONDecodeError) as exc:
            failed += 1
            print(f"FAIL {pack}: {exc}", file=sys.stderr)
            results.append({"pack": str(pack), "ok": False, "error": str(exc)})
            if not args.continue_on_fail:
                break

    print("\n== summary ==")
    for row in results:
        print(("PASS" if row.get("ok") else "FAIL"), row.get("pack"), row.get("error", ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
