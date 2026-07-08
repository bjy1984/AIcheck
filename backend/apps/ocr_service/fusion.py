from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
import re
from copy import deepcopy
from typing import Any

from apps.ocr_service.utils import parse_bool

FIELD_ALIASES = {
    "公司名称": "company_name",
    "单位名称": "organization_name",
    "组织名称": "organization_name",
    "管线号": "pipe_no",
    "管道号": "pipe_no",
    "管道代号": "pipe_no",
    "管号": "pipe_no",
    "pipeline": "pipe_no",
    "pipeline_no": "pipe_no",
    "line_no": "pipe_no",
    "pipe_no": "pipe_no",
    "图纸编号": "drawing_no",
    "图纸号": "drawing_no",
    "图纸号dwg_no": "drawing_no",
    "dwg_no": "drawing_no",
    "drawing_no": "drawing_no",
    "项目名称": "project_name",
    "project_name": "project_name",
    "文件标题": "document_title",
    "设计阶段": "design_phase",
    "证书编号": "certificate_no",
    "合格证编号": "certificate_no",
    "质证书编号": "certificate_no",
    "certificate_no": "certificate_no",
    "certificate_number": "certificate_no",
    "cert_no": "certificate_no",
    "报告编号": "report_no",
    "报告号": "report_no",
    "report_no": "report_no",
    "report_number": "report_no",
    "生产厂家": "manufacturer",
    "制造单位": "manufacturer",
    "制造商": "manufacturer",
    "manufacturer": "manufacturer",
    "材质": "material_grade",
    "材料牌号": "material_grade",
    "牌号": "material_grade",
    "material_grade": "material_grade",
    "规格": "specification",
    "规格型号": "specification",
    "型号规格": "specification",
    "specification": "specification",
    "炉批号": "batch_no",
    "批号": "batch_no",
    "batch_no": "batch_no",
    "标准号": "standard_no",
    "执行标准": "standard_no",
    "standard_no": "standard_no",
    "检验结论": "inspection_conclusion",
    "结论": "conclusion",
    "inspection_conclusion": "inspection_conclusion",
    "日期": "issue_date",
    "签发日期": "issue_date",
    "发证日期": "issue_date",
    "出厂日期": "issue_date",
    "issue_date": "issue_date",
    "有效期": "valid_until",
    "有效期至": "valid_until",
    "valid_until": "valid_until",
    "签发机构": "issuer",
    "发证机关": "issuer",
    "issuer": "issuer",
    "许可范围": "license_scope",
    "license_scope": "license_scope",
    "检测方法": "detection_method",
    "探伤方法": "detection_method",
    "detection_method": "detection_method",
    "焊口编号": "weld_no",
    "焊口号": "weld_no",
    "weld_no": "weld_no",
    "检测日期": "detection_date",
    "detection_date": "detection_date",
    "评定级别": "evaluation_level",
    "evaluation_level": "evaluation_level",
    "检测单位": "inspection_unit",
    "inspection_unit": "inspection_unit",
    "记录编号": "record_no",
    "record_no": "record_no",
    "施工日期": "construction_date",
    "construction_date": "construction_date",
    "责任人": "responsible_person",
    "responsible_person": "responsible_person",
    "焊工": "welder_name",
    "焊工姓名": "welder_name",
    "welder_name": "welder_name",
    "焊工资格证号": "welder_cert_no",
    "证书号": "welder_cert_no",
    "welder_cert_no": "welder_cert_no",
    "焊接日期": "welding_date",
    "welding_date": "welding_date",
    "设计压力": "design_pressure",
    "试验压力": "test_pressure",
}

TABLE_HEADER_ALIASES = {
    "piping_characteristic_table": {"序号", "管道号", "管道代号", "管线号", "管号", "pipeno", "lineno", "公称直径", "dn", "nps", "管道等级", "设计压力", "介质", "起点", "终点"},
    "weld_detection_result_table": {"焊口编号", "焊口号", "weldno", "检测方法", "探伤方法", "rt", "ut", "评定级别", "检测比例", "结论", "报告编号"},
    "material_chemical_composition_table": {"化学成分", "化学成份", "炉批号", "批号", "heatno", "batchno", "c", "si", "mn", "p", "s"},
    "mechanical_property_table": {"力学性能", "机械性能", "抗拉强度", "屈服强度", "伸长率", "tensile", "yield", "elongation"},
    "construction_record_table": {"施工日期", "施工内容", "责任人", "检查结果", "记录编号", "project"},
    "welding_record_table": {"焊口编号", "焊口号", "焊工", "焊工资格", "资格证号", "焊接日期", "wps", "pqr"},
}


def fuse_parse_result(result: dict[str, Any], *, profile: dict[str, Any]) -> dict[str, Any]:
    fused = deepcopy(result)
    fused["fragments"] = dedupe_fragments(fused.get("fragments") or [])
    fused["fields"] = fuse_fields(fused.get("fields") or [])
    fused["tables"] = choose_tables(fused.get("tables") or [], profile=profile)
    seal_candidates = enrich_visual_seals_from_fragments(
        fused.get("seals") or [],
        fused.get("fragments") or [],
        profile=profile,
    )
    seal_candidates.extend(fragment_seal_candidates_from_text(fused.get("fragments") or [], existing_seals=seal_candidates))
    seal_candidates = reconcile_seal_organization_fields(
        seal_candidates,
        fragments=fused.get("fragments") or [],
        fields=fused.get("fields") or [],
    )
    fused["seals"] = fuse_seals(
        seal_candidates,
        profile=profile,
    )
    promoted_seal_fields = top_level_fields_from_seals(fused["seals"])
    if promoted_seal_fields:
        fused["fields"] = fuse_fields([*(fused.get("fields") or []), *promoted_seal_fields])
    fused["quality"] = build_quality_gate(fused, profile)
    fused["diagnostics"] = filter_resolved_quality_diagnostics(fused.get("diagnostics") or [], fused["quality"])
    return fused


def filter_resolved_quality_diagnostics(diagnostics: list[Any], quality: dict[str, Any]) -> list[Any]:
    unresolved = {str(item) for item in (quality.get("reasons") or [])}
    stale_codes = {
        "REQUIRED_FIELD_MISSING",
        "REQUIRED_TABLE_MISSING",
        "SEAL_NOT_FOUND",
        "SEAL_TEXT_LOW_CONFIDENCE",
        "SEAL_EVIDENCE_MISSING",
        "TABLE_EVIDENCE_MISSING",
        "TABLE_CELL_EVIDENCE_LOW",
    }
    filtered = []
    for item in diagnostics:
        code = str(item.get("code") or "") if isinstance(item, dict) else str(item)
        if code in stale_codes and code not in unresolved:
            continue
        filtered.append(item)
    return filtered


def dedupe_fragments(fragments: list[Any]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        key = (
            fragment.get("pageNo"),
            fragment.get("coordinateSystem"),
            fragment.get("coordinateTransformStatus"),
            normalize_text(fragment.get("text")),
            tuple(flat_bbox(fragment.get("bbox")) or []),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fragment)
    return deduped


def fuse_fields(fields: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    passthrough = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_code = normalize_field_key(field.get("fieldCode") or field.get("fieldName") or "")
        if not field_code:
            passthrough.append(field)
            continue
        grouped.setdefault(field_code, []).append(field)
    fused = []
    for field_code, candidates in grouped.items():
        formal_candidates = [
            candidate
            for candidate in candidates
            if parse_bool(candidate.get("remediationCandidateOnly"), False) is not True
        ]
        selectable_candidates = formal_candidates or candidates
        best = max(selectable_candidates, key=lambda item: field_score(item, field_code=field_code))
        conflict = field_value_conflict(selectable_candidates, field_code=field_code)
        output = deepcopy(best)
        output["fieldCode"] = field_code
        output["selectedVariantId"] = output.get("selectedVariantId") or output.get("variantId")
        if conflict:
            output["fusionDecision"] = "conflict_highest_confidence_candidate"
            flags = {str(flag) for flag in output.get("qualityFlags") or []}
            flags.add("field_value_conflict")
            output["qualityFlags"] = sorted(flags)
            output["conflictingValues"] = conflict
        else:
            output["fusionDecision"] = "single_candidate" if len(candidates) == 1 else "highest_confidence_candidate"
        output["candidates"] = [
            {
                "value": item.get("fieldValue"),
                "confidence": item.get("confidence"),
                "sourceEngine": item.get("sourceEngine"),
                "variantId": item.get("variantId") or item.get("selectedVariantId"),
                "bbox": item.get("bbox"),
                "polygon": item.get("polygon"),
                "pageNo": item.get("pageNo"),
                "coordinateSystem": item.get("coordinateSystem"),
                "sourceCoordinateSystem": item.get("sourceCoordinateSystem"),
                "coordinateTransformStatus": item.get("coordinateTransformStatus"),
                "qualityFlags": list(item.get("qualityFlags") or []),
            }
            for item in candidates
        ]
        fused.append(output)
    return [*fused, *passthrough]


def choose_tables(tables: list[Any], *, profile: dict[str, Any]) -> list[dict[str, Any]]:
    table_items = [table for table in tables if isinstance(table, dict)]
    if not table_items:
        return []
    required_tables = [str(item) for item in profile.get("requiredTables") or []]
    if len(table_items) == 1 and not required_tables:
        return table_items
    selected: list[dict[str, Any]] = []
    for required in required_tables:
        matched_candidates = [table for table in table_items if table_matches_required(table, required)]
        candidates = matched_candidates or non_auxiliary_table_candidates(table_items) or table_items
        best_source = max(candidates, key=lambda item: table_score(item, required_table=required))
        existing = next((table for table in selected if same_table_selection_identity(table, best_source)), None)
        if existing is not None:
            if matched_candidates:
                matched = {str(item) for item in existing.get("matchedRequiredTables") or [] if item}
                if existing.get("matchedRequiredTable"):
                    matched.add(str(existing["matchedRequiredTable"]))
                matched.add(required)
                existing["matchedRequiredTables"] = sorted(matched)
                existing.pop("matchedRequiredTable", None)
            schemas = {str(item) for item in existing.get("businessSchemas") or [] if item}
            schemas.update(str(item) for item in best_source.get("businessSchemas") or [] if item)
            if best_source.get("businessSchema"):
                schemas.add(str(best_source["businessSchema"]))
            if schemas:
                existing["businessSchemas"] = sorted(schemas)
            if not matched_candidates:
                flags = {str(flag) for flag in existing.get("qualityFlags") or []}
                flags.add("required_table_unmatched_candidate")
                existing["qualityFlags"] = sorted(flags)
                candidates_for = {str(item) for item in existing.get("candidateForRequiredTables") or [] if item}
                candidates_for.add(required)
                existing["candidateForRequiredTables"] = sorted(candidates_for)
            continue
        best = deepcopy(best_source)
        if matched_candidates:
            best.setdefault("matchedRequiredTable", required)
            best["matchedRequired"] = True
            best["candidateOnly"] = False
        else:
            flags = {str(flag) for flag in best.get("qualityFlags") or []}
            flags.add("required_table_unmatched_candidate")
            best["qualityFlags"] = sorted(flags)
            best.setdefault("candidateForRequiredTables", [required])
            best["matchedRequired"] = False
            best["candidateOnly"] = True
        conflicts = [
            table.get("tableId")
            for table in candidates
            if not same_table_identity(table, best_source)
            and abs(table_score(best, required_table=required) - table_score(table, required_table=required)) < 0.08
            and table.get("sourceEngine") != best.get("sourceEngine")
        ]
        if conflicts:
            best.setdefault("qualityFlags", []).append("table_engine_conflict")
            best["conflictingTableIds"] = conflicts
        selected.append(best)
    unmatched = [
        table
        for table in table_items
        if not any(same_table_selection_identity(table, selected_item) for selected_item in selected)
        and (table_score(table) >= 0.72 or table_is_auxiliary_candidate(table))
    ]
    selected.extend(deepcopy(table) for table in unmatched)
    if not selected:
        selected.append(deepcopy(max(table_items, key=table_score)))
    return selected


def fuse_seals(seals: list[Any], *, profile: dict[str, Any]) -> list[dict[str, Any]]:
    seal_items = [seal for seal in seals if isinstance(seal, dict)]
    fused: list[dict[str, Any]] = []
    for seal in sorted(seal_items, key=lambda item: seal_score(item, profile), reverse=True):
        if any(same_page_overlap(seal, existing) for existing in fused):
            continue
        output = deepcopy(seal)
        output["selectedVariantId"] = output.get("selectedVariantId") or output.get("variantId")
        output["visualRankScore"] = round(seal_score(seal, profile), 4)
        fused.append(output)
    return fused


def enrich_visual_seals_from_fragments(
    seals: list[Any],
    fragments: list[dict[str, Any]],
    *,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    enriched = []
    for seal in seals:
        if not isinstance(seal, dict):
            continue
        if not should_enrich_visual_seal(seal, profile):
            enriched.append(seal)
            continue
        seal_bbox = flat_bbox(seal.get("bbox") or seal.get("polygon"))
        if not seal_bbox:
            enriched.append(seal)
            continue
        hits = fragments_for_seal(seal, fragments)
        if not seal_fragment_hits_are_readable(seal, hits, profile):
            enriched.append(seal)
            continue
        text = " ".join(normalize_text(item.get("text")) for item in hits if normalize_text(item.get("text")))
        confidence = min(0.9, max(0.66, average([float(item.get("confidence") or 0.0) for item in hits]) * 0.88))
        output = deepcopy(seal)
        if not output.get("coordinateSystem") and hits:
            output.update(
                copy_spatial_metadata(
                    hits[0],
                    bbox=seal_bbox,
                    polygon=output.get("polygon") or bbox_to_polygon(seal_bbox),
                )
            )
        output["sealName"] = compact_seal_text(text)
        output["sealType"] = infer_fragment_seal_type(text, seal)
        output["ocrConfidence"] = round(confidence, 4)
        output["sourceEngine"] = "fragment_seal_text_fusion"
        flags = {str(flag) for flag in output.get("qualityFlags") or []}
        flags.add("fragment_seal_text")
        flags.add("seal_bbox_from_ocr_fragments")
        can_satisfy = fragment_seal_text_can_satisfy_required(output["sealType"], text)
        flags.add("requires_seal_crop_ocr")
        if not can_satisfy:
            flags.add("text_only_seal_candidate")
        output["qualityFlags"] = sorted(flags)
        output["sealEvidenceLevel"] = "fragment_roi_text" if can_satisfy else "visual_plus_page_text"
        output["sourceKind"] = "fragment_seal_bbox" if can_satisfy else output.get("sourceKind")
        output["candidateOnly"] = True
        output["canSatisfyRequiredSeal"] = False
        output["fields"] = fragment_seal_fields(text, hits, seal_bbox, confidence, spatial_source=seal)
        output["fragmentEvidence"] = [
            {
                **copy_spatial_metadata(item),
                "text": item.get("text"),
                "confidence": item.get("confidence"),
            }
            for item in hits
        ]
        enriched.append(output)
    return enriched


def should_enrich_visual_seal(seal: dict[str, Any], profile: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    if "visual_candidate_only" not in flags or "requires_seal_ocr_text" not in flags:
        return False
    seal_rules = profile.get("sealRules") or {}
    preferred_colors = {str(item).lower() for item in seal_rules.get("preferredVisualColors") or []}
    visual_color = str(seal.get("visualColor") or "").lower()
    if preferred_colors:
        return visual_color in preferred_colors
    return visual_color in {"red", "blue"}


def fragments_for_seal(seal: dict[str, Any], fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seal_bbox = flat_bbox(seal.get("bbox"))
    if not seal_bbox or not has_evidence_box(seal):
        return []
    x0, y0, x1, y1 = seal_bbox
    seal_page = int_from(seal.get("pageNo"), default=1)
    seal_coordinate = seal.get("coordinateSystem")
    pad_x = max((x1 - x0) * 0.12, 60.0)
    pad_y = max((y1 - y0) * 0.12, 60.0)
    hits = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        text = normalize_text(fragment.get("text"))
        if not text or len(text) <= 1:
            continue
        if not has_evidence_box(fragment):
            continue
        if int_from(fragment.get("pageNo"), default=1) != seal_page:
            continue
        if fragment.get("coordinateSystem") != seal_coordinate:
            continue
        bbox = flat_bbox(fragment.get("bbox"))
        if not bbox:
            continue
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        if x0 - pad_x <= center_x <= x1 + pad_x and y0 - pad_y <= center_y <= y1 + pad_y:
            hits.append(fragment)
    ranked = sorted(hits, key=seal_fragment_rank_key)[:24]
    return sorted(ranked, key=fragment_sort_key)


def seal_fragment_rank_key(fragment: dict[str, Any]) -> tuple[int, float, float, str]:
    bbox = flat_bbox(fragment.get("bbox")) or [0.0, 0.0, 0.0, 0.0]
    text = normalize_text(fragment.get("text"))
    return (0 if seal_text_has_indicator(text) else 1, bbox[1], bbox[0], text)


def fragment_sort_key(fragment: dict[str, Any]) -> tuple[float, float, str]:
    bbox = flat_bbox(fragment.get("bbox")) or [0.0, 0.0, 0.0, 0.0]
    return (bbox[1], bbox[0], normalize_text(fragment.get("text")))


def seal_fragment_hits_are_readable(
    seal: dict[str, Any],
    hits: list[dict[str, Any]],
    profile: dict[str, Any],
) -> bool:
    if len(hits) < 2:
        return False
    text = " ".join(normalize_text(item.get("text")) for item in hits)
    if len(text.replace(" ", "")) < 8:
        return False
    if seal_text_has_indicator(text):
        return True
    expected = " ".join(str(item) for item in (profile.get("sealRules") or {}).get("expectedSealTypes") or [])
    return bool(expected and any(token in text.lower() for token in ["seal", "license", "permit"]))


def compact_seal_text(text: str) -> str:
    clean = normalize_text(text)
    return clean[:120]


def seal_text_has_indicator(text: str) -> bool:
    indicators = ["章", "许可", "管道", "检测", "检验", "公司", "设计", "出图", "单位名称", "TS"]
    return any(indicator in text for indicator in indicators)


def infer_fragment_seal_type(text: str, seal: dict[str, Any]) -> str:
    if "设计许可" in text or ("管道" in text and ("许可" in text or re.search(r"TS\s*\d", text, flags=re.I))):
        return "design_license_seal"
    if "检测" in text or "检验" in text:
        return "inspection_testing_seal"
    if "出图" in text or "审图" in text or "施工图审查" in text:
        return "drawing_approval_seal"
    if "管道" in text or re.search(r"TS\s*\d", text, flags=re.I):
        return "design_license_seal"
    return str(seal.get("sealType") or "fragment_text_seal")


def fragment_seal_candidates_from_text(
    fragments: list[dict[str, Any]],
    *,
    existing_seals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    existing_types = {normalize_seal_type_key(seal.get("sealType")) for seal in existing_seals if isinstance(seal, dict)}
    grouped: dict[int, list[dict[str, Any]]] = {}
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        page_no = int(fragment.get("pageNo") or 1)
        grouped.setdefault(page_no, []).append(fragment)
    specs = [
        (
            "design_license_seal",
            ("设计许可", "压力管道"),
            ("设计许可", "许可", "压力管道", "TS"),
        ),
        (
            "drawing_approval_seal",
            ("出图", "单位名称"),
            ("出图", "出图专用", "施工图审查", "单位名称"),
        ),
        (
            "inspection_testing_seal",
            ("检测", "检验"),
            ("检测专用章", "检验专用章", "检验检测", "检测", "检验"),
        ),
        (
            "quality_seal",
            ("质量", "证明"),
            ("质量证明", "出厂检验", "质量专用章", "质量", "证明"),
        ),
        (
            "quality_seal",
            ("质检专用章",),
            ("质检专用章", "检验合格", "出厂检验", "合格证"),
        ),
    ]
    for page_no, page_fragments in grouped.items():
        for seal_type, required_terms, optional_terms in specs:
            if seal_type in existing_types:
                continue
            hits = keyword_fragment_hits(page_fragments, required_terms=required_terms, optional_terms=optional_terms)
            if not hits:
                continue
            bbox = union_bbox([flat_bbox(item.get("bbox")) for item in hits])
            if not bbox:
                continue
            text = " ".join(normalize_text(item.get("text")) for item in sorted(hits, key=fragment_sort_key))
            can_satisfy = fragment_seal_text_can_satisfy_required(seal_type, text)
            quality_flags = ["fragment_seal_text", "seal_bbox_from_ocr_fragments"]
            quality_flags.append("requires_seal_crop_ocr")
            if not can_satisfy:
                quality_flags.append("text_only_seal_candidate")
            spatial = copy_spatial_metadata(hits[0], bbox=bbox, polygon=bbox_to_polygon(bbox)) if hits else {}
            candidates.append(
                {
                    **spatial,
                    "sealId": f"fragment_{seal_type}_{page_no}_{len(candidates) + 1}",
                    "pageNo": page_no,
                    "sealType": seal_type,
                    "sealName": compact_seal_text(text),
                    "bbox": bbox,
                    "polygon": bbox_to_polygon(bbox),
                    "ocrConfidence": round(min(0.88, max(0.68, average([float(item.get("confidence") or 0.0) for item in hits]) * 0.9)), 4),
                    "candidateOnly": True,
                    "canSatisfyRequiredSeal": False,
                    "sealEvidenceLevel": "fragment_roi_text" if can_satisfy else "visual_plus_page_text",
                    "sourceKind": "fragment_seal_bbox" if can_satisfy else None,
                    "fields": fragment_seal_fields(text, hits, bbox, 0.78, spatial_source=hits[0] if hits else None),
                    "qualityFlags": quality_flags,
                    "sourceEngine": "fragment_seal_text_detector",
                    "fragmentEvidence": [
                        {
                            **copy_spatial_metadata(item),
                            "text": item.get("text"),
                            "confidence": item.get("confidence"),
                        }
                        for item in hits
                    ],
                }
            )
            existing_types.add(seal_type)
    return candidates


def top_level_fields_from_seals(seals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for seal in seals:
        if not isinstance(seal, dict):
            continue
        if parse_bool(seal.get("candidateOnly"), False) is True:
            continue
        for field in seal.get("fields") or []:
            if not isinstance(field, dict):
                continue
            field_code = normalize_field_key(field.get("fieldCode") or field.get("fieldName"))
            if not field_code or field_code == "seal_text":
                continue
            promoted = deepcopy(field)
            promoted["fieldCode"] = field_code
            promoted.setdefault("sourceEngine", seal.get("sourceEngine"))
            promoted.setdefault("confidence", seal.get("ocrConfidence"))
            promoted.setdefault("extractionMethod", "seal_roi_ocr_field")
            promoted["sourceSealId"] = seal.get("sealId")
            promoted["sourceSealType"] = seal.get("sealType")
            if not has_evidence_box(promoted):
                promoted.update(
                    copy_spatial_metadata(
                        seal,
                        bbox=promoted.get("bbox") or seal.get("bbox"),
                        polygon=promoted.get("polygon") or seal.get("polygon"),
                    )
                )
            if str(seal.get("sealEvidenceLevel") or "") == "visual_plus_seal_crop_ocr":
                promoted["extractionMethod"] = "seal_crop_ocr_field"
                promoted["sourcePriority"] = "crop_ocr"
            elif str(seal.get("sealEvidenceLevel") or "") == "fragment_roi_text":
                promoted.setdefault("sourcePriority", "fragment_roi_text")
            fields.append(promoted)
    return fields


def fragment_seal_text_can_satisfy_required(seal_type: Any, text: str) -> bool:
    normalized_type = normalize_seal_type_key(seal_type)
    compact = normalize_text(text).replace(" ", "")
    if normalized_type == "design_license_seal":
        return bool(
            re.search(r"TS\s*[A-Z0-9-]+", text, flags=re.I)
            and ("压力管道" in compact or "设计许可" in compact or "特种设备" in compact)
        )
    if normalized_type == "drawing_approval_seal":
        has_certificate = bool(re.search(r"\bA\s*\d{6,12}\b", text, flags=re.I))
        has_expiry = bool(extract_blue_seal_expiry(text))
        has_approval_signal = any(token in compact for token in ["出图", "审图", "施工图审查", "资质证书编号", "单位名称"])
        return has_approval_signal and (has_certificate or has_expiry)
    return False


def keyword_fragment_hits(
    fragments: list[dict[str, Any]],
    *,
    required_terms: tuple[str, ...],
    optional_terms: tuple[str, ...],
) -> list[dict[str, Any]]:
    term_hits: list[dict[str, Any]] = []
    text_blob = " ".join(normalize_text(item.get("text")) for item in fragments)
    if not all(term in text_blob for term in required_terms):
        return []
    for fragment in fragments:
        text = normalize_text(fragment.get("text"))
        if text and any(term in text for term in optional_terms):
            term_hits.append(fragment)
    if len(term_hits) < 2:
        return []
    bbox = union_bbox([flat_bbox(item.get("bbox")) for item in term_hits])
    if not bbox:
        return []
    x0, y0, x1, y1 = bbox
    pad_x = max((x1 - x0) * 0.18, 80.0)
    pad_y = max((y1 - y0) * 0.18, 80.0)
    nearby: list[dict[str, Any]] = []
    for fragment in fragments:
        fragment_bbox = flat_bbox(fragment.get("bbox"))
        if not fragment_bbox:
            continue
        center_x = (fragment_bbox[0] + fragment_bbox[2]) / 2
        center_y = (fragment_bbox[1] + fragment_bbox[3]) / 2
        if x0 - pad_x <= center_x <= x1 + pad_x and y0 - pad_y <= center_y <= y1 + pad_y:
            nearby.append(fragment)
    ranked = sorted(nearby or term_hits, key=seal_fragment_rank_key)[:18]
    return sorted(ranked, key=fragment_sort_key)


def fragment_seal_fields(
    text: str,
    hits: list[dict[str, Any]],
    seal_bbox: list[float],
    confidence: float,
    *,
    spatial_source: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    spatial = copy_spatial_metadata(spatial_source or (hits[0] if hits else {}), bbox=seal_bbox)
    seal_type = infer_fragment_seal_type(text, {})
    fields = [
        {
            **spatial,
            "fieldName": "seal_text",
            "fieldCode": "seal_text",
            "fieldValue": compact_seal_text(text),
            "confidence": round(confidence, 4),
            "source": "ocr_fragments_in_visual_seal_bbox",
        }
    ]
    license_match = re.search(r"TS\s*[A-Z0-9-]+", text, flags=re.I)
    if license_match:
        fields.append(
            {
                **spatial,
                "fieldName": "license_no",
                "fieldCode": "license_no",
                "fieldValue": license_match.group(0).replace(" ", ""),
                "confidence": round(confidence, 4),
                "source": "ocr_fragments_in_visual_seal_bbox",
            }
        )
    blue_certificate_match = re.search(r"\bA\s*\d{6,12}\b", text, flags=re.I)
    if seal_type == "drawing_approval_seal" and blue_certificate_match:
        fields.append(
            {
                **spatial,
                "fieldName": "资质证书编号",
                "fieldCode": "blue_seal_license_no",
                "fieldValue": blue_certificate_match.group(0).replace(" ", ""),
                "confidence": round(confidence, 4),
                "source": "ocr_fragments_in_visual_seal_bbox",
            }
        )
    blue_expiry = extract_blue_seal_expiry(text)
    if seal_type == "drawing_approval_seal" and blue_expiry:
        fields.append(
            {
                **spatial,
                "fieldName": "蓝章有效期至",
                "fieldCode": "blue_seal_expiry",
                "fieldValue": blue_expiry,
                "confidence": round(confidence, 4),
                "source": "ocr_fragments_in_visual_seal_bbox",
            }
        )
    red_date = extract_red_seal_date(text)
    if seal_type == "design_license_seal" and red_date:
        fields.append(
            {
                **spatial,
                "fieldName": "红章日期",
                "fieldCode": "red_seal_date",
                "fieldValue": red_date,
                "confidence": round(confidence, 4),
                "source": "ocr_fragments_in_visual_seal_bbox",
            }
        )
    scope = next((normalize_text(item.get("text")) for item in hits if "管道" in normalize_text(item.get("text"))), "")
    if scope:
        fields.append(
            {
                **spatial,
                "fieldName": "license_scope",
                "fieldCode": "license_scope",
                "fieldValue": scope,
                "confidence": round(confidence, 4),
                "source": "ocr_fragments_in_visual_seal_bbox",
            }
        )
    return fields


def extract_blue_seal_expiry(text: str) -> str | None:
    patterns = [
        re.compile(r"有效期(?:限)?至\s*[:：]?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"),
        re.compile(r"有效期(?:限)?\s*[:：]?\s*(?:至|到)\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", "", match.group(1))
    return None


def extract_red_seal_date(text: str) -> str | None:
    if "有效期" in text:
        return None
    match = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", text)
    return re.sub(r"\s+", "", match.group(1)) if match else None


def reconcile_seal_organization_fields(
    seals: list[dict[str, Any]],
    *,
    fragments: list[dict[str, Any]],
    fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    organization_candidates = document_organization_candidates(fragments, fields)
    if not organization_candidates:
        return seals
    output: list[dict[str, Any]] = []
    for seal in seals:
        candidate = deepcopy(seal)
        seal_fields = [item for item in candidate.get("fields") or [] if isinstance(item, dict)]
        if not seal_fields:
            output.append(candidate)
            continue
        reconciled_fields: list[dict[str, Any]] = []
        seen_organization_values: set[str] = set()
        for field in seal_fields:
            name = str(field.get("fieldName") or field.get("fieldCode") or "")
            value = str(field.get("fieldValue") or field.get("value") or "").strip()
            if "单位名称" in name or is_organization_text(value):
                best = best_matching_organization(value, organization_candidates)
                if best and best["score"] >= 0.58:
                    normalized_value = best["value"]
                    key = normalize_text(normalized_value)
                    if key in seen_organization_values:
                        continue
                    seen_organization_values.add(key)
                    updated = {
                        **field,
                        "fieldName": "单位名称",
                        "fieldValue": normalized_value,
                        "confidence": max(safe_float(field.get("confidence")), best["confidence"]),
                        "source": "document_organization_reconciliation",
                    }
                    if normalize_text(value) != normalize_text(normalized_value):
                        updated["originalFieldValue"] = value
                    reconciled_fields.append(updated)
                    continue
            reconciled_fields.append(field)
        candidate["fields"] = reconciled_fields
        output.append(candidate)
    return output


def document_organization_candidates(
    fragments: list[dict[str, Any]],
    fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    def add(value: Any, confidence: Any) -> None:
        organization = extract_organization_text(str(value or ""))
        if not organization:
            return
        key = normalize_text(organization)
        if any(item["key"] == key for item in candidates):
            return
        candidates.append(
            {
                "key": key,
                "value": organization,
                "confidence": safe_float(confidence),
            }
        )

    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("fieldCode") or field.get("fieldName") or "")
        if any(token in name for token in ["company", "organization", "单位", "公司", "设计院"]):
            add(field.get("fieldValue") or field.get("value"), field.get("confidence"))
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        add(fragment.get("text") or fragment.get("fullText"), fragment.get("confidence"))
    return sorted(candidates, key=lambda item: item["confidence"], reverse=True)


def best_matching_organization(value: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not value:
        return None
    normalized_value = normalize_text(value)
    best: dict[str, Any] | None = None
    for candidate in candidates:
        score = SequenceMatcher(None, normalized_value, candidate["key"]).ratio()
        if not best or score > best["score"]:
            best = {**candidate, "score": score}
    return best


def extract_organization_text(value: str) -> str:
    compact = normalize_text(value)
    match = re.search(r"[\u4e00-\u9fff（）()]{4,}?(?:设计院有限公司|设计有限公司|有限责任公司|有限公司)", compact)
    return match.group(0) if match else ""


def is_organization_text(value: str) -> bool:
    return bool(extract_organization_text(value))


def safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def copy_spatial_metadata(src: dict[str, Any], *, bbox: Any | None = None, polygon: Any | None = None) -> dict[str, Any]:
    output = {
        "bbox": bbox if bbox is not None else src.get("bbox"),
        "polygon": polygon if polygon is not None else src.get("polygon"),
        "pageNo": src.get("pageNo"),
        "coordinateSystem": src.get("coordinateSystem"),
        "sourceCoordinateSystem": src.get("sourceCoordinateSystem"),
        "coordinateTransform": src.get("coordinateTransform"),
        "coordinateTransformStatus": src.get("coordinateTransformStatus"),
        "qualityFlags": list(src.get("qualityFlags") or []),
        "variantId": src.get("variantId"),
        "selectedVariantId": src.get("selectedVariantId"),
        "sourceEngine": src.get("sourceEngine"),
    }
    return {key: value for key, value in output.items() if value is not None and value != []}


def build_quality_gate(result: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    existing = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    fields = [field for field in result.get("fields") or [] if isinstance(field, dict)]
    tables = [table for table in result.get("tables") or [] if isinstance(table, dict)]
    seals = [seal for seal in result.get("seals") or [] if isinstance(seal, dict)]
    required_fields = [normalize_field_key(field) for field in profile.get("requiredFields") or [] if field != "seal"]
    field_codes = {
        normalize_field_key(field.get("fieldCode") or field.get("fieldName") or "")
        for field in fields
        if parse_bool(field.get("remediationCandidateOnly"), False) is not True
    }
    missing_fields = [field for field in required_fields if field and field not in field_codes]
    required_tables = [str(table) for table in profile.get("requiredTables") or []]
    missing_tables = missing_required_tables(tables, required_tables)
    required_seal = parse_bool((profile.get("sealRules") or {}).get("required"), False) is True
    expected_seal_types = [str(item) for item in (profile.get("sealRules") or {}).get("expectedSealTypes") or []]
    field_confidence = average([float(field.get("confidence") or 0) for field in fields])
    table_confidence = average([float(table.get("structureConfidence") or 0) for table in tables])
    table_cell_evidence_coverage = average([table_cell_evidence_score(table) for table in tables])
    formal_seals = [seal for seal in seals if seal_text_is_readable(seal)]
    seal_confidence = (
        average([float(seal.get("ocrConfidence") or 0) for seal in formal_seals])
        if formal_seals
        else average([float(seal.get("visualConfidence") or 0) for seal in seals])
    )
    matched_seal_types = matched_expected_seal_types(
        seal_type_evidence_candidates(formal_seals, seals),
        expected_seal_types,
    )
    missing_expected_seal_types = (
        expected_seal_types
        if required_seal and expected_seal_types and not matched_seal_types
        else []
    )
    field_completeness = 1.0 - (len(missing_fields) / max(len(required_fields), 1)) if required_fields else 1.0
    table_completeness = 1.0 - (len(missing_tables) / max(len(required_tables), 1)) if required_tables else 1.0
    low_cell_evidence_tables = mark_low_table_cell_evidence(tables, required_tables, profile)
    low_cell_table_codes = {
        str(item.get("tableCode"))
        for item in low_cell_evidence_tables
        if item.get("tableCode") is not None
    }
    table_auto_blocked_count = len(set(missing_tables) | low_cell_table_codes)
    table_auto_usable_completeness = (
        1.0 - (table_auto_blocked_count / max(len(required_tables), 1)) if required_tables else 1.0
    )
    seal_completeness = (
        1.0
        if not required_seal
        else 1.0
        if formal_seals and not missing_expected_seal_types
        else 0.0
    )
    reasons = []
    if missing_fields:
        reasons.append("REQUIRED_FIELD_MISSING")
    low_confidence_fields = mark_low_confidence_fields(fields, profile, required_fields)
    if low_confidence_fields:
        reasons.append("FIELD_LOW_CONFIDENCE")
    invalid_fields = mark_invalid_field_values(fields, profile, required_fields)
    if invalid_fields:
        reasons.append("FIELD_FORMAT_INVALID")
    missing_evidence = mark_missing_required_evidence(
        fields=fields,
        tables=tables,
        seals=seals,
        profile=profile,
        required_fields=required_fields,
        required_tables=required_tables,
        required_seal=required_seal,
    )
    missing_evidence_types = {item.get("targetType") for item in missing_evidence}
    if "field" in missing_evidence_types:
        reasons.append("FIELD_EVIDENCE_MISSING")
    if "table" in missing_evidence_types:
        reasons.append("TABLE_EVIDENCE_MISSING")
    if "seal" in missing_evidence_types:
        reasons.append("SEAL_EVIDENCE_MISSING")
    if missing_tables:
        reasons.append("REQUIRED_TABLE_MISSING")
    if required_tables and tables and all(table_is_heuristic_fallback(table) for table in tables):
        reasons.append("TABLE_HEURISTIC_REVIEW_REQUIRED")
    min_table_confidence = float((profile.get("qualityRules") or {}).get("minTableStructureConfidence") or 0.0)
    if tables and min_table_confidence and table_confidence < min_table_confidence:
        reasons.append("TABLE_STRUCTURE_LOW_CONFIDENCE")
    if low_cell_evidence_tables:
        reasons.append("TABLE_CELL_EVIDENCE_LOW")
    if required_seal and not seals:
        reasons.append("SEAL_NOT_FOUND")
    if required_seal and seals and not formal_seals:
        reasons.append("SEAL_TEXT_LOW_CONFIDENCE")
    elif required_seal and formal_seals and seal_confidence < 0.65:
        reasons.append("SEAL_TEXT_LOW_CONFIDENCE")
    if formal_seals and missing_expected_seal_types:
        reasons.append("EXPECTED_SEAL_TYPE_MISSING")
    if any("table_engine_conflict" in (table.get("qualityFlags") or []) for table in tables):
        reasons.append("TABLE_ENGINE_CONFLICT")
    if any(field_conflict_requires_review(field, profile, required_fields) for field in fields):
        reasons.append("FIELD_VALUE_CONFLICT")
    status = "failed" if result.get("status") == "failed" else "needs_human_review" if reasons else "auto_usable"
    return {
        **existing,
        "status": status,
        "overallConfidence": round(average([field_confidence, table_confidence or field_confidence, seal_confidence or field_confidence]), 4),
        "textConfidence": round(field_confidence, 4),
        "tableConfidence": round(table_confidence, 4),
        "tableCellEvidenceCoverage": round(table_cell_evidence_coverage, 4),
        "sealConfidence": round(seal_confidence, 4),
        "fieldCompleteness": round(field_completeness, 4),
        "tableCompleteness": round(table_completeness, 4),
        "tableAutoUsableCompleteness": round(table_auto_usable_completeness, 4),
        "sealCompleteness": round(seal_completeness, 4),
        "evidenceCompleteness": round(evidence_completeness(result), 4),
        "reasons": sorted(set(reasons)),
        "missingFields": missing_fields,
        "missingTables": missing_tables,
        "matchedSealTypes": matched_seal_types,
        "missingExpectedSealTypes": missing_expected_seal_types,
        "lowConfidenceFields": low_confidence_fields,
        "invalidFields": invalid_fields,
        "missingEvidence": missing_evidence,
        "lowTableCellEvidenceTables": low_cell_evidence_tables,
    }


def matched_expected_seal_types(seals: list[dict[str, Any]], expected_seal_types: list[str]) -> list[str]:
    expected_by_key = {normalize_seal_type_key(item): item for item in expected_seal_types}
    if not expected_by_key:
        return []
    matched = []
    for seal in seals:
        for key in seal_type_candidate_keys(seal):
            if key in expected_by_key and expected_by_key[key] not in matched:
                matched.append(expected_by_key[key])
    return sorted(matched)


def seal_type_evidence_candidates(
    formal_seals: list[dict[str, Any]],
    seals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = list(formal_seals)
    seen_ids = {str(seal.get("sealId") or id(seal)) for seal in candidates}
    for seal in seals:
        if not isinstance(seal, dict):
            continue
        flags = {str(flag) for flag in seal.get("qualityFlags") or []}
        seal_id = str(seal.get("sealId") or id(seal))
        if (
            seal_id not in seen_ids
            and seal.get("sourceEngine") == "fragment_seal_text_detector"
            and "text_only_seal_candidate" in flags
            and float(seal.get("ocrConfidence") or 0) >= 0.65
        ):
            candidates.append(seal)
            seen_ids.add(seal_id)
    return candidates


def seal_type_candidate_keys(seal: dict[str, Any]) -> list[str]:
    keys = [normalize_seal_type_key(seal.get("sealType"))]
    inferred = infer_seal_type_key(seal)
    if inferred:
        keys.append(inferred)
    return [key for key in dict.fromkeys(keys) if key]


def infer_seal_type_key(seal: dict[str, Any]) -> str:
    text_parts = [
        seal.get("sealName"),
        seal.get("sealType"),
        seal.get("organizationName"),
        " ".join(str(field.get("fieldValue") or field.get("value") or "") for field in seal.get("fields") or [] if isinstance(field, dict)),
    ]
    text = " ".join(str(item or "") for item in text_parts)
    if ("设计许可" in text or "设计许可证" in text) and ("压力管道" in text or "特种设备" in text):
        return "design_license_seal"
    if "检验检测" in text or "检测专用章" in text or "检验专用章" in text:
        return "inspection_testing_seal"
    if "出厂检验" in text or "质量证明" in text or "质量专用章" in text or "质检专用章" in text or "质检章" in text:
        return "quality_seal"
    if "审图" in text or "施工图审查" in text:
        return "drawing_approval_seal"
    return ""


def normalize_seal_type_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "pressure_pipe_design_license_seal": "design_license_seal",
        "special_equipment_design_permit_seal": "design_license_seal",
        "special_equipment_design_license_seal": "design_license_seal",
        "design_permit_seal": "design_license_seal",
        "design_approval_seal": "drawing_approval_seal",
        "testing_seal": "inspection_testing_seal",
        "inspection_seal": "inspection_testing_seal",
        "quality_certificate_seal": "quality_seal",
        "quality_inspection_seal": "quality_seal",
        "quality_control_seal": "quality_seal",
    }
    return aliases.get(normalized, normalized)


def missing_required_tables(tables: list[dict[str, Any]], required_tables: list[str]) -> list[str]:
    return [
        required_table
        for required_table in required_tables
        if not any(
            not parse_bool(table.get("candidateOnly"), False) and table_matches_required(table, required_table)
            for table in tables
        )
    ]


def mark_low_table_cell_evidence(
    tables: list[dict[str, Any]],
    required_tables: list[str],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    if not required_tables:
        return []
    threshold = float((profile.get("qualityRules") or {}).get("minTableCellEvidenceCoverage") or 0.5)
    if threshold <= 0:
        return []
    low: list[dict[str, Any]] = []
    for required_table in required_tables:
        matched = [
            table
            for table in tables
            if isinstance(table, dict)
            and not parse_bool(table.get("candidateOnly"), False)
            and not table_is_heuristic_fallback(table)
            and table_matches_required(table, required_table)
        ]
        if not matched:
            continue
        best = max(matched, key=lambda table: table_score(table, required_table=required_table))
        coverage = table_cell_evidence_score(best)
        if coverage >= threshold:
            continue
        flags = {str(flag) for flag in best.get("qualityFlags") or []}
        flags.add("table_cell_evidence_low")
        best["qualityFlags"] = sorted(flags)
        low.append(
            {
                "tableCode": required_table,
                "tableId": best.get("tableId"),
                "businessSchema": best.get("businessSchema"),
                "cellEvidenceCoverage": round(coverage, 4),
                "minCellEvidenceCoverage": threshold,
                "sourceEngine": best.get("sourceEngine"),
                "variantId": best.get("variantId") or best.get("selectedVariantId"),
            }
        )
    return low


def table_matches_required(table: dict[str, Any], required_table: str) -> bool:
    required = normalize_table_key(required_table)
    if not required:
        return False
    candidates = [
        table.get("businessSchema"),
        table.get("businessSchemas"),
        table.get("matchedRequiredTables"),
        table.get("tableId"),
        table.get("tableType"),
        table.get("schema"),
    ]
    if any(normalize_table_key(candidate) == required for candidate in flatten_table_candidates(candidates)):
        return True
    return table_schema_match_score(table, required_table) >= 0.58 or table_schema_match_count(table, required_table) >= 3


def flatten_table_candidates(candidates: list[Any]) -> list[Any]:
    flattened: list[Any] = []
    for candidate in candidates:
        if isinstance(candidate, (list, tuple, set)):
            flattened.extend(candidate)
        else:
            flattened.append(candidate)
    return flattened


def table_is_auxiliary_candidate(table: dict[str, Any]) -> bool:
    schema = normalize_table_key(table.get("businessSchema") or table.get("tableType") or "")
    flags = {str(flag) for flag in table.get("qualityFlags") or []}
    return (
        parse_bool(table.get("auxiliaryTable"), False)
        or schema in {"engineering_drawing_title_block", "engineering_drawing_title_block_v1"}
        or "title_block_region" in flags
    )


def non_auxiliary_table_candidates(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [table for table in tables if not table_is_auxiliary_candidate(table)]


def same_table_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if int_from(left.get("pageNo"), default=1) != int_from(right.get("pageNo"), default=1):
        return False
    if not left.get("coordinateSystem") or not right.get("coordinateSystem"):
        return False
    if left.get("coordinateSystem") != right.get("coordinateSystem"):
        return False
    if left.get("tableId") and right.get("tableId") and left.get("tableId") == right.get("tableId"):
        return True
    return left.get("sourceEngine") == right.get("sourceEngine") and left.get("bbox") == right.get("bbox")


def same_table_selection_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if same_table_identity(left, right):
        return True
    if left.get("tableId") and left.get("tableId") == right.get("tableId"):
        left_page = left.get("pageNo")
        right_page = right.get("pageNo")
        if left_page is not None and right_page is not None and int_from(left_page, default=1) != int_from(right_page, default=1):
            return False
        return True
    return False


def normalize_table_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    normalized = re.sub(r"_v\d+$", "", normalized)
    normalized = re.sub(r"_\d+$", "", normalized)
    return normalized


def table_schema_match_score(table: dict[str, Any], required_table: str | None) -> float:
    if not required_table:
        return 0.0
    expected = TABLE_HEADER_ALIASES.get(normalize_table_key(required_table), set())
    if not expected:
        return 0.0
    headers = table_header_tokens(table)
    if not headers:
        return 0.0
    matched = {token for token in expected if any(header_token_matches(token, header) for header in headers)}
    return len(matched) / max(len(expected), 1)


def table_schema_match_count(table: dict[str, Any], required_table: str | None) -> int:
    if not required_table:
        return 0
    expected = TABLE_HEADER_ALIASES.get(normalize_table_key(required_table), set())
    if not expected:
        return 0
    headers = table_header_tokens(table)
    if not headers:
        return 0
    return len({token for token in expected if any(header_token_matches(token, header) for header in headers)})


def header_token_matches(expected: str, header: str) -> bool:
    if not expected or not header:
        return False
    if len(expected) <= 2 or len(header) <= 2:
        return expected == header
    return expected in header or header in expected


def same_page_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if int_from(left.get("pageNo"), default=1) != int_from(right.get("pageNo"), default=1):
        return False
    left_coordinate = left.get("coordinateSystem")
    right_coordinate = right.get("coordinateSystem")
    if bool(left_coordinate) != bool(right_coordinate):
        return False
    if left_coordinate and right_coordinate and left_coordinate != right_coordinate:
        return False
    return overlaps(left.get("bbox"), right.get("bbox"))


def table_header_tokens(table: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for cell in table.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        is_header = bool(cell.get("isHeader")) or int_from(cell.get("row"), default=-1) == 0
        if not is_header:
            continue
        token = normalize_header_token(cell.get("text"))
        if token:
            tokens.add(token)
    for row in (table.get("normalizedRows") or [])[:2]:
        if isinstance(row, dict):
            tokens.update(normalize_header_token(key) for key in row.keys())
    return {token for token in tokens if token}


def normalize_header_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def int_from(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def field_score(field: dict[str, Any], *, field_code: str | None = None) -> float:
    value = str(field.get("fieldValue") or "")
    confidence = float(field.get("confidence") or 0.0)
    bbox_bonus = 0.05 if has_evidence_box(field) else -0.05 if field.get("bbox") or field.get("polygon") else 0.0
    value_bonus = min(len(value), 20) / 400.0
    validation_bonus = 0.0
    if field_code:
        valid, _ = validate_business_field_value(field_code, value)
        validation_bonus = 0.08 if valid else -0.22
    source_priority = str(field.get("sourcePriority") or "")
    method = str(field.get("extractionMethod") or "")
    crop_bonus = 0.1 if source_priority == "crop_ocr" or method == "seal_crop_ocr_field" else 0.0
    fragment_penalty = -0.02 if source_priority == "fragment_roi_text" else 0.0
    return confidence + bbox_bonus + value_bonus + validation_bonus + crop_bonus + fragment_penalty


def field_value_conflict(candidates: list[dict[str, Any]], *, field_code: str | None = None) -> list[dict[str, Any]]:
    if field_code:
        valid_candidates = [
            candidate
            for candidate in candidates
            if validate_business_field_value(field_code, candidate.get("fieldValue"))[0]
        ]
        if valid_candidates:
            candidates = valid_candidates
    by_value: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        normalized = normalize_field_value(candidate.get("fieldValue"))
        if not normalized:
            continue
        confidence = float(candidate.get("confidence") or 0.0)
        existing = by_value.get(normalized)
        if existing is None or confidence > float(existing.get("confidence") or 0.0):
            by_value[normalized] = {
                **copy_spatial_metadata(candidate),
                "value": candidate.get("fieldValue"),
                "normalizedValue": normalized,
                "confidence": confidence,
                "sourceEngine": candidate.get("sourceEngine"),
                "variantId": candidate.get("variantId") or candidate.get("selectedVariantId"),
            }
    if len(by_value) < 2:
        return []
    ordered = sorted(by_value.values(), key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
    best = float(ordered[0].get("confidence") or 0.0)
    min_confidence = 0.7
    max_gap = 0.18
    conflicting = [
        item
        for item in ordered
        if float(item.get("confidence") or 0.0) >= min_confidence and best - float(item.get("confidence") or 0.0) <= max_gap
    ]
    return conflicting if len(conflicting) >= 2 else []


def normalize_field_value(value: Any) -> str:
    return "".join(str(value or "").upper().split())


def field_conflict_requires_review(
    field: dict[str, Any],
    profile: dict[str, Any],
    required_fields: list[str],
) -> bool:
    if "field_value_conflict" not in (field.get("qualityFlags") or []):
        return False
    code = normalize_field_key(field.get("fieldCode") or field.get("fieldName"))
    required = {normalize_field_key(item) for item in required_fields}
    profile_critical = {
        normalize_field_key(item)
        for item in ((profile.get("qualityRules") or {}).get("criticalConflictFields") or [])
    }
    return code in required or code in profile_critical


def mark_low_confidence_fields(
    fields: list[dict[str, Any]],
    profile: dict[str, Any],
    required_fields: list[str],
) -> list[dict[str, Any]]:
    threshold = float((profile.get("qualityRules") or {}).get("minFieldConfidence") or 0.0)
    if threshold <= 0:
        return []
    required = {normalize_field_key(item) for item in required_fields}
    profile_critical = {
        normalize_field_key(item)
        for item in ((profile.get("qualityRules") or {}).get("criticalConflictFields") or [])
    }
    watched = required | profile_critical
    low_confidence = []
    for field in fields:
        code = normalize_field_key(field.get("fieldCode") or field.get("fieldName"))
        if not code or code not in watched:
            continue
        confidence = float(field.get("confidence") or 0.0)
        if confidence >= threshold:
            continue
        flags = {str(flag) for flag in field.get("qualityFlags") or []}
        flags.add("field_low_confidence")
        field["qualityFlags"] = sorted(flags)
        low_confidence.append(
            {
                "fieldCode": field.get("fieldCode") or field.get("fieldName"),
                "fieldName": field.get("fieldName"),
                "fieldValue": field.get("fieldValue"),
                "confidence": confidence,
                "threshold": threshold,
                "sourceEngine": field.get("sourceEngine"),
                "variantId": field.get("variantId") or field.get("selectedVariantId"),
            }
        )
    return low_confidence


def mark_invalid_field_values(
    fields: list[dict[str, Any]],
    profile: dict[str, Any],
    required_fields: list[str],
) -> list[dict[str, Any]]:
    required = {normalize_field_key(item) for item in required_fields}
    profile_critical = {
        normalize_field_key(item)
        for item in ((profile.get("qualityRules") or {}).get("criticalConflictFields") or [])
    }
    watched = required | profile_critical
    invalid: list[dict[str, Any]] = []
    for field in fields:
        code = normalize_field_key(field.get("fieldCode") or field.get("fieldName"))
        if not code or code not in watched:
            continue
        ok, reason = validate_business_field_value(code, field.get("fieldValue"))
        if ok:
            continue
        flags = {str(flag) for flag in field.get("qualityFlags") or []}
        flags.add("field_format_invalid")
        field["qualityFlags"] = sorted(flags)
        invalid.append(
            {
                "fieldCode": field.get("fieldCode") or field.get("fieldName"),
                "fieldName": field.get("fieldName"),
                "fieldValue": field.get("fieldValue"),
                "reason": reason,
                "sourceEngine": field.get("sourceEngine"),
                "variantId": field.get("variantId") or field.get("selectedVariantId"),
            }
        )
    return invalid


def validate_business_field_value(field_code: str, value: Any) -> tuple[bool, str]:
    text = normalize_text(value)
    if not text:
        return False, "empty_value"
    normalized = normalize_field_key(field_code)
    if normalized in {
        "report_no",
        "certificate_no",
        "record_no",
        "drawing_no",
        "welder_cert_no",
        "batch_no",
        "standard_no",
    }:
        return validate_identifier_value(normalized, text)
    if normalized in {
        "issue_date",
        "valid_until",
        "detection_date",
        "construction_date",
        "welding_date",
    }:
        return validate_date_value(text)
    if normalized in {"pipe_no", "weld_no"}:
        return validate_code_list_value(normalized, text)
    if normalized in {"design_pressure", "test_pressure", "pressure"}:
        return validate_pressure_value(text)
    if normalized in {"detection_method"}:
        return validate_detection_method(text)
    if normalized in {"evaluation_level"}:
        return validate_evaluation_level(text)
    if normalized in {"conclusion", "inspection_conclusion"}:
        return validate_conclusion_value(text)
    return True, ""


def validate_identifier_value(field_code: str, text: str) -> tuple[bool, str]:
    compact = normalize_identifier_text(text)
    if len(compact) < 2:
        return False, "identifier_too_short"
    if re.search(r"[^A-Z0-9/_.#()（）\-\u4e00-\u9fff]", compact, flags=re.I):
        return False, "identifier_has_invalid_characters"
    if not re.search(r"[A-Z0-9]", compact, flags=re.I):
        return False, "identifier_missing_alnum"
    if field_code in {"report_no", "certificate_no", "record_no", "drawing_no"} and len(compact) < 4:
        return False, "identifier_too_short"
    return True, ""


def validate_date_value(text: str) -> tuple[bool, str]:
    compact = normalize_identifier_text(text)
    patterns = [
        r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日?",
        r"(?P<year>\d{4})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})",
        r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})",
        r"(?P<year>\d{4})年(?P<month>\d{1,2})月",
        r"(?P<year>\d{4})[-/.](?P<month>\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact)
        if not match:
            continue
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.groupdict().get("day") or 1)
        try:
            datetime(year, month, day)
        except ValueError:
            return False, "date_out_of_range"
        return True, ""
    return False, "date_format_unrecognized"


def validate_code_list_value(field_code: str, text: str) -> tuple[bool, str]:
    tokens = [token for token in re.split(r"[,，;；、\s]+", normalize_identifier_text(text)) if token]
    if not tokens:
        return False, "code_list_empty"
    valid_count = 0
    for token in tokens[:30]:
        if re.search(r"[A-Z]", token, flags=re.I) and re.search(r"\d", token) and re.fullmatch(r"[A-Z0-9_.#()/（）\-]+", token, flags=re.I):
            valid_count += 1
    if valid_count == 0:
        return False, f"{field_code}_format_unrecognized"
    return True, ""


def validate_pressure_value(text: str) -> tuple[bool, str]:
    compact = normalize_identifier_text(text).replace("MPA", "").replace("Mpa", "").replace("MPa", "")
    matches = re.findall(r"\d+(?:\.\d+)?", compact)
    if not matches:
        return False, "pressure_missing_number"
    values = [float(value) for value in matches]
    if any(value < 0 or value > 100 for value in values):
        return False, "pressure_out_of_range"
    return True, ""


def validate_detection_method(text: str) -> tuple[bool, str]:
    compact = normalize_identifier_text(text).upper()
    if any(method in compact for method in ["RT", "UT", "MT", "PT", "TOFD", "PAUT", "DR"]):
        return True, ""
    if any(term in compact for term in ["射线", "超声", "磁粉", "渗透", "检测"]):
        return True, ""
    return False, "detection_method_unrecognized"


def validate_evaluation_level(text: str) -> tuple[bool, str]:
    compact = normalize_identifier_text(text).upper()
    if re.search(r"(I{1,4}|ⅰ|Ⅱ|Ⅲ|Ⅳ|一级|二级|三级|四级|合格|不合格|AB|B|C)", compact):
        return True, ""
    return False, "evaluation_level_unrecognized"


def validate_conclusion_value(text: str) -> tuple[bool, str]:
    if any(term in text for term in ["合格", "不合格", "通过", "符合", "不符合", "返修", "复验", "接受", "拒收"]):
        return True, ""
    if any(term in text.upper() for term in ["PASS", "FAIL", "ACCEPT", "REJECT", "OK", "NG"]):
        return True, ""
    return False, "conclusion_unrecognized"


def normalize_identifier_text(value: Any) -> str:
    return "".join(str(value or "").split())


def mark_missing_required_evidence(
    *,
    fields: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    seals: list[dict[str, Any]],
    profile: dict[str, Any],
    required_fields: list[str],
    required_tables: list[Any],
    required_seal: bool,
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    required = {normalize_field_key(item) for item in required_fields}
    profile_critical = {
        normalize_field_key(item)
        for item in ((profile.get("qualityRules") or {}).get("criticalConflictFields") or [])
    }
    watched = required | profile_critical
    for field in fields:
        code = normalize_field_key(field.get("fieldCode") or field.get("fieldName"))
        if not code or code not in watched or has_evidence_box(field):
            continue
        flags = {str(flag) for flag in field.get("qualityFlags") or []}
        flags.add("field_evidence_missing")
        field["qualityFlags"] = sorted(flags)
        missing.append(
            {
                "targetType": "field",
                "targetId": field.get("fieldCode") or field.get("fieldName"),
                "fieldCode": field.get("fieldCode") or field.get("fieldName"),
                "fieldName": field.get("fieldName"),
                "fieldValue": field.get("fieldValue"),
                "sourceEngine": field.get("sourceEngine"),
                "variantId": field.get("variantId") or field.get("selectedVariantId"),
            }
        )
    if required_tables:
        for table in tables:
            if has_evidence_box(table):
                continue
            flags = {str(flag) for flag in table.get("qualityFlags") or []}
            flags.add("table_evidence_missing")
            table["qualityFlags"] = sorted(flags)
            missing.append(
                {
                    "targetType": "table",
                    "targetId": table.get("tableId") or table.get("businessSchema"),
                    "businessSchema": table.get("businessSchema"),
                    "sourceEngine": table.get("sourceEngine"),
                }
            )
    if required_seal:
        for seal in seals:
            if not seal_text_is_readable(seal) or has_evidence_box(seal):
                continue
            flags = {str(flag) for flag in seal.get("qualityFlags") or []}
            flags.add("seal_evidence_missing")
            seal["qualityFlags"] = sorted(flags)
            missing.append(
                {
                    "targetType": "seal",
                    "targetId": seal.get("sealId") or seal.get("sealName"),
                    "sealName": seal.get("sealName"),
                    "sealType": seal.get("sealType"),
                    "sourceEngine": seal.get("sourceEngine"),
                }
            )
    return missing


def normalize_field_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", str(value or "").strip().lower()).strip("_")
    return FIELD_ALIASES.get(normalized, normalized)


def table_score(table: dict[str, Any], required_table: str | None = None) -> float:
    confidence = float(table.get("structureConfidence") or 0.0)
    normalized_rows = len(table.get("normalizedRows") or [])
    cells = len(table.get("cells") or [])
    source_bonus = 0.12 if table.get("sourceEngine") == "pp_structure_v3" else 0.0
    header_bonus = table_schema_match_score(table, required_table) * 0.22 if required_table else 0.0
    fill_bonus = table_fill_rate(table) * 0.08
    cell_evidence_bonus = table_cell_evidence_score(table) * 0.08
    evidence_bonus = 0.06 if has_evidence_box(table) else -0.04 if table.get("bbox") or table.get("polygon") else 0.0
    return (
        confidence
        + min(normalized_rows, 20) * 0.02
        + min(cells, 200) * 0.0005
        + source_bonus
        + header_bonus
        + fill_bonus
        + cell_evidence_bonus
        + evidence_bonus
    )


def table_cell_evidence_score(table: dict[str, Any]) -> float:
    cells = [cell for cell in table.get("cells") or [] if isinstance(cell, dict)]
    if not cells:
        return 0.0
    valid = [cell for cell in cells if has_evidence_box(cell)]
    return len(valid) / max(len(cells), 1)


def table_fill_rate(table: dict[str, Any]) -> float:
    cells = [cell for cell in table.get("cells") or [] if isinstance(cell, dict)]
    if cells:
        return len([cell for cell in cells if str(cell.get("text") or "").strip()]) / max(len(cells), 1)
    rows = [row for row in table.get("normalizedRows") or [] if isinstance(row, dict)]
    values = [value for row in rows for value in row.values()]
    if not values:
        return 0.0
    return len([value for value in values if str(value or "").strip()]) / len(values)


def table_is_heuristic_fallback(table: dict[str, Any]) -> bool:
    source = str(table.get("sourceEngine") or "")
    flags = {str(flag) for flag in table.get("qualityFlags") or []}
    return source.startswith("heuristic_") or "heuristic_table_fallback" in flags


def seal_score(seal: dict[str, Any], profile: dict[str, Any] | None = None) -> float:
    confidence = float(seal.get("ocrConfidence") or seal.get("visualConfidence") or 0.0)
    name_bonus = 0.12 if str(seal.get("sealName") or "").strip() else 0.0
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    formal_bonus = -0.3 if "visual_candidate_only" in flags else 0.25
    if parse_bool(seal.get("canSatisfyRequiredSeal"), None) is True:
        formal_bonus += 1.0
    if "text_only_seal_candidate" in flags:
        formal_bonus -= 1.0
    if parse_bool(seal.get("candidateOnly"), False) is True:
        formal_bonus -= 0.8
    if has_evidence_box(seal):
        formal_bonus += 0.08
    elif seal.get("bbox") or seal.get("polygon"):
        formal_bonus -= 0.05
    if "agentdesign_seal_ocr" in flags:
        formal_bonus += 0.2
    evidence_level = str(seal.get("sealEvidenceLevel") or "")
    if evidence_level == "visual_plus_seal_crop_ocr":
        formal_bonus += 0.28
    elif evidence_level == "fragment_roi_text":
        formal_bonus += 0.04
    if "seal_crop_ocr" in flags:
        formal_bonus += 0.12
    return confidence + name_bonus + formal_bonus + visual_profile_bonus(seal, profile or {})


def visual_profile_bonus(seal: dict[str, Any], profile: dict[str, Any]) -> float:
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    if "visual_candidate_only" not in flags:
        return 0.0
    seal_rules = profile.get("sealRules") or {}
    bonus = 0.0
    preferred_colors = {str(item).lower() for item in seal_rules.get("preferredVisualColors") or []}
    visual_color = str(seal.get("visualColor") or "").lower()
    if preferred_colors and visual_color in preferred_colors:
        bonus += 0.2
    if str(seal_rules.get("preferredVisualRegion") or "") == "bottom_right" and seal_in_bottom_right(seal):
        bonus += 0.15
    return bonus


def seal_in_bottom_right(seal: dict[str, Any]) -> bool:
    bbox = flat_bbox(seal.get("bbox"))
    page_width = float(seal.get("pageWidth") or 0)
    page_height = float(seal.get("pageHeight") or 0)
    if not bbox or page_width <= 0 or page_height <= 0:
        return False
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return center_x >= page_width * 0.55 and center_y >= page_height * 0.55


def seal_text_is_readable(seal: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    if parse_bool(seal.get("candidateOnly"), False) is True:
        return False
    if parse_bool(seal.get("canSatisfyRequiredSeal"), None) is False:
        return False
    if {"visual_candidate_only", "requires_seal_ocr_text", "text_only_seal_candidate"}.intersection(flags):
        return False
    seal_name = str(seal.get("sealName") or "").strip()
    if not seal_name or seal_name.startswith("视觉"):
        return False
    return float(seal.get("ocrConfidence") or 0) >= 0.65


def overlaps(left: Any, right: Any) -> bool:
    left_box = flat_bbox(left)
    right_box = flat_bbox(right)
    if not left_box or not right_box:
        return False
    lx0, ly0, lx1, ly1 = left_box
    rx0, ry0, rx1, ry1 = right_box
    inter_x0 = max(lx0, rx0)
    inter_y0 = max(ly0, ry0)
    inter_x1 = min(lx1, rx1)
    inter_y1 = min(ly1, ry1)
    if inter_x1 <= inter_x0 or inter_y1 <= inter_y0:
        return False
    inter = (inter_x1 - inter_x0) * (inter_y1 - inter_y0)
    left_area = max((lx1 - lx0) * (ly1 - ly0), 1.0)
    right_area = max((rx1 - rx0) * (ry1 - ry0), 1.0)
    return inter / min(left_area, right_area) >= 0.65


def flat_bbox(raw_bbox: Any) -> list[float] | None:
    if not isinstance(raw_bbox, list) or not raw_bbox:
        return None
    if len(raw_bbox) == 4 and all(isinstance(value, (int, float)) for value in raw_bbox):
        x0, y0, x1, y1 = [float(value) for value in raw_bbox]
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    points = []
    for point in raw_bbox:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if not points:
        return None
    return [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]


def union_bbox(boxes: list[list[float] | None]) -> list[float] | None:
    valid = [box for box in boxes if box and len(box) >= 4]
    if not valid:
        return None
    return [
        min(float(box[0]) for box in valid),
        min(float(box[1]) for box in valid),
        max(float(box[2]) for box in valid),
        max(float(box[3]) for box in valid),
    ]


def bbox_to_polygon(bbox: list[float]) -> list[list[float]]:
    x0, y0, x1, y1 = [float(item) for item in bbox[:4]]
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def evidence_completeness(result: dict[str, Any]) -> float:
    evidence_items = [
        *(field for field in result.get("fields") or [] if isinstance(field, dict)),
        *(table for table in result.get("tables") or [] if isinstance(table, dict)),
        *(seal for seal in result.get("seals") or [] if isinstance(seal, dict)),
    ]
    if not evidence_items:
        return 0.0
    with_bbox = [item for item in evidence_items if has_evidence_box(item)]
    return len(with_bbox) / len(evidence_items)


def has_evidence_box(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    if parse_bool(item.get("candidateOnly"), False) is True:
        return False
    flags = {str(flag) for flag in item.get("qualityFlags") or []}
    if {"document_coordinate_unmapped", "coordinate_transform_unmapped", "external_coordinate_unverified"}.intersection(flags):
        return False
    if item.get("coordinateSystem") != "rendered_pixels":
        return False
    if not item.get("pageNo"):
        return False
    status = item.get("coordinateTransformStatus")
    if status and status not in {"original", "mapped", "mapped_from_crop", "mapped_from_pdf_points"}:
        return False
    return bool(flat_bbox(item.get("bbox")) or flat_bbox(item.get("polygon")))


def average(values: list[float]) -> float:
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else 0.0


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())
