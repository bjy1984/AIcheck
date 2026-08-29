"""自动审查派发必须异步——不能在周期锁内同步跑 inline 审查。

dispatch_pending_auto_review_candidates 持有 auto-review-periodic 锁，
其中 _start_auto_review_node → ai_recheck → dispatch_ai_recheck。
若 orchestration=inline，会在锁内同步跑完整审查（含 LLM，多节点串行几分钟），
锁被长期占用 → 后续每个 beat 全 duplicate_inflight → 自动派发永久卡死且无自愈
（2026-08-29 生产实测：NDT 候选一直 pending，持锁连接 idle 但不释放）。
"""

from __future__ import annotations

import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_dispatch_ai_recheck_supports_force_async() -> None:
    source = (BACKEND_ROOT / "libs" / "integrations" / "task_dispatcher.py").read_text(encoding="utf-8")
    assert "force_async" in source, "dispatch_ai_recheck 必须支持强制异步"
    # force_async 分支必须在 inline/temporal 分支之前，否则 inline 仍会同步执行
    body = source.split("def dispatch_ai_recheck", 1)[1][:900]
    force_pos = body.index("if force_async")
    inline_pos = body.index('orchestration_mode in {"temporal", "inline"}')
    assert force_pos < inline_pos, "force_async 必须优先于 inline 分支"
    assert ".delay(" in body[force_pos:inline_pos], "force_async 必须走异步 .delay"


def test_auto_review_path_forces_async() -> None:
    source = (BACKEND_ROOT / "apps" / "api" / "routes.py").read_text(encoding="utf-8")
    assert "auto_review_dispatch = body.get(\"autoReviewPolicyRevision\")" in source
    assert "force_async=auto_review_dispatch" in source
