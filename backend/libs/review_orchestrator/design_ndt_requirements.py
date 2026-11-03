"""Extract explicit clause-local NDT requirements without borrowing another method's values."""
from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from libs.regulatory_tables import acceptance_level_meets, ndt_acceptance_level

METHOD_RE = re.compile(r"相控阵(?:超声)?|超声相控阵|射线|超声|渗透|磁粉|(?<![A-Za-z])(?:PAUT|TOFD|RT|UT|PT|MT)(?![A-Za-z])", re.IGNORECASE)
COVERAGE_RE = re.compile(r"(?:检测比例|抽检比例|检测率|比例)\s*[:：]?\s*(?:不低于|不少于|≥|>=)?\s*(\d{1,3})\s*%")
# 管道特性表的单元格只写「RT10%」，表头「检验比例%」在另一行，上面那条找不到关键词
METHOD_COVERAGE_RE = re.compile(r"(?<![A-Za-z])(?:PAUT|TOFD|RT|UT|PT|MT)\s*[-:：]?\s*(\d{1,3})\s*%", re.IGNORECASE)
LEVEL_RE = re.compile(r"(?<![A-Za-z0-9])((?:不符合|不满足|未达到|不低于|不高于|低于|高于)?\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX0-9/／或者至—–-]+)\s*级(?:\s*(不合格|未合格))?", re.IGNORECASE)
_ALIASES = {"射线": "RT", "超声": "UT", "渗透": "PT", "磁粉": "MT",
            "相控阵": "PAUT", "相控阵超声": "PAUT", "超声相控阵": "PAUT"}


def _common(rows: list[dict[str, Any]], key: str) -> Any:
    values = [row.get(key) for row in rows]
    return values[0] if values and values[0] is not None and all(value == values[0] for value in values) else None


def _values_by_method(rows: list[dict[str, Any]], key: str) -> dict[str, list[Any]] | None:
    """同一方法在别处（图签、正文）只被提到、没写数值，不抹掉表里写明的值；有方法一处数值都没有才算缺。"""
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        values = grouped.setdefault(row["method"], [])
        if row.get(key) is not None and row[key] not in values:
            values.append(row[key])
    return grouped if grouped and all(grouped.values()) else None


def method_value_summary(rows: list[dict[str, Any]], key: str, suffix: str) -> str | None:
    grouped = _values_by_method(rows, key)
    if grouped is None:
        return None
    distinct = {value for values in grouped.values() for value in values}
    if len(distinct) == 1:
        return f"{distinct.pop()}{suffix}"
    return "；".join(f"{method}: {value}{suffix}" for method, values in grouped.items() for value in values)


def design_ndt_requirements(text: str) -> dict[str, Any]:
    rows = []
    for clause in re.split(r"[;；。\n]+", text):
        matches = list(METHOD_RE.finditer(clause))
        methods = list(dict.fromkeys(_ALIASES.get(match.group().upper(), match.group().upper()) for match in matches))
        if not methods:
            continue
        coverages, levels = list(COVERAGE_RE.finditer(clause)), list(LEVEL_RE.finditer(clause))
        keyword_spans = [match.span(1) for match in coverages]
        coverages += [match for match in METHOD_COVERAGE_RE.finditer(clause) if match.span(1) not in keyword_spans]
        # Multiple methods share values only when written as an explicit list.
        # A prose relation such as "RT替代UT" does not assert equal requirements.
        shared = len(methods) == 1 or all(
            re.fullmatch(r"[\s、,，+和及与（）()]*", clause[left.end():right.start()])
            for left, right in pairwise(matches))
        ratio = int(coverages[0].group(1)) if shared and len(coverages) == 1 else None
        level = levels[0].group(1).strip() if shared and len(levels) == 1 and not levels[0].group(2) else None
        for method in methods:
            required = ndt_acceptance_level(method, coverage_percent=ratio) if shared else None
            rows.append({"method": method, "coveragePercent": ratio, "acceptanceLevel": level,
                         "requiredAcceptance": required,
                         "acceptanceLevelMeetsRequirement": acceptance_level_meets(level, required["level"]) if level and required and required.get("level") else None,
                         "quotedText": clause.strip(),
                         "associationResolved": shared and len(coverages) <= 1 and len(levels) <= 1})
    checks = _values_by_method(rows, "acceptanceLevelMeetsRequirement")
    flat = [row["acceptanceLevelMeetsRequirement"] for row in rows]
    acceptance = False if False in flat else True if checks is not None else None
    return {"methods": list(dict.fromkeys(row["method"] for row in rows)), "methodRequirements": rows,
            "coveragePercent": _common(rows, "coveragePercent"), "acceptanceLevel": _common(rows, "acceptanceLevel"),
            "requiredAcceptance": _common(rows, "requiredAcceptance"), "acceptanceLevelMeetsRequirement": acceptance}
