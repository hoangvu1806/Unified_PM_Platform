"""End-to-end access checks through the gateway (Sprint 3, S3-11).

    docker run --rm --network platform_default -v "$PWD/scripts:/s:ro" \
        python:3.12-slim python /s/e2e_access.py http://gateway

Uses the seeded mock accounts (password demo123). Creates one BA feature and
one Designer session in PRJ-AURORA; does not call any LLM.
"""

from __future__ import annotations

import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://gateway").rstrip("/")
AURORA, DEMO, LEGACY = "PRJ-AURORA", "PRJ-DEMO", "PRJ-LEGACY"
results: list[tuple[bool, str]] = []


class Client:
    def __init__(self, username: str | None = None) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.name = username or "anonymous"
        if username:
            status, _ = self.call("POST", "/api/core/auth/login", {"username": username, "password": "demo123"})
            assert status == 200, f"login {username}: {status}"

    def call(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with self.opener.open(req, timeout=60) as res:
                raw = res.read()
                return res.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                return err.code, json.loads(raw)
            except ValueError:
                return err.code, raw


def check(label: str, got: int, want: int) -> None:
    ok = got == want
    results.append((ok, f"{'PASS' if ok else 'FAIL'}  {label}: {got} (want {want})"))


anon = Client()
an, chi, binh, dung = Client("ba.an"), Client("ba.chi"), Client("designer.binh"), Client("lead.dung")

# ── Login & portal ───────────────────────────────────────────────
check("anonymous /api/core/me", anon.call("GET", "/api/core/me")[0], 401)
_, projects = an.call("GET", "/api/core/projects")
check("ba.an sees Aurora", int(AURORA in {p["id"] for p in projects}) * 200, 200)
_, projects = chi.call("GET", "/api/core/projects")
check("ba.chi does not see Aurora", int(AURORA not in {p["id"] for p in projects}) * 200, 200)
_, projects = dung.call("GET", "/api/core/projects")
check("lead.dung sees Legacy", int(LEGACY in {p["id"] for p in projects}) * 200, 200)
for path in ("/", "/login", f"/ba/?project={AURORA}", f"/designer/?project={AURORA}"):
    check(f"page {path}", anon.call("GET", path)[0], 200)

# ── BA ───────────────────────────────────────────────────────────
check("anonymous BA features", anon.call("GET", f"/ba/api/features?project_id={AURORA}")[0], 401)
status, feature = an.call("POST", "/ba/api/features", {"title": "E2E access feature", "project_id": AURORA})
check("ba.an creates feature in Aurora", status, 201)
sid = feature["session_id"]
_, listed = an.call("GET", f"/ba/api/features?project_id={AURORA}")
check("feature listed in Aurora", int(any(f["session_id"] == sid for f in listed)) * 200, 200)
_, listed = an.call("GET", f"/ba/api/features?project_id={DEMO}")
check("feature not listed in Demo", int(all(f["session_id"] != sid for f in listed)) * 200, 200)
check("designer.binh reads BA feature (member)", binh.call("GET", f"/ba/api/features/{sid}")[0], 200)
check("designer.binh reads BA chat history", binh.call("GET", f"/ba/api/features/{sid}/history")[0], 200)
check(
    "designer.binh cannot send BA chat",
    binh.call("POST", f"/ba/api/v1/chat/{sid}/message", {"user_id": "x", "user_message": "hi"})[0],
    403,
)
check("designer.binh cannot create BA feature", binh.call("POST", "/ba/api/features", {"title": "x", "project_id": AURORA})[0], 403)
check("ba.chi cannot list Aurora features", chi.call("GET", f"/ba/api/features?project_id={AURORA}")[0], 403)
check("ba.chi cannot read Aurora feature", chi.call("GET", f"/ba/api/features/{sid}")[0], 403)
check("ba.chi cannot read Aurora chat", chi.call("GET", f"/ba/api/features/{sid}/history")[0], 403)
check("ba.chi cannot list Aurora wiki", chi.call("GET", f"/ba/api/wiki/pages?project_id={AURORA}")[0], 403)
check("ba.an lists Aurora wiki", an.call("GET", f"/ba/api/wiki/pages?project_id={AURORA}")[0], 200)
check("create feature without project", an.call("POST", "/ba/api/features", {"title": "x"})[0], 400)

# ── Designer ─────────────────────────────────────────────────────
check("anonymous Designer sessions", anon.call("GET", f"/designer/api/v1/sessions?project_id={AURORA}")[0], 401)
check("Designer health stays public", anon.call("GET", "/designer/api/v1/health")[0], 200)
status, session = binh.call("POST", "/designer/api/v1/sessions", {"title": "E2E access", "project_id": AURORA})
check("designer.binh creates session in Aurora", status, 201)
dsid = session["id"]
_, sessions = binh.call("GET", f"/designer/api/v1/sessions?project_id={AURORA}")
check("session listed in Aurora", int(any(s["id"] == dsid for s in sessions)) * 200, 200)
check("ba.an reads Designer runs (member)", an.call("GET", f"/designer/api/v1/sessions/{dsid}/runs")[0], 200)
check(
    "ba.an cannot message Designer",
    an.call("POST", f"/designer/api/v1/sessions/{dsid}/messages", {"content": "hi"})[0],
    403,
)
check("ba.an cannot create Designer session", an.call("POST", "/designer/api/v1/sessions", {"title": "x", "project_id": AURORA})[0], 403)
check("ba.chi cannot read Aurora Designer runs", chi.call("GET", f"/designer/api/v1/sessions/{dsid}/runs")[0], 403)
check("ba.chi cannot list Aurora Designer sessions", chi.call("GET", f"/designer/api/v1/sessions?project_id={AURORA}")[0], 403)
check("handoff without agent secret", anon.call("POST", "/designer/api/v1/handoffs", {"correlation_id": "c", "feature_id": "f", "prompt": "abc"})[0], 401)

# ── Legacy data ──────────────────────────────────────────────────
_, legacy = dung.call("GET", f"/ba/api/features?project_id={LEGACY}")
check("legacy BA feature visible in Legacy", int(len(legacy) >= 1) * 200, 200)

# Cleanup the records this script created.
an.call("DELETE", f"/ba/api/features/{sid}")
binh.call("DELETE", f"/designer/api/v1/sessions/{dsid}")

for _, line in results:
    print(line)
failed = sum(1 for ok, _ in results if not ok)
print(f"\n{len(results) - failed} passed, {failed} failed")
sys.exit(1 if failed else 0)
