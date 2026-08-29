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


def test_full_load_must_not_mark_deferred_collections_as_loaded() -> None:
    """全量加载后「所有集合标记已加载」的兜底逻辑必须排除延迟集合。

    上线前实测踩到：延迟集合被标成 collection_is_loaded=True →
    ensure_collections_loaded 直接跳过补拉 → 内存永远 0 行。
    那不是性能问题，是**静默的数据缺失**：调用方拿到空列表当成「库里没有」。

    这条用源码钉不变量（真实加载要连库，单测环境没有）。
    """
    source = (BACKEND_ROOT / "libs" / "db" / "repository.py").read_text(encoding="utf-8")
    marker = "for collection_name in STATE_COLLECTIONS.values():"
    assert marker in source
    guard_region = source[source.index(marker) - 600 : source.index(marker) + 400]
    assert "deferred_now" in guard_region, "全量加载的水位线兜底必须排除延迟集合"
    assert "continue" in guard_region


def test_slice_task_ensures_page_index_loaded_before_write() -> None:
    """切片任务写 knowledge_page_index_nodes（PIN-ROOT-*），它是延迟集合。
    内存为空时新写的 id 撞库里已有行 → flush ConcurrentPersistenceError，
    整条切片链断掉（2026-08-29 生产实测：延迟加载上线后所有切片卡死）。
    入口必须先 ensure_collections_loaded。"""
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    slice_body = source.split("def slice_knowledge", 1)[1][:800]
    assert "ensure_collections_loaded" in slice_body, "切片任务写页索引前必须加载它"
    assert "knowledge_page_index_nodes" in slice_body


def test_page_index_rebuild_has_defensive_load_guard() -> None:
    """sync_standard_page_index_for_source「先删后 extend」重建整表——
    内存为空时会丢掉库里其他 source 的全部节点。方法内必须有防御性护栏，
    任何调用方忘了 ensure 都不静默丢数据。"""
    source = (BACKEND_ROOT / "libs" / "db" / "repository.py").read_text(encoding="utf-8")
    method = source.split("def sync_standard_page_index_for_source", 1)[1][:600]
    assert "ensure_deferred_loaded" in method
    assert "knowledge_page_index_nodes" in method


def test_ensure_deferred_loaded_only_fills_missing(monkeypatch) -> None:
    from libs.db import repository

    repo = repository.InMemoryRepository()
    calls = []
    monkeypatch.setattr(repo, "collection_is_loaded", lambda key, tenant_id=None: key == "knowledge_vectors")
    monkeypatch.setattr(repo, "load_collections_into_state", lambda keys, tenant_id=None: calls.append(keys))
    repo.ensure_deferred_loaded("knowledge_vectors", "knowledge_page_index_nodes")
    # vectors 已加载，只补 page_index
    assert calls == [["knowledge_page_index_nodes"]]
