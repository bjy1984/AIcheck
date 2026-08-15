"""作用域 flush 不能被一条没改过的邻居记录拖垮。

## 线上症状（2026-08-15）

「发起缺项预审」接口返回 `waiting_human_review`，数据库里那条 review_run
永远停在 `queued`。前一轮我给 execute_review_run_inline 包了 try/finally 落库，
线上复验**依然是 queued**——因为 flush 根本没写成功，异常被 `except: pass` 吞了。

在容器里不吞异常跑一遍，真正的报错是：

    ConcurrentPersistenceError: Concurrent persistence update detected
    for ai_runs/AIRUN-1-36612F2E; reload before retrying.

**报错的记录和丢数据的记录不是同一条。** review_run_state_records 交上来的是
整个聚合（review_runs / review_events / ai_runs / tree_nodes ...），其中 ai_runs
这次压根没被改过，只是执行期间 worker 进程写了库里那一行。守卫发现
baseline 与库里对不上就抛异常，整个事务回滚，把 review_runs 的完成状态一起带走。

## 判据

没改过的记录不写。冲突消失，而真改过还撞上时守卫照旧拦——不是把守卫关掉。
"""

from __future__ import annotations

from libs.db.repository import InMemoryRepository


def _repo_with_baseline(collection: str, object_id: str, doc: dict) -> InMemoryRepository:
    repository = InMemoryRepository()
    payload = repository.canonical_persistence_payload(repository.persistence_tenant_document(doc))
    repository._persistence_baseline[(collection, object_id)] = payload
    return repository


def test_没改过的记录判为无需写入():
    doc = {"id": "AIRUN-1", "status": "completed"}
    repository = _repo_with_baseline("ai_runs", "AIRUN-1", doc)
    payload = repository.canonical_persistence_payload(repository.persistence_tenant_document(doc))
    assert repository.unchanged_since_baseline(("ai_runs", "AIRUN-1"), payload) is True


def test_改过的记录仍然要写并接受守卫检查():
    """跳过只针对「没动过」的记录。真改过的必须照常进事务，
    该撞的并发冲突还得撞——否则就是把守卫悄悄关掉了。"""
    doc = {"id": "AIRUN-1", "status": "completed"}
    repository = _repo_with_baseline("ai_runs", "AIRUN-1", doc)
    changed = repository.canonical_persistence_payload(
        repository.persistence_tenant_document({"id": "AIRUN-1", "status": "failed"})
    )
    assert repository.unchanged_since_baseline(("ai_runs", "AIRUN-1"), changed) is False


def test_新记录不会被误判为无需写入():
    """没有 baseline 的键是新插入，必须写。"""
    repository = InMemoryRepository()
    payload = repository.canonical_persistence_payload({"id": "NEW-1"})
    assert repository.unchanged_since_baseline(("ai_runs", "NEW-1"), payload) is False


def test_两条写入路径都接了这道判据():
    """Postgres 与 SQLite 是同一个形状，只修一边等于没修。"""
    import inspect

    source = inspect.getsource(InMemoryRepository.sync_state_records_to_sync_postgres)
    assert "unchanged_since_baseline" in source
    source = inspect.getsource(InMemoryRepository.sync_state_records_to_sqlite)
    assert "unchanged_since_baseline" in source


def test_落库失败必须留下日志而不是_pass():
    """上一轮的根因之所以查了一整轮，就是因为这里写的是 `pass`。

    落库尽力而为是对的（不能让它掀翻已经跑完、已经花过 token 的结果），
    但「尽力而为」不等于「无声无息」。
    """
    import inspect

    from libs.review_orchestrator import execution

    source = inspect.getsource(execution.execute_review_run_inline)
    finally_block = source[source.index("finally:") :]
    assert "pass" not in finally_block.split("except")[-1].split("\n")[1:][0]
    assert "logging" in finally_block or "logger" in finally_block
