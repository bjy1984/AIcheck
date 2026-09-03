from __future__ import annotations

import hashlib
import html
import json
import os
import re
import unicodedata
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from libs.business_pack import load_business_pack, matching_rule_for_node
from libs.contracts.responses import server_time
from libs.model_usage import estimate_messages_tokens, estimate_text_tokens
from libs.qwen_runtime import resolved_model_label
from libs.manual_binding_links import SUBMITTED_BINDING_STATUSES
from libs.review_evidence import active_node_document_versions

PROMPT_VERSION = "project-monolithic-analysis@1.3.0"

# --- Token 预算校准（2026-08-28，第一阶段 prompt 长度优化）---
#
# estimate_text_tokens 是 utf8字节÷4 的启发式，对本功能的中文 OCR + JSON 载荷
# **系统性偏低**（8 对生产实报校准：DeepSeek ×1.19–1.31，通义 DashScope ×1.51，
# 同一 prompt 降级到备胎时贵 51%——分词器不同）。偏低的后果是「预检通过、
# 供应商 400」，比预检拒绝更糟。
#
# 可用输入按「主/备两家中最紧的一家」取：备胎随时可能接住任何一次调用，
# 只按主供应商算预算，主供应商故障瞬间大项目的降级调用必被备胎拒绝。
PRIMARY_TOKEN_FACTOR_ENV = "AICHECK_PA_TOKEN_FACTOR_PRIMARY"
FALLBACK_TOKEN_FACTOR_ENV = "AICHECK_PA_TOKEN_FACTOR_FALLBACK"
FALLBACK_CONTEXT_TOKENS_ENV = "AICHECK_LLM_FALLBACK_MAX_CONTEXT_TOKENS"
DEFAULT_PRIMARY_TOKEN_FACTOR = 1.35  # 实测上界 1.31 + 余量
DEFAULT_FALLBACK_TOKEN_FACTOR = 1.60  # 实测 1.51 + 余量


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def dynamic_reserved_output_tokens(node_count: int) -> int:
    """输出预留随节点数缩放。

    实报口径（含 reasoning tokens）：20 节点 13,542、3 节点最高 4,679。
    写死 24,000 的两头都错：小项目白锁 20% 输入空间，百节点项目又不够
    （finish_reason=length → LLM_OUTPUT_TRUNCATED）。公式按实报 ×1.6 余量。
    """
    return max(8000, min(4000 + 900 * max(1, int(node_count)), 32768))


def provider_token_budgets(max_context: int, reserved: int) -> list[dict[str, Any]]:
    """各供应商的可用输入预算（以本估算器的原始口径计）。

    availableRawTokens = (上下文 − 输出预留) ÷ 该家校准系数——预检拿原始估算
    直接与它比较即可。备胎地址与密钥齐全才计入（与 fallback_provider 同规矩）。
    """
    budgets = [
        {
            "provider": "primary",
            "contextTokens": int(max_context),
            "tokenFactor": _float_env(PRIMARY_TOKEN_FACTOR_ENV, DEFAULT_PRIMARY_TOKEN_FACTOR),
        }
    ]
    if os.getenv("AICHECK_LLM_FALLBACK_API_BASE") and os.getenv("AICHECK_LLM_FALLBACK_API_KEY"):
        fallback_context = int(
            os.getenv(FALLBACK_CONTEXT_TOKENS_ENV) or max_context
        )
        budgets.append(
            {
                "provider": "fallback",
                "contextTokens": fallback_context,
                "tokenFactor": _float_env(
                    FALLBACK_TOKEN_FACTOR_ENV, DEFAULT_FALLBACK_TOKEN_FACTOR
                ),
            }
        )
    for budget in budgets:
        budget["availableRawTokens"] = int(
            max(0, budget["contextTokens"] - reserved) / budget["tokenFactor"]
        )
    return budgets
DEFAULT_BUSINESS_PACK_ID = "engineering_inspection_v1"
DEFAULT_MODEL_ALIAS = "project-review-large"

_HTML_TAG_PATTERN = re.compile(r"<[^>]*>")
_HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*?/?>", re.IGNORECASE)


SYSTEM_PROMPT = """你是压力管道安装工程监督检验 AI 审查代理。

你将收到一个工程中所有有有效挂接资料业务节点的规则、资料要求、node.fileRefs，以及项目级唯一 project.fileCorpus。请在同一次模型调用中完成全部节点分析。

强制要求：
1. Resolve every node.fileRefs[].fileId against project.fileCorpus before reviewing that node.
2. Use only fileCorpus entries referenced by the current node.fileRefs.
3. criteria、checkMethod 和 configuredRequirements 是审查依据，不是已被证据证明的事实。
4. quotedText 必须逐字存在于对应 fullOcrText；不连续原文必须拆成多条 evidenceRef。
5. ruleRef 只能逐字引用当前节点 criteria 或 checkMethod。
6. 没有直接证据时使用 insufficient_evidence、human_confirm 和空 evidenceRefs。
7. 所有 Finding 强制 requiresHumanConfirmation=true，不得改变正式业务状态。
8. 只输出符合 outputSchema 的一个合法 JSON 对象。
9. fileCorpus 条目带 identicalToFileId 时，表示该文件内容与所指文件逐字相同：
   按所指文件的 fullOcrText 审查，evidenceRefs.fileId 仍写当前文件自己的 fileId。
10. node.certificateVerification 是服务端对证照/资格证有效期、持证主体、许可范围的
   确定性核验结论。解释并引用它，不得改写：result 为 failed 的证书不得判为满足，
   evidence_insufficient 的证书只能要求人工确认；有效期数值以它为准。
   findings 面向监检人员：用「服务端证照核验通过/未通过/证据不足」等业务语言表述，
   不要把 certificateVerification、result、evidence_insufficient 这类字段名或枚举值写进
   title/description。
"""


OUTPUT_SCHEMA = {
    "nodeReviews": [
        {
            "nodeId": "number",
            "reviewResult": "supported|partially_supported|insufficient_evidence|conflict|mismatch",
            "findings": [
                {
                    "findingType": "string",
                    "severity": "low|medium|high|critical",
                    "title": "string",
                    "description": "string",
                    "evidenceRefs": [
                        {
                            "fileId": "string",
                            "pageNo": "number|null",
                            "quotedText": "verbatim string",
                        }
                    ],
                }
            ],
        }
    ],
}


class ProjectAnalysisContextLimitError(RuntimeError):
    def __init__(
        self,
        *,
        estimated_tokens: int,
        max_context_tokens: int,
        reserved_output_tokens: int,
    ) -> None:
        self.estimated_tokens = int(estimated_tokens)
        self.max_context_tokens = int(max_context_tokens)
        self.reserved_output_tokens = int(reserved_output_tokens)
        self.available_input_tokens = max(0, self.max_context_tokens - self.reserved_output_tokens)
        super().__init__("PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED")


def _stable_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean_project_ocr_text(source: str) -> str:
    text = unicodedata.normalize("NFC", str(source)).replace("\r\n", "\n").replace("\r", "\n")
    text = _HTML_IMAGE_PATTERN.sub("", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</t[dh]\s*>", " | ", text, flags=re.IGNORECASE)
    text = re.sub(r"</tr\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</table\s*>", "\n", text, flags=re.IGNORECASE)
    text = _HTML_TAG_PATTERN.sub("", text)
    text = html.unescape(text)
    text = "".join(
        character
        for character in text
        if character in "\n\t"
        or (unicodedata.category(character) not in {"Cc", "Cf"} and character != "\ufffd")
    )
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"[ \t\u00a0\u3000]+", " ", raw_line).strip()
        line = re.sub(r"(?:\s*\|\s*){2,}", " | ", line).strip(" |")
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


def _records(
    state: dict[str, Any], primary: str, fallback: str | None = None
) -> list[dict[str, Any]]:
    rows = state.get(primary)
    if not isinstance(rows, list) and fallback:
        rows = state.get(fallback)
    return [row for row in rows or [] if isinstance(row, dict)]


def _latest_parse_result(state: dict[str, Any], version_id: str) -> dict[str, Any]:
    rows = [
        row
        for row in _records(state, "ocr_parse_results")
        if str(row.get("documentVersionId") or "") == str(version_id)
    ]
    rows.sort(
        key=lambda row: str(
            row.get("finishedAt")
            or row.get("updatedAt")
            or row.get("createdAt")
            or row.get("id")
            or ""
        ),
        reverse=True,
    )
    return rows[0] if rows else {}


def _full_ocr_text(parse_result: dict[str, Any]) -> str:
    for key in ("fullText", "markdown", "contentMarkdown", "text"):
        value = parse_result.get(key)
        if isinstance(value, str) and value.strip():
            return value
    fragments = [row for row in parse_result.get("fragments") or [] if isinstance(row, dict)]
    fragments.sort(
        key=lambda row: (
            int(row.get("pageNo") or 0),
            str(row.get("id") or ""),
        )
    )
    return "\n".join(
        str(row.get("text") or row.get("content") or "")
        for row in fragments
        if str(row.get("text") or row.get("content") or "").strip()
    )


def _node_record(state: dict[str, Any], project_id: str, node_id: int) -> dict[str, Any]:
    return next(
        (
            row
            for row in _records(state, "tree_nodes", "project_nodes")
            if str(row.get("projectId") or "") == str(project_id)
            and int(row.get("nodeId") or row.get("id") or 0) == int(node_id)
        ),
        {},
    )


def _node_requirements(
    state: dict[str, Any], project_id: str, node_id: int
) -> list[dict[str, Any]]:
    return [
        deepcopy(row)
        for row in _records(state, "requirements", "node_requirements")
        if str(row.get("projectId") or project_id) == str(project_id)
        and int(row.get("nodeId") or 0) == int(node_id)
    ]


def _node_rule_text(
    state: dict[str, Any], business_pack_id: str, node_id: int, node: dict[str, Any]
) -> tuple[str, str]:
    criteria = str(node.get("criteria") or node.get("standardText") or "")
    check_method = str(node.get("checkMethod") or node.get("witnessText") or "")
    if criteria and check_method:
        return criteria, check_method
    persisted = next(
        (
            row
            for row in _records(state, "business_rule_versions", "rule_versions")
            if str(row.get("businessPackId") or business_pack_id) == business_pack_id
            and node_id in {int(value) for value in row.get("nodeIds") or []}
            and str(row.get("status") or "").lower() in {"production", "published", "已发布"}
        ),
        {},
    )
    try:
        packaged = matching_rule_for_node(load_business_pack(business_pack_id), node_id) or {}
    except (FileNotFoundError, KeyError, ValueError):
        packaged = {}
    rule = persisted or packaged
    return (
        criteria or str(rule.get("criteria") or rule.get("standardText") or ""),
        check_method or str(rule.get("checkMethod") or rule.get("witnessText") or ""),
    )


def _route_limits(model_route: dict[str, Any]) -> tuple[int, int]:
    budget = (
        model_route.get("budgetPolicy") if isinstance(model_route.get("budgetPolicy"), dict) else {}
    )
    maximum = int(model_route.get("maxContextTokens") or budget.get("maxContextTokens") or 0)
    reserved = int(
        model_route.get("reservedOutputTokens") or budget.get("reservedOutputTokens") or 0
    )
    return maximum, reserved


def _certificate_verification_for_node(
    state: dict[str, Any], project_id: str, node_id: int, document_version_ids: list[str]
) -> dict[str, Any] | None:
    from libs.review_orchestrator.certificate_facts import (
        build_certificate_facts,
        certificate_profile_for_node,
    )
    from libs.review_orchestrator.deterministic_tools import check_certificate_validity

    if not certificate_profile_for_node(node_id):
        return None
    facts = build_certificate_facts(state, project_id, node_id, document_version_ids)
    cert_facts = facts.get("certificateFacts") or {}
    period = cert_facts.get("period") or {}
    output = check_certificate_validity(
        {
            "certificateType": cert_facts.get("certificateType"),
            "certificates": list(cert_facts.get("certificates") or []),
            "periodStart": period.get("periodStart"),
            "periodEnd": period.get("periodEnd"),
            "referenceDate": period.get("referenceDate"),
            "expectedHolder": cert_facts.get("expectedHolder"),
            "requiredScopes": [],
        }
    )
    verified = output.get("facts") or {}
    return {
        "result": output.get("result"),
        "ruleVersion": output.get("ruleVersion"),
        "certificateType": verified.get("certificateType"),
        "period": {"start": verified.get("periodStart"), "end": verified.get("periodEnd"), "referenceDate": verified.get("referenceDate")},
        "expectedHolder": verified.get("expectedHolder"),
        "certificates": [
            {k: item.get(k) for k in ("label", "holder", "certificateNo", "issuer", "validFrom", "validUntil", "scopes", "result", "checks")}
            for item in verified.get("certificates") or []
        ],
        "warnings": list(output.get("warnings") or []) + list(cert_facts.get("extractionWarnings") or []),
    }


def _active_project_node_documents(
    state: dict[str, Any], project_id: str, node_id: int
) -> list[dict[str, Any]]:
    # 链接 ∪ 已提交人工挂载，逻辑收口在 review_evidence.active_node_document_versions：
    # 节点复核与一键分析看到的资料集合必须一致。
    return [deepcopy(row) for row in active_node_document_versions(state, project_id, node_id)]


def build_project_analysis_snapshot(
    state: dict[str, Any],
    project_id: str,
    *,
    business_pack_id: str = DEFAULT_BUSINESS_PACK_ID,
    prompt_version: str = PROMPT_VERSION,
    model_route: dict[str, Any],
) -> dict[str, Any]:
    evidence_node_ids = {
        int(row.get("nodeId") or 0)
        for row in _records(state, "node_evidence_links")
        if str(row.get("projectId") or "") == str(project_id)
        and str(row.get("manualStatus") or "").lower() != "rejected"
        and int(row.get("nodeId") or 0) > 0
    }
    submitted_binding_node_ids = {
        int(row.get("nodeId") or 0)
        for row in _records(state, "bindings", "node_bindings")
        if str(row.get("projectId") or "") == str(project_id)
        and int(row.get("nodeId") or 0) > 0
        and str(row.get("bindingStatus") or "") in SUBMITTED_BINDING_STATUSES
    }
    node_ids = sorted(evidence_node_ids | submitted_binding_node_ids)
    nodes: list[dict[str, Any]] = []
    document_versions: set[str] = set()
    document_ocr_hashes: dict[str, dict[str, str]] = {}
    node_snapshot_hashes: dict[str, str] = {}
    documents = {str(row.get("id") or ""): row for row in _records(state, "documents")}
    evidence_metadata: dict[str, dict[str, str]] = {}
    for node_id in node_ids:
        active = _active_project_node_documents(state, project_id, node_id)
        if not active:
            continue
        node = _node_record(state, project_id, node_id)
        criteria, check_method = _node_rule_text(state, str(business_pack_id), node_id, node)
        file_refs = [
            {
                "fileId": str(row.get("documentId") or ""),
                "documentVersionId": str(row.get("documentVersionId") or ""),
            }
            for row in active
        ]
        document_versions.update(row["documentVersionId"] for row in file_refs)
        for file_ref in file_refs:
            file_id = str(file_ref["fileId"])
            evidence_metadata[file_id] = {
                "documentVersionId": str(file_ref["documentVersionId"]),
                "fileName": str((documents.get(file_id) or {}).get("fileName") or file_id),
            }
        node_payload = {
            "nodeId": node_id,
            "nodeName": node.get("name") or node.get("nodeName") or f"节点 {node_id}",
            "criteria": criteria,
            "checkMethod": check_method,
            "configuredRequirements": _node_requirements(state, project_id, node_id),
            "fileRefs": file_refs,
        }
        # 证书类节点先做确定性有效性核验，结论随节点一起进提示词：模型看到的是
        # 「有效期至 2028-01-17，覆盖施工期：通过」而不是一堆 OCR 片段。它进快照哈希，
        # 证书事实变了就是一次新的分析。
        certificate_verification = _certificate_verification_for_node(
            state, project_id, node_id, [str(row["documentVersionId"]) for row in file_refs]
        )
        if certificate_verification is not None:
            node_payload["certificateVerification"] = certificate_verification
        nodes.append(node_payload)
        node_snapshot_hashes[str(node_id)] = _stable_hash(node_payload)
        for version_id in sorted({row["documentVersionId"] for row in file_refs}):
            parse_result = _latest_parse_result(state, version_id)
            source_text = _full_ocr_text(parse_result)
            document_ocr_hashes[version_id] = {
                "artifactHash": str(parse_result.get("artifactHash") or ""),
                "sourceContentHash": _stable_hash(source_text),
                "cleanedContentHash": _stable_hash(clean_project_ocr_text(source_text)),
            }
    maximum, reserved = _route_limits(model_route)
    core = {
        "schemaVersion": "ProjectAnalysisSnapshot@1.0.0",
        "projectId": str(project_id),
        "businessPackId": str(business_pack_id),
        "nodeIds": [row["nodeId"] for row in nodes],
        "nodes": nodes,
        "nodeSnapshotHashes": node_snapshot_hashes,
        "documentVersionIds": sorted(document_versions),
        "documentOcrHashes": {key: document_ocr_hashes[key] for key in sorted(document_ocr_hashes)},
        "promptVersion": str(prompt_version),
        "modelAlias": str(model_route.get("modelAlias") or DEFAULT_MODEL_ALIAS),
        "modelRouteVersion": str(model_route.get("version") or model_route.get("id") or ""),
        "maxContextTokens": maximum,
        "reservedOutputTokens": reserved,
    }
    snapshot_hash = _stable_hash(core)
    return {
        "id": f"PASNAP-{snapshot_hash.removeprefix('sha256:')[:16].upper()}",
        "projectAnalysisSnapshotId": f"PASNAP-{snapshot_hash.removeprefix('sha256:')[:16].upper()}",
        **core,
        # 展示/审计元数据只供服务端校验回填，不进入模型请求，也不参与快照哈希。
        "evidenceMetadata": {
            key: evidence_metadata[key] for key in sorted(evidence_metadata)
        },
        "snapshotHash": snapshot_hash,
        "createdAt": server_time(),
    }


def build_project_analysis_request(
    state: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    model_alias: str = DEFAULT_MODEL_ALIAS,
) -> dict[str, Any]:
    file_corpus: dict[str, dict[str, Any]] = {}
    content_primary_file: dict[str, str] = {}
    nodes = deepcopy(snapshot.get("nodes") or [])
    for node in nodes:
        for file_ref in node.get("fileRefs") or []:
            file_id = str(file_ref.get("fileId") or "")
            version_id = str(file_ref.get("documentVersionId") or "")
            parse_result = _latest_parse_result(state, version_id)
            source_text = _full_ocr_text(parse_result)
            cleaned_text = clean_project_ocr_text(source_text)
            if file_id in file_corpus:
                continue
            cleaned_hash = _stable_hash(cleaned_text)
            entry: dict[str, Any] = {
                "fileId": file_id,
                "sourceContentHash": _stable_hash(source_text),
                "cleanedContentHash": cleaned_hash,
            }
            # 内容级去重：同一份证书/报告以不同 fileId 挂多个节点时，全文只传
            # 一次，重复条目用 identicalToFileId 指向正主——语料是 prompt 长度的
            # 绝对主体，按 fileId 去重挡不住这种重复。空文本不参与（无意义且
            # 会把所有无 OCR 文件串成别名链）。
            primary_id = content_primary_file.get(cleaned_hash) if cleaned_text else None
            if primary_id:
                entry["identicalToFileId"] = primary_id
            else:
                entry["fullOcrText"] = cleaned_text
                if cleaned_text:
                    content_primary_file[cleaned_hash] = file_id
            file_corpus[file_id] = entry
        node["fileRefs"] = [
            {"fileId": str(file_ref.get("fileId") or "")}
            for file_ref in node.get("fileRefs") or []
        ]
    project = next(
        (
            row
            for row in _records(state, "projects")
            if str(row.get("id") or "") == str(snapshot.get("projectId") or "")
        ),
        {},
    )
    payload = {
        "task": "Analyze every included business node in one response.",
        "requirements": [
            "Resolve every node.fileRefs[].fileId against project.fileCorpus before reviewing the node.",
            "Use only fileCorpus entries referenced by the current node.fileRefs.",
            "Read every resolved fullOcrText completely and do not truncate evidence.",
            "Every finding requires human confirmation.",
        ],
        "project": {
            "projectId": snapshot.get("projectId"),
            "projectCode": project.get("projectCode")
            or project.get("code")
            or snapshot.get("projectId"),
            "projectName": project.get("name")
            or project.get("projectName")
            or snapshot.get("projectId"),
            "includedNodeCount": len(nodes),
            "nodes": nodes,
            "fileCorpus": file_corpus,
        },
        "outputSchema": OUTPUT_SCHEMA,
    }
    return {
        "model": model_alias,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        ],
    }


BATCH_BUDGET_ENV = "AICHECK_PA_MAX_BATCH_INPUT_TOKENS"


def _node_scaffold_tokens(node: dict[str, Any]) -> int:
    return estimate_text_tokens(json.dumps(node, ensure_ascii=False, separators=(",", ":")))


def _corpus_entry_tokens(entry: dict[str, Any]) -> int:
    return estimate_text_tokens(
        json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    )


def _node_corpus_primaries(
    node: dict[str, Any], corpus: dict[str, dict[str, Any]]
) -> set[str]:
    """节点实际要携带的语料条目键（别名跟到正主；别名条目本身也要带——
    模型按 fileId 解析，规则 9 告诉它跟去正主读全文）。"""
    keys: set[str] = set()
    for file_ref in node.get("fileRefs") or []:
        file_id = str(file_ref.get("fileId") or "")
        entry = corpus.get(file_id)
        if not entry:
            continue
        keys.add(file_id)
        alias = str(entry.get("identicalToFileId") or "")
        if alias and alias in corpus:
            keys.add(alias)
    return keys


def plan_project_analysis_batches(
    request_payload: dict[str, Any],
    *,
    batch_budget_tokens: int,
) -> list[dict[str, Any]]:
    """把节点集按共享文件亲和度装箱，每批不超预算。

    第二阶段 prompt 长度优化的核心：上限从「项目 ≤ 单次上下文」变成
    「无上限，成本线性」。装箱是确定性的（按文件集签名排序 + 首次适配）：
    同一快照永远得到同一批次方案，批间幂等才有据可依。
    引用同一份资料的节点尽量同批——语料是长度主体，跨批就要重复传。
    单个节点连自己的语料都装不下预算时不装箱（由调用方判超限，
    这是第三阶段检索式裁剪的触发条件）。
    """
    project = request_payload.get("project") or {}
    corpus = project.get("fileCorpus") or {}
    nodes = list(project.get("nodes") or [])
    scaffold = estimate_text_tokens(
        json.dumps(
            {key: value for key, value in request_payload.items() if key != "project"},
            ensure_ascii=False,
        )
    ) + 512  # system prompt + project 元数据的固定开销
    # 亲和度：按语料键集合的规范签名排序，共享文件的节点相邻
    def signature(node: dict[str, Any]) -> tuple:
        return (
            tuple(sorted(_node_corpus_primaries(node, corpus))),
            int(node.get("nodeId") or 0),
        )

    batches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for node in sorted(nodes, key=signature):
        node_keys = _node_corpus_primaries(node, corpus)
        node_tokens = _node_scaffold_tokens(node)
        standalone_cost = (
            scaffold
            + node_tokens
            + sum(_corpus_entry_tokens(corpus[key]) for key in node_keys)
        )
        if current is not None:
            added_corpus = node_keys - current["corpusKeys"]
            added_cost = node_tokens + sum(
                _corpus_entry_tokens(corpus[key]) for key in added_corpus
            )
            if current["estimatedTokens"] + added_cost <= batch_budget_tokens:
                current["nodeIds"].append(int(node.get("nodeId") or 0))
                current["corpusKeys"] |= node_keys
                current["estimatedTokens"] += added_cost
                continue
        current = {
            "index": len(batches),
            "nodeIds": [int(node.get("nodeId") or 0)],
            "corpusKeys": set(node_keys),
            "estimatedTokens": standalone_cost,
            "oversized": standalone_cost > batch_budget_tokens,
        }
        batches.append(current)
    for batch in batches:
        batch["corpusKeys"] = sorted(batch["corpusKeys"])
    return batches


def build_batch_request(
    request: dict[str, Any], node_ids: list[int]
) -> dict[str, Any]:
    """从冻结的全工程请求切出一个批次请求：只带批内节点与它们引用的语料
    （别名的正主一并带上）。消息结构、模型参数与全量请求完全一致。"""
    batch = deepcopy(request)
    payload = json.loads(batch["messages"][1]["content"])
    project = payload.get("project") or {}
    wanted = {int(item) for item in node_ids}
    corpus = project.get("fileCorpus") or {}
    kept_nodes = [
        node for node in project.get("nodes") or [] if int(node.get("nodeId") or 0) in wanted
    ]
    keys: set[str] = set()
    for node in kept_nodes:
        keys |= _node_corpus_primaries(node, corpus)
    project["nodes"] = kept_nodes
    project["includedNodeCount"] = len(kept_nodes)
    project["fileCorpus"] = {key: corpus[key] for key in sorted(keys) if key in corpus}
    payload["project"] = project
    batch["messages"][1]["content"] = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )
    return batch


def project_analysis_batch_budget(available_raw_tokens: int) -> int:
    try:
        configured = int(os.getenv(BATCH_BUDGET_ENV, "0"))
    except ValueError:
        configured = 0
    if configured > 0:
        return configured
    return available_raw_tokens


def project_analysis_preview(
    state: dict[str, Any],
    project_id: str,
    *,
    model_route: dict[str, Any],
) -> dict[str, Any]:
    snapshot = build_project_analysis_snapshot(
        state,
        project_id,
        business_pack_id=str(
            next(
                (
                    row.get("businessPackId")
                    for row in _records(state, "projects")
                    if str(row.get("id") or "") == str(project_id)
                ),
                DEFAULT_BUSINESS_PACK_ID,
            )
            or DEFAULT_BUSINESS_PACK_ID
        ),
        prompt_version=PROMPT_VERSION,
        model_route=model_route,
    )
    request = build_project_analysis_request(state, snapshot)
    estimated = estimate_messages_tokens(request["messages"])
    maximum, _route_reserved = _route_limits(model_route)
    reserved = dynamic_reserved_output_tokens(len(snapshot["nodeIds"]))
    budgets = provider_token_budgets(maximum, reserved)
    limiting = min(budgets, key=lambda item: item["availableRawTokens"])
    available = int(limiting["availableRawTokens"])
    payload = json.loads(request["messages"][1]["content"])
    reference_count = sum(len(node.get("fileRefs") or []) for node in payload["project"]["nodes"])
    documents_by_id = {
        str(row.get("id") or ""): row for row in _records(state, "documents")
    }
    top_corpus_files = sorted(
        (
            {
                "fileId": file_id,
                "fileName": str(
                    (documents_by_id.get(file_id) or {}).get("fileName")
                    or (documents_by_id.get(file_id) or {}).get("name")
                    or file_id
                ),
                "estimatedTokens": estimate_text_tokens(str(entry.get("fullOcrText") or "")),
            }
            for file_id, entry in payload["project"]["fileCorpus"].items()
            if entry.get("fullOcrText")
        ),
        key=lambda item: item["estimatedTokens"],
        reverse=True,
    )[:3]
    # 分批装箱：超限语义从「整体超上下文」收窄为「存在连自己语料都装不下
    # 一批的单节点」（那是第三阶段检索式裁剪的触发条件）。整体超限的项目
    # 现在自动分批，不再拒绝。
    batch_budget = project_analysis_batch_budget(available)
    batch_plan = plan_project_analysis_batches(payload, batch_budget_tokens=batch_budget)
    oversized_nodes = [
        node_id
        for batch in batch_plan
        if batch.get("oversized")
        for node_id in batch["nodeIds"]
    ]
    return {
        "projectId": str(project_id),
        "snapshot": snapshot,
        "request": request,
        "snapshotHash": snapshot["snapshotHash"],
        # 实际模型进幂等键（见 domain.create_project_analysis_run）：换模型即新运行。
        "modelName": resolved_model_label(str(model_route.get("modelAlias") or DEFAULT_MODEL_ALIAS)),
        "includedNodeCount": len(snapshot["nodeIds"]),
        "uniqueFileCount": len(payload["project"]["fileCorpus"]),
        "fileReferenceCount": reference_count,
        "estimatedInputTokens": estimated,
        "maxContextTokens": maximum,
        "reservedOutputTokens": reserved,
        "availableInputTokens": available,
        "contextLimitExceeded": bool(oversized_nodes),
        "oversizedNodeIds": oversized_nodes,
        "batchPlan": [
            {
                "index": batch["index"],
                "nodeIds": batch["nodeIds"],
                "estimatedTokens": batch["estimatedTokens"],
            }
            for batch in batch_plan
        ],
        "batchCount": len(batch_plan),
        "batchBudgetTokens": batch_budget,
        "tokenBudgets": budgets,
        "limitingProvider": limiting["provider"],
        "topCorpusFiles": top_corpus_files,
        "modelAlias": model_route.get("modelAlias") or DEFAULT_MODEL_ALIAS,
        "modelRouteVersion": snapshot["modelRouteVersion"],
    }


def prepare_project_analysis_request(
    state: dict[str, Any],
    project_id: str,
    *,
    model_route: dict[str, Any],
    model_call: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    preview = project_analysis_preview(state, project_id, model_route=model_route)
    if preview["contextLimitExceeded"]:
        raise ProjectAnalysisContextLimitError(
            estimated_tokens=preview["estimatedInputTokens"],
            max_context_tokens=preview["maxContextTokens"],
            reserved_output_tokens=preview["reservedOutputTokens"],
        )
    if model_call:
        model_call(preview["request"])
    return preview
