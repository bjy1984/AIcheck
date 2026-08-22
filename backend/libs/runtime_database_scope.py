from __future__ import annotations

import math
import os
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from threading import Condition
from typing import Protocol, TypedDict


_WORKER_ROLES = ("mineru-worker", "review-worker")
_PARTICIPANT_ROLES = {
    "mineru-worker": "processingWorker",
    "review-worker": "reviewWorker",
}
_MAX_CACHE_ENTRIES = 8
_MAX_HEARTBEAT_IDENTITY_LENGTH = 512
_monotonic = time.monotonic


class DatabaseIdentity(TypedDict):
    database: str
    schema: str


class ParticipantScope(TypedDict):
    ready: bool
    database: str | None
    schema: str | None
    runMarker: str | None


class ParticipantsScope(TypedDict):
    api: ParticipantScope
    processingWorker: ParticipantScope
    reviewWorker: ParticipantScope


class RuntimeDatabaseScope(TypedDict):
    engine: str
    database: str
    schema: str
    runMarker: str
    participants: ParticipantsScope


class PostgresConnectionKwargs(TypedDict):
    connect_timeout: int
    options: str


class QueryResult(Protocol):
    def fetchone(self) -> Sequence[object] | None: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: object = None) -> QueryResult: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True)
class _CacheEntry:
    scope: RuntimeDatabaseScope
    expires_at: float


@dataclass(frozen=True)
class _ProbeResult:
    scope: RuntimeDatabaseScope
    freshness_deadline: float | None = None


_CACHE_CONDITION = Condition()
_SCOPE_CACHE: OrderedDict[str, _CacheEntry] = OrderedDict()
_REFRESHING_KEYS: set[str] = set()


def _empty_participant() -> ParticipantScope:
    return {"ready": False, "database": None, "schema": None, "runMarker": None}


def _empty_scope() -> RuntimeDatabaseScope:
    return {
        "engine": "postgresql",
        "database": "",
        "schema": "",
        "runMarker": "",
        "participants": {
            "api": _empty_participant(),
            "processingWorker": _empty_participant(),
            "reviewWorker": _empty_participant(),
        },
    }


def _probe_timeout_seconds() -> float:
    try:
        return min(
            2.0,
            max(
                0.1,
                float(os.getenv("AICHECK_RUNTIME_DATABASE_SCOPE_TIMEOUT_SECONDS", "0.75")),
            ),
        )
    except ValueError:
        return 0.75


def _heartbeat_max_age_seconds() -> int:
    try:
        return max(
            1,
            min(
                300,
                int(os.getenv("AICHECK_WORKER_HEARTBEAT_MAX_AGE_SECONDS", "30")),
            ),
        )
    except ValueError:
        return 30


def _cache_ttl_seconds() -> float:
    try:
        configured = float(os.getenv("AICHECK_RUNTIME_DATABASE_SCOPE_CACHE_TTL_SECONDS", "5"))
    except ValueError:
        configured = 5.0
    return min(float(_heartbeat_max_age_seconds()), max(0.1, min(30.0, configured)))


def postgres_connection_kwargs(dsn: str) -> PostgresConnectionKwargs:
    """Validate a DSN and preserve its search_path without exposing connection secrets."""
    from psycopg.conninfo import conninfo_to_dict

    parsed = conninfo_to_dict(dsn)
    timeout = _probe_timeout_seconds()
    existing_options = str(parsed.get("options") or "").strip()
    statement_timeout = f"-c statement_timeout={max(100, math.ceil(timeout * 1000))}"
    return {
        "connect_timeout": max(1, math.ceil(timeout)),
        "options": " ".join(part for part in (existing_options, statement_timeout) if part),
    }


def postgres_connection_identity(connection: DatabaseConnection) -> DatabaseIdentity:
    row = connection.execute("SELECT current_database(), current_schema()").fetchone()
    database = str((row or ("", ""))[0] or "").lower()
    schema = str((row or ("", ""))[1] or "")
    return {"database": database, "schema": schema}


def _ready_participant(
    database: str,
    schema: str,
    run_marker: str,
) -> ParticipantScope:
    return {
        "ready": True,
        "database": database,
        "schema": schema,
        "runMarker": run_marker,
    }


def _valid_heartbeat_string(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > _MAX_HEARTBEAT_IDENTITY_LENGTH:
        return None
    return value


def _heartbeat_matches(
    raw_payload: object,
    *,
    database: str,
    schema: str,
    run_marker: str,
) -> bool:
    if not isinstance(raw_payload, Mapping):
        return False
    heartbeat_database = _valid_heartbeat_string(raw_payload.get("database"))
    heartbeat_schema = _valid_heartbeat_string(raw_payload.get("schema"))
    heartbeat_run_marker = _valid_heartbeat_string(raw_payload.get("runMarker"))
    return bool(
        heartbeat_database
        and heartbeat_schema
        and heartbeat_run_marker
        and heartbeat_database.lower() == database
        and heartbeat_schema == schema
        and heartbeat_run_marker == run_marker
    )


def _cache_key(dsn: str, run_marker: str) -> str:
    digest = sha256()
    digest.update(dsn.encode("utf-8", errors="surrogatepass"))
    digest.update(b"\0")
    digest.update(run_marker.encode("utf-8", errors="surrogatepass"))
    return digest.hexdigest()


def _cached_scope(key: str, now: float) -> RuntimeDatabaseScope | None:
    entry = _SCOPE_CACHE.get(key)
    if entry is None:
        return None
    if now >= entry.expires_at:
        _SCOPE_CACHE.pop(key, None)
        return None
    _SCOPE_CACHE.move_to_end(key)
    return deepcopy(entry.scope)


def _probe_runtime_database_scope(dsn: str, run_marker: str) -> _ProbeResult:
    try:
        import psycopg

        kwargs = postgres_connection_kwargs(dsn)
        with psycopg.connect(dsn, **kwargs) as connection:
            api_identity = postgres_connection_identity(connection)
            database = api_identity["database"]
            schema = api_identity["schema"]
            expected_complete = bool(database and schema and run_marker)
            api_participant = (
                _ready_participant(database, schema, run_marker)
                if expected_complete
                else _empty_participant()
            )
            scope: RuntimeDatabaseScope = {
                "engine": "postgresql",
                "database": database,
                "schema": schema,
                "runMarker": run_marker,
                "participants": {
                    "api": api_participant,
                    "processingWorker": _empty_participant(),
                    "reviewWorker": _empty_participant(),
                },
            }
            max_age = _heartbeat_max_age_seconds()
            try:
                heartbeat_observed_at = _monotonic()
                rows = connection.execute(
                    """
                    SELECT service_role,
                           payload,
                           last_seen_at >= now() - (%s * interval '1 second') AS fresh,
                           GREATEST(
                               0,
                               %s - EXTRACT(EPOCH FROM (now() - last_seen_at))
                           ) AS freshness_remaining_seconds
                    FROM service_heartbeats
                    WHERE service_role = ANY(%s)
                    ORDER BY service_role, last_seen_at DESC, service_id
                    """,
                    (max_age, max_age, list(_WORKER_ROLES)),
                ).fetchall()
            except Exception:
                connection.rollback()
                return _ProbeResult(scope)
            connection.rollback()
    except Exception:
        return _ProbeResult(_empty_scope())

    fresh_payloads: dict[str, list[object]] = {role: [] for role in _WORKER_ROLES}
    freshness_remaining: list[float] = []
    for row in rows:
        if len(row) < 4:
            continue
        role, payload, fresh, remaining = row[:4]
        if role not in fresh_payloads or not bool(fresh):
            continue
        fresh_payloads[role].append(payload)
        try:
            freshness_remaining.append(max(0.0, float(remaining)))
        except (TypeError, ValueError):
            freshness_remaining.append(0.0)

    for role, payloads in fresh_payloads.items():
        matches = bool(
            expected_complete
            and payloads
            and all(
                _heartbeat_matches(
                    payload,
                    database=database,
                    schema=schema,
                    run_marker=run_marker,
                )
                for payload in payloads
            )
        )
        participant_name = _PARTICIPANT_ROLES[role]
        scope["participants"][participant_name] = (
            _ready_participant(database, schema, run_marker)
            if matches
            else _empty_participant()
        )
    return _ProbeResult(
        scope,
        heartbeat_observed_at + min(freshness_remaining)
        if freshness_remaining
        else None,
    )


def runtime_database_scope(dsn: str | None = None) -> RuntimeDatabaseScope:
    """Return the current cached public scope without performing database I/O."""
    configured_dsn = dsn or os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not configured_dsn:
        return _empty_scope()
    key = _cache_key(configured_dsn, os.getenv("AICHECK_E2E_RUN_MARKER", ""))
    with _CACHE_CONDITION:
        return _cached_scope(key, _monotonic()) or _empty_scope()


def refresh_runtime_database_scope(dsn: str | None = None) -> RuntimeDatabaseScope:
    """Coalesce a bounded PostgreSQL probe and refresh the process-local public snapshot."""
    configured_dsn = dsn or os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not configured_dsn:
        return _empty_scope()
    run_marker = os.getenv("AICHECK_E2E_RUN_MARKER", "")
    key = _cache_key(configured_dsn, run_marker)
    with _CACHE_CONDITION:
        cached = _cached_scope(key, _monotonic())
        if cached is not None:
            return cached
        if key in _REFRESHING_KEYS:
            _CACHE_CONDITION.wait(timeout=_probe_timeout_seconds() + 0.25)
            return _cached_scope(key, _monotonic()) or _empty_scope()
        _REFRESHING_KEYS.add(key)

    try:
        probe = _probe_runtime_database_scope(configured_dsn, run_marker)
        expires_at = _monotonic() + _cache_ttl_seconds()
        if probe.freshness_deadline is not None:
            expires_at = min(expires_at, probe.freshness_deadline)
        entry = _CacheEntry(deepcopy(probe.scope), expires_at)
        with _CACHE_CONDITION:
            _SCOPE_CACHE[key] = entry
            _SCOPE_CACHE.move_to_end(key)
            while len(_SCOPE_CACHE) > _MAX_CACHE_ENTRIES:
                _SCOPE_CACHE.popitem(last=False)
        return deepcopy(probe.scope)
    finally:
        with _CACHE_CONDITION:
            _REFRESHING_KEYS.discard(key)
            _CACHE_CONDITION.notify_all()
