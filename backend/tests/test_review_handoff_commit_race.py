"""结果提交与来源变动同时发生时的事务边界。

执行前有一道来源校验闸（execution 调 ensure_live_document_sources），但它读的是
另一条连接的只读事务，写结果又是后面另一次事务——两者之间存在窗口：闸通过之后、
结果落库之前，上游交接来源可能被别的程序改掉。

写入侧的乐观锁（assert_persistence_baseline）只比对**被写的那一行**的基线。
上游交接是另一行，改它不会让审查运行这一行的基线失配，于是依据已经过时的结果
仍会作为最新结果保存下来。这一组用例把这个边界钉住。
"""
from copy import deepcopy

import psycopg
import pytest

from libs.db.repository import InMemoryRepository
from libs.review_handoff_inputs import freeze_handoff_inputs
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id
from scripts.migrate_backend import apply_migrations

pytest_plugins = ["test_review_handoff_inputs"]

RESULT_FIELDS = {
    "status": "waiting_human_review",
    "currentStep": "waiting_human_review",
    "findingDrafts": [{"id": "F-1", "title": "依据已过时的结论"}],
    "outputHash": "STALE-OUTPUT",
}


def _seed(isolated_postgres_url, inputs):
    """把一条带交接快照的审查运行写进隔离库，返回 (writer, worker, 运行, 交接 id)。

    租户上下文必须在写入之前设好——仓库禁止跨租户持久化。
    """
    state, run, selection = inputs
    run["handoffInputsSnapshot"] = freeze_handoff_inputs(run, state, selection)
    apply_migrations(isolated_postgres_url)
    writer, worker = InMemoryRepository(seed=False), InMemoryRepository(seed=False)
    writer.configure_sync_postgres(isolated_postgres_url)
    writer.upsert_state_records_to_sync_postgres(state)
    worker.configure_sync_postgres(isolated_postgres_url)
    worker.load_review_run_scope_from_sync_postgres("NEXT")
    loaded = worker.find_one("review_runs", "NEXT", id_field="reviewRunId")
    return writer, worker, loaded, state["review_handoffs"][0]["id"]


def _append_foreign_verification(dsn, handoff_id):
    """模拟另一个程序在闸通过之后追加一次核验——上游来源就此变化。"""
    with psycopg.connect(dsn) as other:
        row = other.execute(
            "SELECT payload FROM aicheck_state WHERE tenant_id = %s AND collection = 'review_handoffs' AND object_id = %s",
            ("T", handoff_id),
        ).fetchone()
        payload = deepcopy(row[0])
        history = list(payload.get("verifications") or [])
        history.append({**deepcopy(history[-1]), "id": "VERIFICATION-FOREIGN", "note": "另一个程序追加的核验"})
        payload["verifications"] = history
        other.execute(
            "UPDATE aicheck_state SET payload = %s WHERE tenant_id = %s AND collection = 'review_handoffs' AND object_id = %s",
            (psycopg.types.json.Json(payload), "T", handoff_id),
        )
        other.commit()


def _stored_run(dsn, run_id="NEXT"):
    with psycopg.connect(dsn) as reader:
        row = reader.execute(
            "SELECT payload FROM aicheck_state WHERE tenant_id = %s AND collection = 'review_runs' AND object_id = %s",
            ("T", run_id),
        ).fetchone()
    return row[0] if row else None


def test_result_commit_is_refused_when_upstream_changed_after_the_gate(isolated_postgres_url, inputs):
    """闸通过之后来源变了：结果不能作为最新结果保存。"""
    token = set_request_tenant_id("T")
    writer = worker = None
    try:
        writer, worker, run, handoff_id = _seed(isolated_postgres_url, inputs)
        from libs.review_live_sources import ensure_live_document_sources

        # 1) 执行前的闸：此刻来源仍然一致，闸放行。
        ensure_live_document_sources(run, worker.state, repository=worker)

        # 2) 闸之后、落库之前，另一个程序改掉上游交接。
        _append_foreign_verification(isolated_postgres_url, handoff_id)

        # 3) 本程序把依据已过时的结果写下去。
        before = _stored_run(isolated_postgres_url)
        run.update(deepcopy(RESULT_FIELDS))
        with pytest.raises(Exception) as failure:
            worker.flush_to_sync_postgres(selected_state_keys={"review_runs"})

        message = str(getattr(failure.value, "reason", "") or failure.value)
        assert "HANDOFF" in message.upper() or "handoff" in message, f"应给出来源变动的原因，实际：{message}"

        # 4) 库里那条不能被过时结论覆盖。
        stored = _stored_run(isolated_postgres_url)
        assert stored["status"] == before["status"], "来源已变，结果不该作为最新结果落库"
        assert stored.get("outputHash") != "STALE-OUTPUT"
        assert not stored.get("findingDrafts")
    finally:
        reset_request_tenant_id(token)
        for repository in (writer, worker):
            if repository is not None and repository.sync_postgres:
                repository.sync_postgres.close()


def test_result_commit_succeeds_when_upstream_is_unchanged(isolated_postgres_url, inputs):
    """来源没变时照常提交——守卫不能把正常提交也挡掉。"""
    token = set_request_tenant_id("T")
    writer = worker = None
    try:
        writer, worker, run, _handoff_id = _seed(isolated_postgres_url, inputs)
        from libs.review_live_sources import ensure_live_document_sources

        ensure_live_document_sources(run, worker.state, repository=worker)
        run.update(deepcopy(RESULT_FIELDS))
        worker.flush_to_sync_postgres(selected_state_keys={"review_runs"})

        stored = _stored_run(isolated_postgres_url)
        assert stored["status"] == "waiting_human_review"
        assert stored["outputHash"] == "STALE-OUTPUT"
    finally:
        reset_request_tenant_id(token)
        for repository in (writer, worker):
            if repository is not None and repository.sync_postgres:
                repository.sync_postgres.close()


def test_runs_without_handoff_inputs_are_not_gated(isolated_postgres_url, inputs):
    """没有交接依赖的运行不该被这道守卫影响，也不该为它多查一次库。"""
    token = set_request_tenant_id("T")
    writer = worker = None
    try:
        writer, worker, run, _handoff_id = _seed(isolated_postgres_url, inputs)
        run.pop("handoffInputsSnapshot", None)
        run.update(deepcopy(RESULT_FIELDS))
        worker.flush_to_sync_postgres(selected_state_keys={"review_runs"})
        assert _stored_run(isolated_postgres_url)["outputHash"] == "STALE-OUTPUT"
    finally:
        reset_request_tenant_id(token)
        for repository in (writer, worker):
            if repository is not None and repository.sync_postgres:
                repository.sync_postgres.close()
