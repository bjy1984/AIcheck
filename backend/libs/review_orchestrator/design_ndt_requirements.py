"""Extract explicit clause-local NDT requirements without borrowing another method's values."""
from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from libs.regulatory_tables import acceptance_level_meets, ndt_acceptance_level

METHOD_RE = re.compile(r"相控阵(?:超声)?|超声相控阵|射线|超声|渗透|磁粉|(?<![A-Za-z])(?:PAUT|TOFD|RT|UT|PT|MT)(?![A-Za-z])", re.IGNORECASE)
COVERAGE_RE = re.compile(r"(?:检测比例|抽检比例|检测率|比例)\s*[:：]?\s*(?:不低于|不少于|≥|>=)?\s*(\d{1,3})\s*%")
LEVEL_RE = re.compile(r"(?<![A-Za-z0-9])((?:不符合|不满足|未达到|不低于|不高于|低于|高于)?\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX0-9/／或者至—–-]+)\s*级(?:\s*(不合格|未合格))?", re.IGNORECASE)
_ALIASES = {"射线": "RT", "超声": "UT", "渗透": "PT", "磁粉": "MT",
            "相控阵": "PAUT", "相控阵超声": "PAUT", "超声相控阵": "PAUT"}


def _common(rows: list[dict[str, Any]], key: str) -> Any:
    values = [row.get(key) for row in rows]
    return values[0] if values and values[0] is not None and all(value == values[0] for value in values) else None


def method_value_summary(rows: list[dict[str, Any]], key: str, suffix: str) -> str | None:
    if not rows or any(row.get(key) is None for row in rows):
        return None
    common = _common(rows, key)
    return f"{common}{suffix}" if common is not None else "；".join(f"{row['method']}: {row[key]}{suffix}" for row in rows)


def design_ndt_requirements(text: str) -> dict[str, Any]:
    rows = []
    for clause in re.split(r"[;；。\n]+", text):
        matches = list(METHOD_RE.finditer(clause))
        methods = list(dict.fromkeys(_ALIASES.get(match.group().upper(), match.group().upper()) for match in matches))
        if not methods:
            continue
        coverages, levels = list(COVERAGE_RE.finditer(clause)), list(LEVEL_RE.finditer(clause))
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
    checks = [row["acceptanceLevelMeetsRequirement"] for row in rows]
    acceptance = False if False in checks else True if checks and all(value is True for value in checks) else None
    return {"methods": list(dict.fromkeys(row["method"] for row in rows)), "methodRequirements": rows,
            "coveragePercent": _common(rows, "coveragePercent"), "acceptanceLevel": _common(rows, "acceptanceLevel"),
            "requiredAcceptance": _common(rows, "requiredAcceptance"), "acceptanceLevelMeetsRequirement": acceptance}
