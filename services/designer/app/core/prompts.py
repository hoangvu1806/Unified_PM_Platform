from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "docs" / "knowledge"  # services/designer/docs

DESIGN_PROMPTS = {
    "project_analyzer",
    "master_architect",
    "screen-composer",
    "page-designer",
    "revision",
    "workspace-page-plan",
}

KNOWLEDGE_FILES = (
    "design-craft.md",
    "gemini-code-1790741317691.md",
    "layout-and-typography-rules.md",
    "fig-export-asset-and-layout-quality.md",
)


class PromptLibrary:
    def __init__(self, directory: Path = PROMPT_DIR) -> None:
        self.directory = directory
        self._cache: dict[str, str] = {}

    def render(self, name: str, **values: object) -> str:
        template = self._load(name)
        for key, value in values.items():
            template = template.replace("{{" + key + "}}", str(value))
        if name in DESIGN_PROMPTS:
            for knowledge_file in KNOWLEDGE_FILES:
                knowledge = KNOWLEDGE_DIR / knowledge_file
                template += "\n\n" + knowledge.read_text(encoding="utf-8")
        return template

    def _load(self, name: str) -> str:
        if name not in self._cache:
            path = self.directory / f"{name}.md"
            self._cache[name] = path.read_text(encoding="utf-8")
        return self._cache[name]
