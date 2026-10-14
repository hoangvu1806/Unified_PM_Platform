"""Copy files from the local storage volume to S3 (one-off, idempotent).

    docker compose exec core-api python -m platform_core.sync_storage [--dry-run]

Walks STORAGE_LOCAL_ROOT and uploads every key missing in the bucket, using
the same key layout (projects/<id>/..., shared/...). Run it once after
switching STORAGE_BACKEND to s3.
"""

from __future__ import annotations

import argparse

from platform_core.settings import get_common_settings
from platform_core.storage import LocalStorage, S3Storage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = get_common_settings()
    if settings.storage_backend != "s3":
        raise SystemExit("STORAGE_BACKEND must be s3")
    local = LocalStorage(settings.storage_local_root)
    s3 = S3Storage(settings)
    uploaded = skipped = 0
    for key in local.keys():
        if s3.exists(key):
            skipped += 1
            continue
        if not args.dry_run:
            s3.client.put_object(Bucket=s3.bucket, Key=s3._object(key), Body=local.get(key))
        uploaded += 1
        print(("would upload " if args.dry_run else "uploaded ") + key)
    print(f"{uploaded} uploaded, {skipped} already in s3://{s3.bucket}")


if __name__ == "__main__":
    main()
