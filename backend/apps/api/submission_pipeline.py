"""报审前置：资料的处理链路走到哪一段了。

## 为什么要分环节

上传成功 ≠ 可以报审。资料还要过 OCR → 切片 → 向量化三段，三段全绿
才允许提交（否则审查拿不到证据）。

原先判定只回 True/False，三个提交入口统一报「文件上传处理尚未成功」。
可上传早就成功了——卡住的往往是它后面的切片或向量化。线上真按这句话
查过上传：文件在、大小对、OCR 显示已识别，什么问题也查不出来，
真身是切片从没被派过队（见 apps/worker/tasks.py 里 MinerU 那处
dispatch_slice 注释）。**文案指错方向，比没有文案更费时间。**

## 「在跑」和「失败」要分开说

都说成「尚未完成」的话，真失败的那些会被一直干等下去——
而它们需要的是有人去点重试。
"""

from __future__ import annotations

from typing import Any

OCR_DONE_STATUSES = {"已识别", "人工修正", "抽取不完整"}


def pipeline_stage_of(
    document: dict[str, Any],
    version: dict[str, Any],
    knowledge_file: dict[str, Any],
) -> dict[str, Any] | None:
    """没就绪时返回**卡在哪一段**；三段都就绪返回 None。

    按 OCR → 切片 → 向量化的顺序返回第一个没过的：后面那些还没轮到，
    报它们只会让人去看一个根本还没开始的环节。
    """
    ocr_status = str(
        document.get("currentOcrStatus")
        or version.get("ocrStatus")
        or knowledge_file.get("ocrStatus")
        or ""
    )
    slice_status = str(knowledge_file.get("sliceStatus") or version.get("sliceStatus") or "")
    vector_status = str(knowledge_file.get("vectorStatus") or version.get("vectorStatus") or "")
    if ocr_status not in OCR_DONE_STATUSES:
        return {"stage": "ocr", "stageLabel": "文字识别", "status": ocr_status or "未开始"}
    # 报审只要求 OCR 完成。切片/向量化曾是前置，但审查读的是 OCR 证据——
    # 项目资料的向量在整个系统里消费者为零（检索只查规范条款），
    # 拿它当报审门槛只会让施工方被一个无意义的环节卡住
    # （2026-08-29 审计：积压的 67 份「未切片」全被这道门挡在报审外）。
    # 项目资料已不再切片/向量化（见 task_dispatcher.project_file_indexing_blocker），
    # slice_status / vector_status 对报审不再有含义。
    _ = (slice_status, vector_status)
    return None


def pipeline_incomplete_message(blocked: list[dict[str, Any]]) -> str:
    """按卡住的环节说人话，并告诉对方这是等待还是出错。"""
    if not blocked:
        return "资料处理尚未完成，暂不能提交。"
    labels = list(dict.fromkeys(str(item.get("stageLabel") or "处理") for item in blocked))
    failed = [item for item in blocked if "失败" in str(item.get("status") or "")]
    scope = "、".join(labels)
    if failed:
        reasons = list(dict.fromkeys(str(item.get("reason") or "") for item in failed if item.get("reason")))
        if reasons:
            # 有确切原因就直说，别让人去「重试」一件重试一百次也不会变的事
            return f"资料的{scope}未完成：{'；'.join(reasons)}。"
        return f"资料的{scope}未完成（有处理失败），请在资料详情里重试后再提交。"
    return f"资料的{scope}还在进行中，等它完成后即可提交。"
