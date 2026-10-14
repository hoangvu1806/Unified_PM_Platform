"""File storage behind one interface; keys follow the future S3 layout.

Keys look like ``projects/<project_id>/designer/assets/<name>`` or
``shared/wiki/blobs/<name>``. ``LocalStorage`` maps them under
``STORAGE_LOCAL_ROOT`` today; an S3 backend will reuse the same keys.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Protocol

from platform_core.settings import CommonSettings, get_common_settings


def project_key(project_id: str | None, *parts: str) -> str:
    scope = f"projects/{project_id}" if project_id else "shared"
    return str(PurePosixPath(scope, *parts))


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def local_path(self, key: str) -> Path | None: ...


class LocalStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / PurePosixPath(key)).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError(f"storage key escapes root: {key!r}")
        return path

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def local_path(self, key: str) -> Path | None:
        return self._path(key)


def get_storage(settings: CommonSettings | None = None) -> Storage:
    s = settings or get_common_settings()
    if s.storage_backend == "local":
        return LocalStorage(s.storage_local_root)
    raise NotImplementedError(f"STORAGE_BACKEND={s.storage_backend!r} is not available yet")
