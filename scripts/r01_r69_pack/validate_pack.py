from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

from PIL import Image
from pypdf import PdfReader

from .catalog import FOLDER_PATHS, load_catalog
from .content_factory import STANDARDS, load_scenario_data
from .model import load_project_master
from .node_snapshot import load_node_snapshot
from .render_common import has_signature_marking, has_test_marking


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


def _searchable_payload(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".docx", ".xlsx"}:
        with zipfile.ZipFile(path) as archive:
            return b"\n".join(
                archive.read(name)
                for name in archive.namelist()
                if name.endswith(".xml") or name.endswith(".rels")
            ).decode("utf-8", errors="ignore")
    if suffix == ".pdf":
        reader = PdfReader(path)
        metadata = " ".join(str(value) for value in (reader.metadata or {}).values())
        return metadata + "\n" + "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    if suffix in {".jpg", ".jpeg", ".png"}:
        with Image.open(path) as image:
            comment = image.info.get("comment", b"")
            if isinstance(comment, bytes):
                comment = comment.decode("utf-8", errors="ignore")
            return f"{comment} {' '.join(str(value) for value in image.getexif().values())}"
    return ""


def _validate_source_evidence(
    source_rows: list[dict],
    source_root: Path,
    errors: list[str],
) -> None:
    if len(source_rows) != 12:
        errors.append(f"引用原始证据应为12份，实际为{len(source_rows)}份")
    for row in source_rows:
        path = source_root / row["path"]
        if not path.exists():
            errors.append(f"缺少引用原始证据：{row['path']}")
            continue
        if _sha256(path) != row.get("sha256"):
            errors.append(f"原始证据哈希不一致：{row['path']}")
        try:
            page_count = len(PdfReader(path).pages)
        except Exception as exc:
            errors.append(f"原始证据不可读：{row['path']}：{exc}")
            continue
        if page_count != row.get("pageCount"):
            errors.append(
                f"原始证据页数不一致：{row['path']}，"
                f"登记{row.get('pageCount')}页，实际{page_count}页"
            )
        if row.get("status") != "已绑定":
            errors.append(f"原始证据未绑定：{row['path']}")


def _validate_control_closures(
    scenario_data: dict[str, dict],
    data_dir: Path,
    errors: list[str],
) -> None:
    closures = scenario_data["M00"].get("dataClosures", [])
    expected_categories = {"壁厚", "介质", "管线范围", "无损检测单位", "证书时效"}
    if {row.get("category") for row in closures} != expected_categories:
        errors.append("数据一致性闭环项不完整")
    if any(row.get("status") != "已闭环" for row in closures):
        errors.append("数据一致性存在未闭环项")

    registry = scenario_data["M00"].get("signatureRegistry", [])
    if len(registry) != 76 or any(row.get("status") != "已登记" for row in registry):
        errors.append("测试专用签章登记台账不完整")

    r69 = scenario_data["V00"]
    statuses = [row.get("status") for row in r69.get("r69Workflow", [])]
    if statuses != ["发现定位缺页", "补录页码与哈希", "复核合格", "合格闭环"]:
        errors.append("R69工作流异常整改链不完整或顺序错误")
    if r69.get("finalStatus") != "合格闭环":
        errors.append("R69工作流未合格闭环")

    m00_content = json.loads(
        (data_dir / "content/M00.json").read_text(encoding="utf-8")
    )
    standard_rows = m00_content["documents"]["M00-STD-001"]["workbook"]["sheets"][0]["rows"]
    if standard_rows != STANDARDS:
        errors.append("标准版本台账与已核定标准清单不一致")


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


def validate_pack(
    root: Path,
    *,
    source_root: Path | None = None,
) -> ValidationReport:
    package_dir = Path(__file__).parent
    data_dir = package_dir / "data"
    master = load_project_master(data_dir / "project_master.json")
    catalog = load_catalog(data_dir / "document_catalog.json")
    snapshot = load_node_snapshot(data_dir / "requirement_map.json")
    scenario_data = load_scenario_data(data_dir / "content")
    source_root = source_root or Path(__file__).resolve().parents[2]
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

    signed_generated_files = 0
    national_id_pattern = re.compile(r"(?<![0-9A-Fa-f])\d{18}(?![0-9A-Fa-f])")
    for path in actual_files:
        for error in _file_health(path):
            errors.append(f"{path.name}：{error}")
        if not has_test_marking(path):
            errors.append(f"{path.name}：缺少测试专用标识")
        if has_signature_marking(path):
            signed_generated_files += 1
        else:
            errors.append(f"{path.name}：缺少测试签章形态")
        if national_id_pattern.search(_searchable_payload(path)):
            errors.append(f"{path.name}：疑似含未脱敏18位身份证号")
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
    source_rows = scenario_data["M00"].get("sourceEvidence", [])
    _validate_source_evidence(source_rows, source_root, errors)
    _validate_control_closures(scenario_data, data_dir, errors)

    field_photos = sum("-PHOTO-" in spec.logical_id for spec in catalog.documents)
    radiographic_films = sum("-FILM-" in spec.logical_id for spec in catalog.documents)
    external_queries = sum("-QUERY-" in spec.logical_id for spec in catalog.documents)

    metrics = {
        "nodes": len(snapshot.nodes),
        "requirements": len(snapshot.requirements),
        "logical_documents": len(catalog.documents),
        "physical_files": len(actual_files),
        "referenced_source_files": len(source_rows),
        "evidence_universe_files": len(actual_files) + len(source_rows),
        "field_photos": field_photos,
        "radiographic_films": radiographic_films,
        "external_query_screenshots": external_queries,
        "signed_generated_files": signed_generated_files,
        "lines": len(master.lines),
        "welds": len(master.welds),
        "material_batches": len(master.material_batches),
    }
    if metrics["physical_files"] != 136:
        errors.append(
            f"物理文件数量应为136，实际为{metrics['physical_files']}"
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
