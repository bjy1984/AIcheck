"""把 Agent 各轮的推理过程攒成一份可存档的记录。

## 为什么要存

推理过程原先只活在串流期间：`agent.reasoning.delta` 事件推给前端渐进渲染，
模型答完，最终消息里就没有了。事件流里还留着，但那是运维视角的东西——
监检回头看这条结论时，看不到「它凭什么这么判」。

这套系统出的是监督检验意见。**结论可追溯是底线**，事后被问「你凭什么」时，
「去查事件流」不是一个能给监检的答案。

## 为什么分轮记

一次核查跑了 6 轮工具调用，6 段推理直接首尾相接是一堵墙。实测那次总长
13,587 字——不分段的话，读的人没法定位「它是在拿到 OCR 结果之后才改口的」。

## 为什么截断保留末尾

超长时保留靠后的轮次：结论是最后几轮定下来的，追问「凭什么」时最相关。
截掉的部分要明说截了多少，不能让人以为看到的就是全部——事件流里有全量。
"""

from __future__ import annotations

from typing import Any

# 单条消息里存档的推理上限。实测一次 6 轮核查产出 13,587 字；给到 24000
# 能完整装下绝大多数，又不至于让单条消息无限膨胀。
MAX_TRANSCRIPT_CHARS = 24000


def append_reasoning_turn(transcript: list[dict[str, Any]], turn: int, text: str) -> None:
    """记下某一轮的推理。空白轮次不记——一个空的「第 3 轮」只是噪音。"""
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    for item in transcript:
        if item.get("turn") == turn:
            # 同一轮可能既走串流缓冲又走非串流兜底，取更完整的那份，不要拼两遍
            if len(cleaned) > len(str(item.get("text") or "")):
                item["text"] = cleaned
            return
    transcript.append({"turn": int(turn), "text": cleaned})


def reasoning_transcript_text(
    transcript: list[dict[str, Any]] | None,
    max_chars: int = MAX_TRANSCRIPT_CHARS,
) -> str:
    """拼成可读文本。超长时保留靠后的轮次，并写明截掉了多少。"""
    items = [
        item
        for item in (transcript or [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    if not items:
        return ""
    def _turn_of(item: dict[str, Any]) -> int:
        # 轮号只是排序与显示用。坏数据不能把整条消息带崩——这段在主链路上。
        try:
            return int(item.get("turn") or 0)
        except (TypeError, ValueError):
            return 0

    items.sort(key=_turn_of)
    sections = [
        f"── 第 {_turn_of(item)} 轮 ──\n{str(item['text']).strip()}" for item in items
    ]

    kept: list[str] = []
    used = 0
    dropped = 0
    # 从最后一轮往前收：结论是最后几轮定下来的
    for section in reversed(sections):
        if used + len(section) + 2 > max_chars and kept:
            dropped += 1
            continue
        if used + len(section) + 2 > max_chars:
            # 单轮就超限：截这一轮的尾部，并明说截了
            room = max(0, max_chars - 40)
            kept.append(section[:room] + f"\n…（本轮推理过长，已截去 {len(section) - room} 字）")
            used = max_chars
            continue
        kept.append(section)
        used += len(section) + 2
    kept.reverse()
    if dropped:
        kept.insert(
            0,
            f"（较早的 {dropped} 轮推理未存档，完整内容见会话事件流 agent.reasoning.delta）",
        )
    return "\n\n".join(kept)


def reasoning_block(
    transcript: list[dict[str, Any]] | None,
    max_chars: int = MAX_TRANSCRIPT_CHARS,
) -> dict[str, Any] | None:
    """组装成消息内容块。没有推理就返回 None——空块会渲染出一个点不开的行。"""
    text = reasoning_transcript_text(transcript, max_chars)
    if not text:
        return None
    return {"type": "reasoning", "text": text}
