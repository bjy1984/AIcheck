"""让 API 进程看得见进程外的写入（issue #9）。

## 问题

全量业务状态驻留在 API 进程内存，启动时加载一次。进程外的写入它一概看不见：

- worker 落库的 OCR 结果、审查产物；
- 运维改口令、调配置；
- 迁移与修数脚本。

线上踩过两次：改完口令登录仍失败、数据写进库了界面还是旧的，都得重启容器才好。
排查时最费时间的不是修，是意识到「代码没问题，是这个进程还活在过去」。

## 做法

两级探针，先问一个数，再问改了哪几个集合：

    一级  SELECT max(updated_at) ... WHERE tenant_id=%s          1 行，近乎免费
    二级  SELECT collection, max(updated_at) ... GROUP BY ...    仅在一级变动时跑

只重载真正变了的集合。全量重载在这个库上要几秒，按集合重载是毫秒级。

不能用 revision 当探针：它是每对象各自计数（实测全表只有 1..4），
不是全局单调序列，比不出新旧。

## 为什么带节流

探针再便宜也是一次往返。默认 1 秒内至多探一次——业务上「口令改了 1 秒后生效」
完全够用，而每请求都探会在高频读上白白加一次数据库往返。

## 失败取向

探测失败一律当作「没变化」并继续用内存里的数据，不阻断请求。
理由是代价不对称：探针本身不是数据源，它挂了让整个 API 跟着挂是本末倒置；
而多用一会儿旧数据，下一次探针成功时就会自愈。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

LOGGER = logging.getLogger("aicheck.state_freshness")

# 两次探针之间的最小间隔（秒）。
DEFAULT_PROBE_INTERVAL_SECONDS = 1.0


class StateFreshnessProbe:
    """记录本进程见过的最新写入时间，并判断库里有没有更新的。"""

    def __init__(self, *, interval_seconds: float = DEFAULT_PROBE_INTERVAL_SECONDS) -> None:
        self._interval = max(0.0, float(interval_seconds))
        self._lock = threading.Lock()
        self._last_probe_at = 0.0
        self._seen_global: Any = None
        self._seen_by_collection: dict[str, Any] = {}

    def prime(self, *, global_max: Any, collection_max: dict[str, Any]) -> None:
        """整表加载之后立刻建立基线。

        不建的话，下一次探测会被判成「首次探测」——而首次探测按设计**只建基线、
        不刷新任何东西**。于是 worker 的第二个任务读到的还是整表加载那一刻的数据，
        中间由别的进程写入的东西一概看不见。

        0819 线上就是这样：OCR worker 写好解析结果，切片 worker 读到 0 片段，
        判成 empty_text，报审因此永久卡住——**症状和一个已修的老 bug 一模一样，
        只是换了机制**。加载完就把基线建上，这条缝就没有了。
        """
        with self._lock:
            self._seen_global = global_max
            self._seen_by_collection.update(collection_max)

    def reset(self) -> None:
        """把「见过的最新时间」清空，下次探针会认为一切都需要重载。"""
        with self._lock:
            self._last_probe_at = 0.0
            self._seen_global = None
            self._seen_by_collection = {}

    def _due(self, now: float) -> bool:
        return now - self._last_probe_at >= self._interval

    def stale_collections(
        self,
        *,
        global_max: Any,
        collection_max: dict[str, Any] | None = None,
        now: float | None = None,
        force: bool = False,
    ) -> set[str]:
        """返回需要重载的集合名。

        参数是查询结果而不是连接：这样这段判断逻辑可以脱离数据库测试，
        而它恰恰是最容易出错、也最该被钉住的部分。
        """
        stamp = time.monotonic() if now is None else now
        with self._lock:
            if not force and not self._due(stamp):
                return set()
            self._last_probe_at = stamp
            first_probe = self._seen_global is None
            if global_max is None:
                # 库里一行都没有：没有可比对的东西，也就没有过期一说
                self._seen_global = None
                return set()
            if not first_probe and global_max == self._seen_global:
                return set()
            self._seen_global = global_max
            if collection_max is None:
                # 一级发现变化但没给二级结果——调用方会据此再查一次
                return set()
            stale = {
                name
                for name, stamp_value in collection_max.items()
                if self._seen_by_collection.get(name) != stamp_value
            }
            self._seen_by_collection = dict(collection_max)
            if first_probe:
                # 首次探针只是建立基线：此刻内存里的数据就是刚加载的，
                # 全判成过期会在每个进程启动后立刻触发一次全量重载。
                return set()
            return stale

    def needs_second_stage(self, *, global_max: Any) -> bool:
        """一级探针是否发现了变化（用于决定要不要跑二级查询）。"""
        with self._lock:
            return self._seen_global is None or global_max != self._seen_global
