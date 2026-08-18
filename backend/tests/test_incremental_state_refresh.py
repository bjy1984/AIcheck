"""状态刷新只拉变化的行。

## 这条为什么值得钉住

请求中间件发现集合过期就整表重载。而向量化每写一个断点批次就弄脏两张大表：
knowledge_vectors 61 MB（重载 17.4 秒）、knowledge_embedding_batches 21 MB
（7.6 秒）。于是**只要有任何一份资料在向量化**，其后每个 API 请求都要先付
25 秒以上——0819 线上实测知识网络页 47 秒才出内容，而那个页面自己构建只要
0.15 秒。用户看到的是「一直在转圈，提示知识网络构建中」。

这不是批量重建才有的问题：正常上传一份资料同样会让全站慢几分钟。

## 判据

不是「快了」（那要计时，不稳），而是**没变的行根本不该被查**：
断言 SQL 里带 updated_at 过滤，且没有整表取 payload 的语句。
另外两条是正确性底线——删除要被感知、钉住的对象不许被覆盖。
"""

from __future__ import annotations

from datetime import UTC, datetime

from libs.db.repository import InMemoryRepository


class RecordingConnection:
    """记录执行过的 SQL，并按语句形状返回假数据。"""

    def __init__(self, rows: dict[tuple[str, str], tuple[dict, datetime]]):
        self.rows = rows
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        self.statements.append((normalized, params or ()))
        if normalized.startswith("SELECT object_id, payload, updated_at FROM aicheck_state"):
            _tenant, collection, watermark = params
            return _Cursor(
                [
                    (object_id, payload, stamp)
                    for (coll, object_id), (payload, stamp) in sorted(self.rows.items())
                    if coll == collection and stamp > watermark
                ]
            )
        if normalized.startswith("SELECT object_id FROM aicheck_state"):
            _tenant, collection = params
            return _Cursor([(object_id,) for (coll, object_id) in sorted(self.rows) if coll == collection])
        return _Cursor([])

    def commit(self) -> None:
        pass


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _repo_with(rows, watermark):
    repository = InMemoryRepository()
    connection = RecordingConnection(rows)
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True
    repository.ensure_postgres_schema = lambda: None  # type: ignore[method-assign]
    repository.configure_sync_postgres = lambda: None  # type: ignore[method-assign]
    repository._collection_watermarks[("TENANT-DEFAULT", "knowledge_vectors")] = watermark
    return repository, connection


def test_只查变化的行_不整表取payload() -> None:
    old = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
    new = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    rows = {
        ("knowledge_vectors", "V-1"): ({"id": "V-1", "v": "旧"}, old),
        ("knowledge_vectors", "V-2"): ({"id": "V-2", "v": "新"}, new),
    }
    repository, connection = _repo_with(rows, old)
    repository.state["knowledge_vectors"] = [{"id": "V-1", "v": "旧"}, {"id": "V-2", "v": "更旧"}]

    repository.refresh_collections_incrementally({"knowledge_vectors"})

    fetched = [s for s, _ in connection.statements if "payload" in s]
    assert fetched, "一条取 payload 的语句都没有？那什么都没刷新"
    assert all("updated_at > " in s for s in fetched), (
        "还在整表取 payload——没变的行也被拉了一遍，这正是要修的东西"
    )
    by_id = {item["id"]: item for item in repository.state["knowledge_vectors"]}
    assert by_id["V-2"]["v"] == "新", "变化的行没有被更新"
    assert by_id["V-1"]["v"] == "旧"


def test_库里删掉的记录要从内存里消失() -> None:
    """只拉变化行的话很容易漏掉删除——漏掉就等于内存里留着幽灵记录。"""
    old = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
    rows = {("knowledge_vectors", "V-1"): ({"id": "V-1"}, old)}
    repository, _ = _repo_with(rows, old)
    repository.state["knowledge_vectors"] = [{"id": "V-1"}, {"id": "V-DELETED"}]

    repository.refresh_collections_incrementally({"knowledge_vectors"})

    ids = {item["id"] for item in repository.state["knowledge_vectors"]}
    assert ids == {"V-1"}, "库里已经没有的记录还留在内存里"


def test_钉住的对象不许被库里的副本覆盖() -> None:
    """别的请求正在改它，覆盖等于让那次改动无声蒸发。整表加载路径同样有这条保护。"""
    old = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
    new = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    rows = {("knowledge_vectors", "V-1"): ({"id": "V-1", "v": "库里的"}, new)}
    repository, _ = _repo_with(rows, old)
    repository.state["knowledge_vectors"] = [{"id": "V-1", "v": "正在改的"}]
    repository.pin_object("knowledge_vectors", "V-1")

    repository.refresh_collections_incrementally({"knowledge_vectors"})

    assert repository.state["knowledge_vectors"][0]["v"] == "正在改的"


def test_没有水位线时退回整表加载() -> None:
    """进程刚起、集合从没加载过——此时没有可比对的时刻，必须整表来一次。"""
    repository = InMemoryRepository()
    calls: list[set[str]] = []
    repository.sync_postgres = RecordingConnection({})
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True
    repository.configure_sync_postgres = lambda: None  # type: ignore[method-assign]
    repository.load_from_sync_postgres = lambda keys=None, tenant_id=None: calls.append(set(keys or ()))  # type: ignore[method-assign]

    repository.refresh_collections_incrementally({"knowledge_vectors"})

    assert calls == [{"knowledge_vectors"}], "没有水位线却没走整表加载"


def test_没加载过的集合不能只走增量() -> None:
    """worker 刷新状态的契约：首次整表，之后增量。

    方向写反的后果不是「慢」，而是**读到空数据**：增量只拉「变化的行」，
    对从没加载过的集合来说等于什么都没拉，而调用方会把空内存当成
    「库里就是没有」——切片任务会认为文件不存在、向量化会认为没有分块。
    """
    from apps.worker import tasks

    repository = InMemoryRepository()
    calls: list[object] = []
    repository.refresh_stale_state_from_postgres = lambda **_kwargs: calls.append("增量")  # type: ignore[method-assign]

    original_repo = tasks.repo
    original_load = tasks.load_state
    original_enabled = tasks.worker_state_persistence_enabled
    try:
        tasks.repo = repository  # type: ignore[assignment]
        tasks.load_state = lambda keys=None: calls.append(("整表", keys))  # type: ignore[assignment]
        tasks.worker_state_persistence_enabled = lambda: True  # type: ignore[assignment]

        # 没有任何水位线 → 必须整表
        tasks.refresh_worker_state({"knowledge_chunks"})
        assert calls and calls[0][0] == "整表", "从没加载过却直接走了增量——会读到空数据"

        # 加载过之后 → 走增量
        calls.clear()
        repository._collection_watermarks[("TENANT-DEFAULT", "knowledge_chunks")] = datetime(
            2026, 8, 18, tzinfo=UTC
        )
        tasks.refresh_worker_state({"knowledge_chunks"})
        assert calls == ["增量"], "已经加载过了还在整表重来——每个任务白付几十秒"
    finally:
        tasks.repo = original_repo  # type: ignore[assignment]
        tasks.load_state = original_load  # type: ignore[assignment]
        tasks.worker_state_persistence_enabled = original_enabled  # type: ignore[assignment]
