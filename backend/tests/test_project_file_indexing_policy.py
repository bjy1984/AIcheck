"""项目资料不做切片/向量化——架构决策的契约。

项目资料是**被审查的对象**，不是检索语料。检索的所有消费者（审查执行、
节点标准依据、FDE 评测、健康探针）都在找规范条款；项目资料混入等于
用被审对象当审查依据。2026-08-29 生产审计：向量库 53%（6118 条）是
项目文件、消费者为零、哈希伪向量全部来自这批，且它们是 cpu.heavy
积压的大头（单份图纸上千分块）。

三层收口：检索候选排除、派发层拦截、报审/分析门槛放宽到 OCR。
"""

from __future__ import annotations

import pathlib

from libs.integrations import task_dispatcher

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _seed_project_file(repo_module):
    repo = repo_module.repo
    repo.state.setdefault("knowledge_sources", []).append(
        {"id": "KS-PROJECT-FILE", "sourceType": "project-file", "enabled": True}
    )
    repo.state.setdefault("knowledge_files", []).append(
        {"id": "KF-TEST-PF-1", "sourceId": "KS-PROJECT-FILE", "fileName": "施工方案.pdf"}
    )


def test_dispatch_slice_blocks_project_file(monkeypatch) -> None:
    from libs.db import repository

    _seed_project_file(repository)
    try:
        result = task_dispatcher.dispatch_slice("KF-TEST-PF-1")
        assert result.get("statusReason") == "project_file_indexing_disabled"
        assert result.get("taskId") is None
    finally:
        repository.repo.state["knowledge_files"] = [
            f for f in repository.repo.state["knowledge_files"] if f.get("id") != "KF-TEST-PF-1"
        ]


def test_dispatch_embed_blocks_project_file(monkeypatch) -> None:
    from libs.db import repository

    _seed_project_file(repository)
    try:
        result = task_dispatcher.dispatch_embed("KF-TEST-PF-1")
        assert result.get("statusReason") == "project_file_indexing_disabled"
    finally:
        repository.repo.state["knowledge_files"] = [
            f for f in repository.repo.state["knowledge_files"] if f.get("id") != "KF-TEST-PF-1"
        ]


def test_override_switch_restores_indexing(monkeypatch) -> None:
    """AICHECK_PROJECT_FILE_INDEXING=true 保留后路（未来做项目资料语义搜索时）。"""
    monkeypatch.setenv("AICHECK_PROJECT_FILE_INDEXING", "true")
    assert task_dispatcher.project_file_indexing_blocker("KF-ANY") is None


def test_retrieval_candidates_exclude_project_files() -> None:
    source = (BACKEND_ROOT / "libs" / "knowledge_retrieval.py").read_text(encoding="utf-8")
    assert 'sourceType") == "project-file"' in source, "检索候选必须排除项目资料"


def test_submission_gate_is_ocr_only() -> None:
    """报审只要求 OCR：切片/向量化对项目资料已无含义，
    拿它们当门槛只会让施工方被无意义的环节卡住。"""
    source = (BACKEND_ROOT / "apps" / "api" / "submission_pipeline.py").read_text(encoding="utf-8")
    body = source.split("def pipeline_stage_of", 1)[1]
    gate = body.split("def ", 1)[0]
    assert '"stage": "slice"' not in gate, "报审不得再卡切片"
    assert '"stage": "vector"' not in gate, "报审不得再卡向量化"
    assert "OCR_DONE_STATUSES" in gate


def test_analysis_input_gate_dropped_slice_vector() -> None:
    source = (BACKEND_ROOT / "libs" / "material_targeting.py").read_text(encoding="utf-8")
    body = source.split("def unclassified_input_versions_for_project", 1)[1].split("def ", 1)[0]
    assert "sliceStatus" not in body, "分析输入不得再卡切片"
    assert "vectorStatus" not in body, "分析输入不得再卡向量化"


def test_ops_tools_scope_to_standard_library() -> None:
    for rel in ("scripts/reprocess_index_backlog.py", "scripts/health_watch.py"):
        source = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
        assert "project-file" in source, f"{rel} 必须把项目资料排除在索引口径外"
