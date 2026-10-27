import asyncio

import pytest

from app.render import Renderer, build_document, fragment_of

pytest.importorskip("playwright")

SCREEN = """
<div x-data="{open: false}" class="min-h-screen bg-background p-8">
  <h1 class="text-2xl font-semibold text-foreground">Yêu cầu vật tư</h1>
  <button @click="open = true" class="mt-4 rounded-lg bg-primary px-4 py-2 text-primary-foreground">Mở</button>
  <p x-show="open" class="mt-2">Đã mở</p>
  <div data-state="error" class="mt-4 rounded border border-destructive p-3">Không tải được dữ liệu</div>
  <div data-state-hide="error" class="mt-4">Danh sách</div>
</div>
"""
DEFECTS = """
<div class="p-4">
  <div class="w-32 overflow-hidden whitespace-nowrap border p-1">Kho trung tâm Hà Nội khu vực nhận hàng</div>
  <div class="mt-4 h-40 w-64 rounded-xl border border-border bg-card"></div>
  <div class="mt-4 w-[1200px] bg-muted p-2">rộng</div>
</div>
"""


def run(coro):
    return asyncio.run(coro)


def render(fragment, **kwargs):
    async def go():
        renderer = Renderer(allow_network=False)
        try:
            return await renderer.render(fragment, **kwargs)
        except Exception as error:  # noqa: BLE001 — no browser on this machine
            if "Executable doesn't exist" in str(error):
                pytest.skip("Chromium is not installed")
            raise
        finally:
            await renderer.close()

    return run(go())


def test_document_wraps_fragment_with_theme_runtime_and_csp():
    doc = build_document("<main>Hi</main>", vendor_base="https://x.test/v/")
    assert "<main>Hi</main>" in doc
    assert 'src="https://x.test/v/tailwindcss-browser.js"' in doc
    assert 'src="https://x.test/v/alpine.min.js"' in doc
    assert "script-src https://x.test 'unsafe-inline' 'unsafe-eval'" in doc
    assert "--color-primary" in doc and "window.__designer" in doc
    assert "axe.min.js" not in doc


def test_fragment_of_accepts_a_whole_document():
    whole = "<html><head><style>.x{color:red}</style></head><body class='a'><p>Hi</p></body></html>"
    assert fragment_of(whole) == "<style>.x{color:red}</style>\n<p>Hi</p>"
    assert fragment_of("  <p>Hi</p> ") == "<p>Hi</p>"


def test_render_applies_tailwind_states_and_screenshot():
    default = render(SCREEN, width=800)
    assert default.image and default.image[:3] == b"\xff\xd8\xff"
    assert default.states == ["error"]
    assert "Danh sách" in default.text and "Không tải được" not in default.text
    assert "tailwindcss" in default.css and ".bg-primary" in default.css
    assert not default.blocking, default.findings

    error = render(SCREEN, width=800, state="error", screenshot="png", lint=False)
    assert error.image[:4] == b"\x89PNG"
    assert "Không tải được" in error.text and "Danh sách" not in error.text


def test_lint_reports_overflow_clipped_text_and_empty_region():
    result = render(DEFECTS, width=800, screenshot=None)
    rules = {f["rule"]: f for f in result.findings}
    assert rules["page-overflow"]["severity"] == "error"
    assert rules["clipped-text"]["elements"][0]["text"].startswith("Kho trung tâm")
    assert "empty-region" in rules
    assert {f["rule"] for f in result.blocking} == {"page-overflow", "clipped-text"}
    assert all("data-d" not in e["html"] for f in result.findings for e in f["elements"])
