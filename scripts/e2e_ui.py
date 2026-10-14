"""Headless UI walk-through (Sprint 3): login -> portal -> module UI by role.

    docker run --rm --network platform_default -v "$PWD/scripts:/s" \
        mcr.microsoft.com/playwright/python:v1.48.0-jammy python /s/e2e_ui.py http://gateway
"""

import sys

from playwright.sync_api import expect, sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://gateway").rstrip("/")
OUT = "/s/screens"


def login(page, username):
    page.goto(f"{BASE}/login")
    page.get_by_role("button", name=username).click()
    expect(page.get_by_role("heading", name="Dự án của tôi")).to_be_visible()


with sync_playwright() as p:
    browser = p.chromium.launch()

    # BA user: card click opens the BA UI for that project.
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.goto(f"{BASE}/")
    expect(page.get_by_text("Đăng nhập nhanh")).to_be_visible()
    page.screenshot(path=f"{OUT}/1-login.png")
    login(page, "ba.an")
    page.screenshot(path=f"{OUT}/2-portal-ba.png")
    page.get_by_role("heading", name="Aurora").click()
    page.wait_for_url("**/ba/**")
    expect(page.locator("#platformBar")).to_contain_text("Aurora")
    expect(page.locator("#btnCreateFeature")).to_be_visible()
    page.screenshot(path=f"{OUT}/3-ba-aurora.png")
    print("ba.an -> BA UI ok:", page.url)

    # Designer user: card click opens the Designer UI.
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    login(page, "designer.binh")
    page.get_by_role("heading", name="Aurora").click()
    page.wait_for_url("**/designer/**")
    expect(page.locator("#platformBar")).to_contain_text("Aurora")
    page.screenshot(path=f"{OUT}/4-designer-aurora.png")
    print("designer.binh -> Designer UI ok:", page.url)

    # Designer opening BA of the same project: read-only.
    page.goto(f"{BASE}/ba/?project=PRJ-AURORA")
    expect(page.locator("#platformBar")).to_contain_text("CHỈ ĐỌC")
    expect(page.locator("#btnCreateFeature")).to_be_hidden()
    page.screenshot(path=f"{OUT}/5-ba-readonly.png")
    print("designer.binh -> BA read-only ok")

    # Lead with both roles: card opens the project page with both modules.
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    login(page, "lead.dung")
    page.get_by_role("heading", name="Aurora").click()
    expect(page.get_by_role("link", name="BA")).to_be_visible()
    page.screenshot(path=f"{OUT}/6-project-lead.png")
    print("lead.dung -> project page ok")
    expect(page.get_by_role("button", name="Assets")).to_be_visible()
    page.get_by_role("button", name="Data workspace").click()
    expect(page.get_by_role("heading", name="BA sessions")).to_be_visible()
    expect(page.get_by_role("heading", name="Designer sessions")).to_be_visible()
    page.screenshot(path=f"{OUT}/7-project-workspace.png")
    print("lead.dung -> Assets / Data workspace tabs ok")

    # Not a member: BA URL of Aurora bounces back to the portal.
    page = browser.new_page()
    login(page, "ba.chi")
    page.goto(f"{BASE}/ba/?project=PRJ-AURORA")
    page.wait_for_url(f"{BASE}/")
    print("ba.chi -> Aurora redirected to portal ok")

    # Logged out: module URL goes to login with next=.
    page = browser.new_page()
    page.goto(f"{BASE}/designer/?project=PRJ-AURORA")
    page.wait_for_url("**/login?next=**")
    print("anonymous -> login ok")
    browser.close()
print("UI walk-through passed")
