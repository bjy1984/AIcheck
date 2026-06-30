from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_corpus import SCENARIO_PROFILE_DEFAULTS
from scripts.ocr_100_ingest_samples import (
    classify_sample,
    discover_candidate_files,
    safe_filename,
    sha256_file,
)
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan local folders for new OCR 100 real-sample candidates and optionally copy them into intake scenario folders.")
    parser.add_argument("inputs", nargs="+", help="Files or folders to scan.")
    parser.add_argument("--existing-queue", action="append", default=[], help="Existing sample queue or annotation task JSON used for duplicate detection. Repeatable.")
    parser.add_argument("--intake-dir", help="OCR 100 intake directory containing samples/<scenario>/ folders.")
    parser.add_argument("--copy-to-intake", action="store_true", help="Copy non-duplicate candidates into intake samples/<scenario>/ folders.")
    parser.add_argument("--include-standards", action="store_true", help="Include likely standards/specification PDFs. Default excludes them.")
    parser.add_argument("--output", help="Optional JSON report path.")
    parser.add_argument("--markdown-output", help="Optional Markdown report path.")
    args = parser.parse_args()

    report = build_collection_candidate_report(
        [Path(item) for item in args.inputs],
        existing_queues=[Path(item) for item in args.existing_queue],
        intake_dir=Path(args.intake_dir) if args.intake_dir else None,
        copy_to_intake=bool(args.copy_to_intake),
        include_standards=bool(args.include_standards),
    )
    if args.output:
        write_text_file(Path(args.output), json.dumps(report, ensure_ascii=False, indent=2))
    if args.markdown_output:
        write_text_file(Path(args.markdown_output), candidates_markdown(report))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


def build_collection_candidate_report(
    inputs: list[Path],
    *,
    existing_queues: list[Path] | None = None,
    intake_dir: Path | None = None,
    copy_to_intake: bool = False,
    include_standards: bool = False,
) -> dict[str, Any]:
    files = discover_candidate_files(inputs, include_standards=include_standards)
    existing_index = build_existing_index(existing_queues or [])
    intake_dir = intake_dir.expanduser().resolve() if intake_dir else None
    failures: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    copied: list[dict[str, Any]] = []
    for path in files:
        digest = sha256_file(path)
        duplicate = existing_index.get(digest)
        scenario, classification = classify_sample(path)
        profile_id, document_type = SCENARIO_PROFILE_DEFAULTS[scenario]
        item = {
            "path": str(path),
            "fileName": path.name,
            "sha256": digest,
            "sizeBytes": path.stat().st_size,
            "scenario": scenario,
            "effectiveScenario": str(duplicate.get("scenario")) if isinstance(duplicate, dict) and duplicate.get("scenario") else scenario,
            "profileId": profile_id,
            "documentType": document_type,
            "classification": classification,
            "duplicate": duplicate is not None,
            "duplicateOf": duplicate,
        }
        if copy_to_intake and duplicate is None:
            if intake_dir is None:
                failures.append({"code": "INTAKE_DIR_REQUIRED", "message": "--intake-dir is required with --copy-to-intake"})
            else:
                destination = copy_candidate_to_intake(path, digest=digest, intake_dir=intake_dir, scenario=scenario)
                item["copiedTo"] = str(destination)
                copied.append({"source": str(path), "destination": str(destination), "scenario": scenario})
        candidates.append(item)
    new_candidates = [item for item in candidates if not item.get("duplicate")]
    duplicate_candidates = [item for item in candidates if item.get("duplicate")]
    summary = {
        "schemaVersion": "aicheck-ocr-100-collection-candidates-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "inputs": [str(path) for path in inputs],
        "inputFiles": len(files),
        "newCandidates": len(new_candidates),
        "duplicates": len(duplicate_candidates),
        "copied": len(copied),
        "scenarioCounts": count_by_scenario(candidates),
        "newScenarioCounts": count_by_scenario(new_candidates),
        "duplicateScenarioCounts": count_by_scenario(duplicate_candidates, key="effectiveScenario"),
        "existingHashes": len(existing_index),
        "failureCount": len(failures),
    }
    return {
        "schemaVersion": "aicheck-ocr-100-collection-candidates-v1",
        "ok": not failures,
        "summary": summary,
        "candidates": candidates,
        "copied": copied,
        "failures": failures,
    }


def build_existing_index(paths: list[Path]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.expanduser().exists():
            continue
        payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
        items = (payload.get("cases") or payload.get("tasks")) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            digest = source.get("sha256")
            if not digest:
                digest = hash_from_task_path(item, base_dir=path.parent)
            if not digest:
                continue
            index[str(digest)] = {
                "queue": str(path),
                "caseId": item.get("caseId"),
                "taskId": item.get("taskId"),
                "scenario": item.get("scenario"),
                "fileName": source.get("fileName") or item.get("fileName"),
            }
    return index


def hash_from_task_path(item: dict[str, Any], *, base_dir: Path) -> str | None:
    raw = item.get("sourcePathResolved") or item.get("sourcePath")
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        candidates = [base_dir / path, Path.cwd() / path]
    else:
        candidates = [path]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return sha256_file(candidate)
    return None


def copy_candidate_to_intake(path: Path, *, digest: str, intake_dir: Path, scenario: str) -> Path:
    scenario_dir = intake_dir / "samples" / scenario
    scenario_dir.mkdir(parents=True, exist_ok=True)
    destination = scenario_dir / f"{digest.removeprefix('sha256:')[:12]}-{safe_filename(path.name)}"
    if not destination.exists():
        shutil.copy2(path, destination)
    return destination.resolve()


def count_by_scenario(items: list[dict[str, Any]], *, key: str = "scenario") -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        scenario = str(item.get(key) or item.get("scenario") or "unspecified")
        counts[scenario] = counts.get(scenario, 0) + 1
    return dict(sorted(counts.items()))


def candidates_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# OCR 100 Collection Candidates",
        "",
        f"- Input files: {summary.get('inputFiles', 0)}",
        f"- New candidates: {summary.get('newCandidates', 0)}",
        f"- Duplicates: {summary.get('duplicates', 0)}",
        f"- Copied: {summary.get('copied', 0)}",
        "",
        "## New Scenario Counts",
        "",
        "| Scenario | Count |",
        "| --- | ---: |",
    ]
    for scenario, count in (summary.get("newScenarioCounts") or {}).items():
        lines.append(f"| {scenario} | {count} |")
    if not summary.get("newScenarioCounts"):
        lines.append("| none | 0 |")
    lines.extend(["", "## Candidates", "", "| Status | Scenario | File | Destination |", "| --- | --- | --- | --- |"])
    for item in report.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        status = "duplicate" if item.get("duplicate") else "new"
        lines.append(f"| {status} | {item.get('effectiveScenario') or item.get('scenario')} | {item.get('fileName')} | {item.get('copiedTo', '')} |")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
