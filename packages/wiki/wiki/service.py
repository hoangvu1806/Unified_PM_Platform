from __future__ import annotations

import hashlib
import json
import re

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki.audit import log_audit
from wiki.db import Connection, connect, row_to_dict
from wiki.extract import extract_pdf
from wiki.models import (
    Actor,
    ProposePageIn,
    SearchHit,
    SearchQuery,
    WikiError,
    WikiPage,
    WikiSource,
)
from wiki.llm_config import build_sorter
from wiki.paths import blob_key, delete_blob, put_blob
from wiki.permissions import require_project_scope, require_tool
from wiki.sort import Sorter


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _slug(text: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").upper()
    return slug[:24] or fallback


class WikiService:
    def __init__(self, root: Path, sorter: Sorter | None = None) -> None:
        self.root = root
        self.sorter = sorter or build_sorter()
        self._conn = connect(root)

    @property
    def conn(self) -> "Connection":
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def reset_store(self) -> dict:
        """Wipe the wiki tables + their blobs only. Never touches BA/ADK schemas."""
        from wiki.db import TABLES, schema_name

        schema = schema_name()
        names = {
            row[0]
            for row in self.conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
                (schema,),
            )
        }
        foreign = names & {
            "ba_packages",
            "ba_package_sections",
            "sessions",
            "events",
            "app_states",
            "user_states",
            "adk_internal_metadata",
        }
        if foreign:
            raise WikiError(
                "COMMON_PRECONDITION_FAILED",
                f"refusing to clear schema {schema}: contains BA/ADK tables {sorted(foreign)}",
                409,
            )
        keys = [
            str(row["storage_uri"])
            for row in self.conn.execute("SELECT storage_uri FROM wiki_source")
        ] if "wiki_source" in names else []
        for table in TABLES:
            if table in names:
                self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        removed_blobs = 0
        for key in keys:
            try:
                removed_blobs += int(delete_blob(key))
            except ValueError:
                continue  # legacy absolute paths are not ours to delete
        return {"pages": 0, "sources": 0, "removed_blobs": removed_blobs, "wiki_db": f"postgres:{schema}"}

    def ingest_source(
        self,
        actor: Actor,
        *,
        filename: str,
        data: bytes,
        namespace: str,
        project_id: str | None,
        source_id: str | None = None,
        sort_mode: str | None = None,
    ) -> dict:
        require_tool(self.root, actor, "wiki.ingest_source")
        require_project_scope(actor, namespace=namespace, project_id=project_id)
        if namespace not in {"company", "project"}:
            raise WikiError("COMMON_SCHEMA_INVALID", "namespace must be company or project")
        if not data:
            raise WikiError("COMMON_SCHEMA_INVALID", "empty file")

        prev_sorter = self.sorter
        if sort_mode:
            self.sorter = build_sorter(sort_mode)
        try:
            return self._ingest_source_body(
                actor,
                filename=filename,
                data=data,
                namespace=namespace,
                project_id=project_id,
                source_id=source_id,
            )
        finally:
            self.sorter = prev_sorter

    def _ingest_source_body(
        self,
        actor: Actor,
        *,
        filename: str,
        data: bytes,
        namespace: str,
        project_id: str | None,
        source_id: str | None = None,
    ) -> dict:
        digest = _sha256(data)
        existing = self.conn.execute(
            """
            SELECT * FROM wiki_source
            WHERE sha256 = ?
              AND namespace = ?
              AND (
                (CAST(? AS TEXT) IS NULL AND project_id IS NULL)
                OR project_id = ?
              )
            """,
            (digest, namespace, project_id, project_id),
        ).fetchone()
        if existing:
            src = WikiSource(**row_to_dict(existing))
            page_ids = [
                str(r["page_id"])
                for r in self.conn.execute(
                    """
                    SELECT page_id FROM wiki_page
                    WHERE source_ids LIKE ?
                    ORDER BY updated_at DESC
                    """,
                    (f'%"{src.source_id}"%',),
                ).fetchall()
            ]
            log_audit(
                self.root,
                operation="wiki.ingest_source",
                actor=actor,
                extra={"source_id": src.source_id, "dedup": True, "proposed_page_ids": page_ids},
            )
            return {
                "source_id": src.source_id,
                "extract_status": "complete",
                "sort_status": "unchanged_existing_source",
                "sort_backend": "dedup",
                "proposed_page_ids": page_ids,
            }

        source_id = source_id or f"SRC-{digest[:8].upper()}"
        # Same bytes may already exist under another project/namespace — use a distinct source_id.
        if self.conn.execute(
            "SELECT 1 FROM wiki_source WHERE source_id = ?", (source_id,)
        ).fetchone():
            source_id = f"SRC-{digest[:8].upper()}-{_slug_project(project_id or namespace)}"
        suffix = Path(filename).suffix.lower()
        if data.startswith(b"%PDF"):
            ext = ".pdf"
        elif suffix in {".txt", ".md", ".markdown"}:
            ext = suffix
        else:
            ext = ".txt" if suffix == "" else suffix
        storage_key = blob_key(f"{source_id}{ext}", namespace, project_id)
        blob = put_blob(storage_key, data)

        markdown, page_map = extract_pdf(blob, filename)
        ingested_at = _now()
        self.conn.execute(
            """
            INSERT INTO wiki_source (
              source_id, filename, sha256, namespace, project_id, storage_uri,
              markdown_extract, page_map, ingested_at, ingested_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                filename,
                digest,
                namespace,
                project_id,
                storage_key,
                markdown,
                json.dumps(page_map),
                ingested_at,
                actor.actor,
            ),
        )

        drafts = self.sorter.sort(
            markdown,
            source_id=source_id,
            namespace=namespace,
            project_id=project_id,
            owner=actor.actor,
            now=ingested_at,
        )
        sort_backend = getattr(self.sorter, "last_backend", "heuristic")
        page_ids: list[str] = []
        for page in drafts:
            existing = self.conn.execute(
                "SELECT * FROM wiki_page WHERE page_id = ?", (page.page_id,)
            ).fetchone()
            if existing:
                old = row_to_dict(existing)
                merged = list(dict.fromkeys(old["source_ids"] + page.source_ids))
                same_scope = (old.get("namespace") == page.namespace) and (
                    (old.get("project_id") or None) == (page.project_id or None)
                )
                # Approved or cross-scope collisions: only attach the new source id.
                # Same-scope drafts must refresh title/body or uploads look stuck.
                if str(old.get("status") or "") == "approved" or not same_scope:
                    self.conn.execute(
                        "UPDATE wiki_page SET source_ids = ? WHERE page_id = ?",
                        (json.dumps(merged), page.page_id),
                    )
                    page_ids.append(page.page_id)
                    continue
                page.source_ids = merged
                page.status = "draft"
                page.namespace = old["namespace"]
                page.project_id = old.get("project_id")
                page_ids.append(
                    self._upsert_page(page, actor.actor, create_revision=True)
                )
                continue
            page_ids.append(self._upsert_page(page, actor.actor, create_revision=True))

        self.conn.commit()
        log_audit(
            self.root,
            operation="wiki.ingest_source",
            actor=actor,
            extra={
                "source_id": source_id,
                "proposed_page_ids": page_ids,
                "sort_backend": sort_backend,
            },
        )
        return {
            "source_id": source_id,
            "extract_status": "complete",
            "sort_status": "draft_pending_review",
            "sort_backend": sort_backend,
            "proposed_page_ids": page_ids,
        }

    def get_source(self, actor: Actor, source_id: str) -> WikiSource:
        require_tool(self.root, actor, "wiki.read_source")
        row = self.conn.execute(
            "SELECT * FROM wiki_source WHERE source_id = ?", (source_id,)
        ).fetchone()
        if not row:
            raise WikiError("COMMON_REFERENCE_NOT_FOUND", f"unknown source_id {source_id}", 404)
        src = WikiSource(**row_to_dict(row))
        require_project_scope(actor, namespace=src.namespace, project_id=src.project_id)
        if actor.actor_type == "agent" and src.namespace == "project":
            if actor.project_id != src.project_id:
                raise WikiError("COMMON_PERMISSION_DENIED", "agent cannot read another project", 403)
        log_audit(self.root, operation="wiki.read_source", actor=actor, extra={"source_id": source_id})
        return src

    def propose_page(self, actor: Actor, payload: ProposePageIn) -> WikiPage:
        require_tool(self.root, actor, "wiki.propose_page")
        require_project_scope(
            actor, namespace=payload.namespace, project_id=payload.project_id
        )
        now = _now()
        page_id = payload.page_id or f"PG-{_slug(payload.abbrev or payload.title or 'PAGE', 'NEW')}"
        existing = self.conn.execute(
            "SELECT * FROM wiki_page WHERE page_id = ?", (page_id,)
        ).fetchone()
        page = WikiPage(
            page_id=page_id,
            namespace=payload.namespace,
            project_id=payload.project_id,
            bucket_id=payload.bucket_id,
            title=payload.title or payload.abbrev or page_id,
            abbrev=payload.abbrev,
            expansion=payload.expansion,
            disambiguation=payload.disambiguation,
            status="draft" if existing is None else "proposed",
            version=payload.version,
            body=payload.body,
            source_ids=payload.source_ids,
            owner=payload.owner or actor.actor,
            updated_at=now,
        )
        if existing and dict(existing)["status"] == "approved":
            # new version, back to proposed — never overwrite approved in place without revision
            major, minor, patch = _parse_semver(dict(existing)["version"])
            page.version = f"{major}.{minor + 1}.0"
            page.status = "proposed"
        self._upsert_page(page, actor.actor, create_revision=True)
        self.conn.commit()
        log_audit(
            self.root,
            operation="wiki.propose_page",
            actor=actor,
            extra={"page_id": page.page_id, "status": page.status},
        )
        return self.fetch_page(actor, page.page_id, page.version, as_propose_followup=True)

    def search_pages(self, actor: Actor, q: SearchQuery) -> list[SearchHit]:
        require_tool(self.root, actor, "wiki.search_pages")
        require_project_scope(actor, namespace=q.namespace, project_id=q.project_id)
        status = q.status
        if actor.actor_type == "agent":
            status = "approved"
        if not q.namespace:
            raise WikiError("COMMON_SCHEMA_INVALID", "namespace is required")

        sql = [
            "SELECT page_id, title, body, version, bucket_id, status, namespace, project_id",
            "FROM wiki_page WHERE namespace = ?",
        ]
        args: list = [q.namespace]
        if q.project_id:
            sql.append("AND project_id = ?")
            args.append(q.project_id)
        elif actor.actor_type == "agent" and actor.project_id:
            sql.append("AND (project_id = ? OR namespace = 'company')")
            args.append(actor.project_id)
        if q.bucket_id:
            sql.append("AND bucket_id = ?")
            args.append(q.bucket_id)
        if status:
            sql.append("AND status = ?")
            args.append(status)
        if q.query:
            sql.append("AND (title LIKE ? OR body LIKE ? OR ifnull(abbrev,'') LIKE ? OR ifnull(expansion,'') LIKE ?)")
            like = f"%{q.query}%"
            args.extend([like, like, like, like])

        sql.append("LIMIT ?")
        args.append(max(1, min(q.limit, 50)))
        rows = self.conn.execute(" ".join(sql), args).fetchall()
        hits: list[SearchHit] = []
        needle = (q.query or "").lower()
        for row in rows:
            body = row["body"]
            snippet = body[:160] + ("..." if len(body) > 160 else "")
            score = 0.5
            if needle and needle in (row["title"] or "").lower():
                score = 0.91
            elif needle and needle in body.lower():
                score = 0.75
            hits.append(
                SearchHit(
                    page_id=row["page_id"],
                    title=row["title"],
                    snippet=snippet,
                    version=row["version"],
                    bucket_id=row["bucket_id"],
                    score=score,
                )
            )
        log_audit(
            self.root,
            operation="wiki.search_pages",
            actor=actor,
            extra={"namespace": q.namespace, "hits": len(hits)},
        )
        return hits

    def fetch_page(
        self,
        actor: Actor,
        page_id: str,
        version: str | None = None,
        *,
        as_propose_followup: bool = False,
    ) -> WikiPage:
        if not as_propose_followup:
            require_tool(self.root, actor, "wiki.fetch_page")
        row = self.conn.execute(
            "SELECT * FROM wiki_page WHERE page_id = ?", (page_id,)
        ).fetchone()
        if not row:
            raise WikiError("COMMON_REFERENCE_NOT_FOUND", f"unknown page_id {page_id}", 404)
        page = WikiPage(**row_to_dict(row))
        require_project_scope(actor, namespace=page.namespace, project_id=page.project_id)
        if actor.actor_type == "agent" and page.namespace == "project":
            if actor.project_id != page.project_id:
                raise WikiError(
                    "COMMON_PERMISSION_DENIED",
                    "agent cannot fetch another project_id",
                    403,
                )
            if not as_propose_followup and page.status != "approved":
                raise WikiError(
                    "COMMON_PRECONDITION_FAILED",
                    "agent may fetch only approved pages",
                    412,
                )
        if version and version != page.version:
            rev = self.conn.execute(
                "SELECT * FROM wiki_revision WHERE page_id = ? AND version = ? ORDER BY created_at DESC",
                (page_id, version),
            ).fetchone()
            if not rev:
                raise WikiError(
                    "COMMON_REFERENCE_NOT_FOUND",
                    f"unknown version {version} for {page_id}",
                    404,
                )
            page.body = rev["body_snapshot"]
            page.version = rev["version"]
            page.status = rev["status"]
        if not as_propose_followup:
            log_audit(
                self.root,
                operation="wiki.fetch_page",
                actor=actor,
                extra={"page_id": page_id, "version": page.version},
            )
        return page

    def approve_page(self, actor: Actor, page_id: str, version: str | None = None) -> WikiPage:
        require_tool(self.root, actor, "wiki.approve_page")
        row = self.conn.execute(
            "SELECT * FROM wiki_page WHERE page_id = ?", (page_id,)
        ).fetchone()
        if not row:
            raise WikiError("COMMON_REFERENCE_NOT_FOUND", f"unknown page_id {page_id}", 404)
        page = WikiPage(**row_to_dict(row))
        require_project_scope(actor, namespace=page.namespace, project_id=page.project_id)
        if version and version != page.version:
            raise WikiError(
                "COMMON_PRECONDITION_FAILED",
                f"version mismatch: current {page.version}",
                409,
            )
        now = _now()
        page.status = "approved"
        page.updated_at = now
        self._upsert_page(page, actor.actor, create_revision=True)
        self.conn.commit()
        log_audit(
            self.root,
            operation="wiki.approve_page",
            actor=actor,
            extra={"page_id": page_id, "version": page.version},
        )
        return page

    def demote_page(self, actor: Actor, page_id: str) -> WikiPage:
        """Human-only: approved → draft so VA no longer sees the page.

        Prefer this over hard delete when resolving V-WIKI conflicts — the
        body stays editable. Agents cannot call this tool.
        """
        require_tool(self.root, actor, "wiki.demote_page")
        row = self.conn.execute(
            "SELECT * FROM wiki_page WHERE page_id = ?", (page_id,)
        ).fetchone()
        if not row:
            raise WikiError("COMMON_REFERENCE_NOT_FOUND", f"unknown page_id {page_id}", 404)
        page = WikiPage(**row_to_dict(row))
        require_project_scope(actor, namespace=page.namespace, project_id=page.project_id)
        if page.status != "approved":
            raise WikiError(
                "COMMON_PRECONDITION_FAILED",
                f"only approved pages can be demoted (current={page.status})",
                409,
            )
        now = _now()
        page.status = "draft"
        page.updated_at = now
        self._upsert_page(page, actor.actor, create_revision=True)
        self.conn.commit()
        log_audit(
            self.root,
            operation="wiki.demote_page",
            actor=actor,
            extra={"page_id": page_id, "version": page.version, "status": "draft"},
        )
        return page

    def delete_page(self, actor: Actor, page_id: str) -> dict[str, Any]:
        """Human-only hard delete of one page (+ revisions). Agents denied."""
        require_tool(self.root, actor, "wiki.delete_page")
        row = self.conn.execute(
            "SELECT * FROM wiki_page WHERE page_id = ?", (page_id,)
        ).fetchone()
        if not row:
            raise WikiError("COMMON_REFERENCE_NOT_FOUND", f"unknown page_id {page_id}", 404)
        page = WikiPage(**row_to_dict(row))
        require_project_scope(actor, namespace=page.namespace, project_id=page.project_id)
        n = self.delete_pages([page_id])
        log_audit(
            self.root,
            operation="wiki.delete_page",
            actor=actor,
            extra={"page_id": page_id, "deleted": n},
        )
        return {"ok": True, "page_id": page_id, "deleted": n}

    def list_pages(self, *, status: str | None = None, project_id: str | None = None) -> list[WikiPage]:
        sql = "SELECT * FROM wiki_page WHERE 1=1"
        args: list = []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if project_id:
            sql += " AND project_id = ?"
            args.append(project_id)
        sql += " ORDER BY updated_at DESC"
        return [WikiPage(**row_to_dict(r)) for r in self.conn.execute(sql, args).fetchall()]

    def delete_pages(self, page_ids: list[str]) -> int:
        if not page_ids:
            return 0
        placeholders = ",".join("?" for _ in page_ids)
        self.conn.execute(
            f"DELETE FROM wiki_revision WHERE page_id IN ({placeholders})",
            page_ids,
        )
        cur = self.conn.execute(
            f"DELETE FROM wiki_page WHERE page_id IN ({placeholders})",
            page_ids,
        )
        self.conn.commit()
        return int(cur.rowcount or 0)

    def _upsert_page(self, page: WikiPage, actor_name: str, *, create_revision: bool) -> str:
        self.conn.execute(
            """
            INSERT INTO wiki_page (
              page_id, namespace, project_id, bucket_id, title, abbrev, expansion,
              disambiguation, status, version, body, source_ids, owner, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_id) DO UPDATE SET
              namespace=excluded.namespace,
              project_id=excluded.project_id,
              bucket_id=excluded.bucket_id,
              title=excluded.title,
              abbrev=excluded.abbrev,
              expansion=excluded.expansion,
              disambiguation=excluded.disambiguation,
              status=excluded.status,
              version=excluded.version,
              body=excluded.body,
              source_ids=excluded.source_ids,
              owner=excluded.owner,
              updated_at=excluded.updated_at
            """,
            (
                page.page_id,
                page.namespace,
                page.project_id,
                page.bucket_id,
                page.title,
                page.abbrev,
                page.expansion,
                page.disambiguation,
                page.status,
                page.version,
                page.body,
                json.dumps(page.source_ids),
                page.owner,
                page.updated_at,
            ),
        )
        if create_revision:
            # Use MAX, not COUNT — deletions leave gaps; COUNT+1 collides with existing REV-*.
            # Platform: serialize id allocation across connections until commit.
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtext('wiki-revision-id'))")
            row = self.conn.execute(
                """
                SELECT MAX(CAST(SUBSTR(revision_id, 5) AS INTEGER)) AS m
                FROM wiki_revision
                WHERE revision_id LIKE 'REV-%'
                """
            ).fetchone()
            n = int(row["m"] or 0) if row is not None else 0
            revision_id = f"REV-{n + 1:04d}"
            self.conn.execute(
                """
                INSERT INTO wiki_revision (
                  revision_id, page_id, version, status, body_snapshot, diff_ref, actor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    page.page_id,
                    page.version,
                    page.status,
                    page.body,
                    None,
                    actor_name,
                    page.updated_at,
                ),
            )
        return page.page_id


def _slug_project(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", str(raw or "")).upper()
    return (cleaned[-8:] or "SCOPE")


def _parse_semver(version: str) -> tuple[int, int, int]:
    parts = (version or "1.0.0").split(".")
    nums = [(int(p) if p.isdigit() else 0) for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]
