from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from libs.contracts.responses import SERVER_TZ


DEFAULT_BUCKETS = ("documents", "previews", "exports", "ocr-artifacts")


class ObjectStorage:
    def __init__(self) -> None:
        self.endpoint = os.getenv("AICHECK_MINIO_ENDPOINT", "").strip()
        self.access_key = os.getenv("AICHECK_MINIO_ACCESS_KEY", "aicheck")
        self.secret_key = os.getenv("AICHECK_MINIO_SECRET_KEY", "aicheck-dev-password")
        self.secure = os.getenv("AICHECK_MINIO_SECURE", "false").lower() == "true"
        self.public_endpoint = os.getenv("AICHECK_MINIO_PUBLIC_ENDPOINT", self.endpoint).strip()
        self._client: Any | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

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
        )

    def ensure_buckets(self) -> None:
        client = self.client()
        if client is None:
            return
        for bucket in DEFAULT_BUCKETS:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)

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
        bucket, object_name = parsed
        self.ensure_buckets()
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
