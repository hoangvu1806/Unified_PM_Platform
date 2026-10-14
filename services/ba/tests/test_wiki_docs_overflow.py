"""Opt-in Playwright check: 27 approved wiki pages must not bury chat or composer.

Run: BA_E2E=1 .venv/bin/pytest tests/test_wiki_docs_overflow.py -v
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("BA_E2E") != "1",
    reason="opt-in Playwright UI (BA_E2E=1)",
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SESSION = "e6e2f023-overflow-wiki-list"
DOC_COUNT = 27


def _resolve_node() -> str | None:
    env = os.environ.get("BA_NODE")
    if env and Path(env).exists():
        return env
    which = shutil.which("node")
    if which:
        return which
    for candidate in (
        "/Applications/Cursor.app/Contents/Resources/app/resources/helpers/node",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def wiki_documents() -> list[dict]:
    return [
        {
            "page_id": f"L-PG-OVERFLOW-{i:02d}",
            "title": f"[llm] Wiki page {i}",
            "snippet": (
                f"Approved live snippet {i}. Keep this catalog from stretching the chat column."
            ),
        }
        for i in range(1, DOC_COUNT + 1)
    ]


def feature_payload(*, can_proceed: bool = True) -> dict:
    return {
        "session_id": SESSION,
        "title": "Overflow wiki list",
        "description": "",
        "feature_status": "PENDING_VALIDATION" if can_proceed else "DRAFT",
        "can_proceed_to_validation": can_proceed,
        "sections": {
            "feature_definition": {
                "flags": {
                    "FD-F1": "PASS",
                    "FD-F2": "PASS",
                    "FD-F3": "PASS",
                    "FD-F5": "PASS",
                    "FD-F4": "PASS",
                },
                "data": {},
                "is_completable": True,
            }
        },
    }


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="module")
def base_url():
    port = int(os.environ.get("BA_E2E_PORT", "5174"))
    node = _resolve_node()
    vite = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
    if not node:
        pytest.skip("Node binary not found (set BA_NODE)")
    if not vite.exists():
        pytest.skip(f"Vite not installed at {vite}")
    if _port_open(port):
        yield f"http://127.0.0.1:{port}"
        return
    proc = subprocess.Popen(
        [node, str(vite), "--host", "127.0.0.1", "--port", str(port)],
        cwd=FRONTEND,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 40
        while time.time() < deadline:
            if _port_open(port):
                yield f"http://127.0.0.1:{port}"
                return
            if proc.poll() is not None:
                out = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""
                pytest.fail(f"Vite exited {proc.returncode}: {out[-2000:]}")
            time.sleep(0.2)
        pytest.fail("Vite did not start on port %s" % port)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def browser():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        launched = p.chromium.launch(headless=True)
        yield launched
        launched.close()


@pytest.fixture
def browser_page(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    page = context.new_page()
    yield page
    context.close()


def mock_apis(page, *, can_proceed: bool = True) -> None:
    def handle(route):
        url = route.request.url
        if "/documents" in url:
            route.fulfill(json={"documents": wiki_documents()})
            return
        if "/history" in url:
            route.fulfill(
                json={
                    "session_id": SESSION,
                    "messages": [
                        {"sender": "user", "text": "User message that must stay visible."},
                        {
                            "sender": "agent",
                            "text": "Agent reply that must stay reachable above the composer.",
                        },
                    ],
                }
            )
            return
        route.fulfill(json=feature_payload(can_proceed=can_proceed))

    page.route("**/api/features/**", handle)


def assert_wiki_catalog_capped(page) -> None:
    page.locator("#wikiDocsCount").wait_for()
    assert page.locator("#wikiDocsCount").inner_text().strip() == str(DOC_COUNT)

    items = page.locator("#wikiDocsList .wiki-docs-item")
    assert items.count() == 3
    assert "Wiki page 1" in page.locator("#wikiDocsList").inner_text()
    assert "Wiki page 27" not in page.locator("#wikiDocsList").inner_text()

    metrics = page.evaluate(
        """() => {
          const listEl = document.getElementById('wikiDocsList');
          const stream = document.getElementById('chatStream');
          const panel = document.querySelector('main.chat-panel');
          const composer = document.querySelector('.input-dock');
          const workspace = document.querySelector('.workspace-body');
          const listStyle = getComputedStyle(listEl);
          const streamStyle = getComputedStyle(stream);
          const panelStyle = getComputedStyle(panel);
          const composerBox = composer.getBoundingClientRect();
          return {
            listMaxHeight: listStyle.maxHeight,
            listOverflowY: listStyle.overflowY,
            streamOverflowY: streamStyle.overflowY,
            streamMinHeight: streamStyle.minHeight,
            panelOverflowY: panelStyle.overflowY,
            panelMinHeight: panelStyle.minHeight,
            composerTop: composerBox.top,
            composerBottom: composerBox.bottom,
            viewHeight: window.innerHeight,
            workspaceOverflowY: workspace ? getComputedStyle(workspace).overflowY : null,
            workspaceMinHeight: workspace ? getComputedStyle(workspace).minHeight : null,
          };
        }"""
    )

    max_height_px = float(str(metrics["listMaxHeight"]).replace("px", ""))
    assert 12 * 16 - 1 <= max_height_px <= 16 * 16 + 1
    assert metrics["listOverflowY"] in ("auto", "scroll")
    assert metrics["streamOverflowY"] in ("auto", "scroll")
    assert metrics["panelOverflowY"] in ("auto", "scroll")
    assert metrics["streamMinHeight"] == "0px"
    assert metrics["panelMinHeight"] == "0px"
    assert metrics["composerTop"] > 0
    assert metrics["composerBottom"] <= metrics["viewHeight"] + 1
    assert metrics["workspaceOverflowY"] in ("auto", "scroll")
    assert metrics["workspaceMinHeight"] == "0px"

    assert page.get_by_text("User message that must stay visible.").is_visible()
    assert page.get_by_text("Agent reply that must stay reachable above the composer.").is_visible()
    assert page.locator("#chatInput").is_visible()
    assert page.locator(".composer-send").is_visible()

    page.get_by_role("button", name=f"Show all ({DOC_COUNT})").click()
    assert items.count() == DOC_COUNT
    assert "Wiki page 27" in page.locator("#wikiDocsList").inner_text()

    scrollable = page.locator("#wikiDocsList").evaluate(
        """el => ({
          scrollHeight: el.scrollHeight,
          clientHeight: el.clientHeight,
          overflowY: getComputedStyle(el).overflowY,
        })"""
    )
    assert scrollable["scrollHeight"] > scrollable["clientHeight"]
    assert scrollable["overflowY"] in ("auto", "scroll")

    page.locator("#wikiDocsList").evaluate("el => { el.scrollTop = el.scrollHeight; }")
    scrolled = page.locator("#wikiDocsList").evaluate("el => el.scrollTop")
    assert scrolled > 0

    assert page.get_by_text("User message that must stay visible.").is_visible()
    box = page.locator("#chatInput").bounding_box()
    assert box is not None
    assert box["y"] + box["height"] <= 720 + 1
    send = page.locator(".composer-send").bounding_box()
    assert send is not None
    assert send["y"] >= 0


def test_chat_column_stays_usable_with_27_wiki_pages(browser_page, base_url):
    page = browser_page
    mock_apis(page, can_proceed=True)
    page.goto(f"{base_url}/chat.html?session={SESSION}&title=Overflow%20wiki%20list")
    assert_wiki_catalog_capped(page)


def test_chat_hides_wiki_docs_before_validate_unlocked(browser_page, base_url):
    """Approved wiki catalog must stay hidden in BA chat until Validate unlocks."""
    page = browser_page
    docs_hits = {"n": 0}

    def track(route):
        url = route.request.url
        if "/documents" in url:
            docs_hits["n"] += 1
            route.fulfill(json={"documents": wiki_documents()})
            return
        if "/history" in url:
            route.fulfill(json={"session_id": SESSION, "messages": []})
            return
        route.fulfill(json=feature_payload(can_proceed=False))

    page.route("**/api/features/**", track)
    page.goto(f"{base_url}/chat.html?session={SESSION}&title=Drafting%20feature")
    page.locator("#checklistGrid").wait_for()
    card = page.locator("#wikiDocsCard")
    assert card.count() == 1
    assert card.is_hidden()
    assert docs_hits["n"] == 0


def test_va_column_stays_usable_with_27_wiki_pages(browser_page, base_url):
    page = browser_page
    mock_apis(page)
    page.goto(f"{base_url}/va.html?session={SESSION}&title=Overflow%20wiki%20list")
    assert_wiki_catalog_capped(page)
