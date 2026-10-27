"""The service imports and exposes the HTML designer API (catches broken imports/exports early)."""


def test_app_routes():
    from app.main import app

    paths = set(app.openapi()["paths"])
    for path in (
        "/api/v1/health",
        "/api/v1/sessions/{session_id}/screens/{screen_id}/document",
        "/api/v1/sessions/{session_id}/export",
        "/api/v1/design-systems",
        "/api/v1/design-systems/{ds_id}/gallery",
        "/api/v1/render/vendor/{name}",
        "/api/v1/handoffs",
    ):
        assert path in paths, path
    assert not any("openpencil" in p for p in paths)


def test_prompts_are_small():
    from app.core.prompts import PROMPT_DIR

    for name in ("router", "spec", "builder"):
        text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
        assert len(text) < 6000, (name, len(text))  # ≈ 1.5k tokens before context is filled in
