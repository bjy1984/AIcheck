"""状态新鲜度探针（issue #9）。

API 进程把全量业务状态驻留在内存、启动时加载一次，进程外的写入一概看不见——
线上踩过两次：改完口令登录仍失败、数据写进库了界面还是旧的，都得重启容器。

这些用例钉住的是判断逻辑本身，与数据库解耦：探针最容易错的地方不是查询，
是「什么时候该判过期」——判多了每请求都全量重载，判少了继续给旧数据。
"""

from __future__ import annotations

from libs.db.state_freshness import StateFreshnessProbe


def _probe() -> StateFreshnessProbe:
    return StateFreshnessProbe(interval_seconds=0.0)


def test_first_probe_only_establishes_baseline() -> None:
    """首次探针不该判任何东西过期。

    此刻内存里的数据就是刚加载的。全判成过期，会让每个进程启动后立刻多做一次
    全量重载——纯浪费，而且高并发下每个 worker 都来一次。
    """
    probe = _probe()
    stale = probe.stale_collections(global_max="T1", collection_max={"users": "T1"})
    assert stale == set()


def test_unchanged_global_stamp_short_circuits() -> None:
    """一级探针没变就直接返回，不跑二级查询——这正是它省钱的地方。"""
    probe = _probe()
    probe.stale_collections(global_max="T1", collection_max={"users": "T1"})
    assert probe.needs_second_stage(global_max="T1") is False
    assert probe.stale_collections(global_max="T1", collection_max={"users": "T9"}) == set()


def test_only_changed_collections_are_reported() -> None:
    """只报真变了的集合。

    全量重载在这个库上要几秒，按集合重载是毫秒级；多报一个集合就是白付一次。
    """
    probe = _probe()
    probe.stale_collections(
        global_max="T1", collection_max={"users": "T1", "documents": "T1"}
    )
    stale = probe.stale_collections(
        global_max="T2", collection_max={"users": "T2", "documents": "T1"}
    )
    assert stale == {"users"}


def test_new_collection_counts_as_stale() -> None:
    """库里出现了本进程没见过的集合，也要重载——否则它永远是空的。"""
    probe = _probe()
    probe.stale_collections(global_max="T1", collection_max={"users": "T1"})
    stale = probe.stale_collections(
        global_max="T2", collection_max={"users": "T1", "ocr_jobs": "T2"}
    )
    assert stale == {"ocr_jobs"}


def test_throttle_skips_probes_inside_the_interval() -> None:
    """节流：间隔内不重复探。

    探针再便宜也是一次数据库往返，每请求都探会在高频读上白加一次。
    """
    probe = StateFreshnessProbe(interval_seconds=5.0)
    probe.stale_collections(global_max="T1", collection_max={"users": "T1"}, now=100.0)
    # 才过 1 秒，不该再探
    assert probe.stale_collections(
        global_max="T2", collection_max={"users": "T2"}, now=101.0
    ) == set()
    # 超过间隔后正常生效
    assert probe.stale_collections(
        global_max="T2", collection_max={"users": "T2"}, now=106.0
    ) == {"users"}


def test_force_bypasses_the_throttle() -> None:
    """关键动作（改口令、切租户）后要能立刻探，不必等节流窗口。"""
    probe = StateFreshnessProbe(interval_seconds=5.0)
    probe.stale_collections(global_max="T1", collection_max={"users": "T1"}, now=100.0)
    stale = probe.stale_collections(
        global_max="T2", collection_max={"users": "T2"}, now=100.5, force=True
    )
    assert stale == {"users"}


def test_empty_database_is_not_treated_as_stale() -> None:
    """库里一行都没有时没有可比对的东西，不该判过期。"""
    probe = _probe()
    assert probe.stale_collections(global_max=None, collection_max=None) == set()


def test_second_stage_needed_only_when_global_moved() -> None:
    probe = _probe()
    assert probe.needs_second_stage(global_max="T1") is True, "首次必须查"
    probe.stale_collections(global_max="T1", collection_max={"users": "T1"})
    assert probe.needs_second_stage(global_max="T1") is False
    assert probe.needs_second_stage(global_max="T2") is True


def test_reset_forces_a_fresh_baseline() -> None:
    """重置后回到「首次探针」语义：建立基线，不判过期。"""
    probe = _probe()
    probe.stale_collections(global_max="T1", collection_max={"users": "T1"})
    probe.reset()
    assert probe.needs_second_stage(global_max="T1") is True
    assert probe.stale_collections(global_max="T1", collection_max={"users": "T1"}) == set()
