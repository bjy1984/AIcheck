"""设计节点（4–9）事实；节点11转交独立的施工方案／设计参数比对构建器。

此前节点 4–11 没有任何事实构建器：AC-R04-01 要的 designDocumentSet、AC-R04-02/03 要的
designDocuments.documents 永远为空，规则只能输出证据不足。这里从本节点输入资料的 OCR 结果构建：

- designDocumentSet：目录对照——图纸目录（drawing_catalog）里列出的文件类型 vs 实际上传的类型
  vs 能解析的类型，交给 check_document_set_completeness 做差集；
- designDocuments.documents：每份设计文件的子类型（管道特性表 / 布置图 / 材料表 / 计算书 …）、
  签字角色（OCR signatures + 文本里的"设计/校核/审核/审定/批准：姓名"）、覆盖的管线号
  （文本与表格里出现的、与 project.pipelines 一致的管线号），供 evaluate_design_document_approval
  按三级/四级会签逐份、逐管线判定。

分类只靠文件名与 OCR 标题关键词，认不出的记 design_document_other 并列进 unclassified，
不猜；四级触发的管线参数来自 pipeline_facts（N-02）。
"""

from __future__ import annotations

import math
import re
from typing import Any

from libs.business_pack import DEFAULT_BUSINESS_PACK_ID, load_business_pack
from libs.regulatory_tables import (
    inspection_level_for_grade,
    medium_hazard_flags,
    pressure_test_ratios,
    volumetric_ndt_ratio,
)
from libs.review_grounding import REGULATION_CODE_RE
from libs.review_input_data import selected_parse_results
from libs.review_orchestrator.certificate_facts import _documents_by_version, _project_record
from libs.review_orchestrator.design_ndt_requirements import (
    design_ndt_requirements,
    method_value_summary,
)
from libs.review_orchestrator.pipeline_facts import build_project_pipelines
from libs.review_orchestrator.pressure_ratio_calculation import pressure_ratio_calculation
from libs.review_orchestrator.r11_facts import build_r11_business_facts
from libs.standard_timeline import standard_reference_fact

DESIGN_FACT_NODES = frozenset({4, 5, 6, 7, 8, 9, 11})

# 子类型关键词表：先匹配的先赢，顺序按"越具体越靠前"
_DESIGN_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("drawing_catalog", ("图纸目录", "文件目录", "设计文件目录", "目录")),
    ("design_specification", ("设计说明", "设计规定", "总说明", "技术规定")),
    ("pipeline_data_sheet", ("管道特性表", "管线特性表", "管道数据表", "管道表")),
    ("pipeline_material_grade_table", ("管道等级表", "材料等级表", "管道材料等级", "等级表")),
    ("pipeline_stress_calculation", ("应力分析", "应力计算", "柔性分析")),
    ("straight_pipe_strength_calculation", ("直管强度计算", "壁厚计算")),
    ("strength_calculation", ("强度计算", "计算书")),
    ("equipment_layout_drawing", ("设备布置图", "设备平面布置")),
    ("pipeline_layout_drawing", ("管道布置图", "管道平面图", "配管图", "轴测图", "单线图", "布置图")),
    ("pipeline_material_list", ("材料表", "材料清单", "综合材料表", "材料汇总")),
    ("design_change_document", ("设计变更", "变更通知", "修改通知单")),
    ("drawing_review_record", ("图纸会审", "施工图审查", "审图")),
)
_ROLE_LABELS = ("设计", "校核", "审核", "审定", "批准", "专业负责", "项目负责")
_ROLE_RE = re.compile(r"(设计|校核|审核|审定|批准)\s*[人:：]\s*([一-龥]{2,4})")
_LINE_NO_RE = re.compile(r"\b[A-Z]{1,4}-?\d{2,5}(?:-[A-Z0-9]{1,6})?\b")
CALCULATION_TYPES = frozenset({"strength_calculation", "straight_pipe_strength_calculation", "pipeline_stress_calculation"})
_PARAM_RES = {
    "designPressureMPa": re.compile(r"设计压力\s*[:：]?\s*(\d+(?:\.\d+)?)\s*MPa?", re.IGNORECASE),
    "designTemperatureC": re.compile(r"设计温度\s*[:：]?\s*(-?\d+(?:\.\d+)?)\s*[℃C]?"),
    "material": re.compile(r"(?:材质|材料牌号|材料)\s*[:：]\s*([A-Za-z0-9#\-]{2,16})"),
    "specification": re.compile(r"(?:规格|公称直径)\s*[:：]?\s*((?:DN|Φ|φ)?\s*\d+(?:[x×*]\d+(?:\.\d+)?)?)"),
}
_ORG_LABEL_RE = re.compile(r"(原设计单位|设计单位|批准单位|变更单位|审批单位)\s*[:：]\s*([一-龥（）()]{4,40}?(?:公司|院|所|中心))")
_DRAWING_NO_RE = re.compile(r"(?:图号|原图号|图纸编号)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-/.]{3,30})")
_APPROVAL_RE = re.compile(r"(同意|批准|准予|审批通过)")


def _text_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("fieldValue") or item.get("value") or "")
    return str(item or "")


def classify_design_document(file_name: str, page_text: str) -> str:
    """文件名优先（人起的名字最准），再看首页文本。"""
    for source in (file_name or "", (page_text or "")[:600]):
        compact = source.replace(" ", "")
        for code, keywords in _DESIGN_TYPE_RULES:
            if any(keyword in compact for keyword in keywords):
                return code
    return "design_document_other"


def _first_page_text(parse_result: dict[str, Any]) -> str:
    fragments = [item for item in parse_result.get("fragments") or [] if isinstance(item, dict)]
    first = [item for item in fragments if int(item.get("pageNo") or 1) == 1] or fragments
    return "\n".join(_text_of(item) for item in first[:80])


def _all_text(parse_result: dict[str, Any]) -> str:
    parts = [_text_of(item) for item in parse_result.get("fragments") or [] if isinstance(item, dict)]
    parts.extend(_text_of(item) for item in parse_result.get("fields") or [] if isinstance(item, dict))
    for table in parse_result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        for row in table.get("normalizedRows") or table.get("rows") or []:
            if isinstance(row, dict):
                parts.append(" ".join(str(value) for value in row.values() if value not in (None, "")))
    return "\n".join(parts)


def signature_roles(parse_result: dict[str, Any]) -> list[str]:
    """OCR 结构化 signatures 的 role 优先；没有就从文本里认"角色：姓名"。"""
    roles: list[str] = []
    for signature in parse_result.get("signatures") or []:
        if isinstance(signature, dict):
            role = str(signature.get("role") or signature.get("signatureRole") or "").strip()
            if role and (signature.get("name") or signature.get("text") or signature.get("present", True)):
                roles.append(role)
    for field in parse_result.get("fields") or []:
        if isinstance(field, dict):
            name = str(field.get("fieldName") or field.get("fieldCode") or "")
            value = str(field.get("fieldValue") or "").strip()
            for label in _ROLE_LABELS:
                if label in name and value:
                    roles.append(label)
    for match in _ROLE_RE.finditer(_all_text(parse_result)):
        roles.append(match.group(1))
    return list(dict.fromkeys(role for role in roles if role))


def covered_pipeline_ids(parse_result: dict[str, Any], known_pipeline_ids: set[str]) -> list[str]:
    """文档里出现且属于本工程管线表的管线号；没有管线表时退回文本里像管线号的编号。"""
    text = _all_text(parse_result)
    found = list(dict.fromkeys(match.group(0) for match in _LINE_NO_RE.finditer(text)))
    if known_pipeline_ids:
        return [item for item in found if item in known_pipeline_ids]
    return found


def catalog_listed_types(parse_result: dict[str, Any]) -> list[str]:
    """图纸目录逐行分类：每行的文件名 → 子类型。"""
    names: list[str] = []
    for table in parse_result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        for row in table.get("normalizedRows") or table.get("rows") or []:
            if isinstance(row, dict):
                names.append(" ".join(str(value) for value in row.values() if value not in (None, "")))
    if not names:
        names = [line for line in _all_text(parse_result).split("\n") if line.strip()]
    listed = [classify_design_document(name, "") for name in names]
    return list(dict.fromkeys(item for item in listed if item not in ("design_document_other", "drawing_catalog")))


def build_design_business_facts(
    state: dict[str, Any],
    review_run: dict[str, Any],
    *,
    known_pipeline_ids: set[str] | None = None,
) -> dict[str, Any]:
    if review_run.get("nodeId") == 11:
        return build_r11_business_facts(state, review_run)
    project_id = str(review_run.get("projectId") or "")
    versions = _documents_by_version(state, project_id)
    pipelines = build_project_pipelines(state, project_id,
                                       review_run=review_run if "documentScopeSnapshot" in review_run else None)
    if known_pipeline_ids is None:
        known_pipeline_ids = {str(item.get("pipelineId")) for item in pipelines if item.get("pipelineId")}
    texts: dict[str, str] = {}
    parse_by_version: dict[str, dict[str, Any]] = {}
    documents: list[dict[str, Any]] = []
    uploaded: list[str] = []
    parseable: list[str] = []
    catalog: list[str] = []
    unclassified: list[dict[str, Any]] = []
    for parse_result in selected_parse_results(state, {}, context={"reviewRun": review_run}):
        version_id = str(parse_result.get("documentVersionId") or "")
        if not version_id or version_id not in versions:
            continue
        document = versions.get(version_id) or {}
        file_name = str(document.get("fileName") or parse_result.get("fileName") or "")
        design_type = classify_design_document(file_name, _first_page_text(parse_result))
        parsed_ok = str(parse_result.get("status") or "success") in {"success", "succeeded", "已识别", "人工修正", ""}
        uploaded.append(design_type)
        if parsed_ok:
            parseable.append(design_type)
        if design_type == "drawing_catalog":
            catalog.extend(catalog_listed_types(parse_result))
        if design_type == "design_document_other":
            unclassified.append({"documentVersionId": version_id, "fileName": file_name})
        roles = signature_roles(parse_result)
        texts[version_id] = _all_text(parse_result)
        parse_by_version[version_id] = parse_result
        page_no = int((next((item for item in parse_result.get("fragments") or [] if isinstance(item, dict)), {}) or {}).get("pageNo") or 1)
        documents.append(
            {
                "documentId": str(document.get("id") or parse_result.get("documentId") or version_id),
                "documentVersionId": version_id,
                "documentType": design_type,
                "materialTypeCode": document.get("materialTypeCode"),
                "fileName": file_name,
                "bodyUploaded": True,
                "parsed": parsed_ok,
                "signatureRoles": roles,
                "sealTexts": [item for item in _seal_texts(parse_result) if item.strip()],
                "coveredPipelineIds": covered_pipeline_ids(parse_result, known_pipeline_ids or set()),
                "evidenceRefs": [{"documentVersionId": version_id, "pageNo": page_no, "quotedText": file_name}],
            }
        )
    return {
        "designDocumentSet": {
            "catalogListedDocumentTypes": list(dict.fromkeys(catalog)),
            "uploadedDocumentTypes": list(dict.fromkeys(uploaded)),
            "parseableDocumentTypes": list(dict.fromkeys(parseable)),
            "unclassified": unclassified,
        },
        "designDocuments": {"documents": documents, "documentCount": len(documents)},
        "calculationDocuments": calculation_documents(documents, texts, pipelines),
        "designChanges": design_changes(documents, parse_by_version, texts, _project_record(state, project_id)),
        # N-16/N-17：设计说明 / 设计规定的四领域要求；没有设计说明时退回全部设计文件正文
        "designSpecialRequirements": design_special_requirements(
            "\n".join(texts[str(item["documentVersionId"])] for item in documents if item.get("documentType") == "design_specification")
            or "\n".join(texts.values()),
            pipelines,
            source={"documentVersionIds": [str(item["documentVersionId"]) for item in documents if item.get("documentType") == "design_specification"]},
        ),
        "fixedClauses": {"designSpecialRequirementRules": frozen_special_requirement_rules(review_run.get("businessPackId"))},
        "drawingReviewWitness": drawing_review_witness(documents, texts, _project_record(state, project_id)),
        "design": design_standard_references(texts, str(_project_record(state, project_id).get("constructionStart") or "")[:10] or None),
        "standardCatalog": {"versionStatus": design_standard_references(texts, None)["versionStatus"]},
    }


def _seal_texts(parse_result: dict[str, Any]) -> list[str]:
    return [
        " ".join(str(seal.get(key) or "") for key in ("sealName", "name", "text", "ownerName"))
        for seal in parse_result.get("seals") or []
        if isinstance(seal, dict)
    ]


def parameter_comparisons(text: str, pipeline: dict[str, Any] | None) -> list[dict[str, Any]]:
    """计算书正文里的设计参数 vs 管道特性表（覆盖管线）的设计参数；两边都有值才比。"""
    if not pipeline:
        return []
    comparisons: list[dict[str, Any]] = []
    for code, pattern in _PARAM_RES.items():
        match = pattern.search(text or "")
        design_value = pipeline.get(code)
        if not match or design_value in (None, ""):
            continue
        document_value = match.group(1).replace(" ", "")
        if code in ("designPressureMPa", "designTemperatureC"):
            comparisons.append({"code": code, "documentValue": document_value, "designValue": design_value, "tolerance": 0.01 if code == "designPressureMPa" else 1})
        else:
            comparisons.append({"code": code, "documentValue": document_value, "designValue": design_value, "normalizer": "text"})
    return comparisons


def _design_org_name(project: dict[str, Any]) -> str:
    for key in ("designOrgName", "designOrganizationName", "designUnitName", "designUnit"):
        value = str(project.get(key) or "").strip()
        if value:
            return value
    return ""


def calculation_documents(documents: list[dict[str, Any]], texts: dict[str, str], pipelines: list[dict[str, Any]]) -> dict[str, Any]:
    """N-10/N-11：计算书按覆盖管线与设计参数比对；覆盖管线集 ⊇ 需计算管线集（GC1/GCD）作 coverage。"""
    by_id = {str(item.get("pipelineId")): item for item in pipelines if item.get("pipelineId")}
    output: list[dict[str, Any]] = []
    covered_all: set[str] = set()
    for document in documents:
        if document.get("documentType") not in CALCULATION_TYPES:
            continue
        text = texts.get(str(document.get("documentVersionId")), "")
        covered = [item for item in document.get("coveredPipelineIds") or []]
        covered_all.update(covered)
        first = by_id.get(covered[0]) if covered else (pipelines[0] if len(pipelines) == 1 else None)
        output.append({**document, "parameterComparisons": parameter_comparisons(text, first)})
    required = [str(item.get("pipelineId")) for item in pipelines if str(item.get("pipelineGrade") or "").upper() in {"GC1", "GCD"}]
    return {
        "documents": output,
        "documentCount": len(output),
        "requiredPipelineIds": required,
        "coveredPipelineIds": sorted(covered_all),
        "uncoveredRequiredPipelineIds": [item for item in required if item not in covered_all],
    }


def design_changes(documents: list[dict[str, Any]], parse_results: dict[str, dict[str, Any]], texts: dict[str, str], project: dict[str, Any]) -> dict[str, Any]:
    """N-12/N-13：设计变更单的书面批准、原设计单位、签字级别、引用原图号是否在设计集合里。"""
    change_docs = [item for item in documents if item.get("documentType") == "design_change_document"]
    all_design_text = "\n".join(texts.get(str(item.get("documentVersionId")), "") for item in documents if item.get("documentType") != "design_change_document")
    design_org = _design_org_name(project)
    output: list[dict[str, Any]] = []
    for document in change_docs:
        version_id = str(document.get("documentVersionId"))
        text = texts.get(version_id, "")
        parse_result = parse_results.get(version_id, {})
        labeled = {label: name for label, name in _ORG_LABEL_RE.findall(text)}
        seals = _seal_texts(parse_result)
        roles = document.get("signatureRoles") or []
        drawing_nos = list(dict.fromkeys(_DRAWING_NO_RE.findall(text)))
        changed_type = classify_design_document("", text.replace("设计变更", "").replace("变更通知", ""))
        output.append(
            {
                **document,
                "changedDocumentType": changed_type if changed_type != "design_change_document" else "design_document_other",
                "writtenApproval": bool(_APPROVAL_RE.search(text)) and (bool({"批准", "审定", "审核"} & set(roles)) or bool(seals)),
                "originalDesignOrganizationName": labeled.get("原设计单位") or design_org or None,
                "approvingOrganizationName": labeled.get("批准单位") or labeled.get("审批单位") or labeled.get("变更单位") or labeled.get("设计单位") or next((seal for seal in seals if "公司" in seal or "院" in seal), None),
                "designLicenseSeal": any("设计许可" in seal or "许可印章" in seal for seal in seals),
                "referencedDrawingNos": drawing_nos,
                "referencedDrawingsFound": [no for no in drawing_nos if no in all_design_text],
                "referencedDrawingsMissing": [no for no in drawing_nos if no not in all_design_text],
            }
        )
    return {"hasDesignChanges": bool(change_docs), "documents": output, "documentCount": len(output)}


# ── N-16/N-17：设计文件上注明的无损检测 / 防腐 / 耐压试验 / 泄漏试验要求 ──────────────
_CORROSION_RE = re.compile(r"(防腐|涂层|涂料|油漆|环氧|喷砂|除锈|镀锌|保温)")
_COATING_CRITERIA_RE = re.compile(r"(涂层厚度\s*[:：]?\s*(?:不小于|≥|>=)?\s*\d+\s*(?:μm|um|微米)|附着力[^\n。；;]{0,20}|除锈等级\s*[:：]?\s*Sa\s*\d(?:\.\d)?)")
_PRESSURE_METHOD_RE = re.compile(r"(液压试验|水压试验|气压试验|气液组合|耐压试验|压力试验)")
_TEST_PRESSURE_RE = re.compile(r"(?:试验压力|耐压试验压力)\s*[:：]?\s*(?:为|取)?\s*(\d+(?:\.\d+)?)\s*MPa", re.IGNORECASE)
_TEST_RATIO_RE = re.compile(r"(?:试验压力|耐压试验压力)[^\n。；;]{0,20}?(\d(?:\.\d+)?)\s*倍")
_PRESSURE_CRITERIA_RE = re.compile(r"(无泄漏|无渗漏|无变形|无异常|保压\s*\d+\s*(?:min|分钟)|压力(?:无|不)下降)")
_LEAK_METHOD_RE = re.compile(r"(泄漏试验|气密性试验|气密试验|泄漏性试验|真空试验|卤素|氦)")
_LEAK_PRESSURE_RE = re.compile(r"(?:泄漏试验压力|气密性?试验压力|泄漏性试验压力)\s*[:：]?\s*(?:为|取)?\s*(\d+(?:\.\d+)?)\s*MPa", re.IGNORECASE)
_LEAK_CRITERIA_RE = re.compile(r"(无泄漏|发泡剂|皂液|压力降\s*[^\n。；;]{0,15}|保压\s*\d+\s*(?:min|分钟))")

_STD_ID_FIXES = {"GB/T": "GBT", "GB": "GB", "NB/T": "NBT", "JB/T": "JBT", "HG/T": "HGT", "SY/T": "SYT", "SH/T": "SHT", "TSG": "TSG"}


def standard_ref_id(code: str) -> str:
    """"GB/T 20801.1-2025" → "STD-GBT-20801.1-2025"，与规则包 standardRef 同一写法。"""
    text = code.strip().upper().replace("—", "-").replace("–", "-")
    match = re.match(r"([A-Z]+(?:/T)?)\s*([A-Z0-9.\-]+)", text)
    if not match:
        return f"STD-{re.sub(r'[^A-Z0-9.]+', '-', text)}"
    prefix = _STD_ID_FIXES.get(match.group(1), match.group(1).replace("/", ""))
    return f"STD-{prefix}-{match.group(2)}"


def _domain(specified: bool, requirements: dict[str, Any], standard_refs: list[str], source: dict[str, Any]) -> dict[str, Any]:
    return {"specified": specified, "requirements": {key: value for key, value in requirements.items() if value not in (None, "")}, "standardRefs": standard_refs, "source": source}


def design_special_requirements(text: str, pipelines: list[dict[str, Any]], *, source: dict[str, Any] | None = None) -> dict[str, Any]:
    """从设计说明/设计规定文本抽四领域要求；数值判定（试验压力倍数）在这里算好，规则只比布尔与存在性。"""
    text = text or ""
    standard_refs = list(dict.fromkeys(standard_ref_id(match.group(0)) for match in REGULATION_CODE_RE.finditer(text)))
    source = source or {}
    max_design_pressure = max((float(item["designPressureMPa"]) for item in pipelines if type(item.get("designPressureMPa")) in (int, float)
                               and math.isfinite(item["designPressureMPa"]) and item["designPressureMPa"] > 0), default=None)

    ndt_details = design_ndt_requirements(text)
    ndt_methods = ndt_details["methods"]
    coverage_pct = ndt_details["coveragePercent"]
    # 按管线级别推缺省检查等级与体积检测比例（GB/T 20801.1-2025 8.3.1 / 表 42）：取本工程最严的一条
    # GC2 的等级看介质：有毒 → Ⅲ、泄漏危害性 → Ⅱ，都比缺省的 Ⅳ 严。
    # 资料没写毒性/泄漏危害性时不按 Ⅳ 一口咬定——那会把比例要求降下来，
    # 而这正是"标准里有、判定拿不到"最容易出错的地方。
    grade_levels = []
    undetermined: list[str] = []
    for item in pipelines:
        grade = str(item.get("pipelineGrade") or "")
        flags = medium_hazard_flags(
            toxicity=item.get("mediumToxicity"),
            leak_hazard=item.get("leakHazard"),
            medium=item.get("medium"),
        )
        if grade.strip().upper() == "GC2" and not flags["determined"]:
            undetermined.append(item.get("pipelineId") or item.get("lineNo") or "未编号管线")
            continue
        grade_levels.append(inspection_level_for_grade(grade.strip(), toxic=flags["toxic"] is True, leak_hazard=flags["leakHazard"] is True))
    level_rank = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5}
    strictest = min((lvl for lvl in grade_levels if lvl), key=lambda lvl: level_rank.get(lvl, 9), default=None)
    required_ratio_pct = volumetric_ndt_ratio(strictest) if not undetermined else None
    required_acceptance = ndt_details["requiredAcceptance"]
    acceptance_ok = ndt_details["acceptanceLevelMeetsRequirement"]
    method_rows = ndt_details["methodRequirements"]
    known_ratios = [row["coveragePercent"] for row in method_rows]
    coverage_ok = all(ratio >= required_ratio_pct for ratio in known_ratios) if required_ratio_pct is not None and known_ratios and all(ratio is not None for ratio in known_ratios) else None
    ndt = _domain(
        bool(ndt_methods and any(row["coveragePercent"] is not None or row["acceptanceLevel"] for row in method_rows)) or bool(re.search(r"无损检测", text) and ndt_methods),
        {
            "method": "、".join(ndt_methods) or None,
            "coverage": method_value_summary(method_rows, "coveragePercent", "%"),
            "coveragePercent": coverage_pct,
            "acceptanceCriteria": method_value_summary(method_rows, "acceptanceLevel", "级"),
            "requiredAcceptanceLevel": required_acceptance.get("level") if required_acceptance else None,
            "requiredAcceptanceTechnique": required_acceptance.get("technique") if required_acceptance else None,
            "acceptanceLevelMeetsRequirement": acceptance_ok,
            "methodRequirements": ndt_details["methodRequirements"],
            "requiredInspectionLevel": strictest,
            "requiredCoveragePercent": required_ratio_pct,
            # 这些 GC2 管线的检查等级取决于介质毒性/泄漏危害性，资料里没写，按缺省 Ⅳ 级算出来的
            # 比例可能偏低——把管线号列出来让人去补，而不是让它悄悄过去
            "inspectionLevelUndeterminedPipelines": undetermined or None,
            "coverageMeetsRequirement": coverage_ok,
        },
        standard_refs,
        source,
    )
    corrosion_methods = list(dict.fromkeys(match.group(1) for match in _CORROSION_RE.finditer(text)))
    coating = _COATING_CRITERIA_RE.search(text)
    corrosion = _domain(bool(corrosion_methods), {"protectionMethod": "、".join(corrosion_methods) or None, "acceptanceCriteria": coating.group(1).strip() if coating else None}, standard_refs, source)

    pressure_method = _PRESSURE_METHOD_RE.search(text)
    test_pressure = _TEST_PRESSURE_RE.search(text)
    ratio = _TEST_RATIO_RE.search(text)
    pressure_criteria = _PRESSURE_CRITERIA_RE.search(text)
    method_text = pressure_method.group(1) if pressure_method else None
    ratios = pressure_test_ratios()  # GB/T 20801.1-2025 8.6.1.3/8.6.1.4：液压 ≥1.5；气压 ≥1.1 且 ≤1.33
    methods = {"hydro" if match.group(1) in {"液压试验", "水压试验"} else match.group(1)
               for match in _PRESSURE_METHOD_RE.finditer(text)
               if match.group(1) not in {"耐压试验", "压力试验"}}
    is_pneumatic = methods == {"气压试验"}
    required_ratio = ratios["pneumatic"] if is_pneumatic else ratios["hydro"] if methods == {"hydro"} else None
    test_pressure_value = float(test_pressure.group(1)) if test_pressure else None
    ratio_value, meets_ratio, exceeds_max = pressure_ratio_calculation(
        ratio.group(1) if ratio else None, test_pressure.group(1) if test_pressure else None,
        max_design_pressure, required_ratio, ratios["pneumaticMax"] if is_pneumatic else None)
    pressure_test = _domain(
        bool(pressure_method or test_pressure),
        {
            "method": method_text,
            "testPressure": f"{test_pressure_value}MPa" if test_pressure_value is not None else (f"{ratio.group(1)}倍设计压力" if ratio else None),
            "testPressureMPa": test_pressure_value,
            "testPressureRatio": ratio_value,
            "requiredTestPressureRatio": required_ratio,
            "testPressureMeetsRatio": meets_ratio,
            # 气压试验有上限：超过 1.33 倍设计压力是不符合，不是"更保险"
            "maxTestPressureRatio": ratios["pneumaticMax"] if is_pneumatic else None,
            "testPressureExceedsMax": exceeds_max,
            "acceptanceCriteria": pressure_criteria.group(1) if pressure_criteria else None,
        },
        standard_refs,
        source,
    )
    leak_method = _LEAK_METHOD_RE.search(text)
    leak_pressure = _LEAK_PRESSURE_RE.search(text)
    leak_criteria = _LEAK_CRITERIA_RE.search(text)
    leak_value = float(leak_pressure.group(1)) if leak_pressure else None
    leak_test = _domain(
        bool(leak_method),
        {
            "method": leak_method.group(1) if leak_method else None,
            "testPressure": f"{leak_value}MPa" if leak_value is not None else None,
            "testPressureMPa": leak_value,
            "designPressureMPa": max_design_pressure,
            "leakPressureNotBelowDesign": (leak_value >= max_design_pressure) if leak_value is not None and max_design_pressure else None,
            "acceptanceCriteria": leak_criteria.group(1) if leak_criteria else None,
        },
        standard_refs,
        source,
    )
    return {"domains": {"ndt": ndt, "corrosion": corrosion, "pressureTest": pressure_test, "leakTest": leak_test}, "standardRefs": standard_refs}


def frozen_special_requirement_rules(business_pack_id: str | None = None) -> dict[str, Any]:
    """规则包 CLAUSE-PKG-R09 里冻结的 designSpecialRequirementRules（N-16）。"""
    pack = load_business_pack(str(business_pack_id or DEFAULT_BUSINESS_PACK_ID))
    for package in pack.get("standardClausePackages") or []:
        if isinstance(package, dict) and str(package.get("sourceRuleId") or "") == "R09":
            rules = package.get("designSpecialRequirementRules")
            return dict(rules) if isinstance(rules, dict) else {}
    return {}


# ── N-08/N-09：施工图审查见证材料 ─────────────────────────────────────────────
_WITNESS_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("review_approval_certificate", ("审查合格书", "审查合格证", "施工图审查合格", "审图合格")),
    ("owner_filing_receipt", ("备案回执", "备案表", "备案证明")),
    ("design_reply", ("设计回复", "回复意见", "修改回复", "答复")),
    ("review_opinion", ("审查意见", "审图意见", "审查报告", "图纸会审")),
)
_REVIEW_DATE_RE = re.compile(r"(?:审查日期|审图日期|审查完成日期|日期)\s*[:：]?\s*(\d{4})[-./年](\d{1,2})[-./月](\d{1,2})")
_ANY_DATE_RE = re.compile(r"(\d{4})[-./年](\d{1,2})[-./月](\d{1,2})")
_PROJECT_NAME_RE = re.compile(r"(?:工程名称|项目名称)\s*[:：]\s*([^\n，,。；;]{4,60})")
_ISSUER_RE = re.compile(r"(?:审查机构|审图机构|出具单位|审查单位)\s*[:：]\s*([一-龥（）()]{4,40}?(?:公司|院|所|中心|站))")
_VERSION_RE = re.compile(r"(?:版次|版本|版号)\s*[:：]?\s*([A-Za-z0-9.]{1,6})")


def _date_from(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text or "")
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def drawing_review_witness(documents: list[dict[str, Any]], texts: dict[str, str], project: dict[str, Any]) -> dict[str, Any]:
    """见证材料事实：类型口径、工程名称一致、审查日期早于开工、图纸版本一致、签章存在。缺的字段留 None 让规则判证据不足。"""
    candidates = []
    for document in documents:
        text = texts.get(str(document.get("documentVersionId")), "")
        head = f"{document.get('fileName') or ''}\n{text[:800]}".replace(" ", "")
        types = [code for code, keywords in _WITNESS_TYPE_RULES if any(keyword in head for keyword in keywords)]
        if document.get("documentType") == "drawing_review_record" and not types:
            types = ["review_opinion"]
        if types:
            candidates.append((document, text, types))
    if not candidates:
        return {"document": None, "witnessTypes": [], "issuer": {}, "signatures": {}, "candidateCount": 0}
    document, text, types = candidates[0]
    all_types = list(dict.fromkeys(code for _, _, codes in candidates for code in codes))
    project_name = str(project.get("name") or project.get("projectName") or "").strip()
    name_in_doc = (_PROJECT_NAME_RE.search(text) or [None, None])[1]
    name_in_doc = name_in_doc.strip() if isinstance(name_in_doc, str) else None
    matches = None
    if project_name and name_in_doc:
        matches = _normalize_name(name_in_doc) == _normalize_name(project_name) or _normalize_name(project_name) in _normalize_name(name_in_doc)
    elif project_name and project_name.replace(" ", "") in text.replace(" ", ""):
        name_in_doc, matches = project_name, True
    review_date = _date_from(text, _REVIEW_DATE_RE) or _date_from(text, _ANY_DATE_RE)
    construction_start = str(project.get("constructionStart") or "").strip()[:10] or None
    before = (review_date <= construction_start) if review_date and construction_start else None
    versions = list(dict.fromkeys(match.group(1) for match in _VERSION_RE.finditer(text)))
    current_versions = list(
        dict.fromkeys(
            match.group(1)
            for item in documents
            if item.get("documentType") not in ("drawing_review_record", "design_document_other")
            for match in _VERSION_RE.finditer(texts.get(str(item.get("documentVersionId")), ""))
        )
    )
    consistent = (set(versions) <= set(current_versions)) if versions and current_versions else None
    issuer_match = _ISSUER_RE.search(text)
    roles = list(document.get("signatureRoles") or [])
    seal_texts = list(document.get("sealTexts") or [])
    return {
        "document": {key: document.get(key) for key in ("documentId", "documentVersionId", "documentType", "fileName", "bodyUploaded", "evidenceRefs")},
        "witnessTypes": all_types,
        "candidateCount": len(candidates),
        "issuer": {
            "name": issuer_match.group(1) if issuer_match else None,
            "projectNameInDocument": name_in_doc,
            "expectedProjectName": project_name or None,
            "projectNameMatches": matches,
        },
        "reviewDate": review_date,
        "constructionStart": construction_start,
        "reviewBeforeConstruction": before,
        "drawingVersions": versions,
        "currentDrawingVersions": current_versions,
        "drawingVersionConsistent": consistent,
        "signatures": {"roles": roles, "sealPresent": bool(seal_texts), "sealTexts": seal_texts},
    }


def _normalize_name(value: str) -> str:
    return re.sub(r"[\s（）()·\-—]", "", value or "")


def design_standard_references(texts: dict[str, str], review_date: str | None) -> dict[str, Any]:
    """N-03：设计文件引用的规范/标准编号 → 本地时间线状态（TSG）；未收录的标为需在线查询。"""
    codes: list[str] = []
    for text in texts.values():
        for match in REGULATION_CODE_RE.finditer(text or ""):
            code = " ".join(match.group(0).split())
            if code not in codes:
                codes.append(code)
    references = [standard_reference_fact(code, review_date) for code in codes]
    return {
        "standardReferences": references,
        "reviewDate": review_date,
        "versionStatus": {item["standardRef"]: item["timelineStatus"] for item in references},
        "requiresOnlineLookup": [item["standardRef"] for item in references if item.get("requiresOnlineLookup")],
    }
