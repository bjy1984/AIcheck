"""P12 F2：审计反馈指标（§17.3）——FDE / 管理员看板用；独立 router，不再往 routes.py 里加。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from apps.api.routes import fde_error_unless_allowed
from libs.contracts.responses import ok
from libs.db.repository import repo
from libs.feedback.metrics import compute_feedback_metrics, render_markdown

feedback_metrics_router = APIRouter()


@feedback_metrics_router.get("/fde/feedback/metrics")
def fde_feedback_metrics(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:feedback:view")
    if role_error:
        return role_error
    metrics = compute_feedback_metrics(repo.state)
    return ok({"metrics": metrics, "markdown": render_markdown(metrics)}, request)
