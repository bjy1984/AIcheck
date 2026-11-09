"""审查会话的消息、事件按会话编号建索引（2026-11-09，agent-memory 评估 G 项）。

原来读一本会话的消息、算下一个序号、拼事件快照，都把整个 `review_messages` /
`review_session_events` 扫一遍再按 sessionId 筛。生产现在量小（39 条消息、455 条事件）
感觉不到，但每发一句话要扫好几遍，量一上来就是 O(全院消息数)。

为什么可以缓存在进程里、不用到处埋钩子：
- 这两个集合只会被追加。代码里没有删除或原位替换（11-09 grep 过 apps/libs/scripts）。
- 从 Postgres 刷新（整表或按会话）都是给 state 换一个**新列表**
  （见 Repository._merge_scoped_state_rows），不是在旧列表上改。
所以只要记住「索引的是哪个列表对象、索引到第几条」：列表对象换了就整体重建，
变长了就只补新追加的那几条。消息本身是同一批 dict，状态、内容、序号的原地修改天然可见。

防御：长度变短，或已索引的最后一条不再是同一个对象（有人原位替换了），也整体重建。
"""

from __future__ import annotations

import threading
from typing import Any

from libs.db.repository import repo

INDEXED_COLLECTIONS = ("review_messages", "review_session_events")


class _SessionIndex:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] | None = None
        self.indexed = 0
        self.by_session: dict[str, list[dict[str, Any]]] = {}
        self.last: Any = None

    def rebuild(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.indexed = 0
        self.by_session = {}
        self.extend(rows)

    def extend(self, rows: list[dict[str, Any]]) -> None:
        for item in rows[self.indexed :]:
            if isinstance(item, dict):
                self.by_session.setdefault(str(item.get("sessionId") or ""), []).append(item)
        self.indexed = len(rows)

    def current(self, rows: list[dict[str, Any]]) -> None:
        stale = (
            rows is not self.rows
            or len(rows) < self.indexed
            or (self.indexed and rows[self.indexed - 1] is not self.last)
        )
        if stale:
            self.rebuild(rows)
        elif len(rows) > self.indexed:
            self.extend(rows)
        self.last = rows[self.indexed - 1] if self.indexed else None


_LOCK = threading.Lock()
_INDEXES = {collection: _SessionIndex() for collection in INDEXED_COLLECTIONS}


def session_rows(collection: str, session_id: str) -> list[dict[str, Any]]:
    """这本会话在该集合里的全部记录，按追加顺序；返回新列表，元素是 state 里的同一批 dict。"""
    if collection not in _INDEXES:
        return [item for item in repo.state.get(collection, []) if item.get("sessionId") == session_id]
    rows = repo.state.get(collection)
    if not isinstance(rows, list):
        return []
    with _LOCK:
        index = _INDEXES[collection]
        index.current(rows)
        return list(index.by_session.get(str(session_id or ""), ()))


def next_sequence(collection: str, session_id: str) -> int:
    return max((int(item.get("sequence") or 0) for item in session_rows(collection, session_id)), default=0) + 1
