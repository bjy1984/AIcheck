"""P12 F1 采集字段的组装（从 routes.py 拆出：巨石棘轮不许 routes.py 再长）。

发现级反馈带 findingId；"其实有依据"带具体断言；人工结论与 AI 不一致时带根因与两边结论；
source 标明入口（结论卡 / 采纳 / 驳回 / 审查意见）。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time

# 人工结论与 AI 不一致时的"为什么"单选（P12 F2 七类根因的采集端子集）。
AI_FEEDBACK_ROOT_CAUSES = {
    "data_table",  # A 数据表/限值
    "rule_logic",  # B 确定性规则
    "guard_downgrade",  # C 守卫误杀
    "evidence_extraction",  # D 证据抽取
    "prompt",  # E 提示词
    "policy",  # F 业务口径
    "external_source",  # G 外部源
    "other",
}


def build_ai_feedback_record(
    run: dict[str, Any],
    run_id: str,
    body: dict[str, Any],
    *,
    feedback_type: str,
    compact: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """返回 (反馈记录, 错误信息)。rootCause 不在词表里就拒绝——自由文本进不了分类统计。"""
    root_cause = compact(body.get("rootCause"), 40)
    if root_cause and root_cause not in AI_FEEDBACK_ROOT_CAUSES:
        return None, "AI 反馈根因不支持。"
    finding_id = compact(body.get("findingId"), 120)
    record = {
        "id": body.get("id") or f"AIFB-{uuid4().hex[:8].upper()}",
        "aiRunId": run_id,
        "projectId": run["projectId"],
        "nodeId": run["nodeId"],
        "agentId": run.get("agentId"),
        "agentVersion": run.get("agentVersion"),
        "businessPackId": run.get("businessPackId"),
        "businessPackVersion": run.get("businessPackVersion"),
        "feedbackType": feedback_type,
        "accepted": bool(body.get("accepted", False)),
        "comment": body.get("comment") or body.get("reason"),
        "correctedOutput": body.get("correctedOutput"),
        "shouldEnterEvaluationSet": bool(body.get("shouldEnterEvaluationSet", False)),
        "findingId": finding_id or None,
        "claim": compact(body.get("claim"), 200) or None,
        "rootCause": root_cause or None,
        "source": compact(body.get("source"), 40) or None,
        "humanResult": compact(body.get("humanResult"), 40) or None,
        "suggestedResult": compact(body.get("suggestedResult"), 40) or None,
        "createdAt": server_time(),
    }
    return record, None


def confirms_whole_run(record: dict[str, Any]) -> bool:
    """只有对整次运行的采纳才把运行标"已人工确认"；采纳单条发现不代表认可整次结论。"""
    return bool(record.get("accepted")) and not record.get("findingId")


def latest_ai_run_id(state: dict[str, Any], project_id: str, node_id: int) -> str | None:
    return next(
        (
            item.get("id")
            for item in state.get("ai_runs", [])
            if item.get("projectId") == project_id and int(item.get("nodeId") or 0) == int(node_id)
        ),
        None,
    )
