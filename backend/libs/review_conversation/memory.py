"""对话 Agent 记忆系统：会话工具记忆（依赖级失效/租户隔离）、事实台账、滚动摘要、情节记忆、治理化组织教训。

从 apps/api/routes.py 纯搬移抽离（B1 重构）；对 routes 命名空间的引用
统一经 _r() 晚绑定，保持 monkeypatch 与运行语义不变。
"""

from __future__ import annotations

import os
from fastapi import Request
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo
from typing import Any, Iterable
from uuid import uuid4


def _r():
    """晚绑定访问 apps.api.routes 命名空间。

    抽离前这些引用都是 routes 模块全局名（晚绑定）；统一经 _r() 访问保持
    完全相同的语义 —— 测试对 routes 属性的 monkeypatch（如 qwen_runtime_client、
    review_conversation_agent_tool_output）依然对本模块内部调用生效。
    """
    from apps.api import routes

    return routes


REVIEW_SESSION_TOOL_MEMORY_LIMIT = max(
    8, int(os.getenv("AICHECK_REVIEW_CONVERSATION_TOOL_MEMORY_LIMIT", "40"))
)
# 聚合整条判定链的工具不进入记忆：体量大、且应反映最新证据状态。
REVIEW_SESSION_TOOL_MEMORY_EXCLUDED_TOOLS = {"run_node_formal_judgment"}


def review_session_tool_memory_revision(session: dict[str, Any]) -> int:
    return int(session.get("toolMemoryRevision") or 0)


# ---- 细粒度记忆失效：依赖标记 ----
# 每条记忆记录 dependsOn（文档版本 id / 作用域标记），上下文动作只清除依赖
# 发生变化范围的条目。纯函数工具的输出完全由参数决定（签名即完整键），永不失效。

REVIEW_MEMORY_DEP_SESSION_CONTEXT = "__session_context__"
REVIEW_MEMORY_DEP_NODE_EVIDENCE = "__node_evidence__"

# 输出完全由入参决定的确定性工具：跨动作、跨消息永久可复用。
REVIEW_MEMORY_PURE_TOOLS = {
    "check_all_equal",
    "check_date_covers",
    "check_design_license_scope",
    "check_installation_license_scope",
    "decode_welder_qualification",
    "check_welder_work_coverage",
    "check_pressure_gauge_requirements",
    "check_pressure_test_parameters",
    "check_pressure_test_report_consistency",
    "validate_evidence_grounding",
}
# 读取会话/运行状态的上下文工具：任何会话上下文动作后都应失效。
REVIEW_MEMORY_SESSION_CONTEXT_TOOLS = {"get_review_context"}
# 隐式读取节点全量证据范围的工具：证据集合变化后应失效。
REVIEW_MEMORY_NODE_SCOPE_TOOLS = {"search_node_evidence", "assemble_node_judgment_facts"}


def review_tool_memory_dependencies(
    tool_name: str,
    arguments: dict[str, Any] | None,
    output: dict[str, Any] | None,
) -> list[str]:
    if tool_name in _r().REVIEW_MEMORY_PURE_TOOLS:
        return []
    deps: set[str] = set()
    explicit_ids = {
        str(item) for item in (arguments or {}).get("documentVersionIds") or [] if item
    }
    deps |= explicit_ids
    if tool_name in _r().REVIEW_MEMORY_SESSION_CONTEXT_TOOLS:
        deps.add(_r().REVIEW_MEMORY_DEP_SESSION_CONTEXT)
    if tool_name in _r().REVIEW_MEMORY_NODE_SCOPE_TOOLS or (
        not explicit_ids and tool_name in _r().DOCUMENT_SCOPED_CONVERSATION_TOOLS
    ):
        # 未指定文档时按节点全量证据范围执行，证据集合变化即失效。
        deps.add(_r().REVIEW_MEMORY_DEP_NODE_EVIDENCE)
    return sorted(deps)


def invalidate_review_session_tool_memory(
    session: dict[str, Any], scopes: set[str]
) -> int:
    """按依赖作用域清除会话记忆条目，返回清除数量。命中时发可观测事件并同步删除持久化行。"""
    if not scopes:
        return 0
    _r().ensure_review_session_state()
    session_id = session.get("id")
    session_tenant = _r().tenant_id_for_record(session)
    entries = repo.state["review_session_tool_memory"]
    removed_ids: list[str] = []
    kept: list[dict[str, Any]] = []
    for item in entries:
        depends_on = {str(dep) for dep in item.get("dependsOn") or []}
        if (
            item.get("sessionId") == session_id
            and _r().tenant_id_for_record(item) == session_tenant
            and scopes.intersection(depends_on)
        ):
            if item.get("id"):
                removed_ids.append(str(item["id"]))
            continue
        kept.append(item)
    # 事实台账同规则失效：依赖变化范围的事实一并清除。
    facts = repo.state.get("review_session_facts", [])
    removed_fact_ids: list[str] = []
    kept_facts: list[dict[str, Any]] = []
    for item in facts:
        depends_on = {str(dep) for dep in item.get("dependsOn") or []}
        if (
            item.get("sessionId") == session_id
            and _r().tenant_id_for_record(item) == session_tenant
            and scopes.intersection(depends_on)
        ):
            if item.get("id"):
                removed_fact_ids.append(str(item["id"]))
            continue
        kept_facts.append(item)
    if not removed_ids and not removed_fact_ids:
        return 0
    entries[:] = kept
    facts[:] = kept_facts
    if removed_ids:
        _r().persist_review_session_record_deletions("review_session_tool_memory", removed_ids)
    if removed_fact_ids:
        _r().persist_review_session_record_deletions("review_session_facts", removed_fact_ids)
    _r().append_review_session_event(
        session,
        event_type="session.memory.invalidated",
        title=f"会话记忆已按依赖失效（工具 {len(removed_ids)} 条 / 事实 {len(removed_fact_ids)} 条）",
        payload={
            "invalidatedCount": len(removed_ids),
            "invalidatedFactCount": len(removed_fact_ids),
            "scopes": sorted(scopes),
        },
    )
    return len(removed_ids) + len(removed_fact_ids)


def load_review_session_tool_memory(session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _r().ensure_review_session_state()
    # 持久化记忆：多 worker / Celery 执行前先从共享存储刷新，取到其他进程写入的条目。
    if _r().postgres_persistence_configured():
        try:
            _r().refresh_state_from_postgres_for_live_read({"review_session_tool_memory"})
        except Exception:  # noqa: BLE001 - 刷新失败退回本地视图
            pass
    revision = _r().review_session_tool_memory_revision(session)
    session_tenant = _r().tenant_id_for_record(session)
    memory: dict[str, dict[str, Any]] = {}
    for item in repo.state.get("review_session_tool_memory", []):
        if item.get("sessionId") != session.get("id"):
            continue
        # 租户隔离：持久化后记忆可能被跨租户加载，读取侧必须二次过滤。
        if _r().tenant_id_for_record(item) != session_tenant:
            continue
        if int(item.get("memoryRevision") if item.get("memoryRevision") is not None else -1) != revision:
            continue
        signature = str(item.get("signature") or "")
        if signature:
            memory[signature] = item
    return memory


def store_review_session_tool_memory(
    session: dict[str, Any],
    *,
    signature: str,
    tool_name: str,
    summary: str,
    output: dict[str, Any],
    arguments: dict[str, Any] | None = None,
) -> None:
    _r().ensure_review_session_state()
    entries = repo.state["review_session_tool_memory"]
    session_id = session.get("id")
    revision = _r().review_session_tool_memory_revision(session)
    existing = next(
        (
            item
            for item in entries
            if item.get("sessionId") == session_id
            and item.get("signature") == signature
            and int(item.get("memoryRevision") if item.get("memoryRevision") is not None else -1) == revision
        ),
        None,
    )
    if existing is not None:
        existing["summary"] = summary
        existing["output"] = _r().compact_llm_payload(repo.clone(output))
        existing["updatedAt"] = _r().server_time()
        _r().persist_review_session_records(review_session_tool_memory=[existing])
        return
    entry = {
        "id": f"RTMEM-{uuid4().hex[:10].upper()}",
        "schemaVersion": "ReviewSessionToolMemory@1",
        "sessionId": session_id,
        "tenantId": _r().tenant_id_for_record(session),
        "memoryRevision": revision,
        "signature": signature,
        "toolName": tool_name,
        "summary": summary,
        "dependsOn": _r().review_tool_memory_dependencies(tool_name, arguments, output),
        "output": _r().compact_llm_payload(repo.clone(output)),
        "createdAt": _r().server_time(),
        "updatedAt": _r().server_time(),
    }
    entries.insert(0, entry)
    _r().persist_review_session_records(review_session_tool_memory=[entry])
    session_entries = [item for item in entries if item.get("sessionId") == session_id]
    evicted_ids: list[str] = []
    for stale in session_entries[_r().REVIEW_SESSION_TOOL_MEMORY_LIMIT:]:
        entries.remove(stale)
        if stale.get("id"):
            evicted_ids.append(str(stale["id"]))
    if evicted_ids:
        _r().persist_review_session_record_deletions("review_session_tool_memory", evicted_ids)


# ---- 相关性排序的上下文组装 ----
# 候选项（证据/条款/事实/工具摘要）按与当前问题的词面相关性选入配额，取代
# 固定「盲取最近 N 条」；问题无信息量（全零分）时退回原有新近度顺序。
# 词面匹配为确定性算法（ASCII 词 + 中文双字组），零模型成本、可测试；
# embedding 语义排序留作后续增强。


REVIEW_SESSION_FACT_LIMIT = max(
    24, int(os.getenv("AICHECK_REVIEW_CONVERSATION_FACT_LIMIT", "120"))
)
REVIEW_SESSION_FACT_CONTEXT_LIMIT = max(
    8, int(os.getenv("AICHECK_REVIEW_CONVERSATION_FACT_CONTEXT_LIMIT", "24"))
)
_FACT_NAME_KEYS = ("fieldCode", "code")
_FACT_VALUE_KEYS = ("fieldValue", "value")


def _normalized_fact_value(value: Any) -> str:
    return " ".join(str(value).split())[:300]


def extract_facts_from_tool_output(
    tool_name: str,
    arguments: dict[str, Any] | None,
    output: dict[str, Any] | None,
    *,
    max_facts: int = 40,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if not isinstance(output, dict):
        return facts
    if str(output.get("status") or "succeeded") in {"failed", "rejected"}:
        return facts
    if tool_name in _r().REVIEW_MEMORY_SESSION_CONTEXT_TOOLS or tool_name == "search_node_evidence":
        # 上下文/检索类输出是状态与候选，不是事实。
        return facts
    if tool_name in _r().REVIEW_MEMORY_PURE_TOOLS:
        verdict = output.get("result") or output.get("decision") or output.get("status")
        if verdict is not None:
            facts.append(
                {
                    "entity": "deterministic_check",
                    "attribute": f"{tool_name}:{_r().stable_hash_payload(arguments or {})[7:19]}",
                    "value": _r()._normalized_fact_value(verdict),
                    "documentVersionId": None,
                    "pageNo": None,
                }
            )
        return facts

    def walk(node: Any, doc_id: str | None, page: Any) -> None:
        if len(facts) >= max_facts:
            return
        if isinstance(node, dict):
            doc_id = str(node.get("documentVersionId") or doc_id or "") or None
            if node.get("pageNo") is not None:
                page = node.get("pageNo")
            name = next((node[key] for key in _r()._FACT_NAME_KEYS if node.get(key)), None)
            value = next(
                (node[key] for key in _r()._FACT_VALUE_KEYS if node.get(key) not in (None, "")),
                None,
            )
            if name and value is not None and not isinstance(value, (dict, list)):
                facts.append(
                    {
                        "entity": doc_id or "node",
                        "attribute": str(name)[:120],
                        "value": _r()._normalized_fact_value(value),
                        "documentVersionId": doc_id,
                        "pageNo": page,
                    }
                )
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child, doc_id, page)
        elif isinstance(node, list):
            for item in node[:40]:
                walk(item, doc_id, page)

    walk(output, None, None)
    return facts


def store_review_session_facts(
    session: dict[str, Any],
    *,
    tool_name: str,
    arguments: dict[str, Any] | None,
    output: dict[str, Any],
) -> None:
    extracted = _r().extract_facts_from_tool_output(tool_name, arguments, output)
    if not extracted:
        return
    _r().ensure_review_session_state()
    ledger = repo.state["review_session_facts"]
    session_id = session.get("id")
    session_tenant = _r().tenant_id_for_record(session)
    deps_base = _r().review_tool_memory_dependencies(tool_name, arguments, output)
    changed: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for fact in extracted:
        entity = fact["entity"]
        attribute = fact["attribute"]
        value = fact["value"]
        existing_same: dict[str, Any] | None = None
        conflict_partner: dict[str, Any] | None = None
        for item in ledger:
            if item.get("sessionId") != session_id:
                continue
            if _r().tenant_id_for_record(item) != session_tenant:
                continue
            if item.get("entity") == entity and item.get("attribute") == attribute:
                if item.get("value") == value:
                    existing_same = item
                else:
                    conflict_partner = item
        if existing_same is not None:
            # 事实级去重：不同工具产出同一事实 → 累计佐证。
            sources = sorted(set(existing_same.get("sources") or []) | {tool_name})
            existing_same["sources"] = sources
            existing_same["corroborationCount"] = len(sources)
            existing_same["lastConfirmedAt"] = _r().server_time()
            changed.append(existing_same)
            continue
        depends_on = set(deps_base)
        if fact.get("documentVersionId"):
            depends_on.add(str(fact["documentVersionId"]))
        record = {
            "id": f"RFACT-{uuid4().hex[:10].upper()}",
            "schemaVersion": "ReviewSessionFact@1",
            "sessionId": session_id,
            "tenantId": session_tenant,
            "entity": entity,
            "attribute": attribute,
            "value": value,
            "evidence": {
                "documentVersionId": fact.get("documentVersionId"),
                "pageNo": fact.get("pageNo"),
            },
            "sources": [tool_name],
            "corroborationCount": 1,
            "dependsOn": sorted(depends_on),
            "conflict": False,
            "firstSeenAt": _r().server_time(),
            "lastConfirmedAt": _r().server_time(),
        }
        if conflict_partner is not None:
            record["conflict"] = True
            if not conflict_partner.get("conflict"):
                conflict_partner["conflict"] = True
                changed.append(conflict_partner)
            conflicts.append(
                {
                    "entity": entity,
                    "attribute": attribute,
                    "values": [conflict_partner.get("value"), value],
                }
            )
        ledger.insert(0, record)
        changed.append(record)
    session_facts = [item for item in ledger if item.get("sessionId") == session_id]
    if len(session_facts) > _r().REVIEW_SESSION_FACT_LIMIT:
        # 容量淘汰：佐证少且最久未确认的先出。
        overflow = sorted(
            session_facts,
            key=lambda item: (
                int(item.get("corroborationCount") or 1),
                str(item.get("lastConfirmedAt") or ""),
            ),
        )
        evicted = overflow[: len(session_facts) - _r().REVIEW_SESSION_FACT_LIMIT]
        evicted_ids = [str(item["id"]) for item in evicted if item.get("id")]
        for item in evicted:
            ledger.remove(item)
        _r().persist_review_session_record_deletions("review_session_facts", evicted_ids)
    if changed:
        _r().persist_review_session_records(review_session_facts=changed)
    for conflict in conflicts[:3]:
        _r().append_review_session_event(
            session,
            event_type="session.fact.conflict",
            title=f"事实冲突：{conflict['attribute']}",
            payload=conflict,
        )


def load_review_session_fact_ledger(
    session: dict[str, Any], *, limit: int | None = None
) -> list[dict[str, Any]]:
    _r().ensure_review_session_state()
    if _r().postgres_persistence_configured():
        try:
            _r().refresh_state_from_postgres_for_live_read({"review_session_facts"})
        except Exception:  # noqa: BLE001 - 刷新失败退回本地视图
            pass
    session_tenant = _r().tenant_id_for_record(session)
    facts = [
        item
        for item in repo.state.get("review_session_facts", [])
        if item.get("sessionId") == session.get("id")
        and _r().tenant_id_for_record(item) == session_tenant
    ]
    # 冲突优先展示，其次佐证多者与最近确认者。
    facts.sort(
        key=lambda item: (
            not bool(item.get("conflict")),
            -int(item.get("corroborationCount") or 1),
            str(item.get("lastConfirmedAt") or ""),
        )
    )
    selected = facts[: limit or _r().REVIEW_SESSION_FACT_CONTEXT_LIMIT]
    return [
        {
            "documentVersionId": (item.get("evidence") or {}).get("documentVersionId"),
            "attribute": item.get("attribute"),
            "value": item.get("value"),
            "pageNo": (item.get("evidence") or {}).get("pageNo"),
            "sources": int(item.get("corroborationCount") or 1),
            "conflict": bool(item.get("conflict")),
        }
        for item in selected
    ]


# ---- 滚动结构化会话摘要（conversation digest） ----
# 确定性抽取（零模型成本），随会话记录持久化：每轮的问题/结论摘要、已用工具与
# 答案中标注的证据缺口。保留超出 recentConversation 原文窗口的长程上下文。

REVIEW_CONVERSATION_DIGEST_LIMIT = max(
    4, int(os.getenv("AICHECK_REVIEW_CONVERSATION_DIGEST_LIMIT", "12"))
)
REVIEW_CONVERSATION_GAP_TOKENS = ("证据不足", "需补正", "需人工确认", "缺失")


def update_review_session_conversation_digest(
    session: dict[str, Any],
    *,
    user_text: str,
    answer_text: str | None,
    tools_used: list[str] | None,
    message_id: str,
    execution_mode: str,
) -> None:
    digest = session.get("conversationDigest")
    if not isinstance(digest, dict):
        digest = {"exchanges": [], "gaps": []}
    answer = str(answer_text or "").strip()
    gaps: list[str] = []
    for line in answer.splitlines():
        stripped = line.strip()
        if stripped and any(token in stripped for token in _r().REVIEW_CONVERSATION_GAP_TOKENS):
            gaps.append(stripped[:160])
        if len(gaps) >= 3:
            break
    exchange = {
        "messageId": message_id,
        "question": str(user_text or "")[:200],
        "answerSummary": answer.split("\n", 1)[0][:300],
        "toolsUsed": sorted({str(item) for item in tools_used or [] if item})[:8],
        "mode": execution_mode,
        "gaps": gaps,
        "at": _r().server_time(),
    }
    exchanges = [item for item in digest.get("exchanges") or [] if isinstance(item, dict)]
    exchanges.append(exchange)
    digest["exchanges"] = exchanges[-_r().REVIEW_CONVERSATION_DIGEST_LIMIT:]
    # 汇总仍在窗口内的证据缺口（去重保序），供后续回答主动承接。
    open_gaps: list[str] = []
    for item in digest["exchanges"]:
        for gap in item.get("gaps") or []:
            if gap not in open_gaps:
                open_gaps.append(gap)
    digest["gaps"] = open_gaps[-6:]
    digest["updatedAt"] = _r().server_time()
    session["conversationDigest"] = digest


# ---- 治理化组织记忆（review lessons） ----
# 把历史人工反馈（ai_feedback）确定性蒸馏为「经验教训」，走与规则同级的治理
# 生命周期：draft →（人工核准）published →（下线）retired。只有 published 状态
# 的教训才会注入提示——未经审核的记忆不得影响判定（与条款包固化同一原则）。
# 蒸馏只使用人工撰写的反馈评语，模型自由文本不参与。

REVIEW_LESSON_CONTEXT_LIMIT = max(
    1, int(os.getenv("AICHECK_REVIEW_CONVERSATION_LESSON_LIMIT", "6"))
)
REVIEW_LESSON_GOVERNANCE_ROLES = {"admin", "inspection"}
REVIEW_LESSON_FEEDBACK_GUIDANCE = {
    "rejected_false_positive": "该节点曾出现误报（人工驳回）：{comment}。给出“不符合”结论前，须确认证据确实支持该判定。",
    "hallucination": "该节点曾出现无据结论：{comment}。所有结论必须引用工具返回的 basisRefId/evidenceLinkId，缺证据时明确说明。",
    "wrong_evidence": "该节点曾错误引用证据：{comment}。引用前须核对 evidenceLinkId 与文档定位一致。",
    "wrong_rule_reference": "该节点曾错误引用条款：{comment}。只能使用 fixedBasis 中的固化条款。",
    "wrong_severity": "该节点曾出现严重度判定偏差：{comment}。判定严重度时从保守侧把握并说明依据。",
    "missed_issue": "该节点曾漏检问题：{comment}。整体核查时应覆盖全部原子核查项，不要提前收束。",
}


def review_lesson_role_error(request: Request) -> _r().JSONResponse | None:
    role, identity_error = _r().effective_role_for_request(request)
    if identity_error:
        return identity_error
    if role not in _r().REVIEW_LESSON_GOVERNANCE_ROLES:
        return fail(
            errors.FORBIDDEN,
            request,
            message="仅监检人员或管理员可管理组织经验教训。",
            http_status=403,
        )
    return None


def distill_review_lessons_from_feedback(
    request: Request, *, node_id: int | None
) -> list[dict[str, Any]]:
    _r().ensure_review_session_state()
    tenant = _r().request_tenant_id(request)
    distilled_source_ids: set[str] = set()
    for lesson in repo.state.get("review_lessons", []):
        if _r().tenant_id_for_record(lesson) != tenant:
            continue
        distilled_source_ids.update(
            str(item) for item in lesson.get("sourceFeedbackIds") or [] if item
        )
    created: list[dict[str, Any]] = []
    for feedback in repo.state.get("ai_feedback", []):
        if not isinstance(feedback, dict):
            continue
        if _r().tenant_id_for_record(feedback) != tenant:
            continue
        feedback_type = str(feedback.get("feedbackType") or feedback.get("type") or "")
        template = _r().REVIEW_LESSON_FEEDBACK_GUIDANCE.get(feedback_type)
        if template is None:
            continue
        feedback_id = str(feedback.get("id") or "")
        if not feedback_id or feedback_id in distilled_source_ids:
            continue
        feedback_node = int(feedback.get("nodeId") or 0)
        if node_id is not None and feedback_node != node_id:
            continue
        comment = str(feedback.get("comment") or feedback.get("reason") or "").strip()
        lesson = {
            "id": f"RLESSON-{uuid4().hex[:10].upper()}",
            "schemaVersion": "ReviewLesson@1",
            "tenantId": tenant,
            "nodeId": feedback_node or None,
            "feedbackType": feedback_type,
            "title": (f"R{feedback_node:02d} {feedback_type}" if feedback_node else feedback_type),
            "guidance": template.format(comment=(comment[:200] or "见原始反馈")),
            "sourceFeedbackIds": [feedback_id],
            "status": "draft",
            "createdBy": _r().request_user_id(request) or "USER-UNKNOWN",
            "createdAt": _r().server_time(),
            "approvedBy": None,
            "approvedAt": None,
            "updatedAt": _r().server_time(),
        }
        repo.state["review_lessons"].insert(0, lesson)
        distilled_source_ids.add(feedback_id)
        created.append(lesson)
    if created:
        _r().persist_review_session_records(review_lessons=created)
    return created


def load_published_review_lessons(session: dict[str, Any]) -> list[dict[str, Any]]:
    """仅加载 published 教训：草稿与已下线者绝不注入提示（治理红线）。"""
    _r().ensure_review_session_state()
    if _r().postgres_persistence_configured():
        try:
            _r().refresh_state_from_postgres_for_live_read({"review_lessons"})
        except Exception:  # noqa: BLE001 - 刷新失败退回本地视图
            pass
    tenant = _r().tenant_id_for_record(session)
    node_id = int(session.get("nodeId") or 0)
    lessons = [
        item
        for item in repo.state.get("review_lessons", [])
        if str(item.get("status") or "") == "published"
        and _r().tenant_id_for_record(item) == tenant
        and (not item.get("nodeId") or int(item.get("nodeId") or 0) == node_id)
    ]
    lessons.sort(key=lambda item: str(item.get("approvedAt") or ""), reverse=True)
    return [
        {
            "title": item.get("title"),
            "guidance": item.get("guidance"),
            "scope": (f"R{int(item.get('nodeId') or 0):02d}" if item.get("nodeId") else "global"),
        }
        for item in lessons[:_r().REVIEW_LESSON_CONTEXT_LIMIT]
    ]


# ---- 跨会话情节记忆（episodic memory） ----
# 同一节点的历史人工裁定与历史 AI 结论。人工裁定是权威事实，可直接引用；
# 历史 AI 结论未经当前证据核查，只能作为线索——系统提示强制标注，防止锚定效应。

REVIEW_EPISODIC_MEMORY_LIMIT = max(
    1, int(os.getenv("AICHECK_REVIEW_CONVERSATION_EPISODIC_LIMIT", "3"))
)


def review_session_episodic_memory(session: dict[str, Any]) -> dict[str, Any]:
    project_id = str(session.get("projectId") or "")
    node_id = int(session.get("nodeId") or 0)
    project = repo.require_project(project_id) or {}
    project_tenant = _r().tenant_id_for_record(project)
    human_decisions: list[dict[str, Any]] = []
    prior_conclusions: list[dict[str, Any]] = []
    for run in repo.state.get("review_runs", []):
        if run.get("projectId") != project_id or int(run.get("nodeId") or 0) != node_id:
            continue
        if _r().tenant_id_for_record(run) != project_tenant:
            continue
        run_id = str(run.get("reviewRunId") or run.get("id") or "")
        decision = run.get("humanDecision")
        if isinstance(decision, dict) and decision:
            human_decisions.append(
                {
                    "reviewRunId": run_id,
                    "decision": str(decision.get("decision") or decision.get("result") or "")[:60],
                    "comment": str(decision.get("comment") or decision.get("opinion") or "")[:300],
                    "decidedAt": str(
                        decision.get("decidedAt")
                        or decision.get("createdAt")
                        or run.get("updatedAt")
                        or ""
                    ),
                    "authority": "human_decision",
                }
            )
        status = str(run.get("status") or "")
        if status:
            prior_conclusions.append(
                {
                    "reviewRunId": run_id,
                    "status": status,
                    "currentStep": run.get("currentStep"),
                    "findingCount": len(run.get("findingDrafts") or []),
                    "createdAt": str(run.get("createdAt") or ""),
                    "authority": "prior_ai_run_unverified",
                }
            )
    for opinion in repo.state.get("review_opinions", []):
        if opinion.get("projectId") != project_id or int(opinion.get("nodeId") or 0) != node_id:
            continue
        if _r().tenant_id_for_record(opinion) != project_tenant:
            continue
        human_decisions.append(
            {
                "opinionId": opinion.get("id"),
                "decision": str(opinion.get("result") or "")[:60],
                "comment": str(opinion.get("opinion") or "")[:300],
                "decidedAt": str(opinion.get("createdAt") or opinion.get("updatedAt") or ""),
                "authority": "human_review_opinion",
            }
        )
    human_decisions.sort(key=lambda item: str(item.get("decidedAt") or ""), reverse=True)
    prior_conclusions.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return {
        "humanDecisions": human_decisions[:_r().REVIEW_EPISODIC_MEMORY_LIMIT],
        "priorAiConclusions": prior_conclusions[:_r().REVIEW_EPISODIC_MEMORY_LIMIT],
    }


# ---- 心跳、跨进程取消与模型错误分类 ----


def _review_lesson_transition(
    request: Request,
    lesson_id: str,
    idempotency_key: str | None,
    *,
    from_status: str,
    to_status: str,
    action: str,
):
    def produce():
        guard = _r().review_lesson_role_error(request)
        if guard:
            return guard
        _r().ensure_review_session_state()
        lesson = repo.find_one("review_lessons", lesson_id)
        if not lesson or _r().tenant_id_for_record(lesson) != _r().request_tenant_id(request):
            return fail(errors.NOT_FOUND, request)
        if str(lesson.get("status") or "") != from_status:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message=f"仅 {from_status} 状态可{action}，当前为 {lesson.get('status')}。",
            )
        lesson["status"] = to_status
        if to_status == "published":
            lesson["approvedBy"] = _r().request_user_id(request) or "USER-UNKNOWN"
            lesson["approvedAt"] = _r().server_time()
        lesson["updatedAt"] = _r().server_time()
        _r().persist_review_session_records(review_lessons=[lesson])
        return ok({"lesson": repo.clone(lesson)}, request)

    return _r().idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"action": f"review-lesson-{action}", "lessonId": lesson_id},
    )

