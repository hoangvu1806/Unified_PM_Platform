from app import knowledge
from app.designsystem.direction import direction_theme


def test_profiles_follow_the_domain():
    edu = knowledge.product_profile("university e-learning student mobile app")
    stock = knowledge.product_profile("warehouse inventory stock management internal")
    assert edu and stock and edu["product"]["Product Type"] != stock["product"]["Product Type"]
    text = knowledge.profile_text(stock)
    assert "Reference palette" in text and "#" in text and "Avoid" in text


def test_ux_rules_respect_the_platform():
    mobile = knowledge.ux_rules("login form password validation error", "mobile")
    desktop = knowledge.ux_rules("data table filter pagination", "desktop")
    assert mobile and desktop and mobile != desktop
    assert any("Password" in r for r in mobile)


def test_skill_and_checklist_are_loaded():
    assert "Ground your designs in the subject matter" in knowledge.frontend_design_skill()
    checklist = knowledge.review_checklist()
    assert "emojis" in checklist and "Color is not the only indicator" in checklist


def test_direction_becomes_theme_tokens():
    theme = direction_theme({
        "palette": {"primary": "#0f766e", "background": "#ffffff", "foreground": "#111827", "surface": "#ffffff",
                    "muted": "#f3f4f6", "muted_foreground": "#4b5563", "border": "#e5e7eb", "accent": "#f59e0b",
                    "primary_foreground": "#ffffff", "success": "#16a34a", "warning": "#d97706", "destructive": "#dc2626"},
        "heading_font": "Fraunces", "body_font": "Inter", "radius": "xl",
    })
    assert "--color-primary: #0f766e;" in theme["css"] and "--font-heading" in theme["css"]
    assert "--radius-lg: 12px;" in theme["css"]
    assert len(theme["fonts"]) == 2
