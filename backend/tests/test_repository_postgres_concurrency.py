from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from libs.db.repository import InMemoryRepository


class EmptyCursor:
    def fetchall(self):
        return []


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

    def transaction(self):
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

    def execute(self, sql, params=None):
        self.statements.append((" ".join(str(sql).split()), params))
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
    assert review_upsert[0] == "review_runs"
    assert review_upsert[1] == "RRUN-1"


def test_scoped_postgres_sync_deletes_only_explicit_stale_rows() -> None:
    repository = InMemoryRepository()
    connection = RecordingConnection()
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True

    repository.sync_state_records_to_sync_postgres(
        {"extracted_fields": [{"id": "FIELD-NEW", "documentVersionId": "DV-1"}]},
        {"extracted_fields": ["FIELD-OLD"]},
    )

    sql = [statement for statement, _ in connection.statements]
    assert any("DELETE FROM aicheck_state WHERE collection = %s AND object_id = ANY(%s)" in statement for statement in sql)
    assert not any(statement == "DELETE FROM aicheck_state" for statement in sql)
    delete_params = next(
        params
        for statement, params in connection.statements
        if "DELETE FROM aicheck_state WHERE collection" in statement
    )
    assert delete_params == ("extracted_fields", ["FIELD-OLD"])


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
        if "SELECT collection, payload FROM aicheck_state WHERE collection = ANY" in statement
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
    assert "knowledge_vectors" not in params[0]
    assert "ocr_parse_results" in params[1]
    assert params[2] == ["DOC-1", "DV-1"]
    assert params[3:] == ("DOC-1", "DV-1")
