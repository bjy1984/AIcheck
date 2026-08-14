from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from uuid import uuid4

TOOL_NAME = "ocr.welder_certificate.extract"
TOOL_VERSION = "welder-certificate-extractor-v1"

DATE_RE = re.compile(
    r"(?:19|20)\d{2}\s*[.。,\-/年]\s*\d{1,2}\s*[.。,\-/月]\s*\d{1,2}\s*(?:日)?"
)
ID_NO_RE = re.compile(r"\b\d{17}[\dXx]\b")
ARCHIVE_NO_RE = re.compile(r"\b(?:TS)?[A-Z0-9]{8,24}\b", re.IGNORECASE)
OP_PREFIX_RE = re.compile(r"\b(?:GT(?:AW|AT|AN|AI)|SMAW|GMAW|FCAW|SAW|PAW|OFW)\b", re.IGNORECASE)
OP_TOKEN_RE = re.compile(
    r"\b(?:GT(?:AW|AT|AN|AI)|SMAW|GMAW|FCAW|SAW|PAW|OFW)"
    r"[-—－][A-Za-z0-9ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVXLCDMivxlcdm一二三四五六七八九十"
    r"\-/()（）.,。]+",
    re.IGNORECASE,
)


FIELD_DEFINITIONS = {
    "welder_name": ("姓名", "welderName"),
    "welder_certificate_no": ("证件编号", "certificateNo"),
    "welder_archive_no": ("档案编号", "archiveNo"),
    "issuing_authority": ("发证机关", "issuingAuthority"),
}


def extract_welder_certificate_from_ocr_result(
    raw: dict[str, Any] | None = None,
    *,
    text: str | None = None,
) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    fragments = normalize_fragments(source.get("fragments") if source else None, text)
    lines = text_lines(text if text is not None else text_from_fragments(fragments))
    fields = {
        "welderName": field_value("姓名", lines, fragments, name_candidate),
        "certificateNo": field_value("证件编号", lines, fragments, certificate_no_candidate),
        "archiveNo": field_value(
            "档案编号",
            lines,
            fragments,
            archive_no_candidate,
            aliases=["档案标号"],
        ),
        "issuingAuthority": field_value(
            "发证机关",
            lines,
            fragments,
            issuing_authority_candidate,
        ),
    }
    qualified_items = extract_qualified_items(lines)
    diagnostics = build_diagnostics(fields, qualified_items)
    return {
        "toolName": TOOL_NAME,
        "toolVersion": TOOL_VERSION,
        "documentType": "welder_certificate",
        "fields": fields,
        "qualifiedItems": qualified_items,
        "verificationSignals": build_verification_signals(fields, qualified_items),
        "diagnostics": diagnostics,
    }


def extract_welder_certificate_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("ocrResult"), dict):
        return extract_welder_certificate_from_ocr_result(payload["ocrResult"])
    if isinstance(payload.get("parseResult"), dict):
        return extract_welder_certificate_from_ocr_result(payload["parseResult"])
    return extract_welder_certificate_from_ocr_result(payload, text=payload.get("text"))


def welder_certificate_ocr_fields(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    fields = extraction.get("fields") if isinstance(extraction, dict) else {}
    if not isinstance(fields, dict):
        return output
    for field_code, (field_name, public_key) in FIELD_DEFINITIONS.items():
        item = fields.get(public_key)
        if not isinstance(item, dict) or not item.get("value"):
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        output.append(
            {
                "fieldCode": field_code,
                "fieldName": field_name,
                "fieldValue": item["value"],
                "pageNo": int(evidence.get("pageNo") or 1),
                "bbox": evidence.get("bbox"),
                "coordinateSystem": evidence.get("coordinateSystem"),
                "confidence": item.get("confidence", evidence.get("confidence", 0.0)),
                "qualityFlags": item.get("qualityFlags") or [],
                "extractionMethod": TOOL_NAME,
                "sourceEngine": evidence.get("sourceEngine") or "welder_certificate_tool",
            }
        )
    first_item = first_qualified_item(extraction)
    if first_item:
        output.extend(
            [
                qualified_item_field(
                    "welder_operation_item_code",
                    "作业项目代号",
                    first_item,
                    "operationItemCode",
                ),
                qualified_item_field("approval_date", "批准日期", first_item, "approvalDate"),
                qualified_item_field("valid_until", "有效日期", first_item, "validUntil"),
            ]
        )
    return [item for item in output if item.get("fieldValue")]


def welder_certificate_ocr_tables(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    rows = extraction.get("qualifiedItems") if isinstance(extraction, dict) else []
    if not isinstance(rows, list) or not rows:
        return []
    normalized_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized_rows.append(
            {
                "itemNo": row.get("itemNo"),
                "operationItemCode": row.get("operationItemCode"),
                "approvalDate": row.get("approvalDate"),
                "validUntil": row.get("validUntil"),
                "validityStatus": row.get("validityStatus"),
            }
        )
    if not normalized_rows:
        return []
    return [
        {
            "tableId": "welder_qualified_item_table_profile",
            "tableName": "焊工资格作业项目",
            "businessSchema": "welder_qualified_item_table",
            "businessSchemas": ["welder_qualified_item_table"],
            "headers": [
                "序号",
                "作业项目代号",
                "批准日期",
                "有效日期",
                "有效性",
            ],
            "normalizedRows": normalized_rows,
            "cells": [],
            "structureConfidence": average(
                row.get("confidence") for row in rows if isinstance(row, dict)
            ),
            "qualityFlags": ["welder_certificate_schema_match"],
            "extractionMethod": TOOL_NAME,
        }
    ]


def normalize_fragments(raw: Any, fallback_text: str | None = None) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if fallback_text:
        return [{"pageNo": 1, "text": fallback_text, "confidence": 0.0}]
    return []


def text_from_fragments(fragments: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(item.get("text") or "")
        for item in fragments
        if str(item.get("text") or "").strip()
    )


def text_lines(text: str) -> list[str]:
    normalized = (
        str(text or "")
        .replace("\u3000", " ")
        .replace("\r", "\n")
        .replace("：", ":")
        .replace("，", ",")
    )
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def field_value(
    label: str,
    lines: list[str],
    fragments: list[dict[str, Any]],
    value_picker: Any,
    *,
    aliases: list[str] | None = None,
) -> dict[str, Any] | None:
    labels = [label, *(aliases or [])]
    for index, line in enumerate(lines):
        if not any(item in line for item in labels):
            continue
        candidates = [label_tail(line, labels), *lines[index + 1 : index + 5]]
        for candidate in candidates:
            value = value_picker(candidate)
            if value:
                return {
                    "value": value,
                    "confidence": 0.78,
                    "evidence": fragment_for_line(fragments, line)
                    or {"pageNo": 1, "text": line, "confidence": 0.0},
                }
    return None


def label_tail(line: str, labels: list[str]) -> str:
    tail = line
    for label in labels:
        if label in tail:
            tail = tail.split(label, 1)[-1]
            break
    return tail.strip(" :;；-—")


def name_candidate(text: str) -> str | None:
    cleaned = re.sub(r"[^一-龥·]", "", text)
    if 2 <= len(cleaned) <= 6:
        return cleaned
    return None


def certificate_no_candidate(text: str) -> str | None:
    match = ID_NO_RE.search(text.replace(" ", ""))
    return match.group(0).upper() if match else None


def archive_no_candidate(text: str) -> str | None:
    compact = re.sub(r"[^A-Za-z0-9]", "", text)
    if not compact:
        return None
    if ID_NO_RE.fullmatch(compact):
        return compact.upper()
    if compact.upper().startswith("TS") and 10 <= len(compact) <= 24:
        return compact.upper()
    match = ARCHIVE_NO_RE.search(compact)
    if match and len(match.group(0)) >= 10:
        return match.group(0).upper()
    return None


def issuing_authority_candidate(text: str) -> str | None:
    cleaned = re.sub(r"[^一-龥A-Za-z0-9（）()·]", "", text)
    if (
        any(token in cleaned for token in ["局", "总局", "委员会", "厅"])
        and 4 <= len(cleaned) <= 32
    ):
        return cleaned
    return None


def extract_qualified_items(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    buffer: list[str] = []
    for line in lines:
        if "作业项目代号" in line or "批准日期" in line or "有效日期" in line:
            continue
        if OP_PREFIX_RE.search(line) or buffer:
            buffer.append(line)
            joined = " ".join(buffer)
            dates = [normalize_date(match.group(0)) for match in DATE_RE.finditer(joined)]
            codes = operation_codes(joined)
            if codes and len(dates) >= 2:
                item = {
                    "itemNo": len(items) + 1,
                    "operationItemCode": " 和 ".join(codes),
                    "operationItemCodes": codes,
                    "approvalDate": dates[0],
                    "validUntil": dates[1],
                    "validityStatus": validity_status(dates[1]),
                    "evidenceText": joined,
                    "confidence": (
                        0.74
                        if any("requires_original_review" in code for code in codes)
                        else 0.82
                    ),
                }
                items.append(item)
                buffer = []
            elif len(joined) > 360:
                buffer = []
    return items


def operation_codes(text: str) -> list[str]:
    compact = re.sub(r"\s*([-/()（）])\s*", r"\1", text)
    compact = re.sub(r"\s+", " ", compact)
    values: list[str] = []
    for match in OP_TOKEN_RE.finditer(compact):
        code = normalize_operation_code(match.group(0))
        if code and code not in values:
            values.append(code)
    return values


def normalize_operation_code(raw: str) -> str:
    value = (
        raw.strip()
        .replace("—", "-")
        .replace("－", "-")
        .replace("（", "(")
        .replace("）", ")")
        .replace("。", ".")
        .replace(",", "/")
    )
    value = re.sub(r"^GT(?:AT|AN|AI)-", "GTAW-", value, flags=re.IGNORECASE)
    value = re.sub(r"[^A-Za-z0-9ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩivxlcdmIVXLCDM\-/().]", "", value)
    value = (
        value.replace("FeIV", "FeⅣ")
        .replace("Feiv", "FeⅣ")
        .replace("FeII", "FeⅡ")
        .replace("Feii", "FeⅡ")
    )
    return value


def normalize_date(raw: str) -> str:
    parts = re.findall(r"\d+", raw)
    if len(parts) < 3:
        return raw.strip()
    return f"{int(parts[0]):04d}.{int(parts[1]):02d}.{int(parts[2]):02d}"


def validity_status(valid_until: str) -> str:
    try:
        deadline = datetime.strptime(valid_until, "%Y.%m.%d").date()
    except ValueError:
        return "unknown"
    return "valid" if deadline >= date.today() else "expired"


def first_qualified_item(extraction: dict[str, Any]) -> dict[str, Any] | None:
    rows = extraction.get("qualifiedItems") if isinstance(extraction, dict) else []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def qualified_item_field(
    field_code: str,
    field_name: str,
    row: dict[str, Any],
    row_key: str,
) -> dict[str, Any]:
    return {
        "fieldCode": field_code,
        "fieldName": field_name,
        "fieldValue": row.get(row_key),
        "pageNo": 1,
        "bbox": None,
        "confidence": row.get("confidence", 0.0),
        "qualityFlags": [],
        "extractionMethod": TOOL_NAME,
        "sourceEngine": "welder_certificate_tool",
    }


def fragment_for_line(fragments: list[dict[str, Any]], line: str) -> dict[str, Any] | None:
    if not line:
        return None
    compact_line = re.sub(r"\s+", "", line)
    for fragment in fragments:
        text = re.sub(r"\s+", "", str(fragment.get("text") or ""))
        if text and (compact_line in text or text in compact_line):
            return fragment
    return None


def build_verification_signals(
    fields: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    certificate_no = value_of(fields.get("certificateNo"))
    archive_no = value_of(fields.get("archiveNo"))
    issuing_authority = value_of(fields.get("issuingAuthority"))
    expired_rows = [row for row in rows if row.get("validityStatus") == "expired"]
    missing_core = [
        name
        for name, present in {
            "certificateNo": bool(certificate_no),
            "archiveNo": bool(archive_no),
            "issuingAuthority": bool(issuing_authority),
            "qualifiedItems": bool(rows),
        }.items()
        if not present
    ]
    return {
        "hasCertificateNo": bool(certificate_no),
        "hasArchiveNo": bool(archive_no),
        "hasIssuingAuthority": bool(issuing_authority),
        "qualifiedItemCount": len(rows),
        "expiredQualifiedItemCount": len(expired_rows),
        "certificateNoLooksLikeIdNo": bool(certificate_no and ID_NO_RE.fullmatch(certificate_no)),
        "certificateNoEqualsArchiveNo": bool(
            certificate_no and archive_no and certificate_no == archive_no
        ),
        "requiresManualAuthenticityCheck": bool(missing_core or expired_rows),
        "missingCoreFields": missing_core,
    }


def build_diagnostics(fields: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for key, label in [
        ("certificateNo", "证件编号"),
        ("archiveNo", "档案编号"),
        ("issuingAuthority", "发证机关"),
    ]:
        if not fields.get(key):
            diagnostics.append(
                {
                    "code": "WELDER_CERTIFICATE_FIELD_MISSING",
                    "level": "warning",
                    "message": f"{label}未识别。",
                    "field": key,
                }
            )
    if not rows:
        diagnostics.append(
            {
                "code": "WELDER_QUALIFIED_ITEMS_MISSING",
                "level": "warning",
                "message": "未识别作业项目代号、批准日期和有效日期。",
            }
        )
    if any(row.get("validityStatus") == "expired" for row in rows):
        diagnostics.append(
            {
                "code": "WELDER_QUALIFICATION_EXPIRED",
                "level": "warning",
                "message": "存在有效日期早于当前日期的焊工作业项目。",
            }
        )
    return diagnostics


def value_of(item: Any) -> str | None:
    if isinstance(item, dict) and item.get("value"):
        return str(item["value"])
    return None


def average(values: Any) -> float:
    nums = [float(value) for value in values if value is not None]
    return round(sum(nums) / len(nums), 4) if nums else 0.0


def extraction_metadata(extraction: dict[str, Any]) -> dict[str, Any]:
    return {
        "toolName": extraction.get("toolName") or TOOL_NAME,
        "toolVersion": extraction.get("toolVersion") or TOOL_VERSION,
        "extractionId": f"WELDER-CERT-{uuid4().hex[:10].upper()}",
        "verificationSignals": extraction.get("verificationSignals") or {},
    }
