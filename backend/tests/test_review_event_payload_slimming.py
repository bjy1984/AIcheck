"""事件列表不该把 3.9 MB 传给一个不看它的前端。

## 线上实测（2026-08-15，真实浏览器）

打开监检工作台，首屏 6 个接口一共传了 4.9 MB，其中

    /review-sessions/{id}/events   8.0 秒   3,933 KB

一个接口就占了 3.9 MB。DOM 245ms 就绪，剩下十几秒全在等数据。

拆开看：453 条事件里 `graph_node.succeeded` 184 条，占 details 总量的
**99.6%**（每条约 42 KB）。而前端的 ReviewBEvent 契约里根本没有放这些内容的
字段——它只用 eventType / title / status 排执行轨迹，payload 只在流式增量时读。
传过去就被丢掉。

## 判据

- 过大的 payload 折叠成摘要，原文仍在库里，细节入口照常给全量；
- `agent.*` 一个字都不能动：流式增量靠逐字拼接；
- payloadHash 按**原文**算，别拿摘要算——那会让人以为内容变了。
"""

from __future__ import annotations

import json

from apps.api.routes import MAX_EVENT_PAYLOAD_CHARS, slim_event_payload


def _big(chars: int) -> dict:
    return {"output": "字" * chars, "nodeKey": "retrieval"}


def test_过大的执行事件被折叠():
    payload = _big(50000)
    slimmed = slim_event_payload("graph_node.succeeded", payload)
    assert slimmed["payloadTruncated"] is True
    assert "nodeKey" in slimmed["keys"], "折叠后要留下键名，看得出里面有什么"
    assert slimmed["originalChars"] > MAX_EVENT_PAYLOAD_CHARS
    assert len(json.dumps(slimmed, ensure_ascii=False)) < 1000


def test_小的原样返回():
    payload = {"nodeKey": "retrieval", "status": "succeeded"}
    assert slim_event_payload("graph_node.succeeded", payload) is payload


def test_流式增量一个字都不能动():
    """agent.* 是逐字拼接出来的，截断就是把用户看到的答案改了。"""
    payload = {"delta": "很长的正文" * 5000}
    assert slim_event_payload("agent.message.delta", payload) is payload
    assert slim_event_payload("agent.reasoning.delta", payload) is payload


def test_空载荷不炸():
    assert slim_event_payload("graph_node.succeeded", {}) == {}


def test_列表接口用的是原文哈希():
    """折叠是传输层的事。拿摘要算哈希，会让人以为内容变了。"""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "apps" / "api" / "routes.py"
    ).read_text(encoding="utf-8")
    idx = source.index('"payload": slim_event_payload(')
    block = source[idx : idx + 500]
    assert 'stable_hash_payload(item.get("details") or {})' in block
