"""Thin HTTP client for BA demo closed-cycle runs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


class DemoClientError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class DemoClient:
    def __init__(self, base_url: str, *, timeout_s: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        # Platform: the login cookie (platform_token) is reused for every call.
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def login(self, core_url: str, username: str, password: str) -> dict[str, Any]:
        """Log in through core-api; the cookie is then sent to the BA API."""
        req = Request(
            f"{core_url.rstrip('/')}/api/core/auth/login",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=30) as res:
                return json.loads(res.read().decode())
        except HTTPError as exc:
            raise DemoClientError(f"login {username} -> HTTP {exc.code}", status=exc.code) from exc

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        url = self._url(path)
        if query:
            url = f"{url}?{urlencode(query)}"
        headers: dict[str, str] = {}
        data: bytes | None = None
        if files is not None:
            boundary = f"----baDemo{int(time.time() * 1000)}"
            parts: list[bytes] = []
            for key, value in (form or {}).items():
                parts.append(
                    (
                        f"--{boundary}\r\n"
                        f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                        f"{value}\r\n"
                    ).encode()
                )
            for key, (filename, content, content_type) in files.items():
                parts.append(
                    (
                        f"--{boundary}\r\n"
                        f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                        f"Content-Type: {content_type}\r\n\r\n"
                    ).encode()
                    + content
                    + b"\r\n"
                )
            parts.append(f"--{boundary}--\r\n".encode())
            data = b"".join(parts)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif form is not None:
            data = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"

        req = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with self._opener.open(req, timeout=self.timeout_s) as res:
                raw = res.read()
                if not raw:
                    return None
                ctype = res.headers.get("Content-Type", "")
                if "application/json" in ctype or raw[:1] in (b"{", b"["):
                    return json.loads(raw.decode())
                return raw
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise DemoClientError(
                f"{method} {path} -> HTTP {exc.code}: {body[:500]}",
                status=exc.code,
                body=body,
            ) from exc
        except URLError as exc:
            raise DemoClientError(f"{method} {path} failed: {exc}") from exc

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/api/health")

    def create_feature(self, title: str, description: str = "", project_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"title": title, "description": description}
        if project_id:
            body["project_id"] = project_id
        return self.request("POST", "/api/features/", json_body=body)

    def get_feature(self, session_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/features/{session_id}")

    def chat(
        self,
        session_id: str,
        message: str,
        *,
        active_section: str,
        # Must match CONTROL_USER_ID / UI (`ba-user`) or chat.html history stays empty.
        user_id: str = "ba-user",
        action: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user_id": user_id,
            "ticket_type": "NEW_FEATURE",
            "user_message": message,
            "active_section": active_section,
        }
        if action:
            body["action"] = action
        return self.request("POST", f"/api/v1/chat/{session_id}/message", json_body=body)

    def upload_wiki(
        self,
        path: Path,
        *,
        namespace: str,
        project_id: str,
        actor: str = "ba.lead",
        sort_mode: str = "heuristic",
    ) -> dict[str, Any]:
        data = path.read_bytes()
        form = {
            "namespace": namespace,
            # Platform: always send the acting project (company uploads need ADMIN there).
            "project_id": project_id,
            "actor": actor,
            "sort_mode": sort_mode,
        }
        return self.request(
            "POST",
            "/api/wiki/sources",
            form=form,
            files={"file": (path.name, data, "application/pdf")},
        )

    def approve_wiki(self, page_id: str, *, project_id: str, actor: str = "ba.lead") -> dict[str, Any]:
        return self.request(
            "POST",
            f"/api/wiki/pages/{page_id}/approve",
            form={"actor": actor, "project_id": project_id},
        )

    def demote_wiki(self, page_id: str, *, project_id: str, actor: str = "ba.lead") -> dict[str, Any]:
        return self.request(
            "POST",
            f"/api/wiki/pages/{page_id}/demote",
            form={"actor": actor, "project_id": project_id},
        )

    def delete_wiki(self, page_id: str, *, project_id: str, actor: str = "ba.lead") -> dict[str, Any]:
        return self.request(
            "POST",
            f"/api/wiki/pages/{page_id}/delete",
            form={"actor": actor, "project_id": project_id},
        )

    def clear_wiki(self, *, actor: str = "ba.lead") -> dict[str, Any]:
        return self.request(
            "POST",
            "/api/wiki/clear",
            form={"confirm": "CLEAR", "actor": actor},
        )

    def list_wiki(self, project_id: str) -> dict[str, Any]:
        return self.request("GET", "/api/wiki/pages", query={"project_id": project_id})

    def validate(self, session_id: str) -> dict[str, Any]:
        return self.request("POST", f"/api/va/{session_id}/validate")

    def export(self, session_id: str) -> dict[str, Any]:
        return self.request("POST", f"/api/features/{session_id}/export")

    def documents(self, session_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/features/{session_id}/documents")

    def regenerate_bpmn(self, session_id: str) -> bytes:
        raw = self.request(
            "GET",
            f"/api/features/{session_id}/bpmn",
            query={"regenerate": "true"},
        )
        if isinstance(raw, bytes):
            return raw
        raise DemoClientError("BPMN regenerate did not return bytes")
