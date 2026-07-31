from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .model import ProjectMaster
from .node_snapshot import NodeSnapshot


FOLDER_PATHS = {
    "M00": "M00_项目主数据与总目录",
    "B00": "B00_基础项目资料",
    "S01": "S01_境外材料与新材料",
    "S02": "S02_材料代用",
    "S03": "S03_焊缝返修与热处理",
    "S04": "S04_阴极保护与穿跨越",
    "S05": "S05_安全附件",
    "S06": "S06_耐压免除或替代",
    "V00": "V00_R01-R69覆盖验证",
}


@dataclass(frozen=True)
class DocumentSpec:
    logical_id: str
    folder: str
    output_subfolder: str
    title: str
    source_format: str
    submit_format: str
    document_number: str
    revision: str
    date: str
    r_nodes: tuple[int, ...]
    related_lines: tuple[str, ...]
    related_welds: tuple[str, ...]
    related_materials: tuple[str, ...]
    template_kind: str
    content_ref: str
    file_stem: str

    def physical_extensions(self) -> tuple[str, ...]:
        if self.source_format in {"docx", "xlsx"}:
            return (self.source_format, "pdf")
        return (self.source_format,)


@dataclass(frozen=True)
class DocumentCatalog:
    documents: tuple[DocumentSpec, ...]

    def expected_physical_file_count(self) -> int:
        return sum(len(document.physical_extensions()) for document in self.documents)

    def logical_counts_by_folder(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for document in self.documents:
            counts[document.folder] = counts.get(document.folder, 0) + 1
        return counts

    def validate(
        self, master: ProjectMaster, snapshot: NodeSnapshot
    ) -> list[str]:
        errors: list[str] = []
        expected_counts = {
            "M00": 7,
            "B00": 19,
            "S01": 8,
            "S02": 5,
            "S03": 9,
            "S04": 11,
            "S05": 5,
            "S06": 6,
            "V00": 6,
        }
        if len(self.documents) != 76:
            errors.append(f"逻辑资料应为76份，实际为{len(self.documents)}")
        if self.expected_physical_file_count() != 136:
            errors.append(
                "实际文件应为136个，"
                f"目录预计为{self.expected_physical_file_count()}个"
            )
        if self.logical_counts_by_folder() != expected_counts:
            errors.append("分册逻辑资料数量与设计不一致")

        def duplicates(values: list[str], label: str) -> None:
            duplicate_values = sorted(
                {value for value in values if values.count(value) > 1}
            )
            if duplicate_values:
                errors.append(f"{label}重复：{', '.join(duplicate_values)}")

        duplicates([doc.logical_id for doc in self.documents], "逻辑资料编号")
        duplicates([doc.document_number for doc in self.documents], "文件编号")
        duplicates([doc.file_stem for doc in self.documents], "文件名")

        covered = {node for doc in self.documents for node in doc.r_nodes}
        if covered != set(range(1, 70)):
            missing = sorted(set(range(1, 70)) - covered)
            extra = sorted(covered - set(range(1, 70)))
            errors.append(f"节点覆盖错误，缺少{missing}，多出{extra}")
        r69_documents = [
            doc.logical_id for doc in self.documents if 69 in doc.r_nodes
        ]
        if r69_documents != ["V00-R69-001"]:
            errors.append("R69只能绑定V00内部工作流执行记录")

        line_ids = {line.id for line in master.lines}
        weld_ids = {weld.id for weld in master.welds}
        material_ids = {batch.id for batch in master.material_batches}
        for document in self.documents:
            if document.folder not in expected_counts:
                errors.append(f"未知分册：{document.folder}")
            if document.source_format not in {"docx", "xlsx", "pdf", "jpg"}:
                errors.append(
                    f"{document.logical_id}源格式无效：{document.source_format}"
                )
            if set(document.related_lines) - line_ids:
                errors.append(f"{document.logical_id}引用缺失管线")
            if set(document.related_welds) - weld_ids:
                errors.append(f"{document.logical_id}引用缺失焊口")
            if set(document.related_materials) - material_ids:
                errors.append(f"{document.logical_id}引用缺失材料")

        document_ids = {document.logical_id for document in self.documents}
        unresolved_requirements = sorted(
            {
                row.logical_document_id
                for row in snapshot.requirements
                if row.logical_document_id not in document_ids
            }
        )
        if unresolved_requirements:
            errors.append(
                "资料要求引用缺失逻辑资料："
                + ", ".join(unresolved_requirements)
            )
        return errors


def _contexts(master: ProjectMaster) -> dict[str, dict[str, list[str]]]:
    return {
        "M00": {
            "lines": [line.id for line in master.lines],
            "welds": [weld.id for weld in master.welds],
            "materials": [batch.id for batch in master.material_batches],
        },
        "B00": {
            "lines": [line.id for line in master.lines if line.id in {
                "PL8301", "PL8302", "PL8303", "PL8304",
                "PL8305", "PL8306", "VT8301", "VT8302"
            }],
            "welds": [weld.id for weld in master.welds if weld.scenario == "B00"],
            "materials": ["MAT-B00-20-001"],
        },
        "S01": {
            "lines": ["PL8307-TEST"],
            "welds": [f"W-S01-{index:03d}" for index in range(1, 4)],
            "materials": ["MAT-S01-TP316L-001", "MAT-S01-NM01-001"],
        },
        "S02": {
            "lines": ["PL8303"],
            "welds": [f"W-S02-{index:03d}" for index in range(1, 4)],
            "materials": ["MAT-S02-S30408-001"],
        },
        "S03": {
            "lines": ["ST8301-TEST"],
            "welds": [f"W-S03-{index:03d}" for index in range(1, 5)],
            "materials": ["MAT-S03-15CRMO-001"],
        },
        "S04": {
            "lines": ["PL8308-TEST"],
            "welds": [f"W-S04-{index:03d}" for index in range(1, 4)],
            "materials": ["MAT-B00-20-001"],
        },
        "S05": {
            "lines": ["PL8305"],
            "welds": [f"W-S05-{index:03d}" for index in range(1, 3)],
            "materials": ["MAT-B00-20-001"],
        },
        "S06": {
            "lines": ["PL8306"],
            "welds": [f"W-S06-{index:03d}" for index in range(1, 4)],
            "materials": ["MAT-B00-20-001"],
        },
        "V00": {
            "lines": [line.id for line in master.lines],
            "welds": [weld.id for weld in master.welds],
            "materials": [batch.id for batch in master.material_batches],
        },
    }


def _definition_rows() -> list[tuple[str, str, str, str, list[int], str]]:
    return [
        ("M00-README-001", "M00", "使用说明", "docx", [], "00_使用说明与总目录"),
        ("M00-MASTER-001", "M00", "项目主数据", "xlsx", [], FOLDER_PATHS["M00"]),
        ("M00-STD-001", "M00", "标准版本台账", "xlsx", [8], FOLDER_PATHS["M00"]),
        ("M00-DIR-001", "M00", "资料总目录", "xlsx", [], "00_使用说明与总目录"),
        ("M00-SOURCE-001", "M00", "原始证据来源与页级绑定台账", "xlsx", [], FOLDER_PATHS["M00"]),
        ("M00-DATA-001", "M00", "数据一致性差异与闭环报告", "docx", [], FOLDER_PATHS["M00"]),
        ("M00-SEAL-001", "M00", "测试专用签章样式与使用登记台账", "xlsx", [], FOLDER_PATHS["M00"]),
        ("B00-DESIGN-001", "B00", "基础设计输入摘要", "docx", [1, 2, 4, 5, 6, 7, 9], FOLDER_PATHS["B00"]),
        ("B00-CONSTRUCTION-001", "B00", "施工组织设计", "docx", [10], FOLDER_PATHS["B00"]),
        ("B00-QUALITY-001", "B00", "质量计划", "docx", [], FOLDER_PATHS["B00"]),
        ("B00-QUAL-001", "B00", "单位人员资质台账", "xlsx", [1, 2, 3], FOLDER_PATHS["B00"]),
        ("B00-LINES-001", "B00", "基础管线台账", "xlsx", [4, 5, 6, 7, 9], FOLDER_PATHS["B00"]),
        ("B00-MATERIAL-001", "B00", "材料验收台账", "xlsx", [11, 12, 13, 14], FOLDER_PATHS["B00"]),
        ("B00-VALVE-001", "B00", "阀门耐压试验记录", "xlsx", [23], FOLDER_PATHS["B00"]),
        ("B00-WELD-001", "B00", "PQR-WPS基础包", "docx", [24, 25, 26, 27], FOLDER_PATHS["B00"]),
        ("B00-WELD-LEDGER-001", "B00", "焊口与检验台账", "xlsx", [28, 29, 30], FOLDER_PATHS["B00"]),
        ("B00-NDT-001", "B00", "基础无损检测报告", "docx", [35, 36, 37, 38, 39], FOLDER_PATHS["B00"]),
        ("B00-TEST-001", "B00", "压力与泄漏试验方案", "docx", [59, 60, 61, 62], FOLDER_PATHS["B00"]),
        ("B00-INSTALL-001", "B00", "安装试验吹扫综合记录", "xlsx", [40, 41, 42, 43, 44, 45, 66, 67, 68], FOLDER_PATHS["B00"]),
        ("B00-PHOTO-001", "B00", "管道组对现场核验图", "jpg", [28], FOLDER_PATHS["B00"]),
        ("B00-PHOTO-002", "B00", "焊缝外观现场核验图", "jpg", [30], FOLDER_PATHS["B00"]),
        ("B00-PHOTO-003", "B00", "无损检测现场核验图", "jpg", [42], FOLDER_PATHS["B00"]),
        ("B00-PHOTO-004", "B00", "防腐补伤现场核验图", "jpg", [44], FOLDER_PATHS["B00"]),
        ("B00-FILM-001", "B00", "PL8303射线检测模拟底片", "jpg", [41], FOLDER_PATHS["B00"]),
        ("B00-FILM-002", "B00", "PL8306射线检测模拟底片", "jpg", [42], FOLDER_PATHS["B00"]),
        ("B00-QUERY-001", "B00", "焊工资格外部查询测试截图", "jpg", [24], FOLDER_PATHS["B00"]),
        ("S01-DESIGN-001", "S01", "境外与新材料设计变更", "docx", [15, 16, 17, 18, 19, 20, 21], FOLDER_PATHS["S01"]),
        ("S01-FOREIGN-001", "S01", "境外制造与型式资料", "docx", [15, 16], FOLDER_PATHS["S01"]),
        ("S01-MATERIAL-001", "S01", "企业标准与材料证明", "docx", [17], FOLDER_PATHS["S01"]),
        ("S01-RETEST-001", "S01", "验证性复验记录", "xlsx", [18, 19], FOLDER_PATHS["S01"]),
        ("S01-REVIEW-001", "S01", "新材料评审批准", "docx", [20], FOLDER_PATHS["S01"]),
        ("S01-ACCEPT-001", "S01", "到货验收记录", "xlsx", [21], FOLDER_PATHS["S01"]),
        ("S01-MARK-001", "S01", "标志移植台账", "xlsx", [21], FOLDER_PATHS["S01"]),
        ("S01-PHOTO-001", "S01", "到货与标志移植核验图", "jpg", [21], FOLDER_PATHS["S01"]),
        ("S02-DESIGN-001", "S02", "材料代用设计变更", "docx", [22], FOLDER_PATHS["S02"]),
        ("S02-CALC-001", "S02", "技术比较与强度校核", "docx", [22], FOLDER_PATHS["S02"]),
        ("S02-APPROVAL-001", "S02", "材料代用书面批准", "docx", [22], FOLDER_PATHS["S02"]),
        ("S02-WPS-001", "S02", "替代材料与WPS适用性", "docx", [22], FOLDER_PATHS["S02"]),
        ("S02-INSTALL-001", "S02", "替代材料验收安装记录", "xlsx", [22], FOLDER_PATHS["S02"]),
        ("S03-DESIGN-001", "S03", "热处理管线设计变更与计算", "docx", [32], FOLDER_PATHS["S03"]),
        ("S03-WPS-001", "S03", "PQR-WPS专项包", "docx", [32], FOLDER_PATHS["S03"]),
        ("S03-WELDER-001", "S03", "焊工焊材台账", "xlsx", [24, 25, 26, 27], FOLDER_PATHS["S03"]),
        ("S03-WELDLOG-001", "S03", "焊口施焊台账", "xlsx", [31], FOLDER_PATHS["S03"]),
        ("S03-NDT-INITIAL-001", "S03", "首次无损检测不合格报告", "docx", [31], FOLDER_PATHS["S03"]),
        ("S03-REPAIR-001", "S03", "返修方案与记录", "docx", [31], FOLDER_PATHS["S03"]),
        ("S03-NDT-REPEAT-001", "S03", "返修复检合格报告", "docx", [31], FOLDER_PATHS["S03"]),
        ("S03-PWHT-001", "S03", "热处理工艺与仪表", "docx", [32, 33], FOLDER_PATHS["S03"]),
        ("S03-PWHT-RECORD-001", "S03", "热处理曲线与硬度记录", "xlsx", [34], FOLDER_PATHS["S03"]),
        ("S04-DESIGN-001", "S04", "穿越与阴极保护设计变更", "docx", [46, 48, 49, 50, 51, 52, 53, 54, 55], FOLDER_PATHS["S04"]),
        ("S04-DIAGRAM-001", "S04", "穿越结构与焊缝布置图", "pdf", [48, 49, 53], FOLDER_PATHS["S04"]),
        ("S04-EQUIP-001", "S04", "设备材料台账", "xlsx", [46, 47, 50, 51], FOLDER_PATHS["S04"]),
        ("S04-INSTALL-001", "S04", "穿越施工与安装记录", "xlsx", [48, 49, 50, 51, 52, 53, 54, 55], FOLDER_PATHS["S04"]),
        ("S04-CP-001", "S04", "防腐阴保调试记录", "xlsx", [46, 47], FOLDER_PATHS["S04"]),
        ("S04-PHOTO-001", "S04", "施工照片", "jpg", [48], FOLDER_PATHS["S04"]),
        ("S04-PHOTO-002", "S04", "穿越开挖与就位核验图", "jpg", [49], FOLDER_PATHS["S04"]),
        ("S04-PHOTO-003", "S04", "套管防腐绝缘核验图", "jpg", [50], FOLDER_PATHS["S04"]),
        ("S04-PHOTO-004", "S04", "绝缘支撑安装核验图", "jpg", [51], FOLDER_PATHS["S04"]),
        ("S04-PHOTO-005", "S04", "穿越焊接连接核验图", "jpg", [52], FOLDER_PATHS["S04"]),
        ("S04-PHOTO-006", "S04", "穿越布管完成核验图", "jpg", [53], FOLDER_PATHS["S04"]),
        ("S05-DESIGN-001", "S05", "安全附件设计变更与选型", "docx", [56], FOLDER_PATHS["S05"]),
        ("S05-ACCESSORY-001", "S05", "产品质量与型式资料", "docx", [56], FOLDER_PATHS["S05"]),
        ("S05-INSTALL-001", "S05", "安全附件到货安装记录", "xlsx", [56], FOLDER_PATHS["S05"]),
        ("S05-PSV-001", "S05", "安全阀校验报告", "docx", [57], FOLDER_PATHS["S05"]),
        ("S05-ESDV-001", "S05", "紧急切断阀与爆破片记录", "xlsx", [58], FOLDER_PATHS["S05"]),
        ("S06-ANALYSIS-001", "S06", "耐压替代设计论证与应力分析", "docx", [63], FOLDER_PATHS["S06"]),
        ("S06-APPROVAL-001", "S06", "耐压替代申请审批", "docx", [63, 64, 65], FOLDER_PATHS["S06"]),
        ("S06-ALTERNATIVE-001", "S06", "替代检验试验方案", "docx", [64], FOLDER_PATHS["S06"]),
        ("S06-NDT-001", "S06", "百分百RT-MT报告与底片", "docx", [65], FOLDER_PATHS["S06"]),
        ("S06-FINAL-001", "S06", "替代试验泄漏最终确认", "xlsx", [64, 66, 67], FOLDER_PATHS["S06"]),
        ("S06-FILM-001", "S06", "最终封闭焊口射线检测模拟底片", "jpg", [65], FOLDER_PATHS["S06"]),
        ("V00-NODE-MATRIX-001", "V00", "R01-R69资料覆盖矩阵", "xlsx", [], FOLDER_PATHS["V00"]),
        ("V00-REQ-MATRIX-001", "V00", "166项资料要求覆盖明细", "xlsx", [], FOLDER_PATHS["V00"]),
        ("V00-SOURCE-DIFF-001", "V00", "资料来源与差异台账", "xlsx", [], FOLDER_PATHS["V00"]),
        ("V00-CHECKSUM-001", "V00", "文件校验清单", "xlsx", [], FOLDER_PATHS["V00"]),
        ("V00-REPORT-001", "V00", "资料包完整性检查报告", "docx", [], FOLDER_PATHS["V00"]),
        ("V00-R69-001", "V00", "R69质量保证体系实施状况工作流执行记录", "xlsx", [69], FOLDER_PATHS["V00"]),
    ]


def default_catalog_payload(master: ProjectMaster) -> dict[str, Any]:
    contexts = _contexts(master)
    rows: list[dict[str, Any]] = []
    sequence_by_folder: dict[str, int] = {}
    scenario_dates = {
        "M00": "2026-07-15",
        "B00": "2026-05-20",
        "S01": "2026-06-04",
        "S02": "2026-06-10",
        "S03": "2026-06-19",
        "S04": "2026-06-25",
        "S05": "2026-07-01",
        "S06": "2026-07-10",
        "V00": "2026-07-15",
    }
    for logical_id, folder, title, source_format, r_nodes, output_subfolder in _definition_rows():
        sequence_by_folder[folder] = sequence_by_folder.get(folder, 0) + 1
        seq = sequence_by_folder[folder]
        if folder.startswith("S") or folder == "B00":
            document_number = (
                f"QX201903S-13-Y-TEST-{folder}-{seq:03d}"
                if "DESIGN" in logical_id or "ANALYSIS" in logical_id
                else f"TEST-{folder}-{seq:03d}"
            )
        else:
            document_number = f"TEST-{folder}-{seq:03d}"
        safe_title = title.replace("/", "-")
        rows.append(
            {
                "logicalId": logical_id,
                "folder": folder,
                "outputSubfolder": output_subfolder,
                "title": title,
                "sourceFormat": source_format,
                "submitFormat": "pdf" if source_format in {"docx", "xlsx", "pdf"} else "jpg",
                "documentNumber": document_number,
                "revision": "0",
                "date": scenario_dates[folder],
                "rNodes": r_nodes,
                "relatedLines": contexts[folder]["lines"],
                "relatedWelds": contexts[folder]["welds"],
                "relatedMaterials": contexts[folder]["materials"],
                "templateKind": (
                    "ledger"
                    if source_format == "xlsx"
                    else "diagram"
                    if source_format == "pdf"
                    else "photo"
                    if source_format == "jpg"
                    else "narrative"
                ),
                "contentRef": f"content/{folder}.json#{logical_id}",
                "fileStem": f"{folder}_{logical_id}_{document_number}_{safe_title}",
            }
        )
    return {
        "schemaVersion": "r01-r69-document-catalog@1",
        "logicalDocumentCount": len(rows),
        "physicalFileCount": sum(
            2 if row["sourceFormat"] in {"docx", "xlsx"} else 1 for row in rows
        ),
        "documents": rows,
    }


def _spec(row: dict[str, Any]) -> DocumentSpec:
    return DocumentSpec(
        logical_id=row["logicalId"],
        folder=row["folder"],
        output_subfolder=row["outputSubfolder"],
        title=row["title"],
        source_format=row["sourceFormat"],
        submit_format=row["submitFormat"],
        document_number=row["documentNumber"],
        revision=row["revision"],
        date=row["date"],
        r_nodes=tuple(int(value) for value in row["rNodes"]),
        related_lines=tuple(row["relatedLines"]),
        related_welds=tuple(row["relatedWelds"]),
        related_materials=tuple(row["relatedMaterials"]),
        template_kind=row["templateKind"],
        content_ref=row["contentRef"],
        file_stem=row["fileStem"],
    )


def load_catalog(path: Path) -> DocumentCatalog:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return DocumentCatalog(tuple(_spec(row) for row in payload["documents"]))


def write_default_catalog(path: Path, master: ProjectMaster) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(default_catalog_payload(master), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    package_dir = Path(__file__).parent
    master = __import__(
        "scripts.r01_r69_pack.model", fromlist=["load_project_master"]
    ).load_project_master(package_dir / "data/project_master.json")
    output = package_dir / "data/document_catalog.json"
    write_default_catalog(output, master)
    catalog = load_catalog(output)
    print(
        f"logical={len(catalog.documents)} "
        f"physical={catalog.expected_physical_file_count()} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
