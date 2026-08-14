from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.contracts.responses import server_time
from libs.db.repository import flush_state, load_state, repo

VISUAL_EXTRACTION_ROOT = BACKEND_ROOT / "data" / "visual_extractions"
VISUAL_SOURCE_METHOD = "codex_visual_manual_extraction"
ROI_VERSION = "visual-page-content-roi-v1"


def resolve_image_path(raw: Any) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = (WORKSPACE_ROOT / path).resolve()
    return path if path.exists() else None


def content_bbox(image_path: Path) -> tuple[list[int], int, int]:
    from PIL import Image

    with Image.open(image_path).convert("L") as image:
        width, height = image.size
        # Use a conservative dark-pixel mask. Page-level visual extractions can cover
        # headings, tables and footers; the box intentionally represents page content,
        # not a fabricated line-level OCR box.
        mask = image.point(lambda value: 255 if value < 210 else 0)
        box = mask.getbbox()
        if not box:
            return [0, 0, width, height], width, height
        x1, y1, x2, y2 = box
        pad = 12
        return [max(0, x1 - pad), max(0, y1 - pad), min(width, x2 + pad), min(height, y2 + pad)], width, height


def visual_roi(page_no: int, bbox: list[int], width: int, height: int, text: str, confidence: Any) -> dict[str, Any]:
    return {
        "schemaVersion": "FdeRoi@1.0.0",
        "pageNo": page_no,
        "coordinateSystem": "preview_image_px",
        "sourceMethod": VISUAL_SOURCE_METHOD,
        "sourceImageWidth": width,
        "sourceImageHeight": height,
        "previewWidth": width,
        "previewHeight": height,
        "boxes": [
            {
                "id": f"visual-page-content-{page_no}",
                "pageNo": page_no,
                "bbox": bbox,
                "polygon": [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]]],
                "text": " ".join(str(text or "").split())[:240],
                "confidence": confidence,
                "sourceMethod": VISUAL_SOURCE_METHOD,
                "sourceFragmentId": f"visual-page-content-{page_no}",
            }
        ],
        "unionBBox": bbox,
        "qualityWarnings": ["page_level_visual_roi"],
        "roiVersion": ROI_VERSION,
    }


def load_sidecar(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sidecar_paths(args: argparse.Namespace) -> list[Path]:
    if args.sidecar:
        return [Path(item).expanduser().resolve() for item in args.sidecar]
    if args.file_id:
        return [(VISUAL_EXTRACTION_ROOT / f"{file_id}.json").resolve() for file_id in args.file_id]
    return sorted(VISUAL_EXTRACTION_ROOT.glob("*.json"))


def page_text(page: dict[str, Any]) -> str:
    parts = []
    for key in ("title", "summary", "extractedText", "text"):
        value = " ".join(str(page.get(key) or "").split())
        if value and value not in parts:
            parts.append(value)
    return "\n".join(parts)


def update_sidecar(path: Path) -> dict[str, Any]:
    sidecar = load_sidecar(path)
    changed_pages = 0
    missing_images = 0
    for page in sidecar.get("pages") or []:
        if not isinstance(page, dict):
            continue
        image_path = resolve_image_path(page.get("imagePath"))
        if not image_path:
            missing_images += 1
            continue
        page_no = int(page.get("pageNo") or 0)
        if page_no <= 0:
            continue
        bbox, width, height = content_bbox(image_path)
        page["bbox"] = bbox
        page["sourceImageWidth"] = width
        page["sourceImageHeight"] = height
        page["previewWidth"] = width
        page["previewHeight"] = height
        page["coordinateSystem"] = "preview_image_px"
        page["roi"] = visual_roi(page_no, bbox, width, height, page_text(page), page.get("confidence"))
        changed_pages += 1
    if changed_pages:
        path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "sidecar": str(path),
        "fileId": sidecar.get("fileId"),
        "changedPages": changed_pages,
        "missingImages": missing_images,
    }


def apply_to_state(file_id: str, sidecar: dict[str, Any]) -> dict[str, Any]:
    pages = {
        int(page.get("pageNo") or 0): page
        for page in sidecar.get("pages") or []
        if isinstance(page, dict) and int(page.get("pageNo") or 0) > 0 and page.get("bbox") and isinstance(page.get("roi"), dict)
    }
    changed_chunks = 0
    changed_vectors = 0
    changed_clauses = 0
    now = server_time()
    for chunk in repo.state.get("knowledge_chunks", []):
        if str(chunk.get("fileId") or "") != file_id:
            continue
        if chunk.get("sourceMethod") != VISUAL_SOURCE_METHOD and chunk.get("contextType") != "visual_extracted_reference":
            continue
        page = pages.get(int(chunk.get("pageNo") or 0))
        if not page:
            continue
        chunk["bbox"] = page.get("bbox")
        chunk["roi"] = page.get("roi")
        chunk["roiVersion"] = ROI_VERSION
        chunk["updatedAt"] = now
        changed_chunks += 1
    chunk_ids = {
        str(chunk.get("id") or "")
        for chunk in repo.state.get("knowledge_chunks", [])
        if str(chunk.get("fileId") or "") == file_id
        and (chunk.get("sourceMethod") == VISUAL_SOURCE_METHOD or chunk.get("contextType") == "visual_extracted_reference")
    }
    chunks_by_id = {str(chunk.get("id") or ""): chunk for chunk in repo.state.get("knowledge_chunks", []) if str(chunk.get("id") or "") in chunk_ids}
    for vector in repo.state.get("knowledge_vectors", []):
        chunk = chunks_by_id.get(str(vector.get("chunkId") or ""))
        if not chunk:
            continue
        vector["bbox"] = chunk.get("bbox")
        vector["roi"] = chunk.get("roi")
        payload = vector.setdefault("payload", {})
        payload["bbox"] = chunk.get("bbox")
        payload["roi"] = chunk.get("roi")
        vector["updatedAt"] = now
        changed_vectors += 1
    for clause in repo.state.get("knowledge_clauses", []):
        chunk = chunks_by_id.get(str(clause.get("chunkId") or clause.get("clauseId") or ""))
        if not chunk:
            continue
        clause["bbox"] = chunk.get("bbox")
        clause["roi"] = chunk.get("roi")
        changed_clauses += 1
    return {
        "fileId": file_id,
        "changedChunks": changed_chunks,
        "changedVectors": changed_vectors,
        "changedClauses": changed_clauses,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add page-level visual ROI boxes to Codex visual extraction chunks.")
    parser.add_argument("--file-id", action="append", default=[])
    parser.add_argument("--sidecar", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = sidecar_paths(args)
    sidecar_results = [update_sidecar(path) for path in paths if path.exists()]
    load_state()
    state_results = []
    for path in paths:
        if not path.exists():
            continue
        sidecar = load_sidecar(path)
        file_id = str(sidecar.get("fileId") or "")
        if file_id:
            state_results.append(apply_to_state(file_id, sidecar))
    flush_state()
    result = {"status": "success", "sidecars": sidecar_results, "state": state_results}
    print(json.dumps(result, ensure_ascii=False, indent=None if args.json else 2, separators=(",", ":") if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
