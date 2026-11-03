"""Jev 插件：只做加强——逐项分歧提示、事实核对、表格行分类。

结论只来自规则、平台核验和计算（见 jev_usage_policy）。本模组只在审查选用 Jev
时才被登记表载入；各函式内部仍逐一检查部署层总开关（金钥、出境批准、阶段开关），
没开就回 disabled，不送出任何资料。
"""
from __future__ import annotations

from typing import Any

from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID, load_business_pack
from libs.review_orchestrator.jev_client import MODEL, jev_enabled
from libs.review_orchestrator.jev_fact_check import (
    certificate_fact_items,
    check_facts,
    design_fact_items,
    domain_record_fact_items,
    record_fact_items,
    welder_fact_items,
)
from libs.review_orchestrator.jev_primary import (
    attach_hints,
    author_node_questions,
    decide_node,
    jev_hint_summary,
)
from libs.review_orchestrator.jev_tables import classify_review_tables
from libs.security.tenant import tenant_id_for_record


def deployment_available() -> bool:
    """部署上能不能用（总开关、出境批准、金钥都到位）；只回布林，不泄露设定值。"""
    return jev_enabled()


def _pack(review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    project = context.get("project") or {}
    return project.get("businessPackSnapshot") or load_business_pack(
        str(review_run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID))


def classify_tables_step(state: dict[str, Any], review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if review_run.get("workflowEngine") != "temporal":
        return {"status": "skipped_inline"}
    classified = classify_review_tables(state, review_run)
    # 栏位名沿用旧名：R24–R34 的事实构建按表格内容杂凑读这份行角色预测，缺了就用固定解析。
    review_run["jevTableClassifications"] = classified
    return {"status": classified["status"], "classifiedTables": sum(
        len(rows) for rows in classified["tables"].values()),
        "overlongDocumentVersionIds": classified["overlongDocumentVersionIds"]}


def compose_questions_step(state: dict[str, Any], review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    plan = author_node_questions(state, review_run, context.get("ruleResults") or [], _pack(review_run, context),
                                 business_facts=context.get("businessFacts"))
    review_run["jevQuestionPlan"] = plan
    return {"status": plan["status"], "questionCount": len(plan.get("questions") or []), "model": plan.get("model")}


def decision_step(state: dict[str, Any], review_run: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    original = context.get("ruleResults") or []
    decision = decide_node(state, review_run, original, _pack(review_run, context),
                           review_run.get("jevQuestionPlan"), business_facts=context.get("businessFacts"))
    review_run["jevDecision"] = decision
    # Jev 只加提示、不改结论：规则、平台核验和计算结果照旧往下走。
    context["ruleResults"] = attach_hints(original, decision)
    # 规则用到的证书、设计试验要求等事实请 Jev 对原文核一遍：答「否」只标记抽取可疑（R02-02 那一类）。
    fact_check = check_facts(state, review_run,
                             certificate_fact_items(context.get("certificateVerification"))
                             + design_fact_items(context.get("businessFacts"), original)
                             + welder_fact_items(context.get("businessFacts"), original)
                             + record_fact_items(context.get("businessFacts"), original)
                             + domain_record_fact_items(context.get("businessFacts"), original))
    review_run["jevFactCheck"] = fact_check
    return {"status": decision["status"], "decisionCount": len(decision["atomic"]),
            "disagreementCount": len(decision.get("disagreementAtomicCheckIds") or []),
            "factCheckStatus": fact_check["status"], "factSuspectCount": len(fact_check.get("suspects") or [])}


STEPS = {
    "classify_ocr_tables": classify_tables_step,
    "qwen_compose_jev_questions": compose_questions_step,
    "jev_decision": decision_step,
}


def on_run_created(record: dict[str, Any], state: dict[str, Any]) -> None:
    """同工程同节点上一次的人工排队状态，第二意见的升降门槛要用。"""
    previous = next((item.get("jevQueueStatus") for item in state.get("review_runs", [])
                     if isinstance(item, dict) and item.get("projectId") == record.get("projectId")
                     and tenant_id_for_record(item) == record.get("tenantId")
                     and str(item.get("nodeId")) == str(record.get("nodeId"))
                     and isinstance(item.get("jevQueueStatus"), dict)), {})
    record["jevQueuePrevious"] = dict(previous)


def suggestion_fields(review_run: dict[str, Any]) -> dict[str, Any]:
    return jev_hint_summary(review_run.get("jevDecision"), review_run.get("jevFactCheck"))


def _completed(review_run: dict[str, Any]) -> bool:
    return (review_run.get("jevDecision") or {}).get("status") == "completed"


def prompt_requirements(review_run: dict[str, Any]) -> list[str]:
    # Jev 只作分歧提示（见 jev_primary.attach_hints）：结论以规则工具结果为准，不能让草稿替 Jev 立场。
    if not _completed(review_run):
        return []
    return [("jevDecision 只是 Jev 的逐项分歧提示，不是节点建议或原子项结论的来源。"
             "节点建议与各原子项结论一律以规则工具结果（ruleResults）为准，不得依据 Jev 的选择改写；"
             "两者不一致时只写明分歧所在的原子项，提示人工核对。")]


def prompt_payload(review_run: dict[str, Any]) -> dict[str, Any]:
    if not _completed(review_run):
        return {}
    plan = review_run.get("jevQuestionPlan") or {}
    return {"jevDecision": {"model": MODEL,
                            "questionAuthorModel": plan.get("actualModel") or plan.get("model"),
                            "questionPlanHash": plan.get("questionHash"),
                            "atomic": [{"atomicCheckId": row.get("atomicCheckId"),
                                        "choice": row.get("choice"), "confidence": row.get("confidence")}
                                       for row in (review_run.get("jevDecision") or {}).get("atomic") or []]}}
