"""落库比对用的规范化表示：换成 orjson 之后行为必须与原来一致。

## 为什么换

这个函数会对整份状态逐条调用。标准库 json 实测 18 秒、orjson 2.6 秒。
这段时间占着解释器，同进程所有请求都被挤住——0819 实测一次写入期间
/api/healthz 要 16~26 秒，**不是写慢，是全站都慢**。

## 两处必须钉住的差异

1. **整数键**：库里有以整数为键的映射。orjson 不带 OPT_NON_STR_KEYS 会直接抛错，
   而标准库 json 会把它转成字符串。行为不一致的话，同一条记录每次都被判成
   「改过」，于是天天重写、天天触发乐观锁冲突。
2. **确定性**：同样的内容必须给出同样的字符串，否则比对基线永远不相等。
"""

from __future__ import annotations

from libs.db.repository import InMemoryRepository

payload = InMemoryRepository.canonical_persistence_payload


def test_整数键不抛错且与标准库口径一致() -> None:
    got = payload({"nodeScope": {1: "a", 2: "b"}})
    assert '"1"' in got and '"2"' in got, f"整数键没有被转成字符串：{got}"


def test_键序稳定() -> None:
    assert payload({"b": 1, "a": 2}) == payload({"a": 2, "b": 1})


def test_同样内容给同样字符串() -> None:
    value = {"id": "X", "items": [1, 2, {"z": None, "a": True}], "ts": "2026-08-19"}
    assert payload(value) == payload(dict(value))


def test_无法直接序列化的对象退回字符串() -> None:
    from datetime import UTC, datetime

    got = payload({"at": datetime(2026, 8, 19, tzinfo=UTC)})
    assert "2026-08-19" in got, got


def test_中文不转义() -> None:
    """转义成 \\uXXXX 的话体积翻几倍，而这份状态有几十 MB。"""
    assert "压力管道" in payload({"name": "压力管道"})


def test_落库拷贝是浅拷贝且不影响原记录() -> None:
    """这是一条**有代价的约定**，必须钉住两头。

    浅拷贝的理由：原先是 deepcopy，只为序列化一次就丢掉，
    76323 条记录实测 7.4 秒 vs 0.1 秒（74 倍）。落库前要对整份状态逐条做，
    这段时间占着解释器，同进程所有请求都被挤住。

    代价是嵌套结构与运行中的状态**共享**：调用方只能读，不能改。
    所以这里钉两件事——顶层改动不回写原记录（拷贝确实发生了），
    以及嵌套确实是共享的（提醒后来者别在返回值上改嵌套内容）。
    """
    from libs.db.repository import repo

    original = {"id": "X", "nested": {"k": "v"}}
    scoped = repo.persistence_tenant_document(original)

    scoped["id"] = "改过了"
    assert original["id"] == "X", "顶层被改回原记录了——那就不是拷贝"

    assert scoped["nested"] is original["nested"], (
        "嵌套不再共享——要么有人改回了 deepcopy（每次落库多付 7 秒），"
        "要么改成了别的拷贝方式，请连同这条注释一起更新"
    )
