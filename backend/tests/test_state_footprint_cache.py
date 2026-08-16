"""状态占用统计不该让每次开页都等五秒。

## 线上实测（2026-08-16，admin 后台）

逐段计时 /admin/config-overview 的路由体：

    build_admin_overview          0.022s
    list_business_packs           0.000s
    list_admin_org_units          0.000s
    list_admin_users              0.001s
    repository_state_footprint    5.077s   ← 全在这
    singleton_revision / etag     0.000s

它把进程里**全部 41024 条记录**序列化成 JSON，只为得出一个字节数；
而这个诊断指标挂在 config-overview 上，于是每打开一个 admin 页都要付这 5 秒。
PDF 里报的「切换加载时间长，在 8-9 秒」就是它。

## 我自己的两次错

1. 第一次说 A-1 已修——改的是别的加载路径，这条一直没动。
2. 这次先量了接口层（787 KB / 5 秒）就动手瘦身，**没往下钻到函数级**。
   瘦身本身有价值（788 KB → 16 KB），但耗时纹丝不动，因为瓶颈根本不在传输。
   量到「哪个接口慢」不等于量到「慢在哪一行」。

## 判据

- 集合条数不变就复用缓存，不重新序列化
- 条数变了要重算——容量涨了却还报旧数字，比慢更糟
- 不做内容级哈希：那要遍历全部记录，跟直接算一样贵
"""

from __future__ import annotations

import inspect

from apps.api import routes


def _reset() -> None:
    routes._STATE_FOOTPRINT_CACHE.update({"key": None, "value": None})


def test_条数不变时不重新序列化(monkeypatch):
    _reset()
    calls = {"n": 0}
    real_dumps = routes.json.dumps

    def counting_dumps(*args, **kwargs):
        calls["n"] += 1
        return real_dumps(*args, **kwargs)

    monkeypatch.setattr(routes.json, "dumps", counting_dumps)
    routes.repo.state.setdefault("documents", []).append({"id": "DOC-FP-1"})

    routes.repository_state_footprint()
    first = calls["n"]
    assert first > 0, "第一次要真算"

    routes.repository_state_footprint()
    assert calls["n"] == first, "条数没变却又序列化了一遍"


def test_条数变了要重算(monkeypatch):
    _reset()
    calls = {"n": 0}
    real_dumps = routes.json.dumps
    monkeypatch.setattr(
        routes.json,
        "dumps",
        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real_dumps(*a, **k))[1],
    )
    routes.repository_state_footprint()
    before = calls["n"]
    routes.repo.state.setdefault("documents", []).append({"id": "DOC-FP-2"})
    routes.repository_state_footprint()
    assert calls["n"] > before, "数据变了还在报旧数字——比慢更糟"


def test_不做内容级哈希():
    """遍历全部记录算哈希跟直接算一样贵，等于用一个慢操作省另一个慢操作。"""
    source = inspect.getsource(routes.repository_state_footprint)
    assert "hashlib" not in source
    assert "len(value)" in source, "指纹应当按条数，而不是内容"


def test_返回值带测量时间():
    """这是缓存过的近似值，要让看的人知道它不是实时读数。"""
    _reset()
    result = routes.repository_state_footprint()
    assert result.get("measuredAt")


def test_返回副本而不是缓存对象():
    """调用方改了返回值不该污染缓存——下一个请求会拿到被改过的数字。"""
    _reset()
    first = routes.repository_state_footprint()
    first["totalRecords"] = -1
    second = routes.repository_state_footprint()
    assert second["totalRecords"] != -1
