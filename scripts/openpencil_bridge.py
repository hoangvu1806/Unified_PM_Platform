"""Keep an OpenPencil editor tab open (headless) so MCP write automation works.

OpenPencil writes to the canvas through a browser bridge: the editor page must
be open. Run this inside the OpenPencil container's network namespace so the
page and its bridge (ws://localhost:7600) resolve exactly as in a local browser:

    docker run --rm --network container:open-pencil-openpencil-1 \
        -v "$PWD/scripts:/s" mcr.microsoft.com/playwright/python:v1.48.0-jammy \
        sh -c "pip install -q playwright==1.48.0 && python /s/openpencil_bridge.py 3600"
"""

import sys
import time

from playwright.sync_api import sync_playwright

SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3600
URL = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:1420"

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.on("console", lambda m: print(f"[editor:{m.type}] {m.text}", flush=True) if m.type in {"error", "warning"} or "utomation" in m.text else None)
    page.goto(URL, wait_until="networkidle", timeout=120_000)
    print(f"editor open at {URL}; keeping the bridge alive for {SECONDS}s", flush=True)
    deadline = time.time() + SECONDS
    while time.time() < deadline:
        page.wait_for_timeout(15_000)
        if page.is_closed():
            break
    browser.close()
