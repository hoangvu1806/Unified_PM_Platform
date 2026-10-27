"""File storage behind one interface; keys follow the S3 layout.

Keys look like ``projects/<project_id>/designer/assets/<name>`` or
``shared/wiki/blobs/<name>``.

* ``LocalStorage`` keeps files under ``STORAGE_LOCAL_ROOT``.
* ``S3Storage`` is the source of truth in S3 and keeps a write-through cache
  under ``STORAGE_LOCAL_ROOT``: services that read files by path (PDF
  extraction, design assets) call :meth:`local_path`, which downloads the
  object when the cache misses.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Iterator, Protocol

from platform_core.settings import CommonSettings, get_common_settings


def project_key(project_id: str | None, *parts: str) -> str:
    scope = f"projects/{project_id}" if project_id else "shared"
    return str(PurePosixPath(scope, *parts))


def _check_key(key: str) -> str:
    clean = str(PurePosixPath(key))
    if not clean or clean.startswith("/") or ".." in PurePosixPath(clean).parts:
        raise ValueError(f"invalid storage key: {key!r}")
    return clean


class Storage(Protocol):
    backend: str

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def local_path(self, key: str) -> Path: ...
    def keys(self, prefix: str = "") -> Iterator[str]: ...


class LocalStorage:
    backend = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / _check_key(key)).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError(f"storage key escapes root: {key!r}")
        return path

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
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

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def keys(self, prefix: str = "") -> Iterator[str]:
        base = self.root
        for path in sorted(base.rglob("*")):
            if path.is_file():
                key = path.relative_to(base).as_posix()
                if key.startswith(prefix):
                    yield key


class S3Storage:
    """S3 (MinIO / Ceph RGW / AWS) with a local write-through cache."""

    backend = "s3"

    def __init__(self, settings: CommonSettings) -> None:
        import boto3
        from botocore.config import Config

        if not settings.s3_bucket:
            raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.cache = LocalStorage(settings.storage_local_root)
        self._lock = threading.Lock()
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or "us-east-1",
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            verify=settings.s3_verify_ssl,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": settings.s3_addressing_style or "path"},
                retries={"max_attempts": 4, "mode": "standard"},
                connect_timeout=10,
                read_timeout=60,
            ),
        )

    def _object(self, key: str) -> str:
        key = _check_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=self._object(key), Body=data, **extra)
        self.cache.put(key, data)
        return key

    def get(self, key: str) -> bytes:
        if self.cache.exists(key):
            return self.cache.get(key)
        body = self.client.get_object(Bucket=self.bucket, Key=self._object(key))["Body"].read()
        self.cache.put(key, body)
        return body

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        obj = self._object(key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=obj)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            if code not in {"403", "AccessDenied", "Forbidden"}:
                raise
        # Some gateways (e.g. behind Cloudflare) intermittently answer HEAD with
        # 403; LIST is authoritative for existence.
        listing = self.client.list_objects_v2(Bucket=self.bucket, Prefix=obj, MaxKeys=1)
        return any(item["Key"] == obj for item in listing.get("Contents", []))

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._object(key))
        self.cache.delete(key)

    def local_path(self, key: str) -> Path:
        """Cached file path; downloads the object on a cache miss (if it exists)."""
        path = self.cache.local_path(key)
        if not path.is_file():
            with self._lock:
                if not path.is_file() and self.exists(key):
                    self.get(key)
        return path

    def upload_local(self, key: str) -> str:
        """Push a file that code wrote straight into the cache."""
        return self.put(key, self.cache.get(key))

    def keys(self, prefix: str = "") -> Iterator[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        full = self._object(prefix) if prefix else (self.prefix + "/" if self.prefix else "")
        strip = len(self.prefix) + 1 if self.prefix else 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full):
            for obj in page.get("Contents", []):
                yield obj["Key"][strip:]


def make_storage(settings: CommonSettings) -> Storage:
    s = settings
    if s.storage_backend == "local":
        return LocalStorage(s.storage_local_root)
    if s.storage_backend == "s3":
        return S3Storage(s)
    raise ValueError(f"unknown STORAGE_BACKEND={s.storage_backend!r}")


@lru_cache
def get_storage() -> Storage:
    """Process-wide storage from the platform .env."""
    return make_storage(get_common_settings())


def put_local_file(key: str) -> None:
    """After writing straight to ``local_path(key)``, publish it to the backend."""
    storage = get_storage()
    if isinstance(storage, S3Storage):
        storage.upload_local(key)
