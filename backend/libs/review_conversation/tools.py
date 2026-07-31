"""对话 Agent 工具层：工具 schema 注册表、斜线命令映射、工具执行分发、正式判定原子链、工具结果摘要。

从 apps/api/routes.py 纯搬移抽离（B1 重构）；对 routes 命名空间的引用
统一经 _r() 晚绑定，保持 monkeypatch 与运行语义不变。
"""

from __future__ import annotations

import json
from typing import Any

from libs.db.repository import repo
from libs.review_orchestrator.llm_tool_schemas import (
    CONVERSATION_AGENT_RUNTIME_TOOL_NAMES,
    EXTERNAL_REGISTRY_LLM_TOOLS,
    build_review_conversation_agent_tools,
    is_external_registry_tool,
)
from libs.review_orchestrator.r13_facts import build_r13_business_facts
from libs.review_orchestrator.r14_facts import build_r14_business_facts
from libs.review_orchestrator.r15_facts import build_r15_business_facts
from libs.review_orchestrator.r16_facts import build_r16_business_facts
from libs.review_orchestrator.r17_facts import build_r17_business_facts
from libs.review_orchestrator.r18_facts import build_r18_business_facts
from libs.review_orchestrator.r20_r23_facts import (
    build_r20_business_facts,
    build_r21_business_facts,
    build_r22_business_facts,
    build_r23_business_facts,
)
from libs.review_orchestrator.r24_r34_facts import BUILDERS as R24_R34_FACT_BUILDERS
from libs.review_orchestrator.readiness import valid_bbox


def _r():
    """晚绑定访问 apps.api.routes 命名空间。

    抽离前这些引用都是 routes 模块全局名（晚绑定）；统一经 _r() 访问保持
    完全相同的语义 —— 测试对 routes 属性的 monkeypatch（如 qwen_runtime_client、
    review_conversation_agent_tool_output）依然对本模块内部调用生效。
    """
    from apps.api import routes

    return routes


REVIEW_CONVERSATION_CONTEXT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_review_context",
            "description": "读取当前监检节点、固定规则、资料就绪度和 ReviewRun 状态。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_node_evidence",
            "description": "在当前项目节点授权范围内检索全部证据候选（不限会话已选），不会自动确认或采信证据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "文件名或证据原文中的检索词。"},
                    "manualStatus": {
                        "type": "string",
                        "description": "可选的人工状态筛选，例如 confirmed、pending。",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fixed_basis",
            "description": "读取当前节点已经固化的标准条款，模型不能临时改选条款。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "条款号、标准名称或条款摘要关键词。"}
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assemble_node_judgment_facts",
            "description": (
                "一次性聚合当前节点判定所需事实：项目参建单位名称、各证据文档的结构化字段、"
                "印章名称与表格概览。适合用户只核查单个事项时，配合 check_* 工具使用；"
                "整体核查请优先使用 run_node_formal_judgment。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "documentVersionIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。仅聚合指定文档版本；缺省时聚合节点全部证据文档。",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_node_formal_judgment",
            "description": (
                "按当前节点固化规则执行正式判定链：复用正式 ReviewRun 的事实装配与原子项工具计划，"
                "一次调用返回全部原子核查项的确定性判定结果（passed/failed/evidence_insufficient）。"
                "用户要求对当前节点做整体核查或正式判定时应首选本工具，无需先聚合事实或逐个调用判定工具。"
                "结果为辅助判定，未经过完整 ReviewRun 的质量门禁与人工确认环节。"
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

REVIEW_CONVERSATION_AGENT_TOOLS = build_review_conversation_agent_tools(
    context_tools=REVIEW_CONVERSATION_CONTEXT_TOOLS,
)

# ---- Conversation Agent 会话级执行注册表（进程内） ----
# 同一 ReviewSession 同一时刻只允许一个 Agent 执行；cancel_execution 动作通过
# cancelEvent 协同取消，Agent Loop 在每轮模型调用前与每个工具调用前检查该信号。


REVIEW_CONVERSATION_SLASH_COMMANDS: dict[str, str] = {
    "/检索证据": "search_evidence",
    "/补充证据": "search_evidence",
    "/标准条款": "explain_basis",
    "/解释依据": "explain_basis",
    "/解释规则": "explain_basis",
    "/查看条款": "explain_basis",
    "/草拟意见": "draft_opinion",
    "/意见草稿": "draft_opinion",
}


def review_conversation_slash_command(user_text: str) -> str | None:
    stripped = user_text.strip()
    if not stripped.startswith("/"):
        return None
    head = stripped.split(maxsplit=1)[0]
    return _r().REVIEW_CONVERSATION_SLASH_COMMANDS.get(head)


# ---- 持久化 Agent 执行记录（agent_executions） ----


DOCUMENT_SCOPED_CONVERSATION_TOOLS = {
    "get_document_ocr_result",
    "locate_evidence_fragment",
    "extract_document_fields",
    "extract_table_records",
    "recognize_document_seals",
    "recognize_signatures_and_seals",
    "extract_structured_fields",
    "extract_welder_certificate",
    "verify_license_or_certificate",
    "verify_welder_certificate_authenticity",
}


def review_conversation_tool_message_content(output: Any, *, max_total: int = 6000) -> str:
    text = json.dumps(_r().compact_llm_payload(output), ensure_ascii=False, default=str)
    return text if len(text) <= max_total else text[:max_total] + "…(截断)"


def review_conversation_tool_result_summary(tool_name: str, output: dict[str, Any]) -> str:
    status = str(output.get("status") or "completed")
    if status in {"rejected", "failed"}:
        return str(output.get("message") or output.get("errorCode") or status)[:200]
    if tool_name == "get_review_context":
        readiness = output.get("evidenceReadiness") if isinstance(output.get("evidenceReadiness"), dict) else {}
        return (
            f"资料就绪 {readiness.get('satisfiedCount', 0)}/{readiness.get('requiredCount', 0)}，"
            f"待确认 {readiness.get('pendingCount', 0)}"
        )
    if tool_name == "search_node_evidence":
        return f"命中 {output.get('candidateCount', 0)} 条证据候选"
    if tool_name == "get_fixed_basis":
        return f"命中 {output.get('basisCount', 0)} 条固化条款"
    if tool_name in {"check_all_equal", "check_date_covers", "check_design_license_scope", "check_installation_license_scope"}:
        result = output.get("result") or output.get("decision") or output.get("status")
        return f"判定结果：{result}"[:200]
    if tool_name == "validate_evidence_grounding":
        return f"接地校验：{output.get('status') or output.get('result') or 'completed'}"[:200]
    if tool_name == "assemble_node_judgment_facts":
        return (
            f"已聚合 {output.get('documentCount', 0)} 份证据文档的判定事实，"
            f"字段 {output.get('fieldCount', 0)} 项"
        )
    if tool_name == "run_node_formal_judgment":
        summary = output.get("summary") if isinstance(output.get("summary"), dict) else {}
        return (
            f"正式判定链（{output.get('sourceRuleId') or '-'}）：{output.get('result') or '-'}，"
            f"原子项 {summary.get('atomicCheckCount', 0)}："
            f"通过 {summary.get('passedCount', 0)} / 不符合 {summary.get('failedCount', 0)} / "
            f"证据不足 {summary.get('evidenceInsufficientCount', 0)}"
        )[:200]
    return status


# R12/R19 属于依赖人工输入任务的 agent 型节点，正式判定链无法在对话内同步完成。
CONVERSATION_FORMAL_JUDGMENT_EXCLUDED_NODES = {12, 19}

# 与 execution.py load_context 步骤保持一致的 fact builder 分发表（不含 R12/R19）。
CONVERSATION_FORMAL_FACT_BUILDERS: dict[int, Any] = {
    13: build_r13_business_facts,
    14: build_r14_business_facts,
    15: build_r15_business_facts,
    16: build_r16_business_facts,
    17: build_r17_business_facts,
    18: build_r18_business_facts,
    20: build_r20_business_facts,
    21: build_r21_business_facts,
    22: build_r22_business_facts,
    23: build_r23_business_facts,
    **{int(key.removeprefix("r")): builder for key, builder in R24_R34_FACT_BUILDERS.items()},
}


def review_conversation_formal_judgment(
    *,
    project: dict[str, Any],
    node: dict[str, Any],
    evidence_links: list[dict[str, Any]],
) -> dict[str, Any]:
    """对话 Agent 的高层判定工具：只读复用正式判定链（fact builder + tool plan + assembler）。

    不创建 ReviewRun、不写 findingDrafts、不触发人工任务；结果仅作对话辅助判定。
    """
    node_id = int(node.get("nodeId") or 0)
    if node_id in _r().CONVERSATION_FORMAL_JUDGMENT_EXCLUDED_NODES:
        return {
            "status": "rejected",
            "errorCode": "REVIEW_AGENT_NODE_REQUIRES_HUMAN_TASK",
            "message": (
                f"节点 R{node_id:02d} 的正式判定依赖人工输入任务环节，无法在对话内同步执行，"
                "请通过正式 AI 复核（ReviewRun）流程发起。"
            ),
        }
    allowed_document_ids = sorted(
        {
            str(item.get("documentVersionId"))
            for item in evidence_links
            if item.get("documentVersionId")
        }
    )
    business_pack_id = str(project.get("businessPackId") or _r().DEFAULT_BUSINESS_PACK_ID)
    pack = repo.clone(project.get("businessPackSnapshot") or _r().load_business_pack(business_pack_id))
    rule = (
        _r().current_published_rule_for_node(node_id, business_pack_id=business_pack_id)
        or _r().matching_rule_for_node(pack, node_id)
        or {}
    )
    source_rule_id = str(rule.get("sourceRuleId") or rule.get("id") or rule.get("ruleKey") or "")
    if not source_rule_id:
        return {
            "status": "rejected",
            "errorCode": "REVIEW_AGENT_RULE_NOT_FOUND",
            "message": "当前节点未找到已固化的审查规则，无法执行正式判定链。",
        }
    # 合成只读 run：fact builder 只依赖 projectId/nodeId/inputDocumentVersionIds/reviewDate 等字段。
    synthetic_run = {
        "projectId": project.get("id"),
        "nodeId": node_id,
        "reviewMode": "advisory",
        "advisoryOnly": True,
        "inputDocumentVersionIds": allowed_document_ids,
        "reviewDate": _r().server_time()[:10],
    }
    builder = _r().CONVERSATION_FORMAL_FACT_BUILDERS.get(node_id)
    facts = builder(repo.state, synthetic_run) if builder else {}
    plan = _r().compile_node_tool_plan(
        pack,
        source_rule_id,
        available_tools={item["name"] for item in _r().runtime_tool_catalog()},
        # 对话辅助判定放宽 published 门槛，但必须在结果中标注 lifecycleStatus。
        require_published=False,
    )
    binding_set = pack.get("atomicCheckToolBindingSet") or {}
    lifecycle_status = str(binding_set.get("lifecycleStatus") or "draft")
    base = {
        "status": "succeeded",
        "sourceRuleId": source_rule_id,
        "ruleName": rule.get("name"),
        "nodeId": node_id,
        "advisory": True,
        "bindingSetLifecycleStatus": lifecycle_status,
        "factsAvailable": bool(facts),
        "documentVersionIds": allowed_document_ids,
    }
    if not plan:
        return {
            **base,
            "result": "not_configured",
            "atomicResults": [],
            "summary": {"atomicCheckCount": 0},
            "notice": "当前规则尚未配置原子核查项工具绑定，无法执行确定性判定。",
        }
    execution = _r().execute_node_tool_plan(
        plan,
        tool_runner=lambda name, arguments: _r().dispatch_runtime_tool(
            repo.state,
            name,
            arguments,
            context={"documentVersionIds": allowed_document_ids},
        ),
        facts=facts,
        document_version_ids=allowed_document_ids,
    )
    compact_atomic: list[dict[str, Any]] = []
    for item in execution.get("atomicResults") or []:
        tools_compact = []
        for tool_result in item.get("toolResults") or []:
            if not isinstance(tool_result, dict):
                continue
            checks = [
                {"check": check.get("check") or check.get("name"), "result": check.get("result")}
                for check in (tool_result.get("checks") or [])[:12]
                if isinstance(check, dict)
            ]
            tools_compact.append(
                {
                    "toolName": tool_result.get("toolName"),
                    "result": tool_result.get("result") or tool_result.get("status"),
                    "checks": checks,
                    "message": str(tool_result.get("message") or "")[:200] or None,
                }
            )
        compact_atomic.append(
            {
                "atomicCheckId": item.get("atomicCheckId"),
                "result": item.get("result"),
                "warnings": item.get("warnings") or [],
                "tools": tools_compact,
            }
        )
    notices = [
        "本结果复用正式原子项工具链，但未经过完整 ReviewRun 的质量门禁与人工确认，仅作辅助判定。",
    ]
    if lifecycle_status != "published":
        notices.append(f"原子项工具绑定当前为 {lifecycle_status} 状态（未发布），结果仅供参考。")
    if not facts and builder is None:
        notices.append("该节点暂无事实装配器，判定主要依赖绑定参数与证据文档，缺失事实按证据不足处理。")
    return {
        **base,
        "result": execution.get("result"),
        "summary": execution.get("summary") or {},
        "atomicResults": compact_atomic,
        "notice": " ".join(notices),
    }


def review_conversation_agent_tool_output(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    session: dict[str, Any],
    project: dict[str, Any],
    node: dict[str, Any],
    basis: dict[str, Any],
    basis_items: list[dict[str, Any]],
    readiness: dict[str, Any],
    evidence_links: list[dict[str, Any]],
    review_run: dict[str, Any] | None,
    advisory_evidence_links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if tool_name == "get_review_context":
        return {
            "status": "succeeded",
            "project": {"projectId": project.get("id"), "name": project.get("name")},
            "node": {"nodeId": node.get("nodeId"), "name": node.get("name"), "code": node.get("code")},
            "currentTask": session.get("currentTask"),
            "ruleId": basis.get("ruleId"),
            "ruleVersion": basis.get("ruleVersion"),
            "evidenceReadiness": {
                "requiredCount": readiness.get("requiredCount", 0),
                "satisfiedCount": readiness.get("satisfiedCount", 0),
                "missingCount": readiness.get("missingCount", 0),
                "pendingCount": readiness.get("pendingCount", 0),
            },
            "reviewRun": {
                "reviewRunId": (review_run or {}).get("reviewRunId") or (review_run or {}).get("id"),
                "status": (review_run or {}).get("status") or "未发起",
                "currentStep": (review_run or {}).get("currentStep"),
                "findingCount": len((review_run or {}).get("findingDrafts") or []),
            },
        }
    if tool_name == "search_node_evidence":
        query = str(arguments.get("query") or "").strip()
        manual_status = str(arguments.get("manualStatus") or "").strip().lower()
        visible_evidence_by_version: dict[str, list[dict[str, Any]]] = {}
        for item in evidence_links:
            version_id = str(item.get("documentVersionId") or "").strip()
            if not version_id:
                continue
            visible_evidence_by_version.setdefault(version_id, []).append(item)
        allowed_version_ids = sorted(
            {
                str(item.get("documentVersionId") or "").strip()
                for item in [*evidence_links, *(advisory_evidence_links or [])]
                if str(item.get("documentVersionId") or "").strip()
            }
        )

        identity_fields = (
            "evidenceLinkId",
            "evidenceRefId",
            "evidenceId",
            "id",
            "candidateId",
        )

        def evidence_identity_values(item: dict[str, Any]) -> set[str]:
            return {
                str(item.get(field) or "").strip()
                for field in identity_fields
                if str(item.get(field) or "").strip()
            }

        def evidence_locator(
            item: dict[str, Any],
        ) -> tuple[str, str, tuple[Any, ...], str] | None:
            version_id = str(item.get("documentVersionId") or "").strip()
            page_no = item.get("pageNo")
            bbox = item.get("bbox")
            quoted_text = str(item.get("quotedText") or "").strip()
            if (
                not version_id
                or page_no is None
                or not valid_bbox(bbox)
                or not quoted_text
            ):
                return None
            return version_id, str(page_no), tuple(bbox), quoted_text

        def matching_visible_evidence(
            item: dict[str, Any],
        ) -> list[dict[str, Any]]:
            version_id = str(item.get("documentVersionId") or "").strip()
            visible_items = visible_evidence_by_version.get(version_id) or []
            identity_values = evidence_identity_values(item)
            if identity_values:
                identity_matches = [
                    visible_item
                    for visible_item in visible_items
                    if identity_values & evidence_identity_values(visible_item)
                ]
                if identity_matches:
                    return identity_matches
            locator = evidence_locator(item)
            if locator is None:
                return []
            return [
                visible_item
                for visible_item in visible_items
                if evidence_locator(visible_item) == locator
            ]

        project_id = str(project.get("id") or session.get("projectId") or "")
        node_id = int(node.get("nodeId") or session.get("nodeId") or 0)
        if not allowed_version_ids:
            return {
                "status": "succeeded",
                "projectId": project_id,
                "nodeId": node_id,
                "retrievalTraceId": None,
                "candidateCount": 0,
                "formalCandidateCount": 0,
                "advisoryCandidateCount": 0,
                "candidates": [],
                "queryMissed": bool(query),
                "requiresHumanConfirmation": True,
                "fallbackUsed": False,
                "fallbackReason": "empty_visible_evidence_scope",
                "degraded": True,
            }

        fallback_used = False
        fallback_reason = None
        try:
            live_result = _r().search_project_evidence(
                repo,
                project_id=project_id,
                node_id=node_id,
                document_version_ids=allowed_version_ids,
                query=query,
                review_run_id=str(
                    (review_run or {}).get("reviewRunId")
                    or (review_run or {}).get("id")
                    or ""
                )
                or None,
            )
            raw_candidates = list(live_result.get("allCandidates") or [])
            if not raw_candidates:
                raw_candidates = [
                    *(live_result.get("formalCandidates") or []),
                    *(live_result.get("advisoryCandidates") or []),
                ]
        except Exception:  # noqa: BLE001 - retain request-scoped precomputed evidence.
            live_result = {}
            raw_candidates = evidence_links
            fallback_used = True
            fallback_reason = "live_retrieval_exception"
        allowed_versions = set(allowed_version_ids)
        candidates = []
        for item in raw_candidates:
            version_id = str(item.get("documentVersionId") or "").strip()
            if version_id not in allowed_versions:
                continue
            visible_matches = matching_visible_evidence(item)
            if manual_status:
                visible_matches = [
                    visible_item
                    for visible_item in visible_matches
                    if str(visible_item.get("manualStatus") or "").strip().lower()
                    == manual_status
                ]
                if not visible_matches:
                    continue
            matched_visible = visible_matches[0] if visible_matches else None
            candidate = repo.clone(item)
            candidate["candidateId"] = (
                candidate.get("candidateId")
                or candidate.get("evidenceId")
                or candidate.get("id")
            )
            if matched_visible is not None:
                candidate["manualStatus"] = (
                    str(matched_visible.get("manualStatus") or "").strip().lower()
                    or None
                )
                candidate["manualStatusLabel"] = (
                    str(matched_visible.get("manualStatusLabel") or "").strip()
                    or None
                )
            if fallback_used:
                candidate["evidenceLinkId"] = (
                    candidate.get("evidenceLinkId") or candidate.get("id")
                )
                evidence_tier = str(candidate.get("evidenceTier") or "").lower()
                explicitly_advisory = (
                    candidate.get("formalEvidenceEligible") is False
                    or evidence_tier == "advisory"
                )
                formal_eligible = not explicitly_advisory and (
                    candidate.get("formalEvidenceEligible") is True
                    or evidence_tier == "formal"
                    or _r().evidence_link_is_locatable(candidate)
                )
                candidate["formalEvidenceEligible"] = formal_eligible
                candidate["evidenceTier"] = (
                    "formal" if formal_eligible else "advisory"
                )
            candidate["quotedText"] = str(candidate.get("quotedText") or "")[:800]
            candidate["requiresHumanConfirmation"] = True
            candidates.append(candidate)
        candidates = candidates[:12]
        formal_count = sum(
            1 for item in candidates if item.get("formalEvidenceEligible") is True
        )
        advisory_count = len(candidates) - formal_count
        trace = live_result.get("trace") or {}
        return {
            "status": "succeeded",
            "projectId": project_id,
            "nodeId": node_id,
            "retrievalTraceId": str(
                trace.get("retrievalTraceId") or trace.get("id") or ""
            )
            or None,
            "candidateCount": len(candidates),
            "formalCandidateCount": formal_count,
            "advisoryCandidateCount": advisory_count,
            "candidates": candidates,
            "queryMissed": bool(query) and not candidates,
            "requiresHumanConfirmation": True,
            "fallbackUsed": fallback_used,
            "fallbackReason": fallback_reason
            or live_result.get("fallbackReason")
            or trace.get("fallbackReason"),
            "degraded": fallback_used
            or bool(live_result.get("degraded") or trace.get("degraded")),
        }
    if tool_name == "assemble_node_judgment_facts":
        allowed_document_ids = {
            str(item.get("documentVersionId"))
            for item in evidence_links
            if item.get("documentVersionId")
        }
        requested_ids = {str(item) for item in arguments.get("documentVersionIds") or [] if item}
        if requested_ids - allowed_document_ids:
            return {
                "status": "rejected",
                "errorCode": "REVIEW_AGENT_DOCUMENT_SCOPE_VIOLATION",
                "message": "聚合请求包含当前监检节点授权范围外的文档版本。",
            }
        target_ids = requested_ids or allowed_document_ids
        file_names = {
            str(item.get("documentVersionId") or ""): item.get("fileName") or item.get("documentName")
            for item in evidence_links
        }
        documents = []
        field_count = 0
        for parse_result in repo.state.get("ocr_parse_results", []):
            if not isinstance(parse_result, dict):
                continue
            version_id = str(parse_result.get("documentVersionId") or "")
            if version_id not in target_ids:
                continue
            raw_fields = parse_result.get("fields")
            fields_iter = (
                list(raw_fields.values()) if isinstance(raw_fields, dict) else list(raw_fields or [])
            )
            fields = []
            for field in fields_iter[:30]:
                if not isinstance(field, dict):
                    continue
                fields.append(
                    {
                        "code": field.get("fieldCode") or field.get("code") or field.get("name"),
                        "value": str(
                            field.get("fieldValue") or field.get("value") or field.get("text") or ""
                        )[:300],
                        "pageNo": field.get("pageNo"),
                    }
                )
            raw_seals = parse_result.get("seals")
            seals_iter = (
                list(raw_seals.values()) if isinstance(raw_seals, dict) else list(raw_seals or [])
            )
            seal_names = [
                str(seal.get("sealName") or seal.get("name") or seal.get("text") or "")[:120]
                for seal in seals_iter[:10]
                if isinstance(seal, dict)
            ]
            raw_tables = parse_result.get("tables")
            table_count = len(raw_tables) if isinstance(raw_tables, (list, dict)) else 0
            field_count += len(fields)
            documents.append(
                {
                    "documentVersionId": version_id,
                    "fileName": file_names.get(version_id),
                    "documentType": parse_result.get("documentType"),
                    "fields": fields,
                    "sealNames": [name for name in seal_names if name],
                    "tableCount": table_count,
                }
            )
        return {
            "status": "succeeded",
            "project": {
                "name": project.get("name"),
                "ownerOrgName": project.get("ownerOrgName"),
                "contractorOrgName": project.get("contractorOrgName"),
                "ndtOrgName": project.get("ndtOrgName"),
                "inspectionOrgName": project.get("inspectionOrgName"),
            },
            "node": {"nodeId": node.get("nodeId"), "name": node.get("name"), "code": node.get("code")},
            "documentCount": len(documents),
            "fieldCount": field_count,
            "documents": documents,
            "fixedBasisCount": len(basis_items),
        }
    if tool_name == "get_fixed_basis":
        query = str(arguments.get("query") or "").strip().lower()
        matches = []
        for item in basis_items:
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ("standardRef", "standardName", "clauseNo", "title", "summary")
            ).lower()
            if query and query not in haystack:
                continue
            matches.append(
                {
                    "basisRefId": item.get("sourceLocatorId") or item.get("clauseId"),
                    "standardCode": item.get("standardCode"),
                    "standardName": item.get("standardName"),
                    "standardRef": item.get("standardRef"),
                    "clauseNo": item.get("clauseNo"),
                    "title": item.get("title"),
                    "summary": str(item.get("summary") or "")[:1000],
                }
            )
        return {"status": "succeeded", "basisCount": len(matches), "items": matches[:12], "fixedBinding": True}
    if tool_name == "run_node_formal_judgment":
        return _r().review_conversation_formal_judgment(
            project=project,
            node=node,
            evidence_links=evidence_links,
        )
    runtime_tool_names = set(CONVERSATION_AGENT_RUNTIME_TOOL_NAMES) | {
        str(item["function"]["name"])
        for item in EXTERNAL_REGISTRY_LLM_TOOLS
        if isinstance(item, dict) and isinstance(item.get("function"), dict) and item["function"].get("name")
    }
    if tool_name in runtime_tool_names:
        if is_external_registry_tool(tool_name):
            return _r().dispatch_runtime_tool(repo.state, tool_name, arguments or {})
        if tool_name in _r().DOCUMENT_SCOPED_CONVERSATION_TOOLS:
            allowed_document_ids = {
                str(item.get("documentVersionId"))
                for item in evidence_links
                if item.get("documentVersionId")
            }
            requested_document_ids = {
                str(item) for item in arguments.get("documentVersionIds") or [] if item
            }
            if not allowed_document_ids:
                return {
                    "status": "rejected",
                    "errorCode": "REVIEW_AGENT_NODE_EVIDENCE_EMPTY",
                    "message": "当前节点尚无可供工具读取的证据文档版本。",
                }
            if requested_document_ids - allowed_document_ids:
                return {
                    "status": "rejected",
                    "errorCode": "REVIEW_AGENT_DOCUMENT_SCOPE_VIOLATION",
                    "message": "工具请求包含当前监检节点授权范围外的文档版本。",
                }
            scoped_arguments = {
                **arguments,
                "documentVersionIds": sorted(requested_document_ids or allowed_document_ids),
            }
            return _r().dispatch_runtime_tool(
                repo.state,
                tool_name,
                scoped_arguments,
                context={"documentVersionIds": sorted(allowed_document_ids)},
            )
        return _r().dispatch_runtime_tool(repo.state, tool_name, arguments or {})
    return {
        "status": "rejected",
        "errorCode": "REVIEW_AGENT_TOOL_NOT_ALLOWED",
        "message": f"Tool {tool_name} is not available in the B-version review conversation.",
    }
