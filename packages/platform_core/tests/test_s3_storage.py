"""S3Storage against moto (no network, never the real bucket)."""

import boto3
import pytest
from moto import mock_aws

from platform_core.settings import CommonSettings
from platform_core.storage import S3Storage


@pytest.fixture()
def s3(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")
        settings = CommonSettings(
            storage_backend="s3", storage_local_root=str(tmp_path / "cache"),
            s3_bucket="test-bucket", s3_prefix="team", s3_region="us-east-1",
            s3_access_key_id="test", s3_secret_access_key="test",
        )
        yield S3Storage(settings)


def test_put_writes_bucket_and_cache(s3):
    s3.put("projects/P/a.txt", b"hello", content_type="text/plain")
    raw = s3.client.get_object(Bucket="test-bucket", Key="team/projects/P/a.txt")["Body"].read()
    assert raw == b"hello"
    assert s3.cache.get("projects/P/a.txt") == b"hello"


def test_local_path_downloads_on_cache_miss(s3):
    s3.put("shared/x.bin", b"\x00\x01")
    s3.cache.delete("shared/x.bin")
    path = s3.local_path("shared/x.bin")
    assert path.read_bytes() == b"\x00\x01"


def test_exists_delete_keys(s3):
    s3.put("projects/P/one", b"1")
    s3.put("projects/Q/two", b"2")
    assert s3.exists("projects/P/one") and not s3.exists("projects/P/none")
    assert sorted(s3.keys("projects/")) == ["projects/P/one", "projects/Q/two"]
    s3.delete("projects/P/one")
    assert not s3.exists("projects/P/one") and not s3.cache.exists("projects/P/one")


def test_bad_keys_rejected(s3):
    for key in ("../etc", "/abs", "a/../../b"):
        with pytest.raises(ValueError):
            s3.put(key, b"x")
