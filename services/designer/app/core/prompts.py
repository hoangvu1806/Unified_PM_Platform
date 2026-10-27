from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


class PromptLibrary:
    """Markdown prompts under ``prompts/``; ``{{name}}`` placeholders are filled by ``render``."""

    def __init__(self, directory: Path = PROMPT_DIR) -> None:
        self.directory = directory
        self._cache: dict[str, str] = {}

    def render(self, name: str, **values: object) -> str:
        template = self._load(name)
        for key, value in values.items():
            template = template.replace("{{" + key + "}}", str(value))
        return template

    def _load(self, name: str) -> str:
        if name not in self._cache:
            self._cache[name] = (self.directory / f"{name}.md").read_text(encoding="utf-8")
        return self._cache[name]
