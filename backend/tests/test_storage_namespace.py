from __future__ import annotations

from libs.integrations.storage import ObjectStorage, StoredObjectVersion


class FakeMinio:
    def __init__(self) -> None:
        self.buckets: set[str] = set()
        self.puts: list[tuple[str, str]] = []

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def make_bucket(self, bucket: str, **_kwargs) -> None:
        self.buckets.add(bucket)

    def put_object(self, bucket: str, object_name: str, *_args, **_kwargs) -> None:
        self.puts.append((bucket, object_name))


def test_storage_namespace_maps_logical_buckets_without_changing_callers(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("AICHECK_MINIO_BUCKET_PREFIX", "audit-bdd8348")
    monkeypatch.setenv("AICHECK_MINIO_OBJECT_NAMESPACE", "run-001")
    storage = ObjectStorage()
    fake = FakeMinio()
    storage._client = fake

    url = storage.put_bytes("documents", "P-1/DV-1.pdf", b"pdf", content_type="application/pdf")

    assert url == "minio://audit-bdd8348-documents/run-001/P-1/DV-1.pdf"
    assert fake.puts == [("audit-bdd8348-documents", "run-001/P-1/DV-1.pdf")]
    assert storage.namespace_status()["physicallyIsolated"] is True


def test_storage_namespace_does_not_double_prefix_physical_urls(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("AICHECK_MINIO_BUCKET_PREFIX", "audit")
    monkeypatch.setenv("AICHECK_MINIO_OBJECT_NAMESPACE", "run")
    storage = ObjectStorage()

    assert storage.bucket_name("audit-documents") == "audit-documents"
    assert storage.object_name("run/P-1/DV-1.pdf") == "run/P-1/DV-1.pdf"


def test_explicit_bucket_name_works_without_prefix(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_MINIO_ENDPOINT", "minio:9000")
    monkeypatch.delenv("AICHECK_MINIO_BUCKET_PREFIX", raising=False)
    monkeypatch.setenv("AICHECK_MINIO_DOCUMENTS_BUCKET", "isolated-documents")
    storage = ObjectStorage()

    assert storage.bucket_name("documents") == "isolated-documents"


def test_locked_raw_vault_write_verifies_bytes_and_legal_hold(monkeypatch) -> None:
    stored: dict[tuple[str, str], bytes] = {}

    class Result:
        version_id = "version-1"
        etag = "etag-1"

    class Response:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def read(self) -> bytes:
            return self.data

        def close(self) -> None:
            pass

        def release_conn(self) -> None:
            pass

    class LockedClient(FakeMinio):
        def put_object(self, bucket: str, object_name: str, stream, *_args, **_kwargs):
            stored[(bucket, object_name)] = stream.read()
            return Result()

        def get_object(self, bucket: str, object_name: str, *, version_id: str | None = None):
            assert version_id == "version-1"
            return Response(stored[(bucket, object_name)])

        def enable_object_legal_hold(
            self,
            bucket: str,
            object_name: str,
            version_id: str | None = None,
        ) -> None:
            self.puts.append(("legal-hold", bucket, object_name, version_id))

        def is_object_legal_hold_enabled(
            self,
            bucket: str,
            object_name: str,
            version_id: str | None = None,
        ) -> bool:
            self.puts.append(("legal-hold-check", bucket, object_name, version_id))
            return True

    monkeypatch.setenv("AICHECK_MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("AICHECK_RAW_VAULT_BUCKET", "raw-locked")
    storage = ObjectStorage()
    storage._client = LockedClient()

    result = storage.put_locked_bytes(
        "agent-raw-vault",
        "TENANT-A/RRUN-1/event.json",
        b"exact bytes",
        content_type="application/json",
    )

    assert isinstance(result, StoredObjectVersion)
    assert result.bucket == "raw-locked"
    assert result.version_id == "version-1"
    assert result.byte_length == 11
    assert result.legal_hold is True
    assert (
        "legal-hold",
        "raw-locked",
        "TENANT-A/RRUN-1/event.json",
        "version-1",
    ) in storage._client.puts
