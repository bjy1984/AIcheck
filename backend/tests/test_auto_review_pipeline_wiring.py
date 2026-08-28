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
