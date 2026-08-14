from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from libs.contracts.responses import server_time
from libs.db.repository import repo, sync_state_records
from libs.deepseek_runtime import deepseek_runtime_config, deepseek_runtime_public_config
from libs.integrations import task_dispatcher
from libs.integrations.errors import IntegrationServiceError, safe_reason
from libs.integrations.litellm_client import LiteLLMClient
from libs.ocr.profiles import profile_for

PIPELINE_COMPARISON_SCHEMA_VERSION = "DocumentAuditPipelineComparisonRun@1"


def stable_hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compact_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize_value(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    return re.sub(r"[\s_./\\∕／·•:：,，;；()（）\[\]【】]+", "", text)


def comparison_run_id(document_ai_run: dict[str, Any], config: dict[str, Any]) -> str:
    seed = "|".join(
        [
            str(document_ai_run.get("runId") or document_ai_run.get("id") or ""),
            str(document_ai_run.get("priorHash") or ""),
            str(config.get("primaryModel") or ""),
            str(config.get("model") or ""),
            PIPELINE_COMPARISON_SCHEMA_VERSION,
        ]
    )
    return f"DAPCOMP-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:18].upper()}"


def deterministic_sample_selected(value: str, rate: float) -> bool:
    if rate >= 1:
        return True
    if rate <= 0:
        return False
    bucket = int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return bucket < rate


def persist_pipeline_comparison_run(run: dict[str, Any]) -> None:
    sync_state_records({"document_audit_pipeline_comparison_runs": [run]}, {})


def schedule_pipeline_comparison(
    document_ai_run: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    config = deepseek_runtime_config()
    if not config["enabled"]:
        return {"status": "not_dispatched", "statusReason": "pipeline_comparison_disabled"} if force else None
    document_ai_run_id = str(document_ai_run.get("runId") or document_ai_run.get("id") or "")
    if not document_ai_run_id or str(document_ai_run.get("status") or "") != "success":
        return {"status": "not_dispatched", "statusReason": "document_ai_shadow_not_ready"}
    if not force and not deterministic_sample_selected(document_ai_run_id, config["sampleRate"]):
        return {"status": "not_sampled", "statusReason": "pipeline_comparison_sample_excluded"}
    run_id = comparison_run_id(document_ai_run, config)
    existing = repo.find_one("document_audit_pipeline_comparison_runs", run_id)
    if existing and str(existing.get("status") or "") in {"queued", "running", "success"}:
        return {
            "runId": run_id,
            "status": existing.get("status"),
            "taskId": existing.get("taskId"),
            "alreadyScheduled": True,
        }
    now = server_time()
    run = existing or {
        "id": run_id,
        "runId": run_id,
        "schemaVersion": PIPELINE_COMPARISON_SCHEMA_VERSION,
        "documentAiShadowRunId": document_ai_run_id,
        "documentId": document_ai_run.get("documentId"),
        "documentVersionId": document_ai_run.get("documentVersionId"),
        "profileId": document_ai_run.get("profileId"),
        "fileName": document_ai_run.get("fileName"),
        "selectedPageNos": document_ai_run.get("selectedPageNos") or [1],
        "storageKey": document_ai_run.get("storageKey"),
        "storageBucket": document_ai_run.get("storageBucket"),
        "sourceBaselineHash": document_ai_run.get("baselineHash"),
        "sourcePriorHash": document_ai_run.get("priorHash"),
        "advisoryOnly": True,
        "formalEvidenceReady": False,
        "businessImpact": "none",
        "baselinePipelineId": config["primaryPipelineId"],
        "baselineProvider": config["primaryProvider"],
        "baselineModel": config["primaryModel"],
        "challengerPipelineId": config["challengerPipelineId"],
        "challengerProvider": config["challengerProvider"],
        "challengerModel": config["model"],
        "runtime": deepseek_runtime_public_config(),
        "createdAt": now,
    }
    run.update({"status": "queued", "failureReason": None, "queuedAt": now, "updatedAt": now})
    if run not in repo.state.setdefault("document_audit_pipeline_comparison_runs", []):
        repo.state["document_audit_pipeline_comparison_runs"].insert(0, run)
    persist_pipeline_comparison_run(run)
    try:
        dispatch = task_dispatcher.dispatch_document_audit_pipeline_comparison(run_id)
    except Exception as exc:  # pragma: no cover - broker boundary
        dispatch = {
            "mode": task_dispatcher.dispatch_mode(),
            "taskId": None,
            "statusReason": f"dispatch_{exc.__class__.__name__.lower()}",
        }
    run["dispatch"] = dispatch
    run["taskId"] = dispatch.get("taskId")
    if not run.get("taskId"):
        run["status"] = "dispatch_failed"
        run["failureReason"] = str(dispatch.get("statusReason") or "pipeline_comparison_dispatch_failed")
    run["updatedAt"] = server_time()
    persist_pipeline_comparison_run(run)
    return {
        "runId": run_id,
        "status": run.get("status"),
        "taskId": run.get("taskId"),
        "statusReason": (run.get("dispatch") or {}).get("statusReason"),
    }


def build_shared_industry_context(document_ai_run: dict[str, Any]) -> dict[str, Any]:
    profile = profile_for(str(document_ai_run.get("profileId") or ""))
    structured = profile.get("structuredExtraction") if isinstance(profile.get("structuredExtraction"), dict) else {}
    document_id = str(document_ai_run.get("documentId") or "")
    document = repo.find_one("documents", document_id) or {}
    project_id = str(document.get("projectId") or "")
    node_ids = {
        int(item.get("nodeId"))
        for item in repo.state.get("bindings", [])
        if str(item.get("documentId") or "") == document_id and str(item.get("nodeId") or "").isdigit()
    }
    rules = []
    for rule in repo.state.get("rule_versions", []):
        if not node_ids:
            break
        rule_node_ids = {int(value) for value in rule.get("nodeIds") or [] if str(value).isdigit()}
        if node_ids and not (node_ids & rule_node_ids):
            continue
        if rule.get("status") not in {"已发布", "published", "active", "production"}:
            continue
        rules.append(
            {
                "ruleCode": rule.get("ruleCode") or rule.get("id"),
                "version": rule.get("version") or rule.get("ruleSetVersion"),
                "title": rule.get("name") or rule.get("title"),
                "standardText": compact_text(rule.get("standardText"), 800),
                "sources": [
                    {
                        "file": source.get("file") or source.get("path"),
                        "standardNo": source.get("standardNo"),
                    }
                    for source in rule.get("sources") or []
                    if isinstance(source, dict)
                ][:12],
            }
        )
        if len(rules) >= 8:
            break
    retrieval = []
    for trace in repo.state.get("retrieval_traces", []):
        if not project_id:
            break
        if project_id and str(trace.get("projectId") or "") != project_id:
            continue
        if node_ids and str(trace.get("nodeId") or "").isdigit() and int(trace["nodeId"]) not in node_ids:
            continue
        retrieval.append(
            {
                "retrievalTraceId": trace.get("retrievalTraceId") or trace.get("id"),
                "selectedClauseIds": [str(value) for value in trace.get("selectedClauseIds") or [] if value][:12],
                "selectedSources": [compact_text(value, 240) for value in trace.get("selectedSources") or []][:8],
            }
        )
        if len(retrieval) >= 6:
            break
    return {
        "schemaVersion": "SharedDocumentAuditContext@1",
        "projectId": project_id or None,
        "nodeIds": sorted(node_ids),
        "profileId": profile.get("profileId"),
        "requiredFields": profile.get("requiredFields") or [],
        "requiredTables": profile.get("requiredTables") or [],
        "structuredFields": structured.get("fields") or [],
        "fieldDefinitions": structured.get("fieldDefinitions") or {},
        "rules": rules,
        "retrieval": retrieval,
    }


def audit_output_schema() -> dict[str, Any]:
    return {
        "documentFields": {"field_code": {"value": "string|null", "pageNo": "number|null", "sourceCandidateIds": []}},
        "tables": {
            "table_code": [
                {
                    "cells": {"field_code": "string|null"},
                    "pageNo": "number|null",
                    "sourceCandidateIds": [],
                }
            ]
        },
        "findings": [
            {
                "findingType": "string",
                "severity": "low|medium|high",
                "title": "string",
                "description": "string",
                "sourceCandidateIds": ["string"],
                "standardRefs": ["string"],
                "suggestedAction": "human_confirm|request_correction",
                "confidence": "0..1",
            }
        ],
    }


def build_audit_instruction(industry_context: dict[str, Any]) -> str:
    return (
        "你是工业压力管道资料预审助手。仅输出 JSON，不得形成正式通过结论。"
        "只可依据输入资料和提供的规则/标准引用；证据不足必须标记人工复核。"
        "禁止推断不可见日期、证书有效期、印章文字或检测等级。"
        "输出必须匹配此 schema："
        + json.dumps(audit_output_schema(), ensure_ascii=False)
        + "\n共同业务与行业规范上下文："
        + json.dumps(industry_context, ensure_ascii=False)
    )


def collect_source_candidate_ids(value: Any) -> set[str]:
    output: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "sourceCandidateIds" and isinstance(nested, list):
                output.update(str(candidate_id) for candidate_id in nested if candidate_id)
            else:
                output.update(collect_source_candidate_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            output.update(collect_source_candidate_ids(nested))
    return output


def table_evidence_qualification(raw_tables: Any) -> dict[str, Any]:
    if not isinstance(raw_tables, (dict, list)):
        return {"tableCount": 0, "groundedTableCount": 0, "ungroundedTableCount": 0, "inconsistentTableCount": 0, "tables": []}
    table_items = raw_tables.items() if isinstance(raw_tables, dict) else enumerate(raw_tables)
    summaries = []
    for raw_code, raw_value in table_items:
        entries = raw_value if isinstance(raw_value, list) else [raw_value]
        for entry_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            table_code = str(entry.get("tableCode") or entry.get("tableName") or raw_code)
            cells = entry.get("cells") if isinstance(entry.get("cells"), dict) else {}
            column_lengths = {
                str(code): len(value)
                for code, value in cells.items()
                if isinstance(value, list)
            }
            nonzero_lengths = {value for value in column_lengths.values() if value > 0}
            consistent = len(nonzero_lengths) <= 1
            source_ids = sorted(collect_source_candidate_ids(entry))
            summaries.append(
                {
                    "tableCode": table_code,
                    "entryIndex": entry_index,
                    "rowCount": max(column_lengths.values(), default=0),
                    "columnLengths": column_lengths,
                    "columnLengthsConsistent": consistent,
                    "grounded": bool(source_ids),
                    "sourceCandidateIds": source_ids,
                }
            )
    return {
        "tableCount": len(summaries),
        "groundedTableCount": sum(item["grounded"] for item in summaries),
        "ungroundedTableCount": sum(not item["grounded"] for item in summaries),
        "inconsistentTableCount": sum(not item["columnLengthsConsistent"] for item in summaries),
        "tables": summaries,
    }


def build_deepseek_messages(
    document_ai_run: dict[str, Any],
    industry_context: dict[str, Any],
) -> list[dict[str, str]]:
    extraction = document_ai_run.get("structuredOutput") or {}
    attribution = document_ai_run.get("attributionValidation") or {}
    fields = extraction.get("fields") if isinstance(extraction.get("fields"), dict) else {}
    candidate_ids = sorted(collect_source_candidate_ids(extraction))
    supported_field_codes = sorted(
        code
        for code, field in fields.items()
        if isinstance(field, dict) and any(field.get("sourceCandidateIds") or [])
    )
    unsupported_field_codes = sorted(set(fields) - set(supported_field_codes))
    payload = {
        "task": "Audit the validated PaddleOCR + NuExtract result and return JSON findings.",
        "documentFields": fields,
        "tables": extraction.get("tables") or {},
        "seals": extraction.get("seals") or [],
        "allowedSourceCandidateIds": candidate_ids,
        "groundedFieldCodes": supported_field_codes,
        "ungroundedFieldCodes": unsupported_field_codes,
        "tableEvidenceQualification": table_evidence_qualification(extraction.get("tables")),
        "attributionValidation": attribution,
        "requirements": [
            "Do not change extracted field values.",
            "Use sourceCandidateIds only from allowedSourceCandidateIds and copy every ID byte-for-byte.",
            "Never add a suffix, prefix, coordinate, row number, or explanatory text to a candidate ID.",
            "A field listed in ungroundedFieldCodes cannot support a compliance, non-compliance, expiry, ratio, grade, or standards conclusion.",
            "Ungrounded fields may only produce missing_grounding or evidence_gap findings with human_confirm.",
            "An ungrounded or column-length-inconsistent table cannot support a substantive audit conclusion.",
            "Every substantive finding must cite at least one allowed sourceCandidateId.",
            "Return valid JSON only.",
        ],
    }
    return [
        {"role": "system", "content": build_audit_instruction(industry_context)},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def build_qwen_vision_messages(
    page_paths: list[Path],
    industry_context: dict[str, Any],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": image_data_url(path)}} for path in page_paths
    ]
    content.append(
        {
            "type": "text",
            "text": (
            "直接阅读以上原始页面，抽取 documentFields 并生成审计 findings。"
                "documentFields 必须逐项覆盖 requiredFields；不可见字段保留 null，不得只写在 finding 描述中。"
                "tables 必须逐项覆盖 requiredTables，并将每行拆为 cells；不得只在描述中概括表格。"
                "视觉发现无 OCR candidate ID，sourceCandidateIds 必须为空；不要伪造 bbox。"
                "请仅输出有效 JSON。\n"
                + build_audit_instruction(industry_context)
            ),
        }
    )
    return [
        {"role": "system", "content": "你是只读的工业资料视觉预审助手，所有结论均需人工确认。"},
        {"role": "user", "content": content},
    ]


def parse_json_model_output(response: dict[str, Any]) -> dict[str, Any]:
    text = LiteLLMClient.first_message_text(response).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].lstrip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("pipeline audit output must be a JSON object")
    return unwrap_pipeline_payload(payload)


def unwrap_pipeline_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("documentFields"), dict) or isinstance(payload.get("findings"), list):
        return payload
    for key in ["result", "output", "outputSchema"]:
        nested = payload.get(key)
        if isinstance(nested, dict) and (
            isinstance(nested.get("documentFields"), dict) or isinstance(nested.get("findings"), list)
        ):
            return nested
    return payload


def allowed_standard_refs(industry_context: dict[str, Any]) -> set[str]:
    refs = set()
    for rule in industry_context.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        if rule.get("ruleCode"):
            refs.add(str(rule["ruleCode"]))
        for source in rule.get("sources") or []:
            if not isinstance(source, dict):
                continue
            refs.update(str(source[key]) for key in ["file", "standardNo"] if source.get(key))
    for trace in industry_context.get("retrieval") or []:
        if isinstance(trace, dict):
            refs.update(str(value) for value in trace.get("selectedClauseIds") or [] if value)
    return refs


def normalize_pipeline_result(
    payload: dict[str, Any],
    *,
    pipeline_id: str,
    industry_context: dict[str, Any],
    allowed_candidate_ids: set[str] | None,
    fixed_document_fields: dict[str, Any] | None = None,
    fixed_tables: Any | None = None,
    direct_vision_only: bool = False,
) -> dict[str, Any]:
    raw_fields = fixed_document_fields if fixed_document_fields is not None else payload.get("documentFields")
    fields = raw_fields if isinstance(raw_fields, dict) else {}
    raw_tables = fixed_tables if fixed_tables is not None else payload.get("tables")
    tables = raw_tables if isinstance(raw_tables, (dict, list)) else {}
    standards = allowed_standard_refs(industry_context)
    unknown_candidates: set[str] = set()
    unknown_standards: set[str] = set()
    ungrounded_substantive_count = 0
    direct_vision_finding_count = 0
    evidence_gap_finding_count = 0
    findings = []
    for index, raw in enumerate(payload.get("findings") or []):
        if not isinstance(raw, dict) or index >= 10:
            continue
        candidate_ids = []
        for candidate_id in raw.get("sourceCandidateIds") or []:
            value = str(candidate_id)
            if allowed_candidate_ids is not None and value not in allowed_candidate_ids:
                unknown_candidates.add(value)
                continue
            candidate_ids.append(value)
        standard_refs = []
        for standard_ref in raw.get("standardRefs") or []:
            value = str(standard_ref)
            if value not in standards:
                unknown_standards.add(value)
                continue
            standard_refs.append(value)
        finding_type = compact_text(raw.get("findingType") or "manual_review", 80)
        normalized_finding_type = re.sub(r"[^A-Z0-9]+", "_", finding_type.upper()).strip("_")
        evidence_gap_only = normalized_finding_type in {
            "DATA_QUALITY",
            "EVIDENCE_GAP",
            "EXTRACTION_ERROR",
            "MANUAL_REVIEW",
            "MISSING_FIELD",
            "MISSING_GROUNDING",
            "MISSING_INFO",
        }
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0

        grounding_issues = []
        if direct_vision_only:
            grounding_status = "direct_vision_only"
            direct_vision_finding_count += 1
            grounding_issues.append("DIRECT_VISION_WITHOUT_CANDIDATE_BBOX")
            confidence = min(confidence, 0.65)
        elif allowed_candidate_ids is not None and not candidate_ids and evidence_gap_only:
            grounding_status = "evidence_gap"
            evidence_gap_finding_count += 1
            grounding_issues.append("NO_VALID_SOURCE_CANDIDATE")
            confidence = min(confidence, 0.65)
        elif allowed_candidate_ids is not None and not candidate_ids:
            grounding_status = "unsupported_substantive_claim"
            ungrounded_substantive_count += 1
            grounding_issues.append("SUBSTANTIVE_FINDING_WITHOUT_VALID_SOURCE_CANDIDATE")
            confidence = min(confidence, 0.45)
        else:
            grounding_status = "validated_candidate" if candidate_ids else "not_evaluated"
        suggested_action = (
            str(raw.get("suggestedAction"))
            if str(raw.get("suggestedAction") or "") in {"human_confirm", "request_correction"}
            else "human_confirm"
        )
        if grounding_status != "validated_candidate":
            suggested_action = "human_confirm"
        findings.append(
            {
                "id": f"PAF-{hashlib.sha256(f'{pipeline_id}|{index}|{raw}'.encode()).hexdigest()[:12].upper()}",
                "findingType": finding_type,
                "severity": str(raw.get("severity")) if str(raw.get("severity") or "") in {"low", "medium", "high"} else "medium",
                "title": compact_text(raw.get("title"), 200),
                "description": compact_text(raw.get("description"), 1200),
                "sourceCandidateIds": candidate_ids,
                "standardRefs": standard_refs,
                "suggestedAction": suggested_action,
                "confidence": confidence,
                "groundingStatus": grounding_status,
                "groundingIssues": grounding_issues,
                "canSupportComplianceDecision": False,
                "advisoryOnly": True,
                "formalEvidenceReady": False,
            }
        )
    return {
        "pipelineId": pipeline_id,
        "documentFields": fields,
        "tables": tables,
        "tableEvidenceQualification": table_evidence_qualification(tables),
        "findings": findings,
        "validation": {
            "unknownSourceCandidateIds": sorted(unknown_candidates),
            "unknownStandardRefs": sorted(unknown_standards),
            "invalidReferenceCount": len(unknown_candidates) + len(unknown_standards),
            "ungroundedSubstantiveFindingCount": ungrounded_substantive_count,
            "directVisionOnlyFindingCount": direct_vision_finding_count,
            "evidenceGapFindingCount": evidence_gap_finding_count,
        },
        "advisoryOnly": True,
        "formalEvidenceReady": False,
    }


def _field_values(payload: dict[str, Any]) -> dict[str, str]:
    output = {}
    for key, field in (payload.get("documentFields") or {}).items():
        value = field.get("value") if isinstance(field, dict) else field
        normalized = normalize_value(value)
        if normalized:
            output[str(key)] = normalized
    return output


def _grounded_field_codes(payload: dict[str, Any]) -> set[str]:
    return {
        str(key)
        for key, field in (payload.get("documentFields") or {}).items()
        if isinstance(field, dict) and any(field.get("sourceCandidateIds") or [])
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def compare_pipeline_results(baseline: dict[str, Any], challenger: dict[str, Any]) -> dict[str, Any]:
    baseline_fields = _field_values(baseline)
    challenger_fields = _field_values(challenger)
    shared_fields = set(baseline_fields) & set(challenger_fields)
    exact_matches = {key for key in shared_fields if baseline_fields[key] == challenger_fields[key]}
    baseline_findings = baseline.get("findings") or []
    challenger_findings = challenger.get("findings") or []
    baseline_severity = Counter(str(item.get("severity") or "") for item in baseline_findings)
    challenger_severity = Counter(str(item.get("severity") or "") for item in challenger_findings)
    baseline_actions = Counter(str(item.get("suggestedAction") or "") for item in baseline_findings)
    challenger_actions = Counter(str(item.get("suggestedAction") or "") for item in challenger_findings)
    severity_denominator = max(sum(baseline_severity.values()), sum(challenger_severity.values()), 1)
    action_denominator = max(sum(baseline_actions.values()), sum(challenger_actions.values()), 1)
    baseline_standards = {str(value) for item in baseline_findings for value in item.get("standardRefs") or []}
    challenger_standards = {str(value) for item in challenger_findings for value in item.get("standardRefs") or []}
    baseline_grounded_fields = _grounded_field_codes(baseline)
    challenger_grounded_fields = _grounded_field_codes(challenger)
    baseline_table_quality = table_evidence_qualification(baseline.get("tables"))
    challenger_table_quality = table_evidence_qualification(challenger.get("tables"))
    return {
        "schemaVersion": "DocumentAuditPipelineComparisonMetrics@1",
        "accuracyClaimed": False,
        "agreementIsNotAccuracy": True,
        "baselineFieldCount": len(baseline_fields),
        "challengerFieldCount": len(challenger_fields),
        "sharedFieldCount": len(shared_fields),
        "fieldExactAgreement": round(len(exact_matches) / len(shared_fields), 4) if shared_fields else None,
        "fieldCoverageDelta": len(challenger_fields) - len(baseline_fields),
        "baselineGroundedFieldCount": len(baseline_grounded_fields),
        "challengerGroundedFieldCount": len(challenger_grounded_fields),
        "challengerUngroundedFieldCount": len(set(challenger_fields) - challenger_grounded_fields),
        "baselineTableCount": baseline_table_quality["tableCount"],
        "challengerTableCount": challenger_table_quality["tableCount"],
        "challengerGroundedTableCount": challenger_table_quality["groundedTableCount"],
        "challengerUngroundedTableCount": challenger_table_quality["ungroundedTableCount"],
        "challengerInconsistentTableCount": challenger_table_quality["inconsistentTableCount"],
        "baselineOnlyFields": sorted(set(baseline_fields) - set(challenger_fields)),
        "challengerOnlyFields": sorted(set(challenger_fields) - set(baseline_fields)),
        "differentValueFields": sorted(shared_fields - exact_matches),
        "baselineFindingCount": len(baseline_findings),
        "challengerFindingCount": len(challenger_findings),
        "severityAgreement": round(sum((baseline_severity & challenger_severity).values()) / severity_denominator, 4),
        "suggestedActionAgreement": round(sum((baseline_actions & challenger_actions).values()) / action_denominator, 4),
        "standardReferenceAgreement": round(_jaccard(baseline_standards, challenger_standards), 4),
        "baselineOnlyStandardRefs": sorted(baseline_standards - challenger_standards),
        "challengerOnlyStandardRefs": sorted(challenger_standards - baseline_standards),
        "baselineInvalidReferenceCount": int((baseline.get("validation") or {}).get("invalidReferenceCount") or 0),
        "challengerInvalidReferenceCount": int((challenger.get("validation") or {}).get("invalidReferenceCount") or 0),
        "baselineDirectVisionOnlyFindingCount": int(
            (baseline.get("validation") or {}).get("directVisionOnlyFindingCount") or 0
        ),
        "challengerUngroundedSubstantiveFindingCount": int(
            (challenger.get("validation") or {}).get("ungroundedSubstantiveFindingCount") or 0
        ),
        "goldEvaluationRequired": True,
    }


class QwenVisionAuditClient:
    def __init__(self, *, config: dict[str, Any] | None = None, transport: Any | None = None) -> None:
        self.config = config or deepseek_runtime_config()
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return bool(
            self.config.get("enabled")
            and self.config.get("primaryBaseUrl")
            and self.config.get("primaryApiKey")
        )

    def chat_sync(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Qwen VL audit comparison is not configured")
        client_kwargs: dict[str, Any] = {"timeout": self.config["primaryTimeoutSeconds"]}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(
                    f"{self.config['primaryBaseUrl']}/chat/completions",
                    headers={"Authorization": f"Bearer {self.config['primaryApiKey']}"},
                    json={
                        "model": self.config["primaryModel"],
                        "messages": messages,
                        "stream": False,
                        "response_format": {"type": "json_object"},
                        "enable_thinking": False,
                        "temperature": 0.1,
                        "max_tokens": self.config["primaryMaxTokens"],
                    },
                )
        except httpx.HTTPError as exc:
            raise IntegrationServiceError("Qwen VL official API", "chat.completions", reason=exc.__class__.__name__.upper()) from exc
        if response.status_code >= 400:
            reason = None
            try:
                error = response.json().get("error")
                reason = error.get("code") if isinstance(error, dict) else None
            except (AttributeError, ValueError):
                reason = None
            raise IntegrationServiceError(
                "Qwen VL official API",
                "chat.completions",
                status_code=response.status_code,
                reason=safe_reason(reason),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("Qwen VL official API", "chat.completions", reason="INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise IntegrationServiceError("Qwen VL official API", "chat.completions", reason="INVALID_RESPONSE")
        payload.setdefault("model", self.config["primaryModel"])
        payload.setdefault("provider", self.config["primaryProvider"])
        return payload
