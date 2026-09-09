"""Inspect local NDT PDFs through native extraction, without models or review approval."""

import argparse
import hashlib
import json
from pathlib import Path

from apps.ocr_service.engines import PyMuPdfTextLayerEngine
from apps.ocr_service.service import enrich_parse_result, normalize_ocr_result
from libs.ocr.profiles import profile_for


def probe_pdf(path: Path) -> dict:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    profile = profile_for("ndt_procedure_v1")
    raw = PyMuPdfTextLayerEngine().parse(path)
    parsed = enrich_parse_result(
        normalize_ocr_result(raw, f"local-probe://{digest}", path.name),
        profile=profile, document_version_id=f"LOCAL-PROBE-{digest}",
        business_pack_id="engineering_inspection_v1", model_manifest={},
    )
    fragments = parsed.get("fragments", [])
    text_pages = {item["pageNo"] for item in fragments if item.get("text", "").strip()}
    pages = [item["pageNo"] for item in raw.get("pages", [])]
    fields = [{key: item.get(key) for key in (
        "fieldCode", "fieldValue", "pageNo", "bbox", "confidence", "qualityFlags",
    )} for item in parsed.get("fields", [])]
    present = {item["fieldCode"] for item in fields if item["fieldValue"]}
    return {
        "file": str(path), "sha256": digest,
        "profileId": profile["profileId"], "profileSelection": "explicit_probe_override",
        "engine": raw["engine"], "pageCount": len(pages),
        "pagesWithText": sorted(text_pages),
        "pagesWithoutText": sorted(set(pages) - text_pages),
        "fragmentCount": len(fragments), "fields": fields,
        "missingRequiredFields": sorted(set(profile["requiredFields"]) - present),
        "diagnostics": parsed.get("diagnostics", []),
        "businessAcceptance": "not_evaluated", "visualOcrExecuted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    reports = []
    for path in args.pdf:
        try:
            reports.append(probe_pdf(path))
        except (OSError, ValueError, RuntimeError) as exc:
            reports.append({"file": str(path), "errorType": type(exc).__name__,
                            "businessAcceptance": "not_evaluated"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "schemaVersion": 1, "scope": "native_pdf_extraction_only", "documents": reports,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return int(any("errorType" in item for item in reports))


if __name__ == "__main__":
    raise SystemExit(main())
