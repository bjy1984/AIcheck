"""审查会话按会话编号的索引（apps/api/review_session_index.py）与工具记忆核院编号。"""

from __future__ import annotations

import pytest

from apps.api import review_session_index as index
from apps.api import routes as routes_module
from libs.db.repository import repo


@pytest.fixture(autouse=True)
def _fresh_state():
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    routes_module.ensure_review_session_state()
    yield


class CountingRow(dict):
    """记下 sessionId 被读了几次：用来证明第二次查询不再扫整表。"""

    reads = 0

    def get(self, key, default=None):
        if key == "sessionId":
            CountingRow.reads += 1
        return super().get(key, default)


def message(session_id: str, sequence: int, **extra) -> dict:
    return {"id": f"M-{session_id}-{sequence}", "sessionId": session_id, "sequence": sequence, **extra}


def test_rows_are_grouped_by_session_and_keep_append_order() -> None:
    repo.state["review_messages"].extend(
        [message("S1", 1), message("S2", 1), message("S1", 2), message("S2", 2), message("S1", 3)]
    )
    assert [row["sequence"] for row in index.session_rows("review_messages", "S1")] == [1, 2, 3]
    assert [row["id"] for row in index.session_rows("review_messages", "S2")] == ["M-S2-1", "M-S2-2"]
    assert index.session_rows("review_messages", "S-NONE") == []
    assert index.next_sequence("review_messages", "S1") == 4
    assert index.next_sequence("review_messages", "S-NONE") == 1
    # 返回的是 state 里同一批 dict：原地改状态、序号立刻可见
    repo.state["review_messages"][0]["status"] = "completed"
    assert index.session_rows("review_messages", "S1")[0]["status"] == "completed"


def test_appended_rows_are_indexed_without_rescanning_the_collection() -> None:
    CountingRow.reads = 0
    repo.state["review_messages"].extend(CountingRow(message(f"S{i % 50}", i)) for i in range(1000))
    index.session_rows("review_messages", "S1")
    first_build = CountingRow.reads
    assert first_build == 1000

    repo.state["review_messages"].append(CountingRow(message("S1", 5000)))
    rows = index.session_rows("review_messages", "S1")
    assert rows[-1]["sequence"] == 5000
    assert CountingRow.reads - first_build == 1  # 只读了新追加的那一条

    index.session_rows("review_messages", "S2")
    assert CountingRow.reads - first_build == 1  # 没变化时一条都不读


def test_index_rebuilds_when_the_list_is_replaced_or_rows_are_swapped_in_place() -> None:
    repo.state["review_messages"].extend([message("S1", 1), message("S1", 2)])
    assert len(index.session_rows("review_messages", "S1")) == 2

    # 从 Postgres 刷新：state 换成新列表
    repo.state["review_messages"] = [message("S1", 1), message("S1", 2), message("S1", 3, refreshed=True)]
    rows = index.session_rows("review_messages", "S1")
    assert [row["sequence"] for row in rows] == [1, 2, 3] and rows[-1]["refreshed"]

    # 有人原位替换了最后一条（目前代码里没有，防御）
    repo.state["review_messages"][-1] = message("S9", 3)
    assert [row["sequence"] for row in index.session_rows("review_messages", "S1")] == [1, 2]
    assert len(index.session_rows("review_messages", "S9")) == 1

    # 列表变短（同样不该发生）也整体重建
    repo.state["review_messages"].pop()
    assert index.session_rows("review_messages", "S9") == []


def test_events_use_the_same_index_and_unindexed_collections_fall_back_to_scan() -> None:
    repo.state["review_session_events"].extend([message("S1", 1), message("S2", 1), message("S1", 2)])
    assert index.next_sequence("review_session_events", "S1") == 3
    assert routes_module.next_review_session_sequence("review_session_events", "S2") == 2
    repo.state["agent_executions"].append({"id": "X", "sessionId": "S1"})
    assert index.session_rows("agent_executions", "S1") == [{"id": "X", "sessionId": "S1"}]


def test_tool_memory_entries_carry_and_check_the_institute() -> None:
    session = {"id": "RSESSION-T1", "tenantId": "TENANT-A", "toolMemoryRevision": 0}
    routes_module.store_review_session_tool_memory(
        session, signature="sig-1", tool_name="get_fixed_basis", summary="依据 3 条", output={"ok": True}
    )
    entry = repo.state["review_session_tool_memory"][0]
    assert entry["tenantId"] == "TENANT-A"
    assert set(routes_module.load_review_session_tool_memory(session)) == {"sig-1"}

    # 同一会话编号、别的院：拿不到
    other_institute = {**session, "tenantId": "TENANT-B"}
    assert routes_module.load_review_session_tool_memory(other_institute) == {}
    # 别的院写同一签名，不会改到 A 院那条
    routes_module.store_review_session_tool_memory(
        other_institute, signature="sig-1", tool_name="get_fixed_basis", summary="B 院", output={}
    )
    a_entry = next(item for item in repo.state["review_session_tool_memory"] if item["tenantId"] == "TENANT-A")
    assert a_entry["summary"] == "依据 3 条"

    # 改造前没带院编号的老条目算没命中
    repo.state["review_session_tool_memory"].append(
        {"id": "RTMEM-OLD", "sessionId": "RSESSION-T1", "memoryRevision": 0, "signature": "sig-old", "summary": "老"}
    )
    assert "sig-old" not in routes_module.load_review_session_tool_memory(session)
