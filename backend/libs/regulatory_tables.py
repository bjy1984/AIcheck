"""法规数值表（business_packs/engineering_inspection_v1/regulatory_tables.yaml）的只读访问。

规则只从这里取数值；每张表带 verifiedBy——为空的表只能产出预警口径，调用方要检查 `verified`。
"""

from __future__ import annotations

import math
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


_LEVEL_RANK = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5}
_METHOD_KEYS = {
    "RT": "radiographic",
    "射线": "radiographic",
    "UT": "ultrasonic",
    "超声": "ultrasonic",
    "TOFD": "tofd",
    "衍射时差": "tofd",
    "PAUT": "phasedArray",
    "相控阵": "phasedArray",
}


def ndt_acceptance_level(method: str, *, coverage_percent: float | None = None) -> dict[str, Any] | None:
    """GB/T 20801.1-2025 8.3.2：某种无损检测方法在该检查比例下的技术等级与合格级别。

    100% 检查与局部/抽样检查的合格级别不同——射线 100% 要 Ⅱ 级、局部才是 Ⅲ 级；
    超声 100% 要 Ⅰ 级、局部是 Ⅱ 级。设计文件写"验收等级 Ⅲ 级"配 100% 射线是不合格的，
    此前没有任何地方比这一项。比例不明时返回 None——不知道是全检还是抽检就判不了。
    """
    text = str(method or "").upper()
    key = next((value for token, value in _METHOD_KEYS.items() if token.upper() in text), None)
    if key is None:
        return None
    volumetric = table("gbt20801_inspection", "acceptance").get("volumetric") or {}
    if key in {"tofd", "phasedArray"}:
        entry = (volumetric.get("ultrasonic") or {}).get(key)
        if not entry:
            return None
        return {"method": key, "standard": (volumetric.get("ultrasonic") or {}).get("standard"), **entry}
    section = volumetric.get(key) or {}
    if coverage_percent is None:
        return None
    entry = section.get("full") if coverage_percent >= 100 else section.get("partial")
    if not entry:
        return None
    return {"method": key, "standard": section.get("standard"), "coveragePercent": coverage_percent, **entry}


def acceptance_level_meets(actual: str, required: str) -> bool | None:
    """合格级别是否达标：级别数字越小越严，实际必须不低于（即数字不大于）要求。"""
    def rank(value: Any) -> int | None:
        text = str(value or "")
        return next((score for glyph, score in _LEVEL_RANK.items() if glyph in text), None)

    actual_rank, required_rank = rank(actual), rank(required)
    if actual_rank is None or required_rank is None:
        return None
    return actual_rank <= required_rank


def base_material_classification_requirement(grade: str) -> dict[str, Any] | None:
    """母材不在 NB/T 47014-2023 表 1 时，附录 B.2 要求什么。

    表 1 查不到不等于判不了：附录 B 是规范性的，给了两条替代路径，并规定"母材归类报告"
    必须包含哪九项。返回 None 表示该牌号在表 1 里，走正常组别比对即可。
    """
    if wps_base_material_group(grade):
        return None
    annex = table("nbt47014AnnexB", "baseMaterial")
    if not annex:
        return None
    return {
        "grade": grade,
        "clause": annex.get("clause"),
        "inRangeButNotListed": annex.get("inRangeButNotListed"),
        "outOfRange": annex.get("outOfRange"),
        "requiredReport": "母材归类报告",
        "reportContents": list(annex.get("reportContents") or []),
        "retention": annex.get("retention"),
        "verified": is_verified(table("nbt47014AnnexB")),
    }


def filler_metal_classification_requirement(*, filler_class: str | None = None, standard: str | None = None) -> dict[str, Any] | None:
    """填充金属落在表 2~表 4 之外时，附录 B.3 要求什么。返回 None 表示表内已覆盖。

    表 2~表 4 列的是**类别代号**（FeT-1-1 这类）和它们对应的 NB/T 47018 系列标准，
    不是 E5015 这样的产品型号。所以判两件事：类别代号在不在表里，以及焊材执行的标准
    是不是表里所列的那几本（B.3.1.1 说的就是"有相应类别但不是所列标准中的填充金属"）。
    两个参数都不给就返回 None——没有输入不该产生要求。
    """
    code = str(filler_class or "").strip()
    standard_text = "".join(ch for ch in str(standard or "").upper() if ch.isalnum())
    if not code and not standard_text:
        return None
    tables = table("nbt47014FillerClasses").get("tables") or {}
    entries = [entry for kind in tables.values() for entry in (kind or {}).get("entries") or []]
    if code and not any(str(entry.get("fillerClass") or "").strip().upper() == code.upper() for entry in entries):
        pass  # 类别代号不在表里 → 需要归类报告
    elif standard_text and not any(
        "".join(ch for ch in str(entry.get("standard") or "").upper() if ch.isalnum()) == standard_text for entry in entries
    ):
        pass  # 类别在表里，但执行的不是表中所列标准 → B.3.1.1
    else:
        return None
    annex = table("nbt47014AnnexB", "fillerMetal")
    if not annex:
        return None
    return {
        "designation": code,
        "clause": annex.get("clause"),
        "categoryExistsButNotListedStandard": annex.get("categoryExistsButNotListedStandard"),
        "categoryNotListed": annex.get("categoryNotListed"),
        "requiredReport": "填充金属归类报告",
        "reportContents": list(annex.get("reportContents") or []),
        "retention": annex.get("retention"),
        "verified": is_verified(table("nbt47014AnnexB")),
    }


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


_TOXIC_TOKENS = ("极度危害", "高度危害", "中度危害", "轻度危害", "有毒", "剧毒")
_LEAK_TOKENS = ("泄漏危害", "易泄漏")


def medium_hazard_flags(*, toxicity: Any = None, leak_hazard: Any = None, medium: Any = None) -> dict[str, Any]:
    """从设计资料写的毒性程度/泄漏危害性栏推出两个开关，推不出来就说推不出来。

    只认资料上明确写的分级用语（GB 5044 的四档危害程度、"有毒"、"泄漏危害性"）。
    介质名称本身不拿来猜——判一种介质有没有毒要查物质清单，那不是这里该做的事，
    猜错会把有毒 GC2 管道按最宽的 Ⅳ 级算，体积检测比例要求跟着降下来。
    """
    def flag(value: Any, tokens: tuple[str, ...], negatives: set[str]) -> bool | None:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip()
        if text in negatives:
            return False
        if not text or any(word in text for word in ("待确认", "待核", "未知", "不详", "未确定")):
            return None
        return True if text in {"是", "有", "true"} or any(token in text for token in tokens) else None

    toxicity_text = str(toxicity).strip() if toxicity is not None else ""
    leak_text = str(leak_hazard).strip() if leak_hazard is not None else ""
    toxic_flag = flag(toxicity, _TOXIC_TOKENS, {"无毒", "非有毒", "无", "否", "false"})
    leak_flag = flag(leak_hazard, _LEAK_TOKENS, {"无泄漏危害", "无泄漏危害性", "非泄漏危害性介质", "无", "否", "false"})

    return {
        "toxic": toxic_flag,
        "leakHazard": leak_flag,
        "toxicitySource": toxicity_text or None,
        "leakHazardSource": leak_text or None,
        "medium": str(medium or "").strip() or None,
        "determined": leak_flag is True or (toxic_flag is not None and leak_flag is not None),
    }


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
            # 质保书上写的可能是统一数字代号（S30408 / U50207），也可能是牌号（06Cr19Ni10、20G），都认。
            # GB/T 5310 把数字代号放在 unifiedCode 而不是 alias，漏掉它按代号就查不到。
            names = {entry.get("grade"), entry.get("alias"), entry.get("unifiedCode")}
            normalized_names = {_norm_designation(name) for name in names if name}
            inferred_level = next((str(row["level"]) for row in entry.get("levels") or []
                                   if wanted_grade == _norm_designation(entry["grade"]) + _norm_designation(row["level"])), None)
            if wanted_grade not in normalized_names and inferred_level is None:
                continue
            if inferred_level and level and inferred_level.upper() != str(level).upper():
                return None
            merged: dict[str, Any] = {
                "standard": item.get("standard"),
                "grade": entry.get("grade"),
                "verified": is_verified(item),
                # 适用性写在标准层（冲击要外径与壁厚都够、维氏只在合同注明时做），
                # 调用方要按它决定某项限值下不下发，否则会拿标准不要求的项去要证据
                "applicability": dict(item.get("applicability") or {}),
                "composition": dict(entry.get("composition") or entry.get("compositionCommon") or {}),
                "mechanical": dict(entry.get("mechanical") or entry.get("mechanicalCommon") or {}),
            }
            for key in ("hotYieldRp02MPa", "hardness", "heatTreatment", "unifiedCode", "alias", "note"):
                if entry.get(key) is not None:
                    merged[key] = entry[key]
            levels = entry.get("levels") or []
            if not levels:
                return merged if level is None else None
            wanted_level = str(level or inferred_level or "").strip().upper()
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


_WELDING_METHOD_ALIASES = {
    "SMAW": "焊条电弧焊", "SAW": "埋弧焊", "GTAW": "钨极气体保护焊",
    "GMAW": "熔化极气体保护焊", "PAW": "等离子弧焊", "EGW": "气电立焊",
}


def normalize_welding_method(value: Any) -> str:
    text = str(value or "").strip()
    return _WELDING_METHOD_ALIASES.get(text.upper(), text)


def wps_specific_factors(method: str) -> dict[str, list[dict[str, Any]]]:
    """NB/T 47014-2023 表 5：某种焊接方法下，各因素按重要/补加/次要归类。

    重要因素变了要重新评定；补加因素变了要重做冲击试验；次要因素只需改 WPS，不用重新评定（5.2.1）。
    """
    section = table("nbt47014SpecificFactors")
    wanted = normalize_welding_method(method)
    if not wanted:
        return {}
    # factor 文字目前是截断的（见表里的 factorTextQuality/factorTextCaveat），
    # 分类可用、文字不可用——把这件事跟着每一条带出去，免得下游当完整句子展示或做关键词匹配。
    text_truncated = str(section.get("factorTextQuality") or "") == "truncated"
    out: dict[str, list[dict[str, Any]]] = {}
    for item in section.get("factors") or []:
        for cls, methods in (item.get("methodsByClass") or {}).items():
            if wanted in methods:
                out.setdefault(cls, []).append(
                    {
                        "seq": item.get("seq"),
                        "category": item.get("category"),
                        "factor": item.get("factor"),
                        "factorTextTruncated": text_truncated,
                    }
                )
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
    if not math.isfinite(specimen) or specimen <= 0:
        return None
    row = _coverage_row(specimen, bend)
    if row is None:
        return None
    section = table("nbt47014ThicknessCoverage")
    notes: list[str] = []
    method = normalize_welding_method(welding_method)

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
    if "注a" in raw_max and method not in _FOOTNOTE_A_METHODS:
        base_max = None
        notes.append(f"注 a 只限四种电弧焊；{method} 的母材厚度上限按表 8、表 9 或 2T、2t 另判")

    weld_max: float | None = None
    if weld_metal_thickness_mm is not None:
        try:
            t = float(weld_metal_thickness_mm)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(t) or t <= 0:
            return None
        raw_weld = str(row["weldMax"])
        if raw_weld == "2t" or t < 20:
            weld_max = 2 * t
        elif "200" in raw_weld:
            weld_max = 200.0
        elif "1.33T" in raw_weld:
            weld_max = round(1.33 * specimen, 2)
        elif "2T" in raw_weld:
            weld_max = 2 * specimen
        if "注a" in raw_weld and method not in _FOOTNOTE_A_METHODS:
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


_FILLER_KIND_BY_METHOD = {
    "焊条电弧焊": "焊条",
    "埋弧焊": "埋弧焊焊丝-焊剂组合",
    "钨极气体保护焊": "焊丝和填充丝",
    "熔化极气体保护焊": "焊丝和填充丝",
    "等离子弧焊": "焊丝和填充丝",
    "气焊": "焊丝和填充丝",
    "气电立焊": "焊丝和填充丝",
}


def filler_classes_for_group(base_material_group: str, *, welding_method: str | None = None) -> list[dict[str, Any]]:
    """NB/T 47014-2023 表 2~表 4：这个母材组该配哪一类焊材。

    给了焊接方法就只返回该方法对应的那张表（焊条走表 2、埋弧焊走表 4、其余走表 3）；
    不给方法就三张表都返回。查不到返回空列表，不猜。
    """
    wanted = str(base_material_group or "").strip()
    if not wanted:
        return []
    tables = table("nbt47014FillerClasses").get("tables") or {}
    welding_method = normalize_welding_method(welding_method)
    if welding_method and welding_method not in _FILLER_KIND_BY_METHOD:
        return []
    kinds = [_FILLER_KIND_BY_METHOD[welding_method]] if welding_method in _FILLER_KIND_BY_METHOD else list(tables)
    # 表 2~表 4 的母材组别写得比表 1 粗：表 1 是 Fe-8-1、Fe-5B-1，表 2~4 只到 Fe-8、Fe-5B。
    # 只做全等匹配时，奥氏体不锈钢、铬钼钢等 15 个组别一条焊材类别都取不到，
    # 配套性判定会把每一种焊材都判成"不配套"——那是假的不符合。
    # 所以先全等，取不到再退到父级（去掉最后一段）。
    candidates = [wanted]
    if "-" in wanted:
        parent = wanted.rsplit("-", 1)[0]
        if parent and parent != wanted:
            candidates.append(parent)
    out: list[dict[str, Any]] = []
    for group_code in candidates:
        for kind in kinds:
            for entry in (tables.get(kind) or {}).get("entries") or []:
                if str(entry.get("baseMaterialGroup")) == group_code:
                    out.append({**entry, "kind": kind, "matchedGroup": group_code})
        if out:
            break
    return out


def filler_matches_base_material(filler_class: str, base_material_grade: str, *, welding_method: str | None = None) -> dict[str, Any] | None:
    """焊材分类代号与母材牌号是否匹配（先把牌号查成组别，再比对）。

    返回 {matched, baseMaterialGroup, expectedClasses}；母材查不到组别时返回 None——
    查不到就不该给"匹配"或"不匹配"的结论。
    """
    group = wps_base_material_group(base_material_grade)
    if not group:
        return None
    code = str(filler_class or "").strip()
    expected = [item["fillerClass"] for item in filler_classes_for_group(group, welding_method=welding_method)]
    if not expected:
        # 表 2~表 4 没给这个组别的焊材类别（Fe-11A、Ni-2~Ni-5 等 6 个组别）。
        # 空集合不等于"都不配套"——照旧返回 matched=False 会把每一种焊材都判成不符合。
        return None
    return {
        "matched": code in expected,
        "fillerClass": code,
        "baseMaterialGrade": base_material_grade,
        "baseMaterialGroup": group,
        "expectedClasses": expected,
    }


def _limit_from_text(raw: Any) -> dict[str, float] | None:
    """把 "<=0.20" / "0.06-0.15" / ">=430" 变成 {min, max}；看不懂就返回 None，不猜。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.startswith("<="):
            return {"max": float(text[2:])}
        if text.startswith(">="):
            return {"min": float(text[2:])}
        if "-" in text and not text.startswith("-"):
            low, high = text.split("-", 1)
            return {"min": float(low), "max": float(high)}
        return {"min": float(text), "max": float(text)}
    except ValueError:
        return None


def welding_consumable_standard_profiles() -> dict[str, dict[str, Any]]:
    """R26 要的「产品标准限值档案」：标准号 → {chemicalComposition, mechanicalProperties}。

    evaluate_welding_consumable 拿不到这份档案时，成分与力学的每一项都报
    product_standard_limit_profile_missing，整条判定只能停在证据不足——
    2026-09-07 线上审计前一直是这个状态，而限值其实已经在法规表里。

    键按 r24_r34_tools._standard_key 的口径归一化（去掉非字母数字并转小写）。
    同一标准下多个型号的限值不同，这里按型号分组挂在 byDesignation 下，
    顶层只放该标准所有型号都相同的项——宁可少给，不给错。
    """
    import re

    section = table("weldingConsumables")
    electrodes = section.get("electrodes") or {}
    # 焊条的标准号写在段落的 sourceClause 上，焊丝写在条目自己的 standard 上——两种都认
    electrode_standard = str(electrodes.get("sourceClause") or "")
    items = [(item, electrode_standard) for item in electrodes.get("items") or []]
    items += [(item, str(item.get("standard") or "")) for item in section.get("wires") or []]
    profiles: dict[str, dict[str, Any]] = {}
    for item, standard_hint in items:
        standard = standard_hint.split("；")[0].split("（")[0].strip()
        match = re.search(r"(GB/T|NB/T|JB/T)\s?[\d.]+-\d{4}", standard)
        if not match:
            continue
        key = re.sub(r"[^a-z0-9]", "", match.group(0).lower())
        entry = profiles.setdefault(key, {"standard": match.group(0), "byDesignation": {}, "verified": is_verified(section)})
        chemistry = {
            field: parsed
            for field, raw in (item.get("depositedMetalComposition") or item.get("wireComposition") or {}).items()
            if (parsed := _limit_from_text(raw))
        }
        mech = item.get("mechanical") or {}
        mechanics: dict[str, dict[str, float]] = {}
        if mech.get("tensileMPaMin"):
            mechanics["tensileStrength"] = {"min": float(mech["tensileMPaMin"])}
        elif isinstance(mech.get("tensileMPa"), str):
            parsed = _limit_from_text(mech["tensileMPa"])
            if parsed:
                mechanics["tensileStrength"] = parsed
        if mech.get("yieldMPaMin"):
            mechanics["yieldStrength"] = {"min": float(mech["yieldMPaMin"])}
        if mech.get("elongationPctMin"):
            mechanics["elongation"] = {"min": float(mech["elongationPctMin"])}
        if mech.get("kv2JMin"):
            mechanics["impactEnergy"] = {"min": float(mech["kv2JMin"])}
        entry["byDesignation"][str(item.get("designation"))] = {
            "chemicalComposition": chemistry,
            "mechanicalProperties": mechanics,
            "commonName": item.get("commonName"),
            "impactTemperatureC": mech.get("impactTemperatureC"),
        }
    return profiles


def welding_consumable_profile_for(standard: str, designation: str | None = None) -> dict[str, Any] | None:
    """取某标准（可再指定型号）的限值档案；给了型号就直接返回那一档，供 R26 逐项比对。"""
    import re

    key = re.sub(r"[^a-z0-9]", "", str(standard or "").lower())
    profile = welding_consumable_standard_profiles().get(key)
    if profile is None or designation is None:
        return profile
    wanted = _norm_designation(designation)
    for code, entry in (profile.get("byDesignation") or {}).items():
        names = {code, entry.get("commonName")}
        if wanted in {_norm_designation(name) for name in names if name}:
            return {**entry, "standard": profile["standard"], "designation": code, "verified": profile["verified"]}
    return None


def product_inspection_rules() -> dict[str, dict[str, Any]]:
    """R14 要的「产品标准 → 强制出厂检验项」。

    只给标准正文里逐根或按批强制的项；「根据需方要求、经协商」的选项放在 conditionalItems 里，
    不进 requiredItems——那不是标准强制，拿它判不符合会冤枉人。
    """
    section = table("pipeMaterialLimits").get("productInspectionRules") or {}
    out: dict[str, dict[str, Any]] = {}
    for rule in section.get("rules") or []:
        standard = str(rule.get("standard") or "").strip()
        if not standard:
            continue
        out[standard] = {
            "requiredItems": list(rule.get("requiredItems") or []),
            "basis": rule.get("basis"),
            "conditionalItems": list(rule.get("conditionalItems") or []),
            "verified": is_verified(section),
        }
    return out
