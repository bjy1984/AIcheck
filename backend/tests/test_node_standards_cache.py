"""节点依据检索的缓存（节点切换卡顿）。

线上实测：/inspection/nodes/{id}/standards 端到端 6.0 秒，而它只返回 5 条、
5.4KB。慢在 retrieve_knowledge_clauses——每点一次节点就对全部知识条款
（线上 7416 条）做一遍词法打分，单次约 3 秒。

这个开销是纯浪费：查询串由节点规则拼成，候选集是知识库，两者都不随请求变化，
同一个节点每次都会算出同样的结果。
"""

from __future__ import annotations

from typing import Any

from apps.api import routes
from libs.db.repository import repo


def _reset_cache() -> None:
    routes._NODE_STANDARD_RETRIEVAL_CACHE.clear()


def test_identical_requests_hit_the_cache_instead_of_re_retrieving(monkeypatch) -> None:
    _reset_cache()
    calls: list[dict[str, Any]] = []

    def _fake_retrieve(state, **kwargs):
        calls.append(kwargs)
        return {"trace": {"selectedClauses": [{"clauseId": "C-1", "clauseNo": "3.2"}]}}

    monkeypatch.setattr(routes, "retrieve_knowledge_clauses", _fake_retrieve)

    first = routes.cached_node_standard_retrieval(
        business_pack_id="engineering_inspection_v1", node_id=24, query="焊工资格证"
    )
    second = routes.cached_node_standard_retrieval(
        business_pack_id="engineering_inspection_v1", node_id=24, query="焊工资格证"
    )
    assert first == second
    assert len(calls) == 1, f"第二次应命中缓存，实际又检索了 {len(calls)} 次"


def test_cache_is_keyed_by_node_and_business_pack(monkeypatch) -> None:
    """不同节点/不同业务包必须各算各的，不能互相串。"""
    _reset_cache()
    calls: list[dict[str, Any]] = []

    def _fake_retrieve(state, **kwargs):
        calls.append(kwargs)
        return {"trace": {"selectedClauses": [{"clauseId": f"C-{kwargs['node_id']}"}]}}

    monkeypatch.setattr(routes, "retrieve_knowledge_clauses", _fake_retrieve)

    a = routes.cached_node_standard_retrieval(business_pack_id="pack-a", node_id=24, query="q")
    b = routes.cached_node_standard_retrieval(business_pack_id="pack-a", node_id=25, query="q")
    c = routes.cached_node_standard_retrieval(business_pack_id="pack-b", node_id=24, query="q")
    assert len(calls) == 3, "三种键组合必须各检索一次，不能互相命中"
    assert a != b, "不同节点的结果不该相同"
    assert {call["node_id"] for call in calls} == {24, 25}
    assert {call["business_pack_id"] for call in calls} == {"pack-a", "pack-b"}
    assert c is not None


def test_cache_invalidates_when_the_knowledge_base_changes(monkeypatch) -> None:
    """知识库变了就得重算，否则会一直返回旧依据。

    指纹用「条款数 + 最新 updatedAt」：只看条数会漏掉「改内容不增删」的情况。
    """
    _reset_cache()
    calls: list[dict[str, Any]] = []

    def _fake_retrieve(state, **kwargs):
        calls.append(kwargs)
        return {"trace": {"selectedClauses": []}}

    monkeypatch.setattr(routes, "retrieve_knowledge_clauses", _fake_retrieve)

    signatures = iter(["10:2026-01-01", "10:2026-01-01", "10:2026-06-30"])
    monkeypatch.setattr(routes, "knowledge_base_signature", lambda: next(signatures))

    routes.cached_node_standard_retrieval(business_pack_id="p", node_id=24, query="q")
    routes.cached_node_standard_retrieval(business_pack_id="p", node_id=24, query="q")
    assert len(calls) == 1, "指纹未变时不该重算"
    routes.cached_node_standard_retrieval(business_pack_id="p", node_id=24, query="q")
    assert len(calls) == 2, "指纹变了必须重算"


def test_signature_reflects_content_edits_not_only_count() -> None:
    """同样条数、内容更新时间不同，指纹必须不同。"""
    original = repo.state.get("knowledge_clauses")
    try:
        repo.state["knowledge_clauses"] = [{"id": "K1", "updatedAt": "2026-01-01 00:00:00"}]
        before = routes.knowledge_base_signature()
        repo.state["knowledge_clauses"] = [{"id": "K1", "updatedAt": "2026-06-30 00:00:00"}]
        after = routes.knowledge_base_signature()
        assert before != after, "内容更新时间变化必须改变指纹"
    finally:
        repo.state["knowledge_clauses"] = original


def test_cached_payload_is_cloned_so_callers_cannot_corrupt_it(monkeypatch) -> None:
    """返回的是副本——调用方给条目加字段，不能污染下一次命中。"""
    _reset_cache()
    monkeypatch.setattr(
        routes,
        "retrieve_knowledge_clauses",
        lambda state, **kwargs: {"trace": {"selectedClauses": [{"clauseId": "C-1"}]}},
    )
    first = routes.cached_node_standard_retrieval(business_pack_id="p", node_id=24, query="q")
    first[0]["injected"] = True
    second = routes.cached_node_standard_retrieval(business_pack_id="p", node_id=24, query="q")
    assert "injected" not in second[0], "缓存被调用方改坏了"
