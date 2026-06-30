from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_manifest_audit import build_manifest_audit_report, manifest_audit_csv


def test_manifest_audit_flags_quality_certificate_mislabeled_design_calculation(tmp_path: Path) -> None:
    queue = tmp_path / "queue.json"
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    queue.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "case-1",
                        "scenario": "quality_certificate_profile",
                        "profileId": "quality_certificate_v1",
                        "source": {"fileName": "IMG_6511.heic", "path": "Scan/IMG_6511.heic"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (result_dir / "case-1.json").write_text(
        json.dumps(
            {
                "status": "success",
                "fragments": [
                    {"text": "管道壁厚计算书"},
                    {"text": "广东省建设工程勘察设计出图专用章"},
                    {"text": "图名 压力管道强度计算书"},
                ],
                "seals": [{"sealType": "design_license_seal", "sealName": "压力管道设计许可印章"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_manifest_audit_report(queue, result_dirs=[result_dir])
    item = report["items"][0]

    assert report["summary"]["mismatches"] == 1
    assert item["status"] == "mismatch"
    assert item["declaredScenario"] == "quality_certificate_profile"
    assert item["suggestedScenario"] == "evidence_profile"
    assert item["ocrTextAvailable"] is True
    assert item["reviewRequired"] is True
    assert "case-1" in manifest_audit_csv(report)


def test_manifest_audit_keeps_quality_certificate_when_keywords_match(tmp_path: Path) -> None:
    queue = tmp_path / "queue.json"
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    queue.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "case-2",
                        "scenario": "quality_certificate_profile",
                        "source": {"fileName": "cert.pdf", "path": "Scan/cert.pdf"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (result_dir / "case-2.json").write_text(
        json.dumps(
            {
                "status": "success",
                "fragments": [
                    {"text": "产品质量证明书"},
                    {"text": "材料牌号 06Cr19Ni10"},
                    {"text": "炉批号 A123 化学成分 力学性能"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_manifest_audit_report(queue, result_dirs=[result_dir])
    item = report["items"][0]

    assert report["summary"]["mismatches"] == 0
    assert item["status"] == "ok"
    assert item["suggestedScenario"] == "quality_certificate_profile"


def test_manifest_audit_marks_missing_ocr_text_for_review(tmp_path: Path) -> None:
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "fileName": "IMG_6524.heic",
                        "scenario": "seal_text_profile",
                        "notes": "Close-up seal sample.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_manifest_audit_report(queue, result_dirs=[])
    item = report["items"][0]

    assert report["summary"]["missingOcrText"] == 1
    assert item["ocrTextAvailable"] is False
    assert item["reviewRequired"] is True
