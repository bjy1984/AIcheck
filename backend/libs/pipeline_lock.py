from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any


class PipelineLockUnavailable(RuntimeError):
    pass


_LOCAL_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[int, threading.Lock] = {}


def advisory_lock_id(key: str) -> int:
    raw = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big", signed=False)
    return raw - (1 << 64) if raw >= (1 << 63) else raw


def _strict_production() -> bool:
    return str(os.getenv("AICHECK_STRICT_PRODUCTION") or "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@contextmanager
def pipeline_lock(key: str) -> Iterator[bool]:
    database_url = str(os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if database_url.startswith(("postgresql://", "postgres://")):
        try:
            import psycopg

            connection = psycopg.connect(database_url, autocommit=True)
            acquired = bool(connection.execute("SELECT pg_try_advisory_lock(%s)", (advisory_lock_id(key),)).fetchone()[0])
        except Exception as exc:
            if _strict_production():
                raise PipelineLockUnavailable("PostgreSQL pipeline lock is unavailable") from exc
            with _local_pipeline_lock(key) as local_acquired:
                yield local_acquired
            return
        try:
            yield acquired
        finally:
            try:
                if acquired:
                    connection.execute("SELECT pg_advisory_unlock(%s)", (advisory_lock_id(key),))
            except Exception:
                pass
            finally:
                try:
                    connection.close()
                except Exception:
                    pass
        return
    if _strict_production():
        raise PipelineLockUnavailable("PostgreSQL is required for strict pipeline locking")
    with _local_pipeline_lock(key) as acquired:
        yield acquired


@contextmanager
def _local_pipeline_lock(key: str) -> Iterator[bool]:
    lock_id = advisory_lock_id(key)
    with _LOCAL_GUARD:
        lock = _LOCAL_LOCKS.setdefault(lock_id, threading.Lock())
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


def pipeline_task_lock(scope: str, key_builder: Callable[..., str]):
    def decorator(function: Callable[..., dict[str, Any]]):
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
            key = f"aicheck:{scope}:{key_builder(*args, **kwargs)}"
            try:
                with pipeline_lock(key) as acquired:
                    if not acquired:
                        return {
                            "status": "duplicate_inflight",
                            "idempotencyLock": key,
                        }
                    return function(*args, **kwargs)
            except PipelineLockUnavailable as exc:
                task = args[0] if args else None
                retry = getattr(task, "retry", None)
                request = getattr(task, "request", None)
                retries = int(getattr(request, "retries", 0) or 0)
                max_retries = int(getattr(task, "max_retries", 3) or 3)
                if callable(retry) and retries < max_retries:
                    countdowns = (10, 30, 90)
                    raise retry(exc=exc, countdown=countdowns[min(retries, len(countdowns) - 1)])
                raise

        return wrapped

    return decorator
