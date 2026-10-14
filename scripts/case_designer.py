"""Real Designer case: BA handoff -> chat -> spec review -> build -> final review.

Run on the platform network (needs the OpenPencil bridge open, see openpencil_bridge.py):

    docker run --rm --network platform_default -v "$PWD/scripts:/s:ro" python:3.12-slim \
        python /s/case_designer.py http://gateway PRJ-DEMO <ba_feature_id>

Acts like a person in the Designer UI: answers the agent, approves the
specification and the final design. Prints the conversation as it goes.
"""

from __future__ import annotations

import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request

BASE, PROJECT, FEATURE = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
USER = sys.argv[4] if len(sys.argv) > 4 else "lead.dung"
API = f"{BASE}/designer/api/v1"
PROFILE = {
    "endpoint": "http://127.0.0.1:7600/mcp",  # mapped to the user's / default instance server-side
    "source_file": "shadcn-ui",  # matched by name in DESIGN_DATA_DIR/design-systems
    "knowledge_id": "shadcn-ui",
}
DEADLINE = time.time() + 60 * 60

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(method: str, url: str, body: dict | None = None, timeout: int = 120):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=timeout) as res:
            raw = res.read()
            return res.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(errors="replace")[:800]


def say(who: str, text: str) -> None:
    print(f"\n[{who}] {text.strip()[:1500]}", flush=True)


def wait_run(run_id: str) -> dict:
    last = None
    while time.time() < DEADLINE:
        _, run = call("GET", f"{API}/runs/{run_id}")
        state = (run.get("stage"), run.get("status"))
        if state != last:
            print(f"  run {run_id[:8]} stage={state[0]} status={state[1]}", flush=True)
            last = state
        if run.get("status") in {"waiting_review", "completed", "failed", "blocked", "cancelled"}:
            return run
        time.sleep(8)
    raise SystemExit("timeout waiting for the run")


status, _ = call("POST", f"{BASE}/api/core/auth/login", {"username": USER, "password": "demo123"})
assert status == 200, f"login failed: {status}"
print(f"logged in as {USER}")

if len(sys.argv) > 6:  # resume: ... USER SESSION RUN
    session, run_id = sys.argv[5], sys.argv[6]
    print(f"resume designer session {session} run {run_id}")
else:
    status, handoff = call("POST", f"{BASE}/ba/api/features/{FEATURE}/designer-handoff", {}, timeout=300)
    assert status == 200, f"handoff failed: {status} {handoff}"
    session, run_id = handoff["designer_session_id"], handoff["designer_run_id"]
    print(f"handoff -> designer session {session} ({handoff['designer_url']})")

answers = [
    "Đồng ý thiết kế. Phạm vi: 1 màn hình desktop 'Tạo yêu cầu vật tư' cho nhân viên kho "
    "(form chọn vật tư, số lượng, kho xuất, lý do; danh sách dòng yêu cầu; nút Gửi phê duyệt). "
    "File đầu ra: warehouse-request.fig. Dùng thư viện shadcn-ui. Xác nhận phạm vi, bắt đầu thiết kế.",
    "Xác nhận phạm vi như trên, chỉ 1 màn hình desktop. Bắt đầu thiết kế ngay.",
    "Đúng rồi, tiếp tục thiết kế.",
]
turn = 0
while time.time() < DEADLINE:
    run = wait_run(run_id)
    if run.get("assistant_message"):
        say("Designer agent", run["assistant_message"])
    stage, state = run.get("stage"), run.get("status")
    if state == "waiting_review":
        checkpoint = "specification" if stage == "review_spec" else "final"
        say(USER, f"Duyệt ({checkpoint}): approved")
        status, body = call("POST", f"{API}/runs/{run_id}/reviews", {
            "checkpoint": checkpoint, "decision": "approved", "revision": run["revision"],
            "feedback": "", "mcp_profile": PROFILE,
        })
        fixes = globals().setdefault("_layout_fixes", 0)
        if status == 409 and "LAYOUT_NOT_VALID" in str(body) and fixes < 3:
            # Like a reviewer: ask the agent to fix the blocking layout findings, then approve again.
            globals()["_layout_fixes"] = fixes + 1
            feedback = "Sửa các lỗi layout đang chặn duyệt (chồng lấn, tràn khung, căn lề), giữ nguyên nội dung màn hình."
            say(USER, f"Yêu cầu sửa layout ({fixes + 1}/3): {feedback}")
            status, body = call("POST", f"{API}/runs/{run_id}/reviews", {
                "checkpoint": checkpoint, "decision": "changes_requested", "revision": run["revision"],
                "feedback": feedback, "mcp_profile": PROFILE,
            })
        assert status == 202, f"review failed: {status} {body}"
        time.sleep(3)
        continue
    if state == "completed" and stage == "finished" and run.get("mcp_profile") and run.get("specification"):
        print("\nDESIGN FINISHED", json.dumps({"session": session, "run": run_id}), flush=True)
        break
    if state in {"failed", "blocked"}:
        error = run.get("error") or {}
        say("error", json.dumps(error, ensure_ascii=False))
        retries = globals().setdefault("_retries", {})
        if error.get("retryable") and retries.get(run_id, 0) < 2:
            retries[run_id] = retries.get(run_id, 0) + 1
            say(USER, f"Retry ({retries[run_id]}/2)")
            status, body = call("POST", f"{API}/runs/{run_id}/retry", {"mcp_profile": PROFILE})
            assert status == 202, f"retry failed: {status} {body}"
            time.sleep(3)
            continue
        if turn >= len(answers):
            raise SystemExit(1)
    if turn >= len(answers):
        raise SystemExit("agent still has not started the design after all scripted answers")
    say(USER, answers[turn])
    status, run = call("POST", f"{API}/sessions/{session}/messages", {
        "content": answers[turn], "screen_name_hint": "Tạo yêu cầu vật tư",
        "platform_hint": "desktop", "mcp_profile": PROFILE,
    })
    assert status == 202, f"message failed: {status} {run}"
    run_id = run["id"]
    turn += 1

time.sleep(5)
_, files = call("GET", f"{BASE}/api/core/projects/{PROJECT}/files")
print("\nproject files:", json.dumps([{k: f[k] for k in ("kind", "title", "version", "created_by")} for f in files], ensure_ascii=False))
