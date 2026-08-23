"""标准条款库不许走通用重建管线。

## 这条护栏来自一次真实的数据损坏

dispatch_knowledge_file_index_pipeline 会先清掉派生索引、再用**通用切片器**
重建。项目资料没问题（OCR 正文按长度切），标准库不行——它的分块由专用摄取
路径生成、与条款一一对齐（2134 分块对 2134 向量）。

0819 拿这条管线去给标准库换向量模型，结果：31 份标准的分块直接归零，
另 29 份被切成完全不同的粒度（13594 个碎块）。靠迁移前的备份才救回来。

**它不报错**：切片任务返回 succeeded，只是 chunkCount 为 0。等发现时
分块已经没了。所以护栏要挡在入口，而不是指望事后看出来。

正确做法：只换模型用 dispatch_embed（保留分块）；只回填 pgvector 走
scripts/backfill_knowledge_pgvector.py；重建分块走
scripts/reocr_standards_with_mineru.py。
"""

from __future__ import annotations

import pytest

from apps.api.routes import dispatch_knowledge_file_index_pipeline


def test_标准库文件会被直接拒绝() -> None:
    file = {
        "id": "KF-KB-TEST",
        "sourceType": "standard",
        "fileName": "GB 50235-2010 工业金属管道工程施工规范.pdf",
        "documentId": "KDOC-TEST",
        "documentVersionId": "KDV-TEST",
        "chunkCount": 40,
    }
    with pytest.raises(ValueError) as raised:
        dispatch_knowledge_file_index_pipeline(file, reason="测试")
    assert "standard_library_uses_dedicated_ingestion" in str(raised.value)
    # 拒绝要发生在**清空之前**：先清后拒等于照样把分块弄丢了
    assert file["chunkCount"] == 40, "拒绝之前就把分块清了——护栏白加"
    assert "sliceStatus" not in file, "拒绝之前就改了切片状态"


def test_项目资料不受影响() -> None:
    """护栏只挡标准库。挡过头的话，项目资料的重建入口就没了。"""
    file = {"id": "KF-DOC-TEST", "sourceType": "project-file", "documentId": "X", "documentVersionId": "Y"}
    with pytest.raises(ValueError) as raised:
        dispatch_knowledge_file_index_pipeline(file, reason="测试")
    # 走到了找不到文档那一步，说明没有被标准库护栏拦下
    assert "missing_document_version" in str(raised.value)
