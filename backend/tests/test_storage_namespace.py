from __future__ import annotations

from libs.integrations.storage import ObjectStorage


class FakeMinio:
    def __init__(self) -> None:
        self.buckets: set[str] = set()
        self.puts: list[tuple[str, str]] = []

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
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
