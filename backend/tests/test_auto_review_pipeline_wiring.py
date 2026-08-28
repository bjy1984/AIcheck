"""自动审查链路的两处断裂（2026-08-29 审计实锤）钉死。

实测：「每上传自动分析」开关自上线起从未生效——
1. OCR worker 的状态加载范围不含 auto_review_policies，enqueue 守卫
   永远读到空策略，静默跳过（连事件都不产生）；
2. compose 权威声明 business worker 带 -B（内嵌 beat），部署脚本重建时
   把 -B 弄丢，四个 60 秒周期任务（consume/scan/start/finalize）从不执行。
"""

from __future__ import annotations

import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_ocr_worker_state_scope_includes_auto_review_collections() -> None:
    from libs.db.repository import OCR_WORKER_STATE_KEYS_FOR_SQLITE

    assert "auto_review_policies" in OCR_WORKER_STATE_KEYS_FOR_SQLITE
    assert "auto_review_outbox" in OCR_WORKER_STATE_KEYS_FOR_SQLITE
    # postgres 侧的 scoped 加载是方法内联元组，用文本钉住（两份清单必须同步改）
    source = (BACKEND_ROOT / "libs" / "db" / "repository.py").read_text(encoding="utf-8")
    scoped = source.split("Load only state needed by one OCR task", 1)[1][:2000]
    assert '"auto_review_policies"' in scoped
    assert '"auto_review_outbox"' in scoped


def test_mineru_task_refresh_scope_includes_auto_review_policies() -> None:
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    mineru = source.split("def _execute_mineru_ocr_extract", 1)[1][:1200]
    assert '"auto_review_policies"' in mineru
    assert '"auto_review_outbox"' in mineru


def test_deploy_script_keeps_embedded_beat_on_business_worker() -> None:
    """compose 权威声明 -B；部署脚本不许再把它弄丢。"""
    script = (BACKEND_ROOT / "scripts" / "deploy_to_server.sh").read_text(encoding="utf-8")
    business_line = next(
        line for line in script.splitlines() if "recreate_worker aicheck-worker-business" in line
    )
    assert " -B " in business_line, "business worker 必须内嵌 beat，否则 auto_review 周期任务从不执行"
    assert "--schedule=" in business_line
    compose = (BACKEND_ROOT / "docker-compose.deploy.yml").read_text(encoding="utf-8")
    assert "worker -B" in compose  # 两份声明保持一致


def test_scoped_auto_review_tasks_never_flush_singletons() -> None:
    """scoped load 没有加载 admin_config 等单例，flush 默认却带全部单例——
    每轮都试图用空内容覆写 admin_config，被并发守卫拦下后四个周期任务
    互相撞成重试风暴（实测每轮 3-6 次 Concurrent singleton 重试，
    scan 有重试耗尽直接 ERROR 的记录）。三个 scoped 任务必须显式排除单例。"""
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    for task_name in (
        "def auto_review_consume_evidence_events",
        "def auto_review_scan_due_projects",
        "def auto_review_finalize_project_runs",
    ):
        body = source.split(task_name, 1)[1][:1400]
        assert "selected_singleton_keys=set()" in body, task_name


def test_periodic_tasks_are_mutexed_against_overlap() -> None:
    """beat 60 秒一发、任务耗时可超 60 秒：实例互叠在 evidence_snapshots 上
    撞成活锁（实测三实例互相 ConcurrentPersistenceError 重试，候选永远
    pending）。四个周期任务必须有进程外互斥，拿不到锁就让位本轮。"""
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    for task_name in (
        "auto_review_consume_evidence_events",
        "auto_review_scan_due_projects",
        "auto_review_start_pending_candidates",
        "auto_review_finalize_project_runs",
    ):
        head = source.split(f"def {task_name}", 1)[0][-400:]
        assert 'pipeline_task_lock("auto-review-periodic"' in head, task_name


def test_evidence_change_invalidates_session_tool_memory(monkeypatch) -> None:
    """新证据自动挂载后，会话工具记忆必须失效——否则监检人员第二次问
    「核对资质」拿到的是缓存的旧核对结果，新证书根本不进视野。"""
    from apps.api import routes
    from apps.api.review_session_evidence import (
        refresh_review_session_evidence_fingerprint,
    )

    routes.repo.state["node_evidence_links"] = [
        {"id": "NEL-1", "projectId": "P-1", "nodeId": 24, "revision": 1, "manualStatus": "confirmed"}
    ]
    routes.repo.state["bindings"] = []
    routes.repo.state["review_session_events"] = []
    session = {"id": "RS-1", "projectId": "P-1", "nodeId": 24, "toolMemoryRevision": 0}

    # 首次：只记指纹不失效（记忆本来是空的）
    assert refresh_review_session_evidence_fingerprint(session) is False
    assert session["toolMemoryRevision"] == 0
    # 证据没变：不失效
    assert refresh_review_session_evidence_fingerprint(session) is False
    # 自动挂载新证书（不经过会话上下文端点）：必须失效
    routes.repo.state["node_evidence_links"].append(
        {"id": "NEL-2", "projectId": "P-1", "nodeId": 24, "revision": 1, "manualStatus": "pending"}
    )
    assert refresh_review_session_evidence_fingerprint(session) is True
    assert session["toolMemoryRevision"] == 1
    # 驳回一份（状态变化同样是证据变化）
    routes.repo.state["node_evidence_links"][0]["manualStatus"] = "rejected"
    assert refresh_review_session_evidence_fingerprint(session) is True
    assert session["toolMemoryRevision"] == 2
