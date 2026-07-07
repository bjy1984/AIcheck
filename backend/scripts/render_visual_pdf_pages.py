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

from libs.db.repository import load_state, repo
from libs.knowledge_indexing import local_path_from_storage_key


VISUAL_PAGE_ROOT = BACKEND_ROOT / "data" / "visual_extraction_pages"


def parse_page_spec(spec: str | None, total_pages: int) -> list[int]:
    if not spec:
        return list(range(1, total_pages + 1))
    pages: set[int] = set()
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start = int(left.strip())
            end = int(right.strip())
            pages.update(range(max(1, start), min(total_pages, end) + 1))
        else:
            pages.add(int(part))
    return [page for page in sorted(pages) if 1 <= page <= total_pages]


def resolve_pdf_path(file: dict[str, Any]) -> Path:
    local_path = local_path_from_storage_key(str(file.get("storageKey") or ""), WORKSPACE_ROOT)
    if local_path and local_path.suffix.lower() == ".pdf":
        return local_path
    relative_path = str(file.get("sourceRelativePath") or "").strip()
    if relative_path:
        candidate = (WORKSPACE_ROOT / relative_path).resolve()
        if candidate.exists() and candidate.suffix.lower() == ".pdf":
            return candidate
    raise FileNotFoundError(f"Cannot resolve local PDF for {file.get('id') or file.get('fileName')}")


def candidate_files(args: argparse.Namespace) -> list[dict[str, Any]]:
    pdf_files = [
        item
        for item in repo.state.get("knowledge_files", [])
        if item.get("sourceId") == args.source_id and str(item.get("fileName") or "").lower().endswith(".pdf")
    ]
    by_id = {str(item.get("id")): item for item in pdf_files}
    if args.file_id:
        missing = [file_id for file_id in args.file_id if file_id not in by_id]
        if missing:
            raise SystemExit(f"Unknown PDF file id(s): {', '.join(missing)}")
        return [by_id[file_id] for file_id in args.file_id]
    if args.failed_only:
        pdf_files = [item for item in pdf_files if item.get("vectorStatus") != "已向量化"]
    if not args.all and not args.failed_only:
        raise SystemExit("Pass --all, --failed-only, or --file-id.")
    pdf_files.sort(key=lambda item: str(item.get("sourceRelativePath") or item.get("fileName") or ""))
    if args.limit > 0:
        pdf_files = pdf_files[: args.limit]
    return pdf_files


def render_file(file: dict[str, Any], *, pages: str | None, dpi: int, overwrite: bool) -> dict[str, Any]:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        return {
            "fileId": file.get("id"),
            "sourceRelativePath": file.get("sourceRelativePath"),
            "status": "failed",
            "reason": f"PyMuPDF unavailable: {exc}",
        }

    pdf_path = resolve_pdf_path(file)
    output_dir = VISUAL_PAGE_ROOT / str(file["id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[dict[str, Any]] = []
    with fitz.open(str(pdf_path)) as document:
        selected_pages = parse_page_spec(pages, int(document.page_count))
        matrix = fitz.Matrix(float(dpi) / 72.0, float(dpi) / 72.0)
        for page_no in selected_pages:
            output_path = output_dir / f"page-{page_no:04d}.png"
            if output_path.exists() and not overwrite:
                rendered.append({"pageNo": page_no, "imagePath": str(output_path), "status": "exists"})
                continue
            page = document.load_page(page_no - 1)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pixmap.save(str(output_path))
            rendered.append({"pageNo": page_no, "imagePath": str(output_path), "status": "rendered"})
    return {
        "fileId": file.get("id"),
        "fileName": file.get("fileName"),
        "sourceRelativePath": file.get("sourceRelativePath"),
        "pageCount": len(rendered),
        "outputDir": str(output_dir),
        "pages": rendered,
        "status": "success",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render rules PDF pages to PNGs for visual extraction.")
    parser.add_argument("--source-id", default="KS-STANDARD-RULES")
    parser.add_argument("--file-id", action="append", default=[], help="Render one PDF by knowledge file id. Can repeat.")
    parser.add_argument("--all", action="store_true", help="Render all PDF files in the rules source.")
    parser.add_argument("--failed-only", action="store_true", help="Render PDFs currently not fully vectorized.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pages", help="Page list, for example 1-3,8.")
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_state()
    results = [
        render_file(file, pages=args.pages, dpi=args.dpi, overwrite=args.overwrite)
        for file in candidate_files(args)
    ]
    failed = [item for item in results if item.get("status") != "success"]
    summary = {
        "status": "success" if not failed else "partial_success",
        "renderRoot": str(VISUAL_PAGE_ROOT),
        "processed": len(results),
        "failed": len(failed),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":") if args.json else None, indent=None if args.json else 2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
