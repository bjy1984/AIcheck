"""法规数值表（business_packs/engineering_inspection_v1/regulatory_tables.yaml）的只读访问。

规则只从这里取数值；每张表带 verifiedBy——为空的表只能产出预警口径，调用方要检查 `verified`。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

TABLES_PATH = Path(__file__).resolve().parents[1] / "business_packs" / "engineering_inspection_v1" / "regulatory_tables.yaml"


@lru_cache(maxsize=2)
def _load(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_tables(path: Path | None = None) -> dict[str, Any]:
    return _load(str(path or TABLES_PATH))


def table(*keys: str, path: Path | None = None) -> dict[str, Any]:
    node: Any = load_tables(path)
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
        if node is None:
            return {}
    return node if isinstance(node, dict) else {}


def is_verified(section: dict[str, Any]) -> bool:
    return bool(section.get("verifiedBy"))


def welder_material_category(grade: str) -> str | None:
    """TSG Z6002-2026 表 A-2：牌号 → FeⅠ/FeⅡ/FeⅢ/FeⅣ（大小写、连字符不敏感）。"""
    wanted = "".join(ch for ch in str(grade or "").upper() if ch.isalnum())
    if not wanted:
        return None
    for category in table("tsgZ6002_2026", "materialCategories").get("categories") or []:
        for item in category.get("grades") or []:
            if "".join(ch for ch in str(item).upper() if ch.isalnum()) == wanted:
                return str(category.get("code"))
    return None


def wps_base_material_group(grade: str) -> str | None:
    """NB/T 47014-2023 表 1（节选）：牌号 → Fe-x-y。"""
    wanted = "".join(ch for ch in str(grade or "").upper() if ch.isalnum())
    if not wanted:
        return None
    for group in table("nbt47014_2023", "baseMaterialGroups").get("groups") or []:
        for item in group.get("grades") or []:
            key = "".join(ch for ch in str(item).split("（")[0].upper() if ch.isalnum())
            if key == wanted:
                return str(group.get("group"))
    return None


def inspection_level_for_grade(pipeline_grade: str, *, toxic: bool = False, leak_hazard: bool = False) -> str | None:
    """GB/T 20801.1-2025 §8.3.1 按管道级别的缺省检查等级（Ⅰ～Ⅴ）。

    2025 版把 GC1 整级提到 Ⅰ 级；GC2 按介质细分：泄漏危害性 → Ⅱ、有毒 → Ⅲ、其余 → Ⅳ。
    toxic/leak_hazard 只对 GC2 生效（GC1 无论介质都是 Ⅰ 级）。
    """
    defaults = table("gbt20801_inspection", "inspectionLevels").get("gradeDefault") or {}
    grade = str(pipeline_grade or "").upper()
    if grade == "GC2":
        if leak_hazard and defaults.get("GC2_leakHazard"):
            return defaults["GC2_leakHazard"]
        if toxic and defaults.get("GC2_toxic"):
            return defaults["GC2_toxic"]
    return defaults.get(grade)


def volumetric_ndt_ratio(level: str | None) -> int | None:
    """表 5-1 该检查等级对接环缝的射线/超声比例（%）；Ⅴ 级无体积检测要求 → 0。"""
    if not level:
        return None
    levels = table("gbt20801_inspection", "ratiosByLevel").get("levels") or {}
    row = levels.get(level) or {}
    volumetric = row.get("volumetric")
    if not volumetric:
        return 0 if row else None
    first = volumetric[0]
    return int(first) if first is not None else 0


def pressure_test_ratios() -> dict[str, float]:
    """液压下限、气压下限与气压上限（GB/T 20801.1-2025 8.6.1.3/8.6.1.4）。"""
    section = table("gbt20801_inspection", "pressureTest")
    return {
        "hydro": float(section.get("hydroTestRatio") or 1.5),
        "pneumatic": float(section.get("pneumaticTestRatioMin") or 1.1),
        "pneumaticMax": float(section.get("pneumaticTestRatioMax") or 1.33),
    }


def _norm_designation(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def welding_consumable_spec(designation: str) -> dict[str, Any] | None:
    """GB/T 5117 / GB/T 8110 预填表：型号或牌号（E4303 / J422 / ER50-6 / S6）→ 成分与力学性能条目。"""
    wanted = _norm_designation(designation)
    if not wanted:
        return None
    section = table("weldingConsumables")
    electrodes = section.get("electrodes") or {}
    # 焊条段落带了 sourceClause/impactRule 等元数据，条目在 items 里；焊丝仍是裸列表
    candidates = list(electrodes.get("items") or []) if isinstance(electrodes, dict) else list(electrodes)
    candidates += list(section.get("wires") or [])
    for item in candidates:
        keys = {item.get("designation"), item.get("commonName")}
        classification = str(item.get("classification2020") or "")
        if classification:
            keys.add(classification.split("（")[0])
        if wanted in {_norm_designation(k) for k in keys if k}:
            return item
    return None


def pipe_material_limits(standard: str, grade: str, level: str | None = None) -> dict[str, Any] | None:
    """P10 管材限值：按标准号 + 牌号（+ 质量等级）取成分与力学限值。

    Q345 这类带质量等级的牌号，成分与力学分两层：compositionCommon/mechanicalCommon 是各级共有，
    levels 里是该级独有（C、P、S、伸长率、冲击温度与能量）。返回的是合并后的一份，
    调用方不用关心分层；查不到返回 None，不猜。
    """
    wanted_standard = _norm_designation(standard)
    wanted_grade = _norm_designation(grade)
    if not wanted_standard or not wanted_grade:
        return None
    for item in table("pipeMaterialLimits").get("standards") or []:
        if _norm_designation(item.get("standard")) != wanted_standard:
            continue
        for entry in item.get("grades") or []:
            # 质保书上写的可能是统一数字代号（S30408），也可能是牌号（06Cr19Ni10），两种都认
            names = {entry.get("grade"), entry.get("alias")}
            if wanted_grade not in {_norm_designation(name) for name in names if name}:
                continue
            merged: dict[str, Any] = {
                "standard": item.get("standard"),
                "grade": entry.get("grade"),
                "verified": bool(item.get("verifiedBy")),
                "composition": dict(entry.get("composition") or entry.get("compositionCommon") or {}),
                "mechanical": dict(entry.get("mechanical") or entry.get("mechanicalCommon") or {}),
            }
            for key in ("hotYieldRp02MPa", "note"):
                if entry.get(key) is not None:
                    merged[key] = entry[key]
            levels = entry.get("levels") or []
            if not levels:
                return merged if level is None else None
            wanted_level = str(level or "").strip().upper()
            row = next((item2 for item2 in levels if str(item2.get("level") or "").upper() == wanted_level), None)
            if row is None:
                merged["availableLevels"] = [str(item2.get("level")) for item2 in levels]
                return merged
            merged["level"] = row["level"]
            for key, value in row.items():
                if key == "level":
                    continue
                if key in {"elongationPctMin", "impactTemperatureC", "kv2JMin"}:
                    merged["mechanical"][key] = value
                else:
                    merged["composition"][key] = value
            return merged
    return None


def wps_specific_factors(method: str) -> dict[str, list[dict[str, Any]]]:
    """NB/T 47014-2023 表 5：某种焊接方法下，各因素按重要/补加/次要归类。

    重要因素变了要重新评定；补加因素变了要重做冲击试验；次要因素只需改 WPS，不用重新评定（5.2.1）。
    """
    section = table("nbt47014SpecificFactors")
    wanted = str(method or "").strip()
    if not wanted:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for item in section.get("factors") or []:
        for cls, methods in (item.get("methodsByClass") or {}).items():
            if wanted in methods:
                out.setdefault(cls, []).append({"seq": item.get("seq"), "category": item.get("category"), "factor": item.get("factor")})
    return out


def wps_factor_class(method: str, keyword: str) -> str | None:
    """某方法下，含该关键词的因素属于哪一类；命中多条时按 重要 > 补加 > 次要 取最严的一档。"""
    wanted = str(keyword or "").strip()
    if not wanted:
        return None
    ranked = ["重要因素", "补加因素", "次要因素"]
    found = None
    for cls, items in wps_specific_factors(method).items():
        hit = any(wanted in str(item.get("factor") or "") for item in items)
        if hit and (found is None or ranked.index(cls) < ranked.index(found)):
            found = cls
    return found
