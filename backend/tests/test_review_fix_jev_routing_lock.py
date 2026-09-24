"""路由任务的锁连接空闲超时要盖过最坏的 Jev 串行请求耗时，否则锁会在任务仍在跑时被放掉。"""
from __future__ import annotations

import inspect
import re
import sys
from types import SimpleNamespace

from apps.worker import tasks
from libs import jev_document_routing as routing
from libs.review_orchestrator import jev_client


def _worst_case_seconds() -> float:
    timeout = inspect.signature(jev_client.ask_jev).parameters["timeout"].default
    attempts = len(jev_client.RETRY_DELAYS_SECONDS) + 1
    per_batch = timeout * attempts + sum(jev_client.RETRY_DELAYS_SECONDS)
    return routing.MAX_ROUTING_BATCHES * per_batch


def test_budget_matches_the_client_retry_and_timeout_constants():
    assert routing.JEV_REQUEST_TIMEOUT_SECONDS == (
        inspect.signature(jev_client.ask_jev).parameters["timeout"].default)
    assert routing.ROUTING_REQUEST_BUDGET_SECONDS == _worst_case_seconds() == 520


def test_routing_task_lock_outlives_the_worst_case_request_budget(monkeypatch):
    commands = []

    class Connection:
        def execute(self, command, *_args):
            commands.append(command)
            return SimpleNamespace(fetchone=lambda: [True])

        def close(self):
            pass

    monkeypatch.setenv("AICHECK_DATABASE_URL", "postgresql://test")
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(
        connect=lambda *_args, **_kwargs: Connection(), Error=Exception,
    ))
    monkeypatch.setattr(tasks, "jev_stage_enabled", lambda _: False)
    assert tasks.classify_document_node_jev_shadow("P", "D", "V", tenant_id="T")["status"] == "disabled"

    timeouts = [int(match.group(1)) for command in commands
                if (match := re.fullmatch(r"SET idle_session_timeout = '(\d+)s'", str(command)))]
    # pipeline_lock 会把超时夹到 600 秒以内；这里看的是实际下发给 PostgreSQL 的值。
    assert timeouts and timeouts[0] > _worst_case_seconds()
