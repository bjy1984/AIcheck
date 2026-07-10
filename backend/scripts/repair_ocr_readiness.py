from __future__ import annotations

import argparse
import json

from libs.db.repository import flush_state, load_state, repo
from libs.ocr_readiness import build_document_ocr_readiness


def build_repairs() -> list[dict]:
    repairs: list[dict] = []
    for document in repo.state.get("documents", []):
        readiness = build_document_ocr_readiness(repo, document)
        if readiness["status"] != "inconsistent":
            continue
        repairs.append(
            {
                "documentId": document.get("id"),
                "fileName": document.get("fileName"),
                "documentVersionId": readiness.get("documentVersionId"),
                "before": document.get("currentOcrStatus"),
                "after": "待识别",
                "blockingReasons": readiness.get("blockingReasons") or [],
            }
        )
    return repairs


def apply_repairs(repairs: list[dict]) -> None:
    repair_ids = {str(item.get("documentId")) for item in repairs}
    version_ids = {str(item.get("documentVersionId")) for item in repairs}
    for document in repo.state.get("documents", []):
        if str(document.get("id")) in repair_ids:
            document["currentOcrStatus"] = "待识别"
    for version in repo.state.get("versions", []):
        if str(version.get("id")) in version_ids:
            version["ocrStatus"] = "待识别"
            version["sliceStatus"] = "未切片"
            version["vectorStatus"] = "未向量化"
    flush_state()


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair OCR status labels that have no parse artifacts.")
    parser.add_argument("--apply", action="store_true", help="Apply status-only repairs. Default is dry-run.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    load_state()
    repairs = build_repairs()
    if args.apply:
        apply_repairs(repairs)
    report = {
        "schemaVersion": "aicheck-ocr-readiness-repair@1",
        "mode": "apply" if args.apply else "dry-run",
        "repairCount": len(repairs),
        "repairs": repairs,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['mode']}: {report['repairCount']} inconsistent OCR status records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
