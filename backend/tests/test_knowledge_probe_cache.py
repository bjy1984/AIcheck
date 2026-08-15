"""知识库健康度探针不该让每次开页都等九秒。

## 线上实测（2026-08-15）

`/knowledge/overview` 只返回 3 KB，却要 **10.1 秒**。逐段计时：

    load_state                     23.04s（每进程一次，不计入单请求）
    遍历切片                        0.01s
    遍历向量                        0.01s
    build_knowledge_rule_scorecard  8.84s
      └─ run_retrieval_probes       8.82s   ← 全部在这

每次打开知识库页面，都会现场做三次完整检索（在 7,314 条切片上算相似度），
只为得到一个健康度评分。用户看到的是点「AI 知识库管理」之后进度条转十秒，
以为页面没跳转——这正是 admin 问题清单里的第 5 条。

## 顺带记一次我自己的错

第一版我改的是「切片/向量计数交给数据库算」，改完才量，发现那两段各 0.01 秒，
纯属打错目标，还平白多一次数据库往返。已回退。
**先量再改**，这条在这个仓库里已经付过两次学费。

## 判据

评分是自检指标，不是实时读数。缓存按「条款/切片/页索引的条数」失效——
内容真变了自然重算；不做内容级哈希，那要遍历全部切片，
跟直接跑探针一样贵，等于用一个慢操作去省另一个慢操作。
"""

from __future__ import annotations

import inspect

from libs import knowledge_readiness


def _reset_cache() -> None:
    knowledge_readiness._probe_cache.update({"key": None, "at": 0.0, "probes": None})


def test_同一份知识库不重复跑探针(monkeypatch):
    _reset_cache()
    calls = {"n": 0}

    def fake_retrieve(*args, **kwargs):
        calls["n"] += 1
        return {"trace": {"selectedRoute": "exact_clause_lookup", "selectedClauses": []}}

    monkeypatch.setattr(knowledge_readiness, "retrieve_knowledge_clauses", fake_retrieve)
    state = {"knowledge_clauses": [1], "knowledge_chunks": [1, 2], "knowledge_page_index_nodes": []}

    knowledge_readiness.run_retrieval_probes(state)
    first = calls["n"]
    assert first == len(knowledge_readiness.REQUIRED_KNOWLEDGE_ROUTES)

    knowledge_readiness.run_retrieval_probes(state)
    assert calls["n"] == first, "同一份知识库又跑了一遍探针"


def test_内容变了要重跑(monkeypatch):
    _reset_cache()
    calls = {"n": 0}

    def fake_retrieve(*args, **kwargs):
        calls["n"] += 1
        return {"trace": {"selectedRoute": "x", "selectedClauses": []}}

    monkeypatch.setattr(knowledge_readiness, "retrieve_knowledge_clauses", fake_retrieve)
    state = {"knowledge_clauses": [1], "knowledge_chunks": [1], "knowledge_page_index_nodes": []}
    knowledge_readiness.run_retrieval_probes(state)
    before = calls["n"]

    state["knowledge_chunks"] = [1, 2]  # 新切片进来了
    knowledge_readiness.run_retrieval_probes(state)
    assert calls["n"] > before, "知识库变了却还在用旧的探针结果"


def test_可以强制刷新(monkeypatch):
    _reset_cache()
    calls = {"n": 0}

    def fake_retrieve(*args, **kwargs):
        calls["n"] += 1
        return {"trace": {"selectedRoute": "x", "selectedClauses": []}}

    monkeypatch.setattr(knowledge_readiness, "retrieve_knowledge_clauses", fake_retrieve)
    state = {"knowledge_clauses": [], "knowledge_chunks": [], "knowledge_page_index_nodes": []}
    knowledge_readiness.run_retrieval_probes(state)
    before = calls["n"]
    knowledge_readiness.run_retrieval_probes(state, force=True)
    assert calls["n"] > before, "force=True 应当无视缓存"


def test_指纹不做内容级哈希():
    """遍历全部切片算哈希，跟直接跑探针一样贵——用一个慢操作去省另一个慢操作。"""
    source = inspect.getsource(knowledge_readiness._probe_cache_key)
    assert "hashlib" not in source and "json.dumps" not in source
    for key in ("knowledge_clauses", "knowledge_chunks", "knowledge_page_index_nodes"):
        assert key in source, f"{key} 变化时应当失效"
