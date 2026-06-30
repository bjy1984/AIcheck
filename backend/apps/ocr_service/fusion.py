from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

FIELD_ALIASES = {
    "管线号": "pipe_no",
    "管道号": "pipe_no",
    "管道代号": "pipe_no",
    "pipeline_no": "pipe_no",
    "line_no": "pipe_no",
    "pipe_no": "pipe_no",
    "图纸编号": "drawing_no",
    "图纸号": "drawing_no",
    "dwg_no": "drawing_no",
    "drawing_no": "drawing_no",
    "项目名称": "project_name",
    "project_name": "project_name",
    "证书编号": "certificate_no",
    "certificate_no": "certificate_no",
    "报告编号": "report_no",
    "report_no": "report_no",
}

TABLE_HEADER_ALIASES = {
    "piping_characteristic_table": {"序号", "管道号", "管道代号", "管线号", "公称直径", "管道等级", "设计压力", "介质", "起点", "终点"},
    "weld_detection_result_table": {"焊口编号", "检测方法", "评定级别", "检测比例", "结论", "报告编号"},
    "material_chemical_composition_table": {"化学成分", "炉批号", "c", "si", "mn", "p", "s"},
    "mechanical_property_table": {"力学性能", "抗拉强度", "屈服强度", "伸长率"},
    "construction_record_table": {"施工日期", "施工内容", "责任人", "检查结果"},
    "welding_record_table": {"焊口编号", "焊工", "焊工资格", "焊接日期"},
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
    fused["seals"] = fuse_seals(
        seal_candidates,
        profile=profile,
    )
    fused["quality"] = build_quality_gate(fused, profile)
    return fused


def dedupe_fragments(fragments: list[Any]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        key = (
            fragment.get("pageNo"),
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
        best = max(candidates, key=field_score)
        conflict = field_value_conflict(candidates)
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
        candidates = [table for table in table_items if table_matches_required(table, required)] or table_items
        best_source = max(candidates, key=lambda item: table_score(item, required_table=required))
        existing = next((table for table in selected if same_table_identity(table, best_source)), None)
        if existing is not None:
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
            continue
        best = deepcopy(best_source)
        best.setdefault("matchedRequiredTable", required)
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
        if not any(same_table_identity(table, selected_item) for selected_item in selected)
        and table_score(table) >= 0.72
    ]
    selected.extend(deepcopy(table) for table in unmatched)
    if not selected:
        selected.append(deepcopy(max(table_items, key=table_score)))
    return selected


def fuse_seals(seals: list[Any], *, profile: dict[str, Any]) -> list[dict[str, Any]]:
    seal_items = [seal for seal in seals if isinstance(seal, dict)]
    fused: list[dict[str, Any]] = []
    for seal in sorted(seal_items, key=lambda item: seal_score(item, profile), reverse=True):
        if any(overlaps(seal.get("bbox"), existing.get("bbox")) for existing in fused):
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
        hits = fragments_for_seal(seal_bbox, fragments)
        if not seal_fragment_hits_are_readable(seal, hits, profile):
            enriched.append(seal)
            continue
        text = " ".join(normalize_text(item.get("text")) for item in hits if normalize_text(item.get("text")))
        confidence = min(0.9, max(0.66, average([float(item.get("confidence") or 0.0) for item in hits]) * 0.88))
        output = deepcopy(seal)
        output["sealName"] = compact_seal_text(text)
        output["sealType"] = infer_fragment_seal_type(text, seal)
        output["ocrConfidence"] = round(confidence, 4)
        output["sourceEngine"] = "fragment_seal_text_fusion"
        flags = {str(flag) for flag in output.get("qualityFlags") or []}
        flags.discard("visual_candidate_only")
        flags.discard("requires_seal_ocr_text")
        flags.add("fragment_seal_text")
        output["qualityFlags"] = sorted(flags)
        output["fields"] = fragment_seal_fields(text, hits, seal_bbox, confidence)
        output["fragmentEvidence"] = [
            {
                "text": item.get("text"),
                "bbox": item.get("bbox"),
                "confidence": item.get("confidence"),
                "sourceEngine": item.get("sourceEngine"),
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


def fragments_for_seal(seal_bbox: list[float], fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    x0, y0, x1, y1 = seal_bbox
    pad_x = max((x1 - x0) * 0.12, 60.0)
    pad_y = max((y1 - y0) * 0.12, 60.0)
    hits = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        text = normalize_text(fragment.get("text"))
        if not text or len(text) <= 1:
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
            candidates.append(
                {
                    "sealId": f"fragment_{seal_type}_{page_no}_{len(candidates) + 1}",
                    "pageNo": page_no,
                    "sealType": seal_type,
                    "sealName": compact_seal_text(text),
                    "bbox": bbox,
                    "polygon": bbox_to_polygon(bbox),
                    "ocrConfidence": round(min(0.88, max(0.68, average([float(item.get("confidence") or 0.0) for item in hits]) * 0.9)), 4),
                    "fields": fragment_seal_fields(text, hits, bbox, 0.78),
                    "qualityFlags": ["fragment_seal_text", "text_only_seal_candidate"],
                    "sourceEngine": "fragment_seal_text_detector",
                    "fragmentEvidence": [
                        {
                            "text": item.get("text"),
                            "bbox": item.get("bbox"),
                            "confidence": item.get("confidence"),
                            "sourceEngine": item.get("sourceEngine"),
                        }
                        for item in hits
                    ],
                }
            )
            existing_types.add(seal_type)
    return candidates


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
) -> list[dict[str, Any]]:
    fields = [
        {
            "fieldName": "seal_text",
            "fieldCode": "seal_text",
            "fieldValue": compact_seal_text(text),
            "bbox": seal_bbox,
            "confidence": round(confidence, 4),
            "source": "ocr_fragments_in_visual_seal_bbox",
        }
    ]
    license_match = re.search(r"TS\s*[A-Z0-9-]+", text, flags=re.I)
    if license_match:
        fields.append(
            {
                "fieldName": "license_no",
                "fieldCode": "license_no",
                "fieldValue": license_match.group(0).replace(" ", ""),
                "bbox": seal_bbox,
                "confidence": round(confidence, 4),
                "source": "ocr_fragments_in_visual_seal_bbox",
            }
        )
    scope = next((normalize_text(item.get("text")) for item in hits if "管道" in normalize_text(item.get("text"))), "")
    if scope:
        fields.append(
            {
                "fieldName": "license_scope",
                "fieldCode": "license_scope",
                "fieldValue": scope,
                "bbox": seal_bbox,
                "confidence": round(confidence, 4),
                "source": "ocr_fragments_in_visual_seal_bbox",
            }
        )
    return fields


def build_quality_gate(result: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    existing = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    fields = [field for field in result.get("fields") or [] if isinstance(field, dict)]
    tables = [table for table in result.get("tables") or [] if isinstance(table, dict)]
    seals = [seal for seal in result.get("seals") or [] if isinstance(seal, dict)]
    required_fields = [field for field in profile.get("requiredFields") or [] if field != "seal"]
    field_codes = {str(field.get("fieldCode") or field.get("fieldName") or "") for field in fields}
    missing_fields = [field for field in required_fields if field not in field_codes]
    required_tables = [str(table) for table in profile.get("requiredTables") or []]
    missing_tables = missing_required_tables(tables, required_tables)
    required_seal = bool((profile.get("sealRules") or {}).get("required"))
    expected_seal_types = [str(item) for item in (profile.get("sealRules") or {}).get("expectedSealTypes") or []]
    field_confidence = average([float(field.get("confidence") or 0) for field in fields])
    table_confidence = average([float(table.get("structureConfidence") or 0) for table in tables])
    formal_seals = [seal for seal in seals if seal_text_is_readable(seal)]
    seal_confidence = (
        average([float(seal.get("ocrConfidence") or 0) for seal in formal_seals])
        if formal_seals
        else average([float(seal.get("visualConfidence") or 0) for seal in seals])
    )
    matched_seal_types = matched_expected_seal_types(formal_seals, expected_seal_types)
    missing_expected_seal_types = (
        expected_seal_types
        if required_seal and expected_seal_types and not matched_seal_types
        else []
    )
    field_completeness = 1.0 - (len(missing_fields) / max(len(required_fields), 1)) if required_fields else 1.0
    table_completeness = 1.0 - (len(missing_tables) / max(len(required_tables), 1)) if required_tables else 1.0
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
        "sealConfidence": round(seal_confidence, 4),
        "fieldCompleteness": round(field_completeness, 4),
        "tableCompleteness": round(table_completeness, 4),
        "sealCompleteness": round(seal_completeness, 4),
        "evidenceCompleteness": round(evidence_completeness(result), 4),
        "reasons": sorted(set(reasons)),
        "missingFields": missing_fields,
        "missingTables": missing_tables,
        "matchedSealTypes": matched_seal_types,
        "missingExpectedSealTypes": missing_expected_seal_types,
        "lowConfidenceFields": low_confidence_fields,
        "missingEvidence": missing_evidence,
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
    if "出厂检验" in text or "质量证明" in text or "质量专用章" in text:
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
    }
    return aliases.get(normalized, normalized)


def missing_required_tables(tables: list[dict[str, Any]], required_tables: list[str]) -> list[str]:
    return [
        required_table
        for required_table in required_tables
        if not any(table_matches_required(table, required_table) for table in tables)
    ]


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
    return table_schema_match_score(table, required_table) >= 0.58


def flatten_table_candidates(candidates: list[Any]) -> list[Any]:
    flattened: list[Any] = []
    for candidate in candidates:
        if isinstance(candidate, (list, tuple, set)):
            flattened.extend(candidate)
        else:
            flattened.append(candidate)
    return flattened


def same_table_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("tableId") and right.get("tableId") and left.get("tableId") == right.get("tableId"):
        return True
    return left.get("sourceEngine") == right.get("sourceEngine") and left.get("bbox") == right.get("bbox")


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
    matched = {token for token in expected if any(token in header or header in token for header in headers)}
    return len(matched) / max(len(expected), 1)


def table_header_tokens(table: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for cell in table.get("cells") or []:
        if not isinstance(cell, dict) or not cell.get("isHeader"):
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


def field_score(field: dict[str, Any]) -> float:
    value = str(field.get("fieldValue") or "")
    confidence = float(field.get("confidence") or 0.0)
    bbox_bonus = 0.05 if field.get("bbox") else 0.0
    value_bonus = min(len(value), 20) / 400.0
    return confidence + bbox_bonus + value_bonus


def field_value_conflict(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_value: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        normalized = normalize_field_value(candidate.get("fieldValue"))
        if not normalized:
            continue
        confidence = float(candidate.get("confidence") or 0.0)
        existing = by_value.get(normalized)
        if existing is None or confidence > float(existing.get("confidence") or 0.0):
            by_value[normalized] = {
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
    return confidence + min(normalized_rows, 20) * 0.02 + min(cells, 200) * 0.0005 + source_bonus + header_bonus + fill_bonus


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
    if "agentdesign_seal_ocr" in flags:
        formal_bonus += 0.2
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
    flags = seal.get("qualityFlags") or []
    if "visual_candidate_only" in flags or "requires_seal_ocr_text" in flags:
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
    with_bbox = [item for item in evidence_items if item.get("bbox") or item.get("polygon")]
    return len(with_bbox) / len(evidence_items)


def has_evidence_box(item: dict[str, Any]) -> bool:
    return bool(flat_bbox(item.get("bbox")) or flat_bbox(item.get("polygon")))


def average(values: list[float]) -> float:
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else 0.0


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())
