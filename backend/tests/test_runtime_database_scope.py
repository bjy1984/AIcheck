from __future__ import annotations

from typing import Any

import pytest


class _Result:
    def __init__(
        self,
        *,
        one: tuple[Any, ...] | None = None,
        all_rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self._one = one
        self._all = all_rows or []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._one

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._all


class _Connection:
    def __init__(
        self,
        *,
        identity: tuple[Any, ...] = ("Release_DB", "aicheck_test_run42"),
        heartbeats: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.identity = identity
        self.heartbeats = heartbeats or []
        self.calls: list[tuple[str, object]] = []
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: object = None) -> _Result:
        normalized = " ".join(query.split()).lower()
        self.calls.append((normalized, params))
        if "current_database()" in normalized:
            return _Result(one=self.identity)
        return _Result(all_rows=self.heartbeats)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _empty_scope() -> dict[str, object]:
    empty_participant = {"ready": False, "database": None, "schema": None, "runMarker": None}
    return {
        "engine": "postgresql",
        "database": "",
        "schema": "",
        "runMarker": "",
        "participants": {
            "api": dict(empty_participant),
            "processingWorker": dict(empty_participant),
            "reviewWorker": dict(empty_participant),
        },
    }


def _matching_payload() -> dict[str, str]:
    return {
        "database": "release_db",
        "schema": "aicheck_test_run42",
        "runMarker": "run-42",
    }


def test_refresh_uses_authoritative_identity_and_all_matching_fresh_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libs.runtime_database_scope import refresh_runtime_database_scope

    import psycopg

    connection = _Connection(
        heartbeats=[
            ("mineru-worker", {**_matching_payload(), "database": "RELEASE_DB"}, True, 25.0),
            ("mineru-worker", _matching_payload(), True, 24.0),
            ("review-worker", _matching_payload(), True, 23.0),
        ]
    )
    connect_calls: list[tuple[str, dict[str, object]]] = []

    def connect(dsn: str, **kwargs: object) -> _Connection:
        connect_calls.append((dsn, kwargs))
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "run-42")

    scope = refresh_runtime_database_scope(
        "postgresql://secret-user:secret-password@secret-host/Configured_DB"
        "?options=-c%20search_path%3Daicheck_test_run42%2Cpublic"
    )

    participant = {
        "ready": True,
        "database": "release_db",
        "schema": "aicheck_test_run42",
        "runMarker": "run-42",
    }
    assert scope == {
        "engine": "postgresql",
        "database": "release_db",
        "schema": "aicheck_test_run42",
        "runMarker": "run-42",
        "participants": {
            "api": participant,
            "processingWorker": participant,
            "reviewWorker": participant,
        },
    }
    assert connect_calls[0][1]["connect_timeout"] == 1
    options = str(connect_calls[0][1]["options"])
    assert "search_path=aicheck_test_run42,public" in options
    assert "statement_timeout=" in options
    assert all(
        secret not in repr(scope)
        for secret in ("secret-user", "secret-password", "secret-host")
    )


def test_mixed_fresh_instances_fail_role_and_stale_mismatch_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libs.runtime_database_scope import refresh_runtime_database_scope

    import psycopg

    connection = _Connection(
        heartbeats=[
            ("mineru-worker", _matching_payload(), True, 20.0),
            (
                "mineru-worker",
                {**_matching_payload(), "runMarker": "other-run"},
                True,
                20.0,
            ),
            ("review-worker", _matching_payload(), True, 18.0),
            (
                "review-worker",
                {**_matching_payload(), "database": "stale_database"},
                False,
                0.0,
            ),
        ]
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "run-42")

    participants = refresh_runtime_database_scope("postgresql:///mixed_workers")["participants"]

    assert participants["processingWorker"] == {
        "ready": False,
        "database": None,
        "schema": None,
        "runMarker": None,
    }
    assert participants["reviewWorker"] == {
        "ready": True,
        "database": "release_db",
        "schema": "aicheck_test_run42",
        "runMarker": "run-42",
    }


def test_malformed_heartbeat_values_are_never_reflected_publicly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libs.runtime_database_scope import refresh_runtime_database_scope

    import psycopg

    hostile_values = (
        "postgresql://credential-user:credential-password@private-host/secret-db",
        "schema-user:schema-password@schema-host",
        "oversized-marker-" + ("x" * 5000),
    )
    connection = _Connection(
        heartbeats=[
            (
                "mineru-worker",
                {
                    "database": hostile_values[0],
                    "schema": {"credential": hostile_values[1]},
                    "runMarker": [hostile_values[2]],
                },
                True,
                20.0,
            ),
            ("review-worker", _matching_payload(), True, 20.0),
        ]
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "run-42")

    scope = refresh_runtime_database_scope("postgresql:///malformed_heartbeat")

    assert scope["participants"]["processingWorker"] == {
        "ready": False,
        "database": None,
        "schema": None,
        "runMarker": None,
    }
    serialized = repr(scope)
    assert all(value not in serialized for value in hostile_values)
    assert len(serialized) < 1000


def test_missing_run_marker_fails_every_participant_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libs.runtime_database_scope import refresh_runtime_database_scope

    import psycopg

    connection = _Connection(
        heartbeats=[
            ("mineru-worker", _matching_payload(), True, 20.0),
            ("review-worker", _matching_payload(), True, 20.0),
        ]
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.delenv("AICHECK_E2E_RUN_MARKER", raising=False)

    scope = refresh_runtime_database_scope("postgresql:///missing_marker")

    assert scope["runMarker"] == ""
    assert all(participant["ready"] is False for participant in scope["participants"].values())


@pytest.mark.parametrize("dsn", [None, "", "not a postgresql dsn"])
def test_runtime_database_scope_returns_empty_without_refreshing(
    monkeypatch: pytest.MonkeyPatch,
    dsn: str | None,
) -> None:
    from libs.runtime_database_scope import runtime_database_scope

    import psycopg

    monkeypatch.delenv("AICHECK_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "must-not-survive-a-database-failure")
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("cache-only scope reads must not connect"),
    )

    assert runtime_database_scope(dsn) == _empty_scope()


def test_refresh_redacts_connection_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from libs.runtime_database_scope import refresh_runtime_database_scope

    import psycopg

    def reject(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("secret-user:secret-password@secret-host")

    monkeypatch.setattr(psycopg, "connect", reject)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "run-42")

    result = refresh_runtime_database_scope(
        "postgresql://secret-user:secret-password@secret-host/failure_db"
    )

    assert result == _empty_scope()
    assert "secret" not in repr(result)


def test_scope_cache_reuses_probe_then_expires_fail_closed_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libs import runtime_database_scope as scope_module

    import psycopg

    now = [100.0]
    connection = _Connection(
        heartbeats=[
            ("mineru-worker", _matching_payload(), True, 20.0),
            ("review-worker", _matching_payload(), True, 20.0),
        ]
    )
    connection_count = 0

    def connect(*_args: object, **_kwargs: object) -> _Connection:
        nonlocal connection_count
        connection_count += 1
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(scope_module, "_monotonic", lambda: now[0], raising=False)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "run-42")
    monkeypatch.setenv("AICHECK_RUNTIME_DATABASE_SCOPE_CACHE_TTL_SECONDS", "2")
    dsn = "postgresql:///cache_expiry"

    refreshed = scope_module.refresh_runtime_database_scope(dsn)
    assert refreshed["participants"]["processingWorker"]["ready"] is True
    assert scope_module.runtime_database_scope(dsn) == refreshed
    assert connection_count == 1

    now[0] += 2.1
    assert scope_module.runtime_database_scope(dsn) == _empty_scope()
    assert connection_count == 1

    scope_module.refresh_runtime_database_scope(dsn)
    assert connection_count == 2


def test_scope_cache_expires_before_a_cached_heartbeat_can_become_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libs import runtime_database_scope as scope_module

    import psycopg

    now = [200.0]
    connection = _Connection(
        heartbeats=[
            ("mineru-worker", _matching_payload(), True, 0.4),
            ("review-worker", _matching_payload(), True, 0.6),
        ]
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(scope_module, "_monotonic", lambda: now[0])
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "run-42")
    monkeypatch.setenv("AICHECK_RUNTIME_DATABASE_SCOPE_CACHE_TTL_SECONDS", "30")
    dsn = "postgresql:///heartbeat_freshness_expiry"

    assert scope_module.refresh_runtime_database_scope(dsn)["participants"][
        "processingWorker"
    ]["ready"] is True

    now[0] += 0.41
    assert scope_module.runtime_database_scope(dsn) == _empty_scope()


def test_slow_post_query_work_cannot_extend_cached_heartbeat_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libs import runtime_database_scope as scope_module

    import psycopg

    now = [300.0]
    connection = _Connection(
        heartbeats=[
            ("mineru-worker", _matching_payload(), True, 0.5),
            ("review-worker", _matching_payload(), True, 0.7),
        ]
    )

    def slow_post_query_rollback() -> None:
        now[0] += 0.4
        connection.rolled_back = True

    connection.rollback = slow_post_query_rollback  # type: ignore[method-assign]
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(scope_module, "_monotonic", lambda: now[0])
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "run-42")
    monkeypatch.setenv("AICHECK_RUNTIME_DATABASE_SCOPE_CACHE_TTL_SECONDS", "30")
    dsn = "postgresql:///slow_post_query_cache"

    refreshed = scope_module.refresh_runtime_database_scope(dsn)
    assert refreshed["participants"]["processingWorker"]["ready"] is True

    now[0] += 0.11
    assert scope_module.runtime_database_scope(dsn) == _empty_scope()


def test_concurrent_refreshes_coalesce_to_one_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from libs import runtime_database_scope as scope_module

    started = Event()
    release = Event()
    probe_count = 0
    healthy_scope = {
        "engine": "postgresql",
        "database": "release_db",
        "schema": "aicheck_test_run42",
        "runMarker": "run-42",
        "participants": {
            "api": {"ready": True, **_matching_payload()},
            "processingWorker": {"ready": True, **_matching_payload()},
            "reviewWorker": {"ready": True, **_matching_payload()},
        },
    }

    def probe(_dsn: str, _run_marker: str):
        nonlocal probe_count
        probe_count += 1
        started.set()
        assert release.wait(timeout=1)
        return scope_module._ProbeResult(healthy_scope)

    monkeypatch.setattr(scope_module, "_probe_runtime_database_scope", probe)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "run-42")
    dsn = "postgresql:///single_flight"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(scope_module.refresh_runtime_database_scope, dsn)
        assert started.wait(timeout=1)
        second = executor.submit(scope_module.refresh_runtime_database_scope, dsn)
        release.set()
        results = [first.result(timeout=1), second.result(timeout=1)]

    assert results == [healthy_scope, healthy_scope]
    assert probe_count == 1


def test_processing_worker_heartbeat_reads_identity_and_writes_on_one_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.mineru_worker import queue

    import psycopg

    connection = _Connection()
    observed_connections: list[object] = []
    connect_kwargs: list[dict[str, object]] = []

    def connected_identity(actual_connection: object) -> dict[str, str]:
        observed_connections.append(actual_connection)
        return {"database": "worker_db", "schema": "aicheck_test_worker"}

    def connect(*_args: object, **kwargs: object) -> _Connection:
        connect_kwargs.append(kwargs)
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(queue, "postgres_connection_identity", connected_identity, raising=False)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "worker-run")

    queue.write_heartbeat(
        "postgresql://secret@host/actual",
        "worker-a",
        {"activeCount": 2, "lastError": None},
    )

    payload = connection.calls[-1][1][2].obj
    assert observed_connections == [connection]
    assert payload == {
        "activeCount": 2,
        "lastError": None,
        "database": "worker_db",
        "schema": "aicheck_test_worker",
        "runMarker": "worker-run",
    }
    assert connection.committed is True
    assert len(connect_kwargs) == 1
    assert connect_kwargs[0]["connect_timeout"] == 1
    assert "statement_timeout=" in str(connect_kwargs[0]["options"])


def test_review_worker_heartbeat_uses_identity_from_its_open_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.review_worker import outbox

    import psycopg

    connection = _Connection()
    observed_connections: list[object] = []
    connect_kwargs: list[dict[str, object]] = []

    def connected_identity(actual_connection: object) -> dict[str, str]:
        observed_connections.append(actual_connection)
        return {"database": "review_db", "schema": "aicheck_test_review"}

    def connect(*_args: object, **kwargs: object) -> _Connection:
        connect_kwargs.append(kwargs)
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(outbox, "postgres_connection_identity", connected_identity)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "review-run")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.test:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "aicheck")

    outbox.write_worker_heartbeat("postgresql://secret@host/actual")

    payload = connection.calls[-1][1][2].obj
    assert observed_connections == [connection]
    assert payload == {
        "taskQueue": "review.workflow",
        "temporalAddress": "temporal.test:7233",
        "temporalNamespace": "aicheck",
        "outboxRelay": True,
        "auditAnchorWriter": True,
        "rawVaultRelay": True,
        "database": "review_db",
        "schema": "aicheck_test_review",
        "runMarker": "review-run",
    }
    assert connection.committed is True
    assert connect_kwargs[0]["connect_timeout"] == 1
    assert "statement_timeout=" in str(connect_kwargs[0]["options"])


def test_runtime_ui_context_reads_cached_scope_without_probing_and_exposes_no_dsn_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from libs import runtime_database_scope as scope_module

    import psycopg

    dsn = (
        "postgresql://route-user:route-password@route-secret-host/route_cache"
        "?options=-c%20search_path%3Daicheck_test_run42%2Cpublic"
    )
    connection = _Connection(
        heartbeats=[
            ("mineru-worker", _matching_payload(), True, 20.0),
            ("review-worker", _matching_payload(), True, 20.0),
        ]
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setenv("AICHECK_DATABASE_URL", dsn)
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "run-42")
    scope_module.refresh_runtime_database_scope()
    monkeypatch.setattr(
        scope_module,
        "_probe_runtime_database_scope",
        lambda *_args, **_kwargs: pytest.fail("public runtime route must be cache-only"),
    )

    response = TestClient(app).get("/runtime/ui-context")

    assert response.status_code == 200
    database_scope = response.json()["data"]["databaseScope"]
    participant = {
        "ready": True,
        "database": "release_db",
        "schema": "aicheck_test_run42",
        "runMarker": "run-42",
    }
    assert database_scope == {
        "engine": "postgresql",
        "database": "release_db",
        "schema": "aicheck_test_run42",
        "runMarker": "run-42",
        "participants": {
            "api": participant,
            "processingWorker": participant,
            "reviewWorker": participant,
        },
    }
    serialized = response.text
    assert all(
        secret not in serialized
        for secret in ("route-user", "route-password", "route-secret-host")
    )


def test_runtime_ui_context_without_database_or_run_marker_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from apps.api.main import app

    monkeypatch.delenv("AICHECK_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AICHECK_E2E_RUN_MARKER", raising=False)

    response = TestClient(app).get("/runtime/ui-context")

    assert response.status_code == 200
    assert response.json()["data"]["databaseScope"] == _empty_scope()


@pytest.mark.asyncio
async def test_database_scope_refresh_loop_repeats_off_event_loop_and_cancels_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import threading

    from apps.api import main as api_main

    event_loop_thread = threading.get_ident()
    refresh_threads: list[int] = []
    refreshed_twice = asyncio.Event()
    loop = asyncio.get_running_loop()

    def refresh() -> None:
        refresh_threads.append(threading.get_ident())
        if len(refresh_threads) >= 2:
            loop.call_soon_threadsafe(refreshed_twice.set)

    monkeypatch.setattr(api_main, "refresh_runtime_database_scope", refresh, raising=False)
    monkeypatch.setenv("AICHECK_DATABASE_URL", "postgresql:///refresh_loop")
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "loop-run")
    monkeypatch.setenv("AICHECK_RUNTIME_DATABASE_SCOPE_REFRESH_SECONDS", "0")

    task = asyncio.create_task(api_main.runtime_database_scope_refresh_loop())
    await asyncio.wait_for(refreshed_twice.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(refresh_threads) >= 2
    assert all(thread_id != event_loop_thread for thread_id in refresh_threads)


@pytest.mark.asyncio
async def test_lifespan_awaits_inflight_scope_refresh_before_closing_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import threading

    from apps.api import main as api_main

    events: list[str] = []
    refresh_started = threading.Event()
    release_refresh = threading.Event()

    async def init(_app: object) -> None:
        events.append("init")

    async def close(_app: object) -> None:
        events.append("close")

    def refresh() -> None:
        events.append("refresh-start")
        refresh_started.set()
        assert release_refresh.wait(timeout=2)
        events.append("refresh-end")

    async def release_after_shutdown_begins() -> None:
        await asyncio.sleep(0.05)
        release_refresh.set()

    monkeypatch.setattr(api_main, "init_postgres_if_configured", init)
    monkeypatch.setattr(api_main, "close_postgres", close)
    monkeypatch.setattr(api_main, "load_state", lambda: None)
    monkeypatch.setattr(api_main, "bootstrap_local_roles_if_configured", lambda: None)
    monkeypatch.setattr(api_main, "validate_security_runtime", lambda: None)
    monkeypatch.setattr(api_main, "authentication_enforced", lambda: True)
    monkeypatch.setattr(api_main, "refresh_runtime_database_scope", refresh, raising=False)
    monkeypatch.setenv("AICHECK_DATABASE_URL", "postgresql:///lifespan_refresh")
    monkeypatch.setenv("AICHECK_E2E_RUN_MARKER", "lifespan-run")

    async with api_main.lifespan(object()):
        assert await asyncio.to_thread(refresh_started.wait, 1)
        events.append("body")
        release_task = asyncio.create_task(release_after_shutdown_begins())

    await release_task
    assert events.index("body") < events.index("refresh-end") < events.index("close")
