from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time


MAPPING_DOC_RELATIVE_PATH = "docs/工程监检资料映射表.md"
SUPPORTED_STATUS = "命中"
PARTIAL_STATUS = "待人工确认"
UNMATCHED_STATUS = "未命中"
MANUAL_PENDING = "pending"
MANUAL_CONFIRMED = "confirmed"
MANUAL_REJECTED = "rejected"
MANUAL_STATUS_LABELS = {
    MANUAL_PENDING: "待确认",
    MANUAL_CONFIRMED: "已确认",
    MANUAL_REJECTED: "不采用",
}


def stable_short_id(*parts: Any, length: int = 16) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length].upper()


def split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if cells and all(re.fullmatch(r":?-{2,}:?", cell.strip()) for cell in cells):
        return []
    return cells


def extract_material_type(raw: str) -> tuple[str, str]:
    code_match = re.search(r"`([^`]+)`", raw) or re.search(r"[（(]([a-zA-Z0-9_\-]+)[）)]", raw)
    code = str(code_match.group(1)).strip() if code_match else ""
    name = re.sub(r"`[^`]+`", "", raw)
    name = re.sub(r"[（(][^）)]+[）)]", "", name).strip()
    name = re.sub(r"[（(]\s*[）)]", "", name).strip()
    return name or raw.strip(), code


def split_evidence_items(raw: str) -> list[str]:
    normalized = str(raw or "").replace("；", "、").replace(";", "、").replace("，", "、").replace(",", "、")
    items = [item.strip(" ：:。.\t\r\n") for item in normalized.split("、")]
    return [item for item in items if item][:20]


def responsible_party_code(raw: str) -> str:
    text = str(raw or "")
    if "无损" in text or "检测机构" in text:
        return "ndt"
    if "监检" in text:
        return "inspection"
    if "建设" in text or "业主" in text:
        return "owner"
    return "contractor"


def load_review_points_from_mapping_doc(
    mapping_doc: Path,
    *,
    business_pack_id: str = "engineering_inspection_v1",
    source: str = MAPPING_DOC_RELATIVE_PATH,
) -> list[dict[str, Any]]:
    if not mapping_doc.exists():
        return []
    lines = mapping_doc.read_text(encoding="utf-8").splitlines()
    header: list[str] = []
    rows: list[dict[str, str]] = []
    for line in lines:
        cells = split_markdown_row(line)
        if not cells:
            continue
        if cells and cells[0] == "节点":
            header = cells
            continue
        if not header or not cells or not re.fullmatch(r"\d+", cells[0] or ""):
            continue
        padded = cells + [""] * max(0, len(header) - len(cells))
        rows.append(dict(zip(header, padded[: len(header)])))

    review_points: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        material_type_name, material_type_code = extract_material_type(row.get("上传资料类型") or "")
        if not material_type_code:
            continue
        node_id = int(row.get("节点") or 0)
        if node_id == 69:
            continue
        evidence_items = split_evidence_items(row.get("需定位的内容项/字段") or "")
        review_content = (row.get("审查内容") or row.get("节点名称") or material_type_name).strip()
        point_id = f"MRP-{node_id}-{material_type_code}-{stable_short_id(index, review_content, material_type_code, length=6)}"
        review_points.append(
            {
                "id": point_id,
                "businessPackId": business_pack_id,
                "nodeId": node_id,
                "nodeName": (row.get("节点名称") or "").strip(),
                "ruleId": (row.get("规则") or "").strip(),
                "businessModule": (row.get("业务模块") or "").strip(),
                "reviewClass": (row.get("类别") or "").strip(),
                "reviewContent": review_content,
                "materialCategory": (row.get("上传资料大类") or "").strip(),
                "materialTypeCode": material_type_code,
                "materialTypeName": material_type_name,
                "fileContent": (row.get("资料要求/文件内容") or "").strip(),
                "evidenceItemText": (row.get("需定位的内容项/字段") or "").strip(),
                "evidenceItems": evidence_items,
                "responsibleParty": responsible_party_code(row.get("责任方") or ""),
                "responsiblePartyLabel": (row.get("责任方") or "").strip(),
                "requiredType": (row.get("必传口径") or "条件必传").strip(),
                "mappingRelation": (row.get("映射关系") or "").strip(),
                "minConfidence": 0.65,
                "enabled": True,
                "source": source,
                "updatedAt": "2026-06-26 08:30:00",
                "revision": 1,
            }
        )
    return review_points


def latest_parse_result(repo: Any, document_version_id: str) -> dict[str, Any] | None:
    results = [
        item
        for item in repo.state.get("ocr_parse_results", [])
        if str(item.get("documentVersionId") or "") == str(document_version_id)
    ]
    if not results:
        return None
    return sorted(results, key=lambda item: str(item.get("finishedAt") or item.get("createdAt") or ""), reverse=True)[0]


def review_points_for_project(repo: Any, project: dict[str, Any] | None, node_id: int | None = None) -> list[dict[str, Any]]:
    business_pack_id = (project or {}).get("businessPackId") or "engineering_inspection_v1"
    points = [
        repo.clone(item)
        for item in repo.state.get("admin_config", {}).get("materialReviewPoints", [])
        if item.get("enabled", True) and str(item.get("businessPackId") or business_pack_id) == str(business_pack_id)
    ]
    if node_id is not None:
        points = [item for item in points if int(item.get("nodeId") or 0) == int(node_id)]
    return points


def flatten_text(value: Any, *, limit: int = 120000) -> str:
    parts: list[str] = []
    total = 0

    def visit(item: Any) -> None:
        nonlocal total
        if total > limit:
            return
        if item is None:
            return
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, list):
            for nested in item:
                visit(nested)
            return
        text = str(item).strip()
        if text:
            parts.append(text)
            total += len(text) + 1

    visit(value)
    return " ".join(parts)[:limit]


def normalized_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def document_party(document: dict[str, Any]) -> str:
    source = f"{document.get('sourceOrgName') or ''} {document.get('uploaderName') or ''}"
    if "无损" in source or "检测" in source:
        return "ndt"
    if "监检" in source or "特检" in source:
        return "inspection"
    if "建设" in source or "业主" in source:
        return "owner"
    return "contractor"


def keyword_variants(keyword: Any) -> list[str]:
    raw = normalized_text(keyword)
    if not raw:
        return []
    variants = {raw}
    aliases = {
        "机构名称": ["单位名称", "施工单位", "安装单位", "企业名称", "获证单位"],
        "证书编号": ["许可证编号", "许可证号", "编号", "证号"],
        "许可范围": ["许可项目", "许可子项目", "类别级别", "获准从事", "工业管道", "gc1", "gc2", "gcd", "锅炉安装", "a级"],
        "有效期至": ["有效期", "有效期限", "有效日期", "有效期至"],
        "设计说明": ["设计说明", "施工说明", "工艺设计说明书", "设计说明书"],
        "管道特性表中的管道类别/级别和施工范围": ["管道特性表", "压力管道级别", "管道级别", "gc1", "gc2", "gcd", "管线号", "施工范围"],
        "管道类别": ["压力管道级别", "管道级别", "gc1", "gc2", "gcd"],
        "级别": ["压力管道级别", "管道级别", "gc1", "gc2", "gcd"],
        "施工范围": ["工程内容", "项目范围", "施工范围", "管线", "管道"],
        "开始日期": ["开始日期", "开工日期", "安装开工日期", "进场", "工期目标"],
        "结束日期": ["结束日期", "竣工日期", "安装竣工日期", "竣工验收", "完工", "工期目标"],
        "项目范围": ["工程内容", "工程名称", "项目名称", "项目范围", "施工范围"],
        "施工计划工期文件": ["施工方案", "施工组织设计", "施工进度计划", "工期目标", "开工", "竣工"],
        "construction_schedule": ["施工方案", "施工组织设计", "施工进度计划", "工期目标", "开工", "竣工"],
        "设计文件": ["设计文件", "设计说明", "管道特性表", "工艺设计说明书", "图纸"],
        "design_document": ["设计文件", "设计说明", "管道特性表", "工艺设计说明书", "图纸"],
        "施工单位安装许可证": ["特种设备安装改造维修许可证", "特种设备生产许可证", "压力管道安装", "安装许可证"],
        "construction_license": ["特种设备安装改造维修许可证", "特种设备生产许可证", "压力管道安装", "安装许可证"],
    }
    for alias_key, alias_values in aliases.items():
        alias_raw = normalized_text(alias_key)
        if raw == alias_raw or raw in alias_raw or alias_raw in raw:
            variants.update(normalized_text(item) for item in alias_values)
    for prefix in [
        "设计许可证",
        "安装许可证",
        "施工图纸标题栏",
        "设计说明中的",
        "管道特性表中的",
        "报告",
        "证书",
        "文件",
    ]:
        if raw.startswith(prefix):
            variants.add(raw[len(prefix) :])
    for token in re.split(r"[/／:：()（）\[\]【】\-]", raw):
        if len(token) >= 2:
            variants.add(token)
    return [item for item in variants if len(item) >= 2]


def contains_any(haystack: str, keywords: list[str]) -> bool:
    return any(keyword and keyword in haystack for keyword in keywords)


def material_type_matches_point(point: dict[str, Any], document: dict[str, Any], fulltext: str) -> tuple[int, str | None]:
    material_type_code = str(point.get("materialTypeCode") or "")
    material_type_name = str(point.get("materialTypeName") or "")
    material_category = str(point.get("materialCategory") or "")
    declared_type = str(document.get("materialTypeCode") or "")
    declared_category = str(document.get("materialCategory") or "")
    material_keywords = keyword_variants(material_type_code) + keyword_variants(material_type_name)
    if material_type_code and declared_type == material_type_code:
        return 35, "标准资料类型一致"
    if material_type_code == "construction_schedule" and (
        declared_type == "construction_organization_design"
        or contains_any(normalized_text(declared_category), keyword_variants("施工组织与方案"))
        or contains_any(fulltext, keyword_variants("施工计划工期文件"))
    ):
        return 30, "施工方案可支撑施工计划工期"
    if material_type_code == "design_document" and (
        declared_type == "design_document" or contains_any(fulltext, keyword_variants("设计文件"))
    ):
        return 35 if declared_type == "design_document" else 28, "标准资料类型一致" if declared_type == "design_document" else "文件名或 OCR 文本命中资料类型"
    if material_type_code == "construction_license" and contains_any(fulltext, keyword_variants("construction_license")):
        return 28, "文件名或 OCR 文本命中资料类型"
    if contains_any(fulltext, material_keywords):
        return 28, "文件名或 OCR 文本命中资料类型"
    if material_category and (material_category in declared_category or contains_any(fulltext, keyword_variants(material_category))):
        return 14, "上传资料大类一致"
    return 0, None


def best_excerpt(parse_result: dict[str, Any] | None, fields: list[dict[str, Any]], keywords: list[str]) -> dict[str, Any]:
    for field in fields:
        haystack = normalized_text(f"{field.get('fieldName') or ''}{field.get('fieldValue') or ''}")
        if contains_any(haystack, keywords):
            return {
                "quotedText": str(field.get("fieldValue") or field.get("fieldName") or "")[:220],
                "pageNo": int(field.get("pageNo") or 1),
                "bbox": field.get("bbox"),
                "fieldName": field.get("fieldName"),
                "fieldId": field.get("id"),
            }
    for fragment in ((parse_result or {}).get("fragments") or [])[:1000]:
        if not isinstance(fragment, dict):
            continue
        text = str(fragment.get("text") or "").strip()
        if not text:
            continue
        if not keywords or contains_any(normalized_text(text), keywords):
            return {
                "quotedText": text[:220],
                "pageNo": int(fragment.get("pageNo") or 1),
                "bbox": fragment.get("bbox"),
                "fieldName": "OCR文本",
                "fieldId": None,
            }
    return {"quotedText": "", "pageNo": 1, "bbox": None, "fieldName": None, "fieldId": None}


def document_targeting_context(
    document: dict[str, Any],
    parse_result: dict[str, Any] | None,
    extracted_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    fulltext = normalized_text(
        " ".join(
            [
                str(document.get("fileName") or ""),
                str(document.get("materialCategory") or ""),
                str(document.get("materialTypeCode") or ""),
                str(document.get("sourceOrgName") or ""),
                flatten_text(parse_result or {}),
                flatten_text(extracted_fields),
            ]
        )
    )
    field_texts = [
        normalized_text(f"{field.get('fieldName') or ''}{field.get('fieldValue') or ''}")
        for field in extracted_fields
    ]
    return {"fulltext": fulltext, "fieldTexts": field_texts}


def score_review_point(
    point: dict[str, Any],
    document: dict[str, Any],
    version: dict[str, Any] | None,
    parse_result: dict[str, Any] | None,
    extracted_fields: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or document_targeting_context(document, parse_result, extracted_fields)
    fulltext = str(context.get("fulltext") or "")
    field_texts = [str(item) for item in context.get("fieldTexts") or []]

    score = 0
    reasons: list[str] = []
    material_score, material_reason = material_type_matches_point(point, document, fulltext)
    if material_score:
        score += material_score
        if material_reason:
            reasons.append(material_reason)

    evidence_items = [str(item) for item in point.get("evidenceItems") or [] if str(item).strip()]
    matched_evidence: list[str] = []
    for item in evidence_items:
        if contains_any(fulltext, keyword_variants(item)):
            matched_evidence.append(item)
    evidence_coverage = len(matched_evidence) / len(evidence_items) if evidence_items else 0.0
    if evidence_items:
        score += round(35 * evidence_coverage)
        if matched_evidence:
            reasons.append(f"命中 {len(matched_evidence)}/{len(evidence_items)} 个证据项")

    field_hits = 0
    for field_text in field_texts:
        if any(contains_any(field_text, keyword_variants(item)) for item in evidence_items):
            field_hits += 1
    if field_hits:
        score += min(15, field_hits * 3)
        reasons.append(f"结构化字段命中 {field_hits} 项")

    if str(point.get("responsibleParty") or "") == document_party(document):
        score += 10
        reasons.append("上传责任方一致")

    material_category = str(point.get("materialCategory") or "")
    if material_category and material_category in str(document.get("fileName") or ""):
        score += 5
        reasons.append("文件名命中资料大类")

    score = min(score, 100)
    confidence = round(score / 100, 4)
    material_hit = any(reason.startswith("标准资料类型") or "资料类型" in reason for reason in reasons)
    if score >= 70 and (material_hit or evidence_coverage > 0):
        support_status = SUPPORTED_STATUS
    elif score >= 45:
        support_status = PARTIAL_STATUS
    else:
        support_status = UNMATCHED_STATUS

    keywords = []
    for item in [point.get("materialTypeCode"), point.get("materialTypeName"), *matched_evidence, *evidence_items[:3]]:
        keywords.extend(keyword_variants(item))
    excerpt = best_excerpt(parse_result, extracted_fields, keywords)
    return {
        "reviewPointId": point.get("id"),
        "nodeId": int(point.get("nodeId") or 0),
        "score": score,
        "confidence": confidence,
        "supportStatus": support_status,
        "matchedEvidenceItems": matched_evidence,
        "evidenceCoverage": round(evidence_coverage, 4),
        "reasons": reasons,
        "excerpt": excerpt,
    }


def upsert_auto_binding(
    repo: Any,
    project_id: str,
    point: dict[str, Any],
    document: dict[str, Any],
    version_id: str,
    match: dict[str, Any],
) -> dict[str, Any] | None:
    node_id = int(point.get("nodeId") or 0)
    if not node_id:
        return None
    existing = next(
        (
            item
            for item in repo.state.get("bindings", [])
            if item.get("projectId") == project_id
            and int(item.get("nodeId") or 0) == node_id
            and item.get("documentVersionId") == version_id
        ),
        None,
    )
    review_point_ids = {str(item) for item in (existing or {}).get("reviewPointIds") or [] if item}
    review_point_ids.add(str(point.get("id") or ""))
    if existing:
        existing["reviewPointIds"] = sorted(review_point_ids)
        existing["autoMatchConfidence"] = max(float(existing.get("autoMatchConfidence") or 0), float(match.get("confidence") or 0))
        existing["updatedAt"] = server_time()
        return existing

    binding = {
        "id": f"BIND-AUTO-{stable_short_id(project_id, node_id, version_id, length=10)}",
        "projectId": project_id,
        "nodeId": node_id,
        "requirementId": point.get("id"),
        "requirementName": point.get("reviewContent") or point.get("materialTypeName"),
        "documentId": document["id"],
        "documentVersionId": version_id,
        "fileName": document["fileName"],
        "versionNo": "V1",
        "usage": "检测报告" if point.get("responsibleParty") == "ndt" else "原始提交",
        "sourceOrgName": document.get("sourceOrgName") or "",
        "bindingStatus": "草稿挂载",
        "boundByName": document.get("uploaderName") or "系统打靶",
        "boundAt": server_time(),
        "source": "material_targeting",
        "reviewPointIds": sorted(review_point_ids),
        "autoMatchConfidence": match.get("confidence"),
        "actions": ["submission:submit", "submission:withdraw"],
    }
    repo.state.setdefault("bindings", []).insert(0, binding)
    return binding


def node_evidence_link_from_match(
    project_id: str,
    point: dict[str, Any],
    document: dict[str, Any],
    version_id: str,
    match: dict[str, Any],
) -> dict[str, Any]:
    excerpt = match.get("excerpt") or {}
    link_id = f"NEL-{stable_short_id(project_id, point.get('id'), version_id)}"
    return {
        "id": link_id,
        "projectId": project_id,
        "businessPackId": point.get("businessPackId"),
        "nodeId": int(point.get("nodeId") or 0),
        "nodeName": point.get("nodeName"),
        "ruleId": point.get("ruleId"),
        "reviewPointId": point.get("id"),
        "reviewContent": point.get("reviewContent"),
        "materialTypeCode": point.get("materialTypeCode"),
        "materialTypeName": point.get("materialTypeName"),
        "materialCategory": point.get("materialCategory"),
        "requiredType": point.get("requiredType"),
        "responsibleParty": point.get("responsibleParty"),
        "documentId": document["id"],
        "documentVersionId": version_id,
        "fileName": document.get("fileName"),
        "pageNo": excerpt.get("pageNo"),
        "bbox": excerpt.get("bbox"),
        "fieldName": excerpt.get("fieldName"),
        "fieldId": excerpt.get("fieldId"),
        "quotedText": excerpt.get("quotedText"),
        "matchedEvidenceItems": match.get("matchedEvidenceItems") or [],
        "evidenceCoverage": match.get("evidenceCoverage"),
        "supportStatus": match.get("supportStatus"),
        "confidence": match.get("confidence"),
        "score": match.get("score"),
        "scoreReasons": match.get("reasons") or [],
        "manualStatus": MANUAL_PENDING,
        "manualStatusLabel": MANUAL_STATUS_LABELS[MANUAL_PENDING],
        "source": "material_targeting",
        "createdAt": server_time(),
    }


def run_material_targeting(
    repo: Any,
    project_id: str,
    document_id: str,
    version_id: str | None = None,
    *,
    triggered_by: str = "ocr",
    auto_bind: bool = True,
) -> dict[str, Any]:
    project = repo.require_project(project_id)
    document = repo.find_one("documents", document_id)
    if not project or not document or document.get("projectId") != project_id:
        return {"status": "missing", "documentId": document_id, "createdLinkCount": 0, "createdBindingCount": 0}
    current_version = repo.current_version(document_id) or {}
    version_id = version_id or current_version.get("id") or document.get("currentVersionId")
    version = repo.find_one("versions", str(version_id or ""))
    if not version_id:
        return {"status": "missing_version", "documentId": document_id, "createdLinkCount": 0, "createdBindingCount": 0}

    parse_result = latest_parse_result(repo, str(version_id))
    fields = repo.fields_for_versions({str(version_id)})
    points = review_points_for_project(repo, project)
    context = document_targeting_context(document, parse_result, fields)
    previous_manual_state = {
        str(item.get("id")): {
            key: item.get(key)
            for key in [
                "manualStatus",
                "manualStatusLabel",
                "confirmedByName",
                "confirmedAt",
                "rejectedByName",
                "rejectedAt",
                "manualComment",
                "manualUpdatedAt",
            ]
            if item.get(key) is not None
        }
        for item in repo.state.get("node_evidence_links", [])
        if item.get("projectId") == project_id
        and item.get("documentVersionId") == version_id
        and item.get("source") == "material_targeting"
        and item.get("id")
    }
    repo.state["node_evidence_links"] = [
        item
        for item in repo.state.get("node_evidence_links", [])
        if not (
            item.get("projectId") == project_id
            and item.get("documentVersionId") == version_id
            and item.get("source") == "material_targeting"
        )
    ]

    candidates = [
        {**score_review_point(point, document, version, parse_result, fields, context), "reviewPoint": point}
        for point in points
    ]
    candidates.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
    created_links: list[dict[str, Any]] = []
    touched_bindings: list[dict[str, Any]] = []
    touched_nodes: set[int] = set()
    for candidate in candidates:
        point = candidate.pop("reviewPoint")
        min_confidence = float(point.get("minConfidence") or 0.65)
        if candidate["supportStatus"] == UNMATCHED_STATUS or float(candidate["confidence"] or 0) < min_confidence:
            continue
        link = node_evidence_link_from_match(project_id, point, document, str(version_id), candidate)
        if link["id"] in previous_manual_state:
            link.update(previous_manual_state[link["id"]])
        repo.state.setdefault("node_evidence_links", []).insert(0, link)
        created_links.append(link)
        touched_nodes.add(int(point.get("nodeId") or 0))
        if auto_bind and candidate["supportStatus"] == SUPPORTED_STATUS:
            binding = upsert_auto_binding(repo, project_id, point, document, str(version_id), candidate)
            if binding:
                touched_bindings.append(binding)

    for node_id in sorted(touched_nodes):
        node = repo.node(project_id, node_id)
        if node and node.get("status") == "待提交":
            repo.set_node_status(project_id, node_id, "部分提交")

    run = {
        "id": f"MTR-{uuid4().hex[:10].upper()}",
        "projectId": project_id,
        "documentId": document_id,
        "documentVersionId": version_id,
        "triggeredBy": triggered_by,
        "status": "completed",
        "candidateCount": len(candidates),
        "createdLinkCount": len(created_links),
        "createdBindingCount": len({item.get("id") for item in touched_bindings}),
        "topCandidates": [
            {
                key: value
                for key, value in candidate.items()
                if key in {"reviewPointId", "nodeId", "score", "confidence", "supportStatus", "matchedEvidenceItems", "reasons"}
            }
            for candidate in candidates[:12]
        ],
        "createdAt": server_time(),
    }
    repo.state.setdefault("material_targeting_runs", []).insert(0, run)
    return {
        **run,
        "createdLinks": created_links,
        "createdBindings": touched_bindings,
    }


def recompute_project_material_targeting(repo: Any, project_id: str, *, triggered_by: str = "manual") -> dict[str, Any]:
    documents = [item for item in repo.state.get("documents", []) if item.get("projectId") == project_id]
    runs = [
        run_material_targeting(repo, project_id, document["id"], document.get("currentVersionId"), triggered_by=triggered_by)
        for document in documents
    ]
    return {
        "projectId": project_id,
        "documentCount": len(documents),
        "runCount": len(runs),
        "createdLinkCount": sum(int(run.get("createdLinkCount") or 0) for run in runs),
        "createdBindingCount": sum(int(run.get("createdBindingCount") or 0) for run in runs),
        "runs": runs,
    }


def node_evidence_links_for_node(repo: Any, project_id: str, node_id: int) -> list[dict[str, Any]]:
    return [
        repo.clone(item)
        for item in repo.state.get("node_evidence_links", [])
        if item.get("projectId") == project_id and int(item.get("nodeId") or 0) == int(node_id)
    ]


def set_node_evidence_link_manual_status(
    repo: Any,
    project_id: str,
    node_id: int,
    link_id: str,
    manual_status: str,
    *,
    actor_name: str = "",
    comment: str = "",
) -> dict[str, Any] | None:
    if manual_status not in MANUAL_STATUS_LABELS:
        return None
    link = next(
        (
            item
            for item in repo.state.get("node_evidence_links", [])
            if item.get("projectId") == project_id
            and int(item.get("nodeId") or 0) == int(node_id)
            and str(item.get("id") or "") == str(link_id)
        ),
        None,
    )
    if not link:
        return None
    now = server_time()
    link["manualStatus"] = manual_status
    link["manualStatusLabel"] = MANUAL_STATUS_LABELS[manual_status]
    link["manualUpdatedAt"] = now
    if comment:
        link["manualComment"] = str(comment)[:500]
    elif manual_status != MANUAL_REJECTED:
        link.pop("manualComment", None)
    if manual_status == MANUAL_CONFIRMED:
        link["confirmedByName"] = actor_name or "监检人员"
        link["confirmedAt"] = now
        link.pop("rejectedByName", None)
        link.pop("rejectedAt", None)
    elif manual_status == MANUAL_REJECTED:
        link["rejectedByName"] = actor_name or "监检人员"
        link["rejectedAt"] = now
        link.pop("confirmedByName", None)
        link.pop("confirmedAt", None)
    return repo.clone(link)


def build_node_evidence_readiness(repo: Any, project_id: str, node_id: int) -> dict[str, Any]:
    project = repo.require_project(project_id)
    points = review_points_for_project(repo, project, node_id=node_id)
    links = node_evidence_links_for_node(repo, project_id, node_id)
    links_by_point: dict[str, list[dict[str, Any]]] = {}
    for link in links:
        links_by_point.setdefault(str(link.get("reviewPointId") or ""), []).append(link)

    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    required_count = 0
    satisfied_count = 0
    pending_count = 0
    rejected_count = 0
    for point in points:
        point_id = str(point.get("id") or "")
        point_links = sorted(
            links_by_point.get(point_id, []),
            key=lambda item: float(item.get("confidence") or 0),
            reverse=True,
        )
        confirmed_links = [
            link
            for link in point_links
            if str(link.get("manualStatus") or MANUAL_PENDING) == MANUAL_CONFIRMED
        ]
        rejected_links = [
            link
            for link in point_links
            if str(link.get("manualStatus") or MANUAL_PENDING) == MANUAL_REJECTED
        ]
        pending_links = [
            link
            for link in point_links
            if str(link.get("manualStatus") or MANUAL_PENDING) not in {MANUAL_CONFIRMED, MANUAL_REJECTED}
        ]
        partial_links = [link for link in point_links if link.get("supportStatus") == PARTIAL_STATUS]
        fulfilled = bool(confirmed_links)
        if fulfilled:
            evidence_review_status = MANUAL_STATUS_LABELS[MANUAL_CONFIRMED]
        elif pending_links:
            evidence_review_status = MANUAL_STATUS_LABELS[MANUAL_PENDING]
            pending_count += 1
        elif rejected_links:
            evidence_review_status = MANUAL_STATUS_LABELS[MANUAL_REJECTED]
            rejected_count += 1
        else:
            evidence_review_status = "未找到"
        row = {
            **repo.clone(point),
            "matchedLinkCount": len(point_links),
            "matchedBindingCount": len(point_links),
            "matchedFileNames": sorted({str(link.get("fileName") or "") for link in point_links if link.get("fileName")}),
            "supportStatus": SUPPORTED_STATUS if fulfilled else PARTIAL_STATUS if partial_links or pending_links else UNMATCHED_STATUS,
            "evidenceReviewStatus": evidence_review_status,
            "confirmedLinkCount": len(confirmed_links),
            "pendingLinkCount": len(pending_links),
            "rejectedLinkCount": len(rejected_links),
            "fulfilled": fulfilled,
            "bestConfidence": float(point_links[0].get("confidence") or 0) if point_links else 0,
            "evidenceLinkIds": [link["id"] for link in point_links if link.get("id")],
            "confirmedEvidenceLinkIds": [link["id"] for link in confirmed_links if link.get("id")],
        }
        rows.append(row)
        if point.get("requiredType") != "可选":
            required_count += 1
            if fulfilled:
                satisfied_count += 1
            else:
                missing.append(row)

    missing_count = len(missing)
    progress_percent = round((satisfied_count / required_count) * 100) if required_count else 0
    input_version_ids = sorted({str(link.get("documentVersionId")) for link in links if link.get("documentVersionId")})
    blocking_reasons: list[dict[str, Any]] = []
    if not points:
        blocking_reasons.append(
            {
                "code": "NO_REVIEW_POINTS",
                "message": "当前节点未配置必传审查点，AI 复核将仅生成通用核验或人工确认建议。",
                "severity": "blocker",
            }
        )
    if pending_count:
        blocking_reasons.append(
            {
                "code": "PENDING_EVIDENCE_DECISION",
                "message": "仍有候选证据未确认或不采用，AI 复核将把其作为待确认证据参考。",
                "count": pending_count,
                "severity": "blocker",
            }
        )
    if missing_count:
        blocking_reasons.append(
            {
                "code": "MISSING_REQUIRED_EVIDENCE",
                "message": "仍有必传审查点缺少已确认资料证据，不能形成满足要求类结论。",
                "count": missing_count,
                "severity": "blocker",
            }
        )
    ready_for_gap_precheck = bool(points) and pending_count == 0
    ready_for_ai_formal = ready_for_gap_precheck and missing_count == 0
    return {
        "schemaVersion": "node-evidence-readiness-v1",
        "hasReviewPoints": bool(points),
        "requiredCount": required_count,
        "satisfiedCount": satisfied_count,
        "missingCount": missing_count,
        "pendingCount": pending_count,
        "rejectedCount": rejected_count,
        "progressPercent": progress_percent,
        "evidenceReviewComplete": bool(points) and pending_count == 0,
        "readyForAi": ready_for_ai_formal,
        "readyForAiFormal": ready_for_ai_formal,
        "readyForGapPrecheck": ready_for_gap_precheck,
        "blockingReasons": blocking_reasons,
        "requirements": rows,
        "missingRequirements": missing,
        "nodeEvidenceLinks": links,
        "inputDocumentVersionIds": input_version_ids,
        "supportingDocumentCount": len(input_version_ids),
    }


def targeting_input_versions_for_node(repo: Any, project_id: str, node_id: int) -> list[str]:
    readiness = build_node_evidence_readiness(repo, project_id, node_id)
    if readiness.get("inputDocumentVersionIds"):
        return list(readiness["inputDocumentVersionIds"])
    return [item["documentVersionId"] for item in repo.bindings_for_node(project_id, node_id)]


def targeting_run_snapshot(run: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(run, ensure_ascii=False, default=str))
