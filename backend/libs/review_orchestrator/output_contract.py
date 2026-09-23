"""P9 R3 输出契约：标题 ≤30 字只说差距、正文 ≤150 字、每节点 ≤8 条（多出归并）。

审计（2026-09-06）：正文最长 884 字且含 JSON，节点 2 一次 13 条并排。长度在校验层只记
TEXT_TOO_LONG 警告（不判失败——截断会把"差在哪"截掉，比长更糟）；条数在生成后按优先级
截到 8 条，多出的通过守卫的发现归并成一条"其余 N 条已归并"（标题由代码生成，不进守卫），
多出的降级条目只把待核对断言并进最后一条降级项。提示词同时写明这三条格式约束。
"""

from __future__ import annotations

import logging
import os
from copy import deepcopy
from typing import Any

from libs.review_orchestrator.approval_view import recorded_approval_checks

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 30
DESCRIPTION_MAX_CHARS = 150
MAX_FINDINGS_PER_NODE = 8
DOWNGRADED_TITLE = "证据不足，需人工确认"
MERGED_TITLE_PREFIX = "其余"
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

PROMPT_FORMAT_REQUIREMENTS = [
    f"每条 finding 的 title 不超过 {TITLE_MAX_CHARS} 字、只说差距（查到什么不一致），不写结论套话。",
    f"description 不超过 {DESCRIPTION_MAX_CHARS} 字，固定写法：查到什么 → 差在哪 → 怎么做；不要输出 JSON 或表格原文。",
    f"每个节点最多 {MAX_FINDINGS_PER_NODE} 条 finding，同一问题不要拆成多条；超出的合并写。",
]


def prompt_format_requirements(*, complete: bool = False) -> list[str]:
    if not complete:
        return list(PROMPT_FORMAT_REQUIREMENTS)
    return [
        *PROMPT_FORMAT_REQUIREMENTS[:2],
        "保留每个独立问题及其原子审查项和完整证据引用，不得为了条数限制合并或省略不同问题；同一问题不要重复输出。",
    ]


def text_length_warnings_for(draft: dict[str, Any], index: int) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for field, limit in (("title", TITLE_MAX_CHARS), ("description", DESCRIPTION_MAX_CHARS)):
        length = len(" ".join(str(draft.get(field) or "").split()))
        if length > limit:
            warnings.append({"code": "TEXT_TOO_LONG", "index": index, "field": field, "length": length, "limit": limit})
    return warnings


def _is_downgraded(draft: dict[str, Any]) -> bool:
    return str(draft.get("title") or "").startswith(DOWNGRADED_TITLE) or str(draft.get("groundingStatus") or "") == "insufficient_evidence"


def _priority(draft: dict[str, Any]) -> tuple[int, int]:
    return (0 if not _is_downgraded(draft) else 1, -_SEVERITY_RANK.get(str(draft.get("severity") or "").lower(), 0))


def _merge_grounded(extras: list[dict[str, Any]], template: dict[str, Any]) -> dict[str, Any]:
    titles = [" ".join(str(item.get("title") or "").split()) for item in extras]
    body = "；".join(titles)
    description = f"另有 {len(extras)} 条通过证据核对的发现已归并：{body}"
    if len(description) > DESCRIPTION_MAX_CHARS:
        description = description[: DESCRIPTION_MAX_CHARS - 1] + "…"
    severity = max(extras, key=lambda item: _SEVERITY_RANK.get(str(item.get("severity") or "").lower(), 0)).get("severity")
    evidence_refs: list[Any] = []
    for item in extras:
        for ref in item.get("evidenceRefs") or []:
            if ref not in evidence_refs:
                evidence_refs.append(ref)
    merged = {
        **{key: template.get(key) for key in ("reviewRunId", "projectId", "nodeId", "businessPackId", "agentId", "agentVersion")},
        "id": f"{template.get('id') or 'FND-DRAFT'}-MERGED",
        "findingType": "merged_findings",
        "severity": severity,
        "title": f"{MERGED_TITLE_PREFIX} {len(extras)} 条发现已归并",
        "description": description,
        "evidenceRefs": evidence_refs[:6],
        "ruleRefs": [ref for item in extras for ref in item.get("ruleRefs") or []][:6],
        "kbRefs": [],
        "confidence": min(float(item.get("confidence") or 0.5) for item in extras),
        "suggestedAction": "human_confirm",
        "groundingStatus": "grounded",
        "unsupportedClaims": [],
        "requiresHumanConfirmation": True,
        "mergedFindingIds": [str(item.get("id") or "") for item in extras],
        "mergedTitles": titles,
        "llmGenerated": False,
    }
    return merged


def cap_findings(drafts: list[dict[str, Any]], *, limit: int = MAX_FINDINGS_PER_NODE) -> list[dict[str, Any]]:
    """按优先级保留 limit 条；多出的通过守卫项归并成一条，多出的降级项把断言并进保留的降级项。总数永不超过 limit。"""
    items = deepcopy([item for item in drafts if isinstance(item, dict)])
    if len(items) <= limit:
        return items
    ordered = sorted(items, key=_priority)
    kept = ordered[:limit]
    extra_grounded = [item for item in ordered[limit:] if not _is_downgraded(item)]
    extra_downgraded = [item for item in ordered[limit:] if _is_downgraded(item)]
    # 归并条 / 降级汇总条要占名额：从保留区尾部让位，让出的条目本身也进入待归并，直到放得下为止
    def needed_slots() -> int:
        return int(bool(extra_grounded)) + int(bool(extra_downgraded) and not any(_is_downgraded(item) for item in kept))

    while kept and len(kept) + needed_slots() > limit:
        spill = kept.pop()
        (extra_downgraded if _is_downgraded(spill) else extra_grounded).insert(0, spill)
    if extra_grounded:
        kept.append(_merge_grounded(extra_grounded, template=extra_grounded[0]))
    if extra_downgraded:
        target = next((item for item in reversed(kept) if _is_downgraded(item)), None)
        if target is None:
            target = {**extra_downgraded[0], "mergedFindingIds": []}
            kept.append(target)
            extra_downgraded = extra_downgraded[1:]
        claims = list(target.get("unsupportedClaims") or [])
        for item in extra_downgraded:
            for claim in item.get("unsupportedClaims") or []:
                if claim not in claims:
                    claims.append(claim)
        target["unsupportedClaims"] = claims
        target["mergedFindingIds"] = [*(target.get("mergedFindingIds") or []), *(str(item.get("id") or "") for item in extra_downgraded)]
    return kept[:limit]


def cap_generated_findings(
    generated: tuple[list[dict[str, Any]], dict[str, Any]], *, complete: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    drafts, metadata = generated
    if complete:
        return drafts, {**metadata, "findingRetention": "complete", "findingCount": len(drafts)}
    capped = cap_findings(drafts)
    if len(capped) != len(drafts):
        metadata = {**metadata, "cappedFindings": {"before": len(drafts), "after": len(capped), "limit": MAX_FINDINGS_PER_NODE}}
    return capped, metadata


def _superseded(reference: Any) -> dict[str, Any] | None:
    try:
        from libs.standard_editions import superseded_edition

        return superseded_edition(str(reference or ""))
    except Exception:  # noqa: BLE001 -- 换版提示缺失不影响审查
        return None


#: 检索包里混着工程资料，标题就是原文件名。只按后缀判断，不猜内容。
_DOCUMENT_TITLE_SUFFIXES = (".pdf", ".doc", ".docx", ".md", ".txt", ".xls", ".xlsx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg")


def _clause_source_kind(code: str, standard: str) -> str:
    """这条引用是标准条款、工程资料原文，还是版本没登记的标准。

    `standard_document_versions` 里登记过（因而有标准号）的才敢叫标准条款；
    标题带文件后缀的是本工程上传的资料；剩下的是标准名对得上、但版本没登记——
    照样可以引，只是界面上要说清「版本未登记」，不能让人以为引的是现行版。
    """
    if code:
        return "standard"
    if standard.strip().lower().endswith(_DOCUMENT_TITLE_SUFFIXES):
        return "document"
    return "unregistered_standard"


def attach_clause_details(state: dict[str, Any], drafts: list[dict[str, Any]]) -> None:
    """把 kbRefs 里的 clauseId 解析成条款详情，就地写进 finding 的 `clauseRefs`。

    2026-09-13 用户要求「引用的标准条款要清晰标记出来」。模型早就在引条款了
    （kbRefs.clauseIds，从检索包里选 id，不是自己背原文——这是对的，背原文就是幻觉入口），
    但界面上只有一串 `CHK-KF-KB-DE16B8E7E8-14`，等于没引。这里把标准名、章节、条款号、
    原文、页码补齐，界面直接显示、可点开标准原件。
    """
    clause_ids = {
        str(clause_id)
        for draft in drafts
        if isinstance(draft, dict)
        for ref in draft.get("kbRefs") or []
        if isinstance(ref, dict)
        for clause_id in ref.get("clauseIds") or []
        if clause_id
    }
    if not clause_ids:
        return
    # 条款记录里只有标准中文名，标准号在 standard_document_versions 上（按 knowledgeFileId 对）。
    codes_by_file = {
        str(doc.get("knowledgeFileId") or ""): str(doc.get("code") or "")
        for doc in state.get("standard_document_versions") or []
        if isinstance(doc, dict) and doc.get("knowledgeFileId") and doc.get("code")
    }
    index: dict[str, dict[str, Any]] = {}
    for clause in state.get("knowledge_clauses") or []:
        if not isinstance(clause, dict):
            continue
        key = str(clause.get("clauseId") or clause.get("id") or "")
        if key in clause_ids and key not in index:
            index[key] = clause
    if not index:
        return
    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ref in draft.get("kbRefs") or []:
            for clause_id in (ref or {}).get("clauseIds") or []:
                clause = index.get(str(clause_id))
                if not clause or str(clause_id) in seen:
                    continue
                seen.add(str(clause_id))
                title = str(clause.get("title") or "")
                standard, _, section = title.partition(" / ")
                code = codes_by_file.get(str(clause.get("fileId") or ""), "")
                refs.append(
                    {
                        "clauseId": str(clause_id),
                        "standard": standard.strip(),
                        "standardCode": code,
                        # 界面这一栏原来一律叫「引用的标准条款」，但检索包里既有标准，也有本工程
                        # 上传的施工图、施工方案、业务规则说明（2026-09-13 线上审计：
                        # P-2026-ECD202 的 296 条引用里 127 条没有标准号，最多的一条是
                        # 「地上甲类储罐区2（含泵区）施工图.pdf」引了 40 次）。
                        # 把资料原文当标准条款印出去，监检会以为那是规范要求。
                        "sourceKind": _clause_source_kind(code, standard),
                        "section": section.strip(),
                        # 引的是不是过期版本：条款原文一显示出来，监检就会照着核，
                        # 引旧版比不显示更糟（节点 24/29 引的 TSG Z6002-2010 已被 2026 版取代）。
                        "supersededEdition": _superseded(code),
                        "clauseNo": clause.get("clauseNo"),
                        "text": str(clause.get("text") or "")[:600],
                        "pageNo": clause.get("pageNo"),
                        "documentVersionId": clause.get("documentVersionId"),
                        "fileId": clause.get("fileId"),
                    }
                )
        if refs:
            draft["clauseRefs"] = refs


def store_generated_findings(review_run, drafts, *, complete, hash_payload):
    try:
        from libs.db.repository import repo

        attach_clause_details(repo.state, drafts)
    except Exception:  # 条款补全失败只是界面少一块，不能让审查落库失败
        logger.warning("条款详情补全失败，保留原始发现", exc_info=True)
    review_run["findingDrafts"] = deepcopy(drafts)
    if complete:
        review_run["findingRetention"] = "complete"
        review_run["findingSummaryDrafts"] = cap_findings(review_run["findingDrafts"])
    review_run["outputHash"] = hash_payload(review_run["findingDrafts"])
    return {"findingDrafts": len(review_run["findingDrafts"]), "outputHash": review_run["outputHash"]}


def review_view_with_limitations(run: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Project recorded capability warnings without interpreting them as missing files."""
    view = deepcopy(run)
    run_id = run.get("reviewRunId") or run.get("id")
    limitations = set()
    approval_checks = []
    run_records: list[dict[str, Any]] = []
    for record in state.get("rule_check_results", []):
        if not run_id or record.get("reviewRunId") != run_id:
            continue
        if any(record.get(key) not in (None, run.get(key)) for key in ("tenantId", "projectId", "nodeId")):
            continue
        run_records.append(record)
        for atomic in record.get("atomicCheckResults") or []:
            if not isinstance(atomic, dict):
                continue
            approval_checks.extend(recorded_approval_checks(atomic))
            for warning in atomic.get("warnings") or []:
                if warning == "invalid_pending_capabilities":
                    limitations.add((str(atomic.get("atomicCheckId") or ""), warning))
                elif isinstance(warning, str) and warning.startswith("pending_capability:"):
                    code = warning.removeprefix("pending_capability:")
                    if code:
                        limitations.add((str(atomic.get("atomicCheckId") or ""), code))
    # Derive solely from this run's recorded execution, never the current mutable pack.
    if approval_checks:
        view["approvalChecks"] = approval_checks
    # 逐项核查结果（含通过项）。界面原来只列问题，通过了什么看不见——
    # 监检人员没法判断「没报问题」是查过了还是压根没查。
    # 判定来自本次执行留痕；只有名称从业务包按 id 取，取不到就显示 id。
    # 和 approvalChecks 一样，没有留痕就不写这个字段：没记录不等于记录了空。
    check_outcomes = atomic_check_outcomes(run_records, run)
    if check_outcomes:
        view["atomicCheckOutcomes"] = check_outcomes
    view["automationLimitations"] = [
        {"atomicCheckId": atomic_id, "code": code, "requiresHumanReview": True}
        for atomic_id, code in sorted(limitations)
    ]
    return view


def atomic_check_outcomes(records: list[dict[str, Any]], run: dict[str, Any]) -> list[dict[str, Any]]:
    """本次执行逐项核查的结果，含通过项。

    界面原来只列问题：通过了什么、不适用什么，监检人员看不见，也就分不清
    「没报问题」是查过了还是压根没查。判定全部来自本次执行留痕，
    只有显示名按 id 从业务包取，取不到就用 id。
    """
    names = _atomic_check_names(str(run.get("businessPackId") or ""))
    opinions = _visible_jev_opinions(run)
    decision = run.get("jevDecision") or {}
    jev_choices = {str(row.get("atomicCheckId")): row for row in decision.get("atomic") or []
                   if isinstance(row, dict) and row.get("atomicCheckId")}
    seen: set[str] = set()
    outcomes: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        for atomic in record.get("atomicCheckResults") or []:
            if not isinstance(atomic, dict):
                continue
            check_id = str(atomic.get("atomicCheckId") or "")
            if not check_id or check_id in seen:
                continue
            seen.add(check_id)
            original_result = str(atomic.get("deterministicResult") or atomic.get("result") or "")
            jev_row = jev_choices.get(check_id) if decision.get("status") == "completed" else None
            active_result = str(jev_row.get("choice") or "") if jev_row else str(atomic.get("result") or "")
            if decision and decision.get("status") not in {"completed", "disabled", "nonformal_run",
                                                           "no_semantic_checks"}:
                active_result = ("evidence_insufficient" if decision["status"] in {
                    "no_ocr_text", "ocr_not_ready", "overlong_document", "ambiguous_ocr_attempt"
                } else "human_review_required")
            source = ("jev" if jev_row else "jev_unavailable" if decision and decision.get("status")
                      not in {"completed", "disabled", "nonformal_run", "no_semantic_checks"} else "rule_engine")
            outcomes.append(
                {
                    "atomicCheckId": check_id,
                    "name": names.get(check_id) or check_id,
                    "result": active_result,
                    "decisionSource": source,
                    **({"deterministicResult": original_result, "jevConfidence": jev_row["confidence"],
                        **({"perPerson": jev_row["perPerson"]} if jev_row.get("perPerson") else {})}
                       if jev_row else {"deterministicResult": original_result} if source == "jev_unavailable" else {}),
                    "ruleCode": str(record.get("ruleCode") or ""),
                    # 「需人工判断」的原因常是引擎没给分：把没分的事实列出来，
                    # 界面才有东西让人核，核完落成 fact_corrections 下次就有分。
                    # 只挂在「需人工判断」上：grounding 的结果对同一节点的每个原子项都一样，
                    # 挂满五项就是同两条事实列五遍；而人工确认只在这一种结论上能改判。
                    "unscoredFacts": _unscored_facts(atomic) if str(atomic.get("result") or "") == "human_review_required" else [],
                    # 通过/不通过/需人工都要看得见依据：业务工具的逐条检查、不足原因、
                    # 以及事实引用的证据原文（文件·页·引文·来源）。
                    "checks": _business_checks(atomic),
                    "reason": ("Jev 与规则结果不同，请核对原文后确认。" if jev_row and active_result != original_result
                               else "出题或答题本次未完成，需人工核查或重试。" if source == "jev_unavailable"
                               else _outcome_reason(atomic)),
                    "facts": _grounded_facts(atomic),
                    **({"secondOpinion": opinions[check_id]} if check_id in opinions else {}),
                }
            )
    return outcomes


def _visible_jev_opinions(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Release calibrated advice only; raw shadow opinions stay on ReviewRun."""
    truthy = {"1", "true", "yes"}
    if os.getenv("AICHECK_JEV_CALIBRATION_APPROVED", "").lower() not in truthy:
        return {}
    if os.getenv("AICHECK_JEV_SECOND_OPINION_UI_ENABLED", "").lower() not in truthy:
        return {}
    try:
        enter = float(os.environ["AICHECK_JEV_QUEUE_ENTER_CONFIDENCE"])
        exit_at = float(os.environ["AICHECK_JEV_QUEUE_EXIT_CONFIDENCE"])
    except (KeyError, ValueError):
        return {}
    if not 0 < enter < exit_at <= 1:
        return {}
    snapshot = run.get("jevSecondOpinions") or {}
    # R19 compares with Qwen's semantic judgment, not the deterministic rule engine.
    # Keep it shadow-only until that comparison has its own calibrated UI contract.
    if snapshot.get("comparisonSource") == "r19_semantic_review":
        return {}
    if snapshot.get("status") != "completed" or snapshot.get("model") != "jev-1.13.0":
        return {}
    previous = run.get("jevQueuePrevious") or {}
    visible: dict[str, dict[str, Any]] = {}
    for item in snapshot.get("atomic") or []:
        if not isinstance(item, dict) or item.get("model") != "jev-1.13.0":
            continue
        check_id = str(item.get("atomicCheckId") or "")
        confidence = item.get("confidence")
        if not check_id or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            continue
        agrees = item.get("agreesWithRuleEngine") is True
        queued = (True if not agrees else True if confidence < enter else False if confidence >= exit_at
                  else bool(previous.get(check_id, True)))
        visible[check_id] = {"choice": item.get("choice"), "confidence": confidence,
                             "model": "jev-1.13.0", "agreesWithRuleEngine": agrees,
                             "needsHumanReview": queued,
                             "priority": "disagreement" if not agrees else "low_confidence" if queued else "normal"}
    return visible


_EVIDENCE_TOOLS = frozenset({"validate_evidence_grounding", "extract_document_fields", "extract_table_records", "locate_evidence_fragment"})


def _business_checks(atomic: dict[str, Any]) -> list[dict[str, Any]]:
    """业务工具（不含取证/锚定工具）留下的逐条检查：code / 通过否 / 期望 / 实际。"""
    output: list[dict[str, Any]] = []
    for tool in atomic.get("toolResults") or []:
        if not isinstance(tool, dict) or tool.get("toolName") in _EVIDENCE_TOOLS:
            continue
        for item in tool.get("checks") or []:
            if not isinstance(item, dict) or not item.get("code"):
                continue
            output.append(
                {
                    "tool": str(tool.get("toolName") or ""),
                    "code": str(item.get("code")),
                    "passed": item.get("passed") is True,
                    "expected": item.get("expected"),
                    "actual": item.get("actual"),
                    "missing": item.get("missing") is True,
                }
            )
    return output


def _outcome_reason(atomic: dict[str, Any]) -> str:
    """这一项为什么不是通过。

    优先级：判定不合格（failed）> 证据不够（evidence_insufficient / 需人工）> 锚定门。
    2026-09-13 线上审计：节点 1 的设计单位许可证列 GB1/GB2/GC1、工程要 GC2，
    当时证照工具误判 failed，界面又写了「缺少施工起止日期」——那只是同一项里另一个
    工具报的数据缺口，按工具顺序抢先了。资质不覆盖是实质不合格，缺日期是资料没填齐，
    两者混在一起，监检第一眼读到的就是错的那句。
    """
    grounding_reason = ""
    insufficient_reason = ""
    for tool in atomic.get("toolResults") or []:
        if not isinstance(tool, dict):
            continue
        facts = tool.get("facts") if isinstance(tool.get("facts"), dict) else {}
        reason = str(facts.get("reason") or "")
        if not reason:
            continue
        if tool.get("toolName") == "validate_evidence_grounding":
            grounding_reason = reason
        elif tool.get("result") == "failed":
            return reason
        elif tool.get("result") in {"evidence_insufficient", "human_review_required"}:
            insufficient_reason = insufficient_reason or reason
    return insufficient_reason or grounding_reason


def _grounded_facts(atomic: dict[str, Any]) -> list[dict[str, Any]]:
    """锚定门核过的每条事实及其证据原文——通过项也列，监检要能看见依据。"""
    for tool in atomic.get("toolResults") or []:
        if not isinstance(tool, dict) or tool.get("toolName") != "validate_evidence_grounding":
            continue
        claimed = tool.get("claimedFacts") if isinstance(tool.get("claimedFacts"), list) else []
        return [
            {
                "factId": fact.get("factId"),
                "label": fact.get("label") or fact.get("factId"),
                "value": fact.get("value"),
                "scored": fact.get("scored") is not False,
                "platformVerified": fact.get("platformVerified") is True,
                "evidence": [item for item in fact.get("evidence") or [] if isinstance(item, dict)],
            }
            for fact in claimed
            if isinstance(fact, dict)
        ]
    return []


def _atomic_check_names(business_pack_id: str) -> dict[str, str]:
    """原子核查项的显示名。取不到业务包时退回空表，调用方显示 id。"""
    try:
        from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID, load_business_pack

        pack = load_business_pack(business_pack_id or DEFAULT_BUSINESS_PACK_ID)
    except Exception:  # noqa: BLE001 -- 业务包读取失败只影响显示名，调用方回退到原子项 ID
        return {}
    return {
        str(check.get("id")): str(check.get("name") or "")
        for check in pack.get("atomicChecks") or []
        if isinstance(check, dict) and check.get("id")
    }



def _unscored_facts(atomic: dict[str, Any]) -> list[dict[str, Any]]:
    """锚定门标为 unscored 的事实（confidenceUnavailable），附带它们引用的抽取字段。"""
    output: list[dict[str, Any]] = []
    for tool in atomic.get("toolResults") or []:
        if not isinstance(tool, dict) or tool.get("toolName") != "validate_evidence_grounding":
            continue
        facts = tool.get("facts") if isinstance(tool.get("facts"), dict) else {}
        indexes = {int(item) for item in facts.get("unscoredFacts") or [] if str(item).isdigit()}
        claimed = tool.get("claimedFacts") if isinstance(tool.get("claimedFacts"), list) else []
        for index, fact in enumerate(claimed, 1):
            if index in indexes and isinstance(fact, dict):
                output.append(
                    {
                        "factId": fact.get("factId"),
                        "label": fact.get("label") or fact.get("factId"),
                        "value": fact.get("value"),
                        "documentVersionId": fact.get("documentVersionId"),
                        # 印章一类没有抽取字段的事实：界面按 factPath 让人确认。
                        "factPath": fact.get("factPath") or "",
                        "fields": [item for item in fact.get("fields") or [] if isinstance(item, dict)],
                    }
                )
    return output
