from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class SourceFacts:
    project_name: str
    design_organization: str
    drawing_numbers: tuple[str, ...]
    line_numbers: tuple[str, ...]
    design_pressure_mpa: float
    hydro_test_pressure_mpa: float
    base_material: str
    representative_specification: str


def _required_literal(text: str, literal: str, label: str) -> str:
    if literal not in text:
        raise ValueError(f"未在OCR来源中找到{label}：{literal}")
    return literal


def extract_source_facts(workspace: Path) -> SourceFacts:
    source = workspace / "Scan/大模型OCR结果.md"
    text = source.read_text(encoding="utf-8")
    project_name = _required_literal(
        text,
        "珠海恒基达鑫国际化工仓储股份有限公司一、二期装车站新增两套卸车系统项目",
        "项目名称",
    )
    design_organization = _required_literal(
        text,
        "广东星燃石化设计院有限公司",
        "设计单位",
    )
    drawing_numbers = tuple(
        sorted(set(re.findall(r"QX201903S-13-Y-\d{2}", text)))
    )
    line_numbers = tuple(
        sorted(set(re.findall(r"\b(?:PL830[1-6]|VT830[1-2])\b", text)))
    )
    if "0.825" not in text or "0.55" not in text:
        raise ValueError("OCR来源缺少设计压力或水压试验压力")
    source_specifications = ("Φ108×4", "Φ108 x 4", "Φ108*4", "Φ108x4")
    matched_specification = next(
        (candidate for candidate in source_specifications if candidate in text),
        None,
    )
    if matched_specification is None:
        raise ValueError("OCR来源缺少代表性规格Φ108×4")
    return SourceFacts(
        project_name=project_name,
        design_organization=design_organization,
        drawing_numbers=drawing_numbers,
        line_numbers=line_numbers,
        design_pressure_mpa=0.55,
        hydro_test_pressure_mpa=0.825,
        base_material="20#",
        representative_specification="Φ108×4",
    )
