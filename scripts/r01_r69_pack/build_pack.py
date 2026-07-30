from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from .catalog import DocumentSpec, load_catalog
from .content_factory import load_content_library, load_scenario_data
from .convert_pdf import convert_office_to_pdf, convert_xlsx_to_pdf
from .render_docx import render_docx
from .render_graphics import render_pdf_graphic, render_test_photo
from .render_xlsx import render_xlsx


PACK_FOLDER = "R01-R69全节点业务验收测试包"


@dataclass
class BuildResult:
    logical_count: int
    physical_count: int
    files: list[Path]
    documents: list[dict[str, Any]]
    scenario_data: dict[str, dict[str, Any]]
    errors: list[str] = field(default_factory=list)

    def searchable_text(self) -> str:
        return json.dumps(
            {
                "documents": self.documents,
                "scenarioData": self.scenario_data,
            },
            ensure_ascii=False,
        )

    def event_date(self, scenario: str, status: str) -> datetime:
        row = next(
            event
            for event in self.scenario_data[scenario]["events"]
            if event["status"] == status
        )
        return datetime.fromisoformat(row["date"])

    def event_statuses(self, object_id: str) -> list[str]:
        return [
            row["status"]
            for row in self.scenario_data["S03"]["events"]
            if row["object"] == object_id
        ]

    def pwht_curve_is_continuous(self, object_id: str) -> bool:
        rows = [
            row
            for row in self.scenario_data["S03"]["pwhtCurve"]
            if row["weld"] == object_id
        ]
        minutes = [row["minute"] for row in rows]
        return bool(minutes) and minutes == list(
            range(minutes[0], minutes[-1] + 1, 5)
        )

    def max_hardness(self, object_id: str) -> int:
        return max(self.scenario_data["S03"]["hardness"][object_id])

    def photo_requires_ocr(self, logical_id: str) -> bool:
        if logical_id != "S04-PHOTO-001":
            raise KeyError(logical_id)
        return bool(self.scenario_data["S04"]["photoOcrRequired"])

    def cp_potentials(self) -> list[float]:
        return self.scenario_data["S04"]["cpPotentials"]

    def accessory_ids(self) -> set[str]:
        return {
            row["id"] for row in self.scenario_data["S05"]["accessories"]
        }

    def all_accessory_results_qualified(self) -> bool:
        return all(
            row["result"] == "合格"
            for row in self.scenario_data["S05"]["accessories"]
        )

    def acceptance_evidence_ids(self) -> list[str]:
        return self.scenario_data["S06"]["acceptanceEvidenceIds"]

    def rt_coverage(self, weld_id: str) -> int:
        return self.scenario_data["S06"]["coverage"][weld_id]["rt"]

    def mt_coverage(self, weld_id: str) -> int:
        return self.scenario_data["S06"]["coverage"][weld_id]["mt"]

    def leak_test(self) -> dict[str, Any]:
        return self.scenario_data["S06"]["leakTest"]

    def final_status(self) -> str:
        return self.scenario_data["S06"]["finalStatus"]


def _load_raw(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _render_document(
    spec: DocumentSpec,
    content: dict[str, Any],
    master: dict[str, Any],
    output_root: Path,
) -> list[Path]:
    output_dir = output_root / spec.output_subfolder
    if spec.source_format == "docx":
        source = render_docx(content, master, output_dir)
        return [source, convert_office_to_pdf(source, output_dir)]
    if spec.source_format == "xlsx":
        source = render_xlsx(content, master, output_dir)
        sheet_names = [
            str(sheet.get("name", "记录"))[:31]
            for sheet in content.get("workbook", {}).get("sheets", [])
        ] or ["记录"]
        return [
            source,
            convert_xlsx_to_pdf(source, output_dir, sheet_names),
        ]
    if spec.source_format == "pdf":
        return [render_pdf_graphic(content, master, output_dir)]
    if spec.source_format == "jpg":
        return [render_test_photo(content, output_dir)]
    raise ValueError(f"Unsupported source format: {spec.source_format}")


def _populate_checksum_rows(
    content: dict[str, Any],
    catalog,
    output_root: Path,
) -> None:
    rows: list[list[Any]] = []
    sequence = 0
    for spec in catalog.documents:
        for extension in spec.physical_extensions():
            sequence += 1
            path = (
                output_root
                / spec.output_subfolder
                / f"{spec.file_stem}.{extension}"
            )
            if spec.logical_id == "V00-CHECKSUM-001":
                digest = "SELF-REFERENCE-EXCLUDED"
                status = "自引用排除"
            elif path.exists():
                digest = sha256(path)
                status = "已校验"
            else:
                digest = ""
                status = "缺失"
            rows.append(
                [
                    sequence,
                    spec.logical_id,
                    path.name,
                    extension.upper(),
                    digest,
                    status,
                ]
            )
    content["workbook"]["sheets"] = [
        {
            "name": "文件校验",
            "headers": [
                "序号",
                "逻辑编号",
                "文件名",
                "格式",
                "SHA-256",
                "校验状态",
            ],
            "rows": rows,
        }
    ]


def build_selected(
    workspace: Path,
    folders: set[str],
    *,
    output: Path | None = None,
    render: bool = True,
) -> BuildResult:
    data_dir = workspace / "scripts/r01_r69_pack/data"
    master = _load_raw(data_dir / "project_master.json")
    catalog = load_catalog(data_dir / "document_catalog.json")
    content_dir = data_dir / "content"
    library = load_content_library(content_dir)
    scenario_data = load_scenario_data(content_dir)
    specs = [spec for spec in catalog.documents if spec.folder in folders]
    errors: list[str] = []
    missing = [spec.logical_id for spec in specs if spec.logical_id not in library]
    if missing:
        errors.append("缺少内容定义：" + "、".join(missing))
    documents = [library[spec.logical_id] for spec in specs if spec.logical_id in library]
    expected_physical = sum(len(spec.physical_extensions()) for spec in specs)
    files: list[Path] = []
    if render and not errors:
        output_root = output or workspace / "files" / PACK_FOLDER
        ordered_specs = sorted(
            specs,
            key=lambda spec: spec.logical_id == "V00-CHECKSUM-001",
        )
        for spec in ordered_specs:
            if spec.logical_id == "V00-CHECKSUM-001":
                _populate_checksum_rows(
                    library[spec.logical_id], catalog, output_root
                )
            files.extend(
                _render_document(spec, library[spec.logical_id], master, output_root)
            )
        if len(files) != expected_physical:
            errors.append(
                f"物理文件数量错误：预期{expected_physical}，实际{len(files)}"
            )
    return BuildResult(
        logical_count=len(specs),
        physical_count=expected_physical if not render else len(files),
        files=files,
        documents=documents,
        scenario_data={
            folder: scenario_data.get(folder, {}) for folder in folders
        },
        errors=errors,
    )


def build_all(workspace: Path, output: Path | None = None) -> BuildResult:
    return build_selected(
        workspace,
        {"M00", "B00", "S01", "S02", "S03", "S04", "S05", "S06", "V00"},
        output=output,
        render=True,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--folders", nargs="+")
    args = parser.parse_args()
    folders = set(args.folders) if args.folders else {
        "M00", "B00", "S01", "S02", "S03", "S04", "S05", "S06", "V00"
    }
    result = build_selected(
        args.workspace,
        folders,
        output=args.output,
        render=True,
    )
    print(f"logical_documents={result.logical_count}")
    print(f"physical_files={result.physical_count}")
    print(f"build_errors={len(result.errors)}")
    for error in result.errors:
        print(error)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
