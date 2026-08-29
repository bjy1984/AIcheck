"""延迟加载重集合（性能：冷启动 19.5s / 293MB → 目标砍掉 63%）。

knowledge_vectors(113MB) + knowledge_page_index_nodes(73MB) 占冷启动体积的
63%，而它们的所有使用点都是「按 fileId 过滤」或「取 len」——没有常驻场景。

三条不可退让的约束：
1. 跳过 ≠ 空集合：跳过的集合不记水位线，collection_is_loaded 为假，
   调用方能区分「没加载」和「库里没有」；
2. 补拉只填目标集合，**绝不重建整份 state**——请求中途重建会让落库基线
   失配，下一次写入直接 409（第一版实测如此）；
3. 每个消费路径必须显式声明依赖，漏了就是静默少召回。
"""

from __future__ import annotations

import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_default_deferred_keys_are_the_two_bulk_collections() -> None:
    from libs.db.repository import STATE_COLLECTIONS, deferred_bulk_state_keys

    keys = deferred_bulk_state_keys()
    assert keys == {"knowledge_vectors", "knowledge_page_index_nodes"}
    assert all(key in STATE_COLLECTIONS for key in keys)


def test_deferral_can_be_disabled_and_overridden(monkeypatch) -> None:
    from libs.db.repository import deferred_bulk_collections, deferred_bulk_state_keys

    monkeypatch.setenv("AICHECK_DEFERRED_BULK_STATE_KEYS", "")
    assert deferred_bulk_state_keys() == set()
    assert deferred_bulk_collections() == set()  # 空 = 回到旧行为（全量加载）

    monkeypatch.setenv("AICHECK_DEFERRED_BULK_STATE_KEYS", "knowledge_vectors")
    assert deferred_bulk_state_keys() == {"knowledge_vectors"}

    # 未知 key 被忽略，不会让 SQL 拿到不存在的表名
    monkeypatch.setenv("AICHECK_DEFERRED_BULK_STATE_KEYS", "knowledge_vectors,not_a_collection")
    assert deferred_bulk_state_keys() == {"knowledge_vectors"}


def test_ensure_collections_loaded_never_rebuilds_whole_state(monkeypatch) -> None:
    """补拉必须走就地合并，不得调用 load_state——那会换掉整份 state，
    请求中途调用直接导致落库 409。"""
    from libs.db import repository

    calls = {"merge": [], "full": 0}
    monkeypatch.setattr(
        repository.repo, "collection_is_loaded", lambda key, tenant_id=None: False
    )
    monkeypatch.setattr(
        repository.repo,
        "load_collections_into_state",
        lambda keys, tenant_id=None: calls["merge"].append(sorted(keys)),
    )
    monkeypatch.setattr(
        repository, "load_state", lambda *a, **k: calls.__setitem__("full", calls["full"] + 1)
    )

    repository.ensure_collections_loaded("knowledge_vectors", "knowledge_page_index_nodes")
    assert calls["merge"] == [["knowledge_page_index_nodes", "knowledge_vectors"]]
    assert calls["full"] == 0  # 绝不整份重建


def test_already_loaded_collections_are_not_refetched(monkeypatch) -> None:
    from libs.db import repository

    merged = []
    monkeypatch.setattr(
        repository.repo, "collection_is_loaded", lambda key, tenant_id=None: True
    )
    monkeypatch.setattr(
        repository.repo, "load_collections_into_state", lambda keys, tenant_id=None: merged.append(keys)
    )
    repository.ensure_collections_loaded("knowledge_vectors")
    assert merged == []  # 已加载不再查库


def test_every_consumer_declares_its_dependency() -> None:
    """漏声明的后果是静默少召回，不会报错——那种缺陷最难发现。
    所有读延迟集合的函数都必须先 ensure_collections_loaded。"""
    for relative in (
        "apps/api/routes.py",
        "apps/api/knowledge_admin_routes.py",
    ):
        source = (BACKEND_ROOT / relative).read_text(encoding="utf-8")
        consumers = source.count('repo.state.get("knowledge_vectors"') + source.count(
            'repo.state.get("knowledge_page_index_nodes"'
        )
        # 两种声明形式都算：@requires_collections 装饰器（首选，前置条件写在
        # 签名上不会被重构误删）或函数体内直接 ensure_collections_loaded
        declarations = source.count("@requires_collections(") + source.count(
            "ensure_collections_loaded("
        )
        assert consumers == 0 or declarations >= 1, f"{relative}: {consumers} 个消费点但零声明"

    # 检索入口自带兜底：调用点分散，逐个注入不可靠
    retrieval = (BACKEND_ROOT / "libs" / "knowledge_retrieval.py").read_text(encoding="utf-8")
    assert "_ensure_retrieval_collections" in retrieval
    assert "state is not repo.state" in retrieval  # 字面量 state 不触发库访问
