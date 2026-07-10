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
