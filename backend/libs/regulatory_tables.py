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


def trust_policy(path: Path | None = None) -> dict[str, Any]:
    """采信策略：mode 为 accept_without_human_signoff 时不等签字直接采信（见 YAML 顶部说明）。"""
    policy = load_tables(path).get("trustPolicy")
    return policy if isinstance(policy, dict) else {}


def accepts_without_signoff(path: Path | None = None) -> bool:
    return str(trust_policy(path).get("mode") or "") == "accept_without_human_signoff"


def is_verified(section: dict[str, Any]) -> bool:
    """这张表能不能用于"判不符合"。签字了当然可以；采信策略开着时未签字的也可以。"""
    if section.get("verifiedBy"):
        return True
    return accepts_without_signoff()


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
                "verified": is_verified(item),
                "composition": dict(entry.get("composition") or entry.get("compositionCommon") or {}),
                "mechanical": dict(entry.get("mechanical") or entry.get("mechanicalCommon") or {}),
            }
            for key in ("hotYieldRp02MPa", "hardness", "heatTreatment", "unifiedCode", "alias", "note"):
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


_IMPACT_METHODS = {"焊条电弧焊", "埋弧焊", "钨极气体保护焊", "熔化极气体保护焊", "等离子弧焊", "气电立焊"}
_FOOTNOTE_A_METHODS = {"焊条电弧焊", "埋弧焊", "钨极气体保护焊", "熔化极气体保护焊"}


def _coverage_row(specimen_t: float, bend: str) -> dict[str, Any] | None:
    section = table("nbt47014ThicknessCoverage")
    key = "longitudinalBend" if bend == "longitudinal" else "transverseBend"
    rows = (section.get(key) or {}).get("rows") or []
    # 行的区间用文字写（"20<=T<38"），这里按同一顺序判，避免再解析一遍字符串
    if bend == "longitudinal":
        bounds = [(None, 1.5), (1.5, 10.0), (10.0, None)]
    else:
        bounds = [(None, 1.5), (1.5, 10.0), (10.0, 20.0), (20.0, 38.0), (38.0, 150.0), (150.0, None)]
    for row, (low, high) in zip(rows, bounds, strict=False):
        if low is not None and specimen_t < low:
            continue
        # 表 6 的 1.5<=T<=10 与 38<=T<=150 是闭区间，边界值归本行
        closed_upper = specimen_t == high and "<=T<=" in str(row.get("specimenT", ""))
        if high is not None and specimen_t >= high and not closed_upper:
            continue
        return row
    return rows[-1] if rows else None


def wps_thickness_coverage(
    specimen_thickness_mm: float,
    *,
    weld_metal_thickness_mm: float | None = None,
    bend: str = "transverse",
    welding_method: str | None = None,
    impact_tested: bool = False,
) -> dict[str, Any] | None:
    """NB/T 47014-2023 表 6/表 7 + 6.1.5.2：一份评定报告适用于焊件的厚度范围。

    返回 baseMin/baseMax（母材）与 weldMax（焊缝金属）的**数值**，算不出来的位置返回 None
    并在 notes 里说清为什么——不猜。
    """
    try:
        specimen = float(specimen_thickness_mm)
    except (TypeError, ValueError):
        return None
    if specimen <= 0:
        return None
    row = _coverage_row(specimen, bend)
    if row is None:
        return None
    section = table("nbt47014ThicknessCoverage")
    notes: list[str] = []
    method = str(welding_method or "").strip()

    base_min: float | None = specimen if str(row["baseMin"]) == "T" else float(row["baseMin"])
    # 6.1.5.2：要求冲击试验时最小值另有规定
    if impact_tested and method in _IMPACT_METHODS:
        base_min = min(specimen, 16.0) if specimen >= 6 else specimen / 2
        notes.append(f"按 6.1.5.2（有冲击试验，{method}）取母材最小值 {base_min:g}mm")

    raw_max = str(row["baseMax"])
    if raw_max == "2T":
        base_max: float | None = 2 * specimen
    elif raw_max.startswith("200"):
        base_max = 200.0
    elif raw_max.startswith("1.33T"):
        base_max = round(1.33 * specimen, 2)
    else:
        base_max = None
    if "注a" in raw_max and method and method not in _FOOTNOTE_A_METHODS:
        base_max = None
        notes.append(f"注 a 只限四种电弧焊；{method} 的母材厚度上限按表 8、表 9 或 2T、2t 另判")

    weld_max: float | None = None
    if weld_metal_thickness_mm is not None:
        t = float(weld_metal_thickness_mm)
        raw_weld = str(row["weldMax"])
        if raw_weld == "2t" or t < 20:
            weld_max = 2 * t
        elif "200" in raw_weld:
            weld_max = 200.0
        elif "1.33T" in raw_weld:
            weld_max = round(1.33 * specimen, 2)
        elif "2T" in raw_weld:
            weld_max = 2 * specimen
        if "注a" in raw_weld and method and method not in _FOOTNOTE_A_METHODS:
            weld_max = None
            notes.append("焊缝金属厚度上限同样受注 a 限制")
    else:
        notes.append("未给试件焊缝金属厚度 t，焊缝金属上限算不出")

    return {
        "table": (section.get("longitudinalBend" if bend == "longitudinal" else "transverseBend") or {}).get("table"),
        "specimenThicknessMm": specimen,
        "specimenRange": row["specimenT"],
        "baseMetalMinMm": base_min,
        "baseMetalMaxMm": base_max,
        "weldMetalMinMm": 0.0,
        "weldMetalMaxMm": weld_max,
        "verified": is_verified(section),
        "notes": notes,
    }
