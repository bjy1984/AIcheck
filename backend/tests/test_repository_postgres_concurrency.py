from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from libs.db.repository import InMemoryRepository
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id


class EmptyCursor:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class DetectConcurrentTransaction:
    def __init__(self, connection: "DetectConcurrentConnection") -> None:
        self.connection = connection

    def __enter__(self):
        with self.connection.guard:
            self.connection.active_transactions += 1
            self.connection.max_active_transactions = max(
                self.connection.max_active_transactions,
                self.connection.active_transactions,
            )
            if self.connection.active_transactions > 1:
                raise RuntimeError("concurrent transaction on shared connection")
        time.sleep(0.01)
        return self

    def __exit__(self, exc_type, exc, tb):
        with self.connection.guard:
            self.connection.active_transactions -= 1
        return False


class DetectConcurrentConnection:
    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.active_transactions = 0
        self.max_active_transactions = 0
        self.transaction_count = 0

    def transaction(self):
        self.transaction_count += 1
        return DetectConcurrentTransaction(self)

    def execute(self, sql, params=None):
        time.sleep(0.001)
        return EmptyCursor()

    def commit(self):
        return None


class RecordingConnection(DetectConcurrentConnection):
    def __init__(self) -> None:
        super().__init__()
        self.statements: list[tuple[str, object]] = []
        self.state_rows: dict[tuple[str, str], dict] = {}

    def execute(self, sql, params=None):
        statement = " ".join(str(sql).split())
        self.statements.append((statement, params))
        if statement.startswith("SELECT payload FROM aicheck_state"):
            payload = self.state_rows.get((str(params[-2]), str(params[-1])))
            return EmptyCursor([(payload,)] if payload is not None else [])
        return EmptyCursor()


def test_shared_sync_postgres_connection_serializes_concurrent_transactions() -> None:
    repository = InMemoryRepository()
    connection = DetectConcurrentConnection()
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(repository.ensure_postgres_schema) for _ in range(16)]
        for future in futures:
            future.result()

    assert connection.max_active_transactions == 1


def test_scoped_postgres_upsert_never_replaces_unrelated_state() -> None:
    repository = InMemoryRepository()
    connection = RecordingConnection()
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True

    repository.upsert_state_records_to_sync_postgres(
        {"review_runs": [{"id": "RRUN-1", "reviewRunId": "RRUN-1", "status": "queued"}]}
    )

    sql = [statement for statement, _ in connection.statements]
    assert any("INSERT INTO aicheck_state" in statement for statement in sql)
    assert not any("DELETE FROM aicheck_state" in statement for statement in sql)
    review_upsert = next(
        params
        for statement, params in connection.statements
        if "INSERT INTO aicheck_state" in statement
    )
    assert review_upsert[0] == "TENANT-DEFAULT"
    assert review_upsert[1] == "review_runs"
    assert review_upsert[2] == "RRUN-1"


def test_scoped_postgres_sync_deletes_only_explicit_stale_rows() -> None:
    repository = InMemoryRepository()
    connection = RecordingConnection()
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True
    stale = {"id": "FIELD-OLD", "documentVersionId": "DV-1"}
    connection.state_rows[("extracted_fields", "FIELD-OLD")] = stale
    repository._persistence_baseline[("extracted_fields", "FIELD-OLD")] = (
        repository.canonical_persistence_payload(stale)
    )

    repository.sync_state_records_to_sync_postgres(
        {"extracted_fields": [{"id": "FIELD-NEW", "documentVersionId": "DV-1"}]},
        {"extracted_fields": ["FIELD-OLD"]},
    )

    sql = [statement for statement, _ in connection.statements]
    assert any(
        "DELETE FROM aicheck_state WHERE tenant_id = %s AND collection = %s AND object_id = %s" in statement
        for statement in sql
    )
    assert not any(statement == "DELETE FROM aicheck_state" for statement in sql)
    delete_params = next(
        params
        for statement, params in connection.statements
        if "DELETE FROM aicheck_state WHERE tenant_id" in statement
    )
    assert delete_params == ("TENANT-DEFAULT", "extracted_fields", "FIELD-OLD")


def test_scoped_postgres_load_queries_only_selected_collections() -> None:
    repository = InMemoryRepository()
    connection = RecordingConnection()
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True

    repository.load_from_sync_postgres({"documents", "versions", "ocr_parse_results"})

    query = next(
        (statement, params)
        for statement, params in connection.statements
        if "SELECT collection, object_id, payload FROM aicheck_state WHERE collection = ANY" in statement
    )
    assert set(query[1][0]) == {"documents", "document_versions", "ocr_parse_results"}
    assert "knowledge_vectors" not in query[1][0]


def test_ocr_task_postgres_load_scopes_historical_payloads_to_document() -> None:
    repository = InMemoryRepository()
    connection = RecordingConnection()
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True

    repository.load_ocr_task_state_from_sync_postgres("DOC-1", "DV-1")

    statement, params = next(
        (statement, params)
        for statement, params in connection.statements
        if "payload ->> 'documentVersionId'" in statement
    )
    assert params[0] == "TENANT-DEFAULT"
    assert "knowledge_vectors" not in params[1]
    assert "ocr_parse_results" in params[2]
    assert params[3] == ["DOC-1", "DV-1"]
    assert params[4:] == ("DOC-1", "DV-1")


def test_state_and_idempotency_completion_share_one_postgres_transaction() -> None:
    repository = InMemoryRepository()
    connection = RecordingConnection()
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True
    scope = "TENANT-DEFAULT:USER-1:inspection:POST:/review-runs/RRUN-1/cancel:key"
    repository.state["idempotency"][scope] = {
        "tenantId": "TENANT-DEFAULT",
        "requestHash": "sha256:request",
        "response": {"code": 0},
    }
    repository.ensure_postgres_schema()
    connection.transaction_count = 0
    connection.statements.clear()

    repository.upsert_state_records_to_sync_postgres(
        {"review_runs": [{"id": "RRUN-1", "reviewRunId": "RRUN-1", "status": "queued"}]},
        idempotency_scopes=[scope],
    )

    statements = [statement for statement, _ in connection.statements]
    assert connection.transaction_count == 1
    assert any("INSERT INTO aicheck_state" in statement for statement in statements)
    assert any("INSERT INTO idempotency_records" in statement for statement in statements)


def test_sqlite_composite_key_allows_same_object_id_in_two_tenants(tmp_path) -> None:
    repository = InMemoryRepository()
    repository.configure_sqlite(tmp_path / "tenant-state.sqlite3")

    tenant_a = set_request_tenant_id("TENANT-A")
    try:
        repository.sync_state_records_to_sqlite(
            {"review_runs": [{"id": "RRUN-SAME", "reviewRunId": "RRUN-SAME", "status": "queued"}]},
            {},
        )
    finally:
        reset_request_tenant_id(tenant_a)

    tenant_b = set_request_tenant_id("TENANT-B")
    try:
        repository.sync_state_records_to_sqlite(
            {"review_runs": [{"id": "RRUN-SAME", "reviewRunId": "RRUN-SAME", "status": "running"}]},
            {},
        )
    finally:
        reset_request_tenant_id(tenant_b)

    with repository.sqlite_connection() as connection:
        rows = connection.execute(
            "SELECT tenant_id, object_id FROM aicheck_state WHERE collection = ? ORDER BY tenant_id",
            ("review_runs",),
        ).fetchall()
    assert rows == [("TENANT-A", "RRUN-SAME"), ("TENANT-B", "RRUN-SAME")]
