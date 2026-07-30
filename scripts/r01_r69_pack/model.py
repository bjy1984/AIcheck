from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Line:
    id: str
    scenario: str
    material_batch_ids: tuple[str, ...]
    specification: str
    design_pressure_mpa: float
    design_temperature_c: float


@dataclass(frozen=True)
class MaterialBatch:
    id: str
    scenario: str
    grade: str
    standard: str
    heat_number: str


@dataclass(frozen=True)
class Weld:
    id: str
    scenario: str
    line_id: str
    material_batch_id: str
    completed_on: str
    status: str
    repair_count: int = 0


@dataclass(frozen=True)
class PersonRef:
    id: str
    name: str
    role: str
    synthetic: bool


@dataclass(frozen=True)
class CertificateRef:
    id: str
    holder_id: str
    certificate_type: str
    synthetic: bool


@dataclass(frozen=True)
class ProjectMaster:
    project: dict[str, Any]
    organizations: tuple[dict[str, Any], ...]
    people: tuple[PersonRef, ...]
    certificates: tuple[CertificateRef, ...]
    lines: tuple[Line, ...]
    material_batches: tuple[MaterialBatch, ...]
    welds: tuple[Weld, ...]
    scenario_timeline: tuple[dict[str, str], ...]

    def validate(self) -> list[str]:
        errors: list[str] = []
        if len(self.lines) != 11:
            errors.append(f"管线数量应为11，实际为{len(self.lines)}")
        if len(self.welds) != 30:
            errors.append(f"焊口数量应为30，实际为{len(self.welds)}")
        if len(self.material_batches) != 5:
            errors.append(f"主要材料批次数量应为5，实际为{len(self.material_batches)}")

        def duplicate_ids(items: tuple[Any, ...], label: str) -> None:
            ids = [item.id for item in items]
            duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
            if duplicates:
                errors.append(f"{label}存在重复编号：{', '.join(duplicates)}")

        duplicate_ids(self.lines, "管线")
        duplicate_ids(self.material_batches, "材料批次")
        duplicate_ids(self.welds, "焊口")
        duplicate_ids(self.people, "人员")
        duplicate_ids(self.certificates, "证书")

        line_ids = {line.id for line in self.lines}
        material_ids = {batch.id for batch in self.material_batches}
        people_ids = {person.id for person in self.people}
        organization_ids = {org["id"] for org in self.organizations}

        for line in self.lines:
            missing = set(line.material_batch_ids) - material_ids
            if missing:
                errors.append(f"管线{line.id}引用缺失材料：{', '.join(sorted(missing))}")
        for weld in self.welds:
            if weld.line_id not in line_ids:
                errors.append(f"焊口{weld.id}引用缺失管线：{weld.line_id}")
            if weld.material_batch_id not in material_ids:
                errors.append(f"焊口{weld.id}引用缺失材料：{weld.material_batch_id}")
            if weld.repair_count < 0 or weld.repair_count > 2:
                errors.append(f"焊口{weld.id}返修次数越界：{weld.repair_count}")
            try:
                completed = date.fromisoformat(weld.completed_on)
            except ValueError:
                errors.append(f"焊口{weld.id}日期格式错误：{weld.completed_on}")
            else:
                if completed.year != 2026:
                    errors.append(f"测试焊口{weld.id}日期必须在2026年")

        for person in self.people:
            if person.synthetic and not person.id.startswith("TEST-"):
                errors.append(f"合成人员编号缺少TEST前缀：{person.id}")
        for certificate in self.certificates:
            if certificate.synthetic and not certificate.id.startswith("TEST-"):
                errors.append(f"合成证书编号缺少TEST前缀：{certificate.id}")
            if (
                certificate.holder_id not in people_ids
                and certificate.holder_id not in organization_ids
            ):
                errors.append(
                    f"证书{certificate.id}引用缺失主体：{certificate.holder_id}"
                )
        for organization in self.organizations:
            if organization.get("synthetic") and not organization["id"].startswith("TEST-"):
                errors.append(f"合成单位编号缺少TEST前缀：{organization['id']}")

        expected_project = (
            "珠海恒基达鑫国际化工仓储股份有限公司"
            "一、二期装车站新增两套卸车系统项目"
        )
        if self.project.get("name") != expected_project:
            errors.append("项目名称与既有图纸不一致")
        if self.project.get("designOrganization") != "广东星燃石化设计院有限公司":
            errors.append("设计单位与既有图纸不一致")
        if self.project.get("drawingPrefix") != "QX201903S-13-Y":
            errors.append("图号前缀与既有图纸不一致")

        dates: list[date] = []
        for event in self.scenario_timeline:
            try:
                dates.append(date.fromisoformat(event["date"]))
            except (KeyError, ValueError):
                errors.append(f"时间线记录无效：{event}")
        if dates and dates != sorted(dates):
            errors.append("测试时间线不是按日期递增")

        return errors


def _line(payload: dict[str, Any]) -> Line:
    return Line(
        id=payload["id"],
        scenario=payload["scenario"],
        material_batch_ids=tuple(payload["materialBatchIds"]),
        specification=payload["specification"],
        design_pressure_mpa=float(payload["designPressureMpa"]),
        design_temperature_c=float(payload["designTemperatureC"]),
    )


def _material(payload: dict[str, Any]) -> MaterialBatch:
    return MaterialBatch(
        id=payload["id"],
        scenario=payload["scenario"],
        grade=payload["grade"],
        standard=payload["standard"],
        heat_number=payload["heatNumber"],
    )


def _weld(payload: dict[str, Any]) -> Weld:
    return Weld(
        id=payload["id"],
        scenario=payload["scenario"],
        line_id=payload["lineId"],
        material_batch_id=payload["materialBatchId"],
        completed_on=payload["completedOn"],
        status=payload["status"],
        repair_count=int(payload.get("repairCount", 0)),
    )


def load_project_master(path: Path) -> ProjectMaster:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ProjectMaster(
        project=payload["project"],
        organizations=tuple(payload["organizations"]),
        people=tuple(PersonRef(**row) for row in payload["people"]),
        certificates=tuple(CertificateRef(**row) for row in payload["certificates"]),
        lines=tuple(_line(row) for row in payload["lines"]),
        material_batches=tuple(_material(row) for row in payload["materialBatches"]),
        welds=tuple(_weld(row) for row in payload["welds"]),
        scenario_timeline=tuple(payload["scenarioTimeline"]),
    )
