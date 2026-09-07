"""P11 N-06/N-07：设计节点（4–9）的业务事实——设计文件集合与逐份设计文件。

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

import re
from typing import Any

from libs.review_orchestrator.certificate_facts import _documents_by_version

DESIGN_FACT_NODES = frozenset({4, 5, 6, 7, 8, 9})

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
    project_id = str(review_run.get("projectId") or "")
    requested = {str(item) for item in review_run.get("inputDocumentVersionIds") or [] if item}
    versions = _documents_by_version(state, project_id)
    documents: list[dict[str, Any]] = []
    uploaded: list[str] = []
    parseable: list[str] = []
    catalog: list[str] = []
    unclassified: list[dict[str, Any]] = []
    for parse_result in state.get("ocr_parse_results") or []:
        if not isinstance(parse_result, dict):
            continue
        version_id = str(parse_result.get("documentVersionId") or "")
        if not version_id or version_id not in versions or (requested and version_id not in requested):
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
    }
