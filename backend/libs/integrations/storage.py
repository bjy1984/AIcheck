from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from libs.contracts.responses import SERVER_TZ


DEFAULT_BUCKETS = ("documents", "previews", "exports", "ocr-artifacts")


class ObjectStorageUnavailable(RuntimeError):
    """Raised when production mode requires object storage but no signed URL can be created."""


class ObjectStorage:
    def __init__(self) -> None:
        self.endpoint = os.getenv("AICHECK_MINIO_ENDPOINT", "").strip()
        self.access_key = os.getenv("AICHECK_MINIO_ACCESS_KEY", "aicheck")
        self.secret_key = os.getenv("AICHECK_MINIO_SECRET_KEY", "aicheck-dev-password")
        self.secure = os.getenv("AICHECK_MINIO_SECURE", "false").lower() == "true"
        self.region = os.getenv("AICHECK_MINIO_REGION", "us-east-1").strip() or "us-east-1"
        self.public_endpoint = os.getenv("AICHECK_MINIO_PUBLIC_ENDPOINT", self.endpoint).strip()
        self._client: Any | None = None
        self._buckets_ensured = False

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

    @property
    def required(self) -> bool:
        explicit = os.getenv("AICHECK_REQUIRE_OBJECT_STORAGE", "").strip().lower()
        if explicit in {"true", "1", "yes"}:
            return True
        if explicit in {"false", "0", "no"}:
            return False
        auth_required = os.getenv("AICHECK_REQUIRE_AUTH", "false").lower() == "true"
        demo_disabled = os.getenv("AICHECK_ENABLE_DEMO_USERS", "true").lower() == "false"
        return auth_required and demo_disabled

    def expires_at(self, minutes: int = 30) -> str:
        return (datetime.now(SERVER_TZ) + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")

    def client(self) -> Any | None:
        if not self.enabled:
            return None
        if self._client is not None:
            return self._client
        try:
            from minio import Minio
        except Exception:
            return None
        self._client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure,
            region=self.region,
        )
        return self._client

    def presign_client(self) -> Any | None:
        client = self.client()
        if client is None:
            return None
        if not self.public_endpoint or self.public_endpoint == self.endpoint:
            return client
        try:
            from minio import Minio
        except Exception:
            return client
        endpoint, secure = normalize_minio_endpoint(self.public_endpoint, default_secure=self.secure)
        return Minio(
            endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=secure,
            region=self.region,
        )

    def ensure_buckets(self) -> None:
        if self._buckets_ensured:
            return
        client = self.client()
        if client is None:
            return
        for bucket in DEFAULT_BUCKETS:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
        self._buckets_ensured = True

    def presigned_put_url(self, bucket: str, object_name: str, *, content_type: str | None = None) -> str | None:
        client = self.presign_client()
        if client is None:
            return None
        self.ensure_buckets()
        return client.presigned_put_object(bucket, object_name, expires=timedelta(minutes=30))

    def presigned_get_url(self, url: str, *, file_name: str | None = None) -> str | None:
        parsed = parse_storage_url(url)
        if parsed is None:
            return None
        client = self.presign_client()
        if client is None:
            return None
        self.ensure_buckets()
        bucket, object_name = parsed
        return client.presigned_get_object(
            bucket,
            object_name,
            expires=timedelta(minutes=30),
            response_headers={"response-content-disposition": f'attachment; filename="{file_name}"'} if file_name else None,
        )

    def put_bytes(self, bucket: str, object_name: str, data: bytes, *, content_type: str) -> str | None:
        client = self.client()
        if client is None:
            return None
        self.ensure_buckets()
        import io

        client.put_object(bucket, object_name, io.BytesIO(data), length=len(data), content_type=content_type)
        return f"minio://{bucket}/{object_name}"

    def remove_object(self, bucket: str, object_name: str) -> bool:
        client = self.client()
        if client is None:
            if self.required:
                raise ObjectStorageUnavailable("对象存储不可用，无法删除文件对象。")
            return False
        try:
            from minio.error import S3Error
        except Exception:
            S3Error = None  # type: ignore[assignment]
        existed = True
        try:
            client.stat_object(bucket, object_name)
        except Exception as exc:
            if S3Error is not None and isinstance(exc, S3Error) and exc.code == "NoSuchKey":
                existed = False
            elif self.required:
                raise ObjectStorageUnavailable(f"对象存储对象检查失败：{exc}")
        try:
            client.remove_object(bucket, object_name)
            return existed
        except Exception as exc:
            if S3Error is not None and isinstance(exc, S3Error) and exc.code == "NoSuchKey":
                return False
            if self.required:
                raise ObjectStorageUnavailable(f"对象存储删除失败：{exc}")
            return False

    def download_to_temp(self, bucket: str, object_name: str, *, suffix: str = "") -> Path | None:
        client = self.client()
        if client is None:
            return None
        target = Path(tempfile.mkdtemp(prefix="aicheck-ocr-")) / f"source{suffix}"
        client.fget_object(bucket, object_name, str(target))
        return target


def parse_storage_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme != "minio" or not parsed.netloc:
        return None
    return parsed.netloc, unquote(parsed.path.lstrip("/"))


def normalize_minio_endpoint(endpoint: str, *, default_secure: bool) -> tuple[str, bool]:
    if "://" not in endpoint:
        return endpoint.strip("/"), default_secure
    parsed = urlparse(endpoint)
    return (parsed.netloc or parsed.path).strip("/"), parsed.scheme == "https"


object_storage = ObjectStorage()
