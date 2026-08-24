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


def evidence_link_is_locatable(link: dict[str, Any]) -> bool:
    bbox = link.get("bbox")
    try:
        bbox_valid = (
            isinstance(bbox, (list, tuple))
            and len(bbox) >= 4
            and float(bbox[2]) > float(bbox[0])
            and float(bbox[3]) > float(bbox[1])
        )
    except (TypeError, ValueError):
        bbox_valid = False
    return bool(
        link.get("documentVersionId")
        and link.get("pageNo") is not None
        and bbox_valid
        and str(link.get("quotedText") or link.get("fieldName") or "").strip()
    )


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
    return max(results, key=lambda item: str(item.get("finishedAt") or item.get("createdAt") or ""))


def review_points_for_project(repo: Any, project: dict[str, Any] | None, node_id: int | None = None) -> list[dict[str, Any]]:
    business_pack_id = (project or {}).get("businessPackId") or "engineering_inspection_v1"
    # 先按条件筛，再克隆。原先是全量克隆之后才按 nodeId 过滤——审计项总览
    # 逐个节点调这个函数，等于把整张审查要点表深拷贝 69 遍再各扔掉 68/69。
    # cProfile 里它占 3.96s / 8.85s。
    matched = [
        item
        for item in repo.state.get("admin_config", {}).get("materialReviewPoints", [])
        if item.get("enabled", True)
        and str(item.get("businessPackId") or business_pack_id) == str(business_pack_id)
        and (node_id is None or int(item.get("nodeId") or 0) == int(node_id))
    ]
    return [repo.clone(item) for item in matched]


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


METADATA_FIELD_NAMES = {
    "资料类型",
    "OCR分类依据",
    "页数",
    "文件名",
    "文档分类",
    "知识类型",
}
STRICT_POINT_SOURCE_TYPES = {
    "design_document",
    "design_license",
    "construction_license",
    "manufacturing_license",
}


def document_material_type_codes(document: dict[str, Any]) -> set[str]:
    codes = {
        str(value).strip()
        for value in document.get("materialTypeLabels") or []
        if str(value).strip()
    }
    primary = str(document.get("materialTypeCode") or "").strip()
    if primary:
        codes.add(primary)
    return codes


def valid_evidence_bbox(value: Any) -> bool:
    try:
        return bool(
            isinstance(value, (list, tuple))
            and len(value) >= 4
            and float(value[2]) > float(value[0])
            and float(value[3]) > float(value[1])
        )
    except (TypeError, ValueError):
        return False


def point_source_is_allowed(point: dict[str, Any], document: dict[str, Any]) -> tuple[bool, str | None]:
    expected = str(point.get("materialTypeCode") or "").strip()
    declared = str(document.get("materialTypeCode") or "").strip()
    if expected in STRICT_POINT_SOURCE_TYPES and expected not in document_material_type_codes(document):
        return False, f"资料来源类型不符合审查点：需要 {expected}，实际为 {declared or '未声明'}"
    return True, None


def evidence_fact_targets(point: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    def add(
        code: str,
        label: str,
        source_item: str,
        *,
        field_names: tuple[str, ...],
        terms: tuple[str, ...],
    ) -> None:
        if code in seen_codes:
            return
        seen_codes.add(code)
        targets.append(
            {
                "targetCode": code,
                "targetName": label,
                "sourceEvidenceItem": source_item,
                "fieldNames": list(field_names),
                "matchTerms": list(dict.fromkeys(normalized_text(item) for item in terms if normalized_text(item))),
            }
        )

    material_type_code = str(point.get("materialTypeCode") or "")
    for index, raw_item in enumerate(point.get("evidenceItems") or [], start=1):
        item = str(raw_item or "").strip()
        normalized = normalized_text(item)
        recognized = False
        if "机构名称" in normalized or "单位名称" in normalized:
            recognized = True
            add(
                "designer_name" if int(point.get("nodeId") or 0) == 1 else "organization_name",
                "设计单位名称" if int(point.get("nodeId") or 0) == 1 else "单位名称",
                item,
                field_names=("设计许可证机构名称", "机构名称", "单位名称", "设计单位名称"),
                terms=("机构名称", "单位名称", "设计单位名称", "设计院", "设计公司"),
            )
        if "证书编号" in normalized or "许可证编号" in normalized:
            recognized = True
            add(
                "license_number",
                "许可证编号",
                item,
                field_names=("证书编号", "许可证编号", "许可证号"),
                terms=("证书编号", "许可证编号", "许可证号", "资质证书编号"),
            )
        if "许可范围" in normalized:
            recognized = True
            add(
                "license_scope",
                "许可范围",
                item,
                field_names=("许可范围", "许可项目", "许可子项目"),
                terms=("许可范围", "许可项目", "许可子项目", "获准从事", "工业管道"),
            )
        if "许可级别" in normalized:
            recognized = True
            add(
                "license_level",
                "许可级别",
                item,
                field_names=("许可级别", "类别级别"),
                terms=("许可级别", "类别级别", "GC1", "GC2", "GCD"),
            )
        if "有效期" in normalized:
            recognized = True
            add(
                "license_validity",
                "许可证有效期",
                item,
                field_names=("有效期", "有效期至", "生效日期", "到期日期"),
                terms=("有效期", "有效期至", "生效日期", "到期日期"),
            )
        if "印章" in normalized:
            recognized = True
            add(
                "design_seal",
                "设计印章",
                item,
                field_names=("印章", "设计印章", "印章单位名称"),
                terms=("设计印章", "印章单位名称", "印章"),
            )
        if "图号" in normalized:
            recognized = True
            add(
                "drawing_number",
                "图号",
                item,
                field_names=("图号", "设计图号"),
                terms=("图号", "设计图号"),
            )
        if "项目名称" in normalized or "工程名称" in normalized:
            recognized = True
            add(
                "project_name",
                "项目名称",
                item,
                field_names=("项目名称", "工程名称"),
                terms=("项目名称", "工程名称"),
            )
        if "施工范围" in normalized and "许可范围" not in normalized:
            recognized = True
            add(
                "design_scope",
                "设计施工范围",
                item,
                field_names=("施工范围", "项目范围", "工程内容"),
                terms=("施工范围", "项目范围", "工程内容", "卸车管线", "设计范围"),
            )
        if (
            "管道类别" in normalized
            or "管道级别" in normalized
            or (normalized == "级别" and "license" not in material_type_code)
        ):
            recognized = True
            add(
                "pipeline_class",
                "管道类别/级别",
                item,
                field_names=("管道类别", "管道级别", "压力管道级别"),
                terms=("管道类别", "管道级别", "压力管道级别", "GC1", "GC2", "GCD"),
            )
        if "设计压力" in normalized:
            recognized = True
            add(
                "design_pressure",
                "设计压力",
                item,
                field_names=("设计压力",),
                terms=("设计压力", "工作压力"),
            )
        if "温度" in normalized:
            recognized = True
            add(
                "design_temperature",
                "设计温度",
                item,
                field_names=("设计温度", "温度"),
                terms=("设计温度", "工作温度"),
            )
        if "开始日期" in normalized or "开工日期" in normalized:
            recognized = True
            add(
                "construction_start",
                "计划开工日期",
                item,
                field_names=("开始日期", "开工日期", "施工计划工期", "安装工期"),
                terms=("开始日期", "开工日期", "进场", "工期目标"),
            )
        if "结束日期" in normalized or "竣工日期" in normalized:
            recognized = True
            add(
                "construction_end",
                "计划竣工日期",
                item,
                field_names=("结束日期", "竣工日期", "施工计划工期", "安装工期"),
                terms=("结束日期", "竣工日期", "竣工验收", "完工", "工期目标"),
            )
        if "工期" in normalized and "开始日期" not in normalized and "结束日期" not in normalized:
            recognized = True
            add(
                "construction_period",
                "施工计划工期",
                item,
                field_names=("施工计划工期", "安装工期", "工期"),
                terms=("工期目标", "施工工期", "开工", "进场", "竣工", "完工"),
            )
        if not recognized:
            add(
                f"evidence_{stable_short_id(point.get('id'), index, item, length=10).lower()}",
                item,
                item,
                field_names=(item,),
                terms=tuple(keyword_variants(item)),
            )
    return targets


def generic_excerpt_text(text: Any, point: dict[str, Any], document: dict[str, Any]) -> bool:
    normalized = normalized_text(text)
    if not normalized:
        return True
    generic_values = {
        normalized_text(point.get("materialTypeCode")),
        normalized_text(point.get("materialTypeName")),
        normalized_text(point.get("materialCategory")),
        normalized_text(document.get("materialTypeCode")),
        normalized_text(document.get("materialCategory")),
        normalized_text(document.get("fileName")),
    }
    generic_values.discard("")
    return normalized in generic_values or normalized.startswith(("主类型命中", "视觉抽检确认"))


def target_text_contains_fact(target: dict[str, Any], text: Any) -> bool:
    raw = str(text or "").strip()
    normalized = normalized_text(raw)
    code = str(target.get("targetCode") or "")
    if not normalized:
        return False
    if code in {"designer_name", "organization_name"}:
        if code == "designer_name":
            return bool(
                re.search(r"(?:设计单位名称|单位名称|机构名称)[:：\s]*[^；,，]{0,60}(?:设计院|设计公司|设计研究院)", raw)
                or re.search(r"[\u4e00-\u9fff]{2,}(?:设计院|设计公司|设计研究院)", raw)
            )
        return bool(
            re.search(r"(?:单位名称|机构名称)[:：\s]*[^；,，]{4,80}", raw)
            or re.search(r"[\u4e00-\u9fff]{2,}(?:设计院|设计公司|工程公司|有限公司)", raw)
        )
    if code == "license_number":
        return bool(re.search(r"(?:资质证书|许可(?:证)?|证书)(?:编号|号)[:：\s]*[A-Z0-9\-]{5,}", raw, flags=re.IGNORECASE))
    if code == "license_scope":
        return bool(re.search(r"(?:许可范围|许可项目|获准从事|工业管道).{0,100}(?:GC1|GC2|GCD|压力管道|工业管道)", raw, flags=re.IGNORECASE))
    if code == "license_level":
        return bool(re.search(r"(?:许可级别|类别级别).{0,50}(?:GC1|GC2|GCD|GA|GB)", raw, flags=re.IGNORECASE))
    if code == "license_validity":
        return bool(re.search(r"(?:有效期|有效期至|生效日期|到期日期).{0,30}(?:19|20)\d{2}", raw))
    if code == "design_seal":
        return "印章" in normalized or "设计专用章" in normalized
    if code == "drawing_number":
        return bool(
            re.search(r"(?:图号|设计图号|DWG\.?\s*NO\.?).{0,30}(?=[A-Z0-9_—\-]*\d)[A-Z0-9][A-Z0-9_—\-]{4,}", raw, flags=re.IGNORECASE)
            or re.search(r"\b(?:QX|WK)\d{4,}[A-Z0-9_—\-]*\b", raw, flags=re.IGNORECASE)
        )
    if code == "project_name":
        match = re.search(r"(?:项目名称|工程名称)[:：\s；]*([^；\n]{4,120})", raw)
        return bool(match and re.search(r"项目|工程|站|厂|库|公司|装置|管线", match.group(1)))
    if code == "design_scope":
        return bool(re.search(r"(?:施工范围|项目范围|工程内容|设计范围|卸车管线).{2,160}", raw))
    if code == "pipeline_class":
        return bool(re.search(r"(?:GC1|GC2|GCD)", raw, flags=re.IGNORECASE))
    if code == "design_pressure":
        return bool(re.search(r"(?:设计压力|工作压力).{0,30}\d+(?:\.\d+)?\s*(?:MPa|kPa|Pa)", raw, flags=re.IGNORECASE))
    if code == "design_temperature":
        return bool(re.search(r"(?:设计温度|工作温度).{0,30}-?\d+(?:\.\d+)?\s*(?:℃|°C|C)", raw, flags=re.IGNORECASE))
    if code in {"construction_start", "construction_end", "construction_period"}:
        return bool(
            re.search(r"(?:工期|开工|进场|竣工|完工|验收).{0,80}(?:19|20)\d{2}[年\-/]", raw)
            or re.search(r"(?:19|20)\d{2}年\d{1,2}月\d{1,2}日.{0,80}(?:开工|进场|竣工|完工|验收)", raw)
        )
    terms = [normalized_text(item) for item in target.get("matchTerms") or []]
    return any(term and term in normalized for term in terms)


def target_match_score(target: dict[str, Any], field_name: Any, text: Any) -> int:
    normalized_field = normalized_text(field_name)
    field_names = [normalized_text(item) for item in target.get("fieldNames") or []]
    if normalized_field and any(
        normalized_field == expected or normalized_field in expected or expected in normalized_field
        for expected in field_names
        if expected
    ) and target_text_contains_fact(target, text):
        return 70
    if target_text_contains_fact(target, text):
        return 40
    return 0


def union_bboxes(values: list[Any]) -> list[float] | None:
    boxes = [value for value in values if valid_evidence_bbox(value)]
    if not boxes:
        return None
    return [
        min(float(item[0]) for item in boxes),
        min(float(item[1]) for item in boxes),
        max(float(item[2]) for item in boxes),
        max(float(item[3]) for item in boxes),
    ]


def fragment_excerpt(
    fragments: list[dict[str, Any]],
    index: int,
    *,
    point: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    fragment = fragments[index]
    text = str(fragment.get("text") or "").strip()
    page_no = int(fragment.get("pageNo") or 1)
    selected = [fragment]
    if len(normalized_text(text)) < 12 or generic_excerpt_text(text, point, document):
        for adjacent_index in (index - 1, index + 1):
            if 0 <= adjacent_index < len(fragments):
                adjacent = fragments[adjacent_index]
                if int(adjacent.get("pageNo") or 1) == page_no and str(adjacent.get("text") or "").strip():
                    selected.append(adjacent)
        selected.sort(key=lambda item: fragments.index(item))
        text = "；".join(dict.fromkeys(str(item.get("text") or "").strip() for item in selected if str(item.get("text") or "").strip()))
    return {
        "quotedText": text[:500],
        "pageNo": page_no,
        "bbox": union_bboxes([item.get("bbox") for item in selected]),
        "confidence": min(
            [float(item.get("confidence") or 0) for item in selected if item.get("confidence") is not None]
            or [0.0]
        ),
        "fieldName": "OCR文本",
        "fieldId": None,
        "sourceType": "fragment",
        "sourceFragmentIds": [item.get("id") for item in selected if item.get("id")],
    }


def evidence_facts_for_point(
    point: dict[str, Any],
    document: dict[str, Any],
    parse_result: dict[str, Any] | None,
    fields: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    targets = evidence_fact_targets(point)
    fragments = [item for item in (parse_result or {}).get("fragments") or [] if isinstance(item, dict)]
    seals = [item for item in (parse_result or {}).get("seals") or [] if isinstance(item, dict)]
    facts: list[dict[str, Any]] = []
    for target in targets:
        candidates: list[dict[str, Any]] = []
        for field in fields:
            field_name = str(field.get("fieldName") or "").strip()
            field_value = str(field.get("fieldValue") or "").strip()
            if not field_value or field_name in METADATA_FIELD_NAMES:
                continue
            match_score = target_match_score(target, field_name, f"{field_name} {field_value}")
            if not match_score or generic_excerpt_text(field_value, point, document):
                continue
            bbox = field.get("bbox")
            quoted_text = f"{field_name}：{field_value}"[:500]
            candidates.append(
                {
                    "quotedText": quoted_text,
                    "pageNo": int(field.get("pageNo") or 1),
                    "bbox": bbox,
                    "confidence": float(field.get("confidence") or 0),
                    "fieldName": field_name,
                    "fieldId": field.get("id"),
                    "sourceType": "field",
                    "sourceFragmentIds": [field.get("sourceFragmentId")] if field.get("sourceFragmentId") else [],
                    "selectionScore": match_score + (35 if valid_evidence_bbox(bbox) else 0) + min(10, round(float(field.get("confidence") or 0) * 10)),
                }
            )
        for index, fragment in enumerate(fragments):
            text = str(fragment.get("text") or "").strip()
            match_score = target_match_score(target, "OCR文本", text)
            if not match_score or generic_excerpt_text(text, point, document):
                continue
            excerpt = fragment_excerpt(fragments, index, point=point, document=document)
            excerpt["selectionScore"] = match_score + (35 if valid_evidence_bbox(excerpt.get("bbox")) else 0) + min(10, round(float(excerpt.get("confidence") or 0) * 10))
            candidates.append(excerpt)
        if target["targetCode"] == "design_seal":
            for seal in seals:
                text = str(seal.get("text") or seal.get("sealText") or seal.get("sealName") or "").strip()
                if not text:
                    continue
                bbox = seal.get("bbox")
                candidates.append(
                    {
                        "quotedText": text[:500],
                        "pageNo": int(seal.get("pageNo") or 1),
                        "bbox": bbox,
                        "confidence": float(seal.get("confidence") or 0),
                        "fieldName": "印章",
                        "fieldId": seal.get("id"),
                        "sourceType": "seal",
                        "sourceFragmentIds": [],
                        "selectionScore": 80 + (35 if valid_evidence_bbox(bbox) else 0),
                    }
                )
        if not candidates:
            continue
        candidates.sort(
            key=lambda item: (
                int(item.get("selectionScore") or 0),
                len(str(item.get("quotedText") or "")),
            ),
            reverse=True,
        )
        selected = candidates[0]
        selected.update(
            {
                "targetCode": target["targetCode"],
                "targetName": target["targetName"],
                "sourceEvidenceItem": target["sourceEvidenceItem"],
                "formalEvidenceEligible": bool(
                    selected.get("pageNo") is not None
                    and valid_evidence_bbox(selected.get("bbox"))
                    and str(selected.get("quotedText") or "").strip()
                ),
            }
        )
        facts.append(selected)
    facts.sort(
        key=lambda item: (
            bool(item.get("formalEvidenceEligible")),
            int(item.get("selectionScore") or 0),
        ),
        reverse=True,
    )
    return facts, targets


def repo_safe_fact(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in fact.items()
        if key
        in {
            "targetCode",
            "targetName",
            "sourceEvidenceItem",
            "quotedText",
            "pageNo",
            "bbox",
            "confidence",
            "fieldName",
            "fieldId",
            "sourceType",
            "sourceFragmentIds",
            "formalEvidenceEligible",
        }
    }


CONDITIONAL_POINT_CONTEXT_GATES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("境外",), ("境外", "国外", "进口", "overseas", "foreign")),
    (("新材料",), ("新材料", "新型材料", "首次采用", "首次使用")),
    (("穿跨越",), ("穿跨越", "穿越", "跨越")),
    (("替代性试验",), ("替代性试验", "替代试验")),
    (("采用其他标准",), ("采用其他标准", "其他标准", "符合性申明", "比照表")),
)


def point_context_gate(point: dict[str, Any], fulltext: str) -> tuple[bool, str | None]:
    point_text = normalized_text(
        " ".join(
            str(point.get(key) or "")
            for key in ("nodeName", "reviewContent", "fileContent", "mappingRelation")
        )
    )
    for gate_terms, evidence_terms in CONDITIONAL_POINT_CONTEXT_GATES:
        normalized_gate_terms = [normalized_text(item) for item in gate_terms]
        if not contains_any(point_text, normalized_gate_terms):
            continue
        normalized_evidence_terms = [normalized_text(item) for item in evidence_terms]
        if not contains_any(fulltext, normalized_evidence_terms):
            return False, f"未命中条件上下文：{'/'.join(gate_terms)}"
    return True, None


def material_type_matches_point(point: dict[str, Any], document: dict[str, Any], fulltext: str) -> tuple[int, str | None]:
    material_type_code = str(point.get("materialTypeCode") or "")
    material_type_name = str(point.get("materialTypeName") or "")
    material_category = str(point.get("materialCategory") or "")
    declared_type = str(document.get("materialTypeCode") or "")
    declared_types = document_material_type_codes(document)
    declared_category = " ".join(
        [
            str(document.get("materialCategory") or ""),
            *(str(value) for value in document.get("materialCategoryLabels") or []),
        ]
    )
    material_keywords = keyword_variants(material_type_code) + keyword_variants(material_type_name)
    if material_type_code and material_type_code in declared_types:
        return 35, "标准资料类型一致"
    if material_type_code == "construction_schedule" and (
        "construction_organization_design" in declared_types
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


def material_type_is_binding_compatible(point: dict[str, Any], document: dict[str, Any]) -> bool:
    """自动挂载只认最终类型或明确兼容关系；OCR中提到某类型只作诊断。"""
    expected = str(point.get("materialTypeCode") or "").strip()
    declared = str(document.get("materialTypeCode") or "").strip()
    if expected and expected in document_material_type_codes(document):
        return True
    return expected == "construction_schedule" and "construction_organization_design" in document_material_type_codes(document)


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
    declared_categories = {
        str(value).strip()
        for value in [document.get("materialCategory"), *(document.get("materialCategoryLabels") or [])]
        if str(value or "").strip()
    }
    category_fallback = bool(
        document.get("classificationTargetingMode") == "category_advisory"
        and str(point.get("materialCategory") or "").strip() in declared_categories
    )

    source_allowed, source_reason = (True, None) if category_fallback else point_source_is_allowed(point, document)
    if not source_allowed:
        return {
            "reviewPointId": point.get("id"),
            "nodeId": int(point.get("nodeId") or 0),
            "score": 0,
            "confidence": 0.0,
            "supportStatus": UNMATCHED_STATUS,
            "matchedEvidenceItems": [],
            "evidenceCoverage": 0.0,
            "reasons": [source_reason] if source_reason else [],
            "evidenceFacts": [],
            "formalEvidenceFacts": [],
            "formalEvidenceEligible": False,
            "evidenceTier": "advisory",
            "bindingEligible": False,
            "excerpt": {"quotedText": "", "pageNo": 1, "bbox": None, "fieldName": None, "fieldId": None},
        }

    context_allowed, context_reason = (True, None) if category_fallback else point_context_gate(point, fulltext)
    if not context_allowed:
        return {
            "reviewPointId": point.get("id"),
            "nodeId": int(point.get("nodeId") or 0),
            "score": 0,
            "confidence": 0.0,
            "supportStatus": UNMATCHED_STATUS,
            "matchedEvidenceItems": [],
            "evidenceCoverage": 0.0,
            "reasons": [context_reason] if context_reason else [],
            "bindingEligible": False,
            "excerpt": {"quotedText": "", "pageNo": 1, "bbox": None, "fieldName": None, "fieldId": None},
        }

    score = 0
    reasons: list[str] = []
    material_score, material_reason = material_type_matches_point(point, document, fulltext)
    if material_score:
        score += material_score
        if material_reason:
            reasons.append(material_reason)

    evidence_facts, evidence_targets = evidence_facts_for_point(
        point,
        document,
        parse_result,
        extracted_fields,
    )
    if category_fallback and not evidence_facts:
        fallback_excerpt = best_excerpt(parse_result, extracted_fields, [])
        if str(fallback_excerpt.get("quotedText") or "").strip():
            evidence_facts = [
                {
                    **fallback_excerpt,
                    "targetCode": "category_advisory",
                    "targetName": str(point.get("materialCategory") or "资料大类候选"),
                    "sourceEvidenceItem": "资料大类候选",
                    "sourceType": "category_classification",
                    "sourceFragmentIds": [],
                    "formalEvidenceEligible": False,
                }
            ]
    if category_fallback:
        evidence_facts = [{**item, "formalEvidenceEligible": False} for item in evidence_facts]
    matched_target_codes = {str(item.get("targetCode") or "") for item in evidence_facts if item.get("targetCode")}
    matched_evidence = list(
        dict.fromkeys(
            str(item.get("sourceEvidenceItem") or "")
            for item in evidence_facts
            if str(item.get("sourceEvidenceItem") or "").strip()
        )
    )
    evidence_coverage = len(matched_target_codes) / len(evidence_targets) if evidence_targets else 0.0
    if evidence_targets:
        score += round(35 * evidence_coverage)
        if matched_target_codes:
            reasons.append(f"定位 {len(matched_target_codes)}/{len(evidence_targets)} 个事实目标")

    field_hits = len([item for item in evidence_facts if item.get("sourceType") == "field"])
    if field_hits:
        score += min(15, field_hits * 3)
        reasons.append(f"结构化事实命中 {field_hits} 项")

    if str(point.get("responsibleParty") or "") == document_party(document):
        score += 10
        reasons.append("上传责任方一致")

    material_category = str(point.get("materialCategory") or "")
    if material_category and material_category in str(document.get("fileName") or ""):
        score += 5
        reasons.append("文件名命中资料大类")

    bound_node_ids = {int(item) for item in context.get("boundNodeIds") or [] if str(item).isdigit()}
    if int(point.get("nodeId") or 0) in bound_node_ids:
        score += 25
        reasons.append("人工挂载节点一致")

    responsible_party_matches = str(point.get("responsibleParty") or "") == document_party(document)
    score = min(score, 100)
    confidence = round(score / 100, 4)
    formal_facts = (
        []
        if category_fallback
        else [item for item in evidence_facts if item.get("formalEvidenceEligible") is True]
    )
    deterministic_match = bool(
        not category_fallback
        and
        material_type_is_binding_compatible(point, document)
        and material_score > 0
        and evidence_facts
        and responsible_party_matches
    )
    support_status = (
        SUPPORTED_STATUS
        if deterministic_match
        else PARTIAL_STATUS
        if category_fallback and evidence_facts
        else UNMATCHED_STATUS
    )
    binding_eligible = bool(deterministic_match and formal_facts)
    excerpt = repo_safe_fact(formal_facts[0] if formal_facts else evidence_facts[0] if evidence_facts else {})
    return {
        "reviewPointId": point.get("id"),
        "nodeId": int(point.get("nodeId") or 0),
        "score": score,
        "confidence": confidence,
        "supportStatus": support_status,
        "matchedEvidenceItems": matched_evidence,
        "evidenceCoverage": round(evidence_coverage, 4),
        "reasons": reasons,
        "evidenceFacts": [repo_safe_fact(item) for item in evidence_facts],
        "formalEvidenceFacts": [repo_safe_fact(item) for item in formal_facts],
        "formalEvidenceEligible": bool(formal_facts),
        "evidenceTier": "formal" if formal_facts else "advisory",
        "bindingEligible": binding_eligible,
        "categoryFallback": category_fallback,
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
    auto_binding_id = f"BIND-AUTO-{stable_short_id(project_id, node_id, version_id, length=10)}"
    existing = next(
        (
            item
            for item in repo.state.get("bindings", [])
            if item.get("id") == auto_binding_id
            and item.get("source") == "material_targeting"
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
        "id": auto_binding_id,
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
        "actions": ["submission:submit"],
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
    evidence_facts = [
        {
            **fact,
            "documentId": document["id"],
            "documentVersionId": version_id,
            "fileName": document.get("fileName"),
        }
        for fact in match.get("evidenceFacts") or []
        if isinstance(fact, dict)
    ]
    category_fallback = bool(match.get("categoryFallback"))
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
        "evidenceFacts": evidence_facts,
        "formalEvidenceFactCount": len([item for item in evidence_facts if item.get("formalEvidenceEligible") is True]),
        "formalEvidenceEligible": bool(match.get("formalEvidenceEligible")),
        "evidenceTier": match.get("evidenceTier") or "advisory",
        "categoryFallback": category_fallback,
        "manualStatus": MANUAL_PENDING if category_fallback else MANUAL_CONFIRMED,
        "manualStatusLabel": MANUAL_STATUS_LABELS[MANUAL_PENDING if category_fallback else MANUAL_CONFIRMED],
        **(
            {}
            if category_fallback
            else {"confirmedByName": "系统自动打靶", "confirmedAt": server_time()}
        ),
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
    context["boundNodeIds"] = sorted(
        {
            int(item.get("nodeId") or 0)
            for item in repo.state.get("bindings", [])
            if item.get("projectId") == project_id
            and item.get("documentVersionId") == version_id
            and int(item.get("nodeId") or 0) > 0
        }
    )
    has_ocr_artifacts = bool(
        parse_result
        and str(parse_result.get("status") or "").lower() in {"success", "succeeded", "completed"}
        and any(
            isinstance(parse_result.get(key), list) and bool(parse_result.get(key))
            for key in ("fields", "fragments", "tables", "seals")
        )
    )
    if not has_ocr_artifacts:
        waiting_run = {
            "id": f"MTR-{uuid4().hex[:10].upper()}",
            "projectId": project_id,
            "documentId": document_id,
            "documentVersionId": version_id,
            "status": "awaiting_ocr_evidence",
            "triggeredBy": triggered_by,
            "candidateCount": 0,
            "createdLinkCount": 0,
            "createdBindingCount": 0,
            "createdLinks": [],
            "createdBindings": [],
            "reason": "A successful OCR parse result with evidence artifacts is required before targeting.",
            "createdAt": server_time(),
        }
        repo.state.setdefault("material_targeting_runs", []).insert(0, waiting_run)
        return waiting_run
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
        if (
            candidate["supportStatus"] == UNMATCHED_STATUS
            or not candidate.get("evidenceFacts")
        ):
            continue
        link = node_evidence_link_from_match(project_id, point, document, str(version_id), candidate)
        if link["id"] in previous_manual_state:
            link.update(previous_manual_state[link["id"]])
        repo.state.setdefault("node_evidence_links", []).insert(0, link)
        created_links.append(link)
        if not candidate.get("categoryFallback"):
            touched_nodes.add(int(point.get("nodeId") or 0))
        if auto_bind and candidate.get("bindingEligible") is True:
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
        "createdFormalLinkCount": len([item for item in created_links if item.get("formalEvidenceEligible") is True]),
        "createdAdvisoryLinkCount": len([item for item in created_links if item.get("formalEvidenceEligible") is not True]),
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
    all_links = node_evidence_links_for_node(repo, project_id, node_id)
    links = [
        item
        for item in all_links
        if item.get("formalEvidenceEligible") is True or "formalEvidenceEligible" not in item
    ]
    advisory_links = [
        item
        for item in all_links
        if item.get("formalEvidenceEligible") is not True and "formalEvidenceEligible" in item
    ]
    links_by_point: dict[str, list[dict[str, Any]]] = {}
    for link in links:
        links_by_point.setdefault(str(link.get("reviewPointId") or ""), []).append(link)

    bindings_by_point: dict[str, list[dict[str, Any]]] = {}
    for binding in repo.state.get("bindings", []):
        if binding.get("projectId") != project_id or int(binding.get("nodeId") or 0) != int(node_id):
            continue
        review_point_ids = {
            str(item).strip()
            for item in binding.get("reviewPointIds") or []
            if str(item).strip()
        }
        requirement_id = str(binding.get("requirementId") or "").strip()
        if requirement_id:
            review_point_ids.add(requirement_id)
        for point_id in review_point_ids:
            bindings_by_point.setdefault(point_id, []).append(binding)

    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    required_count = 0
    satisfied_count = 0
    pending_count = 0
    rejected_count = 0
    unlocatable_confirmed_count = 0
    for point in points:
        point_id = str(point.get("id") or "")
        point_links = sorted(
            links_by_point.get(point_id, []),
            key=lambda item: float(item.get("confidence") or 0),
            reverse=True,
        )
        point_bindings = bindings_by_point.get(point_id, [])
        all_confirmed_links = [
            link
            for link in point_links
            if str(link.get("manualStatus") or MANUAL_PENDING) == MANUAL_CONFIRMED
        ]
        confirmed_links = [link for link in all_confirmed_links if evidence_link_is_locatable(link)]
        unlocatable_confirmed_links = [
            link for link in all_confirmed_links if not evidence_link_is_locatable(link)
        ]
        unlocatable_confirmed_count += len(unlocatable_confirmed_links)
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
        elif unlocatable_confirmed_links:
            evidence_review_status = "已确认但不可定位"
        elif pending_links:
            evidence_review_status = MANUAL_STATUS_LABELS[MANUAL_PENDING]
            pending_count += 1
        elif rejected_links:
            evidence_review_status = MANUAL_STATUS_LABELS[MANUAL_REJECTED]
            rejected_count += 1
        elif point_bindings:
            evidence_review_status = "已挂载待定位"
        else:
            evidence_review_status = "未找到"
        row = {
            **repo.clone(point),
            "matchedLinkCount": len(point_links),
            "matchedBindingCount": len(point_bindings),
            "matchedBindingIds": [binding["id"] for binding in point_bindings if binding.get("id")],
            "matchedFileNames": sorted(
                {
                    str(item.get("fileName") or "")
                    for item in [*point_bindings, *point_links]
                    if item.get("fileName")
                }
            ),
            "supportStatus": (
                SUPPORTED_STATUS
                if fulfilled
                else PARTIAL_STATUS
                if partial_links or pending_links or point_bindings
                else UNMATCHED_STATUS
            ),
            "evidenceReviewStatus": evidence_review_status,
            "confirmedLinkCount": len(confirmed_links),
            "unlocatableConfirmedLinkCount": len(unlocatable_confirmed_links),
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
                "severity": "warning",
                "actionKey": "contact_fde",
                "targetId": str(node_id),
            }
        )
    if pending_count:
        blocking_reasons.append(
            {
                "code": "PENDING_EVIDENCE_DECISION",
                "message": "仍有候选证据未确认或不采用，AI 复核将把其作为待确认证据参考。",
                "count": pending_count,
                "severity": "warning",
                "actionKey": "review_evidence",
                "targetId": str(node_id),
            }
        )
    if missing_count:
        blocking_reasons.append(
            {
                "code": "MISSING_REQUIRED_EVIDENCE",
                "message": "仍有审查点缺少已确认资料证据，审查意见应说明现有支持程度、缺项和风险。",
                "count": missing_count,
                "severity": "warning",
                "actionKey": "upload_missing_material",
                "targetId": str(node_id),
            }
        )
    if unlocatable_confirmed_count:
        blocking_reasons.append(
            {
                "code": "CONFIRMED_EVIDENCE_NOT_LOCATABLE",
                "message": "存在已确认但缺少页码、bbox 或引用原文的证据，审查意见应说明其不可定位风险。",
                "count": unlocatable_confirmed_count,
                "severity": "warning",
                "actionKey": "review_ocr",
                "targetId": str(node_id),
            }
        )
    ready_for_gap_precheck = bool(points)
    ready_for_ai_formal = ready_for_gap_precheck and pending_count == 0 and missing_count == 0
    available_review_modes = ["formal", "gap_precheck"] if ready_for_gap_precheck else ["formal"]
    recommended_action = (
        "run_formal_review"
        if ready_for_ai_formal
        else "run_gap_precheck"
        if ready_for_gap_precheck
        else "configure_review_points"
    )
    return {
        "schemaVersion": "node-evidence-readiness-v2",
        "hasReviewPoints": bool(points),
        "requiredCount": required_count,
        "satisfiedCount": satisfied_count,
        "missingCount": missing_count,
        "pendingCount": pending_count,
        "rejectedCount": rejected_count,
        "unlocatableConfirmedCount": unlocatable_confirmed_count,
        "progressPercent": progress_percent,
        "evidenceReviewComplete": bool(points) and pending_count == 0,
        "readyForAi": ready_for_ai_formal,
        "readyForAiFormal": ready_for_ai_formal,
        "readyForAiFormalIsRecommendation": True,
        "readyForGapPrecheck": ready_for_gap_precheck,
        "readinessAdvisoryOnly": True,
        "operationBlocked": False,
        "availableReviewModes": available_review_modes,
        "recommendedAction": recommended_action,
        "advisoryReasons": blocking_reasons,
        "blockingReasons": blocking_reasons,
        "requirements": rows,
        "missingRequirements": missing,
        "nodeEvidenceLinks": links,
        "advisoryEvidenceLinks": advisory_links,
        "advisoryEvidenceCount": len(advisory_links),
        "inputDocumentVersionIds": input_version_ids,
        "supportingDocumentCount": len(input_version_ids),
    }


def targeting_input_versions_for_node(repo: Any, project_id: str, node_id: int) -> list[str]:
    readiness = build_node_evidence_readiness(repo, project_id, node_id)
    if readiness.get("inputDocumentVersionIds"):
        return list(readiness["inputDocumentVersionIds"])
    bound_versions = [item["documentVersionId"] for item in repo.bindings_for_node(project_id, node_id)]
    if bound_versions:
        return bound_versions
    return unclassified_input_versions_for_project(repo, project_id)


def unclassified_input_versions_for_project(repo: Any, project_id: str) -> list[str]:
    ready: list[str] = []
    for document in repo.state.get("documents", []):
        if document.get("projectId") != project_id:
            continue
        if str(document.get("materialTypeCode") or "") != "unclassified_material":
            continue
        if str(document.get("currentOcrStatus") or "") not in {"已识别", "人工修正", "抽取不完整"}:
            continue
        version_id = str(document.get("currentVersionId") or "")
        version = repo.find_one("versions", version_id)
        knowledge_file = repo.knowledge_file_for_version(version_id)
        if not version or not knowledge_file:
            continue
        if str(version.get("documentId") or "") != str(document.get("id") or ""):
            continue
        if str(version.get("ocrStatus") or "") not in {"已识别", "人工修正", "抽取不完整"}:
            continue
        if str(knowledge_file.get("materialTypeCode") or "") != "unclassified_material":
            continue
        if str(knowledge_file.get("sliceStatus") or "") != "已切片":
            continue
        if str(knowledge_file.get("vectorStatus") or "") != "已向量化":
            continue
        ready.append(version_id)
    return sorted(set(ready))


def targeting_run_snapshot(run: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(run, ensure_ascii=False, default=str))
