"""报审被拦时要说清卡在哪一段。

## 为什么单独立一个用例

三个提交入口原先都报「文件上传处理尚未成功，暂不能提交」。可上传早就
成功了——卡住的是它后面的切片或向量化。线上真按这句话查过上传：
文件在、大小对、OCR 显示已识别，什么问题也查不出来，而真身是切片
从没被派过队（见 tasks.py 里 MinerU 那处 dispatch_slice 注释）。

文案指错方向，比没有文案更费时间。这里钉住三件事：
分得清环节、区分「在跑」和「失败」、就绪时不拦。
"""

from __future__ import annotations

import pytest

from apps.api.routes import (
    document_upload_pipeline_complete,
    document_upload_pipeline_stage,
    pipeline_incomplete_message,
)
from libs.db.repository import repo


@pytest.fixture
def _doc():
    document = {"id": "DOC-STAGE-TEST", "currentVersionId": "DV-STAGE-TEST"}
    knowledge_file = {
        "id": "KF-STAGE-TEST",
        "documentVersionId": "DV-STAGE-TEST",
        "ocrStatus": "已识别",
        "sliceStatus": "已切片",
        "vectorStatus": "已向量化",
    }
    repo.state.setdefault("documents", []).insert(0, document)
    repo.state.setdefault("knowledge_files", []).insert(0, knowledge_file)
    yield document, knowledge_file
    repo.state["documents"] = [
        item for item in repo.state["documents"] if item.get("id") != document["id"]
    ]
    repo.state["knowledge_files"] = [
        item for item in repo.state["knowledge_files"] if item.get("id") != knowledge_file["id"]
    ]


def test_三段都就绪时不拦(_doc):
    document, _ = _doc
    assert document_upload_pipeline_stage(document) is None
    assert document_upload_pipeline_complete(document) is True


def test_卡在切片时指名切片(_doc):
    """线上真实形态：OCR 已识别、切片没排上队。

    原文案说「上传处理尚未成功」，让人去查上传——那里根本没有问题。
    """
    document, knowledge_file = _doc
    knowledge_file["sliceStatus"] = "待切片"
    knowledge_file["vectorStatus"] = "待向量化"
    stage = document_upload_pipeline_stage(document)
    assert stage["stage"] == "slice"
    assert stage["stageLabel"] == "切片"
    message = pipeline_incomplete_message([{"documentId": document["id"], **stage}])
    assert "切片" in message
    assert "上传" not in message, "又把锅甩给上传了"


def test_卡在向量化时指名向量化(_doc):
    document, knowledge_file = _doc
    knowledge_file["vectorStatus"] = "待向量化"
    stage = document_upload_pipeline_stage(document)
    assert stage["stage"] == "vector"
    assert "向量化" in pipeline_incomplete_message([{"documentId": document["id"], **stage}])


def test_ocr_未完成时才说识别(_doc):
    document, knowledge_file = _doc
    document["currentOcrStatus"] = "识别中"
    knowledge_file["ocrStatus"] = "识别中"
    stage = document_upload_pipeline_stage(document)
    assert stage["stage"] == "ocr"
    assert "文字识别" in pipeline_incomplete_message([{"documentId": document["id"], **stage}])


def test_失败和进行中要说得不一样(_doc):
    """「在跑，等一下」和「挂了，去重试」是两种完全不同的下一步。

    都说成「尚未完成」的话，真失败的那些会被一直干等下去。
    """
    waiting = pipeline_incomplete_message(
        [{"documentId": "D1", "stage": "slice", "stageLabel": "切片", "status": "待切片"}]
    )
    failed = pipeline_incomplete_message(
        [{"documentId": "D1", "stage": "slice", "stageLabel": "切片", "status": "切片失败"}]
    )
    assert "进行中" in waiting
    assert "失败" in failed and "重试" in failed
    assert waiting != failed


def test_全部被判为噪声时要说清原因() -> None:
    """「切片失败」不够——用户会反复重传同一份文件。

    0819 线上实测：一份纯英文资料的文本整份被 symbol_ascii_only 隔离
    （规则本身没错：中文语料里纯 ASCII 片段多是页眉页脚页码）。
    资料传上来了、文字也认出来了，只是内容被当成干扰整份丢掉——
    这种情况重试一百次也不会变，必须直说原因。
    """
    from apps.api.submission_pipeline import pipeline_stage_of

    stage = pipeline_stage_of(
        {"currentOcrStatus": "已识别"},
        {},
        {"sliceStatus": "切片失败", "sliceStatusReason": "all_chunks_quarantined"},
    )
    assert stage is not None
    assert stage["stage"] == "slice"
    assert "噪声" in str(stage.get("reason") or ""), "没有把隔离原因带出来"

    message = pipeline_incomplete_message([stage])
    assert "噪声" in message, f"提示里没说原因：{message}"
    assert "重试" not in message, f"还在让用户重试一件重试也没用的事：{message}"


def test_切片确实在进行中时仍然说等待() -> None:
    """别把「还在跑」也说成失败——那会让人以为要去处理什么。"""
    from apps.api.submission_pipeline import pipeline_stage_of

    stage = pipeline_stage_of({"currentOcrStatus": "已识别"}, {}, {"sliceStatus": "切片中"})
    message = pipeline_incomplete_message([stage])
    assert "还在进行中" in message, message
