"""Headless UI walk-through: login -> projects -> project (both agents) -> journey -> Designer.

    docker run --rm --network platform_default -v "$PWD/scripts:/s" mcr.microsoft.com/playwright/python:v1.48.0-jammy \
        sh -c "pip install -q playwright==1.48.0 && python /s/e2e_ui.py http://gateway"

Screenshots go to scripts/screens/ (git-ignored).
"""

import os
import sys

from playwright.sync_api import expect, sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://gateway").rstrip("/")
OUT = "/s/screens"
os.makedirs(OUT, exist_ok=True)


def login(page, username):
    page.goto(f"{BASE}/login")
    page.get_by_role("button", name=username).click()
    expect(page.get_by_role("heading", name="Chào", exact=False)).to_be_visible()


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 860})

    page.goto(f"{BASE}/")
    expect(page.get_by_text("Đăng nhập nhanh", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Đăng nhập với Keycloak")).to_be_visible()
    page.screenshot(path=f"{OUT}/1-login.png")

    # PM: projects in the rail and as cards.
    login(page, "pm.hoa")
    expect(page.locator(".rail-row", has_text="Aurora")).to_be_visible()
    page.screenshot(path=f"{OUT}/2-projects.png")

    # Project page: both agents are always shown with their state.
    page.locator(".card.project", has_text="Aurora").click()
    page.wait_for_url("**/projects/PRJ-AURORA")
    expect(page.locator(".agent-card", has_text="BA agent")).to_be_visible()
    expect(page.locator(".agent-card", has_text="Designer agent")).to_be_visible()
    page.screenshot(path=f"{OUT}/3-project.png")
    print("project page: BA + Designer cards ok")

    # Journey of the first feature, if the project has one.
    rows = page.locator(".row-button")
    if rows.count():
        rows.first.click()
        page.wait_for_url("**/f/**")
        expect(page.locator(".journey-strip .jstep")).to_have_count(9)
        page.wait_for_timeout(4000)
        page.screenshot(path=f"{OUT}/4-journey.png")
        print("journey: 9 steps ok")
        page.goto(f"{BASE}/projects/PRJ-AURORA")

    # Designer inside the portal, also before any BA handoff.
    page.locator(".agent-card", has_text="Designer agent").get_by_role("button").click()
    page.wait_for_url("**/projects/PRJ-AURORA/designer")
    expect(page.locator("iframe[title='Designer agent']")).to_be_visible()
    page.wait_for_timeout(4000)
    page.screenshot(path=f"{OUT}/5-designer.png")
    print("designer in portal ok")

    # Quick sign-in lists PM accounts only.
    page = browser.new_page(viewport={"width": 1440, "height": 860})
    login(page, "lead.dung")
    page.screenshot(path=f"{OUT}/6-second-pm.png")
    print("lead.dung login ok")

    browser.close()
print("UI walk-through PASS")
