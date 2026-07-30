from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from PIL import Image
from pypdf import PdfReader

from .catalog import FOLDER_PATHS, load_catalog
from .content_factory import load_scenario_data
from .model import load_project_master
from .node_snapshot import load_node_snapshot
from .render_common import has_test_marking


PDFTOPPM = Path(
    "/Users/hankieyooly/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/bin/override/pdftoppm"
)


@dataclass(frozen=True)
class ValidationReport:
    errors: list[str]
    metrics: dict[str, int]
    checksums: dict[str, str]
    photo_ocr_attempts: int = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_health(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        if path.stat().st_size == 0:
            return ["文件为空"]
        suffix = path.suffix.lower()
        if suffix in {".docx", ".xlsx"}:
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
                if bad:
                    errors.append(f"ZIP成员损坏：{bad}")
        elif suffix == ".pdf":
            reader = PdfReader(path)
            if reader.is_encrypted:
                errors.append("PDF加密")
            if not reader.pages:
                errors.append("PDF页数为零")
            for index, page in enumerate(reader.pages, start=1):
                if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                    errors.append(f"PDF第{index}页尺寸无效")
        elif suffix in {".jpg", ".jpeg", ".png"}:
            with Image.open(path) as image:
                image.verify()
    except Exception as exc:
        errors.append(f"文件不可读：{exc}")
    return errors


def _validate_scenarios(
    scenario_data: dict[str, dict],
    errors: list[str],
) -> None:
    s02 = scenario_data["S02"]
    events = s02["events"]
    if [row["date"] for row in events] != sorted(row["date"] for row in events):
        errors.append("S02事件日期未按顺序")
    if events[-1]["status"] != "合格闭环":
        errors.append("S02未合格闭环")

    s03 = scenario_data["S03"]
    statuses = [
        row["status"]
        for row in s03["events"]
        if row["object"] == "W-S03-003"
    ]
    expected_statuses = [
        "施焊完成",
        "首次RT不合格",
        "返修批准",
        "返修完成",
        "RT复检合格",
        "焊后热处理完成",
        "硬度合格",
    ]
    if statuses != expected_statuses:
        errors.append("S03返修事件链不完整或顺序错误")
    curve = [
        row for row in s03["pwhtCurve"] if row["weld"] == "W-S03-003"
    ]
    minutes = [row["minute"] for row in curve]
    if not minutes or minutes != list(range(minutes[0], minutes[-1] + 1, 5)):
        errors.append("S03热处理曲线不连续")
    holding = [
        row["minute"]
        for row in curve
        if 660 <= row["tc1"] <= 700 and 660 <= row["tc2"] <= 700
    ]
    if not holding or max(holding) - min(holding) < 60:
        errors.append("S03热处理保温时间不足60分钟")
    if max(value for values in s03["hardness"].values() for value in values) > 225:
        errors.append("S03硬度超过225 HB")

    s04 = scenario_data["S04"]
    if any(not -1.20 <= value <= -0.85 for value in s04["cpPotentials"]):
        errors.append("S04阴保电位超出范围")
    if s04["photoOcrRequired"]:
        errors.append("S04照片不得要求OCR")

    s05 = scenario_data["S05"]
    if {row["id"] for row in s05["accessories"]} != {
        "PSV-8301-TEST",
        "RD-8301-TEST",
        "ESDV-8301-TEST",
    }:
        errors.append("S05安全附件对象不完整")
    if any(row["result"] != "合格" for row in s05["accessories"]):
        errors.append("S05安全附件存在未合格对象")

    s06 = scenario_data["S06"]
    if "B00-PRESSURE-REPORT" in s06["acceptanceEvidenceIds"]:
        errors.append("S06错误引用B00压力试验作为验收证据")
    if any(
        coverage["rt"] != 100 or coverage["mt"] != 100
        for coverage in s06["coverage"].values()
    ):
        errors.append("S06未实现100%RT和100%MT")
    if s06["leakTest"] != {"pressure_mpa": 0.55, "minutes": 30}:
        errors.append("S06泄漏试验参数错误")
    if s06["finalStatus"] != "合格闭环":
        errors.append("S06未合格闭环")


def validate_pack(root: Path) -> ValidationReport:
    package_dir = Path(__file__).parent
    data_dir = package_dir / "data"
    master = load_project_master(data_dir / "project_master.json")
    catalog = load_catalog(data_dir / "document_catalog.json")
    snapshot = load_node_snapshot(data_dir / "requirement_map.json")
    scenario_data = load_scenario_data(data_dir / "content")
    errors: list[str] = []
    checksums: dict[str, str] = {}

    if not root.exists():
        errors.append(f"资料包不存在：{root}")
        actual_files: list[Path] = []
    else:
        actual_files = sorted(path for path in root.rglob("*") if path.is_file())

    expected_directories = {
        "00_使用说明与总目录",
        *FOLDER_PATHS.values(),
    }
    actual_directories = (
        {path.name for path in root.iterdir() if path.is_dir()}
        if root.exists()
        else set()
    )
    missing_directories = expected_directories - actual_directories
    extra_directories = actual_directories - expected_directories
    if missing_directories:
        errors.append("缺少目录：" + "、".join(sorted(missing_directories)))
    if extra_directories:
        errors.append("多余目录：" + "、".join(sorted(extra_directories)))

    expected_paths: dict[Path, tuple[str, str]] = {}
    for spec in catalog.documents:
        for extension in spec.physical_extensions():
            expected = (
                root
                / spec.output_subfolder
                / f"{spec.file_stem}.{extension}"
            )
            expected_paths[expected] = (spec.logical_id, extension)
            if not expected.exists():
                if extension == "pdf" and spec.source_format in {"docx", "xlsx"}:
                    errors.append(f"缺少配对PDF：{expected.name}")
                else:
                    errors.append(f"缺少文件：{expected.name}")

    actual_set = set(actual_files)
    expected_set = set(expected_paths)
    extras = actual_set - expected_set
    if extras:
        errors.append(
            "资料包存在目录外文件："
            + "、".join(str(path.relative_to(root)) for path in sorted(extras))
        )

    for path in actual_files:
        for error in _file_health(path):
            errors.append(f"{path.name}：{error}")
        if not has_test_marking(path):
            errors.append(f"{path.name}：缺少测试专用标识")
        checksums[str(path.relative_to(root))] = _sha256(path)

    errors.extend(master.validate())
    errors.extend(catalog.validate(master, snapshot))
    if [node.code for node in snapshot.nodes] != list(range(1, 70)):
        errors.append("R节点不是R01—R69连续编号")
    if len(snapshot.requirements) != 166:
        errors.append("资料要求数量不是166")
    if snapshot.requirements_for_node(69):
        errors.append("R69不得含外部资料要求")
    if any(
        row.status not in {"已提供", "本场景不适用"}
        or not (row.locator or row.rationale)
        for row in snapshot.requirements
    ):
        errors.append("存在未解析的资料要求")
    _validate_scenarios(scenario_data, errors)

    metrics = {
        "nodes": len(snapshot.nodes),
        "requirements": len(snapshot.requirements),
        "logical_documents": len(catalog.documents),
        "physical_files": len(actual_files),
        "lines": len(master.lines),
        "welds": len(master.welds),
        "material_batches": len(master.material_batches),
    }
    if metrics["physical_files"] != 114:
        errors.append(
            f"物理文件数量应为114，实际为{metrics['physical_files']}"
        )
    return ValidationReport(
        errors=errors,
        metrics=metrics,
        checksums=checksums,
        photo_ocr_attempts=0,
    )


def render_all_pdfs(root: Path, output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    page_count = 0
    for index, path in enumerate(sorted(root.rglob("*.pdf")), start=1):
        target = output_dir / f"{index:03d}_{path.stem}"
        target.mkdir(parents=True, exist_ok=True)
        prefix = target / "page"
        subprocess.run(
            [
                str(PDFTOPPM),
                "-png",
                "-r",
                "120",
                str(path),
                str(prefix),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        page_count += len(list(target.glob("page-*.png")))
    return page_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--render-qa-dir", type=Path)
    args = parser.parse_args()
    report = validate_pack(args.root)
    for key, value in report.metrics.items():
        print(f"{key}={value}")
    print(f"photo_ocr_attempts={report.photo_ocr_attempts}")
    print(f"validation_errors={len(report.errors)}")
    for error in report.errors:
        print(error)
    if args.render_qa_dir and not report.errors:
        pages = render_all_pdfs(args.root, args.render_qa_dir)
        print(f"rendered_pdf_pages={pages}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
