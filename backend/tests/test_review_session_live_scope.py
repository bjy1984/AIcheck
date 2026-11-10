"""会话级 live read：轮询事件只读这个会话相关的行，不再整表重载（2026-09-25）。

整表重载 review_runs（77 MB）/ review_events（51 MB）单次 12.6 秒，节点页要等它。
"""
from __future__ import annotations

from libs.db.repository import InMemoryRepository
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id
from scripts.migrate_backend import apply_migrations


def _state() -> dict:
    session = {"id": "S1", "projectId": "P", "nodeId": 68, "status": "active", "tenantId": "T"}
    other_session = {"id": "S2", "projectId": "P", "nodeId": 47, "status": "active", "tenantId": "T"}
    return {
        "review_sessions": [session, other_session],
        "review_session_events": [
            {"id": "E1", "sessionId": "S1", "sequence": 1, "tenantId": "T"},
            {"id": "E2", "sessionId": "S2", "sequence": 1, "tenantId": "T"},
        ],
        "review_messages": [{"id": "M1", "sessionId": "S1", "tenantId": "T"}],
        "agent_executions": [{"id": "A1", "sessionId": "S1", "tenantId": "T"}],
        "review_runs": [
            {"id": "R68", "reviewRunId": "R68", "projectId": "P", "nodeId": 68, "tenantId": "T"},
            {"id": "R47", "reviewRunId": "R47", "projectId": "P", "nodeId": 47, "tenantId": "T"},
            {"id": "ROTHER", "reviewRunId": "ROTHER", "projectId": "Q", "nodeId": 68, "tenantId": "T"},
        ],
        "review_events": [
            {"id": "V68", "reviewRunId": "R68", "tenantId": "T"},
            {"id": "V47", "reviewRunId": "R47", "tenantId": "T"},
        ],
    }


def _ids(repo: InMemoryRepository, key: str) -> set[str]:
    return {str(item.get("id")) for item in repo.state.get(key, [])}


def test_session_scope_reads_only_the_session_and_its_node_runs(isolated_postgres_url) -> None:
    apply_migrations(isolated_postgres_url)
    writer, reader = InMemoryRepository(seed=False), InMemoryRepository(seed=False)
    token = set_request_tenant_id("T")
    try:
        writer.configure_sync_postgres(isolated_postgres_url)
        reader.configure_sync_postgres(isolated_postgres_url)
        writer.upsert_state_records_to_sync_postgres(_state())

        reader.load_review_session_scope_from_sync_postgres("S1")

        assert _ids(reader, "review_sessions") == {"S1"}
        assert _ids(reader, "review_session_events") == {"E1"}
        assert _ids(reader, "review_messages") == {"M1"}
        assert _ids(reader, "agent_executions") == {"A1"}
        assert _ids(reader, "review_runs") == {"R68"}, "别的节点、别的项目的运行不读"
        assert _ids(reader, "review_events") == {"V68"}

        # 另一个进程追加的事件，下一次刷新就看得到
        writer.state["review_session_events"].append({"id": "E3", "sessionId": "S1", "sequence": 2, "tenantId": "T"})
        writer.upsert_state_records_to_sync_postgres({"review_session_events": writer.state["review_session_events"]})
        reader.load_review_session_scope_from_sync_postgres("S1")
        assert _ids(reader, "review_session_events") == {"E1", "E3"}
    finally:
        reset_request_tenant_id(token)


def test_a_pinned_record_is_not_overwritten_by_the_session_scope(isolated_postgres_url) -> None:
    apply_migrations(isolated_postgres_url)
    writer, reader = InMemoryRepository(seed=False), InMemoryRepository(seed=False)
    token = set_request_tenant_id("T")
    try:
        writer.configure_sync_postgres(isolated_postgres_url)
        reader.configure_sync_postgres(isolated_postgres_url)
        writer.upsert_state_records_to_sync_postgres(_state())
        reader.load_review_session_scope_from_sync_postgres("S1")
        session = reader.find_one("review_sessions", "S1")
        session["activeReviewRunId"] = "R68"
        reader.pin_object("review_sessions", "S1")
        try:
            reader.load_review_session_scope_from_sync_postgres("S1")
            assert reader.find_one("review_sessions", "S1")["activeReviewRunId"] == "R68"
        finally:
            reader.unpin_object("review_sessions", "S1")
    finally:
        reset_request_tenant_id(token)


def test_message_only_scope_skips_runs_and_run_events(isolated_postgres_url) -> None:
    """只看消息的轮询（回答落定前每 0.8 秒一次）不该连带重读整个节点的运行。"""
    apply_migrations(isolated_postgres_url)
    writer, reader = InMemoryRepository(seed=False), InMemoryRepository(seed=False)
    token = set_request_tenant_id("T")
    try:
        writer.configure_sync_postgres(isolated_postgres_url)
        reader.configure_sync_postgres(isolated_postgres_url)
        writer.upsert_state_records_to_sync_postgres(_state())

        reader.load_review_session_scope_from_sync_postgres("S1", include_runs=False)

        assert _ids(reader, "review_sessions") == {"S1"}
        assert _ids(reader, "review_messages") == {"M1"}
        assert _ids(reader, "agent_executions") == {"A1"}
        assert _ids(reader, "review_runs") == set()
        assert _ids(reader, "review_events") == set()
    finally:
        reset_request_tenant_id(token)


def test_run_events_already_in_memory_are_not_read_again(isolated_postgres_url) -> None:
    """运行事件只追加不改：内存里有的不再从库里重读，新追加的照样读到。"""
    apply_migrations(isolated_postgres_url)
    writer, reader = InMemoryRepository(seed=False), InMemoryRepository(seed=False)
    token = set_request_tenant_id("T")
    try:
        writer.configure_sync_postgres(isolated_postgres_url)
        reader.configure_sync_postgres(isolated_postgres_url)
        writer.upsert_state_records_to_sync_postgres(_state())
        reader.load_review_session_scope_from_sync_postgres("S1")
        assert _ids(reader, "review_events") == {"V68"}

        # 库里那条被改了（真实代码里不会发生）：内存里已有，就不再读它
        writer.upsert_state_records_to_sync_postgres(
            {"review_events": [{"id": "V68", "reviewRunId": "R68", "tenantId": "T", "title": "改过"}]}
        )
        # 同一次运行新追加的事件照样读到
        writer.upsert_state_records_to_sync_postgres(
            {"review_events": [{"id": "V68B", "reviewRunId": "R68", "tenantId": "T"}]}
        )
        reader.load_review_session_scope_from_sync_postgres("S1")

        assert _ids(reader, "review_events") == {"V68", "V68B"}
        assert "title" not in reader.find_one("review_events", "V68")
    finally:
        reset_request_tenant_id(token)
