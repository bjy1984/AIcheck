from __future__ import annotations

import re
from typing import Any


def extract_structured_seal_fields_from_lines(
    lines: list[tuple[str, float]],
    bbox: list[int] | tuple[int, int, int, int],
) -> list[dict[str, Any]]:
    field_bbox = [int(value) for value in bbox]
    normalized_lines = normalize_seal_lines(lines)
    texts = [text for text, _ in normalized_lines]
    text_blob = "\n".join(texts)
    compact_blob = re.sub(r"\s+", "", text_blob)
    fields: list[dict[str, Any]] = []

    def add(name: str, value: Any, confidence: float = 0.9) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = (name, re.sub(r"\s+", "", text))
        existing = {
            (str(item.get("fieldName")), re.sub(r"\s+", "", str(item.get("fieldValue") or "")))
            for item in fields
        }
        if key in existing:
            return
        fields.append(
            {
                "fieldName": name,
                "fieldValue": text,
                "confidence": round(float(confidence or 0.0), 4),
                "bbox": field_bbox,
            }
        )

    license_no = extract_license_no(compact_blob)
    date_text = extract_date(text_blob)
    pressure_pipe = extract_pressure_pipe_scope(texts)
    explicit_title = extract_seal_title(texts)
    design_license_context = bool(
        license_no
        and (
            pressure_pipe
            or "设计许可" in compact_blob
            or "特种设备" in compact_blob
            or "许可印章" in compact_blob
        )
    )
    if explicit_title:
        add("印章名称", explicit_title, confidence=line_confidence(normalized_lines, explicit_title))
    elif design_license_context:
        add("印章名称", "特种设备设计许可印章", confidence=0.78)

    for text, score in normalized_lines:
        for label, name in [
            ("单位名称", "单位名称"),
            ("资质证书编号", "资质证书编号"),
            ("许可证编号", "许可证编号"),
            ("许可项目", "许可项目"),
            ("许可范围", "许可范围"),
            ("有效期至", "有效期至"),
            ("有效期", "有效期"),
            ("业务范围", "业务范围"),
        ]:
            value = split_label_value(text, label)
            if value:
                add(name, value, confidence=score or 0.8)

        organization = extract_organization_name(text)
        if organization:
            add("单位名称", organization, confidence=max(score, 0.6))

    if pressure_pipe:
        add("许可项目", pressure_pipe, confidence=0.86)
    if license_no:
        add("许可证编号", license_no, confidence=0.92)
    if date_text:
        add("日期", date_text, confidence=0.86)

    person = extract_design_license_person(texts, design_license_context=design_license_context)
    if person:
        add("许可人员", person, confidence=line_confidence(normalized_lines, person) or 0.78)

    useful_text = "\n".join(text for text, _ in normalized_lines if text)
    if useful_text:
        add("识别文字", useful_text, confidence=average_score(normalized_lines))
        add("印章原文", useful_text, confidence=average_score(normalized_lines))
    return fields


def normalize_seal_lines(lines: list[tuple[str, float]]) -> list[tuple[str, float]]:
    output: list[tuple[str, float]] = []
    seen: dict[str, int] = {}
    for raw_text, raw_score in lines:
        text = normalize_seal_text(raw_text)
        if not text:
            continue
        try:
            score = float(raw_score or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        key = re.sub(r"\s+", "", text)
        if key in seen:
            index = seen[key]
            if score > output[index][1]:
                output[index] = (text, score)
            continue
        seen[key] = len(output)
        output.append((text, score))
    return output


def normalize_seal_text(value: Any) -> str:
    return (
        str(value or "")
        .replace("：", ":")
        .replace("—", "-")
        .replace("－", "-")
        .strip()
    )


def split_label_value(text: str, label: str) -> str:
    for separator in (":", "："):
        token = f"{label}{separator}"
        if token in text:
            return text.split(token, 1)[1].strip(" :;；")
    if label in text:
        return text.split(label, 1)[1].strip(" :;；")
    return ""


def extract_license_no(text: str) -> str:
    match = re.search(r"TS[A-Z0-9]{6,}[-]?\d{4}", text, flags=re.IGNORECASE)
    return match.group(0).upper() if match else ""


def extract_date(text: str) -> str:
    match = re.search(
        r"(?:19|20)\d{2}年\d{1,2}月\d{1,2}日|(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}",
        text,
    )
    if not match:
        return ""
    value = match.group(0)
    if re.search(r"\d[-/.]\d", value):
        parts = re.split(r"[-/.]", value)
        if len(parts) == 3:
            return f"{int(parts[0])}年{int(parts[1])}月{int(parts[2])}日"
    return value


def extract_pressure_pipe_scope(texts: list[str]) -> str:
    for text in texts:
        compact = re.sub(r"\s+", "", text)
        if "压力管道" in compact and not any(stop in compact for stop in ["有限公司", "业务范围"]):
            return "压力管道"
    return ""


def extract_seal_title(texts: list[str]) -> str:
    candidates = [
        text
        for text in texts
        if any(token in text for token in ["专用章", "印章", "许可章"])
        and not any(token in text for token in ["许可证编号", "资质证书编号"])
    ]
    if not candidates:
        return ""
    candidates.sort(key=lambda item: ("特种设备" not in item, "设计许可" not in item, len(item)))
    return candidates[0]


def extract_organization_name(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    match = re.search(r"[\u4e00-\u9fff（）()]{4,}?(?:设计院有限公司|设计有限公司|有限责任公司|有限公司)", compact)
    return match.group(0) if match else ""


def extract_design_license_person(texts: list[str], *, design_license_context: bool) -> str:
    if not design_license_context:
        return ""
    blocked_tokens = [
        "压力",
        "管道",
        "许可",
        "印章",
        "单位",
        "业务",
        "范围",
        "资质",
        "有效",
        "编号",
        "公司",
        "设计",
        "特种",
        "设备",
    ]
    for text in texts:
        compact = re.sub(r"\s+", "", text)
        if 2 <= len(compact) <= 4 and all("\u4e00" <= char <= "\u9fff" for char in compact):
            if not any(token in compact for token in blocked_tokens):
                return compact
    return ""


def line_confidence(lines: list[tuple[str, float]], text: str) -> float:
    normalized = re.sub(r"\s+", "", text)
    for line, score in lines:
        if re.sub(r"\s+", "", line) == normalized:
            return float(score or 0.0)
    return 0.0


def average_score(lines: list[tuple[str, float]]) -> float:
    if not lines:
        return 0.0
    return round(sum(float(score or 0.0) for _, score in lines) / len(lines), 4)
