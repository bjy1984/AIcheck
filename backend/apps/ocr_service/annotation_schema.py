from __future__ import annotations

import re
from typing import Any


QUALITY_STATUSES = {"auto_usable", "needs_human_review", "failed"}
KNOWN_SEAL_TYPES = {
    "company_official_seal",
    "design_license_seal",
    "inspection_testing_seal",
    "material_certificate_seal",
    "qualification_seal",
    "official_seal",
    "visual_red_seal",
    "visual_blue_seal",
}
FIELD_CODE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_:\-]{1,}$")
BUSINESS_SCHEMA_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_:\-]{1,}$")


def validate_expected_schema(
    expected: dict[str, Any],
    *,
    scenario: str | None = None,
    page_count: int | None = None,
    page_dimensions: dict[int, tuple[int, int]] | None = None,
    require_review: bool = False,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if not isinstance(expected, dict) or not expected:
        return [failure("OCR_ANNOTATION_SCHEMA_EMPTY", "expected annotation JSON is empty")]
    quality_status = expected.get("qualityStatus")
    if quality_status is not None and quality_status not in QUALITY_STATUSES:
        failures.append(
            failure(
                "OCR_ANNOTATION_QUALITY_STATUS_INVALID",
                f"qualityStatus must be one of {sorted(QUALITY_STATUSES)}",
                field="qualityStatus",
            )
        )
    failures.extend(validate_fields(expected.get("fields"), page_count=page_count, page_dimensions=page_dimensions))
    failures.extend(validate_tables(expected.get("tables"), page_count=page_count, page_dimensions=page_dimensions))
    failures.extend(validate_seals(expected.get("seals"), page_count=page_count, page_dimensions=page_dimensions))
    failures.extend(validate_required_sections(expected, scenario=scenario))
    if require_review:
        failures.extend(validate_review(expected))
    return failures


def validate_fields(
    fields: Any,
    *,
    page_count: int | None,
    page_dimensions: dict[int, tuple[int, int]] | None,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(list_items(fields)):
        path = f"fields[{index}]"
        field_code = str(item.get("fieldCode") or "").strip()
        if not field_code or "replace-with" in field_code or not FIELD_CODE_PATTERN.fullmatch(field_code):
            failures.append(failure("OCR_ANNOTATION_FIELD_CODE_INVALID", "fieldCode is required and must be a stable code", field=path))
        value = item.get("value", item.get("fieldValue"))
        if value is None or str(value).strip() == "" or "replace-with" in str(value):
            failures.append(failure("OCR_ANNOTATION_FIELD_VALUE_INVALID", "field value is required", field=path))
            if value is not None and str(value).strip() == "":
                failures.append(failure("OCR_ANNOTATION_FIELD_VALUE_EMPTY", "field value cannot be empty", field=path))
        duplicate_key = (field_code, str(item.get("pageNo") or ""), str(value or "").strip())
        if all(duplicate_key) and duplicate_key in seen:
            failures.append(failure("OCR_ANNOTATION_DUPLICATE_FIELD", "duplicate field label for the same page and value", field=path))
        if all(duplicate_key):
            seen.add(duplicate_key)
        failures.extend(validate_evidence(item, field=path, page_count=page_count, page_dimensions=page_dimensions))
    return failures


def validate_tables(
    tables: Any,
    *,
    page_count: int | None,
    page_dimensions: dict[int, tuple[int, int]] | None,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(list_items(tables)):
        path = f"tables[{index}]"
        schema = str(item.get("businessSchema") or item.get("tableCode") or "").strip()
        if not schema or "replace-with" in schema or not BUSINESS_SCHEMA_PATTERN.fullmatch(schema):
            failures.append(failure("OCR_ANNOTATION_TABLE_SCHEMA_INVALID", "businessSchema is required and must be a stable code", field=path))
        duplicate_key = (schema, str(item.get("pageNo") or ""))
        if all(duplicate_key) and duplicate_key in seen:
            failures.append(failure("OCR_ANNOTATION_DUPLICATE_TABLE", "duplicate table label for the same page", field=path))
        if all(duplicate_key):
            seen.add(duplicate_key)
        for metric in ["minRows", "minColumns"]:
            if metric in item and not positive_int(item.get(metric)):
                failures.append(failure("OCR_ANNOTATION_TABLE_MIN_INVALID", f"{metric} must be a positive integer", field=f"{path}.{metric}"))
        failures.extend(validate_evidence(item, field=path, page_count=page_count, page_dimensions=page_dimensions))
    return failures


def validate_seals(
    seals: Any,
    *,
    page_count: int | None,
    page_dimensions: dict[int, tuple[int, int]] | None,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(list_items(seals)):
        path = f"seals[{index}]"
        name = str(item.get("nameContains") or item.get("sealName") or "").strip()
        seal_type = str(item.get("sealType") or "").strip()
        if not name and not seal_type:
            failures.append(failure("OCR_ANNOTATION_SEAL_LABEL_MISSING", "seal nameContains or sealType is required", field=path))
        if "replace-with" in name:
            failures.append(failure("OCR_ANNOTATION_SEAL_LABEL_MISSING", "seal label placeholder must be replaced", field=path))
        if seal_type and not seal_type_allowed(seal_type):
            failures.append(failure("OCR_ANNOTATION_SEAL_TYPE_INVALID", "sealType is not in the accepted enum pattern", field=path))
        duplicate_key = (seal_type or "-", name or "-", str(item.get("pageNo") or ""))
        if duplicate_key[2] and duplicate_key in seen:
            failures.append(failure("OCR_ANNOTATION_DUPLICATE_SEAL", "duplicate seal label for the same page", field=path))
        if duplicate_key[2]:
            seen.add(duplicate_key)
        failures.extend(validate_evidence(item, field=path, page_count=page_count, page_dimensions=page_dimensions))
    return failures


def validate_evidence(
    item: dict[str, Any],
    *,
    field: str,
    page_count: int | None,
    page_dimensions: dict[int, tuple[int, int]] | None,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    page_no = item.get("pageNo")
    if page_count and page_count > 1:
        if not positive_int(page_no):
            failures.append(failure("OCR_ANNOTATION_PAGE_NO_MISSING", "pageNo is required for multi-page samples", field=field))
        elif int(page_no) > int(page_count):
            failures.append(failure("OCR_ANNOTATION_PAGE_NO_OUT_OF_RANGE", "pageNo exceeds source pageCount", field=field))
    bbox = item.get("bbox")
    polygon = item.get("polygon")
    if not positive_bbox(bbox) and not positive_polygon(polygon):
        failures.append(failure("OCR_ANNOTATION_EVIDENCE_MISSING", "positive-area bbox or polygon is required", field=field))
        return failures
    if positive_int(page_no) and page_dimensions:
        dimensions = page_dimensions.get(int(page_no))
        if dimensions:
            if bbox is not None and not bbox_inside_page(bbox, dimensions):
                failures.append(failure("OCR_ANNOTATION_BBOX_OUT_OF_BOUNDS", "bbox is outside page dimensions", field=field))
            if polygon is not None and not polygon_inside_page(polygon, dimensions):
                failures.append(failure("OCR_ANNOTATION_POLYGON_OUT_OF_BOUNDS", "polygon is outside page dimensions", field=field))
    return failures


def validate_required_sections(expected: dict[str, Any], *, scenario: str | None) -> list[dict[str, Any]]:
    required = required_sections_for_scenario(scenario)
    failures: list[dict[str, Any]] = []
    for section in required:
        if not list_items(expected.get(section)):
            failures.append(
                failure(
                    "OCR_ANNOTATION_REQUIRED_SECTION_MISSING",
                    f"{section} annotation is required for {scenario}",
                    field=section,
                )
            )
    return failures


def validate_review(expected: dict[str, Any]) -> list[dict[str, Any]]:
    review = expected.get("review") if isinstance(expected.get("review"), dict) else {}
    labeler = str(review.get("labeler") or "").strip()
    reviewer = str(review.get("reviewer") or "").strip()
    if not labeler:
        return [failure("OCR_ANNOTATION_LABELER_MISSING", "labeler is required for ready_for_eval")]
    if not reviewer:
        return [failure("OCR_ANNOTATION_REVIEWER_MISSING", "reviewer is required for ready_for_eval")]
    if labeler == reviewer:
        return [failure("OCR_ANNOTATION_REVIEWER_EQUALS_LABELER", "reviewer must be different from labeler")]
    return []


def required_sections_for_scenario(scenario: str | None) -> set[str]:
    scenario = str(scenario or "")
    if scenario in {"piping_table_profile", "quality_gate_profile"}:
        return {"fields", "tables"}
    if scenario in {"seal_text_profile", "fragment_seal_profile"}:
        return {"seals"}
    if scenario in {"evidence_profile"}:
        return {"fields", "tables", "seals"}
    if scenario in {
        "quality_certificate_profile",
        "ndt_rt_profile",
        "ndt_ut_profile",
        "construction_record_profile",
        "welding_record_profile",
        "qualification_certificate_profile",
    }:
        return {"fields", "seals"}
    return set()


def list_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []


def positive_bbox(value: Any) -> bool:
    extents = bbox_extents(value)
    if not extents:
        return False
    x1, y1, x2, y2 = extents
    return x2 > x1 and y2 > y1


def bbox_extents(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        numbers = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if len(numbers) >= 6:
        xs = numbers[0::2]
        ys = numbers[1::2]
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)
    x1, y1, x2, y2 = numbers[:4]
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def positive_polygon(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 3:
        return False
    try:
        xs = [float(point[0]) for point in value if isinstance(point, list) and len(point) >= 2]
        ys = [float(point[1]) for point in value if isinstance(point, list) and len(point) >= 2]
    except (TypeError, ValueError):
        return False
    return bool(xs and ys and max(xs) > min(xs) and max(ys) > min(ys))


def bbox_inside_page(value: Any, dimensions: tuple[int, int]) -> bool:
    extents = bbox_extents(value)
    if not extents:
        return False
    width, height = dimensions
    x1, y1, x2, y2 = extents
    return x1 >= 0 and y1 >= 0 and x2 <= width and y2 <= height


def polygon_inside_page(value: Any, dimensions: tuple[int, int]) -> bool:
    if not positive_polygon(value):
        return False
    width, height = dimensions
    try:
        return all(0 <= float(point[0]) <= width and 0 <= float(point[1]) <= height for point in value)
    except (TypeError, ValueError):
        return False


def positive_int(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def seal_type_allowed(value: str) -> bool:
    return value in KNOWN_SEAL_TYPES or value.startswith("visual_") or value.endswith("_seal")


def failure(code: str, message: str, *, field: str | None = None) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    if field:
        payload["field"] = field
    return payload
