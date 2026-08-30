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


def test_stuck_reconciler_ignores_project_files() -> None:
    """收敛器只该管标准库。

    项目资料不做切片/向量化，它们身上的「待切片/待向量化」是架构调整前的
    历史残留。不排除的后果不是派错任务（派发层会拦），而是**每小时报一次
    「卡住 52 份」**——运维以为有积压，真正该关注的标准库积压淹没在噪音里
    （2026-08-30 实测：52 份项目资料 / 0 份标准库）。
    """
    source = (BACKEND_ROOT / "scripts" / "reconcile_stuck_index_tasks.py").read_text(encoding="utf-8")
    assert "project_sources" in source
    assert 'sourceType") or "") in {"project-file", "project_file"}' in source
    scan = source.split("for file in repo.state.get", 1)[1][:400]
    assert "project_sources" in scan, "扫描时必须跳过项目资料"


def test_project_file_requeue_script_refuses_by_default() -> None:
    """专给项目资料补切片的脚本，使命已结束——要明确拒绝，不能静默空转。

    它的判据就是 projectId 且非 standard，实测会捡起全部 211 份项目资料、
    0 份标准库。静默跑一趟只会报出一个吓人的假积压。
    """
    source = (BACKEND_ROOT / "scripts" / "requeue_index_backlog.py").read_text(encoding="utf-8")
    assert "AICHECK_PROJECT_FILE_INDEXING" in source, "要靠开关放行，不是硬删"
    assert "raise SystemExit(0)" in source, "默认必须提前退出"
    guard = source.split("AICHECK_PROJECT_FILE_INDEXING", 1)[1][:400]
    assert "reprocess_index_backlog" in guard, "要指路到正确的工具"
