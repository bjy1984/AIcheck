from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time


R12_NODE_ID = 12
R12_TASK_TYPE = "official_registry_license_verification"
R12_VERIFICATION_OUTCOMES = {
    "verified_match",
    "verified_mismatch",
    "not_found",
    "unable_to_verify",
}
R12_REGISTRY_STATUSES = {"active", "expired", "revoked", "suspended", "unknown"}

_LICENSE_PATTERN = re.compile(r"\bTS[0-9A-Z-]{7,24}\b", re.IGNORECASE)
_MANUFACTURING_MARKERS = (
    "压力管道元件制造",
    "钢管制造",
    "管件制造",
    "阀门制造",
    "安全附件制造",
    "元件组合装置制造",
)
_PERSONNEL_MARKERS = ("特种设备作业人员证", "焊工证", "焊接作业", "作业项目代号")


def stable_payload_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_r12_formal_review(review_run: dict[str, Any]) -> bool:
    return (
        int(review_run.get("nodeId") or 0) == R12_NODE_ID
        and str(review_run.get("reviewMode") or "formal") == "formal"
        and not bool(review_run.get("advisoryOnly"))
    )


def extract_r12_license_candidates(
    state: dict[str, Any],
    review_run: dict[str, Any],
    *,
    id_namespace: str = "R12",
) -> list[dict[str, Any]]:
    requested_versions = {str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item}
    candidates: list[dict[str, Any]] = []
    for parse_result in state.get("ocr_parse_results", []):
        if not isinstance(parse_result, dict):
            continue
        version_id = str(parse_result.get("documentVersionId") or "")
        if requested_versions and version_id not in requested_versions:
            continue
        page_items: dict[int, list[dict[str, Any]]] = {}
        for item in [*(parse_result.get("fragments") or []), *(parse_result.get("fields") or [])]:
            if not isinstance(item, dict):
                continue
            try:
                page_no = max(1, int(item.get("pageNo") or 1))
            except (TypeError, ValueError):
                page_no = 1
            page_items.setdefault(page_no, []).append(item)
        for page_no, items in sorted(page_items.items()):
            page_text = "\n".join(_item_text(item) for item in items if _item_text(item)).strip()
            if not _is_manufacturing_license_page(page_text):
                continue
            field_map = _field_map(items)
            license_no = _first_value(field_map, "certificate_no", "license_no", "许可证编号", "许可证号")
            if not license_no:
                match = _LICENSE_PATTERN.search(page_text.upper())
                license_no = match.group(0) if match else None
            organization_name = _first_value(
                field_map,
                "organization_name",
                "company_name",
                "unit_name",
                "单位名称",
            ) or _labeled_value(page_text, ("单位名称", "获准单位", "持证单位"))
            license_scope = _first_value(
                field_map,
                "license_scope",
                "许可范围",
                "许可项目",
            ) or _labeled_value(page_text, ("许可项目", "许可范围"))
            valid_until = _first_value(field_map, "valid_until", "expiry_date", "有效期至") or _labeled_value(
                page_text, ("有效期至", "有效日期至")
            )
            valid_from = _first_value(field_map, "valid_from", "issue_date", "发证日期") or _labeled_value(
                page_text, ("发证日期", "发证时间")
            )
            issuer = _first_value(field_map, "issuer", "issuing_authority", "发证机关") or _labeled_value(
                page_text, ("发证机关",)
            )
            primary = _best_evidence_item(items, license_no or organization_name or "许可证")
            candidate_key = {
                "documentVersionId": version_id,
                "pageNo": page_no,
                "licenseNo": _normalize_license_no(license_no),
                "organizationName": _normalize_text(organization_name),
            }
            candidate_id = f"{id_namespace}LIC-" + stable_payload_hash(candidate_key)[7:19].upper()
            evidence_id = f"{id_namespace}EV-{candidate_id.removeprefix(f'{id_namespace}LIC-')}"
            candidates.append(
                {
                    "candidateId": candidate_id,
                    "documentVersionId": version_id,
                    "documentId": parse_result.get("documentId"),
                    "fileName": _file_name(state, version_id),
                    "pageNo": page_no,
                    "licenseNo": license_no,
                    "organizationName": organization_name,
                    "licenseScopeRaw": license_scope,
                    "validFrom": valid_from,
                    "validUntil": valid_until,
                    "issuer": issuer,
                    "ocrConfidence": _average_confidence(items),
                    "evidence": {
                        "id": evidence_id,
                        "evidenceRefId": evidence_id,
                        "documentVersionId": version_id,
                        "pageNo": page_no,
                        "bbox": primary.get("bbox") or primary.get("polygon"),
                        "quotedText": _item_text(primary) or page_text[:500],
                        "confidence": _numeric_confidence(primary),
                    },
                }
            )
    unique: dict[str, dict[str, Any]] = {}
    for item in candidates:
        unique[str(item["candidateId"])] = item
    return list(unique.values())


def extract_component_items(
    state: dict[str, Any],
    review_run: dict[str, Any],
    *,
    id_namespace: str = "COMP",
    include_certificate_items: bool = True,
    design_only: bool = False,
) -> list[dict[str, Any]]:
    requested_versions = {str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item}
    output: list[dict[str, Any]] = []
    for parse_result in state.get("ocr_parse_results", []):
        if not isinstance(parse_result, dict):
            continue
        version_id = str(parse_result.get("documentVersionId") or "")
        if requested_versions and version_id not in requested_versions:
            continue
        if design_only and _is_certificate_or_report_parse_result(state, parse_result):
            continue
        for table in parse_result.get("tables") or []:
            if not isinstance(table, dict):
                continue
            schemas = " ".join(str(item) for item in table.get("businessSchemas") or [])
            table_title = " ".join(
                str(table.get(key) or "") for key in ("title", "tableName", "businessSchema", "documentType")
            )
            rows = table.get("normalizedRows") or table.get("records") or []
            if not isinstance(rows, list):
                continue
            for row_index, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    continue
                component_type = _row_value(
                    row,
                    "componentType",
                    "productType",
                    "productName",
                    "materialName",
                    "元件类型",
                    "产品名称",
                    "材料名称",
                    "名称",
                    "品名",
                )
                manufacturer = _row_value(row, "manufacturer", "manufacturerName", "制造单位", "生产厂家", "厂家")
                if not component_type and not manufacturer:
                    continue
                table_hint = f"{schemas} {table_title} {' '.join(str(key) for key in row)}"
                if not any(token in table_hint.lower() for token in ("material", "component", "valve", "pipe")) and not any(
                    token in table_hint for token in ("材料", "元件", "阀门", "管道", "安全附件")
                ):
                    continue
                item_key = {
                    "documentVersionId": version_id,
                    "tableId": table.get("tableId") or table.get("id"),
                    "rowIndex": row_index,
                    "componentType": component_type,
                    "manufacturer": manufacturer,
                }
                evidence_id = f"{id_namespace}EV-" + stable_payload_hash(item_key)[7:19].upper()
                page_no = table.get("pageNo") or 1
                output.append(
                    {
                        "componentItemId": f"{id_namespace}ITEM-" + stable_payload_hash(item_key)[7:19].upper(),
                        "componentType": component_type,
                        "productName": _row_value(row, "productName", "产品名称", "品名") or component_type,
                        "lineNo": _row_value(row, "lineNo", "pipelineNo", "pipeNo", "管线号", "管道编号"),
                        "manufacturerName": manufacturer,
                        "specification": _row_value(row, "specification", "规格", "规格型号", "型号"),
                        "grade": _row_value(row, "grade", "componentGrade", "strengthGrade", "等级", "性能等级", "强度等级"),
                        "pressureClass": _row_value(row, "pressureClass", "pressureRating", "压力等级", "公称压力"),
                        "nominalPressureMPa": _row_value(row, "nominalPressureMPa", "pressureMPa", "公称压力MPa"),
                        "nominalDiameterMM": _row_value(row, "nominalDiameterMM", "diameterMM", "公称直径", "DN"),
                        "material": _row_value(row, "material", "materialGrade", "材质", "材料牌号"),
                        "standardRef": _row_value(row, "standardRef", "standardNo", "productStandard", "执行标准", "产品标准", "标准号"),
                        "requiredInspectionItems": _row_value(
                            row,
                            "requiredInspectionItems",
                            "specialInspectionItems",
                            "inspectionRequirements",
                            "检验要求",
                            "复验项目",
                            "必检项目",
                        ),
                        "specialInspectionRequired": _optional_boolean(
                            _row_value(row, "specialInspectionRequired", "是否复验", "需要复验")
                        ),
                        "requiresManufacturingLicense": _optional_boolean(
                            _row_value(
                                row,
                                "requiresManufacturingLicense",
                                "manufacturingLicenseRequired",
                                "需制造许可",
                            )
                        ),
                        "requiresManufacturingSupervision": _optional_boolean(
                            _row_value(
                                row,
                                "requiresManufacturingSupervision",
                                "manufacturingSupervisionRequired",
                                "需制造监检",
                            )
                        ),
                        "requiresTypeTest": _optional_boolean(
                            _row_value(row, "requiresTypeTest", "typeTestRequired", "需型式试验")
                        ),
                        "minimumTestPressureMPa": _row_value(
                            row,
                            "minimumTestPressureMPa",
                            "requiredTestPressureMPa",
                            "最低试验压力MPa",
                            "试验压力MPa",
                        ),
                        "manufacturingProcess": _row_value(row, "manufacturingProcess", "process", "制造工艺", "工艺"),
                        "structure": _row_value(row, "structure", "structureType", "结构", "结构型式"),
                        "batchNo": _row_value(row, "batchNo", "lotNo", "批号", "批次号", "炉批号"),
                        "serialNo": _row_value(row, "serialNo", "productSerialNo", "产品编号", "出厂编号", "序列号"),
                        "supervisionMode": _row_value(row, "supervisionMode", "监检方式"),
                        "batchSupervisionEligible": _row_value(row, "batchSupervisionEligible", "可组批监检"),
                        "quantity": _row_value(row, "quantity", "数量"),
                        "documentVersionId": version_id,
                        "pageNo": page_no,
                        "tableId": table.get("tableId") or table.get("id"),
                        "rowIndex": row_index,
                        "sourceRow": row,
                        "evidence": {
                            "id": evidence_id,
                            "evidenceRefId": evidence_id,
                            "documentVersionId": version_id,
                            "pageNo": page_no,
                            "bbox": row.get("bbox") or row.get("polygon") or table.get("bbox") or table.get("polygon"),
                            "quotedText": json.dumps(row, ensure_ascii=False, default=str)[:800],
                            "confidence": _numeric_confidence(row) or _numeric_confidence(table),
                        },
                    }
                )
    certificate_items: list[dict[str, Any]] = []
    for parse_result in state.get("ocr_parse_results", []) if include_certificate_items else []:
        if not isinstance(parse_result, dict):
            continue
        version_id = str(parse_result.get("documentVersionId") or "")
        if requested_versions and version_id not in requested_versions:
            continue
        fields = [item for item in parse_result.get("fields") or [] if isinstance(item, dict)]
        field_map = _field_map(fields)
        manufacturer = _first_value(field_map, "manufacturer", "manufacturer_name", "生产厂家", "制造单位")
        if not manufacturer:
            continue
        fragments = [item for item in parse_result.get("fragments") or [] if isinstance(item, dict)]
        text = "\n".join(_item_text(item) for item in fragments if _item_text(item))
        component_type = _first_value(
            field_map,
            "product_name",
            "component_type",
            "material_name",
            "产品名称",
            "元件名称",
        ) or _labeled_value(text, ("产品名称", "元件名称", "品名"))
        specification = _first_value(field_map, "specification", "规格", "规格型号") or _labeled_value(
            text, ("规格型号", "规格")
        )
        material = _first_value(field_map, "material_grade", "material", "材料牌号", "材质")
        if not component_type and not specification:
            continue
        certificate_key = {
            "documentVersionId": version_id,
            "manufacturer": manufacturer,
            "componentType": component_type,
            "specification": specification,
        }
        certificate_items.append(
            {
                "componentItemId": f"{id_namespace}CERTITEM-" + stable_payload_hash(certificate_key)[7:19].upper(),
                "componentType": component_type,
                "manufacturerName": manufacturer,
                "specification": specification,
                "material": material,
                "documentVersionId": version_id,
                "pageNo": _first_page_no([*fields, *fragments]),
                "sourceType": "quality_certificate",
            }
        )

    unmatched_certificates = list(certificate_items)
    for item in output:
        if item.get("manufacturerName"):
            continue
        match = next((candidate for candidate in unmatched_certificates if _component_records_match(item, candidate)), None)
        if not match:
            continue
        item["manufacturerName"] = match.get("manufacturerName")
        item["qualityCertificateDocumentVersionId"] = match.get("documentVersionId")
        item["qualityCertificatePageNo"] = match.get("pageNo")
        if not item.get("componentType"):
            item["componentType"] = match.get("componentType")
        unmatched_certificates.remove(match)
    output.extend(unmatched_certificates)
    unique_items: dict[str, dict[str, Any]] = {}
    for item in output:
        signature = stable_payload_hash(
            {
                "componentType": _normalize_text(item.get("componentType")),
                "manufacturerName": _normalize_text(item.get("manufacturerName")),
                "specification": _normalize_text(item.get("specification")),
                "documentVersionId": item.get("documentVersionId"),
                "rowIndex": item.get("rowIndex"),
            }
        )
        unique_items[signature] = item
    return list(unique_items.values())


def extract_r12_component_items(
    state: dict[str, Any],
    review_run: dict[str, Any],
) -> list[dict[str, Any]]:
    return extract_component_items(state, review_run, id_namespace="R12", include_certificate_items=True)


def active_r12_human_input_task(review_run: dict[str, Any]) -> dict[str, Any] | None:
    tasks = review_run.get("humanInputTasks") if isinstance(review_run.get("humanInputTasks"), list) else []
    for task in reversed(tasks):
        if isinstance(task, dict) and task.get("taskType") == R12_TASK_TYPE and task.get("status") == "pending":
            return task
    return None


def ensure_r12_human_input_task(
    state: dict[str, Any],
    review_run: dict[str, Any],
    *,
    requested_by: str,
    agent_trace: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not is_r12_formal_review(review_run):
        return None
    existing = active_r12_human_input_task(review_run)
    if existing:
        return existing
    candidates = extract_r12_license_candidates(state, review_run)
    if not candidates:
        return None
    task_input_hash = stable_payload_hash(
        {
            "reviewRunInputHash": review_run.get("inputHash"),
            "candidates": candidates,
        }
    )
    completed = [
        item
        for item in review_run.get("humanInputTasks") or []
        if isinstance(item, dict)
        and item.get("taskType") == R12_TASK_TYPE
        and item.get("status") == "completed"
        and item.get("inputHash") == task_input_hash
    ]
    if completed:
        return None
    now = server_time()
    registry_url = os.getenv("AICHECK_SPECIAL_EQUIPMENT_REGISTRY_URL", "").strip()
    if registry_url and not _valid_http_url(registry_url):
        registry_url = ""
    task = {
        "taskId": f"HIT-R12-{uuid4().hex[:10].upper()}",
        "taskType": R12_TASK_TYPE,
        "nodeId": R12_NODE_ID,
        "title": "核验制造许可证官网登记信息",
        "description": (
            "请在全国特种设备公示信息查询平台逐张查询许可证号，核对单位名称、证照状态、"
            "许可范围和有效期。系统不会把 OCR 结果当作官网核验结果。"
        ),
        "status": "pending",
        "required": True,
        "requestedBy": requested_by,
        "officialRegistryUrl": registry_url,
        "inputHash": task_input_hash,
        "reviewRunInputHash": review_run.get("inputHash"),
        "candidates": candidates,
        "candidateCount": len(candidates),
        "agentTrace": agent_trace or {},
        "responses": [],
        "createdAt": now,
        "updatedAt": now,
    }
    review_run.setdefault("humanInputTasks", []).append(task)
    return task


def validate_r12_human_input(
    review_run: dict[str, Any],
    task_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    task = next(
        (
            item
            for item in review_run.get("humanInputTasks") or []
            if isinstance(item, dict) and str(item.get("taskId") or "") == str(task_id)
        ),
        None,
    )
    if not task:
        return {"status": "missing_task", "errors": ["human_input_task_not_found"]}
    if task.get("status") != "pending" or review_run.get("status") != "waiting_human_input":
        return {"status": "invalid_state", "errors": ["human_input_task_not_pending"]}
    if task.get("reviewRunInputHash") != review_run.get("inputHash"):
        return {"status": "stale_input", "errors": ["review_run_input_changed"]}
    expected_ids = {str(item.get("candidateId")) for item in task.get("candidates") or [] if item.get("candidateId")}
    submitted = payload.get("verifications")
    if not isinstance(submitted, list):
        return {"status": "invalid_input", "errors": ["verifications_must_be_array"]}
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(submitted):
        if not isinstance(item, dict):
            errors.append(f"verification_{index + 1}_must_be_object")
            continue
        candidate_id = str(item.get("candidateId") or "")
        outcome = str(item.get("outcome") or "")
        registry_status = str(item.get("registryStatus") or "unknown")
        if candidate_id not in expected_ids:
            errors.append(f"verification_{index + 1}_candidate_invalid")
        if candidate_id in seen:
            errors.append(f"verification_{index + 1}_candidate_duplicate")
        seen.add(candidate_id)
        if outcome not in R12_VERIFICATION_OUTCOMES:
            errors.append(f"verification_{index + 1}_outcome_invalid")
        if registry_status not in R12_REGISTRY_STATUSES:
            errors.append(f"verification_{index + 1}_registry_status_invalid")
        attested = item.get("attested") is True
        if not attested:
            errors.append(f"verification_{index + 1}_attestation_required")
        source_url = _clean_text(item.get("sourceUrl"), 2000)
        if outcome in {"verified_match", "verified_mismatch"} and not source_url:
            errors.append(f"verification_{index + 1}_source_url_required")
        elif source_url and not _valid_http_url(source_url):
            errors.append(f"verification_{index + 1}_source_url_invalid")
        if outcome == "verified_match" and (
            not _clean_text(item.get("registryLicenseNo"), 120)
            or not _clean_text(item.get("registryOrganizationName"), 300)
            or not _clean_text(item.get("registryScopeRaw"), 4000)
        ):
            errors.append(f"verification_{index + 1}_registry_fields_required")
        normalized.append(
            {
                "candidateId": candidate_id,
                "outcome": outcome,
                "registryLicenseNo": _clean_text(item.get("registryLicenseNo"), 120),
                "registryOrganizationName": _clean_text(item.get("registryOrganizationName"), 300),
                "registryStatus": registry_status,
                "registryScopeRaw": _clean_text(item.get("registryScopeRaw"), 4000),
                "registryValidFrom": _clean_text(item.get("registryValidFrom"), 100),
                "registryValidUntil": _clean_text(item.get("registryValidUntil"), 100),
                "sourceUrl": source_url,
                "attachmentIds": [
                    _clean_text(value, 200)
                    for value in item.get("attachmentIds") or []
                    if _clean_text(value, 200)
                ][:20],
                "comment": _clean_text(item.get("comment"), 2000),
                "correctionReason": _clean_text(item.get("correctionReason"), 1000),
                "attested": attested,
            }
        )
    if seen != expected_ids:
        errors.append("every_candidate_requires_one_verification")
    return {"status": "invalid_input" if errors else "valid", "errors": errors, "verifications": normalized}


def apply_r12_human_input(
    review_run: dict[str, Any],
    task_id: str,
    payload: dict[str, Any],
    *,
    actor_id: str | None,
    actor_name: str | None,
    command_id: str | None = None,
) -> dict[str, Any]:
    validation = validate_r12_human_input(review_run, task_id, payload)
    if validation.get("status") != "valid":
        return validation
    task = next(
        item
        for item in review_run.get("humanInputTasks") or []
        if isinstance(item, dict) and str(item.get("taskId") or "") == str(task_id)
    )
    now = server_time()
    response = {
        "responseId": f"HIRESP-{uuid4().hex[:10].upper()}",
        "commandId": command_id,
        "inputHash": task.get("inputHash"),
        "verifications": validation["verifications"],
        "generalComment": _clean_text(payload.get("comment"), 2000),
        "actorId": actor_id,
        "actorName": actor_name,
        "submittedAt": now,
    }
    task.setdefault("responses", []).append(response)
    task["status"] = "completed"
    task["completedAt"] = now
    task["updatedAt"] = now
    review_run.setdefault("manualRegistryVerifications", []).append(
        {
            "taskId": task_id,
            "responseId": response["responseId"],
            "inputHash": task.get("inputHash"),
            "verifications": validation["verifications"],
            "actorId": actor_id,
            "actorName": actor_name,
            "submittedAt": now,
        }
    )
    review_run["status"] = "resuming"
    review_run["currentStep"] = "resume_after_human_input"
    review_run["updatedAt"] = now
    return {"status": "applied", "task": task, "response": response, "reviewRun": review_run}


def build_r12_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    candidates = extract_r12_license_candidates(state, review_run)
    latest_by_candidate: dict[str, dict[str, Any]] = {}
    for record in review_run.get("manualRegistryVerifications") or []:
        if not isinstance(record, dict):
            continue
        for verification in record.get("verifications") or []:
            if isinstance(verification, dict) and verification.get("candidateId"):
                latest_by_candidate[str(verification["candidateId"])] = verification
    component_items = extract_r12_component_items(state, review_run)
    evidence_refs = [
        item.get("evidence")
        for item in candidates
        if isinstance(item.get("evidence"), dict)
    ]
    return {
        "manufacturerLicenseCandidates": candidates,
        "manualRegistryVerifications": list(latest_by_candidate.values()),
        "componentItems": component_items,
        "judgment": {
            "claimedFacts": [
                {
                    "factId": f"r12-license-{item.get('candidateId')}",
                    "value": item.get("licenseNo"),
                    "documentVersionId": item.get("documentVersionId"),
                    "evidenceRefIds": [item.get("evidence", {}).get("evidenceRefId")],
                    "confidence": item.get("evidence", {}).get("confidence") or item.get("ocrConfidence"),
                    "conflicted": False,
                }
                for item in candidates
            ],
            "evidenceRefs": evidence_refs,
        },
        "evidence": {
            "pageNo": [item.get("pageNo") for item in evidence_refs],
            "bboxOrQuotedText": [item.get("bbox") or item.get("quotedText") for item in evidence_refs],
            "ocrConfidence": [item.get("confidence") for item in evidence_refs],
            "conflictStatus": "no_conflict_detected" if candidates else "unknown",
        },
    }


def _is_manufacturing_license_page(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact or any(marker in compact for marker in _PERSONNEL_MARKERS):
        return False
    has_manufacturing_scope = any(marker in compact for marker in _MANUFACTURING_MARKERS)
    if "压力管道安装" in compact and not has_manufacturing_scope:
        return False
    return has_manufacturing_scope and ("许可证" in compact or bool(_LICENSE_PATTERN.search(compact.upper())))


def _is_certificate_or_report_parse_result(state: dict[str, Any], parse_result: dict[str, Any]) -> bool:
    version_id = str(parse_result.get("documentVersionId") or "")
    metadata = parse_result.get("metadata") if isinstance(parse_result.get("metadata"), dict) else {}
    hints = " ".join(
        str(value or "")
        for value in (
            parse_result.get("profileId"),
            parse_result.get("documentType"),
            metadata.get("detectedProfileId"),
            _file_name(state, version_id),
        )
    ).lower()
    compact = _normalize_text(hints)
    markers = (
        "certificate",
        "report",
        "qualitycertificate",
        "manufacturingsupervision",
        "typetest",
        "证书",
        "检验报告",
        "型式试验",
        "质量证明",
    )
    return any(marker in compact for marker in markers)


def _field_map(items: list[dict[str, Any]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for item in items:
        code = str(item.get("fieldCode") or item.get("key") or item.get("name") or "").strip()
        value = str(item.get("fieldValue") or item.get("value") or "").strip()
        if code and value:
            output[code] = value
    return output


def _first_value(values: dict[str, str], *keys: str) -> str | None:
    normalized = {_normalize_text(key): value for key, value in values.items()}
    for key in keys:
        if _normalize_text(key) in normalized:
            return normalized[_normalize_text(key)]
    return None


def _labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    for line in text.splitlines():
        compact = line.strip()
        for label in labels:
            if label in compact:
                value = re.sub(rf"^.*?{re.escape(label)}\s*[：:]?\s*", "", compact).strip()
                if value and value != compact:
                    return value[:500]
    return None


def _item_text(item: dict[str, Any]) -> str:
    return str(item.get("text") or item.get("quotedText") or item.get("fieldValue") or item.get("value") or "").strip()


def _numeric_confidence(item: dict[str, Any]) -> float:
    try:
        return round(float(item.get("confidence") or item.get("ocrConfidence") or 0), 4)
    except (TypeError, ValueError):
        return 0.0


def _average_confidence(items: list[dict[str, Any]]) -> float:
    values = [_numeric_confidence(item) for item in items if _numeric_confidence(item) > 0]
    return round(sum(values) / len(values), 4) if values else 0.0


def _best_evidence_item(items: list[dict[str, Any]], query: str) -> dict[str, Any]:
    normalized_query = _normalize_text(query)
    ranked = sorted(
        items,
        key=lambda item: (
            normalized_query in _normalize_text(_item_text(item)),
            _numeric_confidence(item),
        ),
        reverse=True,
    )
    return ranked[0] if ranked else {}


def _file_name(state: dict[str, Any], version_id: str) -> str | None:
    version = next(
        (
            item
            for item in state.get("versions", [])
            if isinstance(item, dict)
            and str(item.get("id") or item.get("versionId") or item.get("documentVersionId") or "") == version_id
        ),
        None,
    )
    if not version:
        return None
    if version.get("fileName"):
        return str(version["fileName"])
    document_id = str(version.get("documentId") or "")
    document = next(
        (
            item
            for item in state.get("documents", [])
            if isinstance(item, dict) and str(item.get("id") or item.get("documentId") or "") == document_id
        ),
        None,
    )
    return str((document or {}).get("fileName") or (document or {}).get("name") or "") or None


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    normalized = {_normalize_text(key): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(_normalize_text(key))
        if value is not None and value != "":
            return value
    return None


def _component_records_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_spec = _normalize_text(left.get("specification"))
    right_spec = _normalize_text(right.get("specification"))
    if left_spec and right_spec and (left_spec == right_spec or left_spec in right_spec or right_spec in left_spec):
        return True
    left_type = _normalize_text(left.get("componentType"))
    right_type = _normalize_text(right.get("componentType"))
    left_material = _normalize_text(left.get("material"))
    right_material = _normalize_text(right.get("material"))
    return bool(
        left_type
        and right_type
        and (left_type == right_type or left_type in right_type or right_type in left_type)
        and (not left_material or not right_material or left_material == right_material)
    )


def _first_page_no(items: list[dict[str, Any]]) -> int:
    for item in items:
        try:
            return max(1, int(item.get("pageNo") or 1))
        except (TypeError, ValueError):
            continue
    return 1


def _normalize_license_no(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def _optional_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _normalize_text(value)
    if normalized in {"true", "yes", "required", "是", "需要", "适用", "1"}:
        return True
    if normalized in {"false", "no", "notrequired", "否", "不需要", "不适用", "0"}:
        return False
    return None


def _normalize_text(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)


def _clean_text(value: Any, limit: int) -> str | None:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit] if text else None


def _valid_http_url(value: str) -> bool:
    return bool(re.match(r"^https?://[^\s]+$", value, flags=re.IGNORECASE))
