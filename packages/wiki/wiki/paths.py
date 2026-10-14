from pathlib import Path

MVP_ROOT = Path(__file__).resolve().parent.parent


def data_dir(root: Path | None = None) -> Path:
    return (root or MVP_ROOT) / "data"


def db_path(root: Path | None = None) -> Path:
    return data_dir(root) / "wiki.db"


def blob_dir(root: Path | None = None) -> Path:
    return data_dir(root) / "blobs"


def audit_path(root: Path | None = None) -> Path:
    return data_dir(root) / "audit.jsonl"


def manifest_path(root: Path | None = None) -> Path:
    return (root or MVP_ROOT) / "config" / "manifest.json"


def templates_dir() -> Path:
    return MVP_ROOT / "templates"
