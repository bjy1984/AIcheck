from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_corpus import SCENARIO_PROFILE_DEFAULTS, expected_template_for_scenario
from scripts.ocr_eval_set import write_text_file

SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".heic", ".heif"}
STANDARD_PREFIXES = [
    "gb",
    "gbt",
    "gb∕t",
    "tsg",
    "nbt",
]
STANDARD_TEXT_PATTERNS = [
    "标准",
    "规范",
    "规则",
    "规程",
    "考核细则",
]
SCENARIO_RULES: list[tuple[str, list[str], float]] = [
    ("qualification_certificate_profile", ["资质", "许可证", "许可", "qualification", "license"], 0.9),
    ("ndt_rt_profile", ["rt", "射线", "radiographic", "radiography"], 0.88),
    ("ndt_ut_profile", ["ut", "超声", "ultrasonic"], 0.88),
    ("welding_record_profile", ["焊接", "焊口", "weld", "welding"], 0.84),
    ("construction_record_profile", ["交工", "施工", "construction", "record"], 0.82),
    ("quality_certificate_profile", ["材质", "质量证明", "质证", "material", "quality", "certificate"], 0.86),
    ("piping_table_profile", ["管道特性", "设计资料", "piping", "pipe list", "characteristic"], 0.86),
    ("seal_text_profile", ["印章", "盖章", "seal", "stamp"], 0.74),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a real-sample OCR 100 annotation queue from local documents.")
    parser.add_argument("inputs", nargs="+", help="Files or directories to scan for OCR 100 real samples.")
    parser.add_argument("--output", help="Output JSON path. Prints to stdout when omitted.")
    parser.add_argument("--base-dir", default=".", help="Base directory for stored source.path values.")
    parser.add_argument("--copy-to", help="Optional directory to copy discovered samples into.")
    parser.add_argument("--manifest", help="Optional JSON manifest mapping file names to OCR 100 scenarios.")
    parser.add_argument("--limit", type=int, help="Maximum number of files to ingest after filtering.")
    parser.add_argument("--include-standards", action="store_true", help="Include likely standards/specification PDFs. Default excludes them.")
    parser.add_argument("--scenario", choices=sorted(SCENARIO_PROFILE_DEFAULTS), help="Force every imported file into one OCR 100 scenario.")
    args = parser.parse_args()

    payload = build_sample_queue(
        [Path(item) for item in args.inputs],
        base_dir=Path(args.base_dir),
        copy_to=Path(args.copy_to) if args.copy_to else None,
        manifest=load_manifest(Path(args.manifest)) if args.manifest else {},
        include_standards=bool(args.include_standards),
        limit=args.limit,
        scenario_override=args.scenario,
    )
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        write_text_file(Path(args.output), content)
    else:
        print(content)
    return 0


def build_sample_queue(
    inputs: list[Path],
    *,
    base_dir: Path,
    copy_to: Path | None = None,
    manifest: dict[str, dict[str, Any]] | None = None,
    include_standards: bool = False,
    limit: int | None = None,
    scenario_override: str | None = None,
) -> dict[str, Any]:
    base_dir = base_dir.expanduser().resolve()
    files = discover_candidate_files(inputs, include_standards=include_standards)
    if limit is not None:
        files = files[: max(0, int(limit))]

    cases: list[dict[str, Any]] = []
    sequence_by_scenario: dict[str, int] = {}
    manifest = manifest or {}
    for source_path in files:
        manifest_item = manifest.get(source_path.name) or manifest.get(str(source_path))
        scenario, classification = classify_sample(source_path, scenario_override=scenario_override, manifest_item=manifest_item)
        sequence_by_scenario[scenario] = sequence_by_scenario.get(scenario, 0) + 1
        default_profile_id, default_document_type = SCENARIO_PROFILE_DEFAULTS[scenario]
        profile_id = str((manifest_item or {}).get("profileId") or default_profile_id)
        document_type = str((manifest_item or {}).get("documentType") or default_document_type)
        stored_path = copy_sample(source_path, copy_to=copy_to) if copy_to else source_path
        file_hash = sha256_file(stored_path)
        source = {
            "path": path_for_payload(stored_path, base_dir=base_dir),
            "originalPath": str(source_path.resolve()) if stored_path.resolve() != source_path.resolve() else None,
            "fileName": stored_path.name,
            "sha256": file_hash,
            "sizeBytes": stored_path.stat().st_size,
            "pageCount": page_count(stored_path),
            "mimeType": mimetypes.guess_type(stored_path.name)[0] or mime_type_for_suffix(stored_path),
            "classification": classification,
        }
        if manifest_item:
            for key in ["notes", "tags", "pageRanges", "recommendedAnnotations"]:
                if manifest_item.get(key):
                    source[key] = manifest_item[key]
        cases.append(
            {
                "caseId": f"real-{scenario}-{sequence_by_scenario[scenario]:03d}",
                "scenario": scenario,
                "profileId": profile_id,
                "documentType": document_type,
                "collectionStatus": "needs_labeling",
                "source": source,
                "expected": expected_template_for_scenario(scenario),
            }
        )

    for case in cases:
        source = case.get("source")
        if isinstance(source, dict) and source.get("originalPath") is None:
            source.pop("originalPath", None)
    return {
        "schemaVersion": "aicheck-ocr-100-sample-queue-v1",
        "name": "aicheck_ocr_100_real_sample_queue",
        "version": "0.1.0",
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": {
            "inputs": [str(path) for path in inputs],
            "cases": len(cases),
            "scenarioCounts": scenario_counts(cases),
            "includeStandards": include_standards,
            "collectionStatus": "needs_labeling",
            "certificationNote": "These cases are a labeling queue only. Replace expected placeholders with real positive-area bbox/polygon evidence before OCR 100 certification.",
        },
        "cases": cases,
    }


def discover_candidate_files(inputs: list[Path], *, include_standards: bool) -> list[Path]:
    candidates: list[Path] = []
    for raw_path in inputs:
        path = raw_path.expanduser()
        if path.is_dir():
            items = sorted(item for item in path.rglob("*") if item.is_file())
        elif path.is_file():
            items = [path]
        else:
            continue
        for item in items:
            if item.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if not include_standards and is_likely_standard_doc(item):
                continue
            candidates.append(item.resolve())
    return sorted(dict.fromkeys(candidates))


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    items = payload.get("samples") if isinstance(payload, dict) else payload
    if isinstance(items, dict):
        return {str(key): value for key, value in items.items() if isinstance(value, dict)}
    if not isinstance(items, list):
        raise ValueError("manifest must be a JSON object with samples[] or a filename-to-object mapping.")
    manifest: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        file_name = item.get("fileName") or item.get("path")
        scenario = item.get("scenario")
        if not file_name or scenario not in SCENARIO_PROFILE_DEFAULTS:
            continue
        manifest[str(file_name)] = item
    return manifest


def is_likely_standard_doc(path: Path) -> bool:
    normalized = normalize_text(path.name)
    return normalized.startswith(tuple(STANDARD_PREFIXES)) or any(pattern in normalized for pattern in STANDARD_TEXT_PATTERNS)


def classify_sample(
    path: Path,
    *,
    scenario_override: str | None = None,
    manifest_item: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scenario_override:
        return scenario_override, {"method": "override", "confidence": 1.0, "matchedTerms": [scenario_override]}
    if manifest_item and manifest_item.get("scenario") in SCENARIO_PROFILE_DEFAULTS:
        return str(manifest_item["scenario"]), {
            "method": "manifest",
            "confidence": float(manifest_item.get("confidence") or 1.0),
            "matchedTerms": [str(manifest_item.get("scenario"))],
        }
    normalized = normalize_text(path.name)
    raw_name = path.name.casefold()
    best: tuple[str, list[str], float] | None = None
    for scenario, terms, confidence in SCENARIO_RULES:
        matches = [term for term in terms if scenario_term_matches(term, normalized=normalized, raw_name=raw_name)]
        if matches and (best is None or confidence > best[2]):
            best = (scenario, matches, confidence)
    if best:
        return best[0], {"method": "filename_rule", "confidence": best[2], "matchedTerms": best[1]}
    return "quality_gate_profile", {"method": "default_quality_gate", "confidence": 0.25, "matchedTerms": []}


def mime_type_for_suffix(path: Path) -> str:
    if path.suffix.lower() in {".heic", ".heif"}:
        return "image/heic"
    return "application/octet-stream"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold())


def scenario_term_matches(term: str, *, normalized: str, raw_name: str) -> bool:
    normalized_term = normalize_text(term)
    if re.fullmatch(r"[a-z0-9]{1,3}", normalized_term):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", raw_name) is not None
    return normalized_term in normalized


def copy_sample(path: Path, *, copy_to: Path) -> Path:
    copy_to.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(path)[:12]
    destination = copy_to / f"{digest}-{safe_filename(path.name)}"
    if not destination.exists():
        shutil.copy2(path, destination)
    return destination.resolve()


def safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value).strip("._") or "sample"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def page_count(path: Path) -> int | None:
    if path.suffix.lower() != ".pdf":
        return 1
    try:
        import fitz  # type: ignore
    except Exception:
        return None
    try:
        with fitz.open(path) as document:
            return int(document.page_count)
    except Exception:
        return None


def path_for_payload(path: Path, *, base_dir: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(base_dir))
    except ValueError:
        return str(resolved)


def scenario_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        scenario = str(case.get("scenario") or "unspecified")
        counts[scenario] = counts.get(scenario, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    raise SystemExit(main())
