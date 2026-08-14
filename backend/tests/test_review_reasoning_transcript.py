"""推理过程存档。

原先推理只活在串流期间（agent.reasoning.delta 事件），模型答完，最终消息里
就没有了。这套系统出的是监督检验意见，事后被问「凭什么」时，
「去查事件流」不是一个能给监检的答案。
"""

from __future__ import annotations

from libs.review_reasoning_transcript import (
    MAX_TRANSCRIPT_CHARS,
    append_reasoning_turn,
    reasoning_block,
    reasoning_transcript_text,
)


def test_按轮记录并分段():
    """6 轮推理首尾相接是一堵墙。实测一次核查产出 13,587 字，
    不分段就没法定位「它是拿到 OCR 结果之后才改口的」。"""
    transcript: list[dict] = []
    append_reasoning_turn(transcript, 1, "先看就绪度")
    append_reasoning_turn(transcript, 2, "再调用工具")
    text = reasoning_transcript_text(transcript)
    assert "── 第 1 轮 ──" in text
    assert "── 第 2 轮 ──" in text
    assert text.index("第 1 轮") < text.index("第 2 轮")


def test_同一轮取更完整的那份不拼两遍():
    """串流缓冲和非串流兜底都会记同一轮，直接追加会出现重复内容。"""
    transcript: list[dict] = []
    append_reasoning_turn(transcript, 1, "先看就")
    append_reasoning_turn(transcript, 1, "先看就绪度，再调工具")
    assert len(transcript) == 1
    assert transcript[0]["text"] == "先看就绪度，再调工具"
    # 更短的那份不能把已有的覆盖掉
    append_reasoning_turn(transcript, 1, "短")
    assert transcript[0]["text"] == "先看就绪度，再调工具"


def test_空白轮次不记():
    """一个空的「第 3 轮」只是噪音。"""
    transcript: list[dict] = []
    append_reasoning_turn(transcript, 1, "")
    append_reasoning_turn(transcript, 2, "   \n ")
    assert transcript == []
    assert reasoning_transcript_text(transcript) == ""
    assert reasoning_block(transcript) is None


def test_乱序进来也按轮号排():
    transcript: list[dict] = []
    append_reasoning_turn(transcript, 3, "三")
    append_reasoning_turn(transcript, 1, "一")
    text = reasoning_transcript_text(transcript)
    assert text.index("第 1 轮") < text.index("第 3 轮")


def test_超长时保留末尾并说明截了多少():
    """结论是最后几轮定下来的，追问「凭什么」时最相关。
    截断必须明说——否则人会以为看到的就是全部。"""
    transcript = [{"turn": i, "text": f"第{i}轮内容" + "啊" * 3000} for i in range(1, 8)]
    text = reasoning_transcript_text(transcript, max_chars=8000)
    assert len(text) <= 8000 + 200
    assert "未存档" in text, "截断要明说"
    assert "agent.reasoning.delta" in text, "要指出去哪找全量"
    # 保留的是靠后的轮次
    assert "第7轮内容" in text
    assert "第1轮内容" not in text


def test_单轮就超限时截这一轮的尾部():
    transcript = [{"turn": 1, "text": "啊" * 5000}]
    text = reasoning_transcript_text(transcript, max_chars=1000)
    assert len(text) <= 1100
    assert "已截去" in text


def test_默认上限装得下实测长度():
    """线上一次 6 轮核查产出 13,587 字，默认上限要能完整装下。"""
    assert MAX_TRANSCRIPT_CHARS >= 14000


def test_组装成消息块():
    block = reasoning_block([{"turn": 1, "text": "推理内容"}])
    assert block is not None
    assert block["type"] == "reasoning"
    assert "推理内容" in block["text"]


def test_脏数据不炸():
    """这段在主链路上，带崩了整条消息就出不来。"""
    assert reasoning_transcript_text(None) == ""
    assert reasoning_transcript_text([]) == ""
    assert reasoning_transcript_text([None, 3, "字符串"]) == ""  # type: ignore[list-item]
    assert reasoning_transcript_text([{"turn": "坏", "text": "有内容"}]) != ""
    assert reasoning_block(None) is None
