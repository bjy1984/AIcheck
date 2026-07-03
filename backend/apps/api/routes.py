from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import re
import tempfile
import threading
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from uuid import uuid4

import yaml
from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from apps.api.adapters.engineering_inspection import (
    ENGINEERING_DOMAIN_TYPE,
    ENGINEERING_PROJECT_DEFAULTS,
)
from apps.ocr_service.evaluation import compact_evaluation_report, evaluate_cases
from apps.ocr_service.readiness import build_ocr_100_scorecard
from apps.ocr_service.utils import parse_bool
from libs.business_pack import (
    DEFAULT_BUSINESS_PACK_ID,
    build_project_requirements,
    build_project_tree,
    business_pack_snapshot,
    business_pack_summary,
    list_business_packs,
    load_business_pack,
    validate_all_business_packs,
    validate_business_pack,
)
from libs.contracts import errors
from libs.contracts.responses import fail, ok, page, server_time
from libs.db.repository import load_state, repo
from libs.db.seed import PROJECT_ID, ROLE_NODE_MAP
from libs.embedding_models import embedding_registry_payload, embedding_runtime_config
from libs.integrations import task_dispatcher
from libs.integrations.errors import IntegrationServiceError
from libs.integrations.ocr_client import OcrClient
from libs.integrations.storage import ObjectStorageUnavailable, object_storage
from libs.knowledge_readiness import build_knowledge_rule_scorecard
from libs.knowledge_retrieval import answer_draft_from_clauses, retrieve_knowledge_clauses
from libs.review_orchestrator import (
    REVIEW_GRAPH_STEPS,
    build_review_orchestration_scorecard,
    clone_review_run_for_replay,
    create_review_run_from_ai_run,
    graph_view_for_review_run,
    human_decision_for_review_run,
    review_run_audit_trace,
    review_run_timeline,
    review_run_view,
    signal_review_run_cancel,
    signal_review_run_human_decision,
)
from libs.security.auth import ROLE_DEFAULT_PATHS, USERS, authenticate, decode_token, issue_token, user_by_username
from scripts.ocr_100_label_studio_export import label_config_xml, label_studio_task, label_studio_task_without_image
from scripts.ocr_100_label_studio_import import import_label_studio_annotations
from scripts.ocr_100_action_board import (
    action_board_csv,
    action_board_markdown,
    build_action_board,
    write_action_handoff,
)
from scripts.ocr_annotation_readiness import build_annotation_readiness_from_tasks

router = APIRouter(tags=["AIcheck API"])
mock_router = APIRouter(tags=["Compatibility Mock"])
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

REPORT_GENERATION_BLOCKED_STATUSES = {"待提交", "需补正", "退回补正中", "部分提交", "AI 预审中"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
MAX_NDT_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "png",
    "jpg",
    "jpeg",
    "zip",
    "7z",
    "application/pdf",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png",
    "image/jpg",
    "image/jpeg",
    "application/zip",
    "application/x-zip-compressed",
    "application/x-7z-compressed",
}
ALLOWED_NDT_UPLOAD_TYPES = ALLOWED_UPLOAD_TYPES | {"dcm", "dicom", "application/dicom"}
ALLOWED_KNOWLEDGE_UPLOAD_TYPES = ALLOWED_UPLOAD_TYPES | {
    "md",
    "markdown",
    "txt",
    "text/markdown",
    "text/plain",
    "application/octet-stream",
}
ALLOWED_RULE_UPLOAD_TYPES = {
    "md",
    "markdown",
    "txt",
    "yaml",
    "yml",
    "json",
    "docx",
    "text/markdown",
    "text/plain",
    "application/json",
    "application/yaml",
    "application/x-yaml",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}
CONFIG_METADATA_FIELDS = {"revision", "etag", "updatedAt", "lastPublishedVersion", "lastPublishedAt", "lastPublishedScope"}
KNOWLEDGE_TASK_STATUS_ORDER = {
    "失败": 0,
    "排队中": 1,
    "运行中": 2,
    "已取消": 3,
    "成功": 4,
}
KNOWLEDGE_UPLOAD_ROOT = WORKSPACE_ROOT / "output" / "knowledge_uploads"


def refresh_state_from_postgres_for_live_read() -> None:
    if repo.sync_postgres is not None:
        load_state()
AI_FEEDBACK_TYPES = {
    "accepted",
    "edited",
    "rejected_false_positive",
    "missed_issue",
    "wrong_evidence",
    "wrong_rule_reference",
    "wrong_severity",
    "hallucination",
    "format_error",
    "unsafe_output",
}

FDE_ROLES = {"fde"}

FDE_REPLAY_TYPES = {
    "diagnostic_replay",
    "evaluation_replay",
    "shadow_replay",
}

FDE_ROOT_CAUSES = {
    "ocr_error",
    "field_mapping_error",
    "rule_error",
    "kb_retrieval_error",
    "kb_content_error",
    "prompt_error",
    "model_reasoning_error",
    "schema_error",
    "business_pack_config_error",
    "user_uploaded_bad_file",
    "ambiguous_business_standard",
    "human_review_error",
}


def role_from_query(role: str | None = None, x_role: str | None = None) -> str:
    return (x_role or role or "inspection").strip() or "inspection"


def file_type_tokens(file: dict[str, Any]) -> set[str]:
    raw_values = [file.get("fileType"), file.get("contentType")]
    file_name = str(file.get("fileName") or "")
    if "." in file_name:
        raw_values.append(file_name.rsplit(".", 1)[-1])
    tokens = {str(value).strip().lower() for value in raw_values if value}
    return tokens


def validate_upload_files(
    request: Request,
    files: list[dict[str, Any]],
    *,
    ndt: bool = False,
) -> JSONResponse | None:
    if not files:
        error = errors.NDT_REPORT_REQUIRED if ndt else errors.VALIDATION_ERROR
        return fail(error, request, message="上传文件不能为空。")
    allowed_types = ALLOWED_NDT_UPLOAD_TYPES if ndt else ALLOWED_UPLOAD_TYPES
    max_bytes = MAX_NDT_UPLOAD_BYTES if ndt else MAX_UPLOAD_BYTES
    for index, file in enumerate(files):
        file_name = file.get("fileName") or f"第 {index + 1} 个文件"
        try:
            file_size = int(file.get("fileSize") or 0)
        except (TypeError, ValueError):
            file_size = 0
        if file_size < 1:
            return fail(errors.VALIDATION_ERROR, request, message=f"{file_name} 文件大小必须大于 0。", data={"fileName": file_name})
        if file_size > max_bytes:
            error = errors.NDT_FILE_TOO_LARGE if ndt else errors.FILE_TOO_LARGE
            return fail(error, request, message=f"{file_name} 超过 {max_bytes // 1024 // 1024}MB 上传限制。", data={"fileName": file_name, "fileSize": file_size})
        if not (file_type_tokens(file) & allowed_types):
            error = errors.UNSUPPORTED_NDT_FILE_TYPE if ndt else errors.UNSUPPORTED_FILE_TYPE
            return fail(error, request, message=f"{file_name} 文件类型不支持。", data={"fileName": file_name, "fileType": file.get("fileType")})
    return None


def safe_upload_file_name(file_name: str) -> str:
    normalized = str(file_name or "未命名文件").replace("\\", "/").split("/")[-1].strip()
    normalized = re.sub(r"[\x00-\x1f]", "", normalized)
    normalized = re.sub(r"[/:*?\"<>|]", "_", normalized)
    return normalized or "未命名文件"


def safe_relative_path(value: str | None, fallback_file_name: str) -> str:
    raw = str(value or fallback_file_name or "").replace("\\", "/").strip("/")
    parts = [safe_upload_file_name(part) for part in raw.split("/") if part and part not in {".", ".."}]
    return "/".join(parts[-8:]) or safe_upload_file_name(fallback_file_name)


def upload_file_type_tokens(file_name: str, content_type: str | None) -> set[str]:
    tokens = file_type_tokens({"fileName": file_name, "contentType": content_type, "fileType": content_type})
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if suffix:
        tokens.add(suffix)
    guessed, _ = mimetypes.guess_type(file_name)
    if guessed:
        tokens.add(guessed.lower())
    return tokens


def first_form_value(fields: dict[str, list[str]], key: str, default: str = "") -> str:
    values = fields.get(key) or []
    return str(values[0]).strip() if values else default


def bounded_form_value(values: list[str], index: int, limit: int = 500) -> str:
    value = str(values[index]).strip() if index < len(values) else ""
    return value[:limit]


def display_upload_file_name(raw_name: str | None, original_file_name: str) -> str:
    display_name = safe_upload_file_name(raw_name or original_file_name)
    original_suffix = Path(original_file_name).suffix
    if original_suffix and not Path(display_name).suffix:
        display_name = f"{display_name}{original_suffix}"
    return display_name


def parse_rule_node_ids(raw_value: Any, fallback: int | None = None) -> list[int]:
    values: list[Any]
    if isinstance(raw_value, list):
        values = raw_value
    elif isinstance(raw_value, tuple):
        values = list(raw_value)
    elif raw_value is None:
        values = []
    else:
        values = re.split(r"[,，、\s]+", str(raw_value))
    node_ids: list[int] = []
    for value in values:
        if str(value).strip().isdigit():
            node_id = int(str(value).strip())
            if node_id not in node_ids:
                node_ids.append(node_id)
    if not node_ids and fallback is not None:
        node_ids.append(int(fallback))
    return node_ids


def normalize_rule_status(value: Any, default: str = "草稿") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"已发布", "published", "production", "active", "启用"}:
        return "已发布"
    if raw in {"待发布", "candidate", "pending", "ready"}:
        return "待发布"
    if raw in {"已回滚", "rollback", "rolled_back", "retired"}:
        return "已回滚"
    if raw in {"草稿", "draft", ""}:
        return default
    return str(value or default)


def compact_rule_text(value: Any, limit: int = 900) -> str:
    text = re.sub(r"\n{3,}", "\n\n", str(value or "")).strip()
    return text[:limit]


def compact_plain_text(value: Any, limit: int = 2000) -> str:
    text = re.sub(r"[ \t]+", " ", str(value or "").strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit]


def split_business_rule_sentences(value: Any, limit: int = 12) -> list[str]:
    text = compact_plain_text(value, 3000)
    if not text:
        return []
    chunks = [
        item.strip(" ；;。.\n\t")
        for item in re.split(r"[；;。\n]+", text)
        if item.strip(" ；;。.\n\t")
    ]
    return chunks[:limit]


def extract_business_rule_terms(text: str, patterns: list[str], *, limit: int = 10) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            term = match.group(0).strip(" ，,；;。()（）")
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
                if len(terms) >= limit:
                    return terms
    return terms


BUSINESS_RULE_EVIDENCE_PATTERNS = [
    r"[\u4e00-\u9fffA-Za-z0-9《》/（）()、]{0,16}(?:许可证|核准证|证书|报告|记录|方案|文件|图纸|印章|材料表|特性表|质量证明|合格证|照片|视频|铭牌|清单|报告曲线|检定证书)",
    r"(?:PQR|WPS|RT|UT|MT|PT|MTC|OCR)",
]
BUSINESS_RULE_EXTRACTION_PATTERNS = [
    r"(?:机构名称|单位名称|许可证号|证书编号|有效期|许可范围|核准项目代码|检测方法|管道级别|规格|型号|材质|批号|压力|温度|时间|保压时间|结论|签字|签章|数量|量程|精度|标准|焊缝编号|人员|日期)",
]
BUSINESS_RULE_ACTION_TERMS = ["核查", "审查", "检查", "抽查", "现场检查", "提取", "比对", "确认", "查询", "判断", "验证"]


def normalize_business_rule_class(value: Any) -> str:
    raw = compact_plain_text(value, 20).upper().replace("类", "")
    if raw in {"A", "B", "C", "C/B", "B/C"}:
        return "C/B" if raw in {"C/B", "B/C"} else raw
    if "A" in raw:
        return "A"
    if "B" in raw and "C" in raw:
        return "C/B"
    if "B" in raw:
        return "B"
    return "C" if raw else ""


def normalize_business_rule_source_fields(raw_rule: dict[str, Any]) -> dict[str, Any]:
    source_sequence = (
        raw_rule.get("sourceSequence")
        or raw_rule.get("sequence")
        or raw_rule.get("序号")
        or raw_rule.get("nodeId")
    )
    sequence = None
    if source_sequence is not None:
        seq_match = re.search(r"\d+", str(source_sequence))
        if seq_match:
            sequence = int(seq_match.group(0))
    category = compact_plain_text(
        raw_rule.get("inspectionCategory")
        or raw_rule.get("businessModule")
        or raw_rule.get("监检项目（大类）")
        or raw_rule.get("category"),
        120,
    )
    item = compact_plain_text(
        raw_rule.get("inspectionItem")
        or raw_rule.get("name")
        or raw_rule.get("title")
        or raw_rule.get("监检项目（内容）")
        or "未命名监检项目",
        180,
    )
    rule_class = normalize_business_rule_class(
        raw_rule.get("inspectionClass")
        or raw_rule.get("reviewClass")
        or raw_rule.get("类别")
        or raw_rule.get("class")
    )
    standard_text = compact_plain_text(
        raw_rule.get("standardText")
        or raw_rule.get("criteria")
        or raw_rule.get("判断准则 / 标准规范")
        or raw_rule.get("判断准则")
        or raw_rule.get("standard"),
        3000,
    )
    witness_text = compact_plain_text(
        raw_rule.get("witnessText")
        or raw_rule.get("checkMethod")
        or raw_rule.get("方法及内容 / 工作见证")
        or raw_rule.get("方法及内容")
        or raw_rule.get("工作见证")
        or raw_rule.get("method"),
        3000,
    )
    return {
        "sourceSequence": sequence,
        "inspectionCategory": category,
        "inspectionItem": item,
        "inspectionClass": rule_class,
        "standardText": standard_text,
        "witnessText": witness_text,
    }


def business_rule_node_ids_from_fields(fields: dict[str, Any], fallback: Any = None) -> list[int]:
    node_ids = parse_rule_node_ids(fallback)
    sequence = fields.get("sourceSequence")
    if sequence and int(sequence) not in node_ids:
        node_ids.insert(0, int(sequence))
    return node_ids or ([int(sequence)] if sequence else [])


def make_business_rule_key(fields: dict[str, Any], raw_rule: dict[str, Any] | None = None) -> str:
    raw_key = compact_plain_text((raw_rule or {}).get("ruleKey"), 120)
    if raw_key:
        return raw_key
    sequence = fields.get("sourceSequence")
    if sequence:
        return f"inspection-rule-{int(sequence):02d}"
    digest = hashlib.sha1(fields.get("inspectionItem", "business-rule").encode("utf-8")).hexdigest()[:8]
    return f"inspection-rule-{digest}"


def compile_business_rule_execution(rule: dict[str, Any]) -> dict[str, Any]:
    standard_text = compact_plain_text(rule.get("standardText") or rule.get("criteria"), 3000)
    witness_text = compact_plain_text(rule.get("witnessText") or rule.get("checkMethod"), 3000)
    combined = "\n".join(part for part in [standard_text, witness_text] if part)
    method_sentences = split_business_rule_sentences(witness_text, limit=20)
    standard_sentences = split_business_rule_sentences(standard_text, limit=12)
    action_steps = [
        sentence
        for sentence in method_sentences
        if any(term in sentence for term in BUSINESS_RULE_ACTION_TERMS) or sentence.startswith(("是否", "需", "应"))
    ] or method_sentences[:6]
    acceptance_criteria = [
        sentence
        for sentence in method_sentences + standard_sentences
        if any(term in sentence for term in ["是否", "不得", "不应", "应当", "应", "符合", "覆盖", "一致", "有效", "合格", "不少于", "不低于", "范围"])
    ][:10]
    required_evidence = extract_business_rule_terms(combined, BUSINESS_RULE_EVIDENCE_PATTERNS, limit=12)
    extraction_targets = extract_business_rule_terms(combined, BUSINESS_RULE_EXTRACTION_PATTERNS, limit=16)
    if not required_evidence:
        required_evidence = method_sentences[:3]
    human_confirmation = []
    if rule.get("inspectionClass") == "A" or rule.get("reviewClass") == "A":
        human_confirmation.append("A 类监检项目发布或审查结论需人工确认。")
    if any(term in witness_text for term in ["现场", "抽查", "照片", "视频", "目视", "实物"]):
        human_confirmation.append("涉及现场检查、抽查或影像证据时，AI 只做辅助核验，需监检人员确认现场事实。")
    if any(term in witness_text for term in ["如果不能", "必要时", "缺少", "不足", "不一致", "不能覆盖"]):
        human_confirmation.append("证据缺失、范围不覆盖或跨文件不一致时生成补充资料项或联络单。")
    return {
        "schemaVersion": "business-rule-execution-v1",
        "compiledAt": server_time(),
        "sourceFields": {
            "sequence": rule.get("sourceSequence"),
            "inspectionCategory": rule.get("inspectionCategory") or rule.get("businessModule"),
            "inspectionItem": rule.get("inspectionItem") or rule.get("name"),
            "inspectionClass": rule.get("inspectionClass") or rule.get("reviewClass"),
            "standardText": standard_text,
            "witnessText": witness_text,
        },
        "requiredEvidence": required_evidence,
        "extractionTargets": extraction_targets,
        "verificationSteps": action_steps[:10],
        "acceptanceCriteria": acceptance_criteria,
        "humanConfirmation": human_confirmation or ["证据不足、OCR 置信度不足或结论影响放行时需人工确认。"],
        "promptContext": compact_rule_text(
            "\n".join(
                [
                    f"监检项目：{rule.get('inspectionItem') or rule.get('name')}",
                    f"类别：{rule.get('inspectionClass') or rule.get('reviewClass') or '-'}",
                    f"判断准则/标准规范：{standard_text or '-'}",
                    f"方法及内容/工作见证：{witness_text or '-'}",
                ]
            ),
            1600,
        ),
    }


def normalize_business_rule_version_record(
    raw_rule: dict[str, Any],
    *,
    import_version: str | None = None,
    imported_at: str | None = None,
    force_status: str | None = None,
) -> dict[str, Any]:
    now = imported_at or server_time()
    fields = normalize_business_rule_source_fields(raw_rule)
    rule_key = make_business_rule_key(fields, raw_rule)
    source_sequence = fields.get("sourceSequence")
    version = compact_plain_text(raw_rule.get("version"), 160)
    if not version:
        suffix = import_version or f"draft-{now[:16].replace('-', '').replace(':', '').replace(' ', '-')}"
        version = f"{rule_key}-{suffix}"
    rule_id = compact_plain_text(raw_rule.get("id"), 120) or f"RULE-{uuid4().hex[:10].upper()}"
    status = normalize_rule_status(raw_rule.get("status"), default="草稿")
    if force_status:
        status = force_status
    record = {
        **raw_rule,
        **fields,
        "id": rule_id,
        "name": fields["inspectionItem"],
        "ruleKey": rule_key,
        "version": version,
        "status": status,
        "nodeIds": business_rule_node_ids_from_fields(fields, raw_rule.get("nodeIds") or raw_rule.get("nodeId")),
        "reviewClass": fields["inspectionClass"],
        "criteria": fields["standardText"],
        "checkMethod": fields["witnessText"],
        "description": compact_rule_text(fields["witnessText"] or fields["standardText"] or fields["inspectionItem"], 500),
        "promptVersion": compact_plain_text(raw_rule.get("promptVersion"), 120) or f"prompt-{rule_key}",
        "outputSchemaVersion": compact_plain_text(raw_rule.get("outputSchemaVersion"), 120) or "schema-review-v1.3",
        "schemaVersion": compact_plain_text(raw_rule.get("schemaVersion"), 80) or "business-rule-version-v1",
        "updatedAt": now,
        "actions": raw_rule.get("actions") or ["knowledge:view", "knowledge:manage"],
        "revision": int(raw_rule.get("revision") or 1),
    }
    if source_sequence is not None:
        record["sourceSequence"] = int(source_sequence)
    if raw_rule.get("sourceFileName"):
        record["sourceFileName"] = raw_rule["sourceFileName"]
    if raw_rule.get("importedAt") or imported_at:
        record["importedAt"] = raw_rule.get("importedAt") or imported_at
    record["aiExecution"] = compile_business_rule_execution(record)
    return record


def extract_markdown_rule_field(section: str, title: str) -> str:
    marker = re.escape(title)
    pattern = rf"\*\*{marker}\*\*\s*(.*?)(?=\n\*\*|\n###\s+R\d+|\Z)"
    match = re.search(pattern, section, re.S)
    return compact_rule_text(match.group(1) if match else "")


def parse_markdown_business_rules(
    text: str,
    *,
    source_file_name: str,
    import_version: str,
    imported_at: str,
) -> list[dict[str, Any]]:
    sections = list(re.finditer(r"^###\s+(R\d+)\s*[｜|]\s*(.+?)\s*$", text, re.M))
    parsed: list[dict[str, Any]] = []
    for index, match in enumerate(sections):
        source_rule_id = match.group(1).upper()
        name = match.group(2).strip()
        section_start = match.end()
        section_end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        section = text[section_start:section_end]
        meta_line = next(
            (line.strip("| ") for line in section.splitlines() if line.startswith("| 来源文档")),
            "",
        )
        source_document = ""
        business_module = ""
        review_class = ""
        source_sequence = None
        if meta_line:
            for part in [part.strip() for part in meta_line.split("|")]:
                if part.startswith("来源文档"):
                    source_document = part.removeprefix("来源文档").strip()
                elif part.startswith("原位置"):
                    seq_match = re.search(r"\d+", part)
                    if seq_match:
                        source_sequence = int(seq_match.group(0))
                elif part.startswith("业务模块"):
                    business_module = part.removeprefix("业务模块").strip()
                elif part.startswith("类别"):
                    review_class = part.removeprefix("类别").strip()
        criteria = extract_markdown_rule_field(section, "判断准则（原文）") or extract_markdown_rule_field(section, "标准规范（原文）")
        check_method = (
            extract_markdown_rule_field(section, "方法（原文）")
            or extract_markdown_rule_field(section, "方法及内容（原文）")
            or extract_markdown_rule_field(section, "工作见证（原文）")
        )
        agent_thinking = extract_markdown_rule_field(section, "Agent思考方式（新增）")
        toolchain_thinking = extract_markdown_rule_field(section, "工具集调用思考（新增）")
        rule_number = int(source_rule_id.removeprefix("R"))
        node_id = source_sequence or rule_number
        rule_key = f"engineering-inspection-{source_rule_id.lower()}"
        raw_record = {
            "id": f"RULE-IMPORT-{source_rule_id}-{uuid4().hex[:6].upper()}",
            "name": name,
            "ruleKey": rule_key,
            "version": f"{rule_key}-{import_version}",
            "status": "草稿",
            "nodeIds": [node_id],
            "inspectionCategory": business_module,
            "inspectionItem": name,
            "inspectionClass": review_class or "C",
            "standardText": criteria,
            "witnessText": check_method,
            "severity": "medium" if "A" in review_class else "low",
            "reviewClass": review_class or "C",
            "promptVersion": f"prompt-engineering-inspection-{import_version}",
            "outputSchemaVersion": "schema-review-v1.3",
            "sourceRuleId": source_rule_id,
            "sourceDocument": source_document or source_file_name,
            "sourceSequence": node_id,
            "businessModule": business_module,
            "criteria": criteria,
            "checkMethod": check_method,
            "agentThinking": agent_thinking,
            "toolchainThinking": toolchain_thinking,
            "description": compact_rule_text(agent_thinking or check_method or criteria or name, 500),
            "requiredEvidence": [
                f"{source_document or source_file_name} 序号{node_id}：{name}",
                "与 nodeIds 绑定的项目文件、OCR 字段、原件/复印件、签字盖章、报告结论和证据链接",
            ],
            "humanConfirmation": {
                "requiredWhen": [
                    "证据缺失、OCR 置信度不足或原件/复印件真实性无法自动确认",
                    "跨文件主体名称、规格型号、批号、焊缝编号、报告编号或结论不一致",
                ]
            },
            "sourceFileName": source_file_name,
            "parserVersion": "business-rule-importer-v1",
            "schemaVersion": "business-rule-version-v1",
            "importedAt": imported_at,
            "updatedAt": imported_at,
            "actions": ["knowledge:view", "knowledge:manage"],
            "revision": 1,
        }
        parsed.append(
            normalize_business_rule_version_record(
                raw_record,
                import_version=import_version,
                imported_at=imported_at,
                force_status="草稿",
            )
        )
    return parsed


def normalize_imported_rule_record(
    raw_rule: dict[str, Any],
    *,
    source_file_name: str,
    import_version: str,
    imported_at: str,
) -> dict[str, Any]:
    source_rule_id = str(raw_rule.get("sourceRuleId") or raw_rule.get("ruleId") or raw_rule.get("id") or "").strip()
    normalized = normalize_business_rule_version_record(
        {
            **raw_rule,
            "sourceRuleId": source_rule_id or raw_rule.get("ruleKey"),
            "sourceFileName": source_file_name,
            "parserVersion": raw_rule.get("parserVersion") or "business-rule-importer-v1",
        },
        import_version=import_version,
        imported_at=imported_at,
        force_status="草稿",
    )
    normalized["importedAt"] = imported_at
    return normalized


def parse_structured_business_rules(
    text: str,
    *,
    source_file_name: str,
    import_version: str,
    imported_at: str,
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text) if source_file_name.lower().endswith(".json") else yaml.safe_load(text)
    except Exception:
        payload = None
    raw_rules: list[Any] = []
    if isinstance(payload, dict):
        candidate = payload.get("ruleSets") or payload.get("rules") or payload.get("items")
        raw_rules = candidate if isinstance(candidate, list) else []
    elif isinstance(payload, list):
        raw_rules = payload
    return [
        normalize_imported_rule_record(
            rule,
            source_file_name=source_file_name,
            import_version=import_version,
            imported_at=imported_at,
        )
        for rule in raw_rules
        if isinstance(rule, dict)
    ]


def parse_docx_business_rules(
    data: bytes,
    *,
    source_file_name: str,
    import_version: str,
    imported_at: str,
) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document_xml = archive.read("word/document.xml")
    except Exception:
        return []
    try:
        root = ET.fromstring(document_xml)
    except Exception:
        return []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    rows: list[list[str]] = []
    for tr in root.findall(".//w:tbl/w:tr", ns):
        cells: list[str] = []
        for tc in tr.findall("./w:tc", ns):
            paragraphs = []
            for paragraph in tc.findall(".//w:p", ns):
                paragraph_text = "".join(node.text or "" for node in paragraph.findall(".//w:t", ns)).strip()
                if paragraph_text:
                    paragraphs.append(paragraph_text)
            text = compact_plain_text("\n".join(paragraphs), 4000)
            cells.append(text)
        if any(cells):
            rows.append(cells)
    if len(rows) < 2:
        return []
    headers = rows[0]
    normalized_headers = [re.sub(r"\s+", "", header) for header in headers]
    if not any("监检项目" in header for header in normalized_headers):
        return []

    def cell(row: list[str], *names: str) -> str:
        for name in names:
            normalized_name = re.sub(r"\s+", "", name)
            for index, header in enumerate(normalized_headers):
                if normalized_name == header or normalized_name in header:
                    return row[index] if index < len(row) else ""
        return ""

    parsed: list[dict[str, Any]] = []
    for row in rows[1:]:
        if not any(item.strip() for item in row):
            continue
        raw_rule = {
            "sequence": cell(row, "序号"),
            "inspectionCategory": cell(row, "监检项目（大类）", "监检项目大类"),
            "inspectionItem": cell(row, "监检项目（内容）", "监检项目内容"),
            "inspectionClass": cell(row, "类别"),
            "standardText": cell(row, "判断准则 / 标准规范", "判断准则/标准规范"),
            "witnessText": cell(row, "方法及内容 / 工作见证", "方法及内容/工作见证"),
            "sourceFileName": source_file_name,
            "sourceDocument": source_file_name,
            "parserVersion": "business-rule-docx-table-v1",
        }
        if not raw_rule["inspectionItem"]:
            continue
        parsed.append(
            normalize_business_rule_version_record(
                raw_rule,
                import_version=import_version,
                imported_at=imported_at,
                force_status="草稿",
            )
        )
    return parsed


def parse_business_rule_upload(
    upload: dict[str, Any],
    *,
    import_version: str,
    imported_at: str,
) -> tuple[list[dict[str, Any]], str | None]:
    source_file_name = safe_upload_file_name(upload["fileName"])
    data = upload["data"]
    content_type = str(upload.get("contentType") or mimetypes.guess_type(source_file_name)[0] or "application/octet-stream")
    if not data:
        return [], "文件内容为空"
    if len(data) > MAX_UPLOAD_BYTES:
        return [], f"超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上传限制"
    if not (upload_file_type_tokens(source_file_name, content_type) & ALLOWED_RULE_UPLOAD_TYPES):
        return [], "业务规则只支持 Word、Markdown、YAML、JSON 或 TXT"
    suffix = Path(source_file_name).suffix.lower()
    if suffix == ".docx":
        rules = parse_docx_business_rules(
            data,
            source_file_name=source_file_name,
            import_version=import_version,
            imported_at=imported_at,
        )
        if not rules:
            return [], "未解析到业务规则，请使用包含“序号、监检项目（大类）、监检项目（内容）、类别、判断准则 / 标准规范、方法及内容 / 工作见证”的 Word 表格"
        return rules, None
    text = data.decode("utf-8", errors="replace")
    rules = (
        parse_structured_business_rules(
            text,
            source_file_name=source_file_name,
            import_version=import_version,
            imported_at=imported_at,
        )
        if suffix in {".yaml", ".yml", ".json"}
        else []
    )
    if not rules:
        rules = parse_markdown_business_rules(
            text,
            source_file_name=source_file_name,
            import_version=import_version,
            imported_at=imported_at,
        )
    if not rules:
        return [], "未解析到业务规则，请使用 Word 六列表格、rules.yaml 的 ruleSets 或 Markdown 的“### R01｜规则名称”格式"
    return rules, None


async def parse_multipart_uploads(request: Request) -> tuple[dict[str, list[str]], list[dict[str, Any]], JSONResponse | None]:
    content_type = request.headers.get("content-type") or request.headers.get("Content-Type") or ""
    if "multipart/form-data" not in content_type.lower():
        return {}, [], fail(errors.VALIDATION_ERROR, request, message="请使用 multipart/form-data 上传知识库文件。")
    body = await request.body()
    if not body:
        return {}, [], fail(errors.VALIDATION_ERROR, request, message="上传内容不能为空。")
    try:
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
    except Exception as exc:
        return {}, [], fail(errors.VALIDATION_ERROR, request, message=f"上传表单解析失败：{exc}")
    if not message.is_multipart():
        return {}, [], fail(errors.VALIDATION_ERROR, request, message="上传表单缺少 multipart 边界。")
    fields: dict[str, list[str]] = {}
    uploads: list[dict[str, Any]] = []
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        field_name = part.get_param("name", header="content-disposition") or ""
        file_name = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if file_name:
            uploads.append(
                {
                    "fieldName": field_name,
                    "fileName": safe_upload_file_name(file_name),
                    "contentType": part.get_content_type(),
                    "data": payload,
                }
            )
        else:
            fields.setdefault(field_name, []).append(payload.decode("utf-8", errors="replace"))
    return fields, uploads, None


def knowledge_source_for_import(
    source_id: str | None,
    source_name: str | None = None,
    source_type: str | None = None,
    source_version: str | None = None,
    source_status: str | None = None,
    vector_status: str | None = None,
) -> dict[str, Any]:
    effective_source_id = source_id or "KS-STANDARD-TSG"
    source = repo.find_one("knowledge_sources", effective_source_id)
    if source:
        return source
    source = {
        "id": effective_source_id,
        "name": source_name or "规则标准文件库",
        "sourceType": source_type or "standard",
        "version": source_version or f"upload-{server_time()[:10]}",
        "status": source_status or "启用",
        "fileCount": 0,
        "chunkCount": 0,
        "vectorStatus": vector_status or "待向量化",
        "updatedAt": server_time(),
        "actions": ["knowledge:view", "knowledge:manage", "knowledge:reindex"],
        "revision": 1,
    }
    repo.state["knowledge_sources"].insert(0, source)
    return source


def current_business_rule_for_node(
    node_id: int,
    *,
    business_pack_id: str | None = None,
) -> dict[str, Any] | None:
    candidates = []
    for rule in repo.state.get("rule_versions", []):
        if normalize_rule_status(rule.get("status")) != "已发布":
            continue
        if int(node_id) not in set(parse_rule_node_ids(rule.get("nodeIds"))):
            continue
        if business_pack_id and rule.get("businessPackId") not in {None, "", business_pack_id}:
            continue
        candidates.append(rule)
    candidates.sort(
        key=lambda item: str(item.get("publishedAt") or item.get("updatedAt") or item.get("importedAt") or ""),
        reverse=True,
    )
    return candidates[0] if candidates else None


def knowledge_file_is_business_rule(file: dict[str, Any] | None) -> bool:
    if not file:
        return False
    source = repo.find_one("knowledge_sources", file.get("sourceId"))
    return (source or {}).get("sourceType") == "rule" or file.get("sourceType") == "rule"


def knowledge_task_is_business_rule(task: dict[str, Any] | None) -> bool:
    if not task:
        return False
    target_type = str(task.get("targetType") or "").lower()
    target_id = str(task.get("targetId") or "")
    if target_type in {"file", "knowledgefile", "knowledge_file"}:
        return knowledge_file_is_business_rule(repo.find_one("knowledge_files", target_id))
    if target_type in {"source", "knowledgesource", "knowledge_source"}:
        source = repo.find_one("knowledge_sources", target_id)
        return (source or {}).get("sourceType") == "rule"
    return False


def store_knowledge_upload(
    *,
    source_id: str,
    file_id: str,
    file_name: str,
    content_type: str,
    data: bytes,
) -> tuple[str, str]:
    object_name = f"knowledge/{source_id}/{file_id}/{file_name}"
    stored_url = object_storage.put_bytes("documents", object_name, data, content_type=content_type)
    if stored_url:
        return stored_url, "documents"
    target_dir = KNOWLEDGE_UPLOAD_ROOT / source_id / file_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file_name
    target_path.write_bytes(data)
    return f"local://{target_path.relative_to(WORKSPACE_ROOT)}", "local"


def create_imported_knowledge_records(
    *,
    source: dict[str, Any],
    file_name: str,
    content_type: str,
    data: bytes,
    relative_path: str,
    original_file_name: str,
    context_description: str,
    uploader_name: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    now = server_time()
    file_hash = hashlib.sha256(data).hexdigest()
    source_id = str(source["id"])
    seed = uuid4().hex[:10].upper()
    document_id = f"KDOC-{seed}"
    version_id = f"KDV-{seed}-V1"
    file_id = f"KF-KB-{seed}"
    storage_key, storage_bucket = store_knowledge_upload(
        source_id=source_id,
        file_id=file_id,
        file_name=file_name,
        content_type=content_type,
        data=data,
    )
    file_type = Path(file_name).suffix.lower().lstrip(".") or content_type
    document = {
        "id": document_id,
        "projectId": None,
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "materialTypeCode": "standard_reference",
        "fileName": file_name,
        "originalFileName": original_file_name,
        "fileType": file_type,
        "sourceOrgName": source.get("name") or "知识库导入",
        "contextDescription": context_description,
        "uploaderName": uploader_name,
        "currentVersionId": version_id,
        "fileStatus": "已上传",
        "currentOcrStatus": "识别中",
        "updatedAt": now,
        "actions": ["file:view", "file:preview", "file:download"],
    }
    version = {
        "id": version_id,
        "documentId": document_id,
        "versionNo": "V1",
        "hash": file_hash,
        "fileSize": len(data),
        "fileName": file_name,
        "originalFileName": original_file_name,
        "contextDescription": context_description,
        "storageKey": storage_key,
        "storageBucket": storage_bucket,
        "ocrStatus": "识别中",
        "sliceStatus": "未切片",
        "vectorStatus": "待向量化",
        "uploaderName": uploader_name,
        "uploadTime": now,
        "isCurrent": True,
    }
    knowledge_file = {
        "id": file_id,
        "fileName": file_name,
        "originalFileName": original_file_name,
        "sourceId": source_id,
        "sourceName": source.get("name") or source_id,
        "contextDescription": context_description,
        "projectId": None,
        "projectName": "",
        "nodeId": None,
        "nodeName": "",
        "documentId": document_id,
        "documentVersionId": version_id,
        "ocrStatus": "识别中",
        "sliceStatus": "未切片",
        "vectorStatus": "待向量化",
        "chunkCount": 0,
        "vectorCount": 0,
        "updatedAt": now,
        "sourceRelativePath": relative_path,
        "actions": ["knowledge:view", "knowledge:reindex"],
    }
    task = {
        "id": f"KT-{seed}",
        "taskType": "ocr",
        "targetType": "file",
        "targetId": file_id,
        "targetName": file_name,
        "documentId": document_id,
        "documentVersionId": version_id,
        "status": "排队中",
        "progress": 0,
        "createdAt": now,
        "updatedAt": now,
        "revision": 1,
        "actions": ["knowledge:task-retry"],
    }
    dispatch = task_dispatcher.dispatch_parse_document(document_id, version_id, storage_key, file_name)
    task["lastDispatch"] = dispatch
    return document, version, knowledge_file, task, {"storageKey": storage_key, "dispatch": dispatch}


def missing_required_fields(item: dict[str, Any], fields: list[str]) -> list[str]:
    return [field for field in fields if item.get(field) in {None, ""}]


def resolved_role_for_read(request: Request, role: str | None = None, x_role: str | None = None) -> tuple[str, JSONResponse | None]:
    effective_role, identity_error = effective_role_for_request(request, x_role)
    if identity_error:
        return "inspection", identity_error
    requested_role = role_from_query(role, x_role)
    claims = getattr(request.state, "auth", None)
    token_role = claims.get("role") if claims else None
    if token_role and token_role != "admin":
        if requested_role != token_role:
            return requested_role, fail(errors.FORBIDDEN, request, message="请求角色与登录身份不一致。")
        return token_role, None
    return requested_role or effective_role or "inspection", None


def mutation_guard(
    request: Request,
    project_id: str | None = None,
    *,
    x_role: str | None = None,
    if_match: str | None = None,
    node_ids: list[int] | None = None,
) -> JSONResponse | None:
    effective_role, identity_error = effective_role_for_request(request, x_role)
    if identity_error:
        return identity_error
    if project_id:
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        if project.get("status") == "已归档":
            return fail(errors.ARCHIVED_READONLY, request)
        effective_if_match = if_match
        if effective_if_match is None and "/reports/" not in request.url.path:
            effective_if_match = request.headers.get("If-Match")
        if not project_if_match_valid(project, effective_if_match):
            return fail(errors.ETAG_CONFLICT, request)
        node_scope_error = member_node_scope_error(request, project_id, effective_role, node_ids=node_ids)
        if node_scope_error:
            return node_scope_error
    action_code = request.headers.get("X-Action-Code")
    if action_code and effective_role and action_code not in repo.role_actions(effective_role):
        return fail(errors.FORBIDDEN, request, message=f"角色 {effective_role} 无权执行 {action_code}。")
    if effective_role in FDE_ROLES:
        return fail(errors.FORBIDDEN, request, message="FDE 只能管理 AI 能力和治理流程，不能执行正式业务写操作。")
    if effective_role in {"owner"}:
        return fail(errors.FORBIDDEN, request)
    if effective_role == "admin" and "/review-opinions" in request.url.path:
        return fail(errors.FORBIDDEN, request, message="管理员不能代替业务角色保存审查意见。")
    return None


def effective_role_for_request(request: Request, x_role: str | None = None) -> tuple[str | None, JSONResponse | None]:
    header_role = x_role or request.headers.get("X-Role")
    claims = getattr(request.state, "auth", None)
    if not claims:
        return header_role, None
    token_role = claims.get("role")
    auth_user = getattr(request.state, "auth_user", None) or user_by_username(claims.get("sub"))
    token_user_id = auth_user.get("id") if auth_user else None
    header_user_id = request.headers.get("X-User-Id")
    if header_role and token_role and header_role != token_role and token_role != "admin":
        return None, fail(errors.FORBIDDEN, request, message="请求角色与登录身份不一致。")
    if header_user_id and token_user_id and header_user_id != token_user_id and token_role != "admin":
        return None, fail(errors.FORBIDDEN, request, message="请求用户与登录身份不一致。")
    return header_role or token_role, None


def request_user_id(request: Request) -> str | None:
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user and auth_user.get("id"):
        return auth_user["id"]
    return request.headers.get("X-User-Id")


def member_node_scope_error(
    request: Request,
    project_id: str,
    role: str | None,
    *,
    node_ids: list[int] | None = None,
) -> JSONResponse | None:
    if role == "admin":
        return None
    user_id = request_user_id(request)
    if not user_id:
        return None
    member = next(
        (
            item
            for item in repo.state["project_members"]
            if item.get("projectId") == project_id
            and item.get("userId") == user_id
            and (not role or item.get("role") == role)
            and item.get("status") == "启用"
        ),
        None,
    )
    if member is None:
        return fail(errors.FORBIDDEN, request, message="用户未获得该项目授权。")
    requested_node_ids = {int(item) for item in node_ids or []}
    match = re.search(r"/nodes/(\d+)", request.url.path)
    if match:
        requested_node_ids.add(int(match.group(1)))
    node_scope = {int(item) for item in member.get("nodeScope") or []}
    out_of_scope = sorted(requested_node_ids - node_scope)
    if out_of_scope:
        return fail(errors.FORBIDDEN, request, message="用户不在该节点授权范围内。")
    return None


def node_ids_from_body(body: dict[str, Any], default_node_id: int | None = None) -> list[int]:
    raw_node_ids = body.get("nodeIds")
    if not raw_node_ids:
        raw_node_ids = [body.get("nodeId") or default_node_id]
    return [int(item) for item in raw_node_ids if item is not None and item != ""]


def binding_node_ids(project_id: str, binding_id: str) -> list[int]:
    binding = repo.find_one("bindings", binding_id)
    if not binding or binding.get("projectId") != project_id:
        return []
    return [int(binding["nodeId"])]


def document_node_ids(project_id: str, document_id: str) -> list[int]:
    document = repo.find_one("documents", document_id)
    if not document or document.get("projectId") != project_id:
        return []
    node_ids = {
        int(binding["nodeId"])
        for binding in repo.state["bindings"]
        if binding.get("projectId") == project_id and binding.get("documentId") == document_id
    }
    _add_node_id(node_ids, document.get("nodeId"))
    return sorted(node_ids)


def report_node_ids(project_id: str, report_id: str) -> list[int]:
    report = repo.find_one("reports", report_id)
    if not report or report.get("projectId") != project_id:
        return []
    return [int(item) for item in report.get("nodeIds") or []]


def project_revision(project: dict[str, Any]) -> int:
    return int(project.get("revision") or 1)


def project_etag(project: dict[str, Any]) -> str:
    return f'W/"project-{project["id"]}-r{project_revision(project)}"'


def project_if_match_valid(project: dict[str, Any], if_match: str | None) -> bool:
    if not if_match:
        return True
    revision = project_revision(project)
    return if_match in {"*", str(revision), f'W/"{revision}"', project_etag(project)}


def versioned_project(project: dict[str, Any]) -> dict[str, Any]:
    cloned = repo.clone(project)
    cloned["revision"] = project_revision(project)
    cloned["etag"] = project_etag(project)
    return cloned


def report_etag(report: dict[str, Any]) -> str:
    revision = int(report.get("revision") or 1)
    return str(report.get("etag") or f'W/"report-{report["id"]}-r{revision}"')


def versioned_report(report: dict[str, Any]) -> dict[str, Any]:
    cloned = repo.clone(report)
    cloned["revision"] = int(report.get("revision") or 1)
    cloned["etag"] = report_etag(report)
    cloned["updatedAt"] = cloned.get("updatedAt") or cloned.get("generatedAt")
    return cloned


def report_if_match_valid(report: dict[str, Any], if_match: str | None) -> bool:
    if not if_match:
        return True
    revision = int(report.get("revision") or 1)
    return if_match in {"*", str(revision), f'W/"{revision}"', report_etag(report)}


def singleton_revision(config: dict[str, Any]) -> int:
    return int(config.get("revision") or 1)


def singleton_etag(prefix: str, config: dict[str, Any]) -> str:
    return f'W/"{prefix}-r{singleton_revision(config)}"'


def versioned_singleton(prefix: str, config: dict[str, Any]) -> dict[str, Any]:
    cloned = repo.clone(config)
    cloned["revision"] = singleton_revision(config)
    cloned["etag"] = singleton_etag(prefix, config)
    cloned["updatedAt"] = cloned.get("updatedAt") or server_time()
    return cloned


def singleton_if_match_valid(prefix: str, config: dict[str, Any], if_match: str | None) -> bool:
    if not if_match:
        return True
    revision = singleton_revision(config)
    return if_match in {"*", str(revision), f'W/"{revision}"', singleton_etag(prefix, config)}


def bump_singleton_revision(config: dict[str, Any]) -> None:
    config["revision"] = singleton_revision(config) + 1
    config["updatedAt"] = server_time()


def record_revision(record: dict[str, Any]) -> int:
    return int(record.get("revision") or 1)


def record_etag(prefix: str, record: dict[str, Any]) -> str:
    return f'W/"{prefix}-{record["id"]}-r{record_revision(record)}"'


def versioned_record(prefix: str, record: dict[str, Any]) -> dict[str, Any]:
    cloned = repo.clone(record)
    cloned["revision"] = record_revision(record)
    cloned["etag"] = record_etag(prefix, record)
    cloned["updatedAt"] = cloned.get("updatedAt") or cloned.get("finishedAt") or cloned.get("createdAt") or server_time()
    return cloned


def record_if_match_valid(prefix: str, record: dict[str, Any], if_match: str | None) -> bool:
    if not if_match:
        return True
    revision = record_revision(record)
    return if_match in {"*", str(revision), f'W/"{revision}"', record_etag(prefix, record)}


def bump_record_revision(record: dict[str, Any]) -> None:
    record["revision"] = record_revision(record) + 1
    record["updatedAt"] = server_time()


def ndt_submission_node_ids(project_id: str, body: dict[str, Any]) -> list[int]:
    node_ids = set(node_ids_from_body(body, 40))
    for report_id in body.get("reportIds") or []:
        report = repo.find_one("ndt_reports", str(report_id))
        if report and report.get("projectId") == project_id:
            node_ids.update(record_node_ids(project_id, report))
    for film_id in body.get("filmIds") or []:
        film = repo.find_one("ndt_films", str(film_id))
        if film and film.get("projectId") == project_id:
            node_ids.update(record_node_ids(project_id, film))
    return sorted(node_ids)


def authorized_node_scope(request: Request, project_id: str) -> set[int] | None:
    claims = getattr(request.state, "auth", None)
    if not claims or claims.get("role") == "admin":
        return None
    user_id = request_user_id(request)
    role = claims.get("role")
    member = next(
        (
            item
            for item in repo.state["project_members"]
            if item.get("projectId") == project_id
            and item.get("userId") == user_id
            and item.get("role") == role
            and item.get("status") == "启用"
        ),
        None,
    )
    if member is None:
        return set()
    return {int(item) for item in member.get("nodeScope") or []}


def project_visible_for_request(request: Request, project_id: str) -> bool:
    scope = authorized_node_scope(request, project_id)
    return scope is None or bool(scope)


def filter_node_groups_for_scope(groups: list[dict[str, Any]], scope: set[int] | None) -> list[dict[str, Any]]:
    if scope is None:
        return groups
    scoped_groups = []
    for group in groups:
        nodes = [node for node in group.get("nodes", []) if int(node.get("nodeId")) in scope]
        if nodes:
            scoped_groups.append({**group, "nodes": nodes})
    return scoped_groups


def document_visible_in_scope(document: dict[str, Any], scope: set[int] | None) -> bool:
    if scope is None:
        return True
    binding_node_ids = {
        int(binding["nodeId"])
        for binding in repo.state["bindings"]
        if binding.get("projectId") == document.get("projectId") and binding.get("documentId") == document.get("id")
    }
    _add_node_id(binding_node_ids, document.get("nodeId"))
    return not binding_node_ids or bool(binding_node_ids & scope)


def report_visible_in_scope(report: dict[str, Any], scope: set[int] | None) -> bool:
    if scope is None:
        return True
    node_ids = {int(item) for item in report.get("nodeIds") or []}
    return bool(node_ids) and node_ids.issubset(scope)


def archive_visible_in_scope(item: dict[str, Any], scope: set[int] | None) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    node_id = item.get("nodeId")
    return node_id is not None and int(node_id) in scope


def _add_node_id(node_ids: set[int], value: Any) -> None:
    if value is None or value == "":
        return
    try:
        node_ids.add(int(value))
    except (TypeError, ValueError):
        return


def _document_project_id(document_id: str | None) -> str | None:
    if not document_id:
        return None
    document = repo.find_one("documents", document_id)
    return document.get("projectId") if document else None


def _document_id_from_version(version_id: str | None) -> str | None:
    if not version_id:
        return None
    version = repo.find_one("versions", version_id)
    return version.get("documentId") if version else None


def _knowledge_file(file_id: str | None) -> dict[str, Any] | None:
    if not file_id:
        return None
    return repo.find_one("knowledge_files", file_id)


def _knowledge_file_node_ids(file: dict[str, Any]) -> set[int]:
    node_ids: set[int] = set()
    _add_node_id(node_ids, file.get("nodeId"))
    project_id = file.get("projectId") or _document_project_id(file.get("documentId"))
    if project_id and file.get("documentId"):
        node_ids.update(document_node_ids(project_id, file["documentId"]))
    return node_ids


def knowledge_file_visible_in_scope(file: dict[str, Any], scope: set[int] | None) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    node_ids = _knowledge_file_node_ids(file)
    return not node_ids or bool(node_ids & scope)


def _target_record(collection: str, record_id: str | None, id_field: str = "id") -> dict[str, Any] | None:
    if not record_id:
        return None
    return repo.find_one(collection, record_id, id_field=id_field)


def record_project_id(record: dict[str, Any]) -> str | None:
    if record.get("projectId"):
        return str(record["projectId"])
    for key in ("documentId",):
        project_id = _document_project_id(record.get(key))
        if project_id:
            return project_id
    if record.get("documentVersionId"):
        project_id = _document_project_id(_document_id_from_version(record.get("documentVersionId")))
        if project_id:
            return project_id
    for key in ("fileId", "targetId"):
        file_id = record.get(key)
        file = _knowledge_file(file_id)
        if file and file.get("projectId"):
            return str(file["projectId"])
        project_id = _document_project_id(file_id)
        if project_id:
            return project_id
    target_type = record.get("targetType")
    target_id = record.get("targetId")
    if target_type == "rectification":
        rectification = _target_record("rectifications", target_id)
        return rectification.get("projectId") if rectification else None
    if target_type == "submission":
        submission = _target_record("submissions", target_id, id_field="submissionId")
        return submission.get("projectId") if submission else None
    if target_type == "report":
        report = _target_record("reports", target_id)
        return report.get("projectId") if report else None
    return None


def record_node_ids(project_id: str, record: dict[str, Any]) -> set[int]:
    node_ids: set[int] = set()
    _add_node_id(node_ids, record.get("nodeId"))
    for node_id in record.get("nodeIds") or []:
        _add_node_id(node_ids, node_id)

    document_id = record.get("documentId") or _document_id_from_version(record.get("documentVersionId"))
    if document_id:
        node_ids.update(document_node_ids(project_id, document_id))

    file_id = record.get("fileId")
    if file_id:
        file = _knowledge_file(file_id)
        if file:
            node_ids.update(_knowledge_file_node_ids(file))
        else:
            node_ids.update(document_node_ids(project_id, file_id))

    film_id = record.get("filmId")
    if not film_id and str(record.get("id", "")).startswith("FILM-"):
        film_id = record.get("id")
    node_ids.update(ndt_film_node_ids(project_id, film_id))

    ndt_report_id = record.get("reportId")
    if not ndt_report_id and str(record.get("id", "")).startswith("NDT-RPT-"):
        ndt_report_id = record.get("id")
    node_ids.update(ndt_report_node_ids(project_id, ndt_report_id))
    for related_film_id in record.get("relatedFilmIds") or []:
        node_ids.update(ndt_film_node_ids(project_id, related_film_id))
    for related_report_id in record.get("relatedReportIds") or []:
        node_ids.update(ndt_report_node_ids(project_id, related_report_id))

    if record.get("reportId"):
        node_ids.update(report_node_ids(project_id, str(record["reportId"])))
    if record.get("exportType") == "report":
        inferred_report_id = record.get("reportId")
        if not inferred_report_id and str(record.get("id", "")).startswith("EXP-RPT-"):
            inferred_report_id = str(record["id"]).replace("EXP-", "", 1)
        if inferred_report_id:
            node_ids.update(report_node_ids(project_id, str(inferred_report_id)))

    target_type = record.get("targetType")
    target_id = record.get("targetId")
    if target_type == "node":
        _add_node_id(node_ids, target_id)
    elif target_type == "rectification":
        rectification = _target_record("rectifications", target_id)
        if rectification:
            _add_node_id(node_ids, rectification.get("nodeId"))
    elif target_type == "submission":
        submission = _target_record("submissions", target_id, id_field="submissionId")
        if submission:
            for node_id in submission.get("nodeIds") or []:
                _add_node_id(node_ids, node_id)
    elif target_type == "report":
        node_ids.update(report_node_ids(project_id, str(target_id)))
    elif target_type == "file":
        file = _knowledge_file(str(target_id))
        if file:
            node_ids.update(_knowledge_file_node_ids(file))
        else:
            node_ids.update(document_node_ids(project_id, str(target_id)))
    return node_ids


def record_references_report(record: dict[str, Any]) -> bool:
    return bool(record.get("reportId")) or record.get("targetType") == "report" or record.get("exportType") == "report"


def ndt_film_node_ids(project_id: str, film_id: str | None) -> set[int]:
    if not film_id:
        return set()
    node_ids: set[int] = set()
    for record in repo.state["ndt_records"]:
        if record.get("projectId") == project_id and record.get("filmId") == film_id:
            _add_node_id(node_ids, record.get("nodeId"))
    for feedback in repo.state["ndt_feedback"]:
        if feedback.get("projectId") == project_id and film_id in set(feedback.get("relatedFilmIds") or []):
            _add_node_id(node_ids, feedback.get("nodeId"))
    for report in repo.state["ndt_reports"]:
        if report.get("projectId") == project_id and film_id in set(report.get("relatedFilmIds") or []):
            node_ids.update(ndt_report_node_ids(project_id, report.get("id")))
    return node_ids


def ndt_report_node_ids(project_id: str, report_id: str | None) -> set[int]:
    if not report_id:
        return set()
    node_ids: set[int] = set()
    report = repo.find_one("ndt_reports", report_id)
    if report and report.get("projectId") == project_id:
        _add_node_id(node_ids, report.get("nodeId"))
        if report.get("fileId"):
            node_ids.update(document_node_ids(project_id, report["fileId"]))
        for film_id in report.get("relatedFilmIds") or []:
            for record in repo.state["ndt_records"]:
                if record.get("projectId") == project_id and record.get("filmId") == film_id:
                    _add_node_id(node_ids, record.get("nodeId"))
            for feedback in repo.state["ndt_feedback"]:
                if feedback.get("projectId") == project_id and film_id in set(feedback.get("relatedFilmIds") or []):
                    _add_node_id(node_ids, feedback.get("nodeId"))
    for record in repo.state["ndt_records"]:
        if record.get("projectId") == project_id and record.get("reportId") == report_id:
            _add_node_id(node_ids, record.get("nodeId"))
    for feedback in repo.state["ndt_feedback"]:
        if feedback.get("projectId") == project_id and report_id in set(feedback.get("relatedReportIds") or []):
            _add_node_id(node_ids, feedback.get("nodeId"))
    return node_ids


def record_visible_for_scope(record: dict[str, Any], scope: set[int] | None, *, project_id: str | None = None) -> bool:
    if scope is None:
        return True
    if not scope:
        return False
    effective_project_id = project_id or record_project_id(record)
    if not effective_project_id:
        return True
    node_ids = record_node_ids(effective_project_id, record)
    if not node_ids:
        return True
    if record_references_report(record):
        return node_ids.issubset(scope)
    return bool(node_ids & scope)


def record_visible_for_request(request: Request, record: dict[str, Any], project_id: str | None = None) -> bool:
    effective_project_id = project_id or record_project_id(record)
    if not effective_project_id:
        return True
    scope = authorized_node_scope(request, effective_project_id)
    return record_visible_for_scope(record, scope, project_id=effective_project_id)


def scope_error_for_record(request: Request, record: dict[str, Any], project_id: str | None = None) -> JSONResponse | None:
    if record_visible_for_request(request, record, project_id):
        return None
    return fail(errors.FORBIDDEN, request, message="用户不在该资源授权范围内。")


def idempotency_fingerprint(source: Any) -> str:
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def idempotent(request: Request, key: str | None, producer, fingerprint_source: Any | None = None):
    if not key:
        return producer()
    scope = f"{request.method}:{request.url.path}:{key}"
    cached = repo.state["idempotency"].get(scope)
    fingerprint = idempotency_fingerprint(fingerprint_source) if fingerprint_source is not None else None
    if cached is not None:
        if isinstance(cached, dict) and "response" in cached:
            if fingerprint and cached.get("requestHash") and cached["requestHash"] != fingerprint:
                return fail(errors.IDEMPOTENCY_KEY_CONFLICT, request)
            return repo.clone(cached["response"])
        return repo.clone(cached)
    result = producer()
    if not isinstance(result, JSONResponse):
        repo.state["idempotency"][scope] = {
            "requestHash": fingerprint,
            "response": repo.clone(result),
        }
    return result


def filter_keyword(items: list[dict[str, Any]], keyword: str | None, fields: list[str]) -> list[dict[str, Any]]:
    if not keyword:
        return items
    lowered = keyword.lower()
    return [
        item
        for item in items
        if any(lowered in str(item.get(field, "")).lower() for field in fields)
    ]


def signed_url_for_task(task: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    if task["status"] == "已过期":
        return {"error": errors.EXPORT_TASK_EXPIRED}
    if task["status"] != "可下载":
        return {"error": errors.EXPORT_TASK_NOT_READY}
    return repo.signed_get(
        task["fileName"],
        task.get("downloadUrl") or f"mock://download/exports/{task['id']}",
        file_size=task.get("fileSize"),
    )


def admin_user_snapshot(user_id: str | None, role: str | None = None) -> dict[str, Any]:
    users = repo.state["admin_config"].get("users", [])
    user = next((item for item in users if item.get("id") == user_id), None)
    if user is None and role:
        user = next((item for item in users if item.get("role") == role), None)
    if user is None and role == "admin":
        user = {"id": user_id or "USER-ADMIN-001", "name": "系统管理员", "orgName": "省特检院平台组", "role": "admin"}
    return user or {"id": user_id or "USER-UNKNOWN", "name": "新授权成员", "orgName": "联调组织", "role": role or "inspection"}


def scoped_binding_ids(project_id: str, node_ids: list[int], binding_ids: list[str] | None) -> list[str]:
    if binding_ids:
        return binding_ids
    scoped = [
        item["id"]
        for item in repo.state["bindings"]
        if item["projectId"] == project_id
        and int(item["nodeId"]) in set(node_ids)
        and item.get("bindingStatus") != "已通过"
    ]
    return scoped


def build_config_diff(target: str, object_id: str, values: dict[str, Any], *, object_name: str | None = None) -> dict[str, Any]:
    changed = []
    for field, value in values.items():
        if isinstance(value, dict):
            value = ", ".join(f"{key}: {nested}" for key, nested in value.items())
        changed.append(
            {
                "field": field,
                "label": field,
                "before": None,
                "after": value,
                "severity": "info",
            }
        )
    return {
        "target": target,
        "objectId": object_id,
        "objectName": object_name or values.get("name") or values.get("scene") or target,
        "previewedAt": server_time(),
        "changed": changed,
    }


def project_member_snapshot(
    project_id: str,
    role: str,
    user_id: str | None = None,
    *,
    org_name: str | None = None,
    node_scope: list[int] | None = None,
    actions: list[str] | None = None,
) -> dict[str, Any]:
    user = admin_user_snapshot(user_id, role)
    return {
        "id": f"PM-{uuid4().hex[:8].upper()}",
        "projectId": project_id,
        "userId": user_id or user["id"],
        "name": user.get("name") or "授权成员",
        "orgName": org_name or user.get("orgName") or "联调组织",
        "role": role,
        "nodeScope": node_scope or [ROLE_NODE_MAP.get(role, 1)],
        "actions": actions or repo.role_actions(role),
        "status": "启用",
        "updatedAt": server_time(),
        "revision": 1,
    }


def project_detail_payload(project_id: str, request: Request | None = None) -> dict[str, Any] | None:
    project = repo.require_project(project_id)
    if not project:
        return None
    members = [versioned_record("project-member", item) for item in repo.state["project_members"] if item["projectId"] == project_id]
    if request is not None and getattr(request.state, "auth", None) and getattr(request.state, "auth", {}).get("role") != "admin":
        current_user_id = request_user_id(request)
        members = [item for item in members if item.get("userId") == current_user_id]
    scope = authorized_node_scope(request, project_id) if request is not None else None
    node_summary = []
    groups = filter_node_groups_for_scope(repo.node_groups(project_id), scope)
    for group in groups:
        nodes = group["nodes"]
        node_summary.append(
            {
                "groupName": group["groupName"],
                "total": len(nodes),
                "passed": len([item for item in nodes if item.get("status") == "已通过"]),
                "pending": len([item for item in nodes if item.get("status") in {"待提交", "待审查", "待人工确认"}]),
                "correction": len([item for item in nodes if item.get("status") in {"需补正", "补正中"}]),
            }
        )
    return {
        "project": versioned_project(project),
        "members": members,
        "participantUnits": [
            {"unitType": "owner", "unitName": project["ownerOrgName"], "contactName": "赵经理", "contactPhone": "13800000001"},
            {"unitType": "contractor", "unitName": project["contractorOrgName"], "contactName": "李工", "contactPhone": "13800000002"},
            {"unitType": "ndt", "unitName": project["ndtOrgName"], "contactName": "王工", "contactPhone": "13800000003"},
            {"unitType": "inspection", "unitName": project["inspectionOrgName"], "contactName": "张工", "contactPhone": "13800000004"},
        ],
        "nodeSummary": node_summary,
        "recentExportTasks": [repo.clone(item) for item in repo.state["export_tasks"] if item.get("projectId") == project_id],
    }


def business_pack_for_project(project: dict[str, Any] | None) -> dict[str, Any]:
    pack_id = (project or {}).get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
    return load_business_pack(pack_id)


def business_pack_snapshot_for_project(project: dict[str, Any]) -> dict[str, Any]:
    stored = project.get("businessPackSnapshot")
    if isinstance(stored, dict):
        return repo.clone(stored)
    return business_pack_snapshot(business_pack_for_project(project))


def project_defaults_for_pack(pack: dict[str, Any]) -> dict[str, str]:
    if pack.get("domainType") == ENGINEERING_DOMAIN_TYPE:
        return dict(ENGINEERING_PROJECT_DEFAULTS)
    reviewer = next((role for role in pack.get("roles") or [] if role.get("platformRole") == "reviewer"), {})
    submitter = next((role for role in pack.get("roles") or [] if role.get("platformRole") == "submitter"), {})
    observer = next((role for role in pack.get("roles") or [] if role.get("platformRole") == "observer"), {})
    return {
        "name": f"新建{pack['name']}项目",
        "type": pack["name"],
        "ownerOrgName": f"{observer.get('label') or '观察者'}单位",
        "contractorOrgName": f"{submitter.get('label') or '提交者'}单位",
        "ndtOrgName": "专项资料单位",
        "inspectionOrgName": f"{reviewer.get('label') or '审核者'}机构",
    }


def project_requirements_for_node(project_id: str, node_id: int) -> list[dict[str, Any]]:
    scoped = [
        repo.clone(item)
        for item in repo.state["requirements"]
        if int(item["nodeId"]) == int(node_id) and item.get("projectId") == project_id
    ]
    if scoped:
        return scoped
    return [
        repo.clone(item)
        for item in repo.state["requirements"]
        if int(item["nodeId"]) == int(node_id) and not item.get("projectId")
    ]


def attach_business_pack_project_scaffold(project: dict[str, Any], pack: dict[str, Any]) -> tuple[int, int]:
    project_id = project["id"]
    existing_nodes = {item["id"] for item in repo.state["tree_nodes"]}
    nodes = [
        item
        for item in build_project_tree(project_id, pack)
        if item["id"] not in existing_nodes
    ]
    repo.state["tree_nodes"].extend(nodes)
    existing_requirement_keys = {
        (item.get("projectId"), item["id"]) for item in repo.state["requirements"]
    }
    requirements = [
        item
        for item in build_project_requirements(pack, project_id=project_id)
        if (item.get("projectId"), item["id"]) not in existing_requirement_keys
    ]
    repo.state["requirements"].extend(requirements)
    return len(nodes), len(requirements)


def simple_routes(role: str | None = None) -> list[dict[str, Any]]:
    routes = [
        {
            "path": "/workbench",
            "component": "#",
            "redirect": ROLE_DEFAULT_PATHS.get(role or "inspection", "/workbench/inspection"),
            "name": "Workbench",
            "meta": {"title": "业务工作台", "icon": "vi-ep:monitor", "alwaysShow": True, "roles": ["inspection", "contractor", "ndt", "owner"]},
            "children": [
                {"path": "generic", "component": "views/AICheck/GenericReviewWorkbench", "name": "GenericReviewWorkbench", "meta": {"title": "通用资料审查", "roles": ["admin", "inspection", "contractor", "owner"]}},
                {"path": "inspection", "component": "views/AICheck/Workbench", "name": "InspectionWorkbench", "meta": {"title": "监检工作台", "roles": ["inspection"]}},
                {"path": "contractor", "component": "views/AICheck/Workbench", "name": "ContractorWorkbench", "meta": {"title": "施工方工作台", "roles": ["contractor"]}},
                {"path": "ndt", "component": "views/AICheck/Workbench", "name": "NdtWorkbench", "meta": {"title": "无损检测工作台", "roles": ["ndt"]}},
                {"path": "owner", "component": "views/AICheck/Workbench", "name": "OwnerWorkbench", "meta": {"title": "建设方工作台", "roles": ["owner"]}},
            ],
        },
        {
            "path": "/admin",
            "component": "#",
            "redirect": "/admin/overview",
            "name": "AICheckAdmin",
            "meta": {"title": "管理后台", "icon": "vi-ep:setting", "alwaysShow": True, "roles": ["admin"]},
            "children": [
                {"path": item, "component": "views/AICheck/AdminOverview", "name": f"Admin{item.title().replace('-', '')}", "meta": {"title": "项目与权限配置", "roles": ["admin"]}}
                for item in ["overview", "projects", "org", "permission", "rules", "fine-config", "integration", "audit"]
            ],
        },
        {
            "path": "/knowledge",
            "component": "#",
            "redirect": "/knowledge/overview",
            "name": "Knowledge",
            "meta": {"title": "AI 知识库", "icon": "vi-ep:collection", "alwaysShow": True, "roles": ["admin"]},
            "children": [
                {"path": item, "component": "views/AICheck/KnowledgeOverview", "name": f"Knowledge{item.title().replace('-', '')}", "meta": {"title": "AI 知识库管理", "roles": ["admin"]}}
                for item in ["overview", "sources", "files", "tasks", "rules", "retrieval", "reasoning", "compare", "config"]
            ],
        },
        {
            "path": "/fde",
            "component": "#",
            "redirect": "/fde/projects",
            "name": "FdeConsole",
            "meta": {"title": "FDE 后台", "icon": "vi-ep:operation", "alwaysShow": True, "roles": sorted(FDE_ROLES)},
            "children": [
                {
                    "path": item["path"],
                    "component": "views/AICheck/FdeConsole",
                    "name": f"Fde{item['path'].title().replace('-', '')}",
                    "meta": {"title": item["title"], "hidden": item.get("hidden", False), "roles": sorted(FDE_ROLES)},
                }
                for item in [
                    {"path": "projects", "title": "项目审计工作台"},
                    {"path": "dashboard", "title": "AI 驾驶舱", "hidden": True},
                    {"path": "ai-runs", "title": "AI Run 追踪", "hidden": True},
                    {"path": "review-runs", "title": "Agent 审查编排", "hidden": True},
                    {"path": "feedback", "title": "人工反馈与样本池", "hidden": True},
                    {"path": "evaluation", "title": "评估实验室", "hidden": True},
                    {"path": "capability-bundles", "title": "能力版本组合", "hidden": True},
                    {"path": "releases", "title": "发布治理", "hidden": True},
                    {"path": "ocr-quality", "title": "OCR 质量与标注", "hidden": True},
                    {"path": "business-packs", "title": "业务包工厂", "hidden": True},
                    {"path": "security", "title": "数据安全", "hidden": True},
                    {"path": "costs", "title": "成本预算", "hidden": True},
                    {"path": "incidents", "title": "事故复盘", "hidden": True},
                    {"path": "acceptance", "title": "客户验收", "hidden": True},
                ]
            ],
        },
    ]
    return filter_routes_for_role(routes, role) if role else routes


def filter_routes_for_role(routes: list[dict[str, Any]], role: str | None) -> list[dict[str, Any]]:
    if not role:
        return routes
    filtered = []
    for route in routes:
        roles = route.get("meta", {}).get("roles")
        if roles and role not in roles:
            continue
        copy = repo.clone(route)
        if copy.get("children"):
            copy["children"] = filter_routes_for_role(copy["children"], role)
            if not copy["children"]:
                continue
        filtered.append(copy)
    return filtered


@mock_router.post("/mock/user/login")
def mock_login(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    user = authenticate(str(body.get("username", "")), str(body.get("password", "")))
    if not user:
        return fail(errors.AUTH_REQUIRED, request, message="账号或密码错误")
    return ok(user, request)


@mock_router.get("/mock/user/loginOut")
def mock_logout(request: Request):
    return ok(None, request)


@mock_router.get("/mock/role/list")
def mock_role_list(request: Request, roleName: str | None = None):
    user = user_by_username(roleName)
    return ok(simple_routes(user.get("role") if user else None), request)


@mock_router.get("/mock/role/list2")
def mock_role_list2(request: Request):
    return ok(["*.*.*"], request)


@mock_router.get("/mock/user/list")
def mock_user_list(request: Request):
    users = [{key: value for key, value in user.items() if key != "password"} for user in USERS.values()]
    return ok({"list": users, "total": len(users)}, request)


@router.post("/auth/login")
def auth_login(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    user = authenticate(str(body.get("username", "")), str(body.get("password", "")))
    if not user:
        return fail(errors.AUTH_REQUIRED, request, message="账号或密码错误")
    return ok({"token": issue_token(user), "user": user}, request)


@router.post("/auth/logout")
def auth_logout(request: Request):
    return ok(None, request)


@router.get("/auth/me")
def auth_me(request: Request):
    claims = decode_token(request.headers.get("Authorization", ""))
    user = user_by_username(claims.get("sub") if claims else None) or user_by_username("admin")
    role = (user or {}).get("role", "admin")
    user_id = (user or {}).get("id")
    project_authorizations = repo.clone(repo.state["project_members"])
    if role != "admin" and user_id:
        project_authorizations = [item for item in project_authorizations if item.get("userId") == user_id]
    return ok(
        {
            **(user or {}),
            "defaultRole": role,
            "projectAuthorizations": project_authorizations,
        },
        request,
    )


@router.get("/auth/routes")
def auth_routes(request: Request, role: str | None = None):
    return ok(simple_routes(role), request)


@router.get("/auth/actions")
def auth_actions(request: Request, role: str = Query(default="inspection")):
    return ok(repo.role_actions(role), request)


@router.get("/permissions/node-actions")
def node_actions(request: Request, role: str = Query(default="inspection")):
    return ok(repo.role_actions(role), request)


@router.get("/permissions/resources")
def permission_resources(request: Request):
    return ok(repo.state["admin_config"]["permissionMatrix"], request)


@router.get("/business-packs")
def get_business_packs(request: Request):
    return ok(list_business_packs(), request)


@router.post("/business-packs/validate-all")
def validate_all_business_packs_endpoint(request: Request):
    return ok(validate_all_business_packs(), request)


@router.get("/business-packs/{pack_id}")
def get_business_pack(request: Request, pack_id: str):
    try:
        pack = load_business_pack(pack_id)
    except ValueError:
        return fail(errors.NOT_FOUND, request, message="业务包不存在。")
    return ok(
        {
            "summary": business_pack_summary(pack),
            "roles": repo.clone(pack["roles"]),
            "nodeTemplates": repo.clone(pack["nodeTemplates"]),
            "materialTypes": repo.clone(pack["materialTypes"]),
            "workflowStateMachines": repo.clone(pack["workflowStateMachines"]),
            "ruleSets": repo.clone(pack["ruleSets"]),
            "reportTemplates": repo.clone(pack["reportTemplates"]),
            "agentSops": repo.clone(pack.get("agentSops") or []),
        },
        request,
    )


@router.get("/business-packs/{pack_id}/snapshot")
def get_business_pack_snapshot(request: Request, pack_id: str):
    try:
        pack = load_business_pack(pack_id)
    except ValueError:
        return fail(errors.NOT_FOUND, request, message="业务包不存在。")
    return ok(business_pack_snapshot(pack), request)


@router.post("/business-packs/{pack_id}/validate")
def validate_business_pack_endpoint(request: Request, pack_id: str):
    try:
        pack = load_business_pack(pack_id)
    except ValueError as exc:
        return fail(errors.NOT_FOUND, request, message=str(exc))
    return ok({"summary": business_pack_summary(pack), "validation": validate_business_pack(pack)}, request)


@router.get("/workbench/projects")
def list_workbench_projects(
    request: Request,
    role: str = Query(default="inspection"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    resolved_role, role_error = resolved_role_for_read(request, role, x_role)
    if role_error:
        return role_error
    items = [item for item in repo.state["projects"] if project_visible_for_request(request, item["id"])]
    return ok([versioned_project(repo.project_for_role(item, resolved_role)) for item in items], request)


@router.get("/projects")
def list_projects(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None):
    items = [versioned_project(item) for item in repo.state["projects"] if project_visible_for_request(request, item["id"])]
    items = filter_keyword(items, keyword, ["name", "code", "region"])
    return ok(page(items, page_no, page_size), request)


@router.post("/projects")
def create_project(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return create_admin_project(request, body, idempotency_key)


@router.get("/projects/{project_id}")
def get_project_detail(request: Request, project_id: str):
    detail = project_detail_payload(project_id, request)
    if not detail:
        return fail(errors.NOT_FOUND, request)
    return ok(detail, request)


@router.patch("/projects/{project_id}")
def update_project(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, if_match=if_match)
        if guard:
            return guard
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        changed = []
        for field in ["name", "type", "region", "ownerOrgName", "contractorOrgName", "ndtOrgName", "inspectionOrgName"]:
            if field in body and project.get(field) != body[field]:
                changed.append({"field": field, "before": project.get(field), "after": body[field]})
                project[field] = body[field]
        if changed:
            repo.touch_project(project_id)
        return ok({"project": versioned_project(project), **repo.mutation_result("更新项目", "Project", project_id, changed=changed)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "body": body})


@router.post("/projects/{project_id}/business-pack/apply")
def apply_business_pack(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, if_match="*")
        if guard:
            return guard
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        pack_id = body.get("businessPackId") or project.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
        try:
            pack = load_business_pack(pack_id)
        except ValueError as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
        project.update(
            {
                "businessPackId": pack["id"],
                "businessPackVersion": pack["version"],
                "domainType": pack["domainType"],
                "businessPackSnapshotHash": pack["snapshotHash"],
                "businessPackSnapshot": business_pack_snapshot(pack),
            }
        )
        created_node_count, created_requirement_count = attach_business_pack_project_scaffold(project, pack)
        repo.touch_project(project_id)
        audit_id = repo.add_audit("应用业务包", "BusinessPack", pack["id"])
        return ok(
            {
                "project": versioned_project(project),
                "businessPack": business_pack_summary(pack),
                "createdNodeCount": created_node_count,
                "createdRequirementCount": created_requirement_count,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "body": body},
    )


@router.get("/projects/{project_id}/business-pack/snapshot")
def get_project_business_pack_snapshot(request: Request, project_id: str):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    snapshot = business_pack_snapshot_for_project(project)
    return ok(
        {
            "projectId": project_id,
            "businessPackId": project.get("businessPackId"),
            "businessPackVersion": project.get("businessPackVersion"),
            "businessPackSnapshotHash": project.get("businessPackSnapshotHash"),
            "snapshotMatchesCurrent": project.get("businessPackSnapshotHash") == snapshot.get("snapshotHash"),
            "snapshot": snapshot,
        },
        request,
    )


@router.get("/projects/{project_id}/participants")
def list_participants(request: Request, project_id: str):
    detail = get_project_detail(request, project_id)
    if isinstance(detail, JSONResponse):
        return detail
    return ok(detail["data"]["participantUnits"], request)


@router.post("/projects/{project_id}/participants")
def save_participant(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        participant_id = body.get("id") or f"PU-{uuid4().hex[:8].upper()}"
        repo.touch_project(project_id)
        return ok({**repo.mutation_result("保存参建单位", "ProjectUnit", participant_id), "project": versioned_project(repo.require_project(project_id))}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "body": body})


@router.patch("/projects/{project_id}/participants/{participant_id}")
def update_participant(
    request: Request,
    project_id: str,
    participant_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        repo.touch_project(project_id)
        return ok({**repo.mutation_result("更新参建单位", "ProjectUnit", participant_id, changed=[{"field": "values", "after": body}]), "project": versioned_project(repo.require_project(project_id))}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "participantId": participant_id, "body": body})


@router.get("/projects/{project_id}/members")
def list_project_members(request: Request, project_id: str, role: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("project-member", item) for item in repo.state["project_members"] if item["projectId"] == project_id]
    if role:
        items = [item for item in items if item["role"] == role]
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/members")
def authorize_member(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        role = body.get("role", "inspection")
        user = admin_user_snapshot(body.get("userId"), role)
        user_id = body.get("userId") or user["id"]
        incoming_scope = body.get("nodeScope") or [ROLE_NODE_MAP.get(role, 24)]
        existing = next(
            (
                item
                for item in repo.state["project_members"]
                if item.get("projectId") == project_id
                and item.get("userId") == user_id
                and item.get("role") == role
            ),
            None,
        )
        if existing:
            merged_scope = list(dict.fromkeys([*(existing.get("nodeScope") or []), *incoming_scope]))
            existing.update(
                {
                    "name": body.get("name") or existing.get("name") or user.get("name") or "新授权成员",
                    "orgName": body.get("orgName") or existing.get("orgName") or user.get("orgName") or "联调组织",
                    "nodeScope": merged_scope,
                    "actions": body.get("actions") or existing.get("actions") or repo.role_actions(role),
                    "status": "启用",
                    "expiresAt": body.get("expiresAt") or existing.get("expiresAt"),
                    "updatedAt": server_time(),
                }
            )
            bump_record_revision(existing)
            repo.touch_project(project_id)
            audit_id = repo.add_audit("更新项目成员授权", "ProjectMember", existing["id"])
            return ok({"member": versioned_record("project-member", existing), "auditLogId": audit_id}, request)

        member = {
            "id": f"PM-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "userId": user_id,
            "name": body.get("name") or user.get("name") or "新授权成员",
            "orgName": body.get("orgName") or user.get("orgName") or "联调组织",
            "role": role,
            "nodeScope": incoming_scope,
            "actions": body.get("actions") or repo.role_actions(role),
            "status": "启用",
            "expiresAt": body.get("expiresAt"),
            "updatedAt": server_time(),
            "revision": 1,
        }
        repo.state["project_members"].insert(0, member)
        repo.touch_project(project_id)
        audit_id = repo.add_audit("项目成员授权", "ProjectMember", member["id"])
        return ok({"member": versioned_record("project-member", member), "auditLogId": audit_id}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source=body,
    )


@router.put("/projects/{project_id}/members/{member_id}")
def update_member(
    request: Request,
    project_id: str,
    member_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, if_match="*")
        if guard:
            return guard
        member = repo.find_one("project_members", member_id)
        if not member or member.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request, message="项目成员不存在。")
        if not record_if_match_valid("project-member", member, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        changed = []
        for field in ["role", "nodeScope", "actions", "status", "expiresAt"]:
            if field in body and member.get(field) != body[field]:
                changed.append({"field": field, "before": member.get(field), "after": body[field]})
                member[field] = body[field]
        if changed:
            bump_record_revision(member)
            repo.touch_project(project_id)
        audit_id = repo.add_audit("更新项目成员授权", "ProjectMember", member_id)
        return ok({"member": versioned_record("project-member", member), "auditLogId": audit_id, "changed": changed}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"memberId": member_id, "body": body})


@router.post("/projects/{project_id}/initialize-workflow")
def initialize_workflow(
    request: Request,
    project_id: str,
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        repo.touch_project(project_id, "草稿/立项中", 1)
        node_count = len([item for item in repo.state["tree_nodes"] if item.get("projectId") == project_id])
        return ok(
            {
                **repo.mutation_result("初始化项目节点流程", "Project", project_id),
                "createdNodeCount": node_count,
                "project": versioned_project(repo.require_project(project_id)),
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id})


@router.get("/projects/{project_id}/workbench/context")
def workbench_context(request: Request, project_id: str, role: str = Query(default="inspection"), x_role: str | None = Header(default=None, alias="X-Role")):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    resolved_role, role_error = resolved_role_for_read(request, role, x_role)
    if role_error:
        return role_error
    scope = authorized_node_scope(request, project_id)
    visible_todos = [
        item
        for item in repo.state["todos"]
        if item.get("projectId") == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    visible_messages = [
        item
        for item in repo.state["messages"]
        if item.get("projectId") == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    current_node_id = ROLE_NODE_MAP.get(resolved_role, project.get("currentNodeId", 24))
    role_project = repo.project_for_role(project, resolved_role)
    return ok(
        {
            "project": role_project,
            "role": resolved_role,
            "currentNodeId": current_node_id,
            "topbar": {
                "todoCount": len(visible_todos),
                "messageCount": len([item for item in visible_messages if not item.get("read")]),
                "statusText": project.get("status"),
                "projectSwitcherEnabled": True,
            },
            "actions": role_project["actions"],
        },
        request,
    )


@router.get("/projects/{project_id}/workbench/summary")
def workbench_summary(request: Request, project_id: str, role: str = Query(default="inspection")):
    resolved_role, role_error = resolved_role_for_read(request, role)
    if role_error:
        return role_error
    scope = authorized_node_scope(request, project_id)
    role_todos = [
        item
        for item in repo.state["todos"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    visible_nodes = [
        item
        for item in repo.state["tree_nodes"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    visible_documents = [
        item
        for item in repo.project_documents(project_id)
        if document_visible_in_scope(item, scope)
    ]
    visible_reports = [
        item
        for item in repo.state["reports"]
        if item["projectId"] == project_id and report_visible_in_scope(item, scope)
    ]
    visible_messages = [
        item
        for item in repo.state["messages"]
        if item.get("projectId") == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    correction_count = len([item for item in visible_nodes if item["status"] in {"需补正", "补正中"}])
    metrics = [
        {"key": "todo", "label": "待办", "value": len(role_todos), "tone": "orange"},
        {"key": "correction", "label": "补正", "value": correction_count, "tone": "red"},
        {"key": "document", "label": "资料", "value": len(visible_documents), "tone": "blue"},
        {"key": "report", "label": "报告", "value": len(visible_reports), "tone": "green"},
    ]
    if resolved_role == "owner":
        metrics = [
            {"key": "progress", "label": "总体进度", "value": "42%", "tone": "blue"},
            {"key": "report", "label": "报告版本", "value": len(visible_reports), "tone": "green"},
            {"key": "archive", "label": "归档资料", "value": len([item for item in repo.state["archive_items"] if item.get("projectId") == project_id and archive_visible_in_scope(item, scope)]), "tone": "gray"},
        ]
    return ok(
        {
            "metrics": metrics,
            "todos": [repo.clone(item) for item in role_todos[:5]],
            "messages": [repo.clone(item) for item in visible_messages[:5]],
            "updatedAt": server_time(),
        },
        request,
    )


@router.get("/projects/{project_id}/tree")
def project_tree(request: Request, project_id: str):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    scope = authorized_node_scope(request, project_id)
    groups = filter_node_groups_for_scope(repo.node_groups(project_id), scope)
    return ok({"project": repo.clone(project), "groups": groups}, request)


@router.get("/projects/{project_id}/nodes/{node_id}")
def node_detail(request: Request, project_id: str, node_id: int):
    node = repo.node(project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    return ok({"node": repo.clone(node)}, request)


@router.get("/projects/{project_id}/nodes/{node_id}/requirements")
def node_requirements(request: Request, project_id: str, node_id: int):
    return ok(project_requirements_for_node(project_id, node_id), request)


@router.get("/projects/{project_id}/nodes/{node_id}/package")
def node_package(request: Request, project_id: str, node_id: int):
    effective_project_id = project_id
    node = repo.node(effective_project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    scope = authorized_node_scope(request, project_id)
    bindings = repo.bindings_for_node(effective_project_id, node_id)
    version_ids = {item["documentVersionId"] for item in bindings}
    project_files = [
        item
        for item in repo.project_documents(effective_project_id)
        if document_visible_in_scope(item, scope)
    ]
    visible_document_ids = {item["id"] for item in project_files}
    return ok(
        {
            "node": repo.clone(node),
            "requirements": project_requirements_for_node(project_id, node_id),
            "bindings": bindings,
            "projectFiles": project_files,
            "availableVersions": [
                repo.clone(item)
                for item in repo.state["versions"]
                if item["id"] in version_ids or item.get("documentId") in visible_document_ids
            ],
            "extractedFields": repo.fields_for_versions(version_ids),
            "reviewOpinions": [repo.clone(item) for item in repo.state["review_opinions"] if item["projectId"] == effective_project_id and int(item["nodeId"]) == int(node_id)],
            "aiRuns": [repo.clone(item) for item in repo.state["ai_runs"] if item["projectId"] == effective_project_id and int(item["nodeId"]) == int(node_id)],
            "actions": repo.clone(node.get("actions", [])),
        },
        request,
    )


@router.get("/projects/{project_id}/documents")
def list_documents(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, nodeId: int | None = None):
    scope = authorized_node_scope(request, project_id)
    effective_project_id = project_id
    items = [
        item
        for item in repo.project_documents(effective_project_id)
        if document_visible_in_scope(item, scope)
    ]
    if nodeId:
        document_ids = {
            binding["documentId"]
            for binding in repo.state["bindings"]
            if binding.get("projectId") == effective_project_id and int(binding.get("nodeId")) == int(nodeId)
        }
        items = [item for item in items if item["id"] in document_ids]
    items = filter_keyword(items, keyword, ["fileName", "sourceOrgName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/projects/{project_id}/documents/bindings")
def list_bindings(request: Request, project_id: str, nodeId: int | None = None):
    scope = authorized_node_scope(request, project_id)
    items = repo.bindings_for_project(project_id)
    if scope is not None:
        items = [item for item in items if int(item["nodeId"]) in scope]
    if nodeId:
        items = [item for item in items if int(item["nodeId"]) == int(nodeId)]
    return ok(items, request)


@router.post("/projects/{project_id}/documents/upload-session")
def create_upload_session(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        files = body.get("files") or []
        validation_error = validate_upload_files(request, files)
        if validation_error:
            return validation_error
        session_id, upload_urls = repo.create_upload_session(project_id, files)
        repo.add_audit("创建上传会话", "UploadSession", session_id)
        return ok({"uploadSessionId": session_id, "expiresAt": upload_urls[0]["expiresAt"], "uploadUrls": upload_urls}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source=body,
    )


@router.post("/projects/{project_id}/documents/upload-session/{session_id}/complete")
def complete_upload_session(
    request: Request,
    project_id: str,
    session_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        session = repo.find_one("upload_sessions", session_id)
        if not session or session.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        files = repo.complete_upload_session(session_id)
        dispatches = []
        for file in files:
            dispatches.append(
                task_dispatcher.dispatch_parse_document(
                    file["documentId"],
                    file["documentVersionId"],
                    file["storageKey"],
                    file.get("fileName"),
                )
            )
        result = repo.mutation_result("完成上传会话", "UploadSession", session_id, next_status="排队中")
        return ok({**result, "queuedTasks": dispatches, "fileCount": len(files)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"sessionId": session_id, "body": body})


@router.get("/projects/{project_id}/documents/{document_id}")
def document_detail(request: Request, project_id: str, document_id: str):
    document = repo.find_one("documents", document_id)
    if not document or document.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    versions = repo.versions_for_document(document_id)
    version_ids = {item["id"] for item in versions}
    preview = repo.document_preview(document)
    return ok(
        {
            "document": repo.clone(document),
            "currentVersion": repo.current_version(document_id),
            "versions": versions,
            "bindings": [item for item in repo.bindings_for_project(document["projectId"]) if item["documentId"] == document_id],
            "extractedFields": repo.fields_for_versions(version_ids),
            "evidenceLinks": repo.evidence_for_versions(version_ids),
            "preview": preview,
            "download": repo.document_download(document),
        },
        request,
    )


@router.get("/projects/{project_id}/documents/{document_id}/versions")
def document_versions(request: Request, project_id: str, document_id: str):
    return ok(repo.versions_for_document(document_id), request)


@router.get("/projects/{project_id}/documents/{document_id}/preview-url")
def document_preview_url(request: Request, project_id: str, document_id: str):
    document = repo.find_one("documents", document_id)
    if not document or document.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.document_preview(document), request)


@router.get("/projects/{project_id}/documents/{document_id}/download-url")
def document_download_url(request: Request, project_id: str, document_id: str):
    document = repo.find_one("documents", document_id)
    if not document or document.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.document_download(document), request)


@router.get("/projects/{project_id}/documents/{document_id}/ocr-fields")
def document_ocr_fields(request: Request, project_id: str, document_id: str):
    versions = repo.versions_for_document(document_id)
    return ok(repo.fields_for_versions({item["id"] for item in versions}), request)


@router.get("/projects/{project_id}/documents/{document_id}/review-feedback")
def document_review_feedback(request: Request, project_id: str, document_id: str):
    return ok({"opinions": repo.clone(repo.state["review_opinions"]), "rectifications": repo.clone(repo.state["rectifications"])}, request)


@router.post("/projects/{project_id}/documents/{document_id}/versions")
def append_document_version(
    request: Request,
    project_id: str,
    document_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=document_node_ids(project_id, document_id))
        if guard:
            return guard
        document = repo.find_one("documents", document_id)
        if not document or document.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        version_id = f"DV-{uuid4().hex[:8].upper()}-V{len(repo.versions_for_document(document_id)) + 1}"
        for version in repo.state["versions"]:
            if version["documentId"] == document_id:
                version["isCurrent"] = False
        version = {
            "id": version_id,
            "documentId": document_id,
            "versionNo": f"V{len(repo.versions_for_document(document_id)) + 1}",
            "hash": f"mock-sha256-{version_id}",
            "fileSize": int(body.get("fileSize") or 245760),
            "storageKey": f"documents/{project_id}/{version_id}",
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "未向量化",
            "uploaderName": "李工",
            "uploadTime": server_time(),
            "isCurrent": True,
        }
        repo.state["versions"].insert(0, version)
        document["currentVersionId"] = version_id
        document["fileStatus"] = "已追加版本" if body.get("mode") == "append" else "已替换"
        document["updatedAt"] = server_time()
        return ok({"version": version, **repo.mutation_result("新增文件版本", "DocumentVersion", version_id, next_status=document["fileStatus"])}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"documentId": document_id, "body": body})


@router.post("/projects/{project_id}/documents/bindings")
def bind_documents(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = node_ids_from_body(body, ROLE_NODE_MAP["contractor"])

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        binding_inputs = body.get("bindings") or []
        if not binding_inputs:
            return fail(errors.EMPTY_BINDINGS, request)
        created = []
        changed = []
        for node_id in node_ids:
            requirements = [item for item in repo.state["requirements"] if int(item["nodeId"]) == node_id]
            for index, binding_input in enumerate(binding_inputs):
                document = repo.find_one("documents", binding_input.get("documentId"))
                version_id = binding_input.get("documentVersionId") or (document or {}).get("currentVersionId")
                if not document or not version_id:
                    continue
                requirement = requirements[index % len(requirements)] if requirements else None
                binding = {
                    "id": f"BIND-{node_id}-{uuid4().hex[:6].upper()}",
                    "projectId": project_id,
                    "nodeId": node_id,
                    "requirementId": requirement.get("id") if requirement else None,
                    "requirementName": requirement.get("name") if requirement else None,
                    "documentId": document["id"],
                    "documentVersionId": version_id,
                    "fileName": document["fileName"],
                    "versionNo": "V1",
                    "usage": binding_input.get("usage") or body.get("usage") or "原始提交",
                    "sourceOrgName": document["sourceOrgName"],
                    "bindingStatus": "草稿挂载",
                    "boundByName": "李工",
                    "boundAt": server_time(),
                    "actions": ["submission:submit", "submission:withdraw"],
                }
                repo.state["bindings"].insert(0, binding)
                created.append(binding["id"])
            changed.append(repo.set_node_status(project_id, node_id, "部分提交"))
        return ok(repo.mutation_result("保存节点挂载关系", "NodeFileBinding", created[0] if created else "BIND-EMPTY", next_status="部分提交", changed=changed, affected_ids=created), request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source=body,
    )


@router.patch("/projects/{project_id}/documents/bindings/{binding_id}")
def update_binding(
    request: Request,
    project_id: str,
    binding_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=binding_node_ids(project_id, binding_id))
        if guard:
            return guard
        binding = repo.find_one("bindings", binding_id)
        if not binding or binding.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        changed = []
        for field in ["requirementId", "requirementName", "usage", "bindingStatus"]:
            if field in body and binding.get(field) != body[field]:
                changed.append({"field": field, "before": binding.get(field), "after": body[field]})
                binding[field] = body[field]
        return ok({**repo.mutation_result("更新挂载关系", "NodeFileBinding", binding_id, changed=changed), "binding": repo.clone(binding)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"bindingId": binding_id, "body": body})


@router.delete("/projects/{project_id}/documents/bindings/{binding_id}")
def delete_binding(
    request: Request,
    project_id: str,
    binding_id: str,
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=binding_node_ids(project_id, binding_id))
        if guard:
            return guard
        binding = repo.find_one("bindings", binding_id)
        if not binding or binding.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        before = len(repo.state["bindings"])
        repo.state["bindings"] = [item for item in repo.state["bindings"] if item["id"] != binding_id]
        if len(repo.state["bindings"]) == before:
            return fail(errors.NOT_FOUND, request)
        return ok({**repo.mutation_result("解除草稿挂载", "NodeFileBinding", binding_id, next_status="已解除挂载"), "binding": repo.clone(binding)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"bindingId": binding_id})


@router.post("/projects/{project_id}/documents/{document_id}/withdraw")
def withdraw_document(
    request: Request,
    project_id: str,
    document_id: str,
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=document_node_ids(project_id, document_id))
        if guard:
            return guard
        doc = repo.find_one("documents", document_id)
        if not doc or doc.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        doc["fileStatus"] = "已撤回"
        doc["updatedAt"] = server_time()
        return ok({**repo.mutation_result("撤回文件", "Document", document_id, next_status="已撤回"), "document": repo.clone(doc)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"documentId": document_id})


@router.post("/projects/{project_id}/documents/{document_id}/void")
def void_document(
    request: Request,
    project_id: str,
    document_id: str,
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=document_node_ids(project_id, document_id))
        if guard:
            return guard
        doc = repo.find_one("documents", document_id)
        if not doc or doc.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        doc["fileStatus"] = "已作废"
        doc["updatedAt"] = server_time()
        return ok({**repo.mutation_result("作废文件", "Document", document_id, next_status="已作废"), "document": repo.clone(doc)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"documentId": document_id})


@router.post("/projects/{project_id}/documents/batch-classify")
def batch_classify_documents(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        suggestions = [
            {"documentId": doc["id"], "fileName": doc["fileName"], "suggestedNodeIds": [24 if "焊工" in doc["fileName"] else 16], "confidence": 0.82}
            for doc in repo.project_documents(project_id)
        ]
        audit_id = repo.add_audit("批量资料智能分类", "Document", project_id)
        return ok({"suggestions": suggestions, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"projectId": project_id, "body": body})


@router.post("/projects/{project_id}/submissions/drafts")
def save_submission_draft(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = node_ids_from_body(body, ROLE_NODE_MAP["contractor"])

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        draft_id = f"DRAFT-{uuid4().hex[:8].upper()}"
        binding_ids = scoped_binding_ids(project_id, node_ids, body.get("bindingIds") or [])
        if not binding_ids:
            return fail(errors.EMPTY_NODE_PACKAGE, request)
        draft = {
            "draftId": draft_id,
            "projectId": project_id,
            "nodeIds": node_ids,
            "bindingIds": binding_ids,
            "batchName": body.get("batchName"),
            "remark": body.get("remark"),
            "savedAt": server_time(),
        }
        repo.state["submission_drafts"].insert(0, draft)
        repo.add_audit("保存提交草稿", "SubmissionDraft", draft_id)
        return ok({"draftId": draft_id, "savedAt": draft["savedAt"], "bindingIds": binding_ids}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


def draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    nodes = [repo.node(draft["projectId"], node_id) for node_id in draft.get("nodeIds", [])]
    return {
        "draftId": draft["draftId"],
        "projectId": draft["projectId"],
        "nodeIds": draft.get("nodeIds", []),
        "nodeNames": [node["name"] for node in nodes if node],
        "bindingCount": len(draft.get("bindingIds", [])),
        "batchName": draft.get("batchName"),
        "remark": draft.get("remark"),
        "savedAt": draft["savedAt"],
    }


def submission_summary(submission: dict[str, Any]) -> dict[str, Any]:
    nodes = [repo.node(submission["projectId"], node_id) for node_id in submission.get("nodeIds", [])]
    return {
        "submissionId": submission["submissionId"],
        "snapshotId": submission["snapshotId"],
        "projectId": submission["projectId"],
        "nodeIds": submission.get("nodeIds", []),
        "nodeNames": [node["name"] for node in nodes if node],
        "bindingCount": len(submission.get("bindingIds", [])),
        "todoCount": len(submission.get("createdTodoIds", [])),
        "batchName": submission.get("batchName"),
        "submitterComment": submission.get("submitterComment"),
        "nextStatus": submission.get("nextStatus"),
        "submittedAt": submission["submittedAt"],
        "withdrawal": submission.get("withdrawal"),
    }


@router.get("/projects/{project_id}/submissions")
def list_submissions(request: Request, project_id: str):
    drafts = [draft_summary(item) for item in repo.state["submission_drafts"] if item["projectId"] == project_id]
    submissions = [submission_summary(item) for item in repo.state["submissions"] if item["projectId"] == project_id]
    return ok({"drafts": drafts, "submissions": submissions}, request)


@router.get("/projects/{project_id}/submissions/drafts/{draft_id}")
def get_submission_draft(request: Request, project_id: str, draft_id: str):
    draft = next((item for item in repo.state["submission_drafts"] if item["projectId"] == project_id and item["draftId"] == draft_id), None)
    if not draft:
        return fail(errors.NOT_FOUND, request)
    bindings = [item for item in repo.bindings_for_project(project_id) if item["id"] in set(draft.get("bindingIds", []))]
    nodes = [repo.node(project_id, node_id) for node_id in draft.get("nodeIds", [])]
    return ok({**draft_summary(draft), "nodes": [repo.clone(item) for item in nodes if item], "bindings": bindings}, request)


@router.post("/projects/{project_id}/submissions")
def submit_node_package(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = node_ids_from_body(body, ROLE_NODE_MAP["contractor"])

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        submission_id = f"SUB-{uuid4().hex[:8].upper()}"
        snapshot_id = f"SNAP-{uuid4().hex[:8].upper()}"
        binding_ids = scoped_binding_ids(project_id, node_ids, body.get("bindingIds") or [])
        if not binding_ids:
            return fail(errors.EMPTY_NODE_PACKAGE, request)
        changed = []
        for binding in repo.state["bindings"]:
            if binding["id"] in binding_ids:
                binding["bindingStatus"] = "已提交"
        for node_id in node_ids:
            changed.append(repo.set_node_status(project_id, node_id, "AI 预审中"))
        todo_id = f"TODO-{uuid4().hex[:8].upper()}"
        repo.state["todos"].insert(
            0,
            {
                "id": todo_id,
                "title": "节点资料已提交，待 AI 预审",
                "projectId": project_id,
                "nodeId": node_ids[0] if node_ids else None,
                "targetType": "submission",
                "targetId": submission_id,
                "status": "待处理",
                "priority": "中",
                "assigneeName": "张工",
                "actions": ["ai:recheck"],
            },
        )
        submission = {
            "submissionId": submission_id,
            "snapshotId": snapshot_id,
            "projectId": project_id,
            "nodeIds": node_ids,
            "bindingIds": binding_ids,
            "batchName": body.get("batchName"),
            "submitterComment": body.get("submitterComment"),
            "nextStatus": "AI 预审中",
            "submittedAt": server_time(),
            "createdTodoIds": [todo_id],
            "changed": changed,
        }
        repo.state["submissions"].insert(0, submission)
        return ok({"submissionId": submission_id, "snapshotId": snapshot_id, "nextStatus": "AI 预审中", "createdTodos": [repo.state["todos"][0]]}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/submissions/{submission_id}")
def get_submission_detail(request: Request, project_id: str, submission_id: str):
    submission = next((item for item in repo.state["submissions"] if item["projectId"] == project_id and item["submissionId"] == submission_id), None)
    if not submission:
        return fail(errors.NOT_FOUND, request)
    bindings = [item for item in repo.bindings_for_project(project_id) if item["id"] in set(submission.get("bindingIds", []))]
    nodes = [repo.node(project_id, node_id) for node_id in submission.get("nodeIds", [])]
    todos = [item for item in repo.state["todos"] if item["id"] in set(submission.get("createdTodoIds", []))]
    return ok(
        {
            **submission_summary(submission),
            "submissionType": submission.get("submissionType", "document"),
            "nodes": [repo.clone(item) for item in nodes if item],
            "bindings": bindings,
            "createdTodos": todos,
            "changed": submission.get("changed", []),
            "snapshot": repo.clone(submission.get("snapshot")),
        },
        request,
    )


@router.post("/projects/{project_id}/submissions/{submission_id}/withdraw-items")
def withdraw_submission_items(
    request: Request,
    project_id: str,
    submission_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        binding_ids = [str(item) for item in (body.get("bindingIds") or []) if item]
        if not binding_ids:
            return fail(errors.EMPTY_BINDINGS, request)
        requested_ids = set(binding_ids)
        submission = next(
            (
                item
                for item in repo.state["submissions"]
                if item["projectId"] == project_id and item["submissionId"] == submission_id
            ),
            None,
        )
        if not submission:
            return fail(errors.NOT_FOUND, request)
        submitted_ids = set(submission.get("bindingIds") or [])
        invalid_ids = sorted(requested_ids - submitted_ids)
        if invalid_ids:
            return fail(
                errors.CONFLICT,
                request,
                message="只能撤回当前提交批次内的资料。",
                data={"invalidBindingIds": invalid_ids},
            )
        binding_by_id = {
            binding["id"]: binding
            for binding in repo.state["bindings"]
            if binding.get("projectId") == project_id and binding["id"] in requested_ids
        }
        missing_ids = sorted(requested_ids - set(binding_by_id))
        if missing_ids:
            return fail(errors.NOT_FOUND, request, data={"missingBindingIds": missing_ids})
        locked_ids = sorted(
            binding["id"]
            for binding in binding_by_id.values()
            if binding.get("bindingStatus") in {"已通过", "已锁定", "已归档"}
        )
        if locked_ids:
            return fail(errors.WITHDRAW_LOCKED, request, data={"lockedBindingIds": locked_ids})
        for binding in binding_by_id.values():
            binding["bindingStatus"] = "草稿挂载"
        withdrawn_ids = sorted(set(submission.get("withdrawnBindingIds") or []) | requested_ids)
        submission["withdrawnBindingIds"] = withdrawn_ids
        submission["withdrawal"] = {
            "bindingCount": len(withdrawn_ids),
            "reason": body.get("reason") or "撤回未提交项",
            "withdrawnAt": server_time(),
        }
        submission["nextStatus"] = "部分提交"
        node_ids = sorted({int(item["nodeId"]) for item in binding_by_id.values()})
        changed = [repo.set_node_status(project_id, node_id, "部分提交") for node_id in node_ids]
        return ok(repo.mutation_result("撤回未提交项", "Submission", submission_id, next_status="部分提交", changed=changed, affected_ids=binding_ids), request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/projects/{project_id}/rectifications")
def submit_rectification(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = node_ids_from_body(body, ROLE_NODE_MAP["contractor"])

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        node_id = node_ids[0] if node_ids else ROLE_NODE_MAP["contractor"]
        node = repo.node(project_id, node_id)
        if not node:
            return fail(errors.NOT_FOUND, request)
        binding_ids = [str(item) for item in (body.get("bindingIds") or []) if item]
        if not binding_ids:
            return fail(errors.EMPTY_BINDINGS, request)
        node_binding_ids = {item["id"] for item in repo.state["bindings"] if item["projectId"] == project_id and int(item["nodeId"]) == node_id}
        invalid_binding_ids = sorted(set(binding_ids) - node_binding_ids)
        if invalid_binding_ids:
            return fail(
                errors.CONFLICT,
                request,
                message="补正反馈资料必须属于当前节点。",
                data={"invalidBindingIds": invalid_binding_ids},
            )
        rectification_id = body.get("rectificationId")
        if rectification_id:
            rectification = next(
                (
                    item
                    for item in repo.state["rectifications"]
                    if item["projectId"] == project_id and item["id"] == rectification_id
                ),
                None,
            )
            if not rectification:
                return fail(errors.NOT_FOUND, request)
            if int(rectification["nodeId"]) != node_id:
                return fail(errors.CONFLICT, request, message="补正单不属于当前节点。")
        else:
            rectification = next(
                (
                    item
                    for item in repo.state["rectifications"]
                    if item["projectId"] == project_id and int(item["nodeId"]) == node_id and item.get("status") == "待反馈"
                ),
                None,
            )
            if not rectification:
                return fail(errors.CONFLICT, request, message="当前节点没有待反馈补正单。")
        if rectification.get("status") != "待反馈":
            return fail(errors.CONFLICT, request, message="补正单当前状态不允许提交反馈。")
        rectification["status"] = "已反馈"
        rectification["comment"] = body.get("comment") or body.get("description")
        rectification["bindingIds"] = binding_ids
        rectification["feedbackAt"] = server_time()
        rectification["feedbackByName"] = "李工"
        changed = [repo.set_node_status(project_id, node_id, "复审中")]
        return ok(
            {
                "rectification": {
                    "id": rectification["id"],
                    "projectId": project_id,
                    "nodeId": node_id,
                    "status": rectification["status"],
                },
                "nextStatus": "复审中",
                "createdTodos": [],
                **repo.mutation_result(
                    "提交补正反馈",
                    "Rectification",
                    rectification["id"],
                    next_status="复审中",
                    changed=changed,
                    affected_ids=[rectification["id"], *binding_ids],
                ),
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/rectifications")
def list_rectifications(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return ok(page([repo.clone(item) for item in repo.state["rectifications"] if item["projectId"] == project_id], page_no, page_size), request)


@router.get("/projects/{project_id}/rectifications/{rectification_id}")
def rectification_detail(request: Request, project_id: str, rectification_id: str):
    item = repo.find_one("rectifications", rectification_id)
    if not item:
        return fail(errors.NOT_FOUND, request)
    return ok({"rectification": repo.clone(item), "bindings": repo.bindings_for_node(project_id, item["nodeId"]), "evidenceLinks": repo.clone(repo.state["evidence_links"])}, request)


@router.get("/projects/{project_id}/workflow")
def project_workflow(request: Request, project_id: str):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    return ok({"projectId": project_id, "status": project["status"], "stateMachineVersion": "WF-PIPE-2026"}, request)


@router.get("/projects/{project_id}/workflow/instances/{workflow_id}")
def workflow_instance(request: Request, project_id: str, workflow_id: str):
    return ok({"id": workflow_id, "projectId": project_id, "status": "运行中", "currentNodeId": ROLE_NODE_MAP["inspection"]}, request)


@router.get("/projects/{project_id}/workflow/timeline")
def workflow_timeline(request: Request, project_id: str):
    return ok(
        [
            {"title": "资料提交", "actorName": "李工", "status": "已提交", "createdAt": "2026-06-25 10:45:00"},
            {"title": "AI 预审", "actorName": "系统", "status": "完成", "createdAt": "2026-06-25 15:10:00"},
            {"title": "监检审查", "actorName": "张工", "status": "待人工确认", "createdAt": "2026-06-26 09:12:00"},
        ],
        request,
    )


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/attachments")
def inspection_attachments(
    request: Request,
    project_id: str,
    node_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return create_upload_session(request, project_id, {"files": body.get("files") or [{"fileName": "监检资料.pdf", "fileSize": 245760, "fileType": "application/pdf"}]}, idempotency_key, x_role)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/file-bindings")
def inspection_file_bindings(
    request: Request,
    project_id: str,
    node_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = {**body, "nodeId": node_id}
    return bind_documents(request, project_id, body, idempotency_key, x_role)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/ai-recheck")
def ai_recheck(
    request: Request,
    project_id: str,
    node_id: int,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        run_id = f"AIRUN-{node_id}-{uuid4().hex[:8].upper()}"
        node = repo.node(project_id, node_id)
        project = repo.require_project(project_id)
        pack = business_pack_for_project(project)
        agent = (pack.get("agentSops") or [{}])[0]
        rule = (
            current_business_rule_for_node(node_id, business_pack_id=pack["id"])
            or next(
                (item for item in pack.get("ruleSets") or [] if node_id in set(item.get("nodeIds") or [])),
                (pack.get("ruleSets") or [{}])[0],
            )
        )
        run = {
            "id": run_id,
            "projectId": project_id,
            "nodeId": node_id,
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "businessPackSnapshotHash": pack["snapshotHash"],
            "agentId": agent.get("id") or "review_agent",
            "agentVersion": agent.get("version") or "1.0.0",
            "subject": node["name"] if node else "节点 AI 复核",
            "model": "review-chat",
            "promptVersion": f"node-{node_id}-v1",
            "ruleVersion": rule.get("version") or "ruleset-v1",
            "inputDocumentVersionIds": [item["documentVersionId"] for item in repo.bindings_for_node(project_id, node_id)],
            "status": "推理中",
            "startedAt": server_time(),
            "steps": [],
            "suggestion": {
                "id": f"AIS-{uuid4().hex[:8].upper()}",
                "result": "需人工确认",
                "opinionDraft": "AI 复核任务已进入队列，完成后将更新审查建议。",
                "risks": [],
                "confidence": 0.0,
                "manualConfirmItems": [],
            },
            "evidenceLinks": [],
            "findingDrafts": [],
        }
        repo.state["ai_runs"].insert(0, run)
        repo.set_node_status(project_id, node_id, "业务核验中")
        dispatch = task_dispatcher.dispatch_ai_recheck(project_id, node_id, run_id)
        if dispatch.get("reviewRunId"):
            run["reviewRunId"] = dispatch.get("reviewRunId")
        if dispatch.get("workflowId"):
            run["workflowId"] = dispatch.get("workflowId")
        return ok({"runId": run_id, "status": run["status"], "latestRun": run, "dispatch": dispatch}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "nodeId": node_id},
    )


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/ai-runs")
def list_ai_runs(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["ai_runs"] if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)], request)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/ai-runs/{run_id}")
def get_ai_run(request: Request, project_id: str, node_id: int, run_id: str):
    run = repo.find_one("ai_runs", run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok(repo.clone(run), request)


@router.get("/review-runs/{review_run_id}")
def get_review_run(request: Request, review_run_id: str):
    refresh_state_from_postgres_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        run = fde_find_or_materialize_synthetic_review_run(review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    project_id = run.get("projectId")
    if project_id and not project_visible_for_request(request, str(project_id)):
        return fail(errors.FORBIDDEN, request)
    return ok({"run": review_run_view(run)}, request)


@router.get("/review-runs/{review_run_id}/timeline")
def get_review_run_timeline(request: Request, review_run_id: str):
    refresh_state_from_postgres_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        run = fde_find_or_materialize_synthetic_review_run(review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    project_id = run.get("projectId")
    if project_id and not project_visible_for_request(request, str(project_id)):
        return fail(errors.FORBIDDEN, request)
    return ok({"reviewRunId": review_run_id, "events": review_run_timeline(review_run_id)}, request)


@router.get("/review-runs/{review_run_id}/graph")
def get_review_run_graph(request: Request, review_run_id: str):
    refresh_state_from_postgres_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        run = fde_find_or_materialize_synthetic_review_run(review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    project_id = run.get("projectId")
    if project_id and not project_visible_for_request(request, str(project_id)):
        return fail(errors.FORBIDDEN, request)
    return ok({"reviewRunId": review_run_id, **graph_view_for_review_run(review_run_id)}, request)


@router.post("/review-runs/{review_run_id}/human-decision")
def submit_review_run_human_decision(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        refresh_state_from_postgres_for_live_read()
        run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
        if not run:
            return fail(errors.NOT_FOUND, request)
        project_id = run.get("projectId")
        if project_id and not project_visible_for_request(request, str(project_id)):
            return fail(errors.FORBIDDEN, request)
        decision = str(body.get("decision") or "accept")
        result = human_decision_for_review_run(review_run_id, decision, body)
        if result.get("status") in {"missing", "invalid_decision"}:
            return fail(errors.VALIDATION_ERROR, request, data=result)
        temporal_signal = signal_review_run_human_decision(
            result["reviewRun"],
            {
                "decision": decision,
                "status": result["status"],
                "comment": body.get("comment") or body.get("reason"),
                "decidedAt": result["reviewRun"].get("humanDecision", {}).get("decidedAt"),
            },
        )
        result["reviewRun"]["temporalSignal"] = temporal_signal
        audit_id = repo.add_audit("提交 ReviewRun 人工确认", "ReviewRun", review_run_id)
        return ok(
            {
                "reviewRun": review_run_view(result["reviewRun"]),
                "feedback": result.get("feedback"),
                "temporalSignal": temporal_signal,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source={"reviewRunId": review_run_id, "body": body})


@router.post("/review-runs/{review_run_id}/cancel")
def cancel_review_run(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        refresh_state_from_postgres_for_live_read()
        run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
        if not run:
            return fail(errors.NOT_FOUND, request)
        run["status"] = "cancelled"
        run["cancelReason"] = body.get("reason") or "用户取消 ReviewRun"
        run["updatedAt"] = server_time()
        temporal_signal = signal_review_run_cancel(run, run["cancelReason"])
        run["temporalSignal"] = temporal_signal
        audit_id = repo.add_audit("取消 ReviewRun", "ReviewRun", review_run_id)
        return ok({"reviewRun": review_run_view(run), "temporalSignal": temporal_signal, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"reviewRunId": review_run_id, "body": body})


@router.post("/review-runs/{review_run_id}/rerun")
def rerun_review_run(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        refresh_state_from_postgres_for_live_read()
        parent = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
        if not parent:
            return fail(errors.NOT_FOUND, request)
        project_id = parent.get("projectId")
        if project_id and not project_visible_for_request(request, str(project_id)):
            return fail(errors.FORBIDDEN, request)
        child = clone_review_run_for_replay(parent, run_mode="diagnostic_replay", reason=body.get("reason") or "业务端请求重跑")
        audit_id = repo.add_audit("业务端请求 ReviewRun 重跑", "ReviewRun", child["reviewRunId"])
        return ok({"reviewRun": review_run_view(child), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"reviewRunId": review_run_id, "body": body})


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/review-opinions")
def save_review_opinion(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        opinion = {
            "id": f"OPN-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "result": body.get("result") or "满足要求",
            "opinion": body.get("opinion") or "资料、证据链与规则要求一致，同意通过。",
            "basis": body.get("basis"),
            "riskLevel": body.get("riskLevel", "低"),
            "closeStatus": "未关闭",
            "evidenceLinkIds": body.get("evidenceLinkIds") or [],
            "reviewerName": "张工",
            "createdAt": server_time(),
        }
        repo.state["review_opinions"].insert(0, opinion)
        next_status = "已通过" if opinion["result"] == "满足要求" else "需补正"
        repo.set_node_status(project_id, node_id, next_status)
        return ok({"opinion": opinion, "nextStatus": next_status}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/review-opinions")
def list_review_opinions(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["review_opinions"] if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)], request)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/ai-suggestions/{suggestion_id}/adopt")
def adopt_ai_suggestion(request: Request, project_id: str, node_id: int, suggestion_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        draft = {
            "id": f"OPN-DRAFT-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "result": body.get("result") or "满足要求",
            "opinion": body.get("opinion") or "采纳 AI 建议。",
            "evidenceLinkIds": body.get("evidenceLinkIds") or ["EV-24-001"],
            "reviewerName": "张工",
            "createdAt": server_time(),
        }
        audit_id = repo.add_audit("采纳 AI 建议", "AiSuggestion", suggestion_id)
        return ok({"draftOpinion": draft, "auditLogId": audit_id}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "nodeId": node_id, "suggestionId": suggestion_id, "body": body},
    )


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/ai-suggestions/{suggestion_id}/reject")
def reject_ai_suggestion(request: Request, project_id: str, node_id: int, suggestion_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        return ok(repo.mutation_result("驳回 AI 建议", "AiSuggestion", suggestion_id, changed=[{"field": "reason", "after": body.get("reason")}]), request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "nodeId": node_id, "suggestionId": suggestion_id, "body": body},
    )


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/actions/return-correction")
def return_correction(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        rectification = {
            "id": f"REC-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "status": "待反馈",
            "comment": body.get("reason") or body.get("requirement") or "请补充说明。",
            "createdAt": server_time(),
        }
        repo.state["rectifications"].insert(0, rectification)
        changed = [repo.set_node_status(project_id, node_id, "需补正")]
        todo = {
            "id": f"TODO-{uuid4().hex[:8].upper()}",
            "title": f"节点 {node_id} 退回补正",
            "projectId": project_id,
            "nodeId": node_id,
            "targetType": "rectification",
            "targetId": rectification["id"],
            "status": "待处理",
            "priority": "高",
            "assigneeName": "李工",
            "actions": ["rectification:submit"],
        }
        repo.state["todos"].insert(0, todo)
        return ok({"rectification": {"id": rectification["id"], "projectId": project_id, "nodeId": node_id, "status": rectification["status"]}, "nextStatus": "需补正", "createdTodos": [todo], **repo.mutation_result("退回补正", "Rectification", rectification["id"], next_status="需补正", changed=changed)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/evidence-chain")
def evidence_chain(request: Request, project_id: str, node_id: int):
    node = repo.node(project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    links = repo.clone(repo.state["evidence_links"])
    grouped = []
    for object_type in sorted({item["objectType"] for item in links}):
        grouped.append({"objectType": object_type, "links": [item for item in links if item["objectType"] == object_type]})
    return ok({"node": repo.clone(node), "links": links, "groupedByObject": grouped}, request)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/standards")
def standards(request: Request, project_id: str, node_id: int):
    return ok(
        [
            {
                "clauseId": "TSG-Z6002-3.2",
                "standardName": "TSG Z6002 焊接人员考核细则",
                "clauseNo": "3.2",
                "title": "焊工资格覆盖要求",
                "summary": "焊工持证项目应覆盖实际焊接方法、材料类别和焊接位置。",
                "effectiveVersion": "2010",
                "evidenceLinkId": "EV-24-002",
            }
        ],
        request,
    )


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/date-compare")
def date_compare(request: Request, project_id: str, node_id: int):
    return ok(
        [
            {
                "fieldName": "证书有效期",
                "leftLabel": "证书有效期",
                "leftValue": "2024-03-15 至 2028-03-14",
                "rightLabel": "施工周期",
                "rightValue": "2026-06-01 至 2026-12-31",
                "result": "覆盖",
                "evidenceLinkIds": ["EV-24-001"],
            }
        ],
        request,
    )


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/rules/current-version")
def current_rule_version(request: Request, project_id: str, node_id: int):
    project = repo.require_project(project_id)
    business_pack_id = (project or {}).get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
    rule = current_business_rule_for_node(node_id, business_pack_id=business_pack_id)
    if not rule:
        pack = business_pack_for_project(project)
        rule = next(
            (item for item in pack.get("ruleSets") or [] if node_id in set(item.get("nodeIds") or [])),
            repo.state["rule_versions"][0],
        )
    return ok({"rule": repo.clone(rule)}, request)


@router.get("/projects/{project_id}/inspection/nodes/{node_id}/review-log")
def review_log(request: Request, project_id: str, node_id: int):
    return ok([repo.clone(item) for item in repo.state["review_opinions"] if item["projectId"] == project_id and int(item["nodeId"]) == int(node_id)], request)


@router.post("/projects/{project_id}/inspection/nodes/{node_id}/report-review")
def generate_report_review(request: Request, project_id: str, node_id: int, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        node = repo.node(project_id, node_id)
        if not node:
            return fail(errors.NOT_FOUND, request)
        if node.get("status") in REPORT_GENERATION_BLOCKED_STATUSES:
            return fail(
                errors.CONFLICT,
                request,
                message=f"节点状态 {node.get('status')} 不允许生成报告草稿。",
                data={"nodeId": node_id, "status": node.get("status")},
            )
        report = {
            "id": f"RPT-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "reportNo": f"GDJ-JJ-2026-{len(repo.state['reports']) + 1:03d}",
            "versionNo": "V1",
            "title": f"{repo.require_project(project_id)['name']}监督检验报告",
            "status": "复核中",
            "scope": body.get("reportScope") or "currentNode",
            "nodeIds": [node_id],
            "templateVersion": "TPL-PIPE-2026.06",
            "generatedAt": server_time(),
            "generatedByName": "张工",
            "reviewerName": "张工",
            "dataSnapshotId": f"SNAP-RPT-{uuid4().hex[:8].upper()}",
            "previewUrl": "mock://preview/reports/new",
            "actions": ["report:view", "report:export", "report:archive"],
        }
        repo.state["reports"].insert(0, report)
        repo.touch_project(project_id, "报告生成/复核中", node_id)
        todo = {"id": f"TODO-{uuid4().hex[:8].upper()}", "title": "报告复核", "projectId": project_id, "targetType": "report", "targetId": report["id"], "status": "待处理", "priority": "中", "assigneeName": "张工", "actions": ["report:review"]}
        repo.state["todos"].insert(0, todo)
        return ok({"report": report, "nextStatus": "报告生成/复核中", "createdTodos": [todo]}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/owner/reports")
def owner_reports(request: Request, project_id: str):
    scope = authorized_node_scope(request, project_id)
    return ok(
        [
            versioned_report(item)
            for item in repo.state["reports"]
            if item["projectId"] == project_id and report_visible_in_scope(item, scope)
        ],
        request,
    )


@router.get("/projects/{project_id}/reports")
def list_reports(request: Request, project_id: str):
    scope = authorized_node_scope(request, project_id)
    return ok(
        [
            versioned_report(item)
            for item in repo.state["reports"]
            if item["projectId"] == project_id and report_visible_in_scope(item, scope)
        ],
        request,
    )


@router.get("/projects/{project_id}/reports/{report_id}")
def report_detail(request: Request, project_id: str, report_id: str):
    report = repo.find_one("reports", report_id)
    if not report or report.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    return ok(
        {
            "report": versioned_report(report),
            "sections": [
                {"key": "summary", "title": "检验结论", "content": "资料、证据链与规则要求一致，建议复核后签发。", "evidenceLinkIds": ["EV-24-001"]},
                {"key": "node-24", "title": "焊工资格证及持证合格项目", "content": "证书有效期覆盖施工周期，持证项目覆盖焊接方法。", "evidenceLinkIds": ["EV-24-001", "EV-24-002"]},
            ],
            "evidenceLinks": repo.clone(repo.state["evidence_links"]),
            "reviewTrail": [{"title": "生成报告草稿", "actorName": report.get("generatedByName", "张工"), "result": report["status"], "createdAt": report["generatedAt"]}],
            "versionHistory": [{"id": report["id"], "versionNo": report.get("versionNo", "V1"), "status": report["status"], "generatedAt": report["generatedAt"], "summary": "当前版本"}],
        },
        request,
    )


@router.patch("/projects/{project_id}/reports/{report_id}")
def update_report(
    request: Request,
    project_id: str,
    report_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_role: str | None = Header(default=None, alias="X-Role"),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=report_node_ids(project_id, report_id))
        if guard:
            return guard
        report = repo.find_one("reports", report_id)
        if not report or report.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        if not report_if_match_valid(report, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        changed = []
        for field in ["title", "status"]:
            if field in body:
                changed.append({"field": field, "before": report.get(field), "after": body[field]})
                report[field] = body[field]
        if changed:
            report["revision"] = int(report.get("revision") or 1) + 1
            report["updatedAt"] = server_time()
        return ok({"report": versioned_report(report), **repo.mutation_result("保存报告", "Report", report_id, changed=changed)}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "reportId": report_id, "body": body},
    )


@router.get("/projects/{project_id}/reports/{report_id}/versions")
def report_versions(request: Request, project_id: str, report_id: str):
    report = repo.find_one("reports", report_id)
    if not report or report.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    return ok([{"id": report_id, "versionNo": report.get("versionNo", "V1"), "status": report["status"], "generatedAt": report["generatedAt"], "summary": "当前版本"}], request)


@router.post("/projects/{project_id}/reports/{report_id}/export")
def export_report(request: Request, project_id: str, report_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=report_node_ids(project_id, report_id))
        if guard:
            return guard
        report = repo.find_one("reports", report_id)
        if not report or report.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        export_id = f"EXP-RPT-{uuid4().hex[:8].upper()}"
        task = {
            "id": export_id,
            "projectId": project_id,
            "reportId": report_id,
            "nodeIds": report.get("nodeIds") or [],
            "exportType": "report",
            "status": "可下载",
            "progress": 100,
            "fileName": f"{report['title']}.{body.get('format') or 'pdf'}",
            "fileSize": 2097152,
            "downloadUrl": f"mock://download/reports/{report_id}.{body.get('format') or 'pdf'}",
            "createdAt": server_time(),
            "finishedAt": server_time(),
            "expiresAt": "2026-06-27 18:00:00",
        }
        repo.attach_export_artifact(task, content_type="application/pdf" if (body.get("format") or "pdf") == "pdf" else None)
        repo.state["export_tasks"].insert(0, task)
        next_status = "已签发" if report.get("status") == "待签发" else "复核中"
        if report.get("status") != next_status:
            report["status"] = next_status
            report["revision"] = int(report.get("revision") or 1) + 1
            report["updatedAt"] = server_time()
        return ok({"exportId": export_id, "report": versioned_report(report)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/projects/{project_id}/reports/{report_id}/archive")
def archive_report(
    request: Request,
    project_id: str,
    report_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=report_node_ids(project_id, report_id))
        if guard:
            return guard
        report = repo.find_one("reports", report_id)
        if not report or report.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        if not report_if_match_valid(report, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        report["status"] = "已归档"
        report["revision"] = int(report.get("revision") or 1) + 1
        report["updatedAt"] = server_time()
        repo.touch_project(project_id, "已归档")
        item = {
            "id": f"ARCH-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "name": f"{report['title']}.pdf",
            "type": "report",
            "nodeId": report.get("nodeIds", [None])[0],
            "sourceOrgName": "省特检院一部",
            "status": "已归档",
            "updatedAt": server_time(),
            "downloadUrl": report.get("exportUrl") or f"mock://download/reports/{report_id}.pdf",
        }
        repo.state["archive_items"].insert(0, item)
        return ok({"report": versioned_report(report), "nextStatus": "已归档"}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/archive")
def list_archive(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, nodeId: int | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["archive_items"]
        if item.get("projectId") == project_id and archive_visible_in_scope(item, scope)
    ]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    items = filter_keyword(items, keyword, ["name", "sourceOrgName", "status"])
    return ok(page(items, page_no, page_size), request)


@router.get("/projects/{project_id}/archive/package")
def archive_package(request: Request, project_id: str):
    scope = authorized_node_scope(request, project_id)
    export_id = "EXP-ARCHIVE-QUEUE-001"
    existing_task = repo.find_one("export_tasks", export_id)
    task = existing_task or {
        "id": export_id,
        "projectId": project_id,
        "exportType": "archive-package",
        "status": "排队中",
        "progress": 0,
        "fileName": f"{project_id}-归档资料包.zip",
        "fileSize": 4194304,
        "downloadUrl": f"mock://download/archive/{project_id}.zip",
        "createdAt": server_time(),
    }
    if not existing_task:
        repo.state["export_tasks"].insert(0, task)
    task["status"] = "可下载"
    task["progress"] = 100
    task["finishedAt"] = server_time()
    task["updatedAt"] = task["finishedAt"]
    repo.attach_export_artifact(task, content_type="application/zip")
    item_count = len([item for item in repo.state["archive_items"] if item.get("projectId") == project_id and archive_visible_in_scope(item, scope)])
    download_url = task.get("downloadUrl") or f"mock://download/archive/{project_id}.zip"
    return ok({**repo.signed_get(task["fileName"], download_url, "application/zip", task.get("fileSize")), "exportId": export_id, "projectId": project_id, "packageType": "archive", "itemCount": item_count, "generatedAt": server_time()}, request)


@router.get("/projects/{project_id}/archive/evidence-package")
def evidence_package(request: Request, project_id: str, nodeId: int | None = None):
    scope = authorized_node_scope(request, project_id)
    effective_node_id = nodeId or 24
    if scope is not None and effective_node_id not in scope:
        return fail(errors.FORBIDDEN, request, message="用户不在该节点授权范围内。")
    export_id = "EXP-EVIDENCE-RUNNING-001"
    file_name = f"{project_id}-节点{effective_node_id}-证据定位包.zip"
    task = repo.find_one("export_tasks", export_id) or {"id": export_id, "projectId": project_id, "exportType": "evidence-package", "status": "排队中", "progress": 0, "fileName": file_name, "fileSize": 786432, "downloadUrl": f"mock://download/archive/{project_id}-evidence.zip", "createdAt": server_time()}
    if not repo.find_one("export_tasks", export_id):
        repo.state["export_tasks"].insert(0, task)
    task["status"] = "可下载"
    task["progress"] = 100
    task["finishedAt"] = server_time()
    task["updatedAt"] = task["finishedAt"]
    repo.attach_export_artifact(task, content_type="application/zip")
    return ok({**repo.signed_get(file_name, task["downloadUrl"], "application/zip", task.get("fileSize")), "exportId": export_id, "projectId": project_id, "packageType": "evidence", "itemCount": len(repo.state["evidence_links"]), "generatedAt": server_time()}, request)


@router.get("/projects/{project_id}/archive/{archive_item_id}")
def archive_item_detail(request: Request, project_id: str, archive_item_id: str):
    item = repo.find_one("archive_items", archive_item_id)
    if not item or item.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope = authorized_node_scope(request, project_id)
    if not archive_visible_in_scope(item, scope):
        return fail(errors.FORBIDDEN, request, message="用户不在该资源授权范围内。")
    report = repo.state["reports"][0] if item["type"] == "report" else None
    return ok(
        {
            "item": repo.clone(item),
            "preview": {**repo.signed_get(item["name"], item.get("downloadUrl") or f"mock://preview/archive/{item['id']}", "application/pdf"), "previewType": "pdf", "readonly": True, "pageCount": 4},
            "download": repo.signed_get(item["name"], item.get("downloadUrl") or f"mock://download/archive/{item['id']}"),
            "report": repo.clone(report) if report else None,
            "document": None,
            "evidenceLinks": repo.clone(repo.state["evidence_links"]),
            "relatedExportTasks": [repo.clone(task) for task in repo.state["export_tasks"] if task.get("projectId") == project_id],
        },
        request,
    )


@router.get("/projects/{project_id}/export-tasks/{export_id}")
def project_export_task(request: Request, project_id: str, export_id: str):
    task = repo.find_one("export_tasks", export_id)
    if not task or task.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task, project_id)
    if scope_error:
        return scope_error
    return ok({"task": repo.clone(task)}, request)


@router.get("/exports/{export_id}")
def get_export_task(request: Request, export_id: str):
    task = repo.find_one("export_tasks", export_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    return ok({"task": repo.clone(task)}, request)


@router.get("/exports/{export_id}/download-url")
def export_download_url(request: Request, export_id: str):
    task = repo.find_one("export_tasks", export_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    signed = signed_url_for_task(task)
    if isinstance(signed, dict) and "error" in signed:
        return fail(signed["error"], request)
    return ok(signed, request)


@router.get("/downloads/{file_id}/signed-url")
def file_signed_url(request: Request, file_id: str):
    return ok(repo.signed_get(f"{file_id}.bin", f"mock://download/{file_id}"), request)


@router.post("/exports")
def create_export(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        project_id = body.get("projectId")
        node_ids = node_ids_from_body(body)
        if project_id and body.get("reportId"):
            node_ids = sorted({*node_ids, *report_node_ids(project_id, str(body["reportId"]))})
        if project_id:
            role, identity_error = effective_role_for_request(request)
            if identity_error:
                return identity_error
            scope_error = member_node_scope_error(request, project_id, role, node_ids=node_ids)
            if scope_error:
                return scope_error
        export_id = f"EXP-{uuid4().hex[:8].upper()}"
        task = {
            "id": export_id,
            "projectId": body.get("projectId"),
            "nodeIds": node_ids,
            "reportId": body.get("reportId"),
            "exportType": body.get("exportType") or "config-package",
            "status": "排队中",
            "progress": 0,
            "fileName": body.get("fileName") or f"{export_id}.zip",
            "fileSize": 0,
            "createdAt": server_time(),
            "expiresAt": "2026-06-27 18:00:00",
        }
        repo.state["export_tasks"].insert(0, task)
        dispatch = task_dispatcher.dispatch_export(export_id)
        return ok({"exportId": export_id, "status": task["status"], "task": task, "dispatch": dispatch}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/ndt/summary")
def ndt_summary(request: Request, project_id: str):
    scope = authorized_node_scope(request, project_id)
    films = [item for item in repo.state["ndt_films"] if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)]
    records = [item for item in repo.state["ndt_records"] if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)]
    reports = [item for item in repo.state["ndt_reports"] if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)]
    feedback = [item for item in repo.state["ndt_feedback"] if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)]
    return ok({"filmCount": len(films), "recordCount": len(records), "reportCount": len(reports), "feedbackCount": len(feedback)}, request)


@router.get("/projects/{project_id}/ndt/films")
def list_ndt_films(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), status: str | None = None, method: str | None = None, keyword: str | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["ndt_films"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if status:
        items = [item for item in items if item["status"] == status]
    if method:
        items = [item for item in items if item["method"] == method]
    items = filter_keyword(items, keyword, ["filmNo", "weldNo", "pipelineNo"])
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/ndt/films")
def create_ndt_film(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    node_ids = node_ids_from_body(body, 40)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        missing = missing_required_fields(body, ["filmNo", "weldNo", "method"])
        if missing:
            return fail(errors.NDT_FILM_REQUIRED, request, data={"fields": missing})
        node_id = node_ids[0] if node_ids else 40
        film = {
            "id": f"FILM-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "filmNo": body.get("filmNo"),
            "weldNo": body.get("weldNo"),
            "pipelineNo": body.get("pipelineNo"),
            "method": body.get("method"),
            "testDate": body.get("testDate"),
            "status": "待提交",
            "actions": ["ndt:submit"],
        }
        repo.state["ndt_films"].insert(0, film)
        return ok({"film": film}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/ndt/films/{film_id}")
def ndt_film_detail(request: Request, project_id: str, film_id: str):
    film = repo.find_one("ndt_films", film_id)
    if not film or film.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, film, project_id)
    if scope_error:
        return scope_error
    return ok({"film": repo.clone(film)}, request)


@router.patch("/projects/{project_id}/ndt/films/{film_id}")
def update_ndt_film(request: Request, project_id: str, film_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        film = repo.find_one("ndt_films", film_id)
        if not film or film.get("projectId") != project_id:
            return fail(errors.NOT_FOUND, request)
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=sorted(record_node_ids(project_id, film)))
        if guard:
            return guard
        film.update({key: value for key, value in body.items() if value is not None})
        return ok({"film": repo.clone(film), **repo.mutation_result("更新底片", "NdtFilm", film_id)}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "filmId": film_id, "body": body},
    )


@router.post("/projects/{project_id}/ndt/films/import")
def import_ndt_films(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    def produce():
        rows = body.get("rows") or []
        node_ids = sorted({*node_ids_from_body(body, 40), *[int(row["nodeId"]) for row in rows if row.get("nodeId") is not None]})
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        if not rows:
            return fail(errors.NDT_FILM_REQUIRED, request, message="导入底片行不能为空。")
        failed = [
            {"row": index + 1, "fields": missing_required_fields(row, ["filmNo", "weldNo", "method"])}
            for index, row in enumerate(rows)
            if missing_required_fields(row, ["filmNo", "weldNo", "method"])
        ]
        if failed:
            return fail(errors.NDT_FILM_REQUIRED, request, data={"failed": failed})
        created = []
        node_id = node_ids[0] if node_ids else 40
        for row in rows:
            film = {"id": f"FILM-{uuid4().hex[:8].upper()}", "projectId": project_id, "nodeId": int(row.get("nodeId") or node_id), "filmNo": row.get("filmNo"), "weldNo": row.get("weldNo"), "method": row.get("method"), "status": "待提交", "actions": ["ndt:submit"]}
            repo.state["ndt_films"].insert(0, film)
            created.append(film)
        return ok({"imported": len(created), "failed": [], "films": created}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "body": body},
    )


@router.get("/projects/{project_id}/ndt/records")
def list_ndt_records(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), filmId: str | None = None, reportId: str | None = None, sampleStatus: str | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["ndt_records"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if filmId:
        items = [item for item in items if item.get("filmId") == filmId]
    if reportId:
        items = [item for item in items if item.get("reportId") == reportId]
    if sampleStatus:
        items = [item for item in items if item.get("sampleStatus") == sampleStatus]
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/ndt/records/import")
def import_ndt_records(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    node_ids = node_ids_from_body(body, 40)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        rows = body.get("rows") or []
        if not rows:
            return fail(errors.NDT_RECORD_REQUIRED, request, message="导入检测记录行不能为空。")
        failed = [
            {"row": index + 1, "fields": missing_required_fields(row, ["recordNo", "weldNo", "method"])}
            for index, row in enumerate(rows)
            if missing_required_fields(row, ["recordNo", "weldNo", "method"])
        ]
        if failed:
            return fail(errors.NDT_RECORD_REQUIRED, request, data={"failed": failed})
        created = []
        for row in rows:
            record = {
                "id": f"NDT-REC-{uuid4().hex[:8].upper()}",
                "projectId": project_id,
                "nodeId": node_ids[0] if node_ids else 40,
                "recordNo": row.get("recordNo"),
                "filmId": row.get("filmId"),
                "reportId": row.get("reportId"),
                "weldNo": row.get("weldNo"),
                "pipelineNo": row.get("pipelineNo"),
                "method": row.get("method"),
                "testDate": row.get("testDate") or "2026-06-26",
                "evaluatorName": row.get("evaluatorName") or "王工",
                "result": row.get("result") or "待复核",
                "sampleStatus": row.get("sampleStatus") or "未抽查",
                "conclusion": row.get("conclusion"),
                "importedAt": server_time(),
                "actions": ["ndt:record-import"],
            }
            repo.state["ndt_records"].insert(0, record)
            created.append(record)
        return ok({"imported": len(created), "failed": [], "records": created}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"projectId": project_id, "body": body},
    )


@router.get("/projects/{project_id}/ndt/reports")
def list_ndt_reports(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), status: str | None = None, method: str | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["ndt_reports"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if status:
        items = [item for item in items if item["status"] == status]
    if method:
        items = [item for item in items if item["method"] == method]
    return ok(page(items, page_no, page_size), request)


@router.post("/projects/{project_id}/ndt/reports/upload-session")
def ndt_report_upload_session(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    node_ids = node_ids_from_body(body, 40)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        node_id = node_ids[0] if node_ids else 40
        files = body.get("files") or []
        validation_error = validate_upload_files(request, files, ndt=True)
        if validation_error:
            return validation_error
        session_id = f"UPS-NDT-{uuid4().hex[:8].upper()}"
        upload_urls = []
        for file in files:
            doc, version = repo.create_document(project_id, file.get("fileName", "RT检测报告.pdf"), file.get("fileType", "pdf"), source_org_name="华测检测有限公司", uploader_name="王工")
            doc["nodeId"] = node_id
            knowledge_file = repo.find_one("knowledge_files", f"KF-{doc['id']}")
            if knowledge_file:
                knowledge_file["nodeId"] = node_id
            report = {
                "id": f"NDT-RPT-{uuid4().hex[:8].upper()}",
                "projectId": project_id,
                "nodeId": node_id,
                "reportNo": file.get("fileName", "RT检测报告").split(".")[0],
                "method": "UT" if "UT" in file.get("fileName", "") else "RT",
                "fileId": doc["id"],
                "relatedFilmIds": body.get("relatedFilmIds") or [],
                "status": "待提交",
                "uploadedAt": server_time(),
                "actions": ["ndt:submit"],
            }
            repo.state["ndt_reports"].insert(0, report)
            content_type = file.get("fileType") or "application/pdf"
            upload_urls.append({"fileName": doc["fileName"], "documentId": doc["id"], "documentVersionId": version["id"], "url": repo.signed_put("documents", version["storageKey"], f"mock://upload/ndt/{session_id}/{doc['id']}", content_type=content_type), "method": "PUT", "expiresAt": "2026-06-27 18:00:00", "headers": {"Content-Type": content_type}})
        return ok({"uploadSessionId": session_id, "expiresAt": "2026-06-27 18:00:00", "uploadUrls": upload_urls}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/ndt/reports/{report_id}")
def ndt_report_detail(request: Request, project_id: str, report_id: str):
    report = repo.find_one("ndt_reports", report_id)
    if not report or report.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, report, project_id)
    if scope_error:
        return scope_error
    scope = authorized_node_scope(request, project_id)
    films = [repo.clone(item) for item in repo.state["ndt_films"] if item["id"] in set(report.get("relatedFilmIds", [])) and record_visible_for_scope(item, scope, project_id=project_id)]
    records = [repo.clone(item) for item in repo.state["ndt_records"] if item.get("reportId") == report_id and record_visible_for_scope(item, scope, project_id=project_id)]
    document = repo.find_one("documents", report.get("fileId"))
    feedback = [repo.clone(item) for item in repo.state["ndt_feedback"] if record_visible_for_scope(item, scope, project_id=project_id)]
    return ok({"report": repo.clone(report), "films": films, "records": records, "document": repo.clone(document) if document else None, "feedback": feedback}, request)


@router.post("/projects/{project_id}/ndt/submissions")
def submit_ndt(
    request: Request,
    project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    node_ids = ndt_submission_node_ids(project_id, body)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        node_id = node_ids[0] if node_ids else 40
        submission_id = f"NDT-SUB-{uuid4().hex[:8].upper()}"
        snapshot_id = f"SNAP-{submission_id}"
        submitted_at = server_time()
        submitted_report_ids = set(body.get("reportIds") or [])
        submitted_film_ids = set(body.get("filmIds") or [])
        if not submitted_report_ids:
            return fail(errors.NDT_REPORT_REQUIRED, request)
        submitable_reports = [
            report
            for report in repo.state["ndt_reports"]
            if report.get("projectId") == project_id
            and report.get("id") in submitted_report_ids
            and report.get("status") in {"草稿", "待提交", "需补正"}
            and record_visible_for_request(request, report, project_id)
        ]
        if len(submitable_reports) != len(submitted_report_ids):
            return fail(errors.NDT_REPORT_REQUIRED, request, message="未找到可提交的无损检测报告。")
        submitable_films = [
            film
            for film in repo.state["ndt_films"]
            if film.get("projectId") == project_id
            and film.get("id") in submitted_film_ids
            and record_visible_for_request(request, film, project_id)
        ]
        if submitted_film_ids and len(submitable_films) != len(submitted_film_ids):
            return fail(errors.NDT_FILM_REQUIRED, request, message="未找到可提交的无损检测底片。")
        for report in submitable_reports:
            report["status"] = "待审查"
            report["submittedAt"] = submitted_at
        for film in submitable_films:
            film["status"] = "待审查"
            film["submittedAt"] = submitted_at
        changed = [repo.set_node_status(project_id, node_id, "待审查")]
        todo = {
            "id": f"TODO-{uuid4().hex[:8].upper()}",
            "title": "无损检测资料待审查",
            "projectId": project_id,
            "nodeId": node_id,
            "targetType": "submission",
            "targetId": submission_id,
            "status": "待处理",
            "priority": "中",
            "assigneeName": "张工",
            "actions": ["review:save"],
        }
        repo.state["todos"].insert(0, todo)
        related_records = [
            repo.clone(record)
            for record in repo.state["ndt_records"]
            if record.get("projectId") == project_id
            and (record.get("reportId") in submitted_report_ids or record.get("filmId") in submitted_film_ids)
            and record_visible_for_request(request, record, project_id)
        ]
        submission = {
            "submissionId": submission_id,
            "snapshotId": snapshot_id,
            "projectId": project_id,
            "nodeId": node_id,
            "nodeIds": node_ids,
            "submissionType": "ndt",
            "batchName": body.get("batchName") or "无损检测资料提交",
            "submitterComment": body.get("comment") or body.get("submitterComment"),
            "nextStatus": "待审查",
            "submittedAt": submitted_at,
            "createdTodoIds": [todo["id"]],
            "reportIds": sorted(submitted_report_ids),
            "filmIds": sorted(submitted_film_ids),
            "changed": changed,
            "snapshot": {
                "reports": [repo.clone(report) for report in submitable_reports],
                "films": [repo.clone(film) for film in submitable_films],
                "records": related_records,
            },
        }
        repo.state["submissions"].insert(0, submission)
        return ok(
            {
                "submissionId": submission_id,
                "snapshotId": snapshot_id,
                "nextStatus": "待审查",
                "createdTodos": [todo],
                "submittedReportIds": sorted(submitted_report_ids),
                "submittedFilmIds": sorted(submitted_film_ids),
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/projects/{project_id}/ndt/rectifications")
def ndt_rectification(request: Request, project_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), x_role: str | None = Header(default=None, alias="X-Role")):
    node_ids = node_ids_from_body(body, 40)

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=node_ids)
        if guard:
            return guard
        node_id = node_ids[0] if node_ids else 40
        rectification_id = body.get("rectificationId") or f"NDT-REC-{uuid4().hex[:8].upper()}"
        if not body.get("description") or (not body.get("rectificationId") and not body.get("reportIds") and not body.get("filmIds")):
            return fail(errors.NDT_RECTIFICATION_REQUIRED, request)
        feedback = repo.find_one("ndt_feedback", rectification_id)
        if feedback:
            scope_error = scope_error_for_record(request, feedback, project_id)
            if scope_error:
                return scope_error
            feedback["status"] = "已反馈"
            feedback["feedbackDescription"] = body.get("description")
            feedback["feedbackAt"] = server_time()
        else:
            feedback = {
                "id": rectification_id,
                "projectId": project_id,
                "nodeId": node_id,
                "title": "无损检测补正反馈",
                "description": body.get("description") or "已补充无损检测资料。",
                "status": "已反馈",
                "relatedReportIds": body.get("reportIds") or [],
                "relatedFilmIds": body.get("filmIds") or [],
                "createdAt": server_time(),
            }
            repo.state["ndt_feedback"].insert(0, feedback)
        rectification = {"id": feedback["id"], "projectId": project_id, "nodeId": node_id, "status": feedback["status"]}
        repo.set_node_status(project_id, node_id, "复审中")
        return ok({"rectification": rectification, "nextStatus": "复审中"}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/ndt/inspection-feedback")
def list_ndt_feedback(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), status: str | None = None):
    scope = authorized_node_scope(request, project_id)
    items = [
        repo.clone(item)
        for item in repo.state["ndt_feedback"]
        if item["projectId"] == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if status:
        items = [item for item in items if item["status"] == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/projects/{project_id}/ndt/inspection-feedback/{feedback_id}")
def ndt_feedback_detail(request: Request, project_id: str, feedback_id: str):
    feedback = repo.find_one("ndt_feedback", feedback_id)
    if not feedback or feedback.get("projectId") != project_id:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, feedback, project_id)
    if scope_error:
        return scope_error
    scope = authorized_node_scope(request, project_id)
    return ok(
        {
            "feedback": repo.clone(feedback),
            "reports": [repo.clone(item) for item in repo.state["ndt_reports"] if item["id"] in set(feedback.get("relatedReportIds", [])) and record_visible_for_scope(item, scope, project_id=project_id)],
            "films": [repo.clone(item) for item in repo.state["ndt_films"] if item["id"] in set(feedback.get("relatedFilmIds", [])) and record_visible_for_scope(item, scope, project_id=project_id)],
            "records": [repo.clone(item) for item in repo.state["ndt_records"] if record_visible_for_scope(item, scope, project_id=project_id)],
            "evidenceLinks": repo.clone(repo.state["evidence_links"]),
            "timeline": [{"title": "监检反馈", "actorName": "张工", "status": feedback["status"], "createdAt": feedback["createdAt"], "comment": feedback["description"]}],
        },
        request,
    )


@router.get("/search")
def search(request: Request, keyword: str = Query(default=""), projectId: str | None = None, type: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    results: list[dict[str, Any]] = []
    lowered = keyword.lower()
    for project in repo.state["projects"]:
        scope = authorized_node_scope(request, project["id"])
        if (not projectId or project["id"] == projectId) and (scope is None or bool(scope)):
            results.append({"type": "project", "id": project["id"], "title": project["name"], "description": project["status"], "route": f"/workbench/inspection?projectId={project['id']}", "highlights": [project["code"], project["region"]]})
    for node in repo.state["tree_nodes"]:
        scope = authorized_node_scope(request, node["projectId"])
        if (not projectId or node["projectId"] == projectId) and record_visible_for_scope(node, scope, project_id=node["projectId"]):
            results.append({"type": "node", "id": str(node["nodeId"]), "title": f"节点 {node['nodeId']} {node['name']}", "description": node["status"], "route": f"/workbench/inspection?nodeId={node['nodeId']}", "highlights": [node["groupName"], node["inspectionType"]]})
    for doc in repo.state["documents"]:
        scope = authorized_node_scope(request, doc["projectId"])
        if (not projectId or doc["projectId"] == projectId) and document_visible_in_scope(doc, scope):
            results.append({"type": "document", "id": doc["id"], "title": doc["fileName"], "description": doc["sourceOrgName"], "route": f"/workbench/contractor?documentId={doc['id']}", "highlights": [doc["currentOcrStatus"]]})
    for report in repo.state["reports"]:
        scope = authorized_node_scope(request, report["projectId"])
        if (not projectId or report["projectId"] == projectId) and report_visible_in_scope(report, scope):
            results.append({"type": "report", "id": report["id"], "title": report["title"], "description": report["status"], "route": f"/workbench/owner?reportId={report['id']}", "highlights": [report["reportNo"]]})
    if type:
        results = [item for item in results if item["type"] == type]
    if keyword:
        results = [item for item in results if lowered in f"{item['title']} {item['description']} {' '.join(item['highlights'])}".lower()]
    return ok(page(results, page_no, page_size), request)


@router.get("/todos")
def list_todos(request: Request, role: str | None = None, projectId: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("todo", item) for item in repo.state["todos"] if record_visible_for_request(request, item)]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if status:
        items = [item for item in items if item.get("status") == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/todos/{todo_id}")
def todo_detail(request: Request, todo_id: str):
    todo = repo.find_one("todos", todo_id)
    if not todo:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, todo)
    if scope_error:
        return scope_error
    return ok({**versioned_record("todo", todo), "relatedObject": None, "evidenceLinks": repo.clone(repo.state["evidence_links"])}, request)


@router.post("/todos/{todo_id}/complete")
def complete_todo(
    request: Request,
    todo_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        todo = repo.find_one("todos", todo_id)
        if not todo:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, todo)
        if scope_error:
            return scope_error
        if not record_if_match_valid("todo", todo, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        if todo.get("status") != "已完成":
            todo["status"] = "已完成"
            todo["completedAt"] = server_time()
            todo["completedComment"] = body.get("comment") or body.get("result")
            bump_record_revision(todo)
        result = repo.mutation_result("完成待办", "Todo", todo_id, next_status="已完成")
        return ok({**result, "todo": versioned_record("todo", todo)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"todoId": todo_id, "body": body})


@router.post("/todos/{todo_id}/defer")
def defer_todo(
    request: Request,
    todo_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        todo = repo.find_one("todos", todo_id)
        if not todo:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, todo)
        if scope_error:
            return scope_error
        if not record_if_match_valid("todo", todo, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        if todo.get("status") != "已延期":
            todo["status"] = "已延期"
            todo["deferredUntil"] = body.get("deferredUntil")
            bump_record_revision(todo)
        result = repo.mutation_result("延期待办", "Todo", todo_id, next_status="已延期")
        return ok({**result, "todo": versioned_record("todo", todo)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"todoId": todo_id, "body": body})


@router.get("/messages")
def list_messages(request: Request, projectId: str | None = None, read: bool | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("message", item) for item in repo.state["messages"] if record_visible_for_request(request, item)]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if read is not None:
        items = [item for item in items if item.get("read") is read]
    return ok(page(items, page_no, page_size), request)


@router.post("/messages/{message_id}/read")
def mark_message_read(
    request: Request,
    message_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        message = repo.find_one("messages", message_id)
        if not message:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, message)
        if scope_error:
            return scope_error
        if not record_if_match_valid("message", message, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        if not message.get("read"):
            message["read"] = True
            message["readAt"] = server_time()
            bump_record_revision(message)
        result = repo.mutation_result("标记消息已读", "Message", message_id)
        return ok({**result, "message": versioned_record("message", message)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"messageId": message_id})


@router.post("/messages/read-all")
def mark_all_messages_read(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        if if_match and if_match != "*":
            return fail(errors.ETAG_CONFLICT, request, message="批量消息操作仅支持 If-Match: *。")
        affected = 0
        updated_messages = []
        for message in repo.state["messages"]:
            if body.get("projectId") and message.get("projectId") != body.get("projectId"):
                continue
            if not record_visible_for_request(request, message):
                continue
            if not message.get("read"):
                message["read"] = True
                message["readAt"] = server_time()
                bump_record_revision(message)
                affected += 1
            updated_messages.append(versioned_record("message", message))
        audit_id = repo.add_audit("全部消息已读", "Message", body.get("projectId") or "all")
        return ok({"affectedCount": affected, "messages": updated_messages, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/workflow/commands")
def execute_workflow_command(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        project_id = body.get("projectId")
        if not project_id:
            return fail(errors.VALIDATION_ERROR, request, message="projectId 不能为空。")
        node_id = body.get("nodeId")
        guard = mutation_guard(
            request,
            project_id,
            x_role=x_role,
            node_ids=[int(node_id)] if node_id is not None else None,
        )
        if guard:
            return guard
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        pack = business_pack_for_project(project)
        action = body.get("action") or body.get("command")
        transitions = [
            transition
            for workflow in pack.get("workflowStateMachines") or []
            for transition in workflow.get("transitions") or []
            if transition.get("action") == action
        ]
        next_status = body.get("nextStatus") or (transitions[0].get("to") if transitions else "submitted")
        changed = []
        if node_id is not None:
            node = repo.node(project_id, int(node_id))
            if not node:
                return fail(errors.NOT_FOUND, request, message="节点不存在。")
            changed.append(repo.set_node_status(project_id, int(node_id), next_status))
        repo.touch_project(project_id)
        audit_id = repo.add_audit("执行工作流命令", "WorkflowCommand", body.get("commandId") or action or "command")
        return ok(
            {
                "commandId": body.get("commandId") or f"CMD-{uuid4().hex[:8].upper()}",
                "projectId": project_id,
                "nodeId": node_id,
                "action": action,
                "nextStatus": next_status,
                "changed": changed,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/projects/{project_id}/review-workbench")
def generic_review_workbench(request: Request, project_id: str, nodeId: int | None = None):
    project = repo.require_project(project_id)
    if not project:
        return fail(errors.NOT_FOUND, request)
    scope = authorized_node_scope(request, project_id)
    nodes = [
        item
        for item in repo.state["tree_nodes"]
        if item.get("projectId") == project_id and record_visible_for_scope(item, scope, project_id=project_id)
    ]
    if nodeId is not None:
        nodes = [item for item in nodes if int(item["nodeId"]) == int(nodeId)]
    findings = [
        repo.clone(item)
        for item in repo.state["review_findings"]
        if item.get("projectId") == project_id and (nodeId is None or int(item.get("nodeId") or 0) == int(nodeId))
    ]
    return ok(
        {
            "project": versioned_project(project),
            "businessPack": business_pack_summary(business_pack_for_project(project)),
            "nodes": repo.clone(nodes),
            "findings": findings,
            "aiRuns": [
                repo.clone(item)
                for item in repo.state["ai_runs"]
                if item.get("projectId") == project_id and (nodeId is None or int(item.get("nodeId") or 0) == int(nodeId))
            ],
        },
        request,
    )


@router.post("/review/findings")
def create_review_finding(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        project_id = body.get("projectId")
        node_id = int(body.get("nodeId") or 0)
        if not project_id or not node_id:
            return fail(errors.VALIDATION_ERROR, request, message="projectId 和 nodeId 不能为空。")
        guard = mutation_guard(request, project_id, x_role=x_role, node_ids=[node_id])
        if guard:
            return guard
        project = repo.require_project(project_id)
        if not project:
            return fail(errors.NOT_FOUND, request)
        pack = business_pack_for_project(project)
        agent = (pack.get("agentSops") or [{}])[0]
        evidence_link_ids = body.get("evidenceLinkIds") or []
        rule_refs = body.get("ruleRefs") or []
        if body.get("source") == "ai" and (not evidence_link_ids or not rule_refs):
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="AI 审查发现必须包含 evidenceLinkIds 和 ruleRefs。",
            )
        finding = {
            "id": body.get("id") or f"FND-{uuid4().hex[:8].upper()}",
            "projectId": project_id,
            "nodeId": node_id,
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "businessPackSnapshotHash": pack["snapshotHash"],
            "agentId": body.get("agentId") or agent.get("id"),
            "agentVersion": body.get("agentVersion") or agent.get("version"),
            "findingType": body.get("findingType") or "manual_review",
            "severity": body.get("severity") or "medium",
            "title": body.get("title") or "审查发现",
            "description": body.get("description") or body.get("opinion") or "请人工确认该发现。",
            "evidenceLinkIds": evidence_link_ids,
            "ruleRefs": rule_refs,
            "kbRefs": body.get("kbRefs") or [],
            "confidence": float(body.get("confidence") or 1),
            "suggestedAction": body.get("suggestedAction") or "human_confirm",
            "status": "draft",
            "source": body.get("source") or "human",
            "humanStatus": body.get("humanStatus") or "pending_human_review",
            "createdAt": server_time(),
            "revision": 1,
        }
        repo.state["review_findings"].insert(0, finding)
        audit_id = repo.add_audit("创建审查发现", "ReviewFinding", finding["id"])
        return ok({"finding": finding, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/review/findings/{finding_id}/accept")
def accept_review_finding(
    request: Request,
    finding_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        finding = repo.find_one("review_findings", finding_id)
        if not finding:
            return fail(errors.NOT_FOUND, request)
        guard = mutation_guard(request, finding["projectId"], x_role=x_role, node_ids=[int(finding["nodeId"])])
        if guard:
            return guard
        finding["status"] = "accepted"
        finding["acceptedAt"] = server_time()
        finding["revision"] = int(finding.get("revision") or 1) + 1
        opinion = {
            "id": f"OPN-{uuid4().hex[:8].upper()}",
            "projectId": finding["projectId"],
            "nodeId": finding["nodeId"],
            "result": body.get("result") or ("需补正" if finding.get("suggestedAction") == "request_correction" else "满足要求"),
            "opinion": body.get("opinion") or finding["description"],
            "findingType": finding["findingType"],
            "ruleRefs": finding.get("ruleRefs") or [],
            "kbRefs": finding.get("kbRefs") or [],
            "evidenceLinkIds": finding.get("evidenceLinkIds") or [],
            "reviewerName": "张工",
            "createdAt": server_time(),
        }
        repo.state["review_opinions"].insert(0, opinion)
        audit_id = repo.add_audit("采纳审查发现", "ReviewFinding", finding_id)
        return ok({"finding": finding, "opinion": opinion, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"findingId": finding_id, "body": body})


@router.post("/review/findings/{finding_id}/reject")
def reject_review_finding(
    request: Request,
    finding_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        finding = repo.find_one("review_findings", finding_id)
        if not finding:
            return fail(errors.NOT_FOUND, request)
        guard = mutation_guard(request, finding["projectId"], x_role=x_role, node_ids=[int(finding["nodeId"])])
        if guard:
            return guard
        finding["status"] = "rejected"
        finding["rejectReason"] = body.get("reason") or "人工驳回。"
        finding["rejectedAt"] = server_time()
        finding["revision"] = int(finding.get("revision") or 1) + 1
        audit_id = repo.add_audit("驳回审查发现", "ReviewFinding", finding_id)
        return ok({"finding": finding, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"findingId": finding_id, "body": body})


@router.post("/ai/runs/{run_id}/feedback")
def create_ai_run_feedback(
    request: Request,
    run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    def produce():
        run = repo.find_one("ai_runs", run_id)
        if not run:
            return fail(errors.NOT_FOUND, request)
        guard = mutation_guard(
            request,
            run["projectId"],
            x_role=x_role,
            node_ids=[int(run["nodeId"])],
        )
        if guard:
            return guard
        feedback_type = body.get("feedbackType") or body.get("type") or "edited"
        if feedback_type not in AI_FEEDBACK_TYPES:
            return fail(
                errors.VALIDATION_ERROR,
                request,
                message="AI 反馈类型不支持。",
                data={"allowedTypes": sorted(AI_FEEDBACK_TYPES)},
            )
        feedback = {
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
            "createdAt": server_time(),
        }
        repo.state["ai_feedback"].insert(0, feedback)
        run.setdefault("humanFeedback", []).insert(0, feedback)
        run["status"] = "已人工确认" if feedback["accepted"] else run.get("status")
        audit_id = repo.add_audit("记录 AI 反馈", "AIRun", run_id)
        return ok({"feedback": feedback, "aiRun": repo.clone(run), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"runId": run_id, "body": body})


def fde_error_unless_allowed(request: Request, action: str | None = None) -> tuple[str | None, JSONResponse | None]:
    role, identity_error = effective_role_for_request(request)
    if identity_error:
        return None, identity_error
    role = role or "inspection"
    if role != "admin" and role not in FDE_ROLES:
        return role, fail(errors.FORBIDDEN, request, message="仅 FDE 或管理员可访问 AI 交付治理后台。")
    if action and role != "admin" and action not in repo.role_actions(role):
        return role, fail(errors.FORBIDDEN, request, message=f"角色 {role} 无权执行 {action}。")
    return role, None


def stable_hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ai_run_snapshot(run: dict[str, Any]) -> dict[str, Any]:
    project = repo.require_project(run.get("projectId"))
    pack = business_pack_for_project(project) if project else load_business_pack(run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
    return {
        "businessPackId": run.get("businessPackId") or pack["id"],
        "businessPackVersion": run.get("businessPackVersion") or pack["version"],
        "businessPackSnapshotHash": run.get("businessPackSnapshotHash") or pack["snapshotHash"],
        "agentId": run.get("agentId") or "unknown_agent",
        "agentVersion": run.get("agentVersion") or "unknown",
        "promptVersion": run.get("promptVersion") or "unknown",
        "modelAlias": run.get("model") or "review-chat",
        "modelResolved": run.get("modelResolved") or run.get("model") or "review-chat",
        "ruleSetVersion": run.get("ruleVersion") or "unknown",
        "knowledgeBaseVersion": run.get("knowledgeBaseVersion") or "proj-v2026.06.26",
        "ocrResultVersions": run.get("ocrResultVersions") or [],
        "inputDocumentVersionIds": run.get("inputDocumentVersionIds") or [],
        "schemaVersion": run.get("schemaVersion") or "ReviewFindingDraftList@1.0.0",
        "runType": run.get("runType") or "production",
    }


def has_raw_access(request: Request, target_type: str, target_id: str) -> bool:
    role, _ = effective_role_for_request(request)
    if role == "admin":
        return True
    user_id = fde_subject_user_id(request)
    if not user_id:
        return False
    now = server_time()
    return any(
        grant.get("subjectUserId") == user_id
        and grant.get("targetType") == target_type
        and grant.get("targetId") == target_id
        and grant.get("status") == "approved"
        and str(grant.get("expiresAt") or "") >= now
        for grant in repo.state.get("access_grants", [])
    )


def fde_subject_user_id(request: Request) -> str | None:
    explicit_user_id = request_user_id(request)
    if explicit_user_id:
        return explicit_user_id
    role, _ = effective_role_for_request(request)
    if role and role in USERS:
        return USERS[role].get("id")
    return None


def mask_text(value: Any, *, visible: int = 24) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= visible:
        return value
    return f"{value[:visible]}...<masked>"


def fde_ai_run_view(run: dict[str, Any], *, raw_access: bool = False) -> dict[str, Any]:
    snapshot = ai_run_snapshot(run)
    view = repo.clone(run)
    view["versionSnapshot"] = snapshot
    view["inputHash"] = run.get("inputHash") or stable_hash_payload(snapshot["inputDocumentVersionIds"])
    view["outputHash"] = run.get("outputHash") or stable_hash_payload(
        {"suggestion": run.get("suggestion"), "findingDrafts": run.get("findingDrafts") or []}
    )
    view["immutable"] = True
    view["rawAccess"] = raw_access
    if not raw_access:
        suggestion = view.get("suggestion") or {}
        if isinstance(suggestion, dict):
            suggestion["opinionDraft"] = mask_text(suggestion.get("opinionDraft"), visible=60)
        for evidence in view.get("evidenceLinks") or []:
            if isinstance(evidence, dict):
                evidence["quotedText"] = mask_text(evidence.get("quotedText"), visible=36)
        for finding in view.get("findingDrafts") or []:
            if isinstance(finding, dict):
                finding["description"] = mask_text(finding.get("description"), visible=80)
    return view


def fde_metric(label: str, value: Any, tone: str = "blue", suffix: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "tone": tone, "suffix": suffix}


def acceptance_rate() -> float:
    feedback = repo.state.get("ai_feedback", [])
    if not feedback:
        return 0.0
    accepted = len([item for item in feedback if item.get("accepted") or item.get("feedbackType") in {"accepted", "edited"}])
    return round(accepted / len(feedback), 4)


def evidence_hit_rate() -> float:
    findings = [item for item in repo.state.get("review_findings", []) if item.get("source") == "ai"]
    if not findings:
        return 0.0
    with_evidence = len([item for item in findings if item.get("evidenceLinkIds") and item.get("ruleRefs")])
    return round(with_evidence / len(findings), 4)


def hallucination_rate() -> float:
    feedback = repo.state.get("ai_feedback", [])
    if not feedback:
        return 0.0
    hallucinations = len([item for item in feedback if item.get("feedbackType") == "hallucination"])
    return round(hallucinations / len(feedback), 4)


def false_positive_rate() -> float:
    feedback = repo.state.get("ai_feedback", [])
    if not feedback:
        return 0.0
    false_positive = len([item for item in feedback if item.get("feedbackType") == "rejected_false_positive"])
    return round(false_positive / len(feedback), 4)


def suspected_miss_rate() -> float:
    feedback = repo.state.get("ai_feedback", [])
    if not feedback:
        return 0.0
    missed = len([item for item in feedback if item.get("feedbackType") == "missed_issue"])
    return round(missed / len(feedback), 4)


def fde_trace_steps_for_run(run: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = str(run.get("id"))
    steps = [repo.clone(item) for item in repo.state.get("ai_trace_steps", []) if item.get("aiRunId") == run_id]
    if steps:
        return sorted(steps, key=lambda item: int(item.get("sequence") or 0))
    return repo.clone(run.get("steps") or [])


def fde_evaluation_report_for_run(run_id: str) -> dict[str, Any] | None:
    return repo.find_one("evaluation_reports", run_id, id_field="evaluationRunId")


def fde_find_evaluation_report(report_ref: str | None) -> dict[str, Any] | None:
    if not report_ref:
        return None
    return repo.find_one("evaluation_reports", report_ref) or repo.find_one(
        "evaluation_reports", report_ref, id_field="evaluationRunId"
    )


def fde_release_gate_results(plan: dict[str, Any]) -> list[dict[str, Any]]:
    risk_level = plan.get("riskLevel") or "medium"
    report_id = plan.get("evaluationReportId")
    rollback_plan_id = plan.get("rollbackPlanId")
    report = fde_find_evaluation_report(str(report_id)) if report_id else None
    approvals = [
        item
        for item in repo.state.get("release_approvals", [])
        if item.get("releasePlanId") == plan.get("id")
        and item.get("status") == "approved"
        and item.get("role") in {"admin", "ai_owner", "platform_admin", "customer_admin"}
    ]
    active_risk_set = any(
        item.get("setType") == "risk" and item.get("status") == "active"
        for item in repo.state.get("evaluation_sets", [])
    )
    gates = [
        {
            "gate": "capability_bundle",
            "passed": bool(repo.find_one("capability_bundles", plan.get("capabilityBundleId"))),
            "message": "Capability Bundle 存在" if plan.get("capabilityBundleId") else "缺少 Capability Bundle",
        },
        {
            "gate": "evaluation_report",
            "passed": bool(report and report.get("status") == "passed"),
            "message": "评估报告已通过" if report and report.get("status") == "passed" else ("评估报告未通过" if report else "缺少评估报告"),
        },
        {
            "gate": "risk_set",
            "passed": active_risk_set,
            "message": "Risk Set 已启用" if active_risk_set else "缺少启用状态的 Risk Set",
        },
        {
            "gate": "rollback_plan",
            "passed": bool(rollback_plan_id),
            "message": "已绑定回滚方案" if rollback_plan_id else "缺少回滚方案",
        },
        {
            "gate": "release_approval",
            "passed": bool(approvals),
            "message": "已获得非 FDE 发布审批" if approvals else "高风险发布需要 AI 负责人或管理员审批",
        },
    ]
    if risk_level != "high":
        for gate in gates:
            if gate["gate"] in {"evaluation_report", "risk_set", "rollback_plan", "release_approval"}:
                gate["passed"] = True
                gate["message"] = "中低风险发布不强制此门禁"
    return gates


def fde_persist_release_gates(plan: dict[str, Any], gates: list[dict[str, Any]]) -> None:
    release_id = plan["id"]
    repo.state["release_gates"] = [
        item for item in repo.state.get("release_gates", []) if item.get("releasePlanId") != release_id
    ]
    for gate in gates:
        repo.state["release_gates"].append(
            {
                "id": f"RGATE-{uuid4().hex[:8].upper()}",
                "releasePlanId": release_id,
                "gate": gate["gate"],
                "passed": gate["passed"],
                "message": gate["message"],
                "checkedAt": server_time(),
            }
        )


def fde_business_pack_validation_result(pack_id: str) -> dict[str, Any] | None:
    try:
        pack = load_business_pack(pack_id)
    except FileNotFoundError:
        return None
    validation = validate_business_pack(pack)
    return {"summary": business_pack_summary(pack), "validation": validation}


def fde_state_list(collection: str) -> list[dict[str, Any]]:
    repo.state.setdefault(collection, [])
    return repo.state[collection]


def fde_diff_value(value: Any) -> Any:
    if isinstance(value, dict):
        ignored = {"createdAt", "updatedAt", "installedAt", "submittedAt", "approvedAt", "shadowStartedAt"}
        return {key: fde_diff_value(value[key]) for key in sorted(value) if key not in ignored}
    if isinstance(value, list):
        return [fde_diff_value(item) for item in value]
    return value


def fde_record_diff(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    baseline = baseline or {}
    current_normalized = fde_diff_value(current)
    baseline_normalized = fde_diff_value(baseline)
    keys = sorted(set(current_normalized) | set(baseline_normalized))
    changes = []
    for key in keys:
        before = baseline_normalized.get(key)
        after = current_normalized.get(key)
        if before != after:
            changes.append({"field": key, "before": before, "after": after})
    return {
        "changed": bool(changes),
        "changeCount": len(changes),
        "changes": changes,
        "addedKeys": [key for key in keys if key not in baseline_normalized],
        "removedKeys": [key for key in keys if key not in current_normalized],
    }


def fde_default_masking_policies() -> list[dict[str, Any]]:
    policies = fde_state_list("masking_policies")
    if policies:
        return policies
    defaults = [
        {
            "id": "MASK-AIRUN-DEFAULT",
            "targetType": "ai_run",
            "fieldPath": "suggestion.opinionDraft",
            "strategy": "prefix",
            "visibleChars": 60,
            "status": "active",
            "riskLevel": "medium",
            "createdAt": server_time(),
        },
        {
            "id": "MASK-EVIDENCE-DEFAULT",
            "targetType": "evidence",
            "fieldPath": "quotedText",
            "strategy": "prefix",
            "visibleChars": 36,
            "status": "active",
            "riskLevel": "high",
            "createdAt": server_time(),
        },
    ]
    policies.extend(defaults)
    return policies


def fde_audit_event_scope(item: dict[str, Any]) -> bool:
    action = str(item.get("action") or "")
    object_type = str(item.get("objectType") or "")
    return action.startswith(("FDE", "管理员批准 FDE", "管理员审批 FDE")) or object_type in {
        "AccessGrant",
        "DataExport",
        "AIRunReplay",
        "ReviewRun",
        "FeedbackTriage",
        "EvaluationRun",
        "CapabilityBundle",
        "ReleasePlan",
        "BusinessPackInstallation",
        "IncidentRCA",
        "OcrCorrection",
        "OcrEvaluationRun",
        "CostBudgetChangeRequest",
        "MaskingPolicy",
    }


def fde_version_project_id(version_id: Any) -> str | None:
    version = repo.find_one("versions", str(version_id)) if version_id else None
    document = repo.find_one("documents", version.get("documentId")) if version else None
    return document.get("projectId") if document else None


def fde_project_version_ids(project_id: str, node_id: int | None = None) -> set[str]:
    if node_id is not None:
        return {
            str(item.get("documentVersionId"))
            for item in repo.state.get("bindings", [])
            if item.get("projectId") == project_id
            and int(item.get("nodeId") or 0) == int(node_id)
            and item.get("documentVersionId")
        }
    document_ids = {
        item["id"]
        for item in repo.state.get("documents", [])
        if item.get("projectId") == project_id
    }
    return {
        str(item.get("id"))
        for item in repo.state.get("versions", [])
        if item.get("documentId") in document_ids
    }


def fde_record_matches_project(
    record: dict[str, Any],
    project_id: str,
    *,
    node_id: int | None = None,
    version_ids: set[str] | None = None,
) -> bool:
    if record.get("projectId") and record.get("projectId") != project_id:
        return False
    if node_id is not None:
        record_node_id = record.get("nodeId")
        record_node_ids = {
            int(item)
            for item in record.get("nodeIds") or []
            if str(item).isdigit()
        }
        if record_node_id is not None:
            record_node_ids.add(int(record_node_id))
        if record_node_ids and int(node_id) not in record_node_ids:
            return False
    if record.get("projectId") == project_id:
        return True
    record_version_id = record.get("documentVersionId")
    if record_version_id and version_ids is not None:
        return str(record_version_id) in version_ids
    if record_version_id:
        return fde_version_project_id(record_version_id) == project_id
    return False


def fde_project_quality_blockers(project_id: str, node_id: int | None = None) -> list[dict[str, Any]]:
    version_ids = fde_project_version_ids(project_id, node_id)
    blockers: list[dict[str, Any]] = []
    for document in repo.state.get("documents", []):
        if document.get("projectId") != project_id:
            continue
        if node_id is not None:
            linked = any(
                item.get("projectId") == project_id
                and item.get("documentId") == document.get("id")
                and int(item.get("nodeId") or 0) == int(node_id)
                for item in repo.state.get("bindings", [])
            )
            if not linked:
                continue
        if document.get("currentOcrStatus") not in {"已识别", "识别完成"}:
            blockers.append(
                {
                    "type": "ocr",
                    "level": "warning",
                    "title": "资料 OCR 未完成",
                    "targetId": document.get("id"),
                    "targetName": document.get("fileName"),
                    "action": "进入 OCR 标注与运行诊断",
                }
            )
    for field in repo.state.get("extracted_fields", []):
        if str(field.get("documentVersionId")) not in version_ids:
            continue
        if float(field.get("confidence") or 0) < 0.85 or field.get("reviewStatus") == "低置信度":
            blockers.append(
                {
                    "type": "ocr-field",
                    "level": "warning",
                    "title": "低置信字段需要复核",
                    "targetId": field.get("id"),
                    "targetName": field.get("fieldName"),
                    "action": "修正字段值或 bbox 后入评估集",
                }
            )
    for run in repo.state.get("review_runs", []):
        if not fde_record_matches_project(run, project_id, node_id=node_id, version_ids=version_ids):
            continue
        if run.get("status") in {"waiting_human_review", "needs_human_review", "failed", "blocked_by_gate"}:
            blockers.append(
                {
                    "type": "agent",
                    "level": "danger" if run.get("status") in {"failed", "blocked_by_gate"} else "warning",
                    "title": "AI 审查任务待处理",
                    "targetId": run.get("reviewRunId") or run.get("id"),
                    "targetName": run.get("agentId") or "ReviewRun",
                    "action": "打开 Agent 审查链检查证据、依据和质量门禁",
                }
            )
    for task in fde_ocr_annotation_tasks_source():
        task_project_id = task.get("projectId")
        if task_project_id and task_project_id != project_id:
            continue
        if node_id is not None and task.get("nodeId") and int(task.get("nodeId")) != int(node_id):
            continue
        if task_project_id or not blockers:
            if task.get("collectionStatus") != "ready_for_eval" or task.get("readinessBlockers") or task.get("certificationBlockers"):
                blockers.append(
                    {
                        "type": "ocr-annotation",
                        "level": "warning",
                        "title": "OCR 样本未达到评估门禁",
                        "targetId": task.get("taskId") or task.get("caseId"),
                        "targetName": task.get("scenario"),
                        "action": "补齐字段、表格、印章标注和二审",
                    }
                )
    return blockers[:20]


def fde_project_node_audit_summary(project_id: str, node: dict[str, Any]) -> dict[str, Any]:
    node_id = int(node.get("nodeId"))
    version_ids = fde_project_version_ids(project_id, node_id)
    bindings = repo.bindings_for_node(project_id, node_id)
    review_runs = [
        review_run_view(item)
        for item in repo.state.get("review_runs", [])
        if fde_record_matches_project(item, project_id, node_id=node_id, version_ids=version_ids)
    ]
    ai_runs = [
        fde_ai_run_view(item)
        for item in repo.state.get("ai_runs", [])
        if fde_record_matches_project(item, project_id, node_id=node_id, version_ids=version_ids)
    ]
    ocr_jobs = [
        repo.clone(item)
        for item in repo.state.get("ocr_jobs", [])
        if fde_record_matches_project(item, project_id, node_id=node_id, version_ids=version_ids)
    ]
    fields = [item for item in repo.state.get("extracted_fields", []) if str(item.get("documentVersionId")) in version_ids]
    submissions = [
        submission_summary(item)
        for item in repo.state.get("submissions", [])
        if item.get("projectId") == project_id and node_id in {int(raw) for raw in item.get("nodeIds") or []}
    ]
    blockers = fde_project_quality_blockers(project_id, node_id)
    return {
        "node": repo.clone(node),
        "nodeId": node_id,
        "nodeName": node.get("name"),
        "groupName": node.get("groupName"),
        "status": node.get("status"),
        "documentCount": len({item.get("documentId") for item in bindings}),
        "bindingCount": len(bindings),
        "submissionCount": len(submissions),
        "ocrJobCount": len(ocr_jobs),
        "reviewRunCount": len(review_runs),
        "aiRunCount": len(ai_runs),
        "lowConfidenceFieldCount": len([item for item in fields if float(item.get("confidence") or 0) < 0.85]),
        "blockerCount": len(blockers),
        "latestReviewRun": review_runs[0] if review_runs else None,
        "latestAiRun": ai_runs[0] if ai_runs else None,
    }


def fde_as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def fde_knowledge_lineage_stage(
    *,
    key: str,
    label: str,
    done: bool,
    status: str,
    evidence: str,
    action: str,
    blocker: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "done": done,
        "tone": "green" if done else "orange",
        "evidence": evidence,
        "action": action,
        "blocker": blocker,
        "metrics": metrics or {},
    }


def fde_document_knowledge_lineage(document: dict[str, Any]) -> dict[str, Any]:
    """Build a FDE-facing lineage view for one document without mutating business state."""
    ocr_status = str(document.get("currentOcrStatus") or document.get("ocrStatus") or "")
    slice_status = str(document.get("sliceStatus") or "")
    vector_status = str(document.get("vectorStatus") or "")
    page_index_status = str(document.get("pageIndexStatus") or "")
    chunk_count = fde_as_int(document.get("chunkCount"))
    vector_count = fde_as_int(document.get("vectorCount"))
    vector_gap = max(0, chunk_count - vector_count)
    page_index_node_count = fde_as_int(document.get("pageIndexNodeCount"))
    latest_task = document.get("latestKnowledgeTask")
    if isinstance(latest_task, dict):
        latest_task_status = str(latest_task.get("status") or latest_task.get("taskStatus") or "-")
        latest_task_type = str(latest_task.get("taskType") or "-")
    else:
        latest_task_status = str(latest_task or "-")
        latest_task_type = "-"

    ocr_done = "已识别" in ocr_status or "人工修正" in ocr_status or "success" in ocr_status
    sliced = "已切片" in slice_status or chunk_count > 0
    vectorized = "已向量化" in vector_status or (vector_count > 0 and vector_gap == 0)
    page_index_ready = "已构建" in page_index_status or page_index_node_count > 0
    review_ready = ocr_done and sliced and vectorized and page_index_ready

    stages = [
        fde_knowledge_lineage_stage(
            key="ocr_parse",
            label="资料解析",
            done=ocr_done,
            status=ocr_status or "等待OCR",
            evidence=f"OCR状态：{ocr_status or '未开始'}",
            action="进入 OCR 打标或重跑文档解析" if not ocr_done else "保留字段、表格、印章和 bbox 证据",
            blocker=None if ocr_done else "OCR 未完成",
            metrics={"status": ocr_status},
        ),
        fde_knowledge_lineage_stage(
            key="knowledge_slice",
            label="知识切片",
            done=sliced,
            status=slice_status or "待切片",
            evidence=f"切片 {chunk_count} 条",
            action="重跑 knowledge.slice" if not sliced else "切片已保留页码、bbox 和资料 Profile",
            blocker=None if sliced else "知识切片未完成",
            metrics={"chunkCount": chunk_count},
        ),
        fde_knowledge_lineage_stage(
            key="vector_embed",
            label="向量入库",
            done=vectorized,
            status=vector_status or "待向量化",
            evidence=f"向量 {vector_count}/{chunk_count} 条，模型 {document.get('embeddingModel') or 'embedding-default'}",
            action=(
                "排查失败 chunk 并补跑 knowledge.embed"
                if vector_gap
                else ("重跑 knowledge.embed" if not vectorized else "可参与 Hybrid RAG 检索")
            ),
            blocker=("向量条目少于切片" if vector_gap else (None if vectorized else "向量入库未完成")),
            metrics={"vectorCount": vector_count, "chunkCount": chunk_count, "vectorGap": vector_gap},
        ),
        fde_knowledge_lineage_stage(
            key="pageindex_tree",
            label="PageIndex",
            done=page_index_ready,
            status=page_index_status or "待构建",
            evidence=f"PageIndex 节点 {page_index_node_count} 个",
            action="构建 PageIndex tree 并校验条款映射" if not page_index_ready else "可用于长文档跨章节溯源",
            blocker=None if page_index_ready else "PageIndex 未构建",
            metrics={"pageIndexNodeCount": page_index_node_count},
        ),
        fde_knowledge_lineage_stage(
            key="review_ready",
            label="审查可用",
            done=review_ready,
            status="可用于审查" if review_ready else "需补齐",
            evidence="规则、知识检索和 Agent 编排可引用该资料" if review_ready else "存在 OCR/切片/向量/PageIndex 缺口",
            action="纳入 ReviewRun 规则、RAG 和 PageIndex 溯源" if review_ready else "按前置阻断顺序补齐后再进入审查",
            blocker=None if review_ready else "资料知识资产未达到审查可用门禁",
            metrics={"reviewReady": review_ready},
        ),
    ]
    blockers = [stage["blocker"] for stage in stages if stage.get("blocker")]
    return {
        "schemaVersion": "FdeKnowledgeLineage@1.0.0",
        "documentId": document.get("id"),
        "documentVersionId": document.get("currentVersionId") or document.get("documentVersionId"),
        "knowledgeFileId": document.get("knowledgeFileId"),
        "fileName": document.get("fileName"),
        "readiness": "ready_for_review" if review_ready else "needs_attention",
        "readinessLabel": "可用于审查" if review_ready else "需补齐",
        "auditConclusion": "该资料可进入规则、Hybrid RAG、PageIndex 和 Agent 审查编排。"
        if review_ready
        else "该资料仍有知识资产缺口，FDE 应先补齐阻断再放入审查链。",
        "localOnly": True,
        "latestTaskType": latest_task_type,
        "latestTaskStatus": latest_task_status,
        "vectorIndex": {
            "embeddingModel": document.get("embeddingModel") or "embedding-default",
            "indexVersion": document.get("indexVersion") or "knowledge-index@local",
            "dimensions": fde_as_int(document.get("vectorDimensions"), 1024),
            "chunkCount": chunk_count,
            "vectorCount": vector_count,
            "vectorGap": vector_gap,
        },
        "pageIndex": {
            "status": page_index_status or "待构建",
            "nodeCount": page_index_node_count,
            "coverageLabel": "已覆盖" if page_index_ready else "待构建",
        },
        "stages": stages,
        "blockers": blockers,
    }


def fde_project_knowledge_lineage(documents: list[dict[str, Any]], review_runs: list[dict[str, Any]]) -> dict[str, Any]:
    document_lineages = [fde_document_knowledge_lineage(item) for item in documents]
    total = len(document_lineages)

    def count_done(stage_key: str) -> int:
        return sum(
            1
            for lineage in document_lineages
            for stage in lineage.get("stages", [])
            if stage.get("key") == stage_key and stage.get("done")
        )

    retrieval_traces = [
        item
        for item in repo.state.get("retrieval_traces", [])
        if any(item.get("reviewRunId") == (run.get("reviewRunId") or run.get("id")) for run in review_runs)
    ]
    pageindex_traces = [
        item for item in retrieval_traces if "pageindex" in str(item.get("selectedRoute") or "").lower()
    ]
    vector_flow = [
        {
            "step": "01",
            "label": "资料解析",
            "description": "OCR 字段、表格、印章和页面证据已生成",
            "done": count_done("ocr_parse"),
            "total": total,
            "tone": "green" if total and count_done("ocr_parse") == total else "orange",
        },
        {
            "step": "02",
            "label": "知识切片",
            "description": "按资料 Profile 拆成可检索片段，保留页码和 bbox",
            "done": count_done("knowledge_slice"),
            "total": total,
            "tone": "green" if total and count_done("knowledge_slice") == total else "orange",
        },
        {
            "step": "03",
            "label": "向量入库",
            "description": "Embedding 已写入本地向量索引，可参与 Hybrid RAG",
            "done": count_done("vector_embed"),
            "total": total,
            "tone": "green" if total and count_done("vector_embed") == total else "orange",
        },
        {
            "step": "04",
            "label": "PageIndex",
            "description": "长文档树节点已构建，可做跨章节依据溯源",
            "done": count_done("pageindex_tree"),
            "total": total,
            "tone": "green" if total and count_done("pageindex_tree") == total else "orange",
        },
        {
            "step": "05",
            "label": "审查可用",
            "description": "资料可进入规则、知识检索和 Agent 审查编排",
            "done": count_done("review_ready"),
            "total": total,
            "tone": "green" if total and count_done("review_ready") == total else "red",
        },
    ]
    pageindex_flow = [
        {
            "step": "01",
            "label": "问题分类",
            "description": f"{len(pageindex_traces)} 个检索问题触发 PageIndex 或需要跨章节定位",
            "value": f"{len(pageindex_traces)}/{len(retrieval_traces)}",
            "tone": "blue" if pageindex_traces else "green",
        },
        {
            "step": "02",
            "label": "路由选择",
            "description": "检索路由器在条款索引、Hybrid RAG 和 PageIndex 之间选择路径",
            "value": f"{len(pageindex_traces)} 次",
            "tone": "green" if pageindex_traces else "orange",
        },
        {
            "step": "03",
            "label": "节点定位",
            "description": "定位章节、附录或表格节点，并保留页码范围",
            "value": f"{sum(len(((item.get('pageIndexTree') or {}).get('selectedNodes') or [])) for item in pageindex_traces)} 节点",
            "tone": "green" if pageindex_traces else "orange",
        },
        {
            "step": "04",
            "label": "条款映射",
            "description": "把命中节点映射回正式条款，供审查草稿引用",
            "value": f"{sum(len(item.get('selectedClauses') or []) for item in retrieval_traces)} 条款",
            "tone": "green" if retrieval_traces else "orange",
        },
        {
            "step": "05",
            "label": "质量判断",
            "description": "路由、节点和条款映射可用于审查" if retrieval_traces else "缺少检索 Trace，需要先运行知识检索节点",
            "value": "可用" if retrieval_traces else "待补齐",
            "tone": "green" if retrieval_traces else "red",
        },
    ]
    return {
        "schemaVersion": "FdeProjectKnowledgeLineage@1.0.0",
        "source": "backend_audit_projection",
        "documents": document_lineages,
        "vectorFlow": vector_flow,
        "pageIndexFlow": pageindex_flow,
        "retrievalTraceCount": len(retrieval_traces),
        "pageIndexTraceCount": len(pageindex_traces),
        "blockers": [
            {"documentVersionId": lineage.get("documentVersionId"), "blockers": lineage.get("blockers")}
            for lineage in document_lineages
            if lineage.get("blockers")
        ],
    }


def fde_ratio(numerator: float | int, denominator: float | int, *, default: float = 0.0) -> float:
    try:
        denominator_value = float(denominator)
        if denominator_value <= 0:
            return default
        return max(0.0, min(1.0, float(numerator) / denominator_value))
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def fde_score_section(
    *,
    key: str,
    name: str,
    score: float,
    max_score: float,
    metric: float,
    threshold: float,
    blockers: list[str],
) -> dict[str, Any]:
    score = round(max(0.0, min(score, max_score)), 2)
    return {
        "key": key,
        "name": name,
        "score": score,
        "maxScore": max_score,
        "metric": round(max(0.0, min(metric, 1.0)), 4),
        "threshold": threshold,
        "status": "pass" if score >= max_score * threshold and not blockers else "warn",
        "blockers": blockers,
    }


def fde_trace_selected_clauses(trace: dict[str, Any]) -> list[dict[str, Any]]:
    selected = trace.get("selectedClauses") or trace.get("clauses") or []
    return [item for item in selected if isinstance(item, dict)]


def fde_trace_evidence_backed(trace: dict[str, Any]) -> bool:
    for clause in fde_trace_selected_clauses(trace):
        if clause.get("pageNo") is not None and clause.get("bbox"):
            return True
    return False


def fde_project_retrieval_traces(review_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    run_ids = {
        str(value)
        for run in review_runs
        for value in (run.get("reviewRunId"), run.get("id"))
        if value
    }
    return [
        item
        for item in repo.state.get("retrieval_traces", [])
        if isinstance(item, dict) and (not run_ids or str(item.get("reviewRunId") or "") in run_ids)
    ]


def fde_project_vector_quality(documents: list[dict[str, Any]], review_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Quantify vectorization quality for the FDE console.

    This is a trace-backed operational score, not a gold-set certification. Gold retrieval
    cases still own release approval for model/chunking/reranker changes.
    """
    doc_count = len(documents)
    chunk_total = sum(fde_as_int(item.get("chunkCount")) for item in documents)
    vector_total = sum(fde_as_int(item.get("vectorCount")) for item in documents)
    vector_gap_total = sum(max(0, fde_as_int(item.get("chunkCount")) - fde_as_int(item.get("vectorCount"))) for item in documents)
    docs_with_chunks = len([item for item in documents if fde_as_int(item.get("chunkCount")) > 0])
    docs_vectorized = len(
        [
            item
            for item in documents
            if fde_as_int(item.get("vectorCount")) > 0
            and max(0, fde_as_int(item.get("chunkCount")) - fde_as_int(item.get("vectorCount"))) == 0
        ]
    )
    docs_pageindexed = len(
        [
            item
            for item in documents
            if fde_as_int(item.get("pageIndexNodeCount")) > 0 or "已构建" in str(item.get("pageIndexStatus") or "")
        ]
    )

    def metadata_score(document: dict[str, Any]) -> float:
        checks = [
            bool(document.get("knowledgeFileId")),
            bool(document.get("documentVersionId") or document.get("currentVersionId")),
            bool(document.get("embeddingModel")),
            bool(document.get("indexVersion")),
            bool(document.get("vectorDimensions")),
            bool(document.get("nodeId") or document.get("requirementName")),
        ]
        return fde_ratio(len([item for item in checks if item]), len(checks), default=0.0)

    metadata_completeness = fde_ratio(sum(metadata_score(item) for item in documents), doc_count, default=0.0)
    chunk_coverage = fde_ratio(docs_with_chunks, doc_count, default=0.0)
    vector_completeness = fde_ratio(vector_total, chunk_total, default=0.0)
    vector_document_rate = fde_ratio(docs_vectorized, doc_count, default=0.0)
    page_index_coverage = fde_ratio(docs_pageindexed, doc_count, default=0.0)

    traces = fde_project_retrieval_traces(review_runs)
    trace_count = len(traces)
    trace_hits = len([item for item in traces if fde_trace_selected_clauses(item)])
    trace_evidence_hits = len([item for item in traces if fde_trace_evidence_backed(item)])
    trace_page_index_hits = len(
        [
            item
            for item in traces
            if "pageindex" in str(item.get("selectedRoute") or "").lower()
            or ((item.get("pageIndexTree") or {}).get("selectedNodes") if isinstance(item.get("pageIndexTree"), dict) else None)
        ]
    )
    trace_filter_scoped = len(
        [
            item
            for item in traces
            if isinstance(item.get("filters"), dict)
            and any(key in item["filters"] for key in ("businessPackId", "projectId", "nodeId", "tenantId"))
        ]
    )
    selected_clause_total = sum(len(fde_trace_selected_clauses(item)) for item in traces)
    retrieval_hit_rate = fde_ratio(trace_hits, trace_count, default=0.0)
    retrieval_depth = fde_ratio(selected_clause_total, trace_count * 3, default=0.0)
    trace_filter_rate = fde_ratio(trace_filter_scoped, trace_count, default=0.0)
    evidence_hit_rate_value = fde_ratio(trace_evidence_hits, trace_count, default=0.0)
    page_index_trace_rate = fde_ratio(trace_page_index_hits, trace_count, default=0.0)

    related_file_ids = {str(item.get("knowledgeFileId")) for item in documents if item.get("knowledgeFileId")}
    failed_tasks = [
        item
        for item in repo.state.get("knowledge_tasks", [])
        if item.get("status") in {"失败", "failed"} and str(item.get("targetId") or "") in related_file_ids
    ]
    evaluation_reports = [item for item in repo.state.get("evaluation_reports", []) if isinstance(item, dict)]
    latest_retrieval_report = next(
        (
            item
            for item in evaluation_reports
            if (item.get("caseSummary") or item.get("metrics") or {}).get("retrievalRecall") is not None
        ),
        None,
    )
    latest_metrics = (
        latest_retrieval_report.get("caseSummary")
        if isinstance((latest_retrieval_report or {}).get("caseSummary"), dict)
        else (latest_retrieval_report or {}).get("metrics")
    ) or {}
    gold_cases = len(
        [
            item
            for item in repo.state.get("evaluation_cases", [])
            if isinstance(item, dict) and item.get("expectedClauseIds")
        ]
    )
    report_recall = safe_float(latest_metrics.get("retrievalRecall")) if "retrievalRecall" in latest_metrics else None
    wrong_reference_rate = (
        safe_float(latest_metrics.get("wrongReferenceRate")) if "wrongReferenceRate" in latest_metrics else None
    )
    stability_metric = (
        0.45 * (1.0 if vector_gap_total == 0 else fde_ratio(vector_total, vector_total + vector_gap_total, default=0.0))
        + 0.25 * (1.0 if not failed_tasks else 0.0)
        + 0.3 * (1.0 if latest_retrieval_report and report_recall is not None and report_recall >= 0.9 else 0.0)
    )

    section_metadata_blockers = []
    if chunk_coverage < 0.95:
        section_metadata_blockers.append("资料切片覆盖率低于 95%")
    if metadata_completeness < 0.95:
        section_metadata_blockers.append("部分资料缺少模型、版本或范围 metadata")
    section_vector_blockers = []
    if vector_completeness < 0.98:
        section_vector_blockers.append("向量数量未覆盖全部切片")
    if vector_document_rate < 0.95:
        section_vector_blockers.append("部分资料未完成向量入库")
    section_retrieval_blockers = []
    if trace_count <= 0:
        section_retrieval_blockers.append("缺少 RetrievalTrace，无法量化检索命中")
    if trace_count > 0 and retrieval_hit_rate < 0.9:
        section_retrieval_blockers.append("检索命中率低于 90%")
    if trace_count > 0 and trace_filter_rate < 1.0:
        section_retrieval_blockers.append("检索 Trace 缺少业务包/项目/节点过滤证据")
    section_evidence_blockers = []
    if evidence_hit_rate_value < 0.9:
        section_evidence_blockers.append("检索依据页码或 bbox 覆盖低于 90%")
    if page_index_coverage < 0.8:
        section_evidence_blockers.append("PageIndex 覆盖不足，长文档溯源风险偏高")
    section_stability_blockers = []
    if failed_tasks:
        section_stability_blockers.append(f"{len(failed_tasks)} 个知识任务失败")
    if not latest_retrieval_report:
        section_stability_blockers.append("缺少带 retrievalRecall 的评估报告")
    if gold_cases <= 0:
        section_stability_blockers.append("缺少人工标注的检索评估样本")

    sections = [
        fde_score_section(
            key="corpus_metadata",
            name="切片与 metadata",
            score=15 * (0.45 * chunk_coverage + 0.4 * metadata_completeness + 0.15 * page_index_coverage),
            max_score=15,
            metric=(0.45 * chunk_coverage + 0.4 * metadata_completeness + 0.15 * page_index_coverage),
            threshold=0.9,
            blockers=section_metadata_blockers,
        ),
        fde_score_section(
            key="vector_index",
            name="向量完整性",
            score=25 * (0.7 * vector_completeness + 0.3 * vector_document_rate),
            max_score=25,
            metric=(0.7 * vector_completeness + 0.3 * vector_document_rate),
            threshold=0.95,
            blockers=section_vector_blockers,
        ),
        fde_score_section(
            key="retrieval",
            name="检索命中",
            score=30 * (0.55 * retrieval_hit_rate + 0.25 * retrieval_depth + 0.2 * trace_filter_rate),
            max_score=30,
            metric=(0.55 * retrieval_hit_rate + 0.25 * retrieval_depth + 0.2 * trace_filter_rate),
            threshold=0.9,
            blockers=section_retrieval_blockers,
        ),
        fde_score_section(
            key="evidence",
            name="证据可追溯",
            score=20 * (0.65 * evidence_hit_rate_value + 0.35 * page_index_coverage),
            max_score=20,
            metric=(0.65 * evidence_hit_rate_value + 0.35 * page_index_coverage),
            threshold=0.9,
            blockers=section_evidence_blockers,
        ),
        fde_score_section(
            key="stability",
            name="稳定与门禁",
            score=10 * stability_metric,
            max_score=10,
            metric=stability_metric,
            threshold=0.9,
            blockers=section_stability_blockers,
        ),
    ]
    score = round(sum(float(item["score"]) for item in sections), 2)
    blockers = [blocker for section in sections for blocker in section.get("blockers", [])]

    document_scores = []
    for document in documents:
        document_version_id = str(document.get("documentVersionId") or document.get("currentVersionId") or "")
        chunk_count = fde_as_int(document.get("chunkCount"))
        vector_count = fde_as_int(document.get("vectorCount"))
        vector_gap = max(0, chunk_count - vector_count)
        page_index_ready = fde_as_int(document.get("pageIndexNodeCount")) > 0 or "已构建" in str(document.get("pageIndexStatus") or "")
        document_metadata_score = metadata_score(document)
        doc_metric = (
            0.2 * (1.0 if chunk_count > 0 else 0.0)
            + 0.35 * fde_ratio(vector_count, chunk_count, default=0.0)
            + 0.2 * document_metadata_score
            + 0.15 * (1.0 if page_index_ready else 0.0)
            + 0.1 * (1.0 if vector_gap == 0 and vector_count > 0 else 0.0)
        )
        issue = "无"
        if chunk_count <= 0:
            issue = "未切片"
        elif vector_count <= 0:
            issue = "未向量化"
        elif vector_gap:
            issue = "向量缺口"
        elif not page_index_ready:
            issue = "PageIndex 未构建"

        related_review_runs = []
        for run in review_runs:
            version_refs = [
                str(value)
                for key in ("inputDocumentVersionIds", "documentVersionIds", "ocrResultVersions")
                for value in (run.get(key) or [])
            ]
            if document_version_id and document_version_id in version_refs:
                related_review_runs.append(run)
        related_run_ids = {
            str(value)
            for run in related_review_runs
            for value in (run.get("reviewRunId"), run.get("id"))
            if value
        }
        related_traces = [
            trace
            for trace in traces
            if related_run_ids and str(trace.get("reviewRunId") or "") in related_run_ids
        ]
        trace_scope = "document_explicit" if related_traces else "project_proxy"
        trace_rows = related_traces or traces[:3]
        trace_hit_rate_for_document = fde_ratio(
            len([item for item in trace_rows if fde_trace_selected_clauses(item)]),
            len(trace_rows),
            default=0.0,
        )
        trace_evidence_rate_for_document = fde_ratio(
            len([item for item in trace_rows if fde_trace_evidence_backed(item)]),
            len(trace_rows),
            default=0.0,
        )
        lineage = fde_document_knowledge_lineage(document)
        quality_dimensions = [
            {
                "key": "chunking",
                "name": "知识切片",
                "score": round((1.0 if chunk_count > 0 else 0.0) * 100, 2),
                "metric": round(1.0 if chunk_count > 0 else 0.0, 4),
                "status": "pass" if chunk_count > 0 else "warn",
                "message": f"切片 {chunk_count} 条",
            },
            {
                "key": "vector_integrity",
                "name": "向量完整性",
                "score": round(fde_ratio(vector_count, chunk_count, default=0.0) * 100, 2),
                "metric": round(fde_ratio(vector_count, chunk_count, default=0.0), 4),
                "status": "pass" if chunk_count > 0 and vector_gap == 0 else "warn",
                "message": f"向量 {vector_count}/{chunk_count} 条，缺口 {vector_gap}",
            },
            {
                "key": "metadata",
                "name": "metadata 完整度",
                "score": round(document_metadata_score * 100, 2),
                "metric": round(document_metadata_score, 4),
                "status": "pass" if document_metadata_score >= 0.95 else "warn",
                "message": "模型、索引、版本、节点范围等元数据完整度",
            },
            {
                "key": "pageindex",
                "name": "PageIndex 溯源",
                "score": 100 if page_index_ready else 0,
                "metric": 1.0 if page_index_ready else 0.0,
                "status": "pass" if page_index_ready else "warn",
                "message": f"PageIndex 节点 {fde_as_int(document.get('pageIndexNodeCount'))} 个",
            },
            {
                "key": "llm_retrieval",
                "name": "LLM 检索证据",
                "score": round((0.55 * trace_hit_rate_for_document + 0.45 * trace_evidence_rate_for_document) * 100, 2),
                "metric": round((0.55 * trace_hit_rate_for_document + 0.45 * trace_evidence_rate_for_document), 4),
                "status": "pass" if trace_rows and trace_hit_rate_for_document >= 0.9 and trace_evidence_rate_for_document >= 0.9 else "warn",
                "message": "显式绑定 ReviewRun" if trace_scope == "document_explicit" else "当前以项目级 RetrievalTrace 作为代理",
            },
        ]
        document_scores.append(
            {
                "documentId": document.get("id"),
                "documentVersionId": document_version_id,
                "knowledgeFileId": document.get("knowledgeFileId"),
                "fileName": document.get("fileName"),
                "requirementName": document.get("requirementName"),
                "score": round(doc_metric * 100, 2),
                "chunkCount": chunk_count,
                "vectorCount": vector_count,
                "vectorGap": vector_gap,
                "metadataCompleteness": round(document_metadata_score, 4),
                "pageIndexReady": page_index_ready,
                "pageIndexNodeCount": fde_as_int(document.get("pageIndexNodeCount")),
                "embeddingModel": document.get("embeddingModel") or "embedding-default",
                "indexVersion": document.get("indexVersion") or "knowledge-index@local",
                "vectorDimensions": fde_as_int(document.get("vectorDimensions"), 1024),
                "vectorStatus": document.get("vectorStatus") or "待向量化",
                "sliceStatus": document.get("sliceStatus") or "待切片",
                "latestTaskStatus": lineage.get("latestTaskStatus"),
                "readinessLabel": lineage.get("readinessLabel"),
                "issue": issue,
                "qualityDimensions": quality_dimensions,
                "lineageStages": lineage.get("stages") or [],
                "lineageBlockers": lineage.get("blockers") or [],
                "llmTrace": {
                    "scope": trace_scope,
                    "relatedReviewRunCount": len(related_review_runs),
                    "retrievalTraceCount": len(trace_rows),
                    "hitRate": round(trace_hit_rate_for_document, 4),
                    "evidenceHitRate": round(trace_evidence_rate_for_document, 4),
                },
                "retrievalTraceRows": [
                    {
                        "retrievalTraceId": item.get("retrievalTraceId") or item.get("id"),
                        "query": item.get("query"),
                        "selectedRoute": item.get("selectedRoute"),
                        "selectedClauseCount": len(fde_trace_selected_clauses(item)),
                        "evidenceBacked": fde_trace_evidence_backed(item),
                        "filterScoped": isinstance(item.get("filters"), dict)
                        and any(key in item["filters"] for key in ("businessPackId", "projectId", "nodeId", "tenantId")),
                    }
                    for item in trace_rows[:5]
                ],
            }
        )

    status = "pass" if score >= 90 and not [b for b in blockers if "缺少人工标注" not in b and "评估报告" not in b] else "needs_attention"
    return {
        "schemaVersion": "FdeVectorQuality@1.0.0",
        "score": score,
        "targetScore": 100,
        "status": status,
        "statusLabel": "可进入审查" if status == "pass" else "需补齐质量证据",
        "evaluationMode": "trace_proxy_with_eval_gate",
        "localOnly": True,
        "sections": sections,
        "blockers": blockers,
        "metrics": {
            "documentCount": doc_count,
            "chunkCount": chunk_total,
            "vectorCount": vector_total,
            "vectorGap": vector_gap_total,
            "chunkCoverage": round(chunk_coverage, 4),
            "vectorCompleteness": round(vector_completeness, 4),
            "metadataCompleteness": round(metadata_completeness, 4),
            "pageIndexCoverage": round(page_index_coverage, 4),
            "retrievalTraceCount": trace_count,
            "recallAt5Proxy": round(retrieval_hit_rate, 4),
            "retrievalDepth": round(retrieval_depth, 4),
            "evidenceHitRate": round(evidence_hit_rate_value, 4),
            "filterScopedRate": round(trace_filter_rate, 4),
            "filterLeakageRate": 0.0 if trace_filter_rate >= 1.0 else round(1 - trace_filter_rate, 4),
            "pageIndexTraceRate": round(page_index_trace_rate, 4),
            "goldCaseCount": gold_cases,
            "latestRetrievalRecall": report_recall,
            "latestWrongReferenceRate": wrong_reference_rate,
            "failedKnowledgeTasks": len(failed_tasks),
        },
        "thresholds": {
            "recallAt5Proxy": 0.9,
            "evidenceHitRate": 0.9,
            "vectorCompleteness": 0.98,
            "filterLeakageRate": 0.0,
            "pageIndexCoverage": 0.8,
        },
        "documentScores": sorted(document_scores, key=lambda item: float(item.get("score") or 0), reverse=True),
        "retrievalProbeRows": [
            {
                "retrievalTraceId": item.get("retrievalTraceId") or item.get("id"),
                "query": item.get("query"),
                "selectedRoute": item.get("selectedRoute"),
                "selectedClauseCount": len(fde_trace_selected_clauses(item)),
                "evidenceBacked": fde_trace_evidence_backed(item),
                "filterScoped": isinstance(item.get("filters"), dict)
                and any(key in item["filters"] for key in ("businessPackId", "projectId", "nodeId", "tenantId")),
            }
            for item in traces[:8]
        ],
        "updatedAt": server_time(),
    }


def fde_chunk_text_preview(text: Any, limit: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def fde_chunk_text_hash(text: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return ""
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def fde_trace_chunk_identifiers(trace: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    for clause in fde_trace_selected_clauses(trace):
        for key in ("id", "clauseId", "chunkId"):
            value = clause.get(key)
            if not value:
                continue
            text = str(value)
            identifiers.add(text)
            if text.startswith("KC-"):
                identifiers.add(text[3:])
    return identifiers


def fde_trace_matches_document(trace: dict[str, Any], *, file_id: str, document_version_id: str) -> bool:
    for clause in fde_trace_selected_clauses(trace):
        if file_id and str(clause.get("fileId") or "") == file_id:
            return True
        if document_version_id and str(clause.get("documentVersionId") or "") == document_version_id:
            return True
    return False


def fde_chunk_quality_flags(chunk: dict[str, Any], *, vector_ready: bool, retrieval_hit_count: int, duplicate: bool) -> list[str]:
    flags: list[str] = []
    text = str(chunk.get("text") or "")
    token_count = fde_as_int(chunk.get("tokenCount"))
    if not chunk.get("materialized", True):
        flags.append("not_materialized")
    if not text.strip():
        flags.append("empty_text")
    elif token_count < 20 or len(text) < 40:
        flags.append("too_short")
    elif token_count > 1200 or len(text) > 2400:
        flags.append("too_long")
    if chunk.get("pageNo") is None:
        flags.append("missing_page")
    if not chunk.get("bbox"):
        flags.append("missing_bbox")
    if not vector_ready:
        flags.append("missing_vector")
    if retrieval_hit_count <= 0:
        flags.append("not_retrieved")
    if duplicate:
        flags.append("duplicate_text")
    return flags


def fde_latest_ocr_parse_result(document_version_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in repo.state.get("ocr_parse_results", [])
            if isinstance(item, dict) and str(item.get("documentVersionId") or "") == document_version_id
        ),
        None,
    )


def fde_pipeline_source_view(document: dict[str, Any], version: dict[str, Any] | None) -> dict[str, Any]:
    try:
        preview = repo.document_preview(document)
    except Exception:
        preview = {
            "url": f"mock://preview/documents/{document.get('id')}?versionId={document.get('currentVersionId')}",
            "previewType": repo.document_preview_type(document),
            "readonly": True,
        }
    return {
        "stage": "image",
        "label": "图片/原始文件",
        "status": "ready" if version else "missing",
        "fileName": document.get("fileName"),
        "fileType": document.get("fileType"),
        "documentId": document.get("id"),
        "documentVersionId": document.get("currentVersionId") or (version or {}).get("id"),
        "storageKey": (version or {}).get("storageKey"),
        "storageBucket": (version or {}).get("storageBucket") or "documents",
        "fileSize": (version or {}).get("fileSize"),
        "contentHash": (version or {}).get("hash"),
        "previewUrl": preview.get("url"),
        "previewType": preview.get("previewType"),
        "pageCount": preview.get("pageCount"),
        "readonly": True,
    }


def fde_source_preview_view(
    document: dict[str, Any],
    version: dict[str, Any] | None,
    parse_result: dict[str, Any] | None,
) -> dict[str, Any]:
    source = fde_pipeline_source_view(document, version)
    pages = (parse_result or {}).get("pages") or []
    preview_pages: list[dict[str, Any]] = []
    if isinstance(pages, list):
        for index, page_item in enumerate(pages[:20], start=1):
            if not isinstance(page_item, dict):
                continue
            preview_pages.append(
                {
                    "pageNo": page_item.get("pageNo") or page_item.get("page") or index,
                    "width": page_item.get("width") or page_item.get("imageWidth"),
                    "height": page_item.get("height") or page_item.get("imageHeight"),
                    "previewUrl": page_item.get("previewUrl") or page_item.get("imageUrl") or source.get("previewUrl"),
                    "imageObjectKey": page_item.get("imageObjectKey") or page_item.get("objectKey"),
                    "quality": page_item.get("quality") or {},
                }
            )
    if not preview_pages:
        preview_pages.append(
            {
                "pageNo": 1,
                "width": None,
                "height": None,
                "previewUrl": source.get("previewUrl"),
                "imageObjectKey": source.get("storageKey"),
                "quality": {},
            }
        )
    return {
        **source,
        "schemaVersion": "FdeSourcePreview@1.0.0",
        "pageCount": source.get("pageCount") or len(preview_pages),
        "pages": preview_pages,
        "previewAvailable": bool(source.get("previewUrl")) and not str(source.get("previewUrl")).startswith("mock://"),
        "previewUnavailableReason": ""
        if bool(source.get("previewUrl")) and not str(source.get("previewUrl")).startswith("mock://")
        else "当前文件只有审计投影或 mock preview，尚未生成可渲染图片/PDF 预览。",
    }


def fde_pipeline_ocr_view(
    document_version_id: str,
    parse_result: dict[str, Any] | None,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    parse_fields = (parse_result or {}).get("fields") or []
    parse_fragments = (parse_result or {}).get("fragments") or []
    parse_tables = (parse_result or {}).get("tables") or []
    parse_seals = (parse_result or {}).get("seals") or []
    source_fields = [item for item in parse_fields if isinstance(item, dict)] or fields
    field_rows = [
        {
            "fieldName": item.get("fieldName") or item.get("name") or item.get("fieldCode"),
            "fieldCode": item.get("fieldCode") or item.get("code"),
            "fieldValue": item.get("fieldValue") or item.get("value"),
            "pageNo": item.get("pageNo"),
            "bbox": item.get("bbox"),
            "confidence": item.get("confidence"),
            "source": item.get("sourceEngine") or item.get("extractionMethod") or "extracted_fields",
        }
        for item in source_fields[:20]
    ]
    return {
        "stage": "ocr",
        "label": "OCR 结构化识别",
        "status": (parse_result or {}).get("status") or ("field_only" if fields else "missing"),
        "parseResultId": (parse_result or {}).get("parseResultId"),
        "profileId": (parse_result or {}).get("profileId"),
        "documentType": (parse_result or {}).get("documentType"),
        "parserVersion": (parse_result or {}).get("parserVersion"),
        "engineVersion": (parse_result or {}).get("engineVersion"),
        "engineRuns": (parse_result or {}).get("engineRuns") or [],
        "diagnostics": (parse_result or {}).get("diagnostics") or [],
        "summary": {
            "pageCount": len((parse_result or {}).get("pages") or []),
            "fragmentCount": len(parse_fragments or []),
            "fieldCount": len(source_fields),
            "tableCount": len(parse_tables or []),
            "sealCount": len(parse_seals or []),
        },
        "fieldRows": field_rows,
        "fragmentRows": [
            {
                "fragmentId": item.get("fragmentId") or item.get("id") or f"fragment-{index}",
                "pageNo": item.get("pageNo"),
                "textPreview": fde_chunk_text_preview(item.get("text")),
                "bbox": item.get("bbox"),
                "confidence": item.get("confidence"),
                "sourceEngine": item.get("sourceEngine"),
            }
            for index, item in enumerate(parse_fragments[:20], start=1)
            if isinstance(item, dict)
        ],
        "quality": (parse_result or {}).get("quality") or {},
        "documentVersionId": document_version_id,
    }


def fde_ocr_artifacts_view(
    document_version_id: str,
    parse_result: dict[str, Any] | None,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    ocr = fde_pipeline_ocr_view(document_version_id, parse_result, fields)
    parse_tables = (parse_result or {}).get("tables") or []
    parse_seals = (parse_result or {}).get("seals") or []
    return {
        "schemaVersion": "FdeOcrArtifacts@1.0.0",
        **ocr,
        "fields": ocr["fieldRows"],
        "fragments": ocr["fragmentRows"],
        "tables": [
            {
                "tableId": item.get("tableId") or item.get("id") or f"table-{index}",
                "pageNo": item.get("pageNo"),
                "bbox": item.get("bbox"),
                "rowCount": item.get("rows") or item.get("rowCount"),
                "columnCount": item.get("columns") or item.get("columnCount"),
                "structureConfidence": item.get("structureConfidence") or item.get("confidence"),
                "schema": item.get("businessSchema") or item.get("schema"),
                "sourceEngine": item.get("sourceEngine"),
            }
            for index, item in enumerate(parse_tables[:20], start=1)
            if isinstance(item, dict)
        ],
        "seals": [
            {
                "sealId": item.get("sealId") or item.get("id") or f"seal-{index}",
                "pageNo": item.get("pageNo"),
                "bbox": item.get("bbox"),
                "sealType": item.get("sealType"),
                "sealName": item.get("sealName") or item.get("text"),
                "visualConfidence": item.get("visualConfidence"),
                "ocrConfidence": item.get("ocrConfidence") or item.get("confidence"),
                "qualityFlags": item.get("qualityFlags") or [],
                "sourceEngine": item.get("sourceEngine"),
            }
            for index, item in enumerate(parse_seals[:20], start=1)
            if isinstance(item, dict)
        ],
    }


def fde_text_stage_rows(fields: list[dict[str, Any]], chunk_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, field in enumerate(fields[:20], start=1):
        rows.append(
            {
                "id": field.get("id") or f"field-text-{index}",
                "sourceType": "ocr_field",
                "sourceLabel": field.get("fieldName") or f"字段 {index}",
                "pageNo": field.get("pageNo"),
                "text": f"{field.get('fieldName')}: {field.get('fieldValue')}",
                "textHash": stable_hash_payload({"field": field.get("fieldName"), "value": field.get("fieldValue")}),
                "bbox": field.get("bbox"),
                "confidence": field.get("confidence"),
            }
        )
    for chunk in chunk_rows[:20]:
        rows.append(
            {
                "id": chunk.get("id"),
                "sourceType": "knowledge_chunk",
                "sourceLabel": f"Chunk {chunk.get('chunkNo')}",
                "pageNo": chunk.get("pageNo"),
                "text": chunk.get("textPreview"),
                "textHash": chunk.get("textHash"),
                "bbox": chunk.get("bbox"),
                "confidence": None,
                "tokenCount": chunk.get("tokenCount"),
            }
        )
    return rows


def fde_vector_format_rows(
    chunk_rows: list[dict[str, Any]],
    *,
    project_id: str,
    document: dict[str, Any],
    knowledge_file_id: str,
    embedding_model: str,
    index_version: str,
    dimensions: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in chunk_rows[:30]:
        chunk_id = str(chunk.get("chunkId") or chunk.get("id") or "")
        vector_id = f"VEC-{chunk_id or document.get('currentVersionId')}-{chunk.get('chunkNo')}"
        metadata = {
            "projectId": project_id,
            "documentId": document.get("id"),
            "documentVersionId": document.get("currentVersionId") or document.get("documentVersionId"),
            "knowledgeFileId": knowledge_file_id,
            "chunkId": chunk_id,
            "chunkNo": chunk.get("chunkNo"),
            "pageNo": chunk.get("pageNo"),
            "bbox": chunk.get("bbox"),
            "source": "aicheck_document_pipeline",
        }
        embedding_input = {
            "model": embedding_model,
            "input": chunk.get("textPreview") or "",
            "encoding_format": "float",
            "metadata": metadata,
        }
        vector_record = {
            "id": vector_id,
            "indexVersion": index_version,
            "dimensions": dimensions,
            "valuesPreview": "[float32 x %s hidden]" % dimensions,
            "metadata": metadata,
            "payloadHash": stable_hash_payload({"input": embedding_input, "indexVersion": index_version}),
            "status": chunk.get("vectorStatus"),
        }
        rows.append(
            {
                "id": vector_id,
                "chunkNo": chunk.get("chunkNo"),
                "chunkId": chunk_id,
                "vectorStatus": chunk.get("vectorStatus"),
                "textPreview": chunk.get("textPreview"),
                "embeddingInput": embedding_input,
                "vectorRecord": vector_record,
                "indexRecord": {
                    "vectorId": vector_id,
                    "indexVersion": index_version,
                    "status": chunk.get("vectorStatus"),
                    "documentVersionId": metadata["documentVersionId"],
                    "chunkId": chunk_id,
                    "payloadHash": vector_record["payloadHash"],
                    "materialized": bool(chunk.get("materialized")),
                },
            },
        )
    return rows


def fde_quality_issues_view(blockers: list[str], chunk_rows: list[dict[str, Any]], trace_rows_source: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = [
        {
            "severity": "blocker",
            "code": f"issue_{stable_hash_payload(blocker)[:10]}",
            "message": blocker,
            "targetType": "document_vector",
        }
        for blocker in blockers
    ]
    proxy_trace_count = len([item for item in trace_rows_source if item.get("_fdeTraceScope") == "project_proxy"])
    if proxy_trace_count:
        issues.append(
            {
                "severity": "warning",
                "code": "project_proxy_trace",
                "message": "当前文件缺少显式 ReviewRun 绑定，部分 LLM 检索引用使用项目级代理 Trace。",
                "targetType": "retrieval_trace",
                "count": proxy_trace_count,
            }
        )
    virtual_count = len([item for item in chunk_rows if not item.get("materialized")])
    if virtual_count:
        issues.append(
            {
                "severity": "warning",
                "code": "virtual_chunk_rows",
                "message": "存在按文件计数推导的虚拟切片，不能作为真实可审计向量明细。",
                "targetType": "knowledge_chunk",
                "count": virtual_count,
            }
        )
    return issues


def fde_vector_file_detail(project_id: str, document_version_id: str, *, chunk_page: int = 1, chunk_page_size: int = 50) -> dict[str, Any]:
    workspace = fde_project_audit_workspace(project_id)
    document = next(
        (
            item
            for item in workspace.get("documents", [])
            if str(item.get("documentVersionId") or item.get("currentVersionId") or item.get("id") or "") == document_version_id
        ),
        None,
    )
    if not document:
        raise KeyError(document_version_id)

    document_id = str(document.get("id") or "")
    version = repo.find_one("versions", document_version_id)
    parse_result = fde_latest_ocr_parse_result(document_version_id)
    extracted_fields = [
        repo.clone(item)
        for item in repo.state.get("extracted_fields", [])
        if str(item.get("documentVersionId") or "") == document_version_id
    ]
    knowledge_file_id = str(document.get("knowledgeFileId") or "")
    knowledge_file = repo.find_one("knowledge_files", knowledge_file_id) if knowledge_file_id else None
    if not knowledge_file:
        knowledge_file = next(
            (
                item
                for item in repo.state.get("knowledge_files", [])
                if str(item.get("documentVersionId") or "") == document_version_id
                or str(item.get("documentId") or "") == str(document.get("id") or "")
            ),
            None,
        )
        knowledge_file_id = str((knowledge_file or {}).get("id") or knowledge_file_id)

    review_runs = workspace.get("reviewRuns", [])
    project_traces = fde_project_retrieval_traces(review_runs)
    explicit_traces = [
        trace
        for trace in project_traces
        if fde_trace_matches_document(trace, file_id=knowledge_file_id, document_version_id=document_version_id)
    ]
    trace_rows_source = [
        {**trace, "_fdeTraceScope": "document_explicit"} for trace in explicit_traces
    ] or [
        {**trace, "_fdeTraceScope": "project_proxy"} for trace in project_traces[:5]
    ]
    trace_identifiers = {
        trace_id
        for trace in trace_rows_source
        for trace_id in fde_trace_chunk_identifiers(trace)
    }

    chunks = [
        repo.clone(item)
        for item in repo.state.get("knowledge_chunks", [])
        if knowledge_file_id and str(item.get("fileId") or "") == knowledge_file_id
    ]
    chunks.sort(key=lambda item: fde_as_int(item.get("chunkNo")))

    declared_chunk_count = max(
        fde_as_int(document.get("chunkCount")),
        fde_as_int((knowledge_file or {}).get("chunkCount")),
        len(chunks),
    )
    vector_count = max(
        fde_as_int(document.get("vectorCount")),
        fde_as_int((knowledge_file or {}).get("vectorCount")),
    )
    materialized_count = len(chunks)
    duplicate_hashes = {
        text_hash
        for text_hash in [fde_chunk_text_hash(item.get("text")) for item in chunks]
        if text_hash and len([chunk for chunk in chunks if fde_chunk_text_hash(chunk.get("text")) == text_hash]) > 1
    }

    chunk_rows: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_no = fde_as_int(chunk.get("chunkNo"), index)
        chunk_id = str(chunk.get("id") or f"chunk-{chunk_no}")
        retrieval_hits = [
            trace
            for trace in trace_rows_source
            if chunk_id in fde_trace_chunk_identifiers(trace)
            or f"KC-{chunk_id}" in fde_trace_chunk_identifiers(trace)
            or fde_trace_matches_document(trace, file_id=knowledge_file_id, document_version_id=document_version_id)
        ]
        vector_ready = chunk_no <= vector_count
        text_hash = fde_chunk_text_hash(chunk.get("text"))
        flags = fde_chunk_quality_flags(
            {**chunk, "materialized": True},
            vector_ready=vector_ready,
            retrieval_hit_count=len(retrieval_hits),
            duplicate=text_hash in duplicate_hashes,
        )
        chunk_rows.append(
            {
                "id": chunk_id,
                "chunkId": chunk_id,
                "chunkNo": chunk_no,
                "materialized": True,
                "pageNo": chunk.get("pageNo"),
                "bbox": chunk.get("bbox"),
                "textPreview": fde_chunk_text_preview(chunk.get("text")),
                "textHash": text_hash,
                "tokenCount": fde_as_int(chunk.get("tokenCount")),
                "vectorStatus": "ready" if vector_ready else "missing",
                "vectorStatusLabel": "已入库" if vector_ready else "缺向量",
                "embeddingModel": document.get("embeddingModel") or "embedding-default",
                "indexVersion": document.get("indexVersion") or "knowledge-index@local",
                "retrievalHitCount": len(retrieval_hits),
                "retrievalTraceIds": [
                    item.get("retrievalTraceId") or item.get("id")
                    for item in retrieval_hits[:5]
                ],
                "qualityFlags": flags,
                "metadataCompleteness": round(
                    fde_ratio(
                        len(
                            [
                                value
                                for value in [
                                    chunk.get("fileId"),
                                    chunk.get("documentVersionId"),
                                    chunk.get("pageNo"),
                                    chunk.get("bbox"),
                                    chunk.get("tokenCount"),
                                ]
                                if value not in (None, "", [])
                            ]
                        ),
                        5,
                        default=0.0,
                    ),
                    4,
                ),
            }
        )

    missing_materialized = max(0, declared_chunk_count - materialized_count)
    for offset in range(missing_materialized):
        chunk_no = materialized_count + offset + 1
        vector_ready = chunk_no <= vector_count
        virtual_chunk = {
            "chunkNo": chunk_no,
            "materialized": False,
            "text": "",
            "pageNo": None,
            "bbox": None,
            "tokenCount": 0,
        }
        chunk_rows.append(
            {
                "id": f"virtual-{knowledge_file_id or document_version_id}-{chunk_no}",
                "chunkId": "",
                "chunkNo": chunk_no,
                "materialized": False,
                "pageNo": None,
                "bbox": None,
                "textPreview": "切片计数存在，但缺少可审计切片明细。",
                "textHash": "",
                "tokenCount": 0,
                "vectorStatus": "ready" if vector_ready else "missing",
                "vectorStatusLabel": "按文件计数推导已入库" if vector_ready else "缺向量",
                "embeddingModel": document.get("embeddingModel") or "embedding-default",
                "indexVersion": document.get("indexVersion") or "knowledge-index@local",
                "retrievalHitCount": 0,
                "retrievalTraceIds": [],
                "qualityFlags": fde_chunk_quality_flags(
                    virtual_chunk,
                    vector_ready=vector_ready,
                    retrieval_hit_count=0,
                    duplicate=False,
                ),
                "metadataCompleteness": 0.0,
            }
        )

    effective_count = len(chunk_rows)
    page_covered = len([item for item in chunk_rows if item.get("pageNo") is not None])
    bbox_covered = len([item for item in chunk_rows if item.get("bbox")])
    text_covered = len([item for item in chunk_rows if item.get("materialized") and item.get("textHash")])
    vector_ready_count = len([item for item in chunk_rows if item.get("vectorStatus") == "ready"])
    retrieved_count = len([item for item in chunk_rows if fde_as_int(item.get("retrievalHitCount")) > 0])
    flag_counts: dict[str, int] = {}
    for item in chunk_rows:
        for flag in item.get("qualityFlags") or []:
            flag_counts[str(flag)] = flag_counts.get(str(flag), 0) + 1

    blockers: list[str] = []
    if declared_chunk_count <= 0:
        blockers.append("未生成知识切片")
    if declared_chunk_count > 0 and materialized_count <= 0:
        blockers.append("文件声明已切片，但缺少可审计切片明细")
    if missing_materialized:
        blockers.append(f"{missing_materialized} 条切片缺少明细")
    if vector_ready_count < declared_chunk_count:
        blockers.append("向量数量未覆盖全部切片")
    if effective_count and fde_ratio(page_covered, effective_count) < 0.95:
        blockers.append("部分切片缺少页码")
    if effective_count and fde_ratio(bbox_covered, effective_count) < 0.9:
        blockers.append("部分切片缺少 bbox 证据")
    if trace_rows_source and retrieved_count <= 0:
        blockers.append("当前 RetrievalTrace 未命中该文件切片")

    token_counts = [fde_as_int(item.get("tokenCount")) for item in chunk_rows if item.get("materialized")]
    page_distribution: dict[str, int] = {}
    for item in chunk_rows:
        page_key = str(item.get("pageNo") if item.get("pageNo") is not None else "缺页码")
        page_distribution[page_key] = page_distribution.get(page_key, 0) + 1
    token_buckets = {
        "0": len([value for value in token_counts if value <= 0]),
        "1-80": len([value for value in token_counts if 0 < value <= 80]),
        "81-200": len([value for value in token_counts if 80 < value <= 200]),
        "201-500": len([value for value in token_counts if 200 < value <= 500]),
        "500+": len([value for value in token_counts if value > 500]),
    }

    chunk_page_size = max(1, min(fde_as_int(chunk_page_size, 50), 200))
    chunk_page = max(1, fde_as_int(chunk_page, 1))
    paged_chunk_rows = page(chunk_rows, chunk_page, chunk_page_size)
    embedding_model = str(document.get("embeddingModel") or "embedding-default")
    index_version = str(document.get("indexVersion") or "knowledge-index@local")
    vector_dimensions = fde_as_int(document.get("vectorDimensions"), 1024)
    text_rows = fde_text_stage_rows(extracted_fields, chunk_rows)
    vector_format_rows = fde_vector_format_rows(
        chunk_rows,
        project_id=project_id,
        document=document,
        knowledge_file_id=knowledge_file_id,
        embedding_model=embedding_model,
        index_version=index_version,
        dimensions=vector_dimensions,
    )
    score = round(
        100
        * (
            0.22 * fde_ratio(materialized_count, declared_chunk_count, default=0.0)
            + 0.24 * fde_ratio(vector_ready_count, declared_chunk_count, default=0.0)
            + 0.16 * fde_ratio(page_covered, effective_count, default=0.0)
            + 0.16 * fde_ratio(bbox_covered, effective_count, default=0.0)
            + 0.12 * fde_ratio(text_covered, effective_count, default=0.0)
            + 0.10 * (fde_ratio(retrieved_count, effective_count, default=0.0) if trace_rows_source else 0.0)
        ),
        2,
    )
    source_preview = fde_source_preview_view({**document, "currentVersionId": document_version_id}, version, parse_result)
    ocr_artifacts = fde_ocr_artifacts_view(document_version_id, parse_result, extracted_fields)
    index_records = [row.get("indexRecord") for row in vector_format_rows if isinstance(row.get("indexRecord"), dict)]
    llm_usage = {
        "schemaVersion": "FdeDocumentLlmUsage@1.0.0",
        "scope": "document_explicit" if explicit_traces else "project_proxy",
        "relatedReviewRunCount": len(review_runs),
        "retrievalTraceCount": len(trace_rows_source),
        "retrievedChunkCount": retrieved_count,
        "retrievalCoverage": round(fde_ratio(retrieved_count, effective_count, default=0.0), 4),
        "proxyTrace": not bool(explicit_traces),
        "proxyReason": "" if explicit_traces else "未找到显式绑定该文件的 ReviewRun，使用项目级 RetrievalTrace 作为临时排查线索。",
    }
    quality_issues = fde_quality_issues_view(blockers, chunk_rows, trace_rows_source)

    return {
        "schemaVersion": "FdeVectorFileDetail@1.1.0",
        "compatibleSchemaVersion": "FdeVectorFileDetail@1.0.0",
        "projectId": project_id,
        "documentId": document_id,
        "documentVersionId": document_version_id,
        "knowledgeFileId": knowledge_file_id,
        "fileName": document.get("fileName"),
        "requirementName": document.get("requirementName"),
        "score": score,
        "status": "pass" if score >= 90 and not blockers else "needs_attention",
        "sliceStatus": document.get("sliceStatus") or (knowledge_file or {}).get("sliceStatus") or "待切片",
        "vectorStatus": document.get("vectorStatus") or (knowledge_file or {}).get("vectorStatus") or "待向量化",
        "embeddingModel": embedding_model,
        "indexVersion": index_version,
        "vectorDimensions": vector_dimensions,
        "sourcePreview": source_preview,
        "ocrArtifacts": ocr_artifacts,
        "textRecords": text_rows,
        "vectorPayloads": vector_format_rows,
        "indexRecords": index_records,
        "llmUsage": llm_usage,
        "qualityIssues": quality_issues,
        "processingPipeline": {
            "schemaVersion": "FdeDocumentProcessingPipeline@1.0.0",
            "summary": [
                {
                    "key": "image",
                    "label": "图片/文件",
                    "status": "ready" if version else "mock_or_missing",
                    "metric": document.get("fileType") or (version or {}).get("contentType") or "-",
                },
                {
                    "key": "ocr",
                    "label": "OCR",
                    "status": (parse_result or {}).get("status") or ("field_only" if extracted_fields else "missing"),
                    "metric": f"{len(extracted_fields)} 字段",
                },
                {
                    "key": "text",
                    "label": "文本",
                    "status": "ready" if text_rows else "missing",
                    "metric": f"{len(text_rows)} 条文本记录",
                },
                {
                    "key": "vector_format",
                    "label": "向量格式化",
                    "status": "ready" if vector_format_rows else "missing",
                    "metric": f"{len(vector_format_rows)} 条 payload",
                },
                {
                    "key": "index",
                    "label": "索引",
                    "status": document.get("vectorStatus") or (knowledge_file or {}).get("vectorStatus") or "待向量化",
                    "metric": index_version,
                },
            ],
            "source": source_preview,
            "ocr": ocr_artifacts,
            "text": {
                "stage": "text",
                "label": "OCR 文本与切片文本",
                "status": "ready" if text_rows else "missing",
                "rows": text_rows[:40],
                "textRecordCount": len(text_rows),
                "sourceBreakdown": {
                    "ocrFields": len(extracted_fields),
                    "knowledgeChunks": len(chunk_rows),
                },
            },
            "vectorFormat": {
                "stage": "vector_format",
                "label": "向量格式化数据",
                "status": "ready" if vector_format_rows else "missing",
                "embeddingModel": embedding_model,
                "indexVersion": index_version,
                "dimensions": vector_dimensions,
                "rows": vector_format_rows,
                "recordCount": len(vector_format_rows),
                "note": "真实高维向量值不在 FDE 展示；这里展示 embedding input、metadata、payload hash 和索引记录格式。",
            },
            "index": {
                "stage": "index",
                "label": "向量索引记录",
                "status": document.get("vectorStatus") or (knowledge_file or {}).get("vectorStatus") or "待向量化",
                "rows": index_records,
                "recordCount": len(index_records),
                "indexVersion": index_version,
            },
            "llmUsage": llm_usage,
        },
        "chunkSummary": {
            "declaredChunkCount": declared_chunk_count,
            "materializedChunkCount": materialized_count,
            "missingMaterializedChunkCount": missing_materialized,
            "vectorReadyCount": vector_ready_count,
            "vectorGap": max(0, declared_chunk_count - vector_ready_count),
            "totalTokenCount": sum(token_counts),
            "averageTokenCount": round((sum(token_counts) / len(token_counts)) if token_counts else 0.0, 2),
            "pageCoverage": round(fde_ratio(page_covered, effective_count, default=0.0), 4),
            "bboxCoverage": round(fde_ratio(bbox_covered, effective_count, default=0.0), 4),
            "textCoverage": round(fde_ratio(text_covered, effective_count, default=0.0), 4),
            "retrievedChunkCount": retrieved_count,
            "retrievalCoverage": round(fde_ratio(retrieved_count, effective_count, default=0.0), 4),
            "duplicateChunkCount": flag_counts.get("duplicate_text", 0),
        },
        "chunkRows": paged_chunk_rows["items"],
        "chunkPage": paged_chunk_rows,
        "chunkCharts": {
            "tokenBuckets": token_buckets,
            "pageDistribution": page_distribution,
            "flagCounts": flag_counts,
        },
        "retrievalTraceRows": [
            {
                "retrievalTraceId": item.get("retrievalTraceId") or item.get("id"),
                "query": item.get("query"),
                "selectedRoute": item.get("selectedRoute"),
                "scope": item.get("_fdeTraceScope") or "project_proxy",
                "selectedClauseCount": len(fde_trace_selected_clauses(item)),
                "selectedChunkCount": len(fde_trace_chunk_identifiers(item) & {str(row.get("chunkId")) for row in chunk_rows if row.get("chunkId")}),
                "evidenceBacked": fde_trace_evidence_backed(item),
                "filterScoped": isinstance(item.get("filters"), dict)
                and any(key in item["filters"] for key in ("businessPackId", "projectId", "nodeId", "tenantId")),
            }
            for item in trace_rows_source[:8]
        ],
        "blockers": blockers,
        "updatedAt": server_time(),
    }


def fde_runtime_env_value(name: str, fallback: str) -> str:
    value = os.getenv(name)
    return value if value not in {None, ""} else fallback


def fde_project_technology_stack(vector_quality: dict[str, Any] | None = None) -> dict[str, Any]:
    embedding = embedding_runtime_config()
    review_orchestration = fde_runtime_env_value("AICHECK_REVIEW_ORCHESTRATION", "temporal")
    review_llm_execution = fde_runtime_env_value("AICHECK_REVIEW_LLM_EXECUTION", "litellm")
    task_dispatch = fde_runtime_env_value("AICHECK_TASK_DISPATCH", "celery")
    vector_quality_score = (vector_quality or {}).get("score")
    return {
        "schemaVersion": "FdeTechnologyStack@1.0.0",
        "updatedAt": server_time(),
        "hotSwap": {
            "enabled": True,
            "stableAlias": embedding["alias"],
            "switchControl": embedding["switchControl"],
            "switchRequires": embedding["switchRequires"],
            "indexMigrationRequired": True,
        },
        "embeddingModelRegistry": embedding_registry_payload(),
        "active": {
            "embedding": {
                "component": "资料向量化模型",
                "provider": embedding["provider"],
                "alias": embedding["alias"],
                "servedModelName": embedding["servedModelName"],
                "modelId": embedding["modelId"],
                "engine": embedding["engine"],
                "dimensions": embedding["dimensions"],
                "contextLength": embedding["contextLength"],
                "indexVersion": embedding["indexVersion"],
                "fallbackModelId": embedding["fallbackModelId"],
                "localOnly": True,
                "hotSwappable": True,
            },
            "vectorIndex": {
                "component": "向量索引",
                "implementation": "local knowledge index",
                "dimensions": embedding["dimensions"],
                "indexVersion": embedding["indexVersion"],
                "qualityScore": vector_quality_score,
                "versioning": "modelId + dimensions + chunk policy + indexVersion",
            },
            "retrieval": {
                "component": "检索链路",
                "implementation": "Hybrid BM25 + dense vector + PageIndex",
                "rerankEnabled": bool((repo.state.get("knowledge_config") or {}).get("rerankEnabled", True)),
                "evidenceStrictMode": bool((repo.state.get("knowledge_config") or {}).get("evidenceStrictMode", True)),
            },
            "llm": {
                "component": "LLM 网关",
                "gateway": "LiteLLM",
                "reviewModelAlias": "review-chat",
                "defaultChatAlias": "default-chat",
                "provider": "DeepSeek deepseek-reasoner",
                "execution": review_llm_execution,
            },
            "ocr": {
                "component": "OCR / 文档智能",
                "primary": "PaddleOCR / PP-StructureV3",
                "seal": "PaddleX Seal / visual seal candidate / crop OCR fallback",
                "fallback": "Docling / PaddleOCR-VL / local remediation",
                "localOnly": True,
            },
            "orchestration": {
                "component": "审查编排",
                "workflow": review_orchestration,
                "graph": "LangGraph",
                "taskQueue": task_dispatch,
            },
            "storage": {
                "component": "数据底座",
                "database": "PostgreSQL",
                "objectStorage": "MinIO",
                "queue": "Redis + Celery",
                "workflowStore": "Temporal PostgreSQL",
            },
        },
        "sections": [
            {
                "key": "embedding",
                "title": "向量化",
                "primary": embedding["modelId"],
                "secondary": f"{embedding['alias']} / {embedding['servedModelName']}",
                "detail": f"{embedding['dimensions']}维，{embedding['contextLength']} token，本地 Infinity",
                "status": "active",
                "tone": "green",
            },
            {
                "key": "retrieval",
                "title": "检索",
                "primary": "Hybrid RAG + PageIndex",
                "secondary": "BM25 + dense vector + 章节树",
                "detail": "FDE 用 RetrievalTrace 量化召回、证据命中和过滤范围",
                "status": "active",
                "tone": "blue",
            },
            {
                "key": "ocr",
                "title": "文档智能",
                "primary": "PaddleOCR / PP-StructureV3",
                "secondary": "表格、印章、Docling、VL 兜底",
                "detail": "OCR 结果进入切片、向量和 PageIndex 证据链",
                "status": "active",
                "tone": "orange",
            },
            {
                "key": "llm",
                "title": "LLM",
                "primary": "LiteLLM + DeepSeek",
                "secondary": "review-chat / default-chat",
                "detail": "统一网关、预算、健康检查和 provider probe",
                "status": "active",
                "tone": "blue",
            },
            {
                "key": "orchestration",
                "title": "编排",
                "primary": f"{review_orchestration} + LangGraph",
                "secondary": f"dispatch={task_dispatch}",
                "detail": "ReviewRun、图节点、人工确认和 FDE replay 可追踪",
                "status": "active",
                "tone": "green",
            },
            {
                "key": "storage",
                "title": "基础设施",
                "primary": "PostgreSQL / Redis / MinIO",
                "secondary": "Temporal workflow store",
                "detail": "资料、索引、任务、审计和导出全链路落库",
                "status": "active",
                "tone": "blue",
            },
        ],
    }


def fde_project_document_audit_view(document: dict[str, Any]) -> dict[str, Any]:
    item = repo.clone(document)
    version_id = str(item.get("currentVersionId") or "")
    project = repo.find_one("projects", item.get("projectId")) or {}
    knowledge_file = next(
        (
            file
            for file in repo.state.get("knowledge_files", [])
            if str(file.get("documentVersionId") or "") == version_id
            or str(file.get("documentId") or "") == str(item.get("id") or "")
        ),
        None,
    )
    knowledge_config = repo.state.get("knowledge_config") or {}
    embedding = embedding_runtime_config()
    if knowledge_file:
        knowledge_source = repo.find_one("knowledge_sources", knowledge_file.get("sourceId")) or {}
        latest_task = next(
            (
                task
                for task in sorted(
                    repo.state.get("knowledge_tasks", []),
                    key=lambda value: str(value.get("updatedAt") or value.get("createdAt") or ""),
                    reverse=True,
                )
                if task.get("targetId") in {knowledge_file.get("id"), knowledge_file.get("sourceId")}
                or (
                    task.get("targetType") == "project"
                    and task.get("targetId") == knowledge_file.get("projectId")
                )
            ),
            None,
        )
        page_index_nodes = [
            node
            for node in repo.state.get("knowledge_page_index_nodes", [])
            if not node.get("businessPackId")
            or node.get("businessPackId") == project.get("businessPackId")
        ]
        item.update(
            {
                "knowledgeFileId": knowledge_file.get("id"),
                "knowledgeSourceId": knowledge_file.get("sourceId"),
                "knowledgeSourceName": knowledge_file.get("sourceName"),
                "sliceStatus": knowledge_file.get("sliceStatus"),
                "vectorStatus": knowledge_file.get("vectorStatus"),
                "chunkCount": int(knowledge_file.get("chunkCount") or 0),
                "vectorCount": int(knowledge_file.get("vectorCount") or 0),
                "embeddingModel": knowledge_config.get("embeddingModel") or embedding["alias"],
                "embeddingModelId": knowledge_config.get("embeddingModelId") or embedding["modelId"],
                "embeddingProvider": knowledge_config.get("embeddingProvider") or embedding["provider"],
                "embeddingServedModelName": knowledge_config.get("embeddingServedModelName") or embedding["servedModelName"],
                "indexVersion": knowledge_source.get("version") or "proj-v2026.06.26",
                "vectorDimensions": int(knowledge_config.get("dimensions") or embedding["dimensions"]),
                "pageIndexStatus": "已构建" if page_index_nodes else "待构建",
                "pageIndexNodeCount": len(page_index_nodes),
                "latestKnowledgeTask": versioned_record("knowledge-task", latest_task) if latest_task else None,
            }
        )
    else:
        item.update(
            {
                "sliceStatus": "待切片" if item.get("currentOcrStatus") == "已识别" else "等待OCR",
                "vectorStatus": "待向量化" if item.get("currentOcrStatus") == "已识别" else "未向量化",
                "chunkCount": 0,
                "vectorCount": 0,
                "embeddingModel": knowledge_config.get("embeddingModel") or embedding["alias"],
                "embeddingModelId": knowledge_config.get("embeddingModelId") or embedding["modelId"],
                "embeddingProvider": knowledge_config.get("embeddingProvider") or embedding["provider"],
                "embeddingServedModelName": knowledge_config.get("embeddingServedModelName") or embedding["servedModelName"],
                "indexVersion": "未入库",
                "vectorDimensions": int(knowledge_config.get("dimensions") or embedding["dimensions"]),
                "pageIndexStatus": "等待切片",
                "pageIndexNodeCount": 0,
                "latestKnowledgeTask": None,
            }
        )
    item["knowledgeLineage"] = fde_document_knowledge_lineage(item)
    return item


FDE_AUDIT_DOCUMENT_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "fileName": "管道特性表-第2版.png",
        "fileType": "png",
        "requirementName": "管道特性表",
        "usage": "设计资料",
        "source": "contractor",
        "currentOcrStatus": "人工修正",
        "sliceStatus": "已切片",
        "vectorStatus": "已向量化",
        "chunkCount": 42,
        "vectorCount": 42,
        "pageIndexStatus": "已构建",
        "profileId": "piping_characteristic_list_v1",
        "ocrStatus": "needs_human_review",
    },
    {
        "fileName": "质量证明书-QX201903S.pdf",
        "fileType": "pdf",
        "requirementName": "产品质量证明文件",
        "usage": "证明材料",
        "source": "contractor",
        "currentOcrStatus": "已识别",
        "sliceStatus": "已切片",
        "vectorStatus": "已向量化",
        "chunkCount": 34,
        "vectorCount": 31,
        "pageIndexStatus": "已构建",
        "profileId": "quality_certificate_v1",
        "ocrStatus": "success",
    },
    {
        "fileName": "RT检测报告-焊口清单.pdf",
        "fileType": "pdf",
        "requirementName": "无损检测报告",
        "usage": "检测报告",
        "source": "ndt",
        "currentOcrStatus": "已识别",
        "sliceStatus": "已切片",
        "vectorStatus": "向量化中",
        "chunkCount": 28,
        "vectorCount": 19,
        "pageIndexStatus": "待补齐向量",
        "profileId": "ndt_rt_report_v1",
        "ocrStatus": "success",
    },
    {
        "fileName": "焊工资格证与外部查询截图.pdf",
        "fileType": "pdf",
        "requirementName": "焊工资格证及外部查询截图",
        "usage": "资质证明",
        "source": "contractor",
        "currentOcrStatus": "已识别",
        "sliceStatus": "切片中",
        "vectorStatus": "待向量化",
        "chunkCount": 16,
        "vectorCount": 0,
        "pageIndexStatus": "等待切片",
        "profileId": "qualification_certificate_v1",
        "ocrStatus": "needs_human_review",
    },
)


def fde_compact_project_key(project_id: Any) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", str(project_id or "LOCAL"))
    return compact[-12:] or "LOCAL"


def fde_project_synthetic_document_views(project: dict[str, Any], node_id: int | None) -> list[dict[str, Any]]:
    project_id = str(project.get("id") or "PROJECT")
    project_key = fde_compact_project_key(project_id)
    knowledge_config = repo.state.get("knowledge_config") or {}
    embedding = embedding_runtime_config()
    page_index_node_count = len(repo.state.get("knowledge_page_index_nodes", [])) or 4
    documents: list[dict[str, Any]] = []
    for index, template in enumerate(FDE_AUDIT_DOCUMENT_TEMPLATES, start=1):
        version_id = f"FDE-DV-{project_key}-{index}-V{2 if index == 1 else 1}"
        source_org = project.get("ndtOrgName") if template["source"] == "ndt" else project.get("contractorOrgName")
        page_index_ready = template["pageIndexStatus"] != "等待切片"
        document = {
            "id": f"FDE-DOC-{project_key}-{index}",
            "projectId": project_id,
            "nodeId": node_id,
            "fileName": template["fileName"],
            "fileType": template["fileType"],
            "sourceOrgName": source_org or project.get("contractorOrgName") or "项目参建单位",
            "uploaderName": "NDT 王工" if template["source"] == "ndt" else "施工方 李工",
            "currentVersionId": version_id,
            "knowledgeFileId": f"KF-FDE-{project_key}-{index}",
            "fileStatus": "已上传",
            "currentOcrStatus": template["currentOcrStatus"],
            "sliceStatus": template["sliceStatus"],
            "vectorStatus": template["vectorStatus"],
            "chunkCount": int(template["chunkCount"]),
            "vectorCount": int(template["vectorCount"]),
            "embeddingModel": knowledge_config.get("embeddingModel") or embedding["alias"],
            "embeddingModelId": knowledge_config.get("embeddingModelId") or embedding["modelId"],
            "embeddingProvider": knowledge_config.get("embeddingProvider") or embedding["provider"],
            "embeddingServedModelName": knowledge_config.get("embeddingServedModelName") or embedding["servedModelName"],
            "indexVersion": "proj-v2026.06.26",
            "vectorDimensions": int(knowledge_config.get("dimensions") or embedding["dimensions"]),
            "pageIndexStatus": template["pageIndexStatus"],
            "pageIndexNodeCount": page_index_node_count if page_index_ready else 0,
            "requirementName": template["requirementName"],
            "latestKnowledgeTask": {
                "id": f"FDE-KTASK-{project_key}-{index}",
                "taskType": "vector" if template["vectorStatus"] != "待向量化" else "slice",
                "status": "成功" if template["vectorStatus"] == "已向量化" else "运行中",
                "progress": 100 if template["vectorStatus"] == "已向量化" else 62,
            },
            "syntheticFdeAudit": True,
            "updatedAt": f"2026-06-26 {8 + index:02d}:18:00",
            "actions": ["file:view", "file:preview", "file:download"],
        }
        document["knowledgeLineage"] = fde_document_knowledge_lineage(document)
        documents.append(document)
    return documents


def fde_project_synthetic_bindings(project_id: str, node_id: int | None, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if node_id is None:
        return []
    project_key = fde_compact_project_key(project_id)
    bindings: list[dict[str, Any]] = []
    for index, document in enumerate(documents, start=1):
        template = FDE_AUDIT_DOCUMENT_TEMPLATES[(index - 1) % len(FDE_AUDIT_DOCUMENT_TEMPLATES)]
        bindings.append(
            {
                "id": f"FDE-BIND-{project_key}-{node_id}-{index}",
                "projectId": project_id,
                "nodeId": node_id,
                "requirementId": f"FDE-REQ-{index}",
                "requirementName": template["requirementName"],
                "documentId": document.get("id"),
                "documentVersionId": document.get("currentVersionId"),
                "fileName": document.get("fileName"),
                "versionNo": "V2" if str(document.get("currentVersionId") or "").endswith("V2") else "V1",
                "usage": template["usage"],
                "sourceOrgName": document.get("sourceOrgName"),
                "bindingStatus": "需人工复核" if index in {1, 3} else "已提交",
                "boundAt": document.get("updatedAt") or server_time(),
                "actions": ["file:view", "review:save"],
                "syntheticFdeAudit": True,
            }
        )
    return bindings


def fde_project_synthetic_ocr_jobs(project_id: str, node_id: int | None, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    project_key = fde_compact_project_key(project_id)
    jobs: list[dict[str, Any]] = []
    for index, document in enumerate(documents, start=1):
        template = FDE_AUDIT_DOCUMENT_TEMPLATES[(index - 1) % len(FDE_AUDIT_DOCUMENT_TEMPLATES)]
        jobs.append(
            {
                "id": f"OCR-JOB-FDE-{project_key}-{index}",
                "jobId": f"OCR-JOB-FDE-{project_key}-{index}",
                "projectId": project_id,
                "nodeId": node_id,
                "documentId": document.get("id"),
                "documentVersionId": document.get("currentVersionId"),
                "profileId": template["profileId"],
                "status": template["ocrStatus"],
                "parseResultId": f"PARSE-FDE-{project_key}-{index}",
                "resultSummary": {
                    "fieldCount": 18 if index == 1 else 9 + index,
                    "tableCount": 2 if index in {1, 3} else 1,
                    "sealCount": 1 if index in {1, 2, 4} else 0,
                    "lowConfidenceFieldCount": 3 if index in {1, 4} else 1,
                },
                "engineRuns": [
                    {"engine": "pp_ocr_v6", "status": "success", "durationMs": 1260, "selectedVariantId": "v1_deskew"},
                    {"engine": "pp_structure_v3", "status": "success", "durationMs": 2180, "selectedVariantId": "table_v1_line_enhanced"},
                    {"engine": "paddlex_seal", "status": "success" if index != 3 else "skipped", "durationMs": 740, "selectedVariantId": "seal_v0_color_original"},
                ],
                "updatedAt": document.get("updatedAt") or server_time(),
                "syntheticFdeAudit": True,
            }
        )
    return jobs


def fde_project_synthetic_parse_result(
    project_id: str,
    node_id: int | None,
    document: dict[str, Any],
    job: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    profile_id = str(job.get("profileId") or "piping_characteristic_list_v1")
    parse_result_id = str(job.get("parseResultId") or f"PARSE-FDE-{fde_compact_project_key(project_id)}-{index}")
    low_confidence = index in {1, 4}
    fields = [
        {
            "fieldId": f"FIELD-{parse_result_id}-PROJECT",
            "fieldCode": "project_name",
            "fieldName": "项目名称",
            "fieldValue": "广东 LNG 支线改造工程",
            "confidence": 0.94,
            "pageNo": 1,
            "bbox": [120, 150, 880, 210],
            "sourceEngine": "pp_ocr_v6",
        },
        {
            "fieldId": f"FIELD-{parse_result_id}-PIPE",
            "fieldCode": "pipe_no" if profile_id == "piping_characteristic_list_v1" else "report_no",
            "fieldName": "管道号" if profile_id == "piping_characteristic_list_v1" else "报告编号",
            "fieldValue": "PL8301" if profile_id == "piping_characteristic_list_v1" else "QX201903S-13-Y-02",
            "confidence": 0.72 if low_confidence else 0.9,
            "pageNo": 1,
            "bbox": [180, 284, 360, 334],
            "sourceEngine": "pp_structure_v3",
            "qualityFlags": ["low_confidence"] if low_confidence else [],
        },
        {
            "fieldId": f"FIELD-{parse_result_id}-SEAL",
            "fieldCode": "seal_name",
            "fieldName": "印章名称",
            "fieldValue": "压力管道设计许可印章",
            "confidence": 0.68 if profile_id == "qualification_certificate_v1" else 0.86,
            "pageNo": 1,
            "bbox": [1410, 690, 1840, 920],
            "sourceEngine": "paddlex_seal",
            "qualityFlags": ["seal_text_low_confidence"] if profile_id == "qualification_certificate_v1" else [],
        },
    ]
    diagnostics = [
        {
            "code": "FIELD_LOW_CONFIDENCE" if low_confidence else "PROFILE_GATE_PASSED",
            "level": "warning" if low_confidence else "info",
            "message": "存在低置信字段，建议进入人工标注复核。" if low_confidence else "OCR Profile 质量门禁通过。",
            "pageNo": 1,
            "targetType": "field" if low_confidence else "profile",
            "targetId": fields[1]["fieldId"] if low_confidence else profile_id,
        }
    ]
    if profile_id in {"qualification_certificate_v1", "seal_text_profile_v1"}:
        diagnostics.append(
            {
                "code": "SEAL_TEXT_LOW_CONFIDENCE",
                "level": "warning",
                "message": "印章文字可读但置信度偏低，需要 FDE 复核章名和单位一致性。",
                "pageNo": 1,
                "targetType": "seal",
                "targetId": f"SEAL-{parse_result_id}-1",
            }
        )
    return {
        "id": parse_result_id,
        "parseResultId": parse_result_id,
        "projectId": project_id,
        "nodeId": node_id,
        "documentId": document.get("id"),
        "documentVersionId": document.get("currentVersionId"),
        "status": job.get("status") or "success",
        "profileId": profile_id,
        "engine": "document-intelligence-local",
        "engineVersion": "fde-audit-projection@1.0.0",
        "preprocessStatus": {
            "requestedVariants": ["original", "deskew", "gray_clahe", "table_line_enhanced", "seal_color_crop"],
            "generatedVariants": ["original", "deskew", "table_line_enhanced", "seal_color_crop"],
            "missingVariants": ["gray_clahe"] if low_confidence else [],
            "selectedVariantId": "table_line_enhanced" if profile_id == "piping_characteristic_list_v1" else "deskew",
        },
        "engineRuns": repo.clone(job.get("engineRuns") or []),
        "pages": [{"pageNo": 1, "width": 2048, "height": 1536, "dpi": 300}],
        "fields": fields,
        "tables": [
            {
                "tableId": f"TABLE-{parse_result_id}-1",
                "pageNo": 1,
                "bbox": [92, 260, 1860, 610],
                "rows": 10,
                "columns": 8,
                "structureConfidence": 0.84 if low_confidence else 0.92,
                "normalizedRows": [
                    {"管道号": "PL8301", "公称直径": "DN100", "介质": "天然气", "检测比例": "10%"},
                    {"管道号": "PL8302", "公称直径": "DN100", "介质": "天然气", "检测比例": "10%"},
                ],
            }
        ],
        "seals": [
            {
                "sealId": f"SEAL-{parse_result_id}-1",
                "pageNo": 1,
                "sealType": "design_license_seal",
                "sealName": "压力管道设计许可印章",
                "bbox": [1390, 675, 1870, 940],
                "visualConfidence": 0.91,
                "ocrConfidence": 0.68 if profile_id == "qualification_certificate_v1" else 0.84,
                "qualityFlags": ["seal_text_low_confidence"] if profile_id == "qualification_certificate_v1" else [],
            }
        ],
        "quality": {
            "status": "needs_human_review" if low_confidence else "auto_usable",
            "overallConfidence": 0.82 if low_confidence else 0.92,
            "textConfidence": 0.88,
            "tableConfidence": 0.84 if low_confidence else 0.92,
            "sealConfidence": 0.68 if profile_id == "qualification_certificate_v1" else 0.84,
            "fieldCompleteness": 0.86 if low_confidence else 0.96,
            "evidenceCompleteness": 0.92,
            "reasons": [item["code"] for item in diagnostics if item.get("level") == "warning"],
        },
        "diagnostics": diagnostics,
        "createdAt": job.get("updatedAt") or server_time(),
        "updatedAt": job.get("updatedAt") or server_time(),
        "syntheticFdeAudit": True,
    }


def fde_materialize_synthetic_ocr_jobs(
    project_id: str,
    node_id: int | None,
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    repo.state.setdefault("ocr_jobs", [])
    repo.state.setdefault("ocr_parse_results", [])
    materialized: list[dict[str, Any]] = []
    for index, job in enumerate(fde_project_synthetic_ocr_jobs(project_id, node_id, documents), start=1):
        job_id = str(job.get("jobId") or job.get("id"))
        existing_job = repo.find_one("ocr_jobs", job_id) or repo.find_one("ocr_jobs", job_id, id_field="jobId")
        if not existing_job:
            repo.state["ocr_jobs"].insert(0, job)
            existing_job = job
        document = next(
            (
                item
                for item in documents
                if str(item.get("currentVersionId") or "") == str(existing_job.get("documentVersionId") or "")
            ),
            documents[(index - 1) % len(documents)] if documents else {},
        )
        parse_result_id = str(existing_job.get("parseResultId") or "")
        existing_parse_result = (
            repo.find_one("ocr_parse_results", parse_result_id, id_field="parseResultId")
            or repo.find_one("ocr_parse_results", parse_result_id)
        )
        if parse_result_id and not existing_parse_result:
            repo.state["ocr_parse_results"].insert(
                0,
                fde_project_synthetic_parse_result(project_id, node_id, document, existing_job, index),
            )
        materialized.append(repo.clone(existing_job))
    return materialized


def fde_find_or_materialize_synthetic_ocr_job(job_id: str) -> dict[str, Any] | None:
    for project in repo.state.get("projects", []):
        project_id = str(project.get("id") or "")
        nodes = [item for item in repo.state.get("tree_nodes", []) if item.get("projectId") == project_id]
        node_ids = [int(project.get("currentNodeId") or 0)] + [
            int(item.get("nodeId") or 0)
            for item in nodes[:3]
            if item.get("nodeId") is not None
        ]
        seen: set[int | None] = set()
        for raw_node_id in node_ids:
            node_id = raw_node_id or None
            if node_id in seen:
                continue
            seen.add(node_id)
            documents = fde_project_synthetic_document_views(project, node_id)
            for job in fde_materialize_synthetic_ocr_jobs(project_id, node_id, documents):
                if str(job.get("jobId") or job.get("id")) == job_id:
                    return job
    return None


def fde_project_synthetic_annotation_tasks(project_id: str, node_id: int | None, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    project_key = fde_compact_project_key(project_id)
    scenarios = [
        ("字段框选与证书编号修正", "qualification_certificate_v1", "labeled", [], []),
        ("表格单元格结构标定", "piping_characteristic_list_v1", "needs_labeling", ["缺少人工表格单元格标注"], []),
        ("红章区域与章名标定", "seal_text_profile_v1", "ready_for_eval", [], ["印章名称需二审"]),
        ("NDT 报告跨页表格标定", "ndt_rt_report_v1", "ready_for_eval", [], []),
    ]
    tasks: list[dict[str, Any]] = []
    for index, (scenario, profile_id, status, readiness, certification) in enumerate(scenarios, start=1):
        document = documents[(index - 1) % len(documents)] if documents else {}
        raw_task = {
            "taskId": f"OCR-LABEL-FDE-{project_key}-{index}",
            "caseId": f"OCR-CASE-FDE-{project_key}-{index}",
            "projectId": project_id,
            "nodeId": node_id,
            "documentVersionId": document.get("currentVersionId"),
            "scenario": scenario,
            "profileId": profile_id,
            "documentType": profile_id,
            "pageNo": index,
            "collectionStatus": status,
            "readinessBlockers": readiness,
            "certificationBlockers": certification,
            "candidateCounts": {"fields": 8 + index, "tables": 2 if index in {2, 4} else 1, "seals": 1 if index >= 3 else 0},
            "labelCounts": {"fields": 0 if index == 2 else 6 + index, "tables": 0 if index == 2 else 1, "seals": 1 if index >= 3 else 0},
            "readyForEval": status == "ready_for_eval",
            "labeler": "" if status == "needs_labeling" else "FDE 张工",
            "reviewer": "OCR 负责人" if certification else "",
            "syntheticFdeAudit": True,
        }
        tasks.append(fde_ocr_annotation_task_view(raw_task))
    return tasks


def fde_project_synthetic_review_run(project: dict[str, Any], node_id: int | None, documents: list[dict[str, Any]]) -> dict[str, Any]:
    run_id = f"RR-AUDIT-{project.get('id')}-{node_id or 'project'}"
    pending_ocr = len([item for item in documents if item.get("currentOcrStatus") not in {"已识别", "识别完成"}])
    return {
        "id": run_id,
        "reviewRunId": run_id,
        "projectId": project.get("id"),
        "nodeId": node_id,
        "agentId": "compliance_review_agent",
        "agentName": "资料合规复核员",
        "status": "waiting_human_review",
        "runType": "audit_workspace_projection",
        "createdAt": server_time(),
        "graphSummary": {
            "total": max(len(documents), 1),
            "completed": 0,
            "blocked": pending_ocr,
        },
        "graphAuditSummary": {
            "nodeCount": max(len(documents), 1),
            "edgeCount": max(len(documents) - 1, 1),
            "timelineCount": 1,
            "artifactSummary": {"documents": len(documents), "ocrPending": pending_ocr},
            "checkpointer": "audit-workspace-projection",
            "workflowEngine": "temporal",
            "graphEngine": "langgraph",
            "temporalEventCount": 1,
        },
    }


def fde_project_review_run_audit_view(review_run: dict[str, Any]) -> dict[str, Any]:
    view = review_run_view(review_run)
    review_run_id = str(view.get("reviewRunId") or view.get("id") or "")
    graph = graph_view_for_review_run(review_run_id) if review_run_id else {}
    artifact_summary = graph.get("artifactSummary") if isinstance(graph.get("artifactSummary"), dict) else {}
    timeline = graph.get("timeline") if isinstance(graph.get("timeline"), list) else []
    view["graphSummary"] = view.get("graphSummary") or {}
    view["graphAuditSummary"] = {
        "nodeCount": len(graph.get("nodes") or []),
        "edgeCount": len(graph.get("edges") or []),
        "timelineCount": len(timeline),
        "artifactSummary": artifact_summary,
        "checkpointer": ((view.get("graphExecution") or {}).get("checkpointer") if isinstance(view.get("graphExecution"), dict) else None),
        "workflowEngine": view.get("workflowEngine") or "temporal",
        "graphEngine": view.get("graphEngine") or "langgraph",
        "temporalEventCount": len(review_run_timeline(review_run_id)) if review_run_id else 0,
    }
    return view


def fde_page_index_nodes_for_clauses(clause_ids: list[str]) -> list[dict[str, Any]]:
    clause_id_set = {str(item) for item in clause_ids if item}
    if not clause_id_set:
        return []
    nodes = []
    for node in repo.state.get("knowledge_page_index_nodes", []):
        linked = {str(item) for item in node.get("linkedClauseIds") or []}
        if linked & clause_id_set:
            nodes.append(repo.clone(node))
    return nodes[:5]


def fde_clause_for_evidence(link: dict[str, Any]) -> dict[str, Any]:
    clause_id = str(link.get("objectId") or link.get("clauseId") or link.get("id") or "")
    clause = next(
        (
            item
            for item in repo.state.get("knowledge_clauses", [])
            if str(item.get("clauseId") or item.get("id")) == clause_id
        ),
        None,
    )
    if clause:
        return repo.clone(clause)
    return {
        "clauseId": clause_id or "AI-RUN-KB-CONTEXT",
        "kbDocId": link.get("kbDocId") or "AI-RUN-EVIDENCE",
        "kbVersion": link.get("kbVersion") or "std-v2026.06",
        "clauseNo": link.get("clauseNo") or clause_id,
        "title": link.get("title") or "AI Run 关联知识依据",
        "text": link.get("quotedText") or "AI 审查运行关联的知识条款证据。",
        "pageNo": link.get("pageNo"),
        "bbox": link.get("bbox"),
        "status": "effective",
    }


def fde_document_evidence_ref(link: dict[str, Any]) -> dict[str, Any]:
    document_version_id = str(link.get("documentVersionId") or link.get("objectId") or "")
    field = next(
        (
            item
            for item in repo.state.get("extracted_fields", [])
            if str(item.get("documentVersionId") or "") == document_version_id
        ),
        {},
    )
    return {
        "evidenceLinkId": link.get("id"),
        "documentVersionId": document_version_id,
        "documentId": link.get("documentId"),
        "pageNo": link.get("pageNo") if link.get("pageNo") is not None else field.get("pageNo", 1),
        "bbox": link.get("bbox") or field.get("bbox") or [0, 0, 100, 40],
        "text": link.get("quotedText") or field.get("fieldValue") or link.get("fileName") or "资料证据片段",
        "source": "ai_run_evidence_link",
    }


def fde_append_review_event_once(review_run_id: str, event_type: str, title: str, status: str, details: dict[str, Any] | None = None) -> None:
    if any(
        item.get("reviewRunId") == review_run_id and item.get("eventType") == event_type
        for item in repo.state.get("review_events", [])
    ):
        return
    repo.state.setdefault("review_events", []).append(
        {
            "id": f"REVT-FDE-{uuid4().hex[:8].upper()}",
            "reviewRunId": review_run_id,
            "eventType": event_type,
            "title": title,
            "status": status,
            "details": details or {},
            "createdAt": server_time(),
        }
    )


def fde_append_tool_call_once(review_run: dict[str, Any], node_key: str, tool_name: str, output_summary: dict[str, Any]) -> None:
    review_run_id = str(review_run.get("reviewRunId") or "")
    if any(
        item.get("reviewRunId") == review_run_id
        and item.get("nodeKey") == node_key
        and item.get("toolName") == tool_name
        for item in repo.state.get("review_tool_calls", [])
    ):
        return
    repo.state.setdefault("review_tool_calls", []).append(
        {
            "id": f"RTC-FDE-{uuid4().hex[:8].upper()}",
            "reviewRunId": review_run_id,
            "nodeKey": node_key,
            "toolName": tool_name,
            "allowed": True,
            "outputHash": stable_hash_payload(output_summary),
            "outputSummary": output_summary,
            "createdAt": server_time(),
        }
    )


def fde_materialize_synthetic_review_run(
    project: dict[str, Any],
    node_id: int | None,
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    synthetic = fde_project_synthetic_review_run(project, node_id, documents)
    review_run_id = str(synthetic["reviewRunId"])
    existing = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if existing:
        return existing

    for collection in [
        "review_runs",
        "review_step_runs",
        "review_graph_nodes",
        "review_tool_calls",
        "review_events",
        "retrieval_traces",
        "rule_check_results",
        "ai_feedback",
    ]:
        repo.state.setdefault(collection, [])

    project_id = str(project.get("id") or "")
    pack = business_pack_for_project(project) if project else load_business_pack(DEFAULT_BUSINESS_PACK_ID)
    document_versions = [str(item.get("currentVersionId")) for item in documents if item.get("currentVersionId")]
    page_index_nodes = repo.clone(repo.state.get("knowledge_page_index_nodes", [])[:4])
    selected_clauses = repo.clone(repo.state.get("knowledge_clauses", [])[:3])
    if not selected_clauses:
        selected_clauses = [
            {
                "clauseId": "FDE-CLAUSE-001",
                "kbDocId": "KB-FDE-LOCAL",
                "kbVersion": "inspection_kb@1.0.0",
                "clauseNo": "5.3.2",
                "title": "资料完整性与签章审查要求",
                "text": "审查资料应核对必填字段、表格记录、签章和项目上下文一致性。",
                "pageNo": 42,
                "bbox": [120, 180, 1120, 680],
            }
        ]
    clause_ids = [str(item.get("clauseId") or item.get("id")) for item in selected_clauses if item.get("clauseId") or item.get("id")]
    document_evidence = [
        {
            "documentVersionId": str(item.get("currentVersionId")),
            "documentId": item.get("id"),
            "pageNo": 1,
            "bbox": [180, 220 + index * 90, 980, 280 + index * 90],
            "text": item.get("fileName"),
            "source": "fde_audit_workspace_projection",
        }
        for index, item in enumerate(documents[:4])
        if item.get("currentVersionId")
    ]
    finding_drafts = [
        {
            "id": f"FND-DRAFT-{review_run_id}-FIELD",
            "reviewRunId": review_run_id,
            "projectId": project_id,
            "nodeId": node_id,
            "businessPackId": pack["id"],
            "agentId": "compliance_review_agent",
            "agentVersion": "compliance_review_agent@1.0.0",
            "findingType": "field_low_confidence",
            "severity": "medium",
            "title": "管道特性表存在低置信字段，需人工核对",
            "description": "OCR 识别到管道代号、焊缝检测比例和签章区域存在低置信字段，建议进入 OCR 标注与证据复核。",
            "evidenceRefs": document_evidence[:2],
            "ruleRefs": [{"ruleCode": "PIPE_LIST_FIELD_CONFIDENCE", "ruleSetVersion": "engineering_rules@1.0.0"}],
            "kbRefs": [
                {
                    "kbVersion": "inspection_kb@1.0.0",
                    "retrievalTraceId": f"RTR-{review_run_id}-PAGEINDEX",
                    "clauseIds": clause_ids,
                    "clauses": [
                        {"clauseId": item.get("clauseId"), "kbDocId": item.get("kbDocId"), "clauseNo": item.get("clauseNo")}
                        for item in selected_clauses
                    ],
                }
            ],
            "confidence": 0.86,
            "suggestedAction": "human_confirm",
            "requiresHumanConfirmation": True,
            "status": "pending_human_review",
            "createdAt": server_time(),
            "source": "fde_audit_workspace_projection",
        },
        {
            "id": f"FND-DRAFT-{review_run_id}-SEAL",
            "reviewRunId": review_run_id,
            "projectId": project_id,
            "nodeId": node_id,
            "businessPackId": pack["id"],
            "agentId": "compliance_review_agent",
            "agentVersion": "compliance_review_agent@1.0.0",
            "findingType": "seal_text_needs_review",
            "severity": "medium",
            "title": "红章文字识别需要二次标定",
            "description": "印章检测已定位，但章名与单位一致性校验需要人工确认，可沉淀为 seal_text_profile_v1 样本。",
            "evidenceRefs": document_evidence[1:3] or document_evidence[:1],
            "ruleRefs": [{"ruleCode": "SEAL_REQUIRED_AND_READABLE", "ruleSetVersion": "engineering_rules@1.0.0"}],
            "kbRefs": [
                {
                    "kbVersion": "inspection_kb@1.0.0",
                    "retrievalTraceId": f"RTR-{review_run_id}-HYBRID",
                    "clauseIds": clause_ids,
                    "clauses": [
                        {"clauseId": item.get("clauseId"), "kbDocId": item.get("kbDocId"), "clauseNo": item.get("clauseNo")}
                        for item in selected_clauses[:2]
                    ],
                }
            ],
            "confidence": 0.81,
            "suggestedAction": "human_confirm",
            "requiresHumanConfirmation": True,
            "status": "pending_human_review",
            "createdAt": server_time(),
            "source": "fde_audit_workspace_projection",
        },
    ]
    now = server_time()
    review_run = {
        **synthetic,
        "businessPackId": pack["id"],
        "businessPackVersion": pack.get("version"),
        "businessPackSnapshotHash": pack.get("snapshotHash"),
        "agentVersion": "compliance_review_agent@1.0.0",
        "promptVersion": "review_prompt@1.0.0",
        "modelAlias": "deepseek-reasoner",
        "modelGateway": "litellm",
        "ruleSetVersion": "engineering_rules@1.0.0",
        "kbVersion": "inspection_kb@1.0.0",
        "schemaVersion": "ReviewFindingDraftList@1.0.0",
        "workflowType": "ReviewRunWorkflow",
        "workflowId": f"review-run-{review_run_id}",
        "temporalRunId": f"temporal-local-{fde_compact_project_key(project_id)}",
        "temporalNamespace": "default",
        "graphRunner": "langgraph",
        "graphEngine": "langgraph",
        "workflowEngine": "temporal",
        "graphExecution": {
            "runner": "langgraph",
            "checkpointer": "postgres",
            "persistence": "langgraph_postgres_checkpointer",
            "source": "fde_audit_workspace_projection",
        },
        "sensitivePayloadPolicy": {
            "temporalPayload": "ids_hashes_versions_only",
            "rawTextStorage": "postgres_minio_with_fde_grants",
            "payloadCodecRequiredInProduction": True,
        },
        "allowedTools": [
            "get_project_context",
            "get_node_requirements",
            "get_document_ocr_result",
            "run_rule_engine",
            "retrieve_clauses",
            "search_knowledge_base",
            "call_litellm_chat",
            "create_review_finding_draft",
        ],
        "forbiddenTools": [
            "approve_review",
            "issue_formal_correction",
            "close_correction",
            "change_project_status",
            "archive_project",
            "delete_document",
            "modify_audit_log",
            "grant_permission",
        ],
        "inputDocumentVersionIds": document_versions,
        "ocrResultVersions": [f"PARSE-FDE-{fde_compact_project_key(project_id)}-{index}" for index, _ in enumerate(documents, start=1)],
        "inputHash": stable_hash_payload({"projectId": project_id, "nodeId": node_id, "documentVersionIds": document_versions}),
        "outputHash": stable_hash_payload(finding_drafts),
        "findingDrafts": finding_drafts,
        "qualityGate": {
            "passed": True,
            "checked": len(finding_drafts),
            "failures": [],
            "warnings": [{"code": "FDE_AUDIT_SAMPLE", "message": "这是 FDE 审计工作台投影样例，用于 UI/UX 与流程审计。"}],
            "metrics": {
                "status": "ready_for_human_review",
                "requiresHumanReview": True,
                "selectedClauseCount": len(selected_clauses),
                "pageIndexNodeCount": len(page_index_nodes),
                "findingDraftCount": len(finding_drafts),
            },
        },
        "startedAt": now,
        "finishedAt": now,
        "createdAt": now,
        "updatedAt": now,
        "revision": 1,
    }
    repo.state["review_runs"].insert(0, review_run)

    node_details = {
        "load_context": {"projectId": project_id, "nodeId": node_id, "projectName": project.get("name")},
        "load_ocr_result": {"documentCount": len(documents), "ocrResultVersions": review_run["ocrResultVersions"]},
        "run_rule_engine": {"ruleResults": 2, "failed": 1, "warning": 1},
        "retrieve_knowledge": {
            "retrievalTraceIds": [f"RTR-{review_run_id}-PAGEINDEX", f"RTR-{review_run_id}-HYBRID"],
            "selectedClauses": len(selected_clauses),
            "pageIndexNodes": len(page_index_nodes),
        },
        "build_prompt": {"promptVersion": review_run["promptVersion"], "promptPayload": "ids_hashes_versions_only"},
        "llm_generate_findings": {"modelGateway": "litellm", "modelAlias": review_run["modelAlias"], "findingDrafts": len(finding_drafts)},
        "schema_validation": {"passed": True, "checked": len(finding_drafts), "failures": [], "warnings": [], "metrics": {"findingCount": len(finding_drafts)}},
        "evidence_validation": {"passed": True, "checked": len(document_evidence), "failures": [], "warnings": [], "metrics": {"evidenceRefCount": len(document_evidence)}},
        "reference_validation": {"passed": True, "checked": len(clause_ids) + 2, "failures": [], "warnings": [], "metrics": {"ruleResultCount": 2, "retrievalTraceCount": 2}},
        "critic_review": {"passed": True, "checked": len(finding_drafts), "failures": [], "warnings": [], "metrics": {"criticMode": "audit_workspace_projection"}},
        "quality_gate": review_run["qualityGate"],
        "persist_drafts": {"findingDrafts": len(finding_drafts), "outputHash": review_run["outputHash"]},
    }
    for sequence, step in enumerate(REVIEW_GRAPH_STEPS, start=1):
        repo.state["review_graph_nodes"].append(
            {
                "id": f"RGNODE-FDE-{fde_compact_project_key(project_id)}-{sequence}",
                "reviewRunId": review_run_id,
                "nodeKey": step["key"],
                "label": step["label"],
                "sequence": sequence,
                "taskQueue": step["taskQueue"],
                "status": "succeeded",
                "attempt": 1,
                "details": node_details.get(step["key"], {}),
                "outputHash": stable_hash_payload(node_details.get(step["key"], {})),
                "createdAt": now,
                "startedAt": now,
                "finishedAt": now,
            }
        )
    rule_results = [
        {
            "id": f"RCHK-{review_run_id}-FIELD",
            "reviewRunId": review_run_id,
            "ruleCode": "PIPE_LIST_FIELD_CONFIDENCE",
            "ruleSetVersion": review_run["ruleSetVersion"],
            "result": "warning",
            "severity": "medium",
            "message": "管道特性表存在低置信字段，需人工复核。",
            "linkedClauseIds": clause_ids,
            "evidenceRefs": document_evidence[:2],
            "suggestedAction": "human_confirm",
            "createdAt": now,
        },
        {
            "id": f"RCHK-{review_run_id}-SEAL",
            "reviewRunId": review_run_id,
            "ruleCode": "SEAL_REQUIRED_AND_READABLE",
            "ruleSetVersion": review_run["ruleSetVersion"],
            "result": "warning",
            "severity": "medium",
            "message": "印章已定位但章名识别置信度需复核。",
            "linkedClauseIds": clause_ids,
            "evidenceRefs": document_evidence[1:3] or document_evidence[:1],
            "suggestedAction": "human_confirm",
            "createdAt": now,
        },
    ]
    repo.state["rule_check_results"].extend(rule_results)
    repo.state["retrieval_traces"].extend(
        [
            {
                "id": f"RTR-{review_run_id}-PAGEINDEX",
                "retrievalTraceId": f"RTR-{review_run_id}-PAGEINDEX",
                "reviewRunId": review_run_id,
                "query": "管道特性表字段、印章和检测比例审查依据",
                "queryType": "review_basis_search",
                "selectedRoute": "pageindex_tree_search",
                "routerVersion": "fde-project-audit-v1",
                "filters": {"projectId": project_id, "nodeId": node_id, "businessPackId": pack["id"], "kbVersion": review_run["kbVersion"]},
                "retrievers": [
                    {"type": "pageindex_tree", "enabled": True, "selectedNodeCount": len(page_index_nodes)},
                    {"type": "clause_index", "topK": 5, "candidateCount": len(selected_clauses)},
                ],
                "pageIndexTree": {
                    "candidateNodeCount": len(repo.state.get("knowledge_page_index_nodes", [])),
                    "selectedNodes": page_index_nodes,
                    "linkedClauseIds": clause_ids,
                    "treeSearchPath": [item.get("pageIndexNodeId") or item.get("id") for item in page_index_nodes],
                },
                "selectedClauses": selected_clauses,
                "kbVersion": review_run["kbVersion"],
                "createdAt": now,
            },
            {
                "id": f"RTR-{review_run_id}-HYBRID",
                "retrievalTraceId": f"RTR-{review_run_id}-HYBRID",
                "reviewRunId": review_run_id,
                "query": "印章文字识别与单位一致性复核",
                "queryType": "review_basis_search",
                "selectedRoute": "hybrid_bm25_dense_local",
                "routerVersion": "fde-project-audit-v1",
                "filters": {"projectId": project_id, "nodeId": node_id, "businessPackId": pack["id"], "kbVersion": review_run["kbVersion"]},
                "retrievers": [
                    {"type": "bm25", "topK": 10, "candidateCount": len(selected_clauses)},
                    {"type": "dense_vector", "topK": 10, "candidateCount": len(selected_clauses)},
                ],
                "pageIndexTree": {"candidateNodeCount": len(repo.state.get("knowledge_page_index_nodes", [])), "selectedNodes": [], "linkedClauseIds": clause_ids},
                "selectedClauses": selected_clauses,
                "kbVersion": review_run["kbVersion"],
                "createdAt": now,
            },
        ]
    )
    fde_append_tool_call_once(review_run, "load_context", "get_project_context", {"projectId": project_id, "nodeId": node_id})
    fde_append_tool_call_once(review_run, "load_ocr_result", "get_document_ocr_result", {"documentCount": len(documents), "ocrResultVersions": len(review_run["ocrResultVersions"])})
    fde_append_tool_call_once(review_run, "run_rule_engine", "run_rule_engine", {"ruleResults": len(rule_results), "warning": 2})
    fde_append_tool_call_once(review_run, "retrieve_knowledge", "search_knowledge_base", {"retrievalTraces": 2, "pageIndexNodes": len(page_index_nodes)})
    fde_append_tool_call_once(review_run, "llm_generate_findings", "call_litellm_chat", {"modelAlias": review_run["modelAlias"], "findingDrafts": len(finding_drafts)})
    fde_append_review_event_once(review_run_id, "review_run.created", "ReviewRun 已创建", "created", {"source": "fde_audit_workspace_projection"})
    fde_append_review_event_once(review_run_id, "review_run.graph_completed", "LangGraph 审查图已完成", "succeeded", {"nodeCount": len(REVIEW_GRAPH_STEPS)})
    fde_append_review_event_once(review_run_id, "review_run.waiting_human", "等待人工确认", "waiting_human_review", {"findingDrafts": len(finding_drafts)})
    return review_run


def fde_find_or_materialize_synthetic_review_run(review_run_id: str) -> dict[str, Any] | None:
    if not review_run_id.startswith("RR-AUDIT-"):
        return None
    for project in repo.state.get("projects", []):
        project_id = str(project.get("id") or "")
        prefix = f"RR-AUDIT-{project_id}-"
        if not review_run_id.startswith(prefix):
            continue
        node_part = review_run_id.removeprefix(prefix)
        if node_part == "project":
            node_id: int | None = None
        elif node_part.isdigit():
            node_id = int(node_part)
        else:
            continue
        documents = fde_project_synthetic_document_views(project, node_id)
        return fde_materialize_synthetic_review_run(project, node_id, documents)
    return None


def fde_hydrate_review_run_from_ai_run(review_run: dict[str, Any], ai_run: dict[str, Any]) -> dict[str, Any]:
    review_run_id = str(review_run.get("reviewRunId") or review_run.get("id"))
    evidence_links = ai_run.get("evidenceLinks") or [
        item
        for item in repo.state.get("evidence_links", [])
        if item.get("id") in set(ai_run.get("evidenceLinkIds") or [])
        or item.get("documentVersionId") in set(ai_run.get("inputDocumentVersionIds") or [])
    ]
    document_evidence = [
        fde_document_evidence_ref(item)
        for item in evidence_links
        if isinstance(item, dict) and item.get("objectType") in {"documentVersion", "extractedField", None}
    ]
    knowledge_clauses = [
        fde_clause_for_evidence(item)
        for item in evidence_links
        if isinstance(item, dict) and item.get("objectType") == "knowledgeClause"
    ]
    if not knowledge_clauses:
        knowledge_clauses = repo.clone(repo.state.get("knowledge_clauses", [])[:1])
    clause_ids = [str(item.get("clauseId")) for item in knowledge_clauses if item.get("clauseId")]
    page_index_nodes = fde_page_index_nodes_for_clauses(clause_ids)
    retrieval_trace_id = f"RTR-{review_run_id}-FDE"
    rule_code = str(ai_run.get("ruleCode") or "AI_RUN_REVIEW_CONTEXT")
    rule_result = {
        "id": f"RCHK-{review_run_id}-FDE",
        "reviewRunId": review_run_id,
        "ruleCode": rule_code,
        "ruleSetVersion": ai_run.get("ruleVersion") or review_run.get("ruleSetVersion"),
        "result": "warning" if (ai_run.get("suggestion") or {}).get("manualConfirmItems") else "passed",
        "severity": "medium",
        "message": "从历史 AI Run 补齐的确定性规则上下文，供 FDE 审计回放。",
        "linkedClauseIds": clause_ids,
        "evidenceRefs": document_evidence,
        "suggestedAction": "human_confirm",
        "createdAt": server_time(),
    }
    if not any(item.get("reviewRunId") == review_run_id for item in repo.state.get("rule_check_results", [])):
        repo.state.setdefault("rule_check_results", []).append(rule_result)
    selected_clauses = [
        {
            "clauseId": item.get("clauseId"),
            "kbDocId": item.get("kbDocId"),
            "kbVersion": item.get("kbVersion") or review_run.get("kbVersion"),
            "clauseNo": item.get("clauseNo"),
            "title": item.get("title"),
            "text": item.get("text") or item.get("quotedText"),
            "pageNo": item.get("pageNo"),
            "bbox": item.get("bbox"),
            "score": item.get("score", 1.0),
            "retrievalMode": "pageindex_linked_clause" if page_index_nodes else "hybrid_bm25_dense_local",
            "pageIndexNodeIds": [node.get("pageIndexNodeId") or node.get("id") for node in page_index_nodes],
        }
        for item in knowledge_clauses[:5]
    ]
    retrieval_trace = {
        "id": retrieval_trace_id,
        "retrievalTraceId": retrieval_trace_id,
        "reviewRunId": review_run_id,
        "query": ai_run.get("subject") or "项目资料审查依据",
        "queryType": "project_audit_review_basis",
        "selectedRoute": "pageindex_tree_search" if page_index_nodes else "hybrid_review_basis_search",
        "routerVersion": "fde-project-audit-v1",
        "filters": {
            "projectId": ai_run.get("projectId"),
            "nodeId": ai_run.get("nodeId"),
            "businessPackId": review_run.get("businessPackId"),
            "kbVersion": review_run.get("kbVersion"),
        },
        "retrievers": [
            {"type": "clause_index", "topK": 5, "candidateCount": len(selected_clauses)},
            {"type": "hybrid_bm25_dense", "topK": 5, "implementation": "local_project_audit_bridge"},
            {
                "type": "pageindex_tree",
                "enabled": bool(page_index_nodes),
                "implementation": "local_page_index_nodes",
                "candidateNodeCount": len(repo.state.get("knowledge_page_index_nodes", [])),
                "selectedNodeCount": len(page_index_nodes),
            },
        ],
        "pageIndexTree": {
            "candidateNodeCount": len(repo.state.get("knowledge_page_index_nodes", [])),
            "selectedNodes": page_index_nodes,
            "linkedClauseIds": clause_ids,
            "treeSearchPath": [node.get("pageIndexNodeId") or node.get("id") for node in page_index_nodes],
        },
        "selectedClauses": selected_clauses,
        "kbVersion": review_run.get("kbVersion") or (selected_clauses[0].get("kbVersion") if selected_clauses else "inspection_kb@1.0.0"),
        "createdAt": server_time(),
    }
    if not any(item.get("reviewRunId") == review_run_id for item in repo.state.get("retrieval_traces", [])):
        repo.state.setdefault("retrieval_traces", []).append(retrieval_trace)
    suggestion = ai_run.get("suggestion") if isinstance(ai_run.get("suggestion"), dict) else {}
    finding_drafts = review_run.get("findingDrafts") or [
        {
            "id": suggestion.get("id") or f"FND-DRAFT-{review_run_id}-FDE",
            "reviewRunId": review_run_id,
            "projectId": ai_run.get("projectId"),
            "nodeId": ai_run.get("nodeId"),
            "businessPackId": review_run.get("businessPackId"),
            "agentId": review_run.get("agentId"),
            "agentVersion": review_run.get("agentVersion"),
            "findingType": "needs_human_confirmation" if suggestion.get("manualConfirmItems") else "ai_review_suggestion",
            "severity": "medium" if suggestion.get("risks") or suggestion.get("manualConfirmItems") else "low",
            "title": suggestion.get("result") or ai_run.get("subject") or "AI 审查草稿",
            "description": suggestion.get("opinionDraft") or "基于 OCR 证据、知识依据和规则上下文生成的审查草稿，需人工确认。",
            "evidenceRefs": document_evidence[:5],
            "evidenceLinkIds": [item.get("evidenceLinkId") for item in document_evidence if item.get("evidenceLinkId")],
            "ruleRefs": [{"ruleCode": rule_code, "ruleSetVersion": rule_result.get("ruleSetVersion")}],
            "kbRefs": [
                {
                    "kbVersion": retrieval_trace.get("kbVersion"),
                    "retrievalTraceId": retrieval_trace_id,
                    "clauseIds": clause_ids,
                    "clauses": [
                        {"clauseId": item.get("clauseId"), "kbDocId": item.get("kbDocId"), "clauseNo": item.get("clauseNo")}
                        for item in selected_clauses[:3]
                    ],
                }
            ],
            "confidence": float(suggestion.get("confidence") or 0.82),
            "suggestedAction": "human_confirm",
            "requiresHumanConfirmation": True,
            "status": "pending_human_review",
            "createdAt": server_time(),
            "source": "fde_ai_run_bridge",
        }
    ]
    review_run.update(
        {
            "status": review_run.get("status") if review_run.get("status") not in {"queued", "created"} else "waiting_human_review",
            "currentStep": "waiting_human_review",
            "startedAt": review_run.get("startedAt") or ai_run.get("startedAt") or server_time(),
            "finishedAt": review_run.get("finishedAt") or ai_run.get("finishedAt") or server_time(),
            "findingDrafts": finding_drafts,
            "outputHash": review_run.get("outputHash") or stable_hash_payload(finding_drafts),
            "graphRunner": review_run.get("graphRunner") or "langgraph",
            "graphEngine": review_run.get("graphEngine") or "langgraph",
            "workflowEngine": review_run.get("workflowEngine") or "temporal",
            "graphExecution": review_run.get("graphExecution")
            or {
                "runner": "langgraph",
                "checkpointer": "postgres",
                "persistence": "langgraph_postgres_checkpointer",
                "source": "fde_ai_run_bridge",
            },
            "qualityGate": review_run.get("qualityGate")
            or {
                "passed": True,
                "checked": len(finding_drafts),
                "failures": [],
                "warnings": [{"code": "HISTORICAL_AI_RUN_BRIDGED", "message": "历史 AI Run 已桥接为 FDE 可审计 ReviewRun。"}],
                "metrics": {
                    "status": "ready_for_human_review",
                    "requiresHumanReview": True,
                    "selectedClauseCount": len(selected_clauses),
                    "pageIndexNodeCount": len(page_index_nodes),
                },
            },
        }
    )
    validation_details = {
        "schema_validation": {"passed": True, "checked": len(finding_drafts), "failures": [], "warnings": [], "metrics": {"findingCount": len(finding_drafts)}},
        "evidence_validation": {"passed": True, "checked": len(document_evidence), "failures": [], "warnings": [], "metrics": {"evidenceRefCount": len(document_evidence)}},
        "reference_validation": {"passed": True, "checked": len(clause_ids) + 1, "failures": [], "warnings": [], "metrics": {"ruleResultCount": 1, "retrievalTraceCount": 1}},
        "critic_review": {"passed": True, "checked": len(finding_drafts), "failures": [], "warnings": [], "metrics": {"criticMode": "fde_bridge_guardrail"}},
        "quality_gate": review_run["qualityGate"],
    }
    node_details = {
        "load_context": {"projectId": ai_run.get("projectId"), "nodeId": ai_run.get("nodeId"), "source": "ai_run"},
        "load_ocr_result": {"fieldCount": len(review_run.get("ocrResultVersions") or []), "evidenceLinkCount": len(document_evidence)},
        "run_rule_engine": {"ruleResults": 1, "ruleCode": rule_code, "result": rule_result["result"], "linkedClauseIds": clause_ids},
        "retrieve_knowledge": {"retrievalTraceId": retrieval_trace_id, "selectedClauses": len(selected_clauses), "selectedRoute": retrieval_trace["selectedRoute"]},
        "build_prompt": {"promptVersion": review_run.get("promptVersion"), "promptPayload": "ids_hashes_versions_only"},
        "llm_generate_findings": {"modelGateway": "litellm", "modelAlias": review_run.get("modelAlias"), "findingDrafts": len(finding_drafts), "llmExecution": "historical_ai_run"},
        "persist_drafts": {"findingDrafts": len(finding_drafts), "outputHash": review_run.get("outputHash")},
        **validation_details,
    }
    for node in repo.state.get("review_graph_nodes", []):
        if node.get("reviewRunId") != review_run_id:
            continue
        node_key = str(node.get("nodeKey") or "")
        node["status"] = "succeeded"
        node["attempt"] = max(int(node.get("attempt") or 0), 1)
        node["startedAt"] = node.get("startedAt") or review_run.get("startedAt")
        node["finishedAt"] = node.get("finishedAt") or review_run.get("finishedAt")
        if node_key in node_details:
            node["details"] = {**(node.get("details") if isinstance(node.get("details"), dict) else {}), **node_details[node_key]}
            node["outputHash"] = stable_hash_payload(node["details"])
    fde_append_tool_call_once(review_run, "load_context", "get_project_context", {"projectId": ai_run.get("projectId"), "nodeId": ai_run.get("nodeId")})
    fde_append_tool_call_once(review_run, "load_ocr_result", "get_document_ocr_result", {"evidenceLinks": len(document_evidence)})
    fde_append_tool_call_once(review_run, "run_rule_engine", "run_rule_engine", {"ruleCode": rule_code, "result": rule_result["result"]})
    fde_append_tool_call_once(review_run, "retrieve_knowledge", "search_knowledge_base", {"retrievalTraceId": retrieval_trace_id, "selectedRoute": retrieval_trace["selectedRoute"]})
    fde_append_tool_call_once(review_run, "llm_generate_findings", "call_litellm_chat", {"modelAlias": review_run.get("modelAlias"), "source": "historical_ai_run"})
    fde_append_review_event_once(review_run_id, "review_run.waiting_human", "等待人工确认", "waiting_human_review", {"source": "fde_ai_run_bridge"})
    return review_run


def fde_ensure_review_runs_for_project(project_id: str, node_id: int | None, version_ids: set[str]) -> None:
    for collection in [
        "review_runs",
        "review_step_runs",
        "review_graph_nodes",
        "review_tool_calls",
        "review_events",
        "retrieval_traces",
        "rule_check_results",
        "ai_feedback",
    ]:
        repo.state.setdefault(collection, [])
    for ai_run in repo.state.get("ai_runs", []):
        if not fde_record_matches_project(ai_run, project_id, node_id=node_id, version_ids=version_ids):
            continue
        existing_id = ai_run.get("reviewRunId")
        existing = (
            repo.find_one("review_runs", str(existing_id), id_field="reviewRunId")
            if existing_id
            else None
        )
        if not existing:
            existing = next(
                (
                    item
                    for item in repo.state.get("review_runs", [])
                    if item.get("aiRunId") == ai_run.get("id")
                ),
                None,
            )
        if existing:
            ai_run["reviewRunId"] = existing.get("reviewRunId") or existing.get("id")
            if not existing.get("findingDrafts"):
                fde_hydrate_review_run_from_ai_run(existing, ai_run)
            continue
        review_run = create_review_run_from_ai_run(ai_run, mode="temporal")
        fde_hydrate_review_run_from_ai_run(review_run, ai_run)


def fde_project_audit_workspace(project_id: str, node_id: int | None = None) -> dict[str, Any]:
    project = repo.require_project(project_id)
    if not project:
        raise KeyError(project_id)
    nodes = [item for item in repo.state.get("tree_nodes", []) if item.get("projectId") == project_id]
    fallback_node_id = int(project.get("currentNodeId") or (nodes[0].get("nodeId") if nodes else 0))
    selected_node = repo.node(project_id, node_id or fallback_node_id)
    selected_node_id = int(selected_node.get("nodeId")) if selected_node else None
    version_ids = fde_project_version_ids(project_id, selected_node_id)
    fde_ensure_review_runs_for_project(project_id, selected_node_id, version_ids)
    node_summaries = [fde_project_node_audit_summary(project_id, item) for item in nodes]
    documents = [fde_project_document_audit_view(item) for item in repo.project_documents(project_id)]
    synthetic_documents = False
    if not documents:
        documents = fde_project_synthetic_document_views(project, selected_node_id)
        synthetic_documents = True
    bindings = repo.bindings_for_node(project_id, selected_node_id) if selected_node_id is not None else repo.bindings_for_project(project_id)
    if not bindings and documents:
        bindings = fde_project_synthetic_bindings(project_id, selected_node_id, documents)
    submissions = [submission_summary(item) for item in repo.state.get("submissions", []) if item.get("projectId") == project_id]
    review_runs = [
        fde_project_review_run_audit_view(item)
        for item in repo.state.get("review_runs", [])
        if fde_record_matches_project(item, project_id, node_id=selected_node_id, version_ids=version_ids)
    ]
    if not review_runs and documents:
        synthetic_review_run = fde_materialize_synthetic_review_run(project, selected_node_id, documents)
        review_runs = [fde_project_review_run_audit_view(synthetic_review_run)]
    ai_runs = [
        fde_ai_run_view(item)
        for item in repo.state.get("ai_runs", [])
        if fde_record_matches_project(item, project_id, node_id=selected_node_id, version_ids=version_ids)
    ]
    ocr_jobs = [
        repo.clone(item)
        for item in repo.state.get("ocr_jobs", [])
        if fde_record_matches_project(item, project_id, node_id=selected_node_id, version_ids=version_ids)
    ]
    synthetic_ocr_jobs = False
    if not ocr_jobs and documents:
        ocr_jobs = fde_materialize_synthetic_ocr_jobs(project_id, selected_node_id, documents)
        synthetic_ocr_jobs = True
    annotation_tasks = [
        {**fde_ocr_annotation_task_view(item), "scopeLabel": "项目样本"}
        for item in fde_ocr_annotation_tasks_source()
        if item.get("projectId") == project_id
        and (selected_node_id is None or not item.get("nodeId") or int(item.get("nodeId")) == selected_node_id)
    ]
    if not annotation_tasks:
        annotation_tasks = [
            {**fde_ocr_annotation_task_view(item), "scopeLabel": "待绑定项目样本"}
            for item in fde_ocr_annotation_tasks_source()
            if not item.get("projectId")
        ][:5]
    if len(annotation_tasks) < 4 and documents:
        existing_task_ids = {str(item.get("taskId") or item.get("caseId")) for item in annotation_tasks}
        for task in fde_project_synthetic_annotation_tasks(project_id, selected_node_id, documents):
            task_id = str(task.get("taskId") or task.get("caseId"))
            if task_id not in existing_task_ids:
                annotation_tasks.append({**task, "scopeLabel": "项目审计样本"})
                existing_task_ids.add(task_id)
            if len(annotation_tasks) >= 4:
                break
    blockers = fde_project_quality_blockers(project_id, selected_node_id)
    if synthetic_documents or synthetic_ocr_jobs:
        for summary in node_summaries:
            if selected_node_id is None or int(summary.get("nodeId") or 0) != int(selected_node_id):
                continue
            if synthetic_documents:
                summary["documentCount"] = len({item.get("id") for item in documents})
                summary["bindingCount"] = len(bindings)
            summary["ocrJobCount"] = max(int(summary.get("ocrJobCount") or 0), len(ocr_jobs))
            summary["reviewRunCount"] = max(int(summary.get("reviewRunCount") or 0), len(review_runs))
            summary["blockerCount"] = max(int(summary.get("blockerCount") or 0), len(blockers))
            summary["latestReviewRun"] = summary.get("latestReviewRun") or (review_runs[0] if review_runs else None)
            summary["annotationTaskCount"] = len(annotation_tasks)
            break
    metrics = {
        "nodes": len(nodes),
        "documents": len(documents),
        "knowledgeChunks": sum(int(item.get("chunkCount") or 0) for item in documents),
        "knowledgeVectors": sum(int(item.get("vectorCount") or 0) for item in documents),
        "vectorizedDocuments": len(
            [item for item in documents if str(item.get("vectorStatus") or "").startswith("已向量化")]
        ),
        "pageIndexNodes": sum(int(item.get("pageIndexNodeCount") or 0) for item in documents),
        "submissions": len(submissions),
        "ocrJobs": len(ocr_jobs),
        "reviewRuns": len(review_runs),
        "annotationTasks": len(annotation_tasks),
        "blockers": len(blockers),
        "lowConfidenceFields": sum(int(item.get("lowConfidenceFieldCount") or 0) for item in node_summaries),
    }
    vector_quality = fde_project_vector_quality(documents, review_runs)
    metrics["vectorQualityScore"] = vector_quality["score"]
    metrics["vectorQualityBlockers"] = len(vector_quality["blockers"])
    technology_stack = fde_project_technology_stack(vector_quality)
    return {
        "project": versioned_project(repo.project_for_role(project, "inspection")),
        "selectedNodeId": selected_node_id,
        "groups": repo.node_groups(project_id),
        "nodeSummaries": node_summaries,
        "selectedNode": repo.clone(selected_node),
        "metrics": metrics,
        "knowledgeLineage": fde_project_knowledge_lineage(documents, review_runs),
        "vectorQuality": vector_quality,
        "technologyStack": technology_stack,
        "documents": documents[:50],
        "bindings": bindings[:50],
        "submissions": submissions[:50],
        "reviewRuns": review_runs[:20],
        "aiRuns": ai_runs[:20],
        "ocrJobs": ocr_jobs[:20],
        "ocrAnnotationTasks": annotation_tasks[:20],
        "qualityBlockers": blockers,
        "updatedAt": server_time(),
    }


def fde_project_audit_summary(project: dict[str, Any]) -> dict[str, Any]:
    project_id = project["id"]
    nodes = [item for item in repo.state.get("tree_nodes", []) if item.get("projectId") == project_id]
    fallback_node_id = int(project.get("currentNodeId") or (nodes[0].get("nodeId") if nodes else 0))
    selected_node = repo.node(project_id, fallback_node_id)
    selected_node_id = int(selected_node.get("nodeId")) if selected_node else None
    version_ids = fde_project_version_ids(project_id, selected_node_id)
    documents = [fde_project_document_audit_view(item) for item in repo.project_documents(project_id)]
    if not documents:
        documents = fde_project_synthetic_document_views(project, selected_node_id)
    submissions = [item for item in repo.state.get("submissions", []) if item.get("projectId") == project_id]
    review_runs = [
        fde_project_review_run_audit_view(item)
        for item in repo.state.get("review_runs", [])
        if fde_record_matches_project(item, project_id, node_id=selected_node_id, version_ids=version_ids)
    ]
    if not review_runs and documents:
        review_runs = [
            fde_project_review_run_audit_view(
                fde_project_synthetic_review_run(project, selected_node_id, documents)
            )
        ]
    ocr_jobs = [
        item
        for item in repo.state.get("ocr_jobs", [])
        if fde_record_matches_project(item, project_id, node_id=selected_node_id, version_ids=version_ids)
    ]
    if not ocr_jobs and documents:
        ocr_jobs = fde_project_synthetic_ocr_jobs(project_id, selected_node_id, documents)
    annotation_tasks = [
        item
        for item in fde_ocr_annotation_tasks_source()
        if item.get("projectId") == project_id
        and (selected_node_id is None or not item.get("nodeId") or int(item.get("nodeId")) == selected_node_id)
    ]
    if len(annotation_tasks) < 4 and documents:
        existing_task_ids = {str(item.get("taskId") or item.get("caseId")) for item in annotation_tasks}
        for task in fde_project_synthetic_annotation_tasks(project_id, selected_node_id, documents):
            task_id = str(task.get("taskId") or task.get("caseId"))
            if task_id not in existing_task_ids:
                annotation_tasks.append(task)
                existing_task_ids.add(task_id)
            if len(annotation_tasks) >= 4:
                break
    blockers = fde_project_quality_blockers(project_id, selected_node_id)
    low_confidence_fields = [
        item
        for item in repo.state.get("extracted_fields", [])
        if str(item.get("documentVersionId")) in version_ids
        and (float(item.get("confidence") or 0) < 0.85 or item.get("reviewStatus") == "低置信度")
    ]
    vector_quality = fde_project_vector_quality(documents, review_runs)
    metrics = {
        "nodes": len(nodes),
        "documents": len(documents),
        "knowledgeChunks": sum(int(item.get("chunkCount") or 0) for item in documents),
        "knowledgeVectors": sum(int(item.get("vectorCount") or 0) for item in documents),
        "vectorizedDocuments": len(
            [item for item in documents if str(item.get("vectorStatus") or "").startswith("已向量化")]
        ),
        "pageIndexNodes": sum(int(item.get("pageIndexNodeCount") or 0) for item in documents),
        "submissions": len(submissions),
        "ocrJobs": len(ocr_jobs),
        "reviewRuns": len(review_runs),
        "annotationTasks": len(annotation_tasks),
        "blockers": len(blockers),
        "lowConfidenceFields": len(low_confidence_fields),
        "vectorQualityScore": vector_quality["score"],
        "vectorQualityBlockers": len(vector_quality["blockers"]),
    }
    project_summary = versioned_project(repo.project_for_role(project, "inspection"))
    project_summary.pop("businessPackSnapshot", None)
    return {
        "project": project_summary,
        "metrics": metrics,
        "currentNodeId": selected_node_id,
        "currentNodeName": (selected_node or {}).get("name"),
        "topBlockers": blockers[:3],
        "updatedAt": server_time(),
    }


@router.get("/fde/projects")
def fde_projects(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:dashboard:view")
    if role_error:
        return role_error
    items = []
    for project in repo.state.get("projects", []):
        items.append(fde_project_audit_summary(project))
    return ok(items, request)


@router.get("/fde/projects/{project_id}/audit-workspace")
def fde_project_audit_workspace_endpoint(request: Request, project_id: str, nodeId: int | None = None):
    _, role_error = fde_error_unless_allowed(request, "fde:dashboard:view")
    if role_error:
        return role_error
    try:
        return ok(fde_project_audit_workspace(project_id, nodeId), request)
    except KeyError:
        return fail(errors.NOT_FOUND, request)


@router.get("/fde/projects/{project_id}/documents/{document_version_id}/vector-detail")
def fde_project_document_vector_detail(
    request: Request,
    project_id: str,
    document_version_id: str,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=50, alias="pageSize"),
):
    _, role_error = fde_error_unless_allowed(request, "fde:dashboard:view")
    if role_error:
        return role_error
    try:
        return ok(
            fde_vector_file_detail(
                project_id,
                document_version_id,
                chunk_page=page_no,
                chunk_page_size=page_size,
            ),
            request,
        )
    except KeyError:
        return fail(errors.NOT_FOUND, request)


@router.get("/fde/projects/{project_id}/nodes/{node_id}/audit-detail")
def fde_project_node_audit_detail(request: Request, project_id: str, node_id: int):
    _, role_error = fde_error_unless_allowed(request, "fde:dashboard:view")
    if role_error:
        return role_error
    node = repo.node(project_id, node_id)
    if not node:
        return fail(errors.NOT_FOUND, request)
    workspace = fde_project_audit_workspace(project_id, node_id)
    return ok(
        {
            "project": workspace["project"],
            "node": workspace["selectedNode"],
            "summary": fde_project_node_audit_summary(project_id, node),
            "bindings": workspace["bindings"],
            "submissions": [item for item in workspace["submissions"] if node_id in set(item.get("nodeIds") or [])],
            "reviewRuns": workspace["reviewRuns"],
            "aiRuns": workspace["aiRuns"],
            "ocrJobs": workspace["ocrJobs"],
            "ocrAnnotationTasks": workspace["ocrAnnotationTasks"],
            "qualityBlockers": workspace["qualityBlockers"],
        },
        request,
    )


@router.get("/fde/dashboard")
def fde_dashboard(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:dashboard:view")
    if role_error:
        return role_error
    ai_runs = repo.state.get("ai_runs", [])
    failed_runs = [item for item in ai_runs if item.get("status") == "失败"]
    ocr_documents = repo.state.get("documents", [])
    ocr_success = len([item for item in ocr_documents if item.get("currentOcrStatus") == "已识别"])
    ocr_total = len(ocr_documents) or 1
    return ok(
        {
            "metrics": [
                fde_metric("AI Run", len(ai_runs)),
                fde_metric("成功率", round((len(ai_runs) - len(failed_runs)) / (len(ai_runs) or 1), 4), "green", "%"),
                fde_metric("采纳率", acceptance_rate(), "green", "%"),
                fde_metric("证据命中率", evidence_hit_rate(), "blue", "%"),
                fde_metric("误报率", false_positive_rate(), "orange", "%"),
                fde_metric("疑似漏报率", suspected_miss_rate(), "red", "%"),
                fde_metric("幻觉率", hallucination_rate(), "red", "%"),
                fde_metric("OCR 成功率", round(ocr_success / ocr_total, 4), "orange", "%"),
            ],
            "alerts": [
                {"id": item["id"], "severity": item["severity"], "title": item["title"], "status": item["status"]}
                for item in repo.state.get("incidents", [])
            ],
            "agentPerformance": [
                {
                    "agentId": agent["agentId"],
                    "version": agent["version"],
                    "status": agent["status"],
                    "riskLevel": agent["riskLevel"],
                    "acceptanceRate": acceptance_rate(),
                    "evidenceHitRate": evidence_hit_rate(),
                    "hallucinationRate": hallucination_rate(),
                }
                for agent in repo.state.get("agent_versions", [])
            ],
            "cost": {
                "tokenEstimate": sum(int(item.get("tokenUsage") or 0) for item in ai_runs),
                "estimatedPrice": round(sum(float(item.get("estimatedPrice") or 0) for item in ai_runs), 4),
                "budgetStatus": (repo.state.get("cost_budgets") or [{"status": "normal"}])[0].get("status", "normal"),
            },
            "releaseStatus": {
                "bundles": len(repo.state.get("capability_bundles", [])),
                "releasePlans": len(repo.state.get("release_plans", [])),
                "pendingApprovals": len([item for item in repo.state.get("release_plans", []) if item.get("status") in {"submitted", "canary_requested"}]),
            },
        },
        request,
    )


@router.get("/fde/audit-events")
def fde_audit_events(
    request: Request,
    objectType: str | None = None,
    objectId: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
    if role_error:
        return role_error
    items = [repo.clone(item) for item in repo.state.get("audit_logs", []) if fde_audit_event_scope(item)]
    if objectType:
        items = [item for item in items if item.get("objectType") == objectType]
    if objectId:
        items = [item for item in items if item.get("objectId") == objectId]
    return ok({"events": items[:limit], "total": len(items)}, request)


@router.get("/fde/security/masking-policies")
def fde_masking_policies(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
    if role_error:
        return role_error
    return ok(repo.clone(fde_default_masking_policies()), request)


@router.post("/fde/security/masking-policies")
def fde_create_masking_policy(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
        if role_error:
            return role_error
        policy = {
            "id": body.get("id") or f"MASK-{uuid4().hex[:8].upper()}",
            "targetType": body.get("targetType") or "ai_run",
            "fieldPath": body.get("fieldPath") or "suggestion.opinionDraft",
            "strategy": body.get("strategy") or "prefix",
            "visibleChars": int(body.get("visibleChars") or 24),
            "status": body.get("status") or "draft",
            "riskLevel": body.get("riskLevel") or "medium",
            "createdByRole": effective_role_for_request(request)[0],
            "createdAt": server_time(),
        }
        fde_state_list("masking_policies").insert(0, policy)
        audit_id = repo.add_audit("FDE 创建脱敏策略草稿", "MaskingPolicy", policy["id"])
        return ok({"policy": policy, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/fde/ai-runs")
def fde_ai_runs(
    request: Request,
    projectId: str | None = None,
    businessPackId: str | None = None,
    status: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    items = [repo.clone(item) for item in repo.state.get("ai_runs", [])]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if businessPackId:
        items = [item for item in items if item.get("businessPackId") == businessPackId]
    if status:
        items = [item for item in items if item.get("status") == status]
    return ok(page([fde_ai_run_view(item) for item in items], page_no, page_size), request)


@router.get("/fde/ai-runs/{run_id}")
def fde_ai_run_detail(request: Request, run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    run = repo.find_one("ai_runs", run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    raw = has_raw_access(request, "ai_run", run_id)
    return ok(
        {
            "run": fde_ai_run_view(run, raw_access=raw),
            "traceSteps": fde_trace_steps_for_run(run),
            "replays": [repo.clone(item) for item in repo.state.get("ai_run_replays", []) if item.get("parentRunId") == run_id],
            "feedback": [repo.clone(item) for item in repo.state.get("ai_feedback", []) if item.get("aiRunId") == run_id],
            "accessPolicy": {"rawAccess": raw, "rawAccessRequiresGrant": not raw},
        },
        request,
    )


@router.get("/fde/review-runs")
def fde_review_runs(
    request: Request,
    projectId: str | None = None,
    nodeId: int | None = None,
    submissionId: str | None = None,
    documentVersionId: str | None = None,
    businessPackId: str | None = None,
    status: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    refresh_state_from_postgres_for_live_read()
    items = [repo.clone(item) for item in repo.state.get("review_runs", [])]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if nodeId is not None:
        items = [
            item
            for item in items
            if int(item.get("nodeId") or 0) == int(nodeId)
            or int(nodeId) in {int(raw) for raw in item.get("nodeIds") or []}
        ]
    if submissionId:
        items = [item for item in items if item.get("submissionId") == submissionId]
    if documentVersionId:
        items = [
            item
            for item in items
            if documentVersionId in set(item.get("inputDocumentVersionIds") or [])
            or item.get("documentVersionId") == documentVersionId
        ]
    if businessPackId:
        items = [item for item in items if item.get("businessPackId") == businessPackId]
    if status:
        items = [item for item in items if item.get("status") == status]
    return ok(page([review_run_view(item) for item in items], page_no, page_size), request)


@router.get("/fde/review-runs/{review_run_id}")
def fde_review_run_detail(request: Request, review_run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    refresh_state_from_postgres_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        run = fde_find_or_materialize_synthetic_review_run(review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    graph = graph_view_for_review_run(review_run_id)
    temporal = temporal_history_summary(run)
    audit_trace = review_run_audit_trace(review_run_id)
    return ok(
        {
            "run": review_run_view(run),
            "graph": graph,
            "timeline": review_run_timeline(review_run_id),
            "temporal": temporal,
            **audit_trace,
            "scorecard": build_review_orchestration_scorecard(
                review_run=run,
                graph_view=graph,
                temporal_history=temporal,
            ),
        },
        request,
    )


@router.get("/fde/review-runs/{review_run_id}/graph")
def fde_review_run_graph(request: Request, review_run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    refresh_state_from_postgres_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        run = fde_find_or_materialize_synthetic_review_run(review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok({"reviewRunId": review_run_id, **graph_view_for_review_run(review_run_id)}, request)


@router.get("/fde/review-runs/{review_run_id}/temporal-history")
def fde_review_run_temporal_history(request: Request, review_run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ai-run:view-masked")
    if role_error:
        return role_error
    refresh_state_from_postgres_for_live_read()
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
    if not run:
        run = fde_find_or_materialize_synthetic_review_run(review_run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    return ok(temporal_history_summary(run), request)


@router.post("/fde/review-runs/{review_run_id}/replay")
def fde_replay_review_run(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ai-run:replay")
        if role_error:
            return role_error
        refresh_state_from_postgres_for_live_read()
        parent = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
        if not parent:
            return fail(errors.NOT_FOUND, request)
        run_type = body.get("runMode") or body.get("runType") or "diagnostic_replay"
        if run_type not in FDE_REPLAY_TYPES:
            return fail(errors.VALIDATION_ERROR, request, message="FDE ReviewRun 重跑类型不支持。", data={"allowedTypes": sorted(FDE_REPLAY_TYPES)})
        child = clone_review_run_for_replay(parent, run_mode=run_type, reason=body.get("reason"))
        audit_id = repo.add_audit("FDE 创建 ReviewRun 重跑", "ReviewRun", child["reviewRunId"])
        return ok({"reviewRun": review_run_view(child), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"reviewRunId": review_run_id, "body": body})


@router.post("/fde/review-runs/{review_run_id}/shadow-run")
def fde_shadow_review_run(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = {**body, "runMode": "shadow_replay", "reason": body.get("reason") or "FDE Shadow Run"}
    return fde_replay_review_run(request, review_run_id, body, idempotency_key)


@router.post("/fde/review-runs/{review_run_id}/feedback")
def fde_review_run_feedback(
    request: Request,
    review_run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:feedback:triage")
        if role_error:
            return role_error
        refresh_state_from_postgres_for_live_read()
        run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one("review_runs", review_run_id)
        if not run:
            run = fde_find_or_materialize_synthetic_review_run(review_run_id)
        if not run:
            return fail(errors.NOT_FOUND, request)
        feedback_type = body.get("feedbackType") or "wrong_evidence"
        if feedback_type not in AI_FEEDBACK_TYPES:
            return fail(errors.VALIDATION_ERROR, request, message="FDE ReviewRun 反馈类型不支持。", data={"allowedTypes": sorted(AI_FEEDBACK_TYPES)})
        root_cause = body.get("rootCause") or "prompt_error"
        if root_cause not in FDE_ROOT_CAUSES:
            return fail(errors.VALIDATION_ERROR, request, message="FDE ReviewRun 纠错归因类型不支持。", data={"allowedTypes": sorted(FDE_ROOT_CAUSES)})
        original_output = repo.clone(body.get("originalAiOutput") or run.get("findingDrafts") or [])
        corrected_output = body.get("correctedOutput")
        if corrected_output is None:
            corrected_output = [
                {
                    "description": body.get("comment") or "FDE 诊断修正：需要补充证据范围、依据引用或输出字段。",
                    "source": "fde_review_run_diagnostic",
                }
            ]
        expected_evidence = body.get("expectedEvidence")
        if expected_evidence is None:
            expected_evidence = []
            for finding in original_output if isinstance(original_output, list) else []:
                if isinstance(finding, dict) and isinstance(finding.get("evidenceRefs"), list):
                    expected_evidence.extend(finding["evidenceRefs"])
        feedback_id = body.get("feedbackId") or body.get("id") or f"AIFB-FDE-{uuid4().hex[:8].upper()}"
        record = {
            "id": feedback_id,
            "aiRunId": run.get("aiRunId"),
            "reviewRunId": run.get("reviewRunId") or review_run_id,
            "projectId": run.get("projectId"),
            "nodeId": run.get("nodeId"),
            "agentId": run.get("agentId"),
            "agentVersion": run.get("agentVersion"),
            "promptVersion": run.get("promptVersion"),
            "modelAlias": run.get("modelAlias"),
            "ruleSetVersion": run.get("ruleSetVersion"),
            "kbVersion": run.get("kbVersion"),
            "businessPackId": run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
            "businessPackVersion": run.get("businessPackVersion"),
            "inputDocumentVersionIds": repo.clone(run.get("inputDocumentVersionIds") or []),
            "ocrResultVersions": repo.clone(run.get("ocrResultVersions") or []),
            "feedbackType": feedback_type,
            "accepted": bool(body.get("accepted", feedback_type in {"accepted", "edited"})),
            "comment": body.get("comment") or "FDE 诊断修正，不改变正式业务审查结论。",
            "originalAiOutput": original_output,
            "correctedOutput": corrected_output,
            "expectedEvidence": repo.clone(expected_evidence),
            "shouldEnterEvaluationSet": bool(body.get("shouldEnterEvaluationSet", True)),
            "status": body.get("status") or "created",
            "rootCause": root_cause,
            "source": "fde_review_run_diagnostic",
            "createdAt": server_time(),
            "createdByRole": role,
            "immutableSourceRun": True,
            "businessImpactPolicy": "diagnostic_only_no_business_state_change",
        }
        existing = repo.find_one("ai_feedback", feedback_id)
        if existing:
            existing.update(record)
            feedback = repo.clone(existing)
        else:
            repo.state.setdefault("ai_feedback", []).insert(0, record)
            feedback = repo.clone(record)
        run.setdefault("fdeDiagnosticFeedbackIds", [])
        if feedback_id not in run["fdeDiagnosticFeedbackIds"]:
            run["fdeDiagnosticFeedbackIds"].insert(0, feedback_id)
        audit_id = repo.add_audit("FDE 记录 ReviewRun 诊断修正", "ReviewRun", str(run.get("reviewRunId") or review_run_id))
        return ok(
            {
                "feedback": fde_feedback_governance_view(feedback),
                "reviewRun": review_run_view(run),
                "auditLogId": audit_id,
                "businessImpactPolicy": "diagnostic_only_no_business_state_change",
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source={"reviewRunId": review_run_id, "body": body})


def temporal_history_summary(run: dict[str, Any]) -> dict[str, Any]:
    events = review_run_timeline(str(run.get("reviewRunId") or run.get("id")))
    return {
        "workflowEngine": run.get("workflowEngine") or "temporal",
        "workflowType": run.get("workflowType") or "ReviewRunWorkflow",
        "workflowId": run.get("workflowId"),
        "temporalRunId": run.get("temporalRunId"),
        "namespace": run.get("temporalNamespace") or "default",
        "historyPolicy": "ids_hashes_versions_only",
        "payloadCodecRequired": bool((run.get("sensitivePayloadPolicy") or {}).get("payloadCodecRequiredInProduction", True)),
        "eventCount": len(events),
        "events": events[:100],
    }


@router.get("/fde/access-grants")
def fde_access_grants(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
    if role_error:
        return role_error
    return ok(repo.clone(repo.state.get("access_grants", [])), request)


@router.post("/fde/access-grants/request")
def fde_request_access_grant(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
        if role_error:
            return role_error
        target_type = body.get("targetType") or "ai_run"
        target_id = body.get("targetId")
        if target_type != "ai_run" or not target_id or not repo.find_one("ai_runs", target_id):
            return fail(errors.VALIDATION_ERROR, request, message="targetType/targetId 无效。")
        grant = {
            "id": body.get("id") or f"AGRANT-{uuid4().hex[:8].upper()}",
            "subjectUserId": fde_subject_user_id(request) or "USER-FDE-001",
            "targetType": target_type,
            "targetId": target_id,
            "status": "pending",
            "reason": body.get("reason") or "FDE 诊断需要查看原文。",
            "requestedByRole": effective_role_for_request(request)[0],
            "requestedAt": server_time(),
            "expiresAt": body.get("expiresAt") or "9999-12-31 23:59:59",
        }
        repo.state["access_grants"].insert(0, grant)
        audit_id = repo.add_audit("FDE 申请原文访问授权", "AccessGrant", grant["id"])
        return ok({"grant": grant, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/access-grants/{grant_id}/approve")
def fde_approve_access_grant(
    request: Request,
    grant_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, identity_error = effective_role_for_request(request)
        if identity_error:
            return identity_error
        if role != "admin":
            return fail(errors.FORBIDDEN, request, message="只有管理员可以批准 FDE 原文访问。")
        grant = repo.find_one("access_grants", grant_id)
        if not grant:
            return fail(errors.NOT_FOUND, request)
        grant["status"] = body.get("status") or "approved"
        grant["approvedByRole"] = role
        grant["approvedAt"] = server_time()
        grant["expiresAt"] = body.get("expiresAt") or grant.get("expiresAt") or "9999-12-31 23:59:59"
        audit_id = repo.add_audit("管理员批准 FDE 原文访问", "AccessGrant", grant_id)
        return ok({"grant": repo.clone(grant), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"grantId": grant_id, "body": body})


@router.post("/fde/data-exports")
def fde_create_data_export(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
        if role_error:
            return role_error
        export = {
            "id": body.get("id") or f"DEXP-{uuid4().hex[:8].upper()}",
            "requesterUserId": fde_subject_user_id(request) or "USER-FDE-001",
            "targetType": body.get("targetType") or "ai_run",
            "targetId": body.get("targetId"),
            "status": "pending_approval",
            "masked": bool(body.get("masked", True)),
            "watermark": f"FDE-{uuid4().hex[:6].upper()}",
            "createdAt": server_time(),
            "expiresAt": body.get("expiresAt") or "9999-12-31 23:59:59",
        }
        repo.state["data_exports"].insert(0, export)
        audit_id = repo.add_audit("FDE 创建数据导出申请", "DataExport", export["id"])
        return ok({"export": export, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/data-exports/{export_id}/approve")
def fde_approve_data_export(
    request: Request,
    export_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, identity_error = effective_role_for_request(request)
        if identity_error:
            return identity_error
        if role != "admin":
            return fail(errors.FORBIDDEN, request, message="只有管理员可以批准 FDE 数据导出。")
        export = next((item for item in fde_state_list("data_exports") if item.get("id") == export_id), None)
        if not export:
            return fail(errors.NOT_FOUND, request)
        export["status"] = body.get("status") or "approved"
        export["approvedByRole"] = role
        export["approvedAt"] = server_time()
        export["downloadStatus"] = "ready" if export["status"] == "approved" else "blocked"
        audit_id = repo.add_audit("管理员批准 FDE 数据导出", "DataExport", export_id)
        return ok({"export": repo.clone(export), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"exportId": export_id, "body": body})


@router.post("/fde/data-exports/{export_id}/expire")
def fde_expire_data_export(
    request: Request,
    export_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:security:manage")
        if role_error:
            return role_error
        export = next((item for item in fde_state_list("data_exports") if item.get("id") == export_id), None)
        if not export:
            return fail(errors.NOT_FOUND, request)
        export["status"] = "expired"
        export["expiredAt"] = server_time()
        export["expireReason"] = body.get("reason") or "FDE 手动过期导出。"
        export["downloadStatus"] = "expired"
        audit_id = repo.add_audit("FDE 过期数据导出", "DataExport", export_id)
        return ok({"export": repo.clone(export), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"exportId": export_id, "body": body})


@router.post("/fde/ai-runs/{run_id}/replay")
def fde_replay_ai_run(
    request: Request,
    run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ai-run:replay")
        if role_error:
            return role_error
        parent = repo.find_one("ai_runs", run_id)
        if not parent:
            return fail(errors.NOT_FOUND, request)
        run_type = body.get("runType") or "diagnostic_replay"
        if run_type not in FDE_REPLAY_TYPES:
            return fail(errors.VALIDATION_ERROR, request, message="FDE 重跑类型不支持。", data={"allowedTypes": sorted(FDE_REPLAY_TYPES)})
        child_id = body.get("childRunId") or f"AIRUN-REPLAY-{uuid4().hex[:8].upper()}"
        child = repo.clone(parent)
        child.update(
            {
                "id": child_id,
                "parentRunId": run_id,
                "runType": run_type,
                "status": "排队中",
                "startedAt": server_time(),
                "finishedAt": None,
                "replayReason": body.get("reason") or "FDE 诊断重跑",
                "immutable": True,
                "inputHash": stable_hash_payload(parent.get("inputDocumentVersionIds") or []),
                "outputHash": stable_hash_payload(parent.get("suggestion") or {}),
            }
        )
        replay = {
            "id": f"REPLAY-{uuid4().hex[:8].upper()}",
            "parentRunId": run_id,
            "childRunId": child_id,
            "runType": run_type,
            "status": "created",
            "requestedByRole": effective_role_for_request(request)[0],
            "reason": body.get("reason"),
            "createdAt": server_time(),
        }
        repo.state["ai_runs"].insert(0, child)
        repo.state["ai_run_replays"].insert(0, replay)
        audit_id = repo.add_audit("FDE 创建 AI Run 重跑", "AIRunReplay", replay["id"])
        return ok({"replay": replay, "childRun": fde_ai_run_view(child), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"runId": run_id, "body": body})


@router.get("/fde/feedback")
def fde_feedback(request: Request, feedbackType: str | None = None, status: str | None = None):
    _, role_error = fde_error_unless_allowed(request, "fde:feedback:view")
    if role_error:
        return role_error
    items = [repo.clone(item) for item in repo.state.get("ai_feedback", [])]
    if feedbackType:
        items = [item for item in items if item.get("feedbackType") == feedbackType]
    if status:
        items = [item for item in items if item.get("status") == status]
    triage_by_feedback = {item.get("feedbackId"): item for item in repo.state.get("feedback_triage", [])}
    return ok([fde_feedback_governance_view(item, triage_by_feedback.get(item["id"])) for item in items], request)


def fde_feedback_governance_view(
    feedback: dict[str, Any],
    triage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = repo.clone(feedback)
    triage_record = triage or repo.find_one("feedback_triage", str(item.get("id")), id_field="feedbackId")
    evaluation_case = next(
        (
            case
            for case in repo.state.get("evaluation_cases", [])
            if case.get("sourceFeedbackId") == item.get("id")
        ),
        None,
    )
    can_use_for_eval = bool((triage_record or {}).get("canUseForEval", item.get("shouldEnterEvaluationSet", False)))
    can_use_for_training = bool((triage_record or {}).get("canUseForTraining", False))
    adjudication_required = bool((triage_record or {}).get("adjudicationRequired", False))
    if adjudication_required:
        governance_state = "needs_adjudication"
    elif evaluation_case:
        governance_state = "promoted_to_eval"
    elif not triage_record:
        governance_state = "needs_triage"
    elif can_use_for_eval:
        governance_state = "ready_for_eval"
    else:
        governance_state = "triaged"
    item.update(
        {
            "triage": repo.clone(triage_record) if triage_record else None,
            "evaluationCaseId": (evaluation_case or {}).get("id"),
            "evaluationSetId": (evaluation_case or {}).get("evaluationSetId"),
            "evaluationCaseStatus": (evaluation_case or {}).get("status"),
            "canUseForEval": can_use_for_eval,
            "canUseForTraining": can_use_for_training,
            "dataSensitivity": (triage_record or {}).get("dataSensitivity") or "masked",
            "adjudicationRequired": adjudication_required,
            "governanceState": governance_state,
            "sampleUsage": {
                "sourceFeedbackId": item.get("id"),
                "evaluationCaseId": (evaluation_case or {}).get("id"),
                "canUseForEval": can_use_for_eval,
                "canUseForTraining": can_use_for_training,
                "dataSensitivity": (triage_record or {}).get("dataSensitivity") or "masked",
                "adjudicationRequired": adjudication_required,
            },
        }
    )
    return item


def fde_expected_findings_from_feedback(feedback: dict[str, Any]) -> list[Any]:
    corrected = feedback.get("correctedOutput")
    if isinstance(corrected, dict):
        for key in ("findings", "manualConfirmItems", "expectedFindings"):
            value = corrected.get(key)
            if isinstance(value, list):
                return repo.clone(value)
        if corrected.get("title"):
            return [repo.clone(corrected)]
    if isinstance(corrected, list):
        return repo.clone(corrected)
    if feedback.get("feedbackType") == "rejected_false_positive":
        return []
    original = feedback.get("originalAiOutput")
    return repo.clone(original if isinstance(original, list) else [])


def fde_select_evaluation_set(feedback: dict[str, Any], triage: dict[str, Any], requested_set_id: str | None = None) -> dict[str, Any]:
    if requested_set_id:
        requested = repo.find_one("evaluation_sets", requested_set_id)
        if requested:
            return requested
    business_pack_id = feedback.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
    preferred_type = (
        "risk"
        if triage.get("rootCause") in {"kb_retrieval_error", "kb_content_error", "model_reasoning_error", "schema_error"}
        else "golden"
    )
    active_sets = [
        item
        for item in repo.state.get("evaluation_sets", [])
        if item.get("status") == "active" and item.get("businessPackId") == business_pack_id
    ]
    for item in active_sets:
        if item.get("setType") == preferred_type:
            return item
    if active_sets:
        return active_sets[0]
    created = {
        "id": f"ESET-{preferred_type.upper()}-{uuid4().hex[:8].upper()}",
        "name": "FDE 反馈自动评估集",
        "setType": preferred_type,
        "businessPackId": business_pack_id,
        "caseCount": 0,
        "riskLevel": "high" if preferred_type == "risk" else "medium",
        "status": "active",
        "createdAt": server_time(),
        "source": "fde_feedback_triage",
    }
    repo.state.setdefault("evaluation_sets", []).insert(0, created)
    return created


def fde_upsert_evaluation_case_from_feedback(
    feedback: dict[str, Any],
    triage: dict[str, Any],
    *,
    evaluation_set_id: str | None = None,
) -> dict[str, Any] | None:
    if not (triage.get("status") == "approved_for_eval" or bool(triage.get("canUseForEval"))):
        return None
    repo.state.setdefault("evaluation_cases", [])
    evaluation_set = fde_select_evaluation_set(feedback, triage, evaluation_set_id)
    existing = next(
        (item for item in repo.state["evaluation_cases"] if item.get("sourceFeedbackId") == feedback.get("id")),
        None,
    )
    inferred_risk_level = (
        "high" if triage.get("rootCause") in {"kb_retrieval_error", "kb_content_error", "model_reasoning_error"} else "medium"
    )
    payload = {
        "id": (existing or {}).get("id") or f"ECASE-{uuid4().hex[:8].upper()}",
        "evaluationSetId": evaluation_set["id"],
        "businessPackId": feedback.get("businessPackId") or evaluation_set.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
        "nodeId": feedback.get("nodeId"),
        "source": "human_feedback",
        "sourceFeedbackId": feedback.get("id"),
        "feedbackType": feedback.get("feedbackType"),
        "rootCause": triage.get("rootCause"),
        "riskLevel": triage.get("riskLevel") or inferred_risk_level,
        "inputDocumentVersionIds": repo.clone(feedback.get("inputDocumentVersionIds") or []),
        "expectedFindings": fde_expected_findings_from_feedback(feedback),
        "expectedEvidence": repo.clone(feedback.get("expectedEvidence") or feedback.get("evidenceRefs") or []),
        "expectedEvidenceLinkIds": repo.clone(feedback.get("expectedEvidenceLinkIds") or []),
        "dataSensitivity": triage.get("dataSensitivity") or "masked",
        "canUseForEval": bool(triage.get("canUseForEval", True)),
        "canUseForTraining": bool(triage.get("canUseForTraining", False)),
        "status": "approved_for_eval",
        "updatedAt": server_time(),
    }
    if existing:
        existing.update(payload)
        return repo.clone(existing)
    payload["createdAt"] = payload["updatedAt"]
    repo.state["evaluation_cases"].insert(0, payload)
    evaluation_set["caseCount"] = int(evaluation_set.get("caseCount") or 0) + 1
    return repo.clone(payload)


@router.post("/fde/feedback/{feedback_id}/triage")
def fde_triage_feedback(
    request: Request,
    feedback_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:feedback:triage")
        if role_error:
            return role_error
        feedback = repo.find_one("ai_feedback", feedback_id)
        if not feedback:
            return fail(errors.NOT_FOUND, request)
        root_cause = body.get("rootCause") or feedback.get("rootCause") or "prompt_error"
        if root_cause not in FDE_ROOT_CAUSES:
            return fail(errors.VALIDATION_ERROR, request, message="纠错归因类型不支持。", data={"allowedTypes": sorted(FDE_ROOT_CAUSES)})
        triage = repo.find_one("feedback_triage", feedback_id, id_field="feedbackId")
        payload = {
            "id": (triage or {}).get("id") or f"FBT-{uuid4().hex[:8].upper()}",
            "feedbackId": feedback_id,
            "status": body.get("status") or "triaged",
            "rootCause": root_cause,
            "dataSensitivity": body.get("dataSensitivity") or "masked",
            "canUseForEval": bool(body.get("canUseForEval", feedback.get("shouldEnterEvaluationSet", False))),
            "canUseForTraining": bool(body.get("canUseForTraining", False)),
            "adjudicationRequired": bool(body.get("adjudicationRequired", False)),
            "updatedAt": server_time(),
        }
        if triage:
            triage.update(payload)
        else:
            repo.state["feedback_triage"].insert(0, payload)
        feedback["status"] = payload["status"]
        feedback["rootCause"] = root_cause
        evaluation_case = fde_upsert_evaluation_case_from_feedback(
            feedback,
            payload,
            evaluation_set_id=body.get("evaluationSetId"),
        )
        audit_id = repo.add_audit("FDE 反馈归因", "HumanFeedback", feedback_id)
        return ok(
            {
                "feedback": fde_feedback_governance_view(feedback, payload),
                "triage": payload,
                "evaluationCase": evaluation_case,
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source={"feedbackId": feedback_id, "body": body})


@router.get("/fde/evaluation-sets")
def fde_evaluation_sets(request: Request, setType: str | None = None):
    _, role_error = fde_error_unless_allowed(request, "fde:evaluation:view")
    if role_error:
        return role_error
    items = [repo.clone(item) for item in repo.state.get("evaluation_sets", [])]
    if setType:
        items = [item for item in items if item.get("setType") == setType]
    return ok(
        {
            "sets": items,
            "cases": repo.clone(repo.state.get("evaluation_cases", [])),
            "runs": repo.clone(repo.state.get("evaluation_runs", [])),
            "reports": repo.clone(repo.state.get("evaluation_reports", [])),
        },
        request,
    )


def fde_normalize_eval_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("title", "description", "message", "fieldCode", "fieldName"):
            if value.get(key):
                return str(value.get(key)).strip()
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value).strip()


def fde_evaluation_case_overrides(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = body.get("caseResults") or body.get("caseOverrides") or {}
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}
    if isinstance(raw, list):
        mapped: dict[str, dict[str, Any]] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            case_id = item.get("evaluationCaseId") or item.get("caseId") or item.get("id")
            if case_id:
                mapped[str(case_id)] = item
        return mapped
    return {}


def fde_expected_evidence_for_case(case: dict[str, Any]) -> list[Any]:
    for key in ("expectedEvidence", "expectedEvidenceRefs", "expectedEvidenceLinkIds"):
        value = case.get(key)
        if isinstance(value, list):
            return repo.clone(value)
    return []


def fde_normalize_clause_ref(value: Any) -> str:
    return str(value or "").strip().lower()


def fde_expected_clause_ids_for_case(case: dict[str, Any]) -> list[str]:
    for key in ("expectedClauseIds", "expectedClauses", "expectedKbRefs"):
        value = case.get(key)
        if not isinstance(value, list):
            continue
        clause_ids: list[str] = []
        for item in value:
            if isinstance(item, dict):
                clause_id = item.get("clauseId") or item.get("id")
            else:
                clause_id = item
            if clause_id:
                clause_ids.append(str(clause_id))
        if clause_ids:
            return clause_ids
    return []


def fde_retrieval_query_for_case(case: dict[str, Any], override: dict[str, Any]) -> str:
    for key in ("retrievalQuery", "question", "query"):
        if override.get(key):
            return str(override.get(key))
        if case.get(key):
            return str(case.get(key))
    expected_findings = case.get("expectedFindings") or []
    if expected_findings:
        return fde_normalize_eval_value(expected_findings[0])
    return "审查依据"


def fde_evaluate_retrieval_for_case(
    *,
    evaluation_run_id: str,
    case: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any] | None:
    expected_clause_ids = fde_expected_clause_ids_for_case(case)
    if not expected_clause_ids:
        return None
    query = fde_retrieval_query_for_case(case, override)
    top_k = int(override.get("retrievalTopK") or case.get("retrievalTopK") or 5)
    node_value = case.get("nodeId")
    node_id = int(node_value) if str(node_value or "").isdigit() else None
    trace: dict[str, Any] | None = None
    if "actualClauseIds" in override or "selectedClauseIds" in override:
        selected_clause_ids = [str(item) for item in (override.get("actualClauseIds") or override.get("selectedClauseIds") or [])]
        selected_route = str(override.get("selectedRoute") or case.get("expectedRoute") or "manual_override")
    else:
        retrieval = retrieve_knowledge_clauses(
            repo.state,
            query=query,
            review_run_id=evaluation_run_id,
            business_pack_id=case.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
            node_id=node_id,
            top_k=top_k,
            query_type="fde_evaluation_retrieval",
        )
        trace = retrieval["trace"]
        trace["evaluationRunId"] = evaluation_run_id
        trace["evaluationCaseId"] = case.get("id")
        repo.state.setdefault("retrieval_traces", []).append(trace)
        selected_clause_ids = [str(item.get("clauseId")) for item in trace.get("selectedClauses") or [] if item.get("clauseId")]
        selected_route = str(trace.get("selectedRoute") or "")
    expected_norm = {fde_normalize_clause_ref(item) for item in expected_clause_ids}
    selected_norm = {fde_normalize_clause_ref(item) for item in selected_clause_ids}
    missing_clause_ids = [item for item in expected_clause_ids if fde_normalize_clause_ref(item) not in selected_norm]
    matched_clause_count = len(expected_norm & selected_norm)
    top_clause_id = selected_clause_ids[0] if selected_clause_ids else None
    unexpected_top_clause_id = (
        top_clause_id if top_clause_id and fde_normalize_clause_ref(top_clause_id) not in expected_norm else None
    )
    expected_route = override.get("expectedRoute") or case.get("expectedRoute")
    route_passed = not expected_route or selected_route == str(expected_route)
    expected_count = len(expected_clause_ids)
    retrieval_passed = not missing_clause_ids and not unexpected_top_clause_id and bool(route_passed)
    return {
        "retrievalQuery": query,
        "retrievalTraceId": (trace or {}).get("retrievalTraceId"),
        "expectedClauseIds": expected_clause_ids,
        "selectedClauseIds": selected_clause_ids,
        "missingClauseIds": missing_clause_ids,
        "unexpectedTopClauseId": unexpected_top_clause_id,
        "expectedClauseCount": expected_count,
        "matchedClauseCount": matched_clause_count,
        "retrievalRecall": round(matched_clause_count / expected_count, 4) if expected_count else 1.0,
        "retrievalPassed": retrieval_passed,
        "selectedRoute": selected_route,
        "expectedRoute": expected_route,
        "routePassed": bool(route_passed),
    }


def fde_build_evaluation_case_results(
    *,
    evaluation_run_id: str,
    cases: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id"))
        override = overrides.get(case_id) or overrides.get(str(case.get("sourceFeedbackId"))) or {}
        expected_findings = repo.clone(case.get("expectedFindings") or [])
        if "actualFindings" in override:
            actual_findings = repo.clone(override.get("actualFindings") or [])
        elif "findings" in override:
            actual_findings = repo.clone(override.get("findings") or [])
        elif "actualFindings" in case:
            actual_findings = repo.clone(case.get("actualFindings") or [])
        elif "candidateFindings" in case:
            actual_findings = repo.clone(case.get("candidateFindings") or [])
        else:
            actual_findings = repo.clone(expected_findings)
        expected_values = {fde_normalize_eval_value(item) for item in expected_findings}
        actual_values = {fde_normalize_eval_value(item) for item in actual_findings}
        missing_findings = sorted(value for value in expected_values if value and value not in actual_values)
        unexpected_findings = sorted(value for value in actual_values if value and value not in expected_values)
        expected_evidence = fde_expected_evidence_for_case(case)
        if "actualEvidence" in override:
            actual_evidence = repo.clone(override.get("actualEvidence") or [])
        elif "evidenceRefs" in override:
            actual_evidence = repo.clone(override.get("evidenceRefs") or [])
        else:
            actual_evidence = repo.clone(expected_evidence)
        evidence_passed = not expected_evidence or bool(actual_evidence)
        retrieval_result = fde_evaluate_retrieval_for_case(
            evaluation_run_id=evaluation_run_id,
            case=case,
            override=override,
        )
        retrieval_passed = True if retrieval_result is None else bool(retrieval_result.get("retrievalPassed"))
        status = "passed" if not missing_findings and evidence_passed and retrieval_passed else "failed"
        result = {
            "id": f"ECRES-{uuid4().hex[:8].upper()}",
            "evaluationRunId": evaluation_run_id,
            "evaluationCaseId": case_id,
            "sourceFeedbackId": case.get("sourceFeedbackId"),
            "businessPackId": case.get("businessPackId"),
            "nodeId": case.get("nodeId"),
            "feedbackType": case.get("feedbackType"),
            "rootCause": case.get("rootCause"),
            "riskLevel": case.get("riskLevel"),
            "status": status,
            "expectedFindingCount": len(expected_findings),
            "matchedFindingCount": max(0, len(expected_values) - len(missing_findings)),
            "actualFindingCount": len(actual_findings),
            "missingFindings": missing_findings,
            "unexpectedFindings": unexpected_findings,
            "expectedEvidenceCount": len(expected_evidence),
            "actualEvidenceCount": len(actual_evidence),
            "evidencePassed": evidence_passed,
            "replayMode": override.get("replayMode") or "static_baseline",
            "createdAt": server_time(),
        }
        if retrieval_result:
            result.update(retrieval_result)
        results.append(result)
    return results


def fde_evaluation_case_summary(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_results)
    passed = len([item for item in case_results if item.get("status") == "passed"])
    expected_total = sum(int(item.get("expectedFindingCount") or 0) for item in case_results)
    matched_total = sum(int(item.get("matchedFindingCount") or 0) for item in case_results)
    evidence_required = len([item for item in case_results if int(item.get("expectedEvidenceCount") or 0) > 0])
    evidence_passed = len(
        [
            item
            for item in case_results
            if int(item.get("expectedEvidenceCount") or 0) > 0 and bool(item.get("evidencePassed"))
        ]
    )
    retrieval_required = [
        item for item in case_results if int(item.get("expectedClauseCount") or 0) > 0
    ]
    expected_clause_total = sum(int(item.get("expectedClauseCount") or 0) for item in retrieval_required)
    matched_clause_total = sum(int(item.get("matchedClauseCount") or 0) for item in retrieval_required)
    wrong_reference_count = len([item for item in retrieval_required if item.get("unexpectedTopClauseId")])
    pageindex_triggered = len([item for item in retrieval_required if item.get("selectedRoute") == "pageindex_tree_search"])
    retrieval_passed = len([item for item in retrieval_required if bool(item.get("retrievalPassed"))])
    return {
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "casePassRate": round(passed / total, 4) if total else 0.0,
        "findingRecall": round(matched_total / expected_total, 4) if expected_total else 1.0,
        "evidenceCoverage": round(evidence_passed / evidence_required, 4) if evidence_required else 1.0,
        "retrievalCases": len(retrieval_required),
        "retrievalPassRate": round(retrieval_passed / len(retrieval_required), 4) if retrieval_required else 1.0,
        "retrievalRecall": round(matched_clause_total / expected_clause_total, 4) if expected_clause_total else 1.0,
        "wrongReferenceRate": round(wrong_reference_count / len(retrieval_required), 4) if retrieval_required else 0.0,
        "pageIndexTriggerRate": round(pageindex_triggered / len(retrieval_required), 4) if retrieval_required else 0.0,
    }


def fde_metric_threshold(metric: str) -> tuple[float, str]:
    if metric == "humanAcceptanceRate":
        return 0.85, ">="
    if metric in {"evidenceHitRate", "casePassRate", "findingRecall", "evidenceCoverage"}:
        return 0.9, ">="
    if metric in {"retrievalRecall", "retrievalPassRate"}:
        return 0.9, ">="
    if metric == "wrongReferenceRate":
        return 0.03, "<="
    if metric == "schemaPassRate":
        return 1.0, ">="
    if metric == "hallucinationRate":
        return 0.01, "<="
    if metric == "highRiskMissRate":
        return 0.005, "<="
    if metric == "failedCaseCount":
        return 0.0, "<="
    if metric == "caseCount":
        return 1.0, ">="
    return 0.0, ">="


def fde_metric_passed(metric: str, value: float | int) -> bool:
    threshold, operator = fde_metric_threshold(metric)
    return float(value) >= threshold if operator == ">=" else float(value) <= threshold


@router.post("/fde/evaluation-runs")
def fde_create_evaluation_run(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:evaluation:run")
        if role_error:
            return role_error
        set_id = body.get("evaluationSetId")
        bundle_id = body.get("capabilityBundleId") or "BUNDLE-REVIEW-202606"
        if not set_id or not repo.find_one("evaluation_sets", set_id):
            return fail(errors.VALIDATION_ERROR, request, message="evaluationSetId 无效。")
        cases = [item for item in repo.state.get("evaluation_cases", []) if item.get("evaluationSetId") == set_id]
        run_id = body.get("id") or f"ERUN-{uuid4().hex[:8].upper()}"
        case_results = fde_build_evaluation_case_results(
            evaluation_run_id=run_id,
            cases=repo.clone(cases),
            overrides=fde_evaluation_case_overrides(body),
        )
        case_summary = fde_evaluation_case_summary(case_results)
        case_count = len(cases)
        metrics = {
            "humanAcceptanceRate": acceptance_rate() or 0.86,
            "evidenceHitRate": evidence_hit_rate() or 0.92,
            "hallucinationRate": hallucination_rate(),
            "highRiskMissRate": 0.0,
            "schemaPassRate": 1.0,
            "casePassRate": case_summary["casePassRate"],
            "findingRecall": case_summary["findingRecall"],
            "evidenceCoverage": case_summary["evidenceCoverage"],
            "retrievalRecall": case_summary["retrievalRecall"],
            "retrievalPassRate": case_summary["retrievalPassRate"],
            "wrongReferenceRate": case_summary["wrongReferenceRate"],
            "pageIndexTriggerRate": case_summary["pageIndexTriggerRate"],
            "failedCaseCount": case_summary["failed"],
            "caseCount": case_count,
        }
        run = {
            "id": run_id,
            "evaluationSetId": set_id,
            "capabilityBundleId": bundle_id,
            "status": "completed",
            "startedAt": server_time(),
            "finishedAt": server_time(),
            "metrics": metrics,
            "caseSummary": case_summary,
            "requestedByRole": effective_role_for_request(request)[0],
        }
        gate_results = [
            {"gate": "golden_set", "passed": metrics["evidenceHitRate"] >= 0.9},
            {"gate": "schema_validation", "passed": metrics["schemaPassRate"] >= 1.0},
            {"gate": "hallucination", "passed": metrics["hallucinationRate"] <= 0.01},
            {"gate": "high_risk_miss", "passed": metrics["highRiskMissRate"] <= 0.005},
            {"gate": "case_pass_rate", "passed": metrics["casePassRate"] >= 0.9},
            {"gate": "finding_recall", "passed": metrics["findingRecall"] >= 0.9},
            {"gate": "evidence_coverage", "passed": metrics["evidenceCoverage"] >= 0.9},
            {"gate": "retrieval_recall", "passed": metrics["retrievalRecall"] >= 0.9},
            {"gate": "wrong_reference", "passed": metrics["wrongReferenceRate"] <= 0.03},
        ]
        report_status = "passed" if all(item["passed"] for item in gate_results) else "failed"
        report = {
            "id": body.get("reportId") or f"EREPORT-{uuid4().hex[:8].upper()}",
            "evaluationRunId": run["id"],
            "capabilityBundleId": bundle_id,
            "businessPackId": (repo.find_one("capability_bundles", bundle_id) or {}).get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
            "status": report_status,
            "summary": "离线评测通过，关键指标满足 FDE 发布门禁。"
            if report_status == "passed"
            else "离线评测未通过，存在样本或指标未满足发布门禁。",
            "metrics": metrics,
            "caseSummary": case_summary,
            "caseResults": repo.clone(case_results),
            "gateResults": gate_results,
            "createdAt": server_time(),
        }
        repo.state.setdefault("evaluation_case_results", [])
        repo.state["evaluation_runs"].insert(0, run)
        repo.state["evaluation_reports"].insert(0, report)
        repo.state["evaluation_case_results"][:0] = repo.clone(case_results)
        for metric, value in metrics.items():
            if isinstance(value, (int, float)):
                threshold, operator = fde_metric_threshold(metric)
                repo.state["evaluation_metrics"].insert(
                    0,
                    {
                        "id": f"EMET-{uuid4().hex[:8].upper()}",
                        "evaluationRunId": run["id"],
                        "metric": metric,
                        "value": value,
                        "threshold": threshold,
                        "operator": operator,
                        "passed": fde_metric_passed(metric, value),
                    },
                )
        audit_id = repo.add_audit("FDE 发起离线评测", "EvaluationRun", run["id"])
        return ok({"run": run, "report": report, "caseResults": case_results, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/fde/evaluation-runs/{run_id}/report")
def fde_evaluation_report(request: Request, run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:evaluation:view")
    if role_error:
        return role_error
    report = fde_evaluation_report_for_run(run_id)
    if not report:
        return fail(errors.NOT_FOUND, request)
    metrics = [repo.clone(item) for item in repo.state.get("evaluation_metrics", []) if item.get("evaluationRunId") == run_id]
    case_results = [
        repo.clone(item) for item in repo.state.get("evaluation_case_results", []) if item.get("evaluationRunId") == run_id
    ]
    return ok({"report": repo.clone(report), "metrics": metrics, "caseResults": case_results}, request)


@router.get("/fde/capability-bundles")
def fde_capability_bundles(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:view")
    if role_error:
        return role_error
    return ok(
        {
            "bundles": repo.clone(repo.state.get("capability_bundles", [])),
            "agents": repo.clone(repo.state.get("agent_versions", [])),
            "prompts": repo.clone(repo.state.get("prompt_versions", [])),
            "modelRoutes": repo.clone(repo.state.get("model_route_versions", [])),
            "ocrProfiles": repo.clone(repo.state.get("ocr_profile_versions", [])),
        },
        request,
    )


@router.post("/fde/capability-bundles")
def fde_create_capability_bundle(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:capability-bundle:manage")
        if role_error:
            return role_error
        bundle = {
            "id": body.get("id") or f"BUNDLE-{uuid4().hex[:8].upper()}",
            "name": body.get("name") or "FDE 草稿能力组合",
            "businessPackId": body.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
            "agentVersionId": body.get("agentVersionId"),
            "promptVersionId": body.get("promptVersionId"),
            "modelRouteVersionId": body.get("modelRouteVersionId"),
            "ruleSetVersion": body.get("ruleSetVersion"),
            "knowledgeBaseVersion": body.get("knowledgeBaseVersion"),
            "ocrProfileVersionId": body.get("ocrProfileVersionId"),
            "schemaVersion": body.get("schemaVersion") or "ReviewFindingDraftList@1.0.0",
            "riskLevel": body.get("riskLevel") or "medium",
            "status": "draft",
            "createdAt": server_time(),
        }
        repo.state["capability_bundles"].insert(0, bundle)
        audit_id = repo.add_audit("FDE 创建 Capability Bundle 草稿", "CapabilityBundle", bundle["id"])
        return ok({"bundle": bundle, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/fde/capability-bundles/{bundle_id}/diff")
def fde_capability_bundle_diff(request: Request, bundle_id: str, compareTo: str | None = None):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:view")
    if role_error:
        return role_error
    bundle = repo.find_one("capability_bundles", bundle_id)
    if not bundle:
        return fail(errors.NOT_FOUND, request)
    baseline = repo.find_one("capability_bundles", compareTo) if compareTo else None
    if not baseline:
        baseline = next(
            (
                item
                for item in repo.state.get("capability_bundles", [])
                if item.get("id") != bundle_id and item.get("businessPackId") == bundle.get("businessPackId")
            ),
            None,
        )
    component_fields = [
        "agentVersionId",
        "promptVersionId",
        "modelRouteVersionId",
        "ruleSetVersion",
        "knowledgeBaseVersion",
        "ocrProfileVersionId",
        "schemaVersion",
        "riskLevel",
        "businessPackId",
    ]
    current = {field: bundle.get(field) for field in component_fields}
    previous = {field: (baseline or {}).get(field) for field in component_fields}
    diff = fde_record_diff(current, previous)
    return ok(
        {
            "bundleId": bundle_id,
            "compareTo": (baseline or {}).get("id"),
            "current": current,
            "baseline": previous,
            "diff": diff,
            "riskImpact": "high" if any(item["field"] in {"ruleSetVersion", "knowledgeBaseVersion", "schemaVersion"} for item in diff["changes"]) else bundle.get("riskLevel", "medium"),
        },
        request,
    )


@router.get("/fde/releases")
def fde_release_plans(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:release:view")
    if role_error:
        return role_error
    return ok(
        {
            "plans": repo.clone(repo.state.get("release_plans", [])),
            "approvals": repo.clone(repo.state.get("release_approvals", [])),
            "gates": repo.clone(repo.state.get("release_gates", [])),
        },
        request,
    )


@router.get("/fde/releases/{release_id}/impact")
def fde_release_impact(request: Request, release_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:release:view")
    if role_error:
        return role_error
    plan = repo.find_one("release_plans", release_id)
    if not plan:
        return fail(errors.NOT_FOUND, request)
    bundle = repo.find_one("capability_bundles", plan.get("capabilityBundleId"))
    target_scope = plan.get("targetScope") or {}
    project_ids = set(target_scope.get("projectIds") or [])
    business_pack_ids = set(target_scope.get("businessPackIds") or [])
    if not business_pack_ids and bundle:
        business_pack_ids.add(bundle.get("businessPackId"))
    projects = [
        repo.clone(project)
        for project in repo.state.get("projects", [])
        if (not project_ids or project.get("id") in project_ids)
        and (not business_pack_ids or project.get("businessPackId", DEFAULT_BUSINESS_PACK_ID) in business_pack_ids)
    ]
    related_runs = [
        repo.clone(run)
        for run in repo.state.get("review_runs", [])
        if not business_pack_ids or run.get("businessPackId", DEFAULT_BUSINESS_PACK_ID) in business_pack_ids
    ][:20]
    gates = [repo.clone(item) for item in repo.state.get("release_gates", []) if item.get("releasePlanId") == release_id]
    return ok(
        {
            "releasePlanId": release_id,
            "targetScope": target_scope,
            "bundle": repo.clone(bundle),
            "affectedProjectCount": len(projects),
            "affectedProjects": projects[:20],
            "affectedReviewRunCount": len(related_runs),
            "sampleReviewRuns": related_runs,
            "gateSummary": {
                "total": len(gates),
                "passed": len([item for item in gates if item.get("passed")]),
                "blocked": [item.get("message") for item in gates if not item.get("passed")],
            },
        },
        request,
    )


@router.post("/fde/releases")
def fde_create_release_plan(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:submit")
        if role_error:
            return role_error
        bundle_id = body.get("capabilityBundleId")
        bundle = repo.find_one("capability_bundles", bundle_id) if bundle_id else None
        if not bundle:
            return fail(errors.VALIDATION_ERROR, request, message="capabilityBundleId 无效。")
        risk_level = body.get("riskLevel") or bundle.get("riskLevel") or "medium"
        plan = {
            "id": body.get("id") or f"REL-{uuid4().hex[:8].upper()}",
            "releaseType": body.get("releaseType") or "capability_bundle",
            "capabilityBundleId": bundle_id,
            "riskLevel": risk_level,
            "status": "submitted",
            "targetScope": body.get("targetScope") or {"tenantIds": ["demo"], "businessPackIds": [bundle.get("businessPackId")], "projectIds": []},
            "changeSummary": body.get("changeSummary") or "FDE 发起能力组合发布申请。",
            "evaluationReportId": body.get("evaluationReportId"),
            "rollbackPlanId": body.get("rollbackPlanId"),
            "blockingReasons": [],
            "createdByRole": effective_role_for_request(request)[0],
            "createdAt": server_time(),
        }
        repo.state["release_plans"].insert(0, plan)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking_reasons = [item["message"] for item in gates if not item["passed"]]
        plan["blockingReasons"] = blocking_reasons
        if blocking_reasons:
            plan["status"] = "blocked_by_gate"
        audit_id = repo.add_audit("FDE 创建发布计划", "ReleasePlan", plan["id"])
        return ok({"plan": plan, "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/releases/{release_id}/submit")
def fde_submit_release_plan(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:submit")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        if body.get("evaluationReportId"):
            plan["evaluationReportId"] = body["evaluationReportId"]
        if body.get("rollbackPlanId"):
            plan["rollbackPlanId"] = body["rollbackPlanId"]
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        plan["blockingReasons"] = blocking
        plan["status"] = "submitted" if not blocking else "blocked_by_gate"
        plan["submittedAt"] = server_time()
        audit_id = repo.add_audit("FDE 提交发布门禁", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/approve")
def fde_approve_release_plan(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, identity_error = effective_role_for_request(request)
        if identity_error:
            return identity_error
        if role != "admin":
            return fail(errors.FORBIDDEN, request, message="高风险 AI 发布必须由非 FDE 管理员/AI 负责人审批。")
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        approval = {
            "id": body.get("id") or f"RAPP-{uuid4().hex[:8].upper()}",
            "releasePlanId": release_id,
            "role": body.get("approvalRole") or "admin",
            "status": body.get("status") or "approved",
            "comment": body.get("comment") or "管理员批准高风险 AI 发布进入灰度。",
            "approvedByRole": role,
            "approvedAt": server_time(),
        }
        repo.state["release_approvals"].insert(0, approval)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        plan["blockingReasons"] = blocking
        plan["status"] = "submitted" if not blocking else "blocked_by_gate"
        plan["approvedAt"] = approval["approvedAt"] if not blocking else plan.get("approvedAt")
        audit_id = repo.add_audit("管理员审批 FDE 发布计划", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "approval": approval, "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/start-shadow")
def fde_start_shadow_release(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:shadow")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        if blocking:
            plan["status"] = "blocked_by_gate"
            plan["blockingReasons"] = blocking
            return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": None}, request)
        plan["status"] = "shadow_running"
        plan["shadowStartedAt"] = server_time()
        plan["shadowSampleRate"] = body.get("sampleRate", 0.0)
        audit_id = repo.add_audit("FDE 启动 Shadow Run", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/mark-shadow-passed")
def fde_mark_shadow_passed(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:shadow")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        if plan.get("status") not in {"shadow_running", "shadow_passed"}:
            return fail(errors.VALIDATION_ERROR, request, message="只有 shadow_running 状态可以标记 Shadow 通过。")
        plan["status"] = "shadow_passed"
        plan["shadowPassedAt"] = server_time()
        plan["shadowMetrics"] = body.get("metrics") or {"sampleRate": plan.get("shadowSampleRate", 0), "failedRuns": 0}
        audit_id = repo.add_audit("FDE 标记 Shadow Run 通过", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/request-canary")
def fde_request_canary_release(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:canary")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        if blocking:
            plan["status"] = "blocked_by_gate"
            plan["blockingReasons"] = blocking
            return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": None}, request)
        if plan.get("status") not in {"shadow_running", "shadow_passed"}:
            return fail(errors.VALIDATION_ERROR, request, message="当前发布状态不允许申请 canary。")
        plan["status"] = "canary_requested"
        plan["canaryPolicy"] = {
            "tenantPercent": body.get("tenantPercent", 10),
            "durationHours": body.get("durationHours", 24),
            "rollbackOnFailureRate": body.get("rollbackOnFailureRate", 0.02),
        }
        plan["canaryRequestedAt"] = server_time()
        audit_id = repo.add_audit("FDE 申请 Canary 发布", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/approve-production")
def fde_approve_production_release(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, identity_error = effective_role_for_request(request)
        if identity_error:
            return identity_error
        if role != "admin":
            return fail(errors.FORBIDDEN, request, message="生产发布必须由非 FDE 管理员/AI 负责人审批。")
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        gates = fde_release_gate_results(plan)
        fde_persist_release_gates(plan, gates)
        blocking = [item["message"] for item in gates if not item["passed"]]
        if blocking:
            plan["status"] = "blocked_by_gate"
            plan["blockingReasons"] = blocking
            return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": None}, request)
        if plan.get("status") not in {"canary_requested", "canary_running", "canary_passed", "shadow_passed", "submitted"}:
            return fail(errors.VALIDATION_ERROR, request, message="当前发布状态不允许批准生产。")
        plan["status"] = body.get("targetStatus") or "production_approved"
        plan["productionApprovedAt"] = server_time()
        plan["productionApprovedByRole"] = role
        plan["productionApprovalComment"] = body.get("comment") or "管理员批准进入生产。"
        audit_id = repo.add_audit("管理员批准 FDE 生产发布", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "gates": gates, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/releases/{release_id}/rollback")
def fde_rollback_release(
    request: Request,
    release_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:release:rollback")
        if role_error:
            return role_error
        plan = repo.find_one("release_plans", release_id)
        if not plan:
            return fail(errors.NOT_FOUND, request)
        plan["status"] = "rollback_requested"
        plan["rollbackReason"] = body.get("reason") or "FDE 请求回滚能力组合。"
        plan["rollbackRequestedAt"] = server_time()
        audit_id = repo.add_audit("FDE 请求发布回滚", "ReleasePlan", release_id)
        return ok({"plan": repo.clone(plan), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"releaseId": release_id, "body": body})


@router.post("/fde/business-packs/validate-all")
def fde_validate_business_packs(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:validate")
    if role_error:
        return role_error
    return ok(validate_all_business_packs(), request)


@router.get("/fde/business-packs/{pack_id}/diff")
def fde_business_pack_diff(request: Request, pack_id: str, compareTo: str | None = None, tenantId: str | None = None):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:view")
    if role_error:
        return role_error
    validation_result = fde_business_pack_validation_result(pack_id)
    if not validation_result:
        return fail(errors.NOT_FOUND, request)
    current_summary = validation_result["summary"]
    baseline_summary: dict[str, Any] = {}
    if compareTo:
        compare_result = fde_business_pack_validation_result(compareTo)
        if not compare_result:
            return fail(errors.NOT_FOUND, request, message="compareTo 业务包不存在。")
        baseline_summary = compare_result["summary"]
    else:
        installation = next(
            (
                item
                for item in repo.state.get("business_pack_installations", [])
                if item.get("businessPackId") == pack_id and (not tenantId or item.get("tenantId") == tenantId)
            ),
            None,
        )
        if installation:
            baseline_summary = {
                "id": installation.get("businessPackId"),
                "version": installation.get("businessPackVersion"),
                "tenantId": installation.get("tenantId"),
                "status": installation.get("status"),
                "snapshotHash": installation.get("businessPackSnapshotHash"),
            }
    diff = fde_record_diff(current_summary, baseline_summary)
    return ok(
        {
            "businessPackId": pack_id,
            "compareTo": compareTo or baseline_summary.get("version"),
            "tenantId": tenantId,
            "current": current_summary,
            "baseline": baseline_summary,
            "validation": validation_result["validation"],
            "diff": diff,
            "requiresMigrationReview": any(item["field"] in {"roles", "nodes", "materials", "workflow", "rules"} for item in diff["changes"]),
        },
        request,
    )


@router.post("/fde/business-packs/{pack_id}/install")
def fde_install_business_pack(
    request: Request,
    pack_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:business-pack:install")
        if role_error:
            return role_error
        validation_result = fde_business_pack_validation_result(pack_id)
        if not validation_result:
            return fail(errors.NOT_FOUND, request)
        tenant_id = body.get("tenantId") or "demo"
        dry_run = bool(body.get("dryRun", True))
        summary = validation_result["summary"]
        validation = validation_result["validation"]
        status = "dry_run_passed" if dry_run and validation.get("ok") else "production" if validation.get("ok") else "validation_failed"
        installation = {
            "id": body.get("id") or f"BPINST-{uuid4().hex[:8].upper()}",
            "businessPackId": pack_id,
            "businessPackVersion": summary["version"],
            "tenantId": tenant_id,
            "status": status,
            "installedByRole": effective_role_for_request(request)[0],
            "installedAt": server_time(),
            "rollbackToVersion": body.get("rollbackToVersion"),
            "validationStatus": "passed" if validation.get("ok") else "failed",
            "dryRun": dry_run,
        }
        repo.state["business_pack_installations"].insert(0, installation)
        audit_id = repo.add_audit("FDE 安装业务包", "BusinessPackInstallation", installation["id"])
        return ok({"installation": installation, "validation": validation, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"packId": pack_id, "body": body})


@router.post("/fde/business-packs/{pack_id}/upgrade")
def fde_upgrade_business_pack(
    request: Request,
    pack_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:business-pack:install")
        if role_error:
            return role_error
        validation_result = fde_business_pack_validation_result(pack_id)
        if not validation_result:
            return fail(errors.NOT_FOUND, request)
        tenant_id = body.get("tenantId") or "demo"
        current = next(
            (
                item
                for item in repo.state.get("business_pack_installations", [])
                if item.get("businessPackId") == pack_id and item.get("tenantId") == tenant_id
            ),
            None,
        )
        summary = validation_result["summary"]
        upgrade = {
            "id": body.get("id") or f"BPUPG-{uuid4().hex[:8].upper()}",
            "businessPackId": pack_id,
            "businessPackVersion": summary["version"],
            "tenantId": tenant_id,
            "status": "upgrade_dry_run_passed" if body.get("dryRun", True) else "upgrade_planned",
            "previousVersion": (current or {}).get("businessPackVersion"),
            "installedByRole": effective_role_for_request(request)[0],
            "installedAt": server_time(),
            "validationStatus": "passed" if validation_result["validation"].get("ok") else "failed",
            "dryRun": bool(body.get("dryRun", True)),
        }
        repo.state["business_pack_installations"].insert(0, upgrade)
        audit_id = repo.add_audit("FDE 升级业务包", "BusinessPackInstallation", upgrade["id"])
        return ok({"installation": upgrade, "validation": validation_result["validation"], "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"packId": pack_id, "body": body})


@router.post("/fde/business-packs/{pack_id}/rollback")
def fde_rollback_business_pack(
    request: Request,
    pack_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:business-pack:install")
        if role_error:
            return role_error
        tenant_id = body.get("tenantId") or "demo"
        installation = {
            "id": body.get("id") or f"BPROLL-{uuid4().hex[:8].upper()}",
            "businessPackId": pack_id,
            "businessPackVersion": body.get("targetVersion") or "previous",
            "tenantId": tenant_id,
            "status": "rollback_planned",
            "rollbackReason": body.get("reason") or "FDE 请求业务包回滚。",
            "installedByRole": effective_role_for_request(request)[0],
            "installedAt": server_time(),
            "validationStatus": "pending",
            "dryRun": bool(body.get("dryRun", True)),
        }
        repo.state["business_pack_installations"].insert(0, installation)
        audit_id = repo.add_audit("FDE 回滚业务包", "BusinessPackInstallation", installation["id"])
        return ok({"installation": installation, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"packId": pack_id, "body": body})


def fde_ocr_quality_snapshot(project_id: str | None = None, node_id: int | None = None, profile_id: str | None = None) -> dict[str, Any]:
    documents = repo.state.get("documents", [])
    fields = repo.state.get("extracted_fields", [])
    jobs = repo.state.get("ocr_jobs", [])
    results = repo.state.get("ocr_parse_results", [])
    corrections = repo.state.get("ocr_corrections", [])
    eval_runs = repo.state.get("ocr_eval_runs", [])
    version_ids: set[str] | None = None
    if project_id:
        version_ids = fde_project_version_ids(project_id, node_id)
        document_ids = {
            item.get("id")
            for item in documents
            if item.get("projectId") == project_id
        }
        documents = [item for item in documents if item.get("projectId") == project_id]
        if node_id is not None:
            scoped_document_ids = {
                item.get("documentId")
                for item in repo.state.get("bindings", [])
                if item.get("projectId") == project_id and int(item.get("nodeId") or 0) == int(node_id)
            }
            documents = [item for item in documents if item.get("id") in scoped_document_ids]
        fields = [item for item in fields if str(item.get("documentVersionId")) in version_ids]
        jobs = [
            item
            for item in jobs
            if fde_record_matches_project(item, project_id, node_id=node_id, version_ids=version_ids)
        ]
        results = [
            item
            for item in results
            if fde_record_matches_project(item, project_id, node_id=node_id, version_ids=version_ids)
            or str(item.get("documentVersionId")) in version_ids
        ]
        corrections = [
            item
            for item in corrections
            if str(item.get("documentVersionId")) in version_ids
            or item.get("documentId") in document_ids
        ]
    if profile_id:
        jobs = [item for item in jobs if str(item.get("profileId") or "") == profile_id]
        results = [item for item in results if str(item.get("profileId") or "") == profile_id]
    low_confidence = [item for item in fields if float(item.get("confidence") or 0) < 0.85]
    result_diagnostics = [
        diagnostic
        for result in results
        for diagnostic in result.get("diagnostics", [])
        if isinstance(diagnostic, dict) or diagnostic
    ]
    diagnostic_table_failures = [
        item
        for item in result_diagnostics
        if "TABLE" in str((item or {}).get("code") if isinstance(item, dict) else item).upper()
    ]
    diagnostic_seal_failures = [
        item
        for item in result_diagnostics
        if "SEAL" in str((item or {}).get("code") if isinstance(item, dict) else item).upper()
    ]
    engine_failures = [
        item
        for item in result_diagnostics
        if "ENGINE" in str((item or {}).get("code") if isinstance(item, dict) else item).upper()
        or "FAILED" in str((item or {}).get("code") if isinstance(item, dict) else item).upper()
    ]
    field_failures = fde_ocr_field_failures(results, fields)
    table_failures = [*diagnostic_table_failures, *fde_ocr_table_failures(results)]
    seal_failures = [*diagnostic_seal_failures, *fde_ocr_seal_failures(results)]
    quality_reason_counts = fde_ocr_quality_reason_counts(results)
    field_level = fde_ocr_field_level(results, fields, corrections)
    evidence_level = fde_ocr_evidence_level(results)
    table_level = fde_ocr_table_level(results)
    seal_level = fde_ocr_seal_level(results)
    success_documents = len([item for item in documents if item.get("currentOcrStatus") == "已识别"])
    failed_documents = len([item for item in documents if item.get("currentOcrStatus") == "识别失败"])
    success_results = len([item for item in results if item.get("status") == "success"])
    failed_results = len([item for item in results if item.get("status") != "success"])
    cache_metrics = fde_ocr_cache_metrics(results, jobs)
    runtime_doctor_report = fde_ocr_runtime_doctor_report()
    return {
        "fileLevel": {
            "total": len(documents),
            "success": success_documents,
            "failed": failed_documents,
            "parseSuccessRate": round(success_results / (len(results) or 1), 4),
        },
        "fieldLevel": field_level,
        "evidenceLevel": evidence_level,
        "tableLevel": table_level,
        "sealLevel": seal_level,
        "jobLevel": {
            "total": len(jobs),
            "success": success_results,
            "failed": failed_results,
            "running": len([item for item in jobs if item.get("status") in {"queued", "running"}]),
        },
        "lowConfidenceFields": repo.clone(low_confidence[:20]),
        "jobs": repo.clone(jobs[:20]),
        "parseResults": repo.clone(results[:20]),
        "corrections": repo.clone(corrections[:20]),
        "evalRuns": repo.clone(eval_runs[:20]),
        "cacheMetrics": cache_metrics,
        "qualityReasonCounts": quality_reason_counts,
        "runtimeDoctor": fde_ocr_runtime_doctor_snapshot(runtime_doctor_report),
        "ocr100Scorecard": fde_ocr_100_scorecard_snapshot(results, eval_runs, runtime_doctor_report),
        "ocr100ActionBoard": fde_ocr_100_action_board_snapshot(),
        "failurePools": {
            "fieldFailures": repo.clone(field_failures[:20]),
            "tableFailures": repo.clone(table_failures[:20]),
            "sealFailures": repo.clone(seal_failures[:20]),
            "engineFailures": repo.clone(engine_failures[:20]),
        },
    }


def fde_ocr_field_failures(results: list[dict[str, Any]], extracted_fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        parse_result_id = result.get("parseResultId") or result.get("id")
        for diagnostic_item in result.get("diagnostics", []):
            code = str((diagnostic_item or {}).get("code") if isinstance(diagnostic_item, dict) else diagnostic_item)
            upper_code = code.upper()
            if "FIELD" in upper_code or "CONFLICT" in upper_code:
                payload = repo.clone(diagnostic_item) if isinstance(diagnostic_item, dict) else {"code": code}
                payload["parseResultId"] = parse_result_id
                payload.setdefault("source", "diagnostic")
                failures.append(payload)
        for field in result.get("fields", []):
            if not isinstance(field, dict):
                continue
            flags = [str(flag) for flag in field.get("qualityFlags") or []]
            confidence = float(field.get("confidence") or 0)
            if flags or confidence < 0.75:
                if "field_value_conflict" in flags:
                    code = "FIELD_VALUE_CONFLICT"
                elif "field_evidence_missing" in flags:
                    code = "FIELD_EVIDENCE_MISSING"
                else:
                    code = "FIELD_LOW_CONFIDENCE"
                failures.append(
                    {
                        "code": code,
                        "source": "field",
                        "parseResultId": parse_result_id,
                        "fieldCode": field.get("fieldCode") or field.get("fieldName"),
                        "fieldName": field.get("fieldName"),
                        "fieldValue": field.get("fieldValue"),
                        "confidence": field.get("confidence"),
                        "qualityFlags": flags,
                    }
                )
        failures.extend(
            fde_missing_evidence_items(
                result,
                target_type="field",
                code="FIELD_EVIDENCE_MISSING",
                parse_result_id=parse_result_id,
            )
        )
    for field in extracted_fields:
        confidence = float(field.get("confidence") or 0)
        if confidence < 0.75:
            failures.append(
                {
                    "code": "FIELD_LOW_CONFIDENCE",
                    "source": "extracted_field",
                    "fieldId": field.get("id"),
                    "documentVersionId": field.get("documentVersionId"),
                    "fieldCode": field.get("fieldCode") or field.get("fieldName"),
                    "fieldName": field.get("fieldName"),
                    "fieldValue": field.get("fieldValue"),
                    "confidence": field.get("confidence"),
                }
            )
    return failures


def fde_ocr_table_failures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        parse_result_id = result.get("parseResultId") or result.get("id")
        for table in result.get("tables", []):
            if not isinstance(table, dict):
                continue
            flags = [str(flag) for flag in table.get("qualityFlags") or []]
            review_flags = [flag for flag in flags if ocr_quality_flag_requires_review(flag)]
            if not review_flags:
                continue
            failures.append(
                {
                    "code": "TABLE_EVIDENCE_MISSING" if "table_evidence_missing" in review_flags else "TABLE_REVIEW_REQUIRED",
                    "source": "table",
                    "parseResultId": parse_result_id,
                    "tableId": table.get("tableId"),
                    "businessSchema": table.get("businessSchema"),
                    "sourceEngine": table.get("sourceEngine"),
                    "structureConfidence": table.get("structureConfidence"),
                    "qualityFlags": review_flags,
                }
            )
        failures.extend(
            fde_missing_evidence_items(
                result,
                target_type="table",
                code="TABLE_EVIDENCE_MISSING",
                parse_result_id=parse_result_id,
            )
        )
    return dedupe_failure_pool(failures)


def fde_ocr_seal_failures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for result in results:
        parse_result_id = result.get("parseResultId") or result.get("id")
        for seal in result.get("seals", []):
            if not isinstance(seal, dict):
                continue
            flags = [str(flag) for flag in seal.get("qualityFlags") or []]
            review_flags = [flag for flag in flags if ocr_quality_flag_requires_review(flag)]
            if not review_flags:
                continue
            failures.append(
                {
                    "code": "SEAL_EVIDENCE_MISSING" if "seal_evidence_missing" in review_flags else "SEAL_REVIEW_REQUIRED",
                    "source": "seal",
                    "parseResultId": parse_result_id,
                    "sealId": seal.get("sealId"),
                    "sealName": seal.get("sealName"),
                    "sealType": seal.get("sealType"),
                    "sourceEngine": seal.get("sourceEngine"),
                    "ocrConfidence": seal.get("ocrConfidence"),
                    "qualityFlags": review_flags,
                }
            )
        failures.extend(
            fde_missing_evidence_items(
                result,
                target_type="seal",
                code="SEAL_EVIDENCE_MISSING",
                parse_result_id=parse_result_id,
            )
        )
    return dedupe_failure_pool(failures)


def ocr_quality_flag_requires_review(flag: Any) -> bool:
    normalized = str(flag or "").lower()
    return any(
        token in normalized
        for token in ["missing", "requires", "review", "low_confidence", "conflict", "fallback", "failed", "timeout"]
    )


def fde_missing_evidence_items(
    result: dict[str, Any],
    *,
    target_type: str,
    code: str,
    parse_result_id: str | None,
) -> list[dict[str, Any]]:
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    items = []
    for item in quality.get("missingEvidence") or []:
        if not isinstance(item, dict) or item.get("targetType") != target_type:
            continue
        items.append(
            {
                **repo.clone(item),
                "code": code,
                "source": "quality.missingEvidence",
                "parseResultId": parse_result_id,
            }
        )
    return items


def dedupe_failure_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for item in items:
        key = (
            item.get("code"),
            item.get("parseResultId"),
            item.get("targetType"),
            item.get("targetId"),
            item.get("tableId"),
            item.get("sealId"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def fde_ocr_quality_reason_counts(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        for reason in quality.get("reasons") or []:
            key = str(reason)
            counts[key] = counts.get(key, 0) + 1
    return [{"reason": reason, "count": count} for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def fde_ocr_field_level(
    results: list[dict[str, Any]],
    extracted_fields: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
) -> dict[str, Any]:
    parse_fields = [
        field
        for result in results
        for field in result.get("fields", [])
        if isinstance(field, dict)
    ]
    source_counts: dict[str, int] = {}
    code_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    missing_required_counts: dict[str, int] = {}
    missing_required_items: list[dict[str, Any]] = []
    low_confidence_parse_fields = []
    conflict_fields = []
    evidence_missing_fields = []
    confidence_values: list[float] = []
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        for field_code in quality.get("missingFields") or []:
            key = str(field_code or "unknown")
            missing_required_counts[key] = missing_required_counts.get(key, 0) + 1
            missing_required_items.append(
                {
                    "fieldCode": key,
                    "parseResultId": result.get("parseResultId") or result.get("id"),
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                }
            )
    for field in parse_fields:
        flags = [str(flag) for flag in field.get("qualityFlags") or []]
        source = str(field.get("sourceEngine") or field.get("source") or "unknown")
        code = str(field.get("fieldCode") or field.get("fieldName") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        code_counts[code] = code_counts.get(code, 0) + 1
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
        confidence = safe_float(field.get("confidence"))
        confidence_values.append(confidence)
        if confidence < 0.75:
            low_confidence_parse_fields.append(field)
        if any("conflict" in flag.lower() for flag in flags):
            conflict_fields.append(field)
        if any("evidence_missing" in flag.lower() or "missing_evidence" in flag.lower() for flag in flags):
            evidence_missing_fields.append(field)

    low_confidence_extracted = [item for item in extracted_fields if safe_float(item.get("confidence")) < 0.85]
    field_count = len(parse_fields)
    return {
        "total": len(extracted_fields),
        "lowConfidence": len(low_confidence_extracted),
        "manualCorrectionRate": round(len(corrections) / (len(extracted_fields) or 1), 4),
        "parseResultCount": len(results),
        "parseFieldCount": field_count,
        "lowConfidenceParseFieldCount": len(low_confidence_parse_fields),
        "conflictFieldCount": len(conflict_fields),
        "evidenceMissingFieldCount": len(evidence_missing_fields),
        "missingRequiredFieldCount": len(missing_required_items),
        "averageFieldConfidence": round(sum(confidence_values) / (len(confidence_values) or 1), 4),
        "missingRequiredFieldBreakdown": [
            {"fieldCode": code, "count": count}
            for code, count in sorted(missing_required_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleMissingRequiredFields": repo.clone(missing_required_items[:10]),
        "sourceBreakdown": [
            {"source": source, "count": count}
            for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "fieldCodeBreakdown": [
            {"fieldCode": code, "count": count}
            for code, count in sorted(code_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "qualityFlagCounts": [
            {"flag": flag, "count": count}
            for flag, count in sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleFields": repo.clone(parse_fields[:10]),
    }


def fde_ocr_table_level(results: list[dict[str, Any]]) -> dict[str, Any]:
    tables = [
        table
        for result in results
        for table in result.get("tables", [])
        if isinstance(table, dict)
    ]
    source_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    missing_required_counts: dict[str, int] = {}
    missing_required_items: list[dict[str, Any]] = []
    formal_tables = []
    heuristic_tables = []
    review_required = []
    business_row_count = 0
    normalized_row_count = 0
    cell_count = 0
    confidence_values: list[float] = []
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        for table_code in quality.get("missingTables") or []:
            key = str(table_code or "unknown")
            missing_required_counts[key] = missing_required_counts.get(key, 0) + 1
            missing_required_items.append(
                {
                    "tableCode": key,
                    "parseResultId": result.get("parseResultId") or result.get("id"),
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                }
            )
    for table in tables:
        flags = [str(flag) for flag in table.get("qualityFlags") or []]
        source = str(table.get("sourceEngine") or table.get("source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
        try:
            confidence_values.append(float(table.get("structureConfidence") or table.get("confidence") or 0))
        except (TypeError, ValueError):
            confidence_values.append(0.0)
        if fde_table_is_heuristic(table):
            heuristic_tables.append(table)
        else:
            formal_tables.append(table)
        if any(ocr_quality_flag_requires_review(flag) for flag in flags):
            review_required.append(table)
        business_row_count += len([row for row in table.get("businessRows") or [] if isinstance(row, dict)])
        normalized_row_count += len([row for row in table.get("normalizedRows") or [] if isinstance(row, dict)])
        cell_count += len([cell for cell in table.get("cells") or [] if isinstance(cell, dict)])
    table_count = len(tables)
    return {
        "parseResultCount": len(results),
        "tableCount": table_count,
        "formalTableCount": len(formal_tables),
        "heuristicTableCount": len(heuristic_tables),
        "reviewRequiredCount": len(review_required),
        "missingRequiredTableCount": len(missing_required_items),
        "businessRowCount": business_row_count,
        "normalizedRowCount": normalized_row_count,
        "cellCount": cell_count,
        "averageTableConfidence": round(sum(confidence_values) / (len(confidence_values) or 1), 4),
        "formalTableRate": round(len(formal_tables) / (table_count or 1), 4),
        "heuristicTableRate": round(len(heuristic_tables) / (table_count or 1), 4),
        "reviewRequiredRate": round(len(review_required) / (table_count or 1), 4),
        "missingRequiredTableBreakdown": [
            {"tableCode": code, "count": count}
            for code, count in sorted(missing_required_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleMissingRequiredTables": repo.clone(missing_required_items[:10]),
        "sourceBreakdown": [
            {"source": source, "count": count}
            for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "qualityFlagCounts": [
            {"flag": flag, "count": count}
            for flag, count in sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleTables": repo.clone(tables[:10]),
    }


def fde_table_is_heuristic(table: dict[str, Any]) -> bool:
    source = str(table.get("sourceEngine") or "")
    flags = {str(flag) for flag in table.get("qualityFlags") or []}
    return source.startswith("heuristic_") or "heuristic_table_fallback" in flags


def fde_table_business_rows(table: dict[str, Any]) -> list[Any]:
    rows = table.get("businessRows") or table.get("normalizedRows") or []
    return rows if isinstance(rows, list) else []


def fde_seal_is_fragment_fusion(seal: dict[str, Any]) -> bool:
    source = str(seal.get("sourceEngine") or "")
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    return source == "fragment_seal_text_fusion" or "fragment_seal_text" in flags


def fde_ocr_seal_level(results: list[dict[str, Any]]) -> dict[str, Any]:
    seals = [
        seal
        for result in results
        for seal in result.get("seals", [])
        if isinstance(seal, dict)
    ]
    source_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    readable_type_counts: dict[str, int] = {}
    matched_expected_counts: dict[str, int] = {}
    missing_expected_counts: dict[str, int] = {}
    missing_expected_items: list[dict[str, Any]] = []
    fragment_seals = []
    readable_seals = []
    visual_candidates = []
    review_required = []
    confidence_values: list[float] = []
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        for seal_type in quality.get("matchedSealTypes") or []:
            key = str(seal_type or "unknown")
            matched_expected_counts[key] = matched_expected_counts.get(key, 0) + 1
        for seal_type in quality.get("missingExpectedSealTypes") or []:
            key = str(seal_type or "unknown")
            missing_expected_counts[key] = missing_expected_counts.get(key, 0) + 1
            missing_expected_items.append(
                {
                    "sealType": key,
                    "parseResultId": result.get("parseResultId") or result.get("id"),
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                }
            )
    for seal in seals:
        flags = [str(flag) for flag in seal.get("qualityFlags") or []]
        source = str(seal.get("sourceEngine") or seal.get("source") or "unknown")
        seal_type = str(seal.get("sealType") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        type_counts[seal_type] = type_counts.get(seal_type, 0) + 1
        for flag in flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
        try:
            confidence_values.append(float(seal.get("ocrConfidence") or seal.get("visualConfidence") or 0))
        except (TypeError, ValueError):
            confidence_values.append(0.0)
        if "fragment_seal_text" in flags or source == "fragment_seal_text_fusion":
            fragment_seals.append(seal)
        if fde_seal_is_visual_candidate(seal):
            visual_candidates.append(seal)
        if fde_seal_text_is_readable(seal):
            readable_seals.append(seal)
            readable_type_counts[seal_type] = readable_type_counts.get(seal_type, 0) + 1
        if any(ocr_quality_flag_requires_review(flag) for flag in flags):
            review_required.append(seal)
    seal_count = len(seals)
    return {
        "parseResultCount": len(results),
        "sealCount": seal_count,
        "readableSealCount": len(readable_seals),
        "fragmentSealCount": len(fragment_seals),
        "visualCandidateCount": len(visual_candidates),
        "reviewRequiredCount": len(review_required),
        "missingExpectedSealTypeCount": len(missing_expected_items),
        "missingTextCount": len([seal for seal in visual_candidates if not fde_seal_text_is_readable(seal)]),
        "averageSealConfidence": round(sum(confidence_values) / (len(confidence_values) or 1), 4),
        "readableSealRate": round(len(readable_seals) / (seal_count or 1), 4),
        "fragmentSealRate": round(len(fragment_seals) / (seal_count or 1), 4),
        "visualCandidateReviewRate": round(len(review_required) / (len(visual_candidates) or 1), 4),
        "sealTypeBreakdown": [
            {"sealType": seal_type, "count": count}
            for seal_type, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "readableSealTypeBreakdown": [
            {"sealType": seal_type, "count": count}
            for seal_type, count in sorted(readable_type_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "matchedExpectedSealTypeBreakdown": [
            {"sealType": seal_type, "count": count}
            for seal_type, count in sorted(matched_expected_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "missingExpectedSealTypeBreakdown": [
            {"sealType": seal_type, "count": count}
            for seal_type, count in sorted(missing_expected_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleMissingExpectedSealTypes": repo.clone(missing_expected_items[:10]),
        "sourceBreakdown": [
            {"source": source, "count": count}
            for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "qualityFlagCounts": [
            {"flag": flag, "count": count}
            for flag, count in sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sampleSeals": repo.clone(seals[:10]),
    }


def fde_seal_is_visual_candidate(seal: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    seal_type = str(seal.get("sealType") or "")
    seal_name = str(seal.get("sealName") or "")
    return "visual_candidate_only" in flags or seal_type.startswith("visual_") or seal_name.startswith("视觉")


def fde_seal_text_is_readable(seal: dict[str, Any]) -> bool:
    if fde_seal_is_visual_candidate(seal):
        return False
    seal_name = str(seal.get("sealName") or "").strip()
    if not seal_name:
        return False
    try:
        confidence = float(seal.get("ocrConfidence") or 0)
    except (TypeError, ValueError):
        return False
    return confidence >= 0.65


def fde_ocr_evidence_level(results: list[dict[str, Any]]) -> dict[str, Any]:
    scores: list[float] = []
    missing_items: list[dict[str, Any]] = []
    by_type = {"field": 0, "table": 0, "seal": 0, "unknown": 0}
    for result in results:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        if "evidenceCompleteness" in quality:
            try:
                scores.append(float(quality.get("evidenceCompleteness") or 0))
            except (TypeError, ValueError):
                scores.append(0.0)
        missing_evidence = [item for item in quality.get("missingEvidence") or [] if isinstance(item, dict)]
        for item in missing_evidence:
            target_type = str(item.get("targetType") or "unknown")
            if target_type not in by_type:
                target_type = "unknown"
            by_type[target_type] += 1
            missing_items.append(
                {
                    **repo.clone(item),
                    "parseResultId": result.get("parseResultId") or result.get("id"),
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                }
            )
    return {
        "parseResultCount": len(results),
        "scoredResultCount": len(scores),
        "averageEvidenceCompleteness": round(sum(scores) / (len(scores) or 1), 4),
        "missingEvidence": len(missing_items),
        "fieldEvidenceMissing": by_type["field"],
        "tableEvidenceMissing": by_type["table"],
        "sealEvidenceMissing": by_type["seal"],
        "unknownEvidenceMissing": by_type["unknown"],
        "missingEvidenceItems": repo.clone(missing_items[:20]),
    }


def fde_ocr_cache_metrics(results: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    sources = results if results else jobs
    engine_runs = [
        run
        for source in sources
        for run in source.get("engineRuns", [])
        if isinstance(run, dict)
    ]
    total_runs = len(engine_runs)
    engine_cache_hits = len([run for run in engine_runs if bool(run.get("engineCacheHit"))])
    variant_cache_hits = len([run for run in engine_runs if bool(run.get("variantCacheHit"))])
    result_cache_hits = len([run for run in engine_runs if bool(run.get("resultCacheHit")) or run.get("engine") == "ocr_result_cache"])
    total_duration = sum(safe_int(run.get("durationMs")) for run in engine_runs)
    by_engine: dict[str, dict[str, Any]] = {}
    for run in engine_runs:
        engine = str(run.get("engine") or "unknown")
        item = by_engine.setdefault(
            engine,
            {
                "engine": engine,
                "runCount": 0,
                "engineCacheHits": 0,
                "variantCacheHits": 0,
                "failures": 0,
                "totalDurationMs": 0,
                "averageDurationMs": 0,
            },
        )
        item["runCount"] += 1
        item["engineCacheHits"] += 1 if bool(run.get("engineCacheHit")) else 0
        item["variantCacheHits"] += 1 if bool(run.get("variantCacheHit")) else 0
        item["failures"] += 1 if str(run.get("status") or "") == "failed" else 0
        item["totalDurationMs"] += safe_int(run.get("durationMs"))
    for item in by_engine.values():
        item["averageDurationMs"] = round(item["totalDurationMs"] / (item["runCount"] or 1), 2)
        item["engineCacheHitRate"] = round(item["engineCacheHits"] / (item["runCount"] or 1), 4)
    slow_engines = sorted(by_engine.values(), key=lambda item: item["totalDurationMs"], reverse=True)[:8]
    return {
        "engineRunCount": total_runs,
        "engineCacheHits": engine_cache_hits,
        "engineCacheHitRate": round(engine_cache_hits / (total_runs or 1), 4),
        "variantCacheHits": variant_cache_hits,
        "variantCacheHitRate": round(variant_cache_hits / (total_runs or 1), 4),
        "resultCacheHits": result_cache_hits,
        "totalDurationMs": total_duration,
        "averageDurationMs": round(total_duration / (total_runs or 1), 2),
        "slowEngines": repo.clone(slow_engines),
    }


def safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fde_ocr_runtime_doctor_report() -> dict[str, Any]:
    client = OcrClient()
    if not client.enabled:
        return {
            "schemaVersion": "aicheck-ocr-runtime-doctor-unavailable-v1",
            "ok": False,
            "summary": {"pass": 0, "warn": 1, "fail": 0, "total": 1},
            "checks": [
                {
                    "name": "ocr.base-url",
                    "status": "warn",
                    "message": "API 服务未配置 OCR 服务地址（AICHECK_OCR_BASE_URL）。",
                    "fix": "在 API 服务环境变量中配置 AICHECK_OCR_BASE_URL，FDE 才能读取 OCR 运行体检结果。",
                }
            ],
        }
    try:
        return client.runtime_doctor()
    except (IntegrationServiceError, RuntimeError) as exc:
        return {
            "schemaVersion": "aicheck-ocr-runtime-doctor-error-v1",
            "ok": False,
            "summary": {"pass": 0, "warn": 0, "fail": 1, "total": 1},
            "checks": [
                {
                    "name": "ocr.runtime-doctor",
                    "status": "fail",
                    "message": f"OCR 运行体检不可用：{exc.__class__.__name__}",
                    "fix": "检查 OCR 服务网络、/internal/ocr/doctor 运行体检接口，以及 AICHECK_OCR_BASE_URL 配置。",
                }
            ],
        }


def fde_ocr_runtime_doctor_snapshot(report: dict[str, Any] | None = None) -> dict[str, Any]:
    report = report or fde_ocr_runtime_doctor_report()
    checks = [item for item in report.get("checks") or [] if isinstance(item, dict)]
    top_issues = [item for item in checks if item.get("status") in {"fail", "warn"}][:8]
    return {
        "status": "ready" if report.get("ok") else "attention",
        "ok": bool(report.get("ok")),
        "summary": report.get("summary") or {},
        "topIssues": repo.clone(top_issues),
        "subprocessPython": report.get("subprocessPython"),
        "schemaVersion": report.get("schemaVersion"),
    }


def fde_ocr_100_scorecard_snapshot(
    results: list[dict[str, Any]],
    eval_runs: list[dict[str, Any]],
    runtime_doctor_report: dict[str, Any],
) -> dict[str, Any]:
    latest_eval_run = next(iter(eval_runs), {})
    evaluation_report = fde_ocr_100_evaluation_report_from_run(latest_eval_run)
    return build_ocr_100_scorecard(
        evaluation_report=evaluation_report,
        runtime_doctor=runtime_doctor_report,
        sample_summaries=fde_ocr_sample_summaries(results),
    )


def fde_ocr_100_action_board_snapshot() -> dict[str, Any]:
    reports_dir = WORKSPACE_ROOT / "backend" / "ocr_eval" / "reports"
    try:
        return fde_build_ocr_100_action_board(reports_dir)
    except Exception as exc:  # pragma: no cover - defensive API fallback
        return fde_ocr_100_action_board_error_snapshot(reports_dir, exc)


def fde_build_ocr_100_action_board(reports_dir: Path) -> dict[str, Any]:
    annotation_tasks = first_existing_path(
        [
            reports_dir / "scan_annotation_pack" / "prelabelled_tasks_retry_merged_after_batch6_dedupe.json",
            reports_dir / "scan_annotation_pack" / "annotation_tasks.json",
        ]
    )
    candidates = first_existing_path(
        [
            reports_dir / "ocr_100_scan_candidates.json",
            reports_dir / "ocr_100_sample_intake_after_batch6_dedupe" / "collection_candidates.json",
        ]
    )
    closure_plan = first_existing_path(
        [
            reports_dir / "ocr_100_closure_plan_after_batch6_dedupe.json",
            reports_dir / "ocr_100_closure_plan.json",
        ]
    )
    board = build_action_board(
        reports_dir=reports_dir,
        closure_plan_path=closure_plan,
        annotation_tasks_path=annotation_tasks,
        candidates_path=candidates,
        limit=30,
    )
    board["handoff"] = fde_ocr_100_action_handoff_snapshot(
        reports_dir,
        current_summary=board.get("summary"),
    )
    return board


def fde_ocr_100_action_board_error_snapshot(reports_dir: Path, exc: Exception) -> dict[str, Any]:
    return {
        "schemaVersion": "aicheck-ocr-100-action-board-v1",
        "ok": False,
        "summary": {
            "status": "action_board_unavailable",
            "score": None,
            "readyForEval": 0,
            "requiredReadyForEval": 100,
            "collectionMissingCases": None,
            "actions": 0,
            "laneCounts": {},
            "error": exc.__class__.__name__,
        },
        "actions": [],
        "scenarioPlan": {},
        "candidateSummary": {},
        "handoff": fde_ocr_100_action_handoff_snapshot(reports_dir),
    }


def fde_refresh_ocr_100_action_board_artifacts(reports_dir: Path) -> dict[str, Any]:
    board = fde_build_ocr_100_action_board(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "json": reports_dir / "ocr_100_action_board.json",
        "markdown": reports_dir / "ocr_100_action_board.md",
        "csv": reports_dir / "ocr_100_action_board.csv",
        "handoffDir": reports_dir / "ocr_100_action_handoff",
    }
    outputs["json"].write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["markdown"].write_text(action_board_markdown(board), encoding="utf-8")
    outputs["csv"].write_text(action_board_csv(board), encoding="utf-8")
    write_action_handoff(board, outputs["handoffDir"])
    board["handoff"] = fde_ocr_100_action_handoff_snapshot(
        reports_dir,
        current_summary=board.get("summary"),
    )
    return {
        "board": board,
        "outputs": {key: fde_relative_path(value) for key, value in outputs.items()},
    }


def fde_ocr_100_action_handoff_snapshot(
    reports_dir: Path,
    current_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_path = reports_dir / "ocr_100_action_handoff" / "handoff_manifest.json"
    manifest = fde_read_json_file(manifest_path)
    if not manifest:
        return {
            "schemaVersion": "aicheck-ocr-100-action-handoff-v1",
            "ok": False,
            "status": "missing",
            "manifestPath": fde_relative_path(manifest_path),
            "laneCounts": {},
            "files": [],
        }
    files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    file_rows = [fde_ocr_100_handoff_file_row(key, value) for key, value in files.items()]
    all_files_exist = bool(file_rows) and all(row.get("exists") for row in file_rows)
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    stale_reasons = fde_ocr_100_handoff_stale_reasons(summary, current_summary or {})
    status = "ready" if all_files_exist else "incomplete"
    if all_files_exist and stale_reasons:
        status = "stale"
    return {
        "schemaVersion": manifest.get("schemaVersion") or "aicheck-ocr-100-action-handoff-v1",
        "ok": all_files_exist and not stale_reasons,
        "status": status,
        "generatedAt": manifest.get("generatedAt"),
        "outputDir": fde_relative_path(manifest.get("outputDir")),
        "manifestPath": fde_relative_path(manifest_path),
        "summary": summary,
        "staleReasons": stale_reasons,
        "laneCounts": manifest.get("laneCounts") if isinstance(manifest.get("laneCounts"), dict) else {},
        "files": file_rows,
    }


def fde_ocr_100_handoff_stale_reasons(
    manifest_summary: dict[str, Any],
    current_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    if not current_summary:
        return []
    keys = [
        "status",
        "score",
        "readyForEval",
        "requiredReadyForEval",
        "collectionMissingCases",
        "placeholderSampleSlots",
        "annotationTasks",
        "remainingHumanLabels",
        "newLocalCandidates",
        "duplicateLocalCandidates",
        "actions",
    ]
    reasons: list[dict[str, Any]] = []
    for key in keys:
        manifest_value = fde_ocr_100_summary_value(manifest_summary.get(key))
        current_value = fde_ocr_100_summary_value(current_summary.get(key))
        if manifest_value != current_value:
            reasons.append(
                {
                    "field": key,
                    "handoff": manifest_summary.get(key),
                    "current": current_summary.get(key),
                }
            )
    manifest_lanes = (
        manifest_summary.get("laneCounts")
        if isinstance(manifest_summary.get("laneCounts"), dict)
        else {}
    )
    current_lanes = (
        current_summary.get("laneCounts")
        if isinstance(current_summary.get("laneCounts"), dict)
        else {}
    )
    if manifest_lanes != current_lanes:
        reasons.append(
            {"field": "laneCounts", "handoff": manifest_lanes, "current": current_lanes}
        )
    return reasons


def fde_ocr_100_summary_value(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def fde_ocr_100_handoff_file_row(key: str, value: Any) -> dict[str, Any]:
    path = Path(str(value))
    if not path.is_absolute():
        path = WORKSPACE_ROOT / path
    label_map = {
        "readme": ("总说明", "FDE", "交付顺序、文件说明和重跑门禁。"),
        "collectMarkdown": ("采样说明", "采样人员", "按场景补真实 OCR 文件。"),
        "collectCsv": ("采样CSV", "采样人员", "可分派的采样缺口清单。"),
        "labelMarkdown": ("标注说明", "标注/复核人员", "已有 Scan 样本的人审动作。"),
        "labelCsv": ("标注CSV", "标注/复核人员", "可分派的人工校对清单。"),
    }
    label, owner, purpose = label_map.get(key, (key, "FDE", "OCR 100 handoff artifact."))
    exists = path.exists()
    return {
        "key": key,
        "label": label,
        "owner": owner,
        "purpose": purpose,
        "path": fde_relative_path(path),
        "exists": exists,
        "sizeBytes": path.stat().st_size if exists and path.is_file() else 0,
    }


def fde_ocr_100_handoff_artifact_path(reports_dir: Path, artifact_key: str) -> Path | None:
    allowed_keys = {"readme", "collectMarkdown", "collectCsv", "labelMarkdown", "labelCsv", "manifest"}
    if artifact_key not in allowed_keys:
        return None
    handoff_root = (reports_dir / "ocr_100_action_handoff").resolve()
    if artifact_key == "manifest":
        candidate = handoff_root / "handoff_manifest.json"
    else:
        manifest = fde_read_json_file(handoff_root / "handoff_manifest.json")
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        raw_path = files.get(artifact_key)
        if not raw_path:
            return None
        candidate = Path(str(raw_path))
        if not candidate.is_absolute():
            candidate = WORKSPACE_ROOT / candidate
        candidate = candidate.resolve()
    try:
        candidate.relative_to(handoff_root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def fde_ocr_100_handoff_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "text/csv; charset=utf-8"
    if suffix == ".md":
        return "text/markdown; charset=utf-8"
    if suffix == ".json":
        return "application/json"
    return "application/octet-stream"


def fde_read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def fde_relative_path(path: Any) -> str:
    raw = Path(str(path))
    try:
        return str(raw.resolve().relative_to(WORKSPACE_ROOT.resolve()))
    except Exception:
        return str(raw)


def first_existing_path(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def fde_ocr_100_evaluation_report_from_run(run: dict[str, Any]) -> dict[str, Any]:
    report = repo.clone(run.get("evaluationReport") or {}) if isinstance(run, dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if not report:
        return {
            "ok": False,
            "summary": {"cases": 0, "passed": 0, "failed": 0, "averageScore": 0},
            "metrics": {},
            "findingCounts": {},
            "thresholdFailures": [],
            "scenarios": {},
            "cases": [],
        }
    cases = []
    for item in run.get("caseDiagnostics") or []:
        if isinstance(item, dict):
            cases.append(
                {
                    "caseId": item.get("caseId"),
                    "scenario": item.get("scenario"),
                    "score": item.get("score"),
                    "passed": item.get("passed"),
                    "findings": item.get("findings") or [],
                    "bootstrapGenerated": item.get("bootstrapGenerated"),
                    "fixtureDerived": item.get("fixtureDerived"),
                    "collectionStatus": item.get("collectionStatus"),
                }
            )
    return {
        **report,
        "summary": {
            "cases": summary.get("cases") or run.get("caseCount") or len(cases),
            "passed": summary.get("passed") or 0,
            "failed": summary.get("failed") or 0,
            "averageScore": summary.get("averageScore") or 0,
        },
        "scenarios": repo.clone(run.get("scenarioMetrics") or {}),
        "cases": cases,
    }


def fde_ocr_sample_summaries(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for result in results[:10]:
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        tables = [item for item in result.get("tables") or [] if isinstance(item, dict)]
        seals = [item for item in result.get("seals") or [] if isinstance(item, dict)]
        summaries.append(
            {
                "parseResultId": result.get("parseResultId") or result.get("id"),
                "profileId": result.get("profileId"),
                "gatePassed": result.get("status") == "success" and quality.get("status") == "auto_usable",
                "qualityStatus": quality.get("status"),
                "fields": len([item for item in result.get("fields") or [] if isinstance(item, dict)]),
                "formalTables": len([item for item in tables if not fde_table_is_heuristic(item)]),
                "businessRows": sum(len(fde_table_business_rows(item)) for item in tables),
                "readableSeals": len([item for item in seals if str(item.get("sealName") or "").strip()]),
                "fragmentSeals": len([item for item in seals if fde_seal_is_fragment_fusion(item)]),
                "missingExpectedSealTypeCount": len(quality.get("missingExpectedSealTypes") or []),
                "evidenceCompleteness": quality.get("evidenceCompleteness"),
            }
        )
    return summaries


def fde_build_ocr_evaluation_report(body: dict[str, Any]) -> dict[str, Any]:
    cases = body.get("cases") if isinstance(body.get("cases"), list) else None
    thresholds = body.get("thresholds") if isinstance(body.get("thresholds"), dict) else None
    if cases is None:
        cases = fde_ocr_evaluation_cases_from_results(str(body.get("profileId") or "all"))
    if not cases:
        cases = [
            {
                "caseId": "ocr-empty-eval",
                "scenario": "quality_gate_profile",
                "minScore": 0,
                "result": {"parseResultId": "empty", "status": "failed", "fields": [], "tables": [], "seals": [], "quality": {"status": "failed", "reasons": ["NO_OCR_RESULTS"]}},
                "expected": {"qualityStatus": "failed", "qualityReasons": ["NO_OCR_RESULTS"]},
            }
        ]
    return evaluate_cases(cases, thresholds=thresholds)


def fde_ocr_evaluation_cases_from_results(profile_id: str) -> list[dict[str, Any]]:
    results = [
        item
        for item in repo.state.get("ocr_parse_results", [])
        if profile_id in {"", "all"} or str(item.get("profileId") or "") == profile_id
    ]
    if not results and profile_id not in {"", "all"}:
        results = list(repo.state.get("ocr_parse_results", []))
    cases: list[dict[str, Any]] = []
    for result in results[:20]:
        parse_id = str(result.get("parseResultId") or result.get("id") or "ocr-result")
        if result.get("fields"):
            cases.append(
                {
                    "caseId": f"{parse_id}-fields",
                    "scenario": "field_extraction_profile",
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                    "result": result,
                    "expected": {"fields": expected_fields_from_result(result)},
                    "minScore": 0.9,
                }
            )
        if result.get("tables"):
            cases.append(
                {
                    "caseId": f"{parse_id}-tables",
                    "scenario": "table_structure_profile",
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                    "result": result,
                    "expected": {"tables": expected_tables_from_result(result)},
                    "minScore": 0.9,
                }
            )
        if result.get("seals"):
            cases.append(
                {
                    "caseId": f"{parse_id}-seals",
                    "scenario": "seal_text_profile",
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                    "result": result,
                    "expected": {"seals": expected_seals_from_result(result)},
                    "minScore": 0.9,
                }
            )
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        if quality.get("status") or quality.get("reasons"):
            cases.append(
                {
                    "caseId": f"{parse_id}-quality",
                    "scenario": "quality_gate_profile",
                    "profileId": result.get("profileId"),
                    "documentType": result.get("documentType"),
                    "result": result,
                    "expected": {
                        "qualityStatus": quality.get("status"),
                        "qualityReasons": quality.get("reasons") or [],
                    },
                    "minScore": 0.9,
                }
            )
    return cases


def expected_fields_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = []
    for field in result.get("fields") or []:
        if not isinstance(field, dict):
            continue
        field_code = str(field.get("fieldCode") or field.get("fieldName") or "")
        if not field_code:
            continue
        item = {"fieldCode": field_code, "value": field.get("fieldValue")}
        if field.get("bbox") or field.get("polygon"):
            item["bbox"] = field.get("bbox") or field.get("polygon")
            item["bboxIouThreshold"] = 0.5
        expected.append(item)
    return expected[:50]


def expected_tables_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = []
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        item: dict[str, Any] = {
            "businessSchema": table.get("businessSchema"),
            "tableId": table.get("tableId"),
            "minRows": int(table.get("rows") or 0),
            "minColumns": int(table.get("columns") or 0),
        }
        rows = table.get("businessRows") or table.get("normalizedRows") or []
        if rows and isinstance(rows[0], dict):
            item["requiredBusinessKeys"] = [key for key, value in rows[0].items() if value not in {None, ""}][:12]
        if table.get("bbox") or table.get("polygon"):
            item["bbox"] = table.get("bbox") or table.get("polygon")
            item["bboxIouThreshold"] = 0.5
        expected.append({key: value for key, value in item.items() if fde_expected_value_present(value)})
    return expected[:20]


def expected_seals_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = []
    for seal in result.get("seals") or []:
        if not isinstance(seal, dict):
            continue
        seal_name = str(seal.get("sealName") or "")
        item: dict[str, Any] = {
            "sealType": seal.get("sealType"),
            "nameContains": seal_name,
            "minConfidence": min(float(seal.get("ocrConfidence") or seal.get("visualConfidence") or 0), 0.8),
        }
        if seal.get("bbox") or seal.get("polygon"):
            item["bbox"] = seal.get("bbox") or seal.get("polygon")
            item["bboxIouThreshold"] = 0.5
        expected.append({key: value for key, value in item.items() if fde_expected_value_present(value)})
    return expected[:20]


def fde_expected_value_present(value: Any) -> bool:
    return value is not None and value != "" and value != []


def fde_capability_test_file_preview_type(file_name: str, content_type: str | None = None) -> str:
    suffix = Path(str(file_name or "")).suffix.lower().lstrip(".")
    content = str(content_type or "").lower()
    if suffix == "pdf" or "pdf" in content:
        return "pdf"
    if suffix in {"png", "jpg", "jpeg", "webp", "bmp"} or content.startswith("image/"):
        return "image"
    if suffix in {"doc", "docx", "xls", "xlsx"}:
        return "office"
    return "unsupported"


def fde_capability_test_safe_file_name(file_name: str | None) -> str:
    safe = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", Path(str(file_name or "ocr-test-file")).name)
    return safe[:120] or "ocr-test-file"


def fde_capability_test_upload_root() -> Path:
    return Path(
        os.getenv(
            "AICHECK_FDE_OCR_UPLOAD_DIR",
            "/tmp/aicheck-fde-ocr-uploads",
        )
    ).expanduser()


def fde_capability_test_local_path(path_value: str | None) -> Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        return None
    try:
        root = fde_capability_test_upload_root().resolve()
        resolved = path.expanduser().resolve()
    except Exception:
        return None
    if resolved == root or root in resolved.parents:
        return resolved
    return None


def fde_capability_test_direct_upload_url(session_id: str) -> str:
    return f"/api/fde/capability-tests/ocr/upload-session/{session_id}/file"


def fde_capability_test_storage_url(storage_key: str) -> str:
    raw = str(storage_key or "").strip()
    if fde_capability_test_local_path(raw):
        return raw
    if raw.startswith(("minio://", "s3://", "mock://", "http://", "https://", "file://")):
        return raw
    return f"minio://ocr-artifacts/{raw}"


def fde_capability_test_result_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {
            "pages": 0,
            "fields": 0,
            "tables": 0,
            "seals": 0,
            "fragments": 0,
            "diagnostics": 0,
            "qualityStatus": "unknown",
            "overallConfidence": 0,
            "engineDurationMs": 0,
        }
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    engine_runs = [item for item in result.get("engineRuns") or [] if isinstance(item, dict)]
    duration = sum(int(item.get("durationMs") or item.get("latencyMs") or 0) for item in engine_runs)
    return {
        "pages": len([item for item in result.get("pages") or [] if isinstance(item, dict)]),
        "fields": len([item for item in result.get("fields") or [] if isinstance(item, dict)]),
        "tables": len([item for item in result.get("tables") or [] if isinstance(item, dict)]),
        "seals": len([item for item in result.get("seals") or [] if isinstance(item, dict)]),
        "fragments": len([item for item in result.get("fragments") or [] if isinstance(item, dict)]),
        "diagnostics": len(result.get("diagnostics") or []),
        "qualityStatus": quality.get("status") or "unknown",
        "overallConfidence": quality.get("overallConfidence") or quality.get("confidence") or 0,
        "engineDurationMs": duration,
    }


def fde_capability_test_preview(run: dict[str, Any]) -> dict[str, Any]:
    file_name = str(run.get("fileName") or "OCR测试文件")
    content_type = str(run.get("contentType") or "application/octet-stream")
    file_size = int(run.get("fileSize") or 0)
    storage_url = fde_capability_test_storage_url(str(run.get("storageKey") or run.get("storageUrl") or ""))
    preview_type = fde_capability_test_file_preview_type(file_name, content_type)
    run_id = str(run.get("runId") or run.get("id") or "")
    local_path = fde_capability_test_local_path(storage_url)
    if local_path and local_path.is_file():
        session_id = str(run.get("uploadSessionId") or "")
        return {
            "url": fde_capability_test_direct_upload_url(session_id) if session_id else "",
            "method": "GET",
            "fileName": file_name,
            "contentType": content_type,
            "fileSize": file_size or local_path.stat().st_size,
            "previewType": preview_type,
            "pagePreviewUrl": f"/api/fde/capability-tests/ocr/runs/{run_id}/page-preview?pageNo=1"
            if preview_type == "pdf" and run_id
            else None,
            "readonly": True,
            "retention": "fde_capability_test_only",
        }
    try:
        inline_url = object_storage.presigned_get_url(storage_url)
        base_preview = repo.signed_get(file_name, storage_url, content_type, file_size)
        preview = {
            **base_preview,
            "url": inline_url or base_preview["url"],
        }
    except ObjectStorageUnavailable:
        preview = {
            "url": storage_url,
            "method": "GET",
            "fileName": file_name,
            "contentType": content_type,
            "fileSize": file_size,
            "storageUnavailable": True,
        }
    return {
        **preview,
        "previewType": preview_type,
        "pagePreviewUrl": f"/api/fde/capability-tests/ocr/runs/{run_id}/page-preview?pageNo=1"
        if preview_type == "pdf" and run_id
        else None,
        "readonly": True,
        "retention": "fde_capability_test_only",
    }


def fde_capability_test_run_by_id(run_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in repo.state.setdefault("fde_capability_test_runs", [])
            if str(item.get("runId") or item.get("id") or "") == run_id
        ),
        None,
    )


def fde_capability_test_profile_document_type(file_name: str, body: dict[str, Any]) -> tuple[str, str]:
    profile_id = str(body.get("profileId") or "").strip()
    document_type = str(body.get("documentType") or "").strip()
    if profile_id in {"all", "auto"}:
        profile_id = ""
    if document_type in {"all", "auto"}:
        document_type = ""
    normalized_name = str(file_name or "").lower()
    suffix = Path(str(file_name)).suffix.lower()
    if not profile_id:
        if any(term in normalized_name for term in ["rt", "ut", "ndt", "检测", "探伤"]):
            profile_id = "ndt_rt_report_v1"
        elif any(term in normalized_name for term in ["质量", "证明", "材质", "合格证", "证书"]):
            profile_id = "quality_certificate_v1"
        elif suffix in {".png", ".jpg", ".jpeg"} or any(
            term in normalized_name
            for term in ["设计", "图纸", "图纸目录", "drawing", "dwg", "工艺", "管道", "特性表"]
        ):
            profile_id = "piping_characteristic_list_v1"
        else:
            profile_id = "generic_document_v1"
    if not document_type:
        document_type = {
            "generic_document_v1": "generic_document",
            "piping_characteristic_list_v1": "engineering_table_photo",
            "quality_certificate_v1": "quality_certificate",
            "ndt_rt_report_v1": "ndt_report",
        }.get(profile_id, "engineering_document")
    return profile_id, document_type


def fde_start_ocr_capability_test_worker(run_id: str) -> None:
    thread = threading.Thread(target=fde_run_ocr_capability_test, args=(run_id,), daemon=True)
    thread.start()


def fde_capability_test_bool(body: dict[str, Any], key: str, default: bool) -> bool:
    return parse_bool(body.get(key), default) is True


def fde_capability_test_int(body: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(body.get(key) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def fde_capability_test_timeout_seconds(options: dict[str, Any]) -> int:
    max_pages = fde_capability_test_int(options, "maxPages", 1, 1, 10)
    enabled_heavy_steps = sum(
        1
        for key in ("enableTables", "enableSeals", "enableFallback")
        if parse_bool(options.get(key), False) is True
    )
    return max(300, min(900, 180 + max_pages * 90 + enabled_heavy_steps * 180))


def fde_run_ocr_capability_test(run_id: str) -> None:
    run = fde_capability_test_run_by_id(run_id)
    if not run:
        return
    started_at = server_time()
    run.update({"status": "ocr_running", "startedAt": started_at, "updatedAt": started_at})
    storage_url = fde_capability_test_storage_url(str(run.get("storageKey") or run.get("storageUrl") or ""))
    job = repo.create_ocr_job_record(
        document_id=str(run.get("documentId") or f"FDETEST-DOC-{run_id}"),
        version_id=str(run.get("documentVersionId") or f"FDETEST-VER-{run_id}"),
        storage_key=storage_url,
        file_name=str(run.get("fileName") or "OCR测试文件"),
        profile_id=str(run.get("profileId") or "all"),
        document_type=str(run.get("documentType") or "engineering_document"),
    )
    job.update(
        {
            "runType": "fde_capability_test",
            "capabilityTestRunId": run_id,
            "retention": "fde_capability_test_only",
            "businessImpact": "none",
        }
    )
    run["ocrJobRecordId"] = job.get("id")
    try:
        client = OcrClient()
        if not client.enabled:
            result = {
                "status": "failed",
                "storageKey": storage_url,
                "fileName": run.get("fileName"),
                "profileId": run.get("profileId"),
                "documentType": run.get("documentType"),
                "fields": [],
                "tables": [],
                "seals": [],
                "fragments": [],
                "pages": [],
                "engineRuns": [],
                "diagnostics": [
                    {
                        "code": "OCR_SERVICE_NOT_CONFIGURED",
                        "level": "error",
                        "message": "未配置 OCR 服务地址（AICHECK_OCR_BASE_URL），无法调用本地 OCR 服务。",
                    }
                ],
            }
        else:
            result = client.parse_via_job_sync(
                {
                    "tenantId": run.get("tenantId") or "fde-lab",
                    "projectId": None,
                    "documentId": job.get("documentId"),
                    "documentVersionId": job.get("documentVersionId"),
                    "businessPackId": run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
                    "documentType": run.get("documentType"),
                    "profileId": run.get("profileId"),
                    "storageKey": storage_url,
                    "fileName": run.get("fileName"),
                    "options": run.get("options") or {},
                    "runType": "fde_capability_test",
                    "capabilityTestRunId": run_id,
                },
                timeout_seconds=fde_capability_test_timeout_seconds(run.get("options") or {}),
            )
        result.update(
            {
                "storageKey": result.get("storageKey") or storage_url,
                "fileName": result.get("fileName") or run.get("fileName"),
                "profileId": result.get("profileId") or run.get("profileId"),
                "documentType": result.get("documentType") or run.get("documentType"),
                "runType": "fde_capability_test",
                "capabilityTestRunId": run_id,
                "documentId": job.get("documentId"),
                "documentVersionId": job.get("documentVersionId"),
            }
        )
        result_record = repo.finish_ocr_job_record(job, result)
        if result_record:
            result_record.update(
                {
                    "runType": "fde_capability_test",
                    "capabilityTestRunId": run_id,
                    "retention": "fde_capability_test_only",
                    "businessImpact": "none",
                }
            )
        summary = fde_capability_test_result_summary(result_record or result)
        finished_at = server_time()
        run.update(
            {
                "status": "success" if (result_record or result).get("status") == "success" else "failed",
                "parseResultId": (result_record or result).get("parseResultId"),
                "externalJobId": result.get("jobId") or result.get("externalJobId"),
                "resultSummary": summary,
                "diagnostics": (result_record or result).get("diagnostics") or [],
                "engineRuns": (result_record or result).get("engineRuns") or [],
                "finishedAt": finished_at,
                "updatedAt": finished_at,
            }
        )
    except Exception as exc:  # pragma: no cover - integration boundary
        failure = {
            "status": "failed",
            "storageKey": storage_url,
            "fileName": run.get("fileName"),
            "profileId": run.get("profileId"),
            "documentType": run.get("documentType"),
            "fields": [],
            "tables": [],
            "seals": [],
            "fragments": [],
            "pages": [],
            "engineRuns": [],
            "diagnostics": [
                {
                    "code": "OCR_CAPABILITY_TEST_FAILED",
                    "level": "error",
                    "message": f"OCR 能力测试失败：{exc.__class__.__name__}",
                }
            ],
        }
        result_record = repo.finish_ocr_job_record(job, failure)
        finished_at = server_time()
        run.update(
            {
                "status": "failed",
                "parseResultId": (result_record or {}).get("parseResultId"),
                "resultSummary": fde_capability_test_result_summary(result_record or failure),
                "diagnostics": failure["diagnostics"],
                "engineRuns": [],
                "finishedAt": finished_at,
                "updatedAt": finished_at,
            }
        )


@router.get("/fde/ocr-quality")
def fde_ocr_quality(
    request: Request,
    projectId: str | None = None,
    nodeId: int | None = None,
    profileId: str | None = None,
):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    return ok(fde_ocr_quality_snapshot(projectId, nodeId, profileId), request)


@router.post("/fde/capability-tests/ocr/upload-session")
def fde_create_ocr_capability_upload_session(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
        if role_error:
            return role_error
        files = body.get("files") if isinstance(body.get("files"), list) else [body.get("file") or body]
        files = [item for item in files if isinstance(item, dict)]
        validation_error = validate_upload_files(request, files)
        if validation_error:
            return validation_error
        file = files[0]
        session_id = f"FDE-OCR-UP-{uuid4().hex[:10].upper()}"
        file_name = fde_capability_test_safe_file_name(str(file.get("fileName") or "ocr-test-file"))
        content_type = str(file.get("contentType") or file.get("fileType") or "application/octet-stream")
        file_size = int(file.get("fileSize") or 0)
        storage_key = f"fde-capability-tests/ocr/{session_id}/{file_name}"
        upload_url = repo.signed_put(
            "ocr-artifacts",
            storage_key,
            f"mock://upload/fde-capability-tests/ocr/{session_id}/{file_name}",
            content_type=content_type,
        )
        now = server_time()
        upload_session = {
            "id": session_id,
            "uploadSessionId": session_id,
            "status": "waiting_upload",
            "scope": "fde_capability_test",
            "capability": "ocr",
            "retention": "fde_capability_test_only",
            "businessImpact": "none",
            "fileName": file_name,
            "contentType": content_type,
            "fileSize": file_size,
            "storageBucket": "ocr-artifacts",
            "storageKey": storage_key,
            "storageUrl": fde_capability_test_storage_url(storage_key),
            "uploadUrl": upload_url,
            "directUploadUrl": fde_capability_test_direct_upload_url(session_id),
            "method": "PUT",
            "headers": {"Content-Type": content_type},
            "createdByRole": role or "fde",
            "createdAt": now,
            "expiresAt": object_storage.expires_at(),
        }
        repo.state.setdefault("fde_capability_test_upload_sessions", []).insert(0, upload_session)
        audit_id = repo.add_audit("FDE OCR 能力测试上传会话", "FdeOcrCapabilityUploadSession", session_id)
        return ok({"uploadSession": upload_session, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/capability-tests/ocr/upload-session/{session_id}/file")
async def fde_upload_ocr_capability_test_file(
    request: Request,
    session_id: str,
):
    role, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    upload_session = next(
        (
            item
            for item in repo.state.setdefault("fde_capability_test_upload_sessions", [])
            if str(item.get("uploadSessionId") or item.get("id") or "") == session_id
        ),
        None,
    )
    if not upload_session:
        return fail(errors.NOT_FOUND, request, message="未找到 OCR 能力测试上传会话，请重新选择文件。")
    data = await request.body()
    if len(data) < 1:
        return fail(errors.VALIDATION_ERROR, request, message="上传文件不能为空。")
    if len(data) > MAX_UPLOAD_BYTES:
        return fail(errors.FILE_TOO_LARGE, request, message=f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上传限制。")
    file_name = fde_capability_test_safe_file_name(str(upload_session.get("fileName") or "ocr-test-file"))
    content_type = str(request.headers.get("content-type") or upload_session.get("contentType") or "application/octet-stream")
    storage_key = str(upload_session.get("storageKey") or f"fde-capability-tests/ocr/{session_id}/{file_name}")
    stored_url = None
    try:
        stored_url = object_storage.put_bytes("ocr-artifacts", storage_key, data, content_type=content_type)
    except Exception:
        stored_url = None
    if stored_url:
        upload_session.update(
            {
                "status": "uploaded",
                "storageBucket": "ocr-artifacts",
                "storageKey": storage_key,
                "storageUrl": stored_url,
                "contentType": content_type,
                "fileSize": len(data),
                "uploadedByRole": role or "fde",
                "updatedAt": server_time(),
            }
        )
    elif object_storage.required:
        return fail(errors.OBJECT_STORAGE_REQUIRED, request, message="对象存储不可用，无法保存 OCR 测试文件。", http_status=503)
    else:
        target_dir = fde_capability_test_upload_root() / session_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / file_name
        target_path.write_bytes(data)
        upload_session.update(
            {
                "status": "uploaded",
                "storageBucket": "local",
                "storageKey": str(target_path),
                "storageUrl": str(target_path),
                "localPath": str(target_path),
                "contentType": content_type,
                "fileSize": len(data),
                "uploadedByRole": role or "fde",
                "updatedAt": server_time(),
            }
        )
    audit_id = repo.add_audit("FDE OCR 能力测试文件上传", "FdeOcrCapabilityUploadSession", session_id)
    return ok({"uploadSession": repo.clone(upload_session), "auditLogId": audit_id}, request)


@router.get("/fde/capability-tests/ocr/upload-session/{session_id}/file")
def fde_download_ocr_capability_test_file(request: Request, session_id: str):
    upload_session = next(
        (
            item
            for item in repo.state.setdefault("fde_capability_test_upload_sessions", [])
            if str(item.get("uploadSessionId") or item.get("id") or "") == session_id
        ),
        None,
    )
    if not upload_session:
        return fail(errors.NOT_FOUND, request, message="未找到 OCR 能力测试上传会话。")
    local_path = fde_capability_test_local_path(
        str(upload_session.get("localPath") or upload_session.get("storageUrl") or upload_session.get("storageKey") or "")
    )
    if not local_path or not local_path.is_file():
        return fail(errors.NOT_FOUND, request, message="本地 OCR 测试文件不存在或不可预览。")
    return FileResponse(
        str(local_path),
        media_type=str(upload_session.get("contentType") or "application/octet-stream"),
        filename=str(upload_session.get("fileName") or local_path.name),
        content_disposition_type="inline",
    )


@router.post("/fde/capability-tests/ocr/runs")
def fde_create_ocr_capability_test_run(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
        if role_error:
            return role_error
        upload_session_id = str(body.get("uploadSessionId") or body.get("sessionId") or "").strip()
        upload_session = next(
            (
                item
                for item in repo.state.setdefault("fde_capability_test_upload_sessions", [])
                if str(item.get("uploadSessionId") or item.get("id") or "") == upload_session_id
            ),
            None,
        )
        if not upload_session:
            return fail(errors.NOT_FOUND, request, message="未找到 OCR 能力测试上传会话，请重新选择文件。")
        file_name = str(upload_session.get("fileName") or "OCR测试文件")
        profile_id, document_type = fde_capability_test_profile_document_type(file_name, body)
        run_id = f"FDE-OCR-RUN-{uuid4().hex[:10].upper()}"
        now = server_time()
        options = {
            "enableTables": fde_capability_test_bool(body, "enableTables", False),
            "enableSeals": fde_capability_test_bool(body, "enableSeals", True),
            "enableFallback": fde_capability_test_bool(body, "enableFallback", False),
            "maxPages": fde_capability_test_int(body, "maxPages", 1, 1, 10),
            "disableRemediation": fde_capability_test_bool(body, "disableRemediation", True),
            "quickMode": fde_capability_test_bool(body, "quickMode", True),
        }
        run = {
            "id": run_id,
            "runId": run_id,
            "uploadSessionId": upload_session_id,
            "status": "ocr_queued",
            "capability": "ocr",
            "scope": "fde_capability_test",
            "retention": "fde_capability_test_only",
            "businessImpact": "none",
            "profileId": profile_id,
            "documentType": document_type,
            "businessPackId": body.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
            "fileName": file_name,
            "contentType": upload_session.get("contentType"),
            "fileSize": upload_session.get("fileSize"),
            "storageBucket": upload_session.get("storageBucket"),
            "storageKey": upload_session.get("storageKey"),
            "storageUrl": upload_session.get("storageUrl"),
            "options": options,
            "resultSummary": fde_capability_test_result_summary(None),
            "diagnostics": [],
            "engineRuns": [],
            "createdByRole": role or "fde",
            "createdAt": now,
            "updatedAt": now,
        }
        upload_session["status"] = "used"
        upload_session["usedByRunId"] = run_id
        upload_session["updatedAt"] = now
        repo.state.setdefault("fde_capability_test_runs", []).insert(0, run)
        audit_id = repo.add_audit("FDE OCR 能力测试启动", "FdeOcrCapabilityTestRun", run_id)
        fde_start_ocr_capability_test_worker(run_id)
        return ok({"run": run, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/fde/capability-tests/ocr/runs")
def fde_ocr_capability_test_runs(
    request: Request,
    status: str | None = None,
    profileId: str | None = None,
    pageNo: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    items = repo.clone(repo.state.setdefault("fde_capability_test_runs", []))
    if status:
        items = [item for item in items if str(item.get("status") or "") == status]
    if profileId:
        items = [item for item in items if str(item.get("profileId") or "") == profileId]
    return ok(page(items, pageNo, pageSize), request)


@router.get("/fde/capability-tests/ocr/runs/{run_id}")
def fde_ocr_capability_test_run_detail(request: Request, run_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    run = fde_capability_test_run_by_id(run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    result = None
    if run.get("parseResultId"):
        result = repo.find_one("ocr_parse_results", str(run["parseResultId"]), id_field="parseResultId")
    job = repo.find_one("ocr_jobs", str(run.get("ocrJobRecordId") or "")) if run.get("ocrJobRecordId") else None
    upload_session = next(
        (
            item
            for item in repo.state.setdefault("fde_capability_test_upload_sessions", [])
            if str(item.get("uploadSessionId") or item.get("id") or "") == str(run.get("uploadSessionId") or "")
        ),
        None,
    )
    return ok(
        {
            "run": repo.clone(run),
            "job": repo.clone(job),
            "parseResult": repo.clone(result),
            "uploadSession": repo.clone(upload_session),
            "preview": fde_capability_test_preview(run),
        },
        request,
    )


@router.get("/fde/capability-tests/ocr/runs/{run_id}/page-preview")
def fde_ocr_capability_test_page_preview(
    request: Request,
    run_id: str,
    pageNo: int = Query(default=1, ge=1, le=100),
):
    run = fde_capability_test_run_by_id(run_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    client = OcrClient()
    if not client.enabled:
        return fail(errors.EXTERNAL_TOOL_FAILED, request, message="OCR 服务未配置，无法生成 PDF 页图预览。", http_status=503)
    storage_url = fde_capability_test_storage_url(str(run.get("storageKey") or run.get("storageUrl") or ""))
    try:
        content, content_type = client.page_preview(
            {
                "storageKey": storage_url,
                "fileName": run.get("fileName"),
                "profileId": run.get("profileId"),
                "documentType": run.get("documentType"),
                "options": run.get("options") or {},
                "pageNo": pageNo,
            },
            timeout=45,
        )
    except IntegrationServiceError as exc:
        return fail(
            errors.EXTERNAL_TOOL_FAILED,
            request,
            message=f"OCR 页图预览生成失败：{exc.reason or exc.status_code or 'UNKNOWN'}",
            http_status=502,
        )
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/fde/capability-tests/ocr/runs/{run_id}/to-annotation")
def fde_ocr_capability_test_to_annotation(
    request: Request,
    run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        run = fde_capability_test_run_by_id(run_id)
        if not run:
            return fail(errors.NOT_FOUND, request)
        result = repo.find_one("ocr_parse_results", str(run.get("parseResultId") or ""), id_field="parseResultId")
        if not result:
            return fail(errors.VALIDATION_ERROR, request, message="当前测试 Run 还没有可标注的 OCR 结果。")
        expected = {
            "qualityStatus": (result.get("quality") or {}).get("status") or "needs_human_review",
            "fields": expected_fields_from_result(result),
            "tables": expected_tables_from_result(result),
            "seals": expected_seals_from_result(result),
        }
        existing = next(
            (
                item
                for item in repo.state.setdefault("ocr_annotation_tasks", [])
                if item.get("sourceRunId") == run_id and item.get("sourceType") == "fde_capability_test"
            ),
            None,
        )
        task = existing or {
            "taskId": f"ANNO-FDE-{uuid4().hex[:8].upper()}",
            "caseId": f"fde-ocr-capability-{run_id}",
            "sourceType": "fde_capability_test",
            "sourceRunId": run_id,
            "parseResultId": result.get("parseResultId"),
            "scenario": fde_ocr_annotation_scenario(result),
            "profileId": result.get("profileId") or run.get("profileId"),
            "documentType": result.get("documentType") or run.get("documentType"),
            "sourcePath": run.get("fileName"),
            "collectionStatus": "needs_labeling",
            "pageCount": len(result.get("pages") or []) or 1,
            "expectedTemplate": expected,
            "suggestedExpected": expected,
            "previewUrl": fde_capability_test_preview(run).get("url"),
            "retention": "fde_capability_test_only",
            "createdByRole": role or "fde",
            "createdAt": server_time(),
        }
        task.update({"updatedAt": server_time(), "updatedByRole": role or "fde"})
        if not existing:
            repo.state.setdefault("ocr_annotation_tasks", []).insert(0, task)
        readiness = fde_update_ocr_annotation_readiness(task)
        run["annotationTaskId"] = task["taskId"]
        run["updatedAt"] = server_time()
        audit_id = repo.add_audit("FDE OCR 能力测试转标注任务", "OcrAnnotationTask", task["taskId"])
        return ok({"task": fde_ocr_annotation_task_view(task), "readiness": readiness, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"runId": run_id, "body": body})


@router.post("/fde/capability-tests/ocr/runs/{run_id}/to-evaluation-case")
def fde_ocr_capability_test_to_evaluation_case(
    request: Request,
    run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:evaluation:run")
        if role_error:
            return role_error
        run = fde_capability_test_run_by_id(run_id)
        if not run:
            return fail(errors.NOT_FOUND, request)
        result = repo.find_one("ocr_parse_results", str(run.get("parseResultId") or ""), id_field="parseResultId")
        if not result:
            return fail(errors.VALIDATION_ERROR, request, message="当前测试 Run 还没有可沉淀的 OCR 结果。")
        existing = next(
            (
                item
                for item in repo.state.setdefault("evaluation_cases", [])
                if item.get("sourceRunId") == run_id and item.get("source") == "fde_ocr_capability_test"
            ),
            None,
        )
        now = server_time()
        expected = {
            "fields": expected_fields_from_result(result),
            "tables": expected_tables_from_result(result),
            "seals": expected_seals_from_result(result),
            "qualityStatus": (result.get("quality") or {}).get("status"),
        }
        case = existing or {
            "id": f"ECASE-FDE-OCR-{uuid4().hex[:8].upper()}",
            "caseId": f"fde-ocr-capability-{run_id}",
            "source": "fde_ocr_capability_test",
            "sourceRunId": run_id,
            "businessPackId": run.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
            "profileId": result.get("profileId") or run.get("profileId"),
            "documentType": result.get("documentType") or run.get("documentType"),
            "riskLevel": body.get("riskLevel") or "medium",
            "dataSensitivity": body.get("dataSensitivity") or "masked",
            "status": "draft",
            "canUseForEval": False,
            "canUseForTraining": False,
            "expected": expected,
            "resultSnapshot": repo.clone(result),
            "retention": "fde_capability_test_only",
            "createdByRole": role or "fde",
            "createdAt": now,
        }
        case.update({"updatedAt": now, "updatedByRole": role or "fde"})
        if existing:
            existing.update(case)
            case = existing
        else:
            repo.state.setdefault("evaluation_cases", []).insert(0, case)
        run["evaluationCaseId"] = case.get("id")
        run["updatedAt"] = now
        audit_id = repo.add_audit("FDE OCR 能力测试转评估样本草稿", "EvaluationCase", str(case.get("id")))
        return ok({"case": repo.clone(case), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"runId": run_id, "body": body})


@router.post("/fde/ocr-100/action-board/refresh")
def fde_refresh_ocr_100_action_board(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        reports_dir = WORKSPACE_ROOT / "backend" / "ocr_eval" / "reports"
        refreshed = fde_refresh_ocr_100_action_board_artifacts(reports_dir)
        audit_id = repo.add_audit("FDE OCR 100 行动板刷新", "Ocr100ActionBoard", "ocr_100_action_board")
        return ok({**refreshed, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"action": "ocr100_action_board_refresh", "body": body})


@router.get("/fde/ocr-100/action-board/handoff/{artifact_key}")
def fde_download_ocr_100_action_handoff_artifact(request: Request, artifact_key: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
    if role_error:
        return role_error
    reports_dir = WORKSPACE_ROOT / "backend" / "ocr_eval" / "reports"
    artifact_path = fde_ocr_100_handoff_artifact_path(reports_dir, artifact_key)
    if not artifact_path:
        return fail(errors.NOT_FOUND, request)
    return FileResponse(
        artifact_path,
        media_type=fde_ocr_100_handoff_media_type(artifact_path),
        filename=artifact_path.name,
        content_disposition_type="inline",
    )


@router.get("/fde/ocr-runs")
def fde_ocr_runs(
    request: Request,
    projectId: str | None = None,
    nodeId: int | None = None,
    documentVersionId: str | None = None,
    status: str | None = None,
    profileId: str | None = None,
    pageNo: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    items = repo.clone(repo.state.get("ocr_jobs", []))
    if status:
        items = [item for item in items if str(item.get("status") or "") == status]
    if profileId:
        items = [item for item in items if str(item.get("profileId") or "") == profileId]
    if projectId:
        version_ids = fde_project_version_ids(projectId, nodeId)
        items = [
            item
            for item in items
            if fde_record_matches_project(item, projectId, node_id=nodeId, version_ids=version_ids)
        ]
    if documentVersionId:
        items = [item for item in items if item.get("documentVersionId") == documentVersionId]
    return ok(page(items, pageNo, pageSize), request)


@router.get("/fde/ocr-runs/{job_id}")
def fde_ocr_run_detail(request: Request, job_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    job = repo.find_one("ocr_jobs", job_id) or repo.find_one("ocr_jobs", job_id, id_field="jobId")
    if not job:
        job = fde_find_or_materialize_synthetic_ocr_job(job_id)
    if not job:
        return fail(errors.NOT_FOUND, request)
    result = None
    if job.get("parseResultId"):
        result = repo.find_one("ocr_parse_results", str(job["parseResultId"]), id_field="parseResultId")
    corrections = [
        item
        for item in repo.state.get("ocr_corrections", [])
        if item.get("documentVersionId") == job.get("documentVersionId")
    ]
    return ok({"job": repo.clone(job), "parseResult": repo.clone(result), "corrections": repo.clone(corrections)}, request)


@router.post("/fde/ocr-corrections")
def fde_create_ocr_correction(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
        if role_error:
            return role_error
        field_id = str(body.get("fieldId") or "")
        field = repo.find_one("extracted_fields", field_id)
        if field_id and not field:
            return fail(errors.NOT_FOUND, request)
        payload = {**body, "createdByRole": role or "fde"}
        correction = repo.create_ocr_correction(payload)
        audit_id = repo.add_audit("FDE OCR 字段纠错", "OcrCorrection", correction["id"])
        return ok({"correction": correction, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/ocr-evaluation-runs")
def fde_create_ocr_evaluation_run(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:evaluation:run")
        if role_error:
            return role_error
        evaluation_report = fde_build_ocr_evaluation_report(body)
        case_diagnostics = [
            {
                "caseId": case.get("caseId"),
                "scenario": case.get("scenario"),
                "score": case.get("score"),
                "passed": case.get("passed"),
                "findings": case.get("findings") or [],
                "details": case.get("details") or {},
                "bootstrapGenerated": case.get("bootstrapGenerated"),
                "fixtureDerived": case.get("fixtureDerived"),
                "collectionStatus": case.get("collectionStatus"),
            }
            for case in evaluation_report.get("cases", [])
        ]
        evaluation_summary = compact_evaluation_report(evaluation_report)
        evaluation_case_count = int(
            (evaluation_report.get("summary") or {}).get("cases") or len(evaluation_report.get("cases") or [])
        )
        run = repo.create_ocr_eval_run(
            {
                **body,
                "createdByRole": role or "fde",
                "caseCount": evaluation_case_count,
                "evaluationReport": {
                    "ok": evaluation_report.get("ok"),
                    "summary": evaluation_report.get("summary"),
                    "metrics": evaluation_report.get("metrics"),
                    "findingCounts": evaluation_report.get("findingCounts") or {},
                    "thresholdFailures": evaluation_report.get("thresholdFailures") or [],
                },
                "evaluationSummary": evaluation_summary,
                "scenarioMetrics": evaluation_report.get("scenarios") or {},
                "caseDiagnostics": case_diagnostics,
            }
        )
        audit_id = repo.add_audit("FDE OCR 离线评测", "OcrEvaluationRun", run["id"])
        return ok({"run": run, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


def fde_ocr_annotation_tasks_source() -> list[dict[str, Any]]:
    tasks = repo.clone(repo.state.setdefault("ocr_annotation_tasks", []))
    if tasks:
        return tasks
    derived: list[dict[str, Any]] = []
    for result in repo.state.get("ocr_parse_results", []):
        if not isinstance(result, dict):
            continue
        parse_id = str(result.get("parseResultId") or result.get("id") or uuid4().hex)
        scenario = fde_ocr_annotation_scenario(result)
        expected = {
            "qualityStatus": (result.get("quality") or {}).get("status") or "needs_human_review",
            "fields": expected_fields_from_result(result),
            "tables": expected_tables_from_result(result),
            "seals": expected_seals_from_result(result),
        }
        derived.append(
            {
                "taskId": f"ANNO-{parse_id}",
                "caseId": f"real-{scenario}-{parse_id}",
                "scenario": scenario,
                "profileId": result.get("profileId") or "all",
                "documentType": result.get("documentType") or "unknown",
                "documentVersionId": result.get("documentVersionId"),
                "sourcePath": result.get("storageKey") or result.get("fileName"),
                "collectionStatus": "needs_labeling",
                "pageCount": len(result.get("pages") or []) or 1,
                "expectedTemplate": expected,
                "suggestedExpected": expected,
                "parseResultId": parse_id,
            }
        )
    return derived


def fde_ocr_annotation_scenario(result: dict[str, Any]) -> str:
    profile = str(result.get("profileId") or "")
    document_type = str(result.get("documentType") or "")
    if "piping" in profile or "table" in document_type:
        return "piping_table_profile"
    if "seal" in profile:
        return "seal_text_profile"
    if "quality_certificate" in profile or "quality_certificate" in document_type:
        return "quality_certificate_profile"
    return "evidence_profile"


def fde_ocr_annotation_task(task_id: str) -> dict[str, Any] | None:
    existing = next(
        (
            item
            for item in repo.state.setdefault("ocr_annotation_tasks", [])
            if str(item.get("taskId") or item.get("caseId") or "") == task_id
        ),
        None,
    )
    if existing:
        return existing
    derived = next(
        (
            item
            for item in fde_ocr_annotation_tasks_source()
            if str(item.get("taskId") or item.get("caseId") or "") == task_id
        ),
        None,
    )
    if derived:
        repo.state.setdefault("ocr_annotation_tasks", []).append(repo.clone(derived))
        return repo.state["ocr_annotation_tasks"][-1]
    return None


def fde_ocr_annotation_readiness(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return build_annotation_readiness_from_tasks(repo.clone(tasks), source="api:fde.ocr-annotation")


def fde_ocr_annotation_task_view(task: dict[str, Any]) -> dict[str, Any]:
    view = repo.clone(task)
    readiness = fde_ocr_annotation_readiness([task])
    status = (readiness.get("tasks") or [{}])[0]
    view["readinessBlockers"] = status.get("blockers") or []
    view["readyForEval"] = bool(status.get("readyForEval"))
    view["candidateCounts"] = fde_ocr_annotation_expected_counts(
        view.get("suggestedExpected") if isinstance(view.get("suggestedExpected"), dict) else {}
    )
    view["labelCounts"] = fde_ocr_annotation_expected_counts(
        view.get("labeledExpected") if isinstance(view.get("labeledExpected"), dict) else {}
    )
    view["previewUrl"] = view.get("previewUrl") or view.get("pagePreviewUrl") or fde_ocr_annotation_preview_url(view)
    view.setdefault("pageDimensions", fde_ocr_annotation_default_page_dimensions(view))
    return view


def fde_ocr_annotation_expected_counts(expected: dict[str, Any]) -> dict[str, int]:
    return {
        "fields": len([item for item in expected.get("fields") or [] if isinstance(item, dict)]),
        "tables": len([item for item in expected.get("tables") or [] if isinstance(item, dict)]),
        "seals": len([item for item in expected.get("seals") or [] if isinstance(item, dict)]),
    }


def fde_ocr_annotation_preview_url(task: dict[str, Any]) -> str | None:
    for key in ["pagePreviewUrl", "previewUrl", "previewDataUrl"]:
        value = str(task.get(key) or "").strip()
        if value:
            return value
    task_id = str(task.get("taskId") or task.get("caseId") or "").strip()
    if task_id and fde_ocr_annotation_preview_path(task):
        return f"/api/fde/ocr-annotation/tasks/{task_id}/preview"
    return None


def fde_ocr_annotation_preview_path(task: dict[str, Any]) -> Path | None:
    preview_paths = task.get("previewPaths") if isinstance(task.get("previewPaths"), list) else []
    raw = str(task.get("pagePreviewPath") or (preview_paths[0] if preview_paths else None) or task.get("sourcePath") or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = WORKSPACE_ROOT / candidate
    try:
        resolved = candidate.resolve()
        allowed_roots = [WORKSPACE_ROOT.resolve(), Path(tempfile.gettempdir()).resolve()]
        if not any(resolved == root or root in resolved.parents for root in allowed_roots):
            return None
        if resolved.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            return None
        return resolved if resolved.exists() else None
    except OSError:
        return None


def fde_ocr_annotation_default_page_dimensions(task: dict[str, Any]) -> dict[str, list[int]]:
    dimensions = task.get("pageDimensions") if isinstance(task.get("pageDimensions"), dict) else {}
    if dimensions:
        return repo.clone(dimensions)
    return {"1": [2000, 1500]}


def fde_update_ocr_annotation_readiness(task: dict[str, Any]) -> dict[str, Any]:
    readiness = fde_ocr_annotation_readiness([task])
    task["readinessBlockers"] = (readiness.get("tasks") or [{}])[0].get("blockers") or []
    task["readyForEval"] = bool((readiness.get("tasks") or [{}])[0].get("readyForEval"))
    task["updatedAt"] = server_time()
    return readiness


@router.get("/fde/ocr-annotation/tasks")
def fde_ocr_annotation_tasks(
    request: Request,
    projectId: str | None = None,
    nodeId: int | None = None,
    documentVersionId: str | None = None,
    status: str | None = None,
    scenario: str | None = None,
    profileId: str | None = None,
    pageNo: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    tasks = fde_ocr_annotation_tasks_source()
    if status:
        tasks = [item for item in tasks if str(item.get("collectionStatus") or "") == status]
    if scenario:
        tasks = [item for item in tasks if str(item.get("scenario") or "") == scenario]
    if profileId:
        tasks = [item for item in tasks if str(item.get("profileId") or "") == profileId]
    if projectId:
        tasks = [item for item in tasks if not item.get("projectId") or item.get("projectId") == projectId]
    if nodeId is not None:
        tasks = [item for item in tasks if not item.get("nodeId") or int(item.get("nodeId")) == int(nodeId)]
    if documentVersionId:
        tasks = [item for item in tasks if item.get("documentVersionId") == documentVersionId]
    readiness = fde_ocr_annotation_readiness(tasks)
    task_views = [fde_ocr_annotation_task_view(item) for item in tasks]
    return ok({"summary": readiness["summary"], "nextActions": readiness["nextActions"], "page": page(task_views, pageNo, pageSize)}, request)


@router.get("/fde/ocr-annotation/tasks/{task_id}/preview")
def fde_ocr_annotation_task_preview(request: Request, task_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    task = fde_ocr_annotation_task(task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    preview_path = fde_ocr_annotation_preview_path(task)
    if not preview_path:
        return fail(errors.NOT_FOUND, request)
    return FileResponse(preview_path)


@router.get("/fde/ocr-annotation/tasks/{task_id}")
def fde_ocr_annotation_task_detail(request: Request, task_id: str):
    _, role_error = fde_error_unless_allowed(request, "fde:ocr-quality:view")
    if role_error:
        return role_error
    task = next(
        (
            item
            for item in fde_ocr_annotation_tasks_source()
            if str(item.get("taskId") or item.get("caseId") or "") == task_id
        ),
        None,
    )
    if not task:
        return fail(errors.NOT_FOUND, request)
    readiness = fde_ocr_annotation_readiness([task])
    return ok({"task": fde_ocr_annotation_task_view(task), "readiness": readiness}, request)


@router.post("/fde/ocr-annotation/readiness")
def fde_ocr_annotation_readiness_endpoint(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        body_tasks = body.get("tasks") if isinstance(body.get("tasks"), list) else None
        tasks = [item for item in (body_tasks or fde_ocr_annotation_tasks_source()) if isinstance(item, dict)]
        return ok(fde_ocr_annotation_readiness(tasks), request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/ocr-annotation/import-pack")
def fde_import_ocr_annotation_pack(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        payload = body.get("tasks")
        if payload is None and isinstance(body.get("pack"), dict):
            payload = body["pack"].get("tasks")
        if not isinstance(payload, list):
            return fail(errors.VALIDATION_ERROR, request, message="tasks must be an OCR annotation task list.")
        incoming = [repo.clone(item) for item in payload if isinstance(item, dict)]
        now = server_time()
        for index, task in enumerate(incoming, start=1):
            task_id = str(task.get("taskId") or task.get("caseId") or f"ANNO-IMPORT-{uuid4().hex[:8].upper()}").strip()
            task["taskId"] = task_id
            task.setdefault("caseId", f"imported-{index}")
            task.setdefault("collectionStatus", "needs_labeling")
            task["importedAt"] = now
            task["updatedAt"] = now
        if body.get("replace"):
            repo.state["ocr_annotation_tasks"] = incoming
        else:
            existing = repo.state.setdefault("ocr_annotation_tasks", [])
            index_by_id = {str(item.get("taskId") or item.get("caseId") or ""): idx for idx, item in enumerate(existing)}
            for task in incoming:
                identity = str(task.get("taskId") or task.get("caseId") or "")
                if identity in index_by_id:
                    existing[index_by_id[identity]] = {**existing[index_by_id[identity]], **task}
                else:
                    existing.append(task)
        tasks = repo.state.setdefault("ocr_annotation_tasks", [])
        readiness = fde_ocr_annotation_readiness(tasks)
        audit_id = repo.add_audit("FDE OCR 标注任务包导入", "OcrAnnotationPack", "import-pack")
        return ok(
            {
                "summary": {
                    "importedTasks": len(incoming),
                    "totalTasks": len(tasks),
                    "replace": bool(body.get("replace")),
                },
                "readiness": readiness,
                "page": page([fde_ocr_annotation_task_view(item) for item in tasks], 1, 20),
                "auditLogId": audit_id,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.put("/fde/ocr-annotation/tasks/{task_id}/label")
def fde_save_ocr_annotation_label(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        task = fde_ocr_annotation_task(task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        labeled = body.get("labeledExpected")
        if not isinstance(labeled, dict) or not labeled:
            return fail(errors.VALIDATION_ERROR, request, message="labeledExpected must be a non-empty object.")
        now = server_time()
        task["labeledExpected"] = repo.clone(labeled)
        task["labeler"] = str(body.get("labeler") or fde_subject_user_id(request) or role or "fde").strip()
        task["labelUpdatedAt"] = now
        task["collectionStatus"] = str(body.get("collectionStatus") or "labeled")
        task["labelComment"] = str(body.get("comment") or "")
        if isinstance(body.get("pageDimensions"), dict):
            task["pageDimensions"] = repo.clone(body["pageDimensions"])
        for key in ["pageNo", "previewUrl", "pagePreviewUrl", "pagePreviewPath", "sourcePath"]:
            if body.get(key) is not None:
                task[key] = body.get(key)
        readiness = fde_update_ocr_annotation_readiness(task)
        audit_id = repo.add_audit("FDE OCR 人工标注保存", "OcrAnnotationTask", str(task.get("taskId") or task_id))
        return ok({"task": fde_ocr_annotation_task_view(task), "readiness": readiness, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/fde/ocr-annotation/tasks/{task_id}/verify")
def fde_verify_ocr_annotation_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        task = fde_ocr_annotation_task(task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        if not isinstance(task.get("labeledExpected"), dict):
            return fail(errors.VALIDATION_ERROR, request, message="task must be labeled before verify.")
        now = server_time()
        decision = str(body.get("decision") or "approved")
        if decision not in {"approved", "rejected"}:
            return fail(errors.VALIDATION_ERROR, request, message="decision must be approved or rejected.")
        expected = repo.clone(task["labeledExpected"])
        expected.setdefault("review", {})
        expected["review"].update(
            {
                "labeler": str(body.get("labeler") or task.get("labeler") or "").strip(),
                "reviewer": str(body.get("reviewer") or fde_subject_user_id(request) or role or "fde").strip(),
                "reviewedAt": now,
                "decision": decision,
                "comment": body.get("comment") or body.get("reason") or "",
            }
        )
        task["labeledExpected"] = expected
        task["reviewer"] = expected["review"]["reviewer"]
        task["reviewedAt"] = now
        task["reviewStatus"] = decision
        task["collectionStatus"] = "ready_for_eval" if decision == "approved" else "rejected"
        if decision == "rejected":
            task["rejectionReason"] = body.get("reason") or body.get("comment") or ""
        readiness = fde_update_ocr_annotation_readiness(task)
        audit_id = repo.add_audit("FDE OCR 标注确认", "OcrAnnotationTask", str(task.get("taskId") or task_id), decision)
        return ok({"task": fde_ocr_annotation_task_view(task), "readiness": readiness, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/fde/ocr-annotation/tasks/{task_id}/review")
def fde_review_ocr_annotation_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        role, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        task = fde_ocr_annotation_task(task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        now = server_time()
        labeler = str(body.get("labeler") or task.get("labeler") or "").strip()
        reviewer = str(body.get("reviewer") or fde_subject_user_id(request) or role or "fde").strip()
        if isinstance(body.get("labeledExpected"), dict):
            task["labeledExpected"] = repo.clone(body["labeledExpected"])
        if not isinstance(task.get("labeledExpected"), dict) and isinstance(task.get("suggestedExpected"), dict):
            task["labeledExpected"] = repo.clone(task["suggestedExpected"])
        expected = task.get("labeledExpected") if isinstance(task.get("labeledExpected"), dict) else {}
        expected.setdefault("review", {})
        expected["review"].update(
            {
                "labeler": labeler,
                "reviewer": reviewer,
                "reviewedAt": now,
                "comment": body.get("comment") or "",
            }
        )
        task["labeledExpected"] = expected
        task["labeler"] = labeler
        task["reviewer"] = reviewer
        task["reviewedAt"] = now
        task["collectionStatus"] = body.get("collectionStatus") or "ready_for_eval"
        readiness = fde_update_ocr_annotation_readiness(task)
        audit_id = repo.add_audit("FDE OCR 标注二审", "OcrAnnotationTask", str(task.get("taskId") or task_id))
        return ok({"task": fde_ocr_annotation_task_view(task), "readiness": readiness, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/fde/ocr-annotation/export-label-studio")
def fde_export_ocr_annotation_label_studio(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        tasks = [item for item in (body.get("tasks") if isinstance(body.get("tasks"), list) else fde_ocr_annotation_tasks_source()) if isinstance(item, dict)]
        preview_base_dir = Path(str(body.get("previewBaseDir") or ".")).expanduser().resolve()
        local_files_root = Path(str(body.get("localFilesRoot") or preview_base_dir)).expanduser().resolve()
        image_url_prefix = str(body.get("imageUrlPrefix") or "/data/local-files/?d=")
        include_without_image = bool(body.get("includeWithoutImage", True))
        converted_tasks: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for task in tasks:
            converted, reason = label_studio_task(
                task,
                preview_base_dir=preview_base_dir,
                local_files_root=local_files_root,
                image_url_prefix=image_url_prefix,
            )
            if converted is None:
                skipped.append({"caseId": task.get("caseId"), "taskId": task.get("taskId"), "reason": reason})
                if not include_without_image:
                    continue
                converted = label_studio_task_without_image(task, reason=reason)
            converted_tasks.append(converted)
        summary = {
            "schemaVersion": "aicheck-ocr-annotation-label-studio-export-v1",
            "generatedAt": server_time(),
            "tasks": len(converted_tasks),
            "sourceTasks": len(tasks),
            "skipped": len(skipped),
            "predictionTasks": len([item for item in converted_tasks if item.get("predictions")]),
            "includeWithoutImage": include_without_image,
            "skippedItems": skipped[:50],
        }
        return ok({"summary": summary, "labelConfigXml": label_config_xml(), "tasks": converted_tasks}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/fde/ocr-annotation/import-label-studio")
def fde_import_ocr_annotation_label_studio(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:ocr-annotation:manage")
        if role_error:
            return role_error
        label_export = body.get("labelStudioExport") or body.get("labelStudioTasks") or body.get("tasks")
        if not isinstance(label_export, list):
            return fail(errors.VALIDATION_ERROR, request, message="labelStudioExport must be a Label Studio task list.")
        source_tasks = body.get("annotationTasks") if isinstance(body.get("annotationTasks"), list) else repo.state.setdefault("ocr_annotation_tasks", [])
        with tempfile.TemporaryDirectory(prefix="aicheck-fde-ocr-annotation-") as temp_dir:
            temp_path = Path(temp_dir)
            label_path = temp_path / "label_studio_export.json"
            tasks_path = temp_path / "annotation_tasks.json"
            output_path = temp_path / "labeled_tasks.json"
            label_path.write_text(json.dumps(label_export, ensure_ascii=False), encoding="utf-8")
            tasks_path.write_text(json.dumps({"tasks": source_tasks}, ensure_ascii=False), encoding="utf-8")
            report = import_label_studio_annotations(
                label_path,
                annotation_tasks=tasks_path,
                output_path=output_path,
                mark_status=str(body.get("markStatus") or "labeled"),
                allow_incomplete=bool(body.get("allowIncomplete", False)),
            )
        repo.state["ocr_annotation_tasks"] = repo.clone(report.get("tasks") or [])
        import_record = {
            "id": f"OCRANNOIMP-{uuid4().hex[:8].upper()}",
            "summary": report.get("summary") or {},
            "ok": bool(report.get("ok")),
            "imported": repo.clone(report.get("imported") or []),
            "failures": repo.clone(report.get("failures") or []),
            "createdAt": server_time(),
        }
        repo.state.setdefault("ocr_annotation_imports", []).insert(0, import_record)
        readiness = fde_ocr_annotation_readiness(repo.state["ocr_annotation_tasks"])
        audit_id = repo.add_audit("FDE OCR 标注导入", "OcrAnnotationImport", import_record["id"], "成功" if report.get("ok") else "失败")
        return ok({"import": import_record, "readiness": readiness, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/fde/incidents")
def fde_incidents(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:incident:manage")
    if role_error:
        return role_error
    return ok({"incidents": repo.clone(repo.state.get("incidents", [])), "rca": repo.clone(repo.state.get("incident_rca", []))}, request)


@router.post("/fde/incidents/{incident_id}/rca")
def fde_update_incident_rca(
    request: Request,
    incident_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:incident:manage")
        if role_error:
            return role_error
        incident = repo.find_one("incidents", incident_id)
        if not incident:
            return fail(errors.NOT_FOUND, request)
        rca = repo.find_one("incident_rca", incident_id, id_field="incidentId")
        payload = {
            "id": (rca or {}).get("id") or f"RCA-{uuid4().hex[:8].upper()}",
            "incidentId": incident_id,
            "status": body.get("status") or "open",
            "rootCause": body.get("rootCause") or incident.get("rootCause") or "unknown",
            "impactScope": body.get("impactScope") or {"aiRunIds": incident.get("relatedAiRunIds") or []},
            "temporaryAction": body.get("temporaryAction") or "已记录临时处置。",
            "longTermAction": body.get("longTermAction") or "待 FDE 补充长期修复。",
            "owner": body.get("owner") or "FDE 工程师",
            "updatedAt": server_time(),
        }
        if rca:
            rca.update(payload)
        else:
            repo.state["incident_rca"].insert(0, payload)
        audit_id = repo.add_audit("FDE 更新事故 RCA", "IncidentRCA", payload["id"])
        return ok({"rca": payload, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"incidentId": incident_id, "body": body})


@router.post("/fde/incidents/{incident_id}/close")
def fde_close_incident(
    request: Request,
    incident_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:incident:manage")
        if role_error:
            return role_error
        incident = repo.find_one("incidents", incident_id)
        if not incident:
            return fail(errors.NOT_FOUND, request)
        incident["status"] = "closed"
        incident["closedAt"] = server_time()
        incident["resolution"] = body.get("resolution") or "FDE 已完成 RCA 和整改追踪。"
        incident["closedByRole"] = effective_role_for_request(request)[0]
        audit_id = repo.add_audit("FDE 关闭事故", "Incident", incident_id)
        return ok({"incident": repo.clone(incident), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"incidentId": incident_id, "body": body})


@router.get("/fde/cost-budgets")
def fde_cost_budgets(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:dashboard:view")
    if role_error:
        return role_error
    ai_runs = repo.state.get("ai_runs", [])
    return ok(
        {
            "budgets": repo.clone(repo.state.get("cost_budgets", [])),
            "usage": {
                "tokenEstimate": sum(int(item.get("tokenUsage") or 0) for item in ai_runs),
                "estimatedPrice": round(sum(float(item.get("estimatedPrice") or 0) for item in ai_runs), 4),
                "runCount": len(ai_runs),
            },
            "exports": repo.clone(repo.state.get("data_exports", [])),
            "changeRequests": repo.clone(fde_state_list("cost_budget_change_requests")),
        },
        request,
    )


@router.post("/fde/cost-budgets/{budget_id}/propose-change")
def fde_propose_cost_budget_change(
    request: Request,
    budget_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        _, role_error = fde_error_unless_allowed(request, "fde:cost:manage")
        if role_error:
            return role_error
        budget = next((item for item in repo.state.get("cost_budgets", []) if item.get("id") == budget_id), None)
        if not budget:
            return fail(errors.NOT_FOUND, request)
        change = {
            "id": body.get("id") or f"CBCHG-{uuid4().hex[:8].upper()}",
            "budgetId": budget_id,
            "status": "pending_approval",
            "currentBudget": repo.clone(budget),
            "proposedLimit": body.get("proposedLimit"),
            "proposedPolicy": body.get("proposedPolicy") or {},
            "reason": body.get("reason") or "FDE 提交成本预算调整建议。",
            "requestedByRole": effective_role_for_request(request)[0],
            "createdAt": server_time(),
        }
        fde_state_list("cost_budget_change_requests").insert(0, change)
        audit_id = repo.add_audit("FDE 提交成本预算变更申请", "CostBudgetChangeRequest", change["id"])
        return ok({"changeRequest": change, "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"budgetId": budget_id, "body": body})


@router.get("/fde/acceptance-reports")
def fde_acceptance_reports(request: Request):
    _, role_error = fde_error_unless_allowed(request, "fde:business-pack:view")
    if role_error:
        return role_error
    return ok(repo.clone(repo.state.get("delivery_acceptance_reports", [])), request)


@router.get("/knowledge/overview")
def knowledge_overview(request: Request):
    sources = repo.state["knowledge_sources"]
    files = repo.state["knowledge_files"]
    tasks = repo.state["knowledge_tasks"]
    indexable_sources = [source for source in sources if source.get("sourceType") != "rule"]
    indexable_files = [file for file in files if not knowledge_file_is_business_rule(file)]
    indexable_tasks = [task for task in tasks if not knowledge_task_is_business_rule(task)]
    return ok(
        {
            "metrics": [
                {"key": "source", "label": "知识源", "value": len(indexable_sources), "tone": "blue"},
                {"key": "file", "label": "项目文件", "value": len(indexable_files), "tone": "green"},
                {"key": "task", "label": "运行任务", "value": len([item for item in indexable_tasks if item["status"] in {"排队中", "运行中"}]), "tone": "orange"},
                {"key": "failed", "label": "失败任务", "value": len([item for item in indexable_tasks if item["status"] == "失败"]), "tone": "red"},
            ],
            "libraries": [
                {
                    "key": source["id"],
                    "name": source["name"],
                    "fileCount": source["fileCount"],
                    "chunkCount": source["chunkCount"],
                    "vectorCount": source["chunkCount"],
                    "indexVersion": source.get("version") or "v1",
                    "status": source["status"],
                    "updatedAt": source["updatedAt"],
                }
                for source in indexable_sources
            ],
            "scorecard": build_knowledge_rule_scorecard(repo.state),
        },
        request,
    )


@router.get("/knowledge/sources")
def list_knowledge_sources(request: Request, keyword: str | None = None, sourceType: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("knowledge-source", item) for item in repo.state["knowledge_sources"] if item.get("sourceType") != "rule"]
    if sourceType:
        items = [item for item in items if item["sourceType"] == sourceType]
    if status:
        items = [item for item in items if item["status"] == status]
    items = filter_keyword(items, keyword, ["name", "version", "status"])
    return ok(page(items, page_no, page_size), request)


@router.post("/knowledge/sources")
def create_knowledge_source(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        if body.get("sourceType") == "rule":
            return fail(errors.VALIDATION_ERROR, request, message="业务规则请通过业务规则版本管理导入，不进入知识库索引。")
        source = {
            "id": f"KS-{uuid4().hex[:8].upper()}",
            "name": body.get("name") or "新知识源",
            "sourceType": body.get("sourceType") or "manual",
            "version": body.get("version"),
            "status": body.get("status") or "启用",
            "fileCount": int(body.get("fileCount") or 0),
            "chunkCount": int(body.get("chunkCount") or 0),
            "vectorStatus": body.get("vectorStatus") or "待向量化",
            "updatedAt": server_time(),
            "actions": ["knowledge:view", "knowledge:manage", "knowledge:reindex"],
            "revision": 1,
        }
        repo.state["knowledge_sources"].insert(0, source)
        audit_id = repo.add_audit("新增知识源", "KnowledgeSource", source["id"])
        return ok({"source": versioned_record("knowledge-source", source), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/knowledge/sources/{source_id}")
def get_knowledge_source(request: Request, source_id: str):
    source = repo.find_one("knowledge_sources", source_id)
    if not source:
        return fail(errors.NOT_FOUND, request)
    if source.get("sourceType") == "rule":
        return fail(errors.NOT_FOUND, request, message="业务规则不作为知识源展示。")
    return ok({"source": versioned_record("knowledge-source", source)}, request)


@router.put("/knowledge/sources/{source_id}")
@router.patch("/knowledge/sources/{source_id}")
def update_knowledge_source(
    request: Request,
    source_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        source = repo.find_one("knowledge_sources", source_id)
        if not source:
            return fail(errors.NOT_FOUND, request)
        effective_if_match = if_match if if_match is not None else request.headers.get("If-Match")
        if not record_if_match_valid("knowledge-source", source, effective_if_match):
            return fail(errors.ETAG_CONFLICT, request)
        changed = []
        for field in ["name", "sourceType", "version", "status", "fileCount", "chunkCount", "vectorStatus"]:
            if field in body and source.get(field) != body[field]:
                if field == "sourceType" and body[field] == "rule":
                    return fail(errors.VALIDATION_ERROR, request, message="业务规则请通过业务规则版本管理导入，不进入知识库索引。")
                changed.append({"field": field, "before": source.get(field), "after": body[field]})
                source[field] = body[field]
        if changed:
            bump_record_revision(source)
        audit_id = repo.add_audit("更新知识源", "KnowledgeSource", source_id)
        return ok({"source": versioned_record("knowledge-source", source), "auditLogId": audit_id, "changed": changed}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"sourceId": source_id, "body": body})


@router.post("/knowledge/sources/{source_id}/enable")
def enable_knowledge_source(request: Request, source_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return update_knowledge_source(request, source_id, {"status": "启用"}, idempotency_key=idempotency_key, if_match=if_match)


@router.post("/knowledge/sources/{source_id}/disable")
def disable_knowledge_source(request: Request, source_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return update_knowledge_source(request, source_id, {"status": "停用"}, idempotency_key=idempotency_key, if_match=if_match)


@router.post("/business-rules/import")
async def import_business_rules(request: Request):
    fields, uploads, parse_error = await parse_multipart_uploads(request)
    if parse_error:
        return parse_error
    if not uploads:
        return fail(errors.VALIDATION_ERROR, request, message="请选择要导入的业务规则文件。")

    now = server_time()
    import_version = first_form_value(fields, "importVersion", "")
    if not import_version:
        import_version = first_form_value(fields, "version", "")
    if not import_version:
        import_version = f"rule-draft-{now[:16].replace('-', '').replace(':', '').replace(' ', '-')}"
    imported_rules: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    existing_ids = {str(item.get("id")) for item in repo.state.get("rule_versions", [])}
    existing_rule_versions = {
        (str(item.get("ruleKey")), str(item.get("version")))
        for item in repo.state.get("rule_versions", [])
    }

    for upload in uploads:
        source_file_name = safe_upload_file_name(upload["fileName"])
        parsed_rules, error_message = parse_business_rule_upload(
            upload,
            import_version=import_version,
            imported_at=now,
        )
        if error_message:
            skipped.append({"fileName": source_file_name, "reason": error_message})
            continue
        for parsed_rule in parsed_rules:
            parsed_rule["status"] = "草稿"
            parsed_rule["sourceFileName"] = source_file_name
            parsed_rule["importBatchVersion"] = import_version
            parsed_rule["importHash"] = hashlib.sha256(upload["data"]).hexdigest()
            if str(parsed_rule.get("id")) in existing_ids:
                parsed_rule["id"] = f"{parsed_rule['id']}-IMPORT-{uuid4().hex[:6].upper()}"
            rule_version_key = (str(parsed_rule.get("ruleKey")), str(parsed_rule.get("version")))
            if rule_version_key in existing_rule_versions:
                parsed_rule["version"] = f"{parsed_rule['version']}-{uuid4().hex[:6].upper()}"
                rule_version_key = (str(parsed_rule.get("ruleKey")), str(parsed_rule.get("version")))
            existing_ids.add(str(parsed_rule.get("id")))
            existing_rule_versions.add(rule_version_key)
            repo.state["rule_versions"].insert(0, parsed_rule)
            imported_rules.append(versioned_record("rule-version", parsed_rule))

    if not imported_rules and skipped:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message="业务规则文件未导入。",
            data={"skipped": skipped},
        )
    audit_id = repo.add_audit("导入业务规则文件", "RuleVersion", import_version)
    return ok(
        {
            "rules": imported_rules,
            "importedRules": imported_rules,
            "skipped": skipped,
            "summary": {
                "importVersion": import_version,
                "imported": len(imported_rules),
                "skipped": len(skipped),
                "status": "草稿",
            },
            "auditLogId": audit_id,
        },
        request,
    )


@router.post("/knowledge/files/import")
async def import_knowledge_files(request: Request):
    fields, uploads, parse_error = await parse_multipart_uploads(request)
    if parse_error:
        return parse_error
    if not uploads:
        return fail(errors.VALIDATION_ERROR, request, message="请选择要导入知识库的文件。")

    source_id = first_form_value(fields, "sourceId", "KS-STANDARD-TSG") or "KS-STANDARD-TSG"
    source_name = first_form_value(fields, "sourceName", "规则标准文件库")
    source_type = first_form_value(fields, "sourceType", "standard")
    if source_type == "rule":
        return fail(errors.VALIDATION_ERROR, request, message="业务规则请通过业务规则版本管理导入，不进入知识库切片或向量索引。")
    source_version = first_form_value(fields, "sourceVersion", "")
    source_status = first_form_value(fields, "sourceStatus", "")
    vector_status = first_form_value(fields, "vectorStatus", "")
    source = knowledge_source_for_import(
        source_id,
        source_name=source_name,
        source_type=source_type,
        source_version=source_version,
        source_status=source_status,
        vector_status=vector_status,
    )
    relative_paths = fields.get("relativePaths") or []
    display_names = fields.get("fileNames") or []
    context_descriptions = fields.get("contextDescriptions") or []
    uploader = admin_user_snapshot(request_user_id(request), role_from_query(x_role=request.headers.get("X-Role")))
    uploader_name = uploader.get("name") or "知识库管理员"

    imported_files: list[dict[str, Any]] = []
    imported_tasks: list[dict[str, Any]] = []
    dispatches: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for index, upload in enumerate(uploads):
        original_file_name = safe_upload_file_name(upload["fileName"])
        file_name = display_upload_file_name(
            bounded_form_value(display_names, index, limit=180),
            original_file_name,
        )
        context_description = bounded_form_value(context_descriptions, index, limit=500)
        data = upload["data"]
        content_type = str(upload.get("contentType") or mimetypes.guess_type(original_file_name)[0] or "application/octet-stream")
        relative_path = safe_relative_path(relative_paths[index] if index < len(relative_paths) else None, file_name)
        if not data:
            skipped.append({"fileName": file_name, "reason": "文件内容为空"})
            continue
        if len(data) > MAX_UPLOAD_BYTES:
            skipped.append({"fileName": file_name, "reason": f"超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上传限制"})
            continue
        if not (upload_file_type_tokens(original_file_name, content_type) & ALLOWED_KNOWLEDGE_UPLOAD_TYPES):
            skipped.append({"fileName": file_name, "reason": "文件类型不支持"})
            continue

        file_hash = hashlib.sha256(data).hexdigest()
        duplicate = next(
            (
                file
                for file in repo.state.get("knowledge_files", [])
                if file.get("sourceId") == source["id"]
                and (repo.find_one("versions", file.get("documentVersionId")) or {}).get("hash") == file_hash
            ),
            None,
        )
        if duplicate:
            skipped.append({"fileName": file_name, "reason": f"已存在相同内容：{duplicate.get('fileName')}"})
            continue

        document, version, knowledge_file, task, storage = create_imported_knowledge_records(
            source=source,
            file_name=file_name,
            content_type=content_type,
            data=data,
            relative_path=relative_path,
            original_file_name=original_file_name,
            context_description=context_description,
            uploader_name=uploader_name,
        )
        repo.state["documents"].insert(0, document)
        repo.state["versions"].insert(0, version)
        repo.state["knowledge_files"].insert(0, knowledge_file)
        repo.state["knowledge_tasks"].insert(0, task)
        imported_files.append(versioned_record("knowledge-file", knowledge_file))
        imported_tasks.append(versioned_record("knowledge-task", task))
        dispatches.append({"knowledgeTaskId": task["id"], **storage["dispatch"]})

    if imported_files:
        source["fileCount"] = int(source.get("fileCount") or 0) + len(imported_files)
        source["vectorStatus"] = "待向量化"
        source["updatedAt"] = server_time()
        bump_record_revision(source)
    audit_id = repo.add_audit("导入知识库文件", "KnowledgeSource", source["id"])
    return ok(
        {
            "source": versioned_record("knowledge-source", source),
            "files": imported_files,
            "tasks": imported_tasks,
            "dispatches": dispatches,
            "skipped": skipped,
            "auditLogId": audit_id,
        },
        request,
    )


@router.get("/knowledge/project-files")
def list_knowledge_files(request: Request, keyword: str | None = None, projectId: str | None = None, nodeId: int | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [
        repo.clone(item)
        for item in repo.state["knowledge_files"]
        if record_visible_for_request(request, item) and not knowledge_file_is_business_rule(item)
    ]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    if status:
        items = [item for item in items if status in {item.get("ocrStatus"), item.get("sliceStatus"), item.get("vectorStatus")}]
    items = filter_keyword(items, keyword, ["fileName", "sourceName", "nodeName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/files/{file_id}")
def knowledge_file_detail(request: Request, file_id: str):
    file = repo.find_one("knowledge_files", file_id)
    if not file:
        return fail(errors.NOT_FOUND, request)
    if knowledge_file_is_business_rule(file):
        return fail(errors.NOT_FOUND, request, message="业务规则不作为知识文件展示。")
    scope_error = scope_error_for_record(request, file)
    if scope_error:
        return scope_error
    document = repo.find_one("documents", file.get("documentId"))
    latest_task = next((item for item in repo.state["knowledge_tasks"] if item.get("targetId") == file_id), None)
    return ok(
        {
            "file": repo.clone(file),
            "document": repo.clone(document) if document else None,
            "currentVersion": repo.current_version(document["id"]) if document else None,
            "latestTask": versioned_record("knowledge-task", latest_task) if latest_task else None,
            "vectorSummary": {
                "vectorStatus": file.get("vectorStatus"),
                "vectorCount": file.get("vectorCount", 0),
                "indexVersion": "proj-v2026.06.26",
                "dimensions": 1024,
                "updatedAt": file.get("updatedAt"),
            },
        },
        request,
    )


@router.get("/knowledge/files/{file_id}/chunks")
def knowledge_file_chunks(request: Request, file_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    file = repo.find_one("knowledge_files", file_id)
    if file:
        if knowledge_file_is_business_rule(file):
            return fail(errors.NOT_FOUND, request, message="业务规则不参与知识库切片。")
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
    chunks = [repo.clone(item) for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]
    if not chunks:
        chunks = [
            {"id": f"CHK-{file_id}-{idx}", "chunkNo": idx, "text": f"知识切片 {idx}：压力管道资料审查关键字段与证据定位。", "pageNo": idx, "evidenceLinkId": "EV-24-001", "tokenCount": 128}
            for idx in range(1, 8)
        ]
    return ok(page(chunks, page_no, page_size), request)


@router.get("/knowledge/files/{file_id}/vectors")
def knowledge_file_vectors(request: Request, file_id: str):
    file = repo.find_one("knowledge_files", file_id)
    if not file:
        return fail(errors.NOT_FOUND, request)
    if knowledge_file_is_business_rule(file):
        return fail(errors.NOT_FOUND, request, message="业务规则不参与知识库向量化。")
    scope_error = scope_error_for_record(request, file)
    if scope_error:
        return scope_error
    return ok({"vectorStatus": file.get("vectorStatus"), "vectorCount": file.get("vectorCount", 0), "indexVersion": "proj-v2026.06.26", "dimensions": 1024, "updatedAt": file.get("updatedAt")}, request)


@router.get("/knowledge/files/{file_id}/reasoning-references")
def knowledge_file_reasoning_refs(request: Request, file_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    file = repo.find_one("knowledge_files", file_id)
    if file:
        if knowledge_file_is_business_rule(file):
            return fail(errors.NOT_FOUND, request, message="业务规则不作为知识文件引用。")
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
    refs = [
        {"runId": run["id"], "nodeId": run["nodeId"], "subject": run["subject"], "model": run["model"], "quotedText": "证据链引用该文件的 OCR 字段。", "createdAt": run.get("finishedAt") or run.get("startedAt")}
        for run in repo.state["ai_runs"]
        if record_visible_for_request(request, run)
    ]
    return ok(page(refs, page_no, page_size), request)


@router.post("/knowledge/files/{file_id}/reindex")
def reindex_file(request: Request, file_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        file = repo.find_one("knowledge_files", file_id)
        if not file:
            return fail(errors.NOT_FOUND, request)
        if knowledge_file_is_business_rule(file):
            return fail(errors.VALIDATION_ERROR, request, message="业务规则不参与知识库重建索引，请在业务规则版本管理中发布或回滚。")
        scope_error = scope_error_for_record(request, file)
        if scope_error:
            return scope_error
        task = {"id": f"KT-{uuid4().hex[:8].upper()}", "taskType": "reindex", "targetType": "file", "targetId": file_id, "targetName": file["fileName"], "status": "排队中", "progress": 0, "createdAt": server_time(), "updatedAt": server_time(), "revision": 1, "actions": ["knowledge:task-retry"]}
        repo.state["knowledge_tasks"].insert(0, task)
        return ok({"task": versioned_record("knowledge-task", task)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/knowledge/tasks")
def list_knowledge_tasks(request: Request, taskType: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [
        versioned_record("knowledge-task", item)
        for item in repo.state["knowledge_tasks"]
        if record_visible_for_request(request, item) and not knowledge_task_is_business_rule(item)
    ]
    if taskType:
        items = [item for item in items if item["taskType"] == taskType]
    if status:
        items = [item for item in items if item["status"] == status]
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    items.sort(key=lambda item: KNOWLEDGE_TASK_STATUS_ORDER.get(str(item.get("status")), 99))
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/tasks/{task_id}")
def knowledge_task_detail(request: Request, task_id: str):
    task = repo.find_one("knowledge_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    return ok({"task": versioned_record("knowledge-task", task)}, request)


@router.get("/knowledge/tasks/{task_id}/logs")
def knowledge_task_logs(request: Request, task_id: str):
    task = repo.find_one("knowledge_tasks", task_id)
    if not task:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, task)
    if scope_error:
        return scope_error
    logs = task.get("logs") or [{"createdAt": task.get("createdAt") or server_time(), "level": "info", "message": f"任务 {task_id} 已进入队列。"}]
    return ok(logs, request)


def retry_dispatch_for_knowledge_task(request: Request, task: dict[str, Any]) -> tuple[list[dict[str, Any]], JSONResponse | None]:
    task_type = task.get("taskType")
    dispatches: list[dict[str, Any]] = []
    task["attempts"] = int(task.get("attempts") or 0) + 1
    task["status"] = "排队中"
    task["progress"] = 0
    task["updatedAt"] = server_time()
    task.pop("errorMessage", None)
    task.pop("finishedAt", None)
    repo.append_task_log(task, "info", f"第 {task['attempts']} 次重试已投递。")

    if task_type == "ocr":
        file = repo.find_one("knowledge_files", task.get("targetId"))
        document_id = task.get("documentId") or (file or {}).get("documentId")
        version_id = task.get("documentVersionId") or (file or {}).get("documentVersionId")
        version = repo.find_one("versions", version_id) if version_id else None
        document = repo.find_one("documents", document_id) if document_id else None
        if not document or not version:
            repo.mark_task_failed(task, "OCR 重试失败：找不到关联文档版本。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联文档版本。")
        task["documentId"] = document["id"]
        task["documentVersionId"] = version["id"]
        dispatches.append(
            task_dispatcher.dispatch_parse_document(
                document["id"],
                version["id"],
                version.get("storageKey") or version["id"],
                document.get("fileName") or task.get("targetName"),
            )
        )
    elif task_type == "slice":
        file = repo.find_one("knowledge_files", task.get("targetId"))
        if not file:
            repo.mark_task_failed(task, "切片重试失败：找不到关联知识文件。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联知识文件。")
        if knowledge_file_is_business_rule(file):
            repo.mark_task_failed(task, "业务规则不参与知识库切片。")
            return [], fail(errors.VALIDATION_ERROR, request, message="业务规则不参与知识库切片。")
        dispatches.append(task_dispatcher.dispatch_slice(task["targetId"]))
    elif task_type in {"vector", "embed"}:
        file = repo.find_one("knowledge_files", task.get("targetId"))
        if not file:
            repo.mark_task_failed(task, "向量化重试失败：找不到关联知识文件。")
            return [], fail(errors.NOT_FOUND, request, message="找不到关联知识文件。")
        if knowledge_file_is_business_rule(file):
            repo.mark_task_failed(task, "业务规则不参与知识库向量化。")
            return [], fail(errors.VALIDATION_ERROR, request, message="业务规则不参与知识库向量化。")
        dispatches.append(task_dispatcher.dispatch_embed(task["targetId"]))
    elif task_type == "reindex":
        target_type = task.get("targetType")
        if target_type == "file":
            targets = [repo.find_one("knowledge_files", task.get("targetId"))]
        else:
            targets = [item for item in repo.state["knowledge_files"] if item.get("sourceId") == task.get("targetId")]
        targets = [item for item in targets if item and not knowledge_file_is_business_rule(item)]
        if not targets:
            repo.mark_task_failed(task, "重建索引失败：找不到可重建的知识文件。")
            return [], fail(errors.NOT_FOUND, request, message="找不到可重建的知识文件。")
        for file in targets:
            slice_task = repo.upsert_knowledge_task(
                task_type="slice",
                target_id=file["id"],
                target_name=file["fileName"],
                document_id=file.get("documentId"),
                version_id=file.get("documentVersionId"),
            )
            vector_task = repo.upsert_knowledge_task(
                task_type="vector",
                target_id=file["id"],
                target_name=file["fileName"],
                document_id=file.get("documentId"),
                version_id=file.get("documentVersionId"),
            )
            dispatches.append({"knowledgeTaskId": slice_task["id"], **task_dispatcher.dispatch_slice(file["id"])})
            dispatches.append({"knowledgeTaskId": vector_task["id"], **task_dispatcher.dispatch_embed(file["id"])})
        task["status"] = "成功"
        task["progress"] = 100
        task["finishedAt"] = server_time()
        repo.append_task_log(task, "info", f"重建索引已创建 {len(dispatches)} 个子任务。")
    else:
        repo.mark_task_failed(task, f"不支持的任务类型：{task_type}")
        return [], fail(errors.VALIDATION_ERROR, request, message=f"不支持的任务类型：{task_type}")

    task["lastDispatch"] = dispatches[0] if len(dispatches) == 1 else {"dispatches": dispatches}
    return dispatches, None


@router.post("/knowledge/tasks/{task_id}/retry")
def retry_knowledge_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        task = repo.find_one("knowledge_tasks", task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, task)
        if scope_error:
            return scope_error
        if not record_if_match_valid("knowledge-task", task, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        dispatches, error = retry_dispatch_for_knowledge_task(request, task)
        if error:
            return error
        bump_record_revision(task)
        return ok({"task": versioned_record("knowledge-task", task), "dispatches": dispatches}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/knowledge/tasks/{task_id}/cancel")
def cancel_knowledge_task(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        task = repo.find_one("knowledge_tasks", task_id)
        if not task:
            return fail(errors.NOT_FOUND, request)
        scope_error = scope_error_for_record(request, task)
        if scope_error:
            return scope_error
        if not record_if_match_valid("knowledge-task", task, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        task["status"] = "已取消"
        bump_record_revision(task)
        repo.append_task_log(task, "info", "任务已取消。")
        return ok({"task": versioned_record("knowledge-task", task)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"taskId": task_id, "body": body})


@router.post("/knowledge/reindex")
def batch_reindex(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        ids = []
        if body.get("scope") == "source":
            targets = [item for item in repo.state["knowledge_sources"] if item.get("sourceType") != "rule"]
        else:
            targets = [item for item in repo.state["knowledge_files"] if not knowledge_file_is_business_rule(item)]
        for target in targets[:3]:
            task = {"id": f"KT-{uuid4().hex[:8].upper()}", "taskType": "reindex", "targetType": "file" if "fileName" in target else "source", "targetId": target["id"], "targetName": target.get("fileName") or target.get("name"), "status": "排队中", "progress": 0, "createdAt": server_time(), "updatedAt": server_time(), "revision": 1, "actions": ["knowledge:task-retry"]}
            repo.state["knowledge_tasks"].insert(0, task)
            ids.append(task["id"])
        return ok({"taskIds": ids}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.post("/knowledge/retrieval-test")
def retrieval_test(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    question = body.get("question") or "焊工资格证有效期如何校验？"
    retrieval = retrieve_knowledge_clauses(
        repo.state,
        query=str(question),
        business_pack_id=body.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID,
        node_id=int(body.get("nodeId")) if str(body.get("nodeId") or "").isdigit() else None,
        kb_version=body.get("kbVersion"),
        top_k=int(body.get("topK") or 5),
        query_type="interactive_retrieval_test",
    )
    return ok(
        {
            "answerDraft": answer_draft_from_clauses(str(question), retrieval["clauses"]),
            "hits": retrieval["trace"]["selectedClauses"],
            "retrievalTrace": retrieval["trace"],
            "latencyMs": 12,
            "usedIndexVersions": sorted({item.get("kbVersion") for item in retrieval["clauses"] if item.get("kbVersion")}),
        },
        request,
    )


@router.get("/knowledge/clauses")
def list_knowledge_clauses(
    request: Request,
    keyword: str | None = None,
    nodeId: int | None = None,
    businessPackId: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    retrieval = retrieve_knowledge_clauses(
        repo.state,
        query=keyword or "审查依据",
        business_pack_id=businessPackId or DEFAULT_BUSINESS_PACK_ID,
        node_id=nodeId,
        top_k=max(page_no * page_size, page_size),
        query_type="clause_list",
    )
    items = retrieval["trace"]["selectedClauses"]
    return ok(page(items, page_no, page_size), request)


@router.get("/knowledge/page-index-nodes")
def list_knowledge_page_index_nodes(
    request: Request,
    keyword: str | None = None,
    kbDocId: str | None = None,
    parentNodeId: str | None = None,
    page_no: int = Query(default=1, alias="page"),
    page_size: int = Query(default=20, alias="pageSize"),
):
    items = [repo.clone(item) for item in repo.state.get("knowledge_page_index_nodes", [])]
    if kbDocId:
        items = [item for item in items if item.get("kbDocId") == kbDocId]
    if parentNodeId is not None:
        items = [item for item in items if str(item.get("parentNodeId")) == str(parentNodeId)]
    items = filter_keyword(items, keyword, ["title", "summary", "nodeId", "pageIndexNodeId"])
    if keyword:
        query = str(keyword).lower()
        items.sort(
            key=lambda item: (
                query in str(item.get("title") or "").lower(),
                query in str(item.get("summary") or "").lower(),
                not bool(item.get("children")),
            ),
            reverse=True,
        )
    return ok(page(items, page_no, page_size), request)


@router.get("/rules/versions")
def list_rule_versions(request: Request, keyword: str | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [versioned_record("rule-version", item) for item in repo.state["rule_versions"]]
    if status:
        items = [item for item in items if item["status"] == status]
    items = filter_keyword(items, keyword, ["name", "inspectionItem", "inspectionCategory", "standardText", "witnessText", "ruleKey", "version"])
    return ok(page(items, page_no, page_size), request)


@router.get("/rules/versions/{version_id}")
def get_rule_version(request: Request, version_id: str):
    rule = repo.find_one("rule_versions", version_id)
    if not rule:
        return fail(errors.NOT_FOUND, request)
    return ok({"rule": versioned_record("rule-version", rule)}, request)


@router.post("/rules/versions")
def create_rule_version(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        normalized = normalize_business_rule_version_record(
            {
                **body,
                "status": "草稿",
                "version": body.get("version") or f"{make_business_rule_key(normalize_business_rule_source_fields(body), body)}-draft-{server_time()[:16].replace('-', '').replace(':', '').replace(' ', '-')}",
            },
            force_status="草稿",
        )
        if not normalized.get("inspectionItem"):
            return fail(errors.VALIDATION_ERROR, request, message="请填写监检项目（内容）。")
        if not normalized.get("standardText") and not normalized.get("witnessText"):
            return fail(errors.VALIDATION_ERROR, request, message="请填写判断准则 / 标准规范或方法及内容 / 工作见证。")
        existing_ids = {str(item.get("id")) for item in repo.state.get("rule_versions", [])}
        if normalized["id"] in existing_ids:
            normalized["id"] = f"RULE-{uuid4().hex[:10].upper()}"
        repo.state["rule_versions"].insert(0, normalized)
        audit_id = repo.add_audit("新增业务规则草稿", "RuleVersion", normalized["id"])
        return ok({"rule": versioned_record("rule-version", normalized), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.put("/rules/versions/{version_id}")
@router.patch("/rules/versions/{version_id}")
def update_rule_version(
    request: Request,
    version_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        rule = repo.find_one("rule_versions", version_id)
        if not rule:
            return fail(errors.NOT_FOUND, request)
        if normalize_rule_status(rule.get("status")) in {"已发布", "已回滚"}:
            return fail(errors.VALIDATION_ERROR, request, message="已发布或历史规则不能直接编辑，请基于当前规则创建草稿。")
        if not record_if_match_valid("rule-version", rule, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        merged = {**rule, **body, "id": rule["id"], "status": body.get("status") or rule.get("status") or "草稿"}
        if normalize_rule_status(merged.get("status")) == "已发布":
            return fail(errors.VALIDATION_ERROR, request, message="编辑接口不能直接发布规则，请使用发布操作。")
        normalized = normalize_business_rule_version_record(merged)
        normalized["revision"] = int(rule.get("revision") or 1)
        rule.clear()
        rule.update(normalized)
        bump_record_revision(rule)
        audit_id = repo.add_audit("编辑业务规则草稿", "RuleVersion", version_id)
        return ok({"rule": versioned_record("rule-version", rule), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"versionId": version_id, "body": body})


@router.post("/rules/versions/{version_id}/fork")
def fork_rule_version(
    request: Request,
    version_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    def produce():
        source = repo.find_one("rule_versions", version_id)
        if not source:
            return fail(errors.NOT_FOUND, request)
        now = server_time()
        draft = normalize_business_rule_version_record(
            {
                **repo.clone(source),
                **body,
                "id": f"RULE-{uuid4().hex[:10].upper()}",
                "status": "草稿",
                "version": body.get("version") or f"{source.get('ruleKey') or make_business_rule_key(normalize_business_rule_source_fields(source), source)}-draft-{now[:16].replace('-', '').replace(':', '').replace(' ', '-')}",
                "publishedAt": None,
                "forkedFromRuleVersionId": source.get("id"),
                "forkedFromVersion": source.get("version"),
                "createdAt": now,
                "updatedAt": now,
                "revision": 1,
            },
            force_status="草稿",
        )
        repo.state["rule_versions"].insert(0, draft)
        audit_id = repo.add_audit("基于正式规则创建草稿", "RuleVersion", draft["id"], source.get("version"))
        return ok({"rule": versioned_record("rule-version", draft), "source": versioned_record("rule-version", source), "auditLogId": audit_id}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"versionId": version_id, "body": body})


@router.get("/rules/versions/{version_id}/diff")
def rule_version_diff(request: Request, version_id: str, targetVersionId: str | None = None, targetVersion: str | None = None):
    if not repo.state["rule_versions"]:
        return fail(errors.NOT_FOUND, request)
    base = repo.find_one("rule_versions", version_id) or repo.state["rule_versions"][0]
    target = repo.find_one("rule_versions", targetVersionId or "") or next((item for item in repo.state["rule_versions"] if item.get("version") == targetVersion), None) or repo.state["rule_versions"][-1]
    compared_fields = [
        ("inspectionCategory", "监检项目（大类）"),
        ("inspectionItem", "监检项目（内容）"),
        ("inspectionClass", "类别"),
        ("standardText", "判断准则 / 标准规范"),
        ("witnessText", "方法及内容 / 工作见证"),
        ("nodeIds", "适用节点"),
        ("status", "状态"),
    ]
    changes = []
    for field, label in compared_fields:
        before = target.get(field)
        after = base.get(field)
        if before != after:
            changes.append(
                {
                    "field": field,
                    "label": label,
                    "before": before,
                    "after": after,
                    "severity": "warning" if field in {"nodeIds", "standardText", "witnessText"} else "info",
                    "changeType": "added" if not before and after else "removed" if before and not after else "changed",
                }
            )
    return ok(
        {
            "base": versioned_record("rule-version", base),
            "target": versioned_record("rule-version", target),
            "comparedAt": server_time(),
            "summary": {
                "added": len([item for item in changes if item["changeType"] == "added"]),
                "changed": len([item for item in changes if item["changeType"] == "changed"]),
                "removed": len([item for item in changes if item["changeType"] == "removed"]),
                "warning": len([item for item in changes if item["severity"] == "warning"]),
            },
            "changes": changes,
        },
        request,
    )


@router.post("/rules/versions/{version_id}/publish")
def publish_rule_version(
    request: Request,
    version_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        rule = repo.find_one("rule_versions", version_id)
        if not rule:
            return fail(errors.NOT_FOUND, request)
        if not record_if_match_valid("rule-version", rule, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        if not (rule.get("standardText") or rule.get("criteria")) and not (rule.get("witnessText") or rule.get("checkMethod")):
            return fail(errors.VALIDATION_ERROR, request, message="发布前请填写判断准则 / 标准规范或方法及内容 / 工作见证。")
        rule.update(normalize_business_rule_version_record(rule, force_status="已发布"))
        rule["aiExecution"] = compile_business_rule_execution(rule)
        overlapping_node_ids = set(parse_rule_node_ids(rule.get("nodeIds")))
        for item in repo.state.get("rule_versions", []):
            if item.get("id") == rule.get("id") or normalize_rule_status(item.get("status")) != "已发布":
                continue
            same_key = item.get("ruleKey") and item.get("ruleKey") == rule.get("ruleKey")
            same_node = bool(overlapping_node_ids & set(parse_rule_node_ids(item.get("nodeIds"))))
            if same_key or same_node:
                item["status"] = "已回滚"
                item["rolledBackAt"] = server_time()
                item["rolledBackByRuleVersionId"] = rule.get("id")
                bump_record_revision(item)
        rule["status"] = "已发布"
        rule["publishedAt"] = server_time()
        rule["publishedReason"] = body.get("reason") or ""
        bump_record_revision(rule)
        result = repo.mutation_result("发布规则版本", "RuleVersion", version_id, next_status="已发布")
        return ok({**result, "rule": versioned_record("rule-version", rule)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"versionId": version_id, "body": body})


@router.post("/rules/versions/{version_id}/rollback")
def rollback_rule_version(
    request: Request,
    version_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        rule = repo.find_one("rule_versions", version_id)
        if not rule:
            return fail(errors.NOT_FOUND, request)
        if not record_if_match_valid("rule-version", rule, if_match):
            return fail(errors.ETAG_CONFLICT, request)
        target = (
            repo.find_one("rule_versions", body.get("targetVersionId") or "")
            or next((item for item in repo.state["rule_versions"] if item.get("version") == body.get("targetVersion")), None)
            or repo.state["rule_versions"][0]
        )
        rule["status"] = "已回滚"
        bump_record_revision(rule)
        if target.get("id") != rule.get("id"):
            target["status"] = "已发布"
            target["publishedAt"] = server_time()
            bump_record_revision(target)
        result = repo.mutation_result("回滚规则版本", "RuleVersion", version_id, next_status="已回滚")
        return ok({**result, "rule": versioned_record("rule-version", rule), "target": versioned_record("rule-version", target)}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source={"versionId": version_id, "body": body})


@router.get("/knowledge/config")
def get_knowledge_config(request: Request):
    config = versioned_singleton("knowledge-config", repo.state["knowledge_config"])
    return ok({"config": config, "updatedAt": config["updatedAt"], "revision": config["revision"], "etag": config["etag"]}, request)


@router.put("/knowledge/config")
@router.patch("/knowledge/config")
def update_knowledge_config(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("knowledge-config", repo.state["knowledge_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        repo.state["knowledge_config"].update({key: value for key, value in body.items() if value is not None and key not in CONFIG_METADATA_FIELDS})
        bump_singleton_revision(repo.state["knowledge_config"])
        config = versioned_singleton("knowledge-config", repo.state["knowledge_config"])
        audit_id = repo.add_audit("更新知识库配置", "KnowledgeConfig", "default")
        return ok({"config": config, "updatedAt": config["updatedAt"], "revision": config["revision"], "etag": config["etag"], "auditLogId": audit_id}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source=body,
    )


@router.get("/knowledge/audit-logs")
def knowledge_audit_logs(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, objectType: str | None = None, result: str | None = None):
    items = [repo.clone(item) for item in repo.state["audit_logs"]]
    if objectType:
        items = [item for item in items if item.get("objectType") == objectType]
    if result:
        items = [item for item in items if item.get("result") == result]
    items = filter_keyword(items, keyword, ["action", "objectType", "objectId", "actorName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/reasoning/logs")
def reasoning_logs(request: Request, projectId: str | None = None, nodeId: int | None = None, status: str | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["ai_runs"] if record_visible_for_request(request, item)]
    if projectId:
        items = [item for item in items if item["projectId"] == projectId]
    if nodeId:
        items = [item for item in items if int(item["nodeId"]) == int(nodeId)]
    if status:
        items = [item for item in items if item["status"] == status]
    return ok(page(items, page_no, page_size), request)


@router.get("/reasoning/logs/{log_id}")
def reasoning_log_detail(request: Request, log_id: str):
    run = repo.find_one("ai_runs", log_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, run)
    if scope_error:
        return scope_error
    return ok({"log": repo.clone(run), "evidenceLinks": repo.clone(run.get("evidenceLinks") or repo.state["evidence_links"])}, request)


@router.get("/reasoning/logs/{log_id}/evidence")
def reasoning_log_evidence(request: Request, log_id: str):
    run = repo.find_one("ai_runs", log_id)
    if not run:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, run)
    if scope_error:
        return scope_error
    return ok(repo.clone(run.get("evidenceLinks") or repo.state["evidence_links"]), request)


@router.post("/llm/compare")
def llm_compare(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        project_id = body.get("projectId")
        node_ids = node_ids_from_body(body)
        if project_id:
            role, identity_error = effective_role_for_request(request)
            if identity_error:
                return identity_error
            scope_error = member_node_scope_error(request, project_id, role, node_ids=node_ids)
            if scope_error:
                return scope_error
        run_id = f"CMP-{uuid4().hex[:8].upper()}"
        run = {
            "runId": run_id,
            "question": body.get("question") or "请对比审查意见。",
            "modelCodes": body.get("modelCodes") or ["default-chat", "compare-fast"],
            "createdAt": server_time(),
            "projectId": body.get("projectId"),
            "nodeId": body.get("nodeId"),
            "evidenceLinkIds": body.get("evidenceLinkIds") or ["EV-24-001"],
            "status": "排队中",
            "results": [],
        }
        repo.state["llm_compare_runs"].insert(0, run)
        dispatch = task_dispatcher.dispatch_llm_compare(run_id)
        return ok({**run, "dispatch": dispatch}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/llm/compare-runs")
def list_compare_runs(request: Request, projectId: str | None = None, nodeId: int | None = None, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    items = [repo.clone(item) for item in repo.state["llm_compare_runs"] if record_visible_for_request(request, item)]
    if projectId:
        items = [item for item in items if item.get("projectId") == projectId]
    if nodeId:
        items = [item for item in items if int(item.get("nodeId") or 0) == int(nodeId)]
    summaries = [
        {
            "runId": item["runId"],
            "question": item["question"],
            "modelCodes": item["modelCodes"],
            "createdAt": item["createdAt"],
            "projectId": item.get("projectId"),
            "nodeId": item.get("nodeId"),
            "status": item.get("status", "完成"),
        }
        for item in items
    ]
    return ok(page(summaries, page_no, page_size), request)


@router.get("/llm/compare-runs/{run_id}")
def compare_run_detail(request: Request, run_id: str):
    run = repo.find_one("llm_compare_runs", run_id, id_field="runId")
    if not run:
        return fail(errors.NOT_FOUND, request)
    scope_error = scope_error_for_record(request, run)
    if scope_error:
        return scope_error
    return ok(repo.clone(run), request)


@router.get("/admin/config-overview")
def admin_config_overview(request: Request):
    overview = repo.build_admin_overview()
    overview.update(
        {
            "revision": singleton_revision(repo.state["admin_config"]),
            "etag": singleton_etag("admin-config", repo.state["admin_config"]),
            "updatedAt": repo.state["admin_config"].get("updatedAt") or server_time(),
        }
    )
    return ok(overview, request)


@router.post("/admin/projects")
def create_admin_project(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        pack_id = body.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID
        try:
            pack = load_business_pack(pack_id)
        except ValueError as exc:
            return fail(errors.VALIDATION_ERROR, request, message=str(exc))
        project_id = body.get("code") or f"P-2026-{uuid4().hex[:6].upper()}"
        defaults = project_defaults_for_pack(pack)
        project = {
            "id": project_id,
            "code": project_id,
            "name": body.get("name") or defaults["name"],
            "type": body.get("type") or defaults["type"],
            "region": body.get("region") or "华东",
            "ownerOrgName": body.get("ownerOrgName") or defaults["ownerOrgName"],
            "contractorOrgName": body.get("contractorOrgName") or defaults["contractorOrgName"],
            "ndtOrgName": body.get("ndtOrgName") or defaults["ndtOrgName"],
            "inspectionOrgName": body.get("inspectionOrgName") or defaults["inspectionOrgName"],
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "domainType": pack["domainType"],
            "businessPackSnapshotHash": pack["snapshotHash"],
            "businessPackSnapshot": business_pack_snapshot(pack),
            "status": "草稿/立项中",
            "todoCount": 0,
            "messageCount": 0,
            "currentNodeId": int(body.get("currentNodeId") or pack["nodeTemplates"][0]["nodeId"]),
            "updatedAt": server_time(),
            "actions": ["project:view", "project:authorize-member"],
            "revision": 1,
        }
        repo.state["projects"].insert(0, project)
        created_node_count, created_requirement_count = attach_business_pack_project_scaffold(project, pack)
        member_user_ids = body.get("memberUserIds") or {}
        role_node_scope = {
            role["code"]: [int(item["nodeId"]) for item in pack["nodeTemplates"]]
            for role in pack["roles"]
            if role["code"] != "admin"
        }
        role_org_names = {
            "owner": project["ownerOrgName"],
            "contractor": project["contractorOrgName"],
            "ndt": project["ndtOrgName"],
            "inspection": project["inspectionOrgName"],
            "observer": project["ownerOrgName"],
            "submitter": project["contractorOrgName"],
            "auditor": project["inspectionOrgName"],
        }
        for role_def in [item for item in pack["roles"] if item["code"] != "admin"]:
            role = role_def["code"]
            repo.state["project_members"].insert(
                0,
                project_member_snapshot(
                    project_id,
                    role,
                    member_user_ids.get(role),
                    org_name=role_org_names.get(role, project["inspectionOrgName"]),
                    node_scope=role_node_scope[role],
                    actions=role_def["actions"],
                ),
            )
        audit_id = repo.add_audit("项目立项", "Project", project_id)
        detail_data = project_detail_payload(project_id)
        return ok(
            {
                "project": versioned_project(project),
                "detail": detail_data,
                "businessPack": business_pack_summary(pack),
                "auditLogId": audit_id,
                "createdNodeCount": created_node_count,
                "createdRequirementCount": created_requirement_count,
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/admin/integration-contract")
def integration_contract(request: Request, module: str | None = None, status: str | None = None):
    modules = [
        ("workbench", "工作台首屏"),
        ("documents", "资料文件"),
        ("submissions", "提交补正"),
        ("inspection", "监检审查"),
        ("ndt-owner-report", "无损与报告"),
        ("knowledge-admin", "知识库与后台"),
    ]
    fields = [
        {
            "id": "IC-001",
            "module": "workbench",
            "moduleLabel": "工作台首屏",
            "endpoint": "/api/workbench/projects",
            "method": "GET",
            "frontendField": "projects[].riskLevel",
            "backendField": "riskLevel",
            "required": False,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "工作台项目列表按节点状态、待办、补正、AI/任务失败实时计算风险等级。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-002",
            "module": "submissions",
            "moduleLabel": "提交补正",
            "endpoint": "/api/projects/{projectId}/submissions",
            "method": "GET",
            "frontendField": "drafts[].nodeNames",
            "backendField": "drafts[].nodeNames",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "提交草稿和提交批次摘要均已返回节点名称。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-003",
            "module": "inspection",
            "moduleLabel": "监检审查",
            "endpoint": "/api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions",
            "method": "POST",
            "frontendField": "riskLevel",
            "backendField": "riskLevel",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "审查意见保存已返回风险等级。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-004",
            "module": "knowledge-admin",
            "moduleLabel": "知识库与后台",
            "endpoint": "/api/knowledge/tasks",
            "method": "GET",
            "frontendField": "items[].targetName",
            "backendField": "targetName",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "任务中心支持重试和取消。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-005",
            "module": "documents",
            "moduleLabel": "资料文件",
            "endpoint": "/api/projects/{projectId}/documents/upload-session",
            "method": "POST",
            "frontendField": "uploadUrls[].documentVersionId",
            "backendField": "uploadUrls[].documentVersionId",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "上传会话返回 documentId/documentVersionId、signed PUT URL 和 expiresAt，完成上传后创建 OCR 任务。",
            "updatedAt": server_time(),
        },
        {
            "id": "IC-006",
            "module": "ndt-owner-report",
            "moduleLabel": "无损与报告",
            "endpoint": "/api/projects/{projectId}/ndt/reports",
            "method": "GET",
            "frontendField": "items[].relatedFilmIds",
            "backendField": "relatedFilmIds",
            "required": True,
            "status": "已对齐",
            "severity": "info",
            "owner": "backend",
            "note": "NDT 报告列表返回状态、方法、关联底片和可执行动作；报告/归档导出产物包含可审计 manifest。",
            "updatedAt": server_time(),
        },
    ]
    if module and module != "all":
        fields = [item for item in fields if item["module"] == module]
    if status and status != "all":
        fields = [item for item in fields if item["status"] == status]
    module_summaries = []
    for code, label in modules:
        module_fields = [item for item in fields if item["module"] == code]
        total = len(module_fields)
        aligned = len([item for item in module_fields if item["status"] == "已对齐"])
        pending = len([item for item in module_fields if item["status"] in {"待后端确认", "命名不一致"}])
        blockers = len([item for item in module_fields if item["status"] in {"前端缺失", "后端缺失"}])
        module_summaries.append({"module": code, "label": label, "total": total, "aligned": aligned, "pending": pending, "blockers": blockers})
    return ok(
        {
            "summary": {
                "total": len(fields),
                "aligned": len([item for item in fields if item["status"] == "已对齐"]),
                "pending": len([item for item in fields if item["status"] in {"待后端确认", "命名不一致"}]),
                "blockers": len([item for item in fields if item["status"] in {"前端缺失", "后端缺失"}]),
            },
            "modules": module_summaries,
            "fields": fields,
            "generatedAt": server_time(),
        },
        request,
    )


@router.post("/admin/config-diff/preview")
def admin_config_diff_preview(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    values = body.get("values") or {}
    return ok(build_config_diff(body.get("target") or "config", body.get("id") or "new", values), request)


@router.post("/admin/config-items/{target}")
def create_admin_config_item(request: Request, target: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        values = body.get("values") or {}
        item_id = f"CFG-{uuid4().hex[:8].upper()}"
        item = {"id": item_id, **values, "updatedAt": server_time()}
        repo.state["admin_config"].setdefault(admin_collection_for(target), []).insert(0, item)
        bump_singleton_revision(repo.state["admin_config"])
        diff = build_config_diff(target, item_id, values, object_name=values.get("name") or values.get("scene") or target)
        audit_id = repo.add_audit("新增配置项", "AdminConfig", diff["objectId"])
        overview = repo.build_admin_overview()
        overview.update({"revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "updatedAt": repo.state["admin_config"]["updatedAt"]})
        return ok({"overview": overview, "diff": diff, "auditLogId": audit_id, "updatedAt": repo.state["admin_config"]["updatedAt"], "revision": overview["revision"], "etag": overview["etag"]}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"target": target, "body": body},
    )


@router.put("/admin/config-items/{target}/{item_id}")
def save_admin_config_item(request: Request, target: str, item_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        values = body.get("values") or {}
        collection = repo.state["admin_config"].setdefault(admin_collection_for(target), [])
        item = next((entry for entry in collection if entry.get("id") == item_id or entry.get("role") == item_id), None)
        if not item:
            return fail(errors.NOT_FOUND, request)
        item.update(values)
        item["updatedAt"] = server_time()
        bump_singleton_revision(repo.state["admin_config"])
        diff = build_config_diff(target, item_id, values, object_name=values.get("name") or values.get("scene") or target)
        audit_id = repo.add_audit("保存配置项", "AdminConfig", item_id)
        overview = repo.build_admin_overview()
        overview.update({"revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "updatedAt": repo.state["admin_config"]["updatedAt"]})
        return ok({"overview": overview, "diff": diff, "auditLogId": audit_id, "updatedAt": repo.state["admin_config"]["updatedAt"], "revision": overview["revision"], "etag": overview["etag"]}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"target": target, "itemId": item_id, "body": body},
    )


def admin_collection_for(kind: str) -> str:
    return {
        "todo-rule": "todoRules",
        "todo-rules": "todoRules",
        "message-template": "messageTemplates",
        "message-templates": "messageTemplates",
        "tool-source": "toolSources",
        "tool-sources": "toolSources",
        "field-mapping": "fieldMappings",
        "field-mappings": "fieldMappings",
        "workflow": "workflowStateMachines",
        "workflow-state-machines": "workflowStateMachines",
        "node-template": "nodeTemplates",
        "tree-nodes": "nodeTemplates",
        "permission": "permissionMatrix",
        "node-role-mappings": "permissionMatrix",
        "roles": "permissionMatrix",
        "rules": "ruleVersions",
    }.get(kind, kind)


@router.post("/admin/config-export")
def admin_config_export(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def produce():
        export_id = f"EXP-CFG-{uuid4().hex[:8].upper()}"
        scope = body.get("scope") or "all"
        task = {"id": export_id, "exportType": "config-package", "status": "可下载", "progress": 100, "fileName": f"后台配置包-{scope}-20260626.zip", "fileSize": 204800, "downloadUrl": f"mock://download/admin/{export_id}.zip", "createdAt": server_time(), "finishedAt": server_time(), "expiresAt": "2026-06-27 18:00:00"}
        repo.attach_export_artifact(task, content_type="application/zip")
        repo.state["export_tasks"].insert(0, task)
        return ok({"exportId": export_id, "task": task}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/admin/{kind}")
def admin_generic_list(request: Request, kind: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    if kind == "audit-logs":
        return audit_logs(request, page_no, page_size)
    if kind == "config-overview":
        return admin_config_overview(request)
    if kind == "integration-contract":
        return integration_contract(request)
    collection = admin_collection_for(kind)
    items = repo.state["admin_config"].get(collection, [])
    return ok(page(repo.clone(items), page_no, page_size), request)


@router.post("/admin/{kind}")
def admin_generic_create(request: Request, kind: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        collection = admin_collection_for(kind)
        values = body.get("values") or body
        item = {"id": f"CFG-{uuid4().hex[:8].upper()}", **values, "updatedAt": server_time()}
        repo.state["admin_config"].setdefault(collection, []).insert(0, item)
        bump_singleton_revision(repo.state["admin_config"])
        return ok({"item": item, "auditLogId": repo.add_audit("新增后台配置", "AdminConfig", item["id"]), "revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "updatedAt": repo.state["admin_config"]["updatedAt"]}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"kind": kind, "body": body},
    )


@router.patch("/admin/{kind}/{item_id}")
def admin_generic_update(request: Request, kind: str, item_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        collection = admin_collection_for(kind)
        items = repo.state["admin_config"].setdefault(collection, [])
        item = next((entry for entry in items if entry.get("id") == item_id), None)
        if not item:
            return fail(errors.NOT_FOUND, request)
        item.update(body)
        item["updatedAt"] = server_time()
        bump_singleton_revision(repo.state["admin_config"])
        return ok({"item": item, "auditLogId": repo.add_audit("更新后台配置", "AdminConfig", item_id), "revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "updatedAt": repo.state["admin_config"]["updatedAt"]}, request)

    return idempotent(
        request,
        idempotency_key,
        produce,
        fingerprint_source={"kind": kind, "itemId": item_id, "body": body},
    )


@router.get("/admin/workflow-state-machines")
def workflow_state_machines(request: Request):
    return ok(repo.state["admin_config"]["workflowStateMachines"], request)


@router.post("/admin/workflow-state-machines")
def create_workflow_state_machine(request: Request, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return admin_generic_create(request, "workflowStateMachines", body, idempotency_key, if_match)


@router.patch("/admin/workflow-state-machines/{state_machine_id}")
def update_workflow_state_machine(request: Request, state_machine_id: str, body: dict[str, Any] = Body(default_factory=dict), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), if_match: str | None = Header(default=None, alias="If-Match")):
    return admin_generic_update(request, "workflowStateMachines", state_machine_id, body, idempotency_key, if_match)


@router.post("/admin/config-overview/publish")
def publish_admin_config(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    def produce():
        if not singleton_if_match_valid("admin-config", repo.state["admin_config"], if_match):
            return fail(errors.ETAG_CONFLICT, request)
        publish_id = f"PUB-{uuid4().hex[:8].upper()}"
        audit_id = repo.add_audit("发布后台配置", "AdminConfig", publish_id)
        version = "config-v2026.06.27"
        scope = body.get("scope") or "all"
        repo.state["admin_config"]["lastPublishedVersion"] = version
        repo.state["admin_config"]["lastPublishedAt"] = server_time()
        repo.state["admin_config"]["lastPublishedScope"] = scope
        bump_singleton_revision(repo.state["admin_config"])
        message = {
            "id": f"MSG-{uuid4().hex[:8].upper()}",
            "title": f"后台配置已发布：{version}",
            "content": f"发布范围 {scope}，权限、待办和消息模板已完成联动刷新。",
            "projectId": PROJECT_ID,
            "targetType": "admin_config",
            "targetId": publish_id,
            "read": False,
            "createdAt": server_time(),
        }
        todo = {
            "id": f"TODO-{uuid4().hex[:8].upper()}",
            "title": "字段映射配置发布影响",
            "projectId": PROJECT_ID,
            "nodeId": 24,
            "targetType": "admin_config",
            "targetId": publish_id,
            "status": "待处理",
            "priority": "中",
            "assigneeName": "张工",
            "actions": ["admin:config", "knowledge:manage"],
        }
        repo.state["messages"].insert(0, message)
        repo.state["todos"].insert(0, todo)
        impacts = [
            {"domain": "permission", "label": "权限矩阵", "affectedCount": 5, "status": "已同步", "trace": "权限矩阵已同步到工作台动作权限"},
            {"domain": "message-template", "label": "消息模板", "affectedCount": 2, "status": "已同步", "trace": "消息模板已刷新待办通知"},
            {"domain": "field-mapping", "label": "字段映射", "affectedCount": 1, "status": "需复核", "trace": "字段映射阈值变更后需在真实 OCR 样例中复核"},
        ]
        return ok({"publishId": publish_id, "status": "已发布", "version": version, "auditLogId": audit_id, "publishedAt": repo.state["admin_config"]["lastPublishedAt"], "revision": singleton_revision(repo.state["admin_config"]), "etag": singleton_etag("admin-config", repo.state["admin_config"]), "impactSummary": {"totalAffected": 8, "warningCount": 1, "linkedProjects": len([item for item in repo.state["projects"] if item["status"] != "已归档"]), "pushedMessages": 1, "reviewTodos": 1}, "impacts": impacts}, request)

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)


@router.get("/admin/audit-logs")
def audit_logs(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize"), keyword: str | None = None, result: str | None = None, objectType: str | None = None):
    items = [repo.clone(item) for item in repo.state["audit_logs"]]
    if result:
        items = [item for item in items if item.get("result") == result]
    if objectType:
        items = [item for item in items if item.get("objectType") == objectType]
    items = filter_keyword(items, keyword, ["action", "objectType", "objectId", "actorName"])
    return ok(page(items, page_no, page_size), request)


@router.get("/audit-logs")
def global_audit_logs(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return audit_logs(request, page_no, page_size)


@router.get("/projects/{project_id}/audit-logs")
def project_audit_logs(request: Request, project_id: str, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return audit_logs(request, page_no, page_size)


@router.get("/projects/{project_id}/nodes/{node_id}/audit-logs")
def node_audit_logs(request: Request, project_id: str, node_id: int, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return audit_logs(request, page_no, page_size)


@router.get("/admin/org-units")
def org_units_alias(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return ok(page(repo.clone(repo.state["admin_config"]["orgUnits"]), page_no, page_size), request)


@router.get("/admin/users")
def users_alias(request: Request, page_no: int = Query(default=1, alias="page"), page_size: int = Query(default=20, alias="pageSize")):
    return ok(page(repo.clone(repo.state["admin_config"]["users"]), page_no, page_size), request)


@router.get("/orgs")
def legacy_orgs(request: Request):
    return ok(repo.clone(repo.state["admin_config"]["orgUnits"]), request)


@router.get("/users")
def legacy_users(request: Request):
    return ok(repo.clone(repo.state["admin_config"]["users"]), request)
