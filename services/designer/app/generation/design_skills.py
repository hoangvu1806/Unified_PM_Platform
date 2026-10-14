"""Renderer knowledge used by the page-design tool loop."""

from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "skills"
OPENPENCIL_JSX_KNOWLEDGE = SKILLS_DIR / "openpencil_jsx.md"


def load_openpencil_jsx_knowledge() -> str:
    """Load the compact renderer contract used by the page designer."""
    return OPENPENCIL_JSX_KNOWLEDGE.read_text(encoding="utf-8")
