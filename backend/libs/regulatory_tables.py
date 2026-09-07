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


def inspection_level_for_grade(pipeline_grade: str, *, toxic: bool = False) -> str | None:
    """GB/T 20801.5（征求意见稿）§6.1 按管道级别的缺省检查等级（Ⅰ～Ⅴ）。"""
    defaults = table("gbt20801_inspection", "inspectionLevels").get("gradeDefault") or {}
    grade = str(pipeline_grade or "").upper()
    if grade == "GC1" and toxic:
        return defaults.get("GC1_toxic")
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
    section = table("gbt20801_inspection", "pressureTest")
    return {"hydro": float(section.get("hydroTestRatio") or 1.5), "pneumatic": float(section.get("pneumaticTestRatioMin") or 1.1)}
