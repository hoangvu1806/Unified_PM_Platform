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


def storage_root() -> Path:
    """Shared platform file storage (keys follow the S3 layout)."""
    import os

    raw = os.environ.get("STORAGE_LOCAL_ROOT", "").strip()
    return Path(raw) if raw else data_dir() / "storage"


def blob_key(source_file: str, namespace: str, project_id: str | None) -> str:
    """Storage key of a wiki source blob: projects/<id>/wiki/blobs/… or shared/wiki/blobs/…"""
    scope = f"projects/{project_id}" if namespace == "project" and project_id else "shared"
    return f"{scope}/wiki/blobs/{source_file}"


def blob_path(key: str) -> Path:
    root = storage_root().resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError(f"blob key escapes storage root: {key!r}")
    return path


def _platform_storage():
    """platform_core storage when installed (platform), else None (standalone MVP)."""
    try:
        from platform_core.storage import get_storage
    except ImportError:
        return None
    return get_storage()


def put_blob(key: str, data: bytes) -> Path:
    """Store a source blob (S3 + local cache on the platform) and return its local path."""
    storage = _platform_storage()
    if storage is not None:
        storage.put(key, data)
        return storage.local_path(key)
    path = blob_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def delete_blob(key: str) -> bool:
    storage = _platform_storage()
    if storage is not None:
        existed = storage.local_path(key).is_file() or storage.exists(key)
        storage.delete(key)
        return existed
    path = blob_path(key)
    if path.is_file():
        path.unlink()
        return True
    return False
