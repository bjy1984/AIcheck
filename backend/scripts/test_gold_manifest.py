from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.document_auto_gold import category_definition_snapshot


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def model_input_for_case(
    case: dict[str, Any],
    *,
    markdown: str,
    category_snapshot: dict[str, Any],
) -> dict[str, str]:
    # `case` is accepted so callers can keep corpus bookkeeping beside the
    # input builder. It is intentionally not read: paths and human gold labels
    # must never leak into the production model request.
    del case
    return {
        "categoryDefinitionsJson": json.dumps(category_snapshot, ensure_ascii=False, sort_keys=True),
        "ocrMarkdown": markdown,
    }


def audit_test_gold_manifest(repo_root: Path, manifest_path: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise ValueError("test gold manifest must contain cases[]")
    expected_count = int(payload.get("expectedFileCount") or 0)
    test_root = repo_root / "test"
    actual_paths = {
        str(path.relative_to(test_root))
        for path in test_root.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }
    allowed_categories = {
        item["category"] for item in category_definition_snapshot()["categories"]
    }
    seen: set[str] = set()
    duplicate_paths: list[str] = []
    missing_files: list[str] = []
    hash_mismatches: list[str] = []
    unknown_categories: list[dict[str, str]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        relative_path = str(case.get("relativePath") or "")
        if relative_path in seen:
            duplicate_paths.append(relative_path)
        seen.add(relative_path)
        source_path = test_root / relative_path
        if not source_path.is_file():
            missing_files.append(relative_path)
        elif sha256_file(source_path) != str(case.get("sha256") or ""):
            hash_mismatches.append(relative_path)
        for category in case.get("expectedCategories") or []:
            if str(category) not in allowed_categories:
                unknown_categories.append({"relativePath": relative_path, "category": str(category)})
    extra_files = sorted(actual_paths - seen)
    missing_manifest_entries = sorted(seen - actual_paths)
    ok = not any(
        [
            duplicate_paths,
            missing_files,
            hash_mismatches,
            unknown_categories,
            extra_files,
            missing_manifest_entries,
        ]
    ) and len(cases) == expected_count == len(actual_paths)
    return {
        "ok": ok,
        "fileCount": len(cases),
        "actualFileCount": len(actual_paths),
        "expectedFileCount": expected_count,
        "hashMismatchCount": len(hash_mismatches),
        "unknownCategoryCount": len(unknown_categories),
        "duplicatePaths": sorted(duplicate_paths),
        "missingFiles": sorted(missing_files),
        "hashMismatches": sorted(hash_mismatches),
        "unknownCategories": unknown_categories,
        "extraFiles": extra_files,
        "missingManifestEntries": missing_manifest_entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the 23-file document classification gold corpus.")
    parser.add_argument("--repo-root", default="..")
    parser.add_argument("--manifest", default="ocr_eval/test_gold_manifest.json")
    args = parser.parse_args()
    report = audit_test_gold_manifest(Path(args.repo_root), Path(args.manifest))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
