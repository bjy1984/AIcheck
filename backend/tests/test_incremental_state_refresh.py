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
        if normalized.startswith("SELECT collection, object_id, payload, updated_at FROM aicheck_state"):
            # 整表加载。带一条 projects：库里没有项目时加载路径会去播种 demo 数据，
            # 那条分支与本用例无关，却会把断言淹掉。
            return _Cursor(
                [("projects", "P-1", {"id": "P-1"}, datetime(2026, 8, 18, tzinfo=UTC))]
                + [
                    (coll, object_id, payload, stamp)
                    for (coll, object_id), (payload, stamp) in sorted(self.rows.items())
                ]
            )
        return _Cursor([])

    def commit(self) -> None:
        pass

    def transaction(self):
        from contextlib import nullcontext

        return nullcontext()


class _Cursor:
    def __init__(self, rows):
        self._rows = rows
        self.rowcount = len(rows)

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


def test_整表加载后空集合也要算加载过() -> None:
    """一行都没有的集合，同样要记水位线。

    漏掉它们不会报错，也不会让数据出错——只会让**所有增量优化悄悄失效**：
    collection_is_loaded 对空集合永远返回 False，refresh_worker_state 每次都
    判定「还没加载过」而整份重来。0819 线上就是这样：增量代码部署了，
    worker 每个任务照旧付 38 秒，因为根本走不到增量那条路。

    这类 bug 最难查的地方在于——优化「上线了」，指标却一点没动。
    """
    repository = InMemoryRepository()
    connection = RecordingConnection({})
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True
    repository.configure_sync_postgres = lambda: None  # type: ignore[method-assign]
    repository.ensure_postgres_schema = lambda: None  # type: ignore[method-assign]
    # 加载路径里的条款漂移修复会顺带 flush，与本用例要钉的东西无关，打桩掉
    repository.flush_to_sync_postgres = lambda **_kwargs: None  # type: ignore[method-assign]

    repository.load_from_sync_postgres()

    from libs.db.repository import STATE_COLLECTIONS, deferred_bulk_state_keys

    # 延迟加载的集合是例外：它们这次根本没查库，标成「已加载」会让按需补拉
    # 直接跳过，内存永远空——那是静默的数据缺失，比慢严重得多。
    # 两条不变量各自成立：非延迟集合必须有水位线（本用例），
    # 延迟集合必须没有（test_deferred_bulk_load）。
    deferred = deferred_bulk_state_keys()
    missing = [
        key
        for key in STATE_COLLECTIONS
        if key not in deferred and not repository.collection_is_loaded(key)
    ]
    assert not missing, f"这些集合没有水位线，增量刷新会一直退回整表：{missing[:5]}"
    still_loaded = [key for key in deferred if repository.collection_is_loaded(key)]
    assert not still_loaded, f"延迟集合不该被标记已加载：{still_loaded}"


def test_整表加载后立刻建立探针基线() -> None:
    """加载完就要建基线，否则「第一次增量刷新」什么都不刷。

    探针的首次探测按设计只建基线、不返回过期集合。如果整表加载没有顺带把
    基线建上，那么 worker 的**第二个任务**才触发首次探测——它读到的仍是
    整表那一刻的数据，中间由别的进程写入的东西一概看不见。

    0819 线上实测的后果：OCR worker 写好解析结果，切片 worker 读到 0 片段、
    判成 empty_text，报审因此永久卡住——**症状和一个已修的老 bug 一模一样，
    只是换了机制**，而且同样不报错。
    """
    stamp = datetime(2026, 8, 19, 3, 0, tzinfo=UTC)
    repository = InMemoryRepository()
    connection = RecordingConnection({("knowledge_chunks", "C-1"): ({"id": "C-1"}, stamp)})
    repository.sync_postgres = connection
    repository.postgres_dsn = "postgresql://fake"
    repository.postgres_enabled = True
    repository.configure_sync_postgres = lambda: None  # type: ignore[method-assign]
    repository.ensure_postgres_schema = lambda: None  # type: ignore[method-assign]
    repository.flush_to_sync_postgres = lambda **_kwargs: None  # type: ignore[method-assign]

    repository.load_from_sync_postgres()

    # 基线建上了 → 下一次探测不再是「首次」，能真正判出过期集合
    later = datetime(2026, 8, 19, 3, 5, tzinfo=UTC)
    stale = repository._state_probe.stale_collections(
        global_max=later,
        collection_max={"knowledge_chunks": later},
        force=True,
    )
    assert stale == {"knowledge_chunks"}, (
        "整表加载后没建基线——第一次增量刷新会静默地什么都不刷，"
        "worker 于是一直读旧数据"
    )
