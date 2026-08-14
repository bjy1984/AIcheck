from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PUBLIC_BENCHMARK_DATASETS: dict[str, dict[str, Any]] = {
    "doclaynet": {
        "name": "DocLayNet",
        "benchmarkType": "layout",
        "scenario": "public_layout_benchmark",
        "sourceUrl": "https://github.com/DS4SD/DocLayNet",
        "notes": "COCO-style document layout benchmark. Foundation-only; not an AIcheck production certification corpus.",
    },
    "pubtabnet": {
        "name": "PubTabNet",
        "benchmarkType": "table_structure",
        "scenario": "public_table_structure_benchmark",
        "sourceUrl": "https://github.com/ibm-aur-nlp/PubTabNet",
        "notes": "Image-based table recognition benchmark with HTML annotations. Foundation-only.",
    },
    "ctdar": {
        "name": "ICDAR 2019 cTDaR",
        "benchmarkType": "table_detection",
        "scenario": "public_table_detection_benchmark",
        "sourceUrl": "https://cndplab-founder.github.io/cTDaR2019/",
        "notes": "Table detection/recognition benchmark. Foundation-only.",
    },
}


def public_dataset_registry() -> dict[str, Any]:
    return {
        "schemaVersion": "aicheck-ocr-public-benchmark-registry-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "productionCertificationEligible": False,
        "datasets": PUBLIC_BENCHMARK_DATASETS,
    }


def build_public_benchmark_index(
    dataset: str,
    dataset_root: Path,
    *,
    limit: int | None = None,
    split: str | None = None,
) -> dict[str, Any]:
    dataset_key = normalize_dataset_key(dataset)
    root = dataset_root.expanduser().resolve()
    blockers: list[str] = []
    cases: list[dict[str, Any]] = []
    if not root.exists():
        blockers.append(f"dataset root does not exist: {root}")
    elif dataset_key == "doclaynet":
        cases, blockers = doclaynet_cases(root, limit=limit, split=split)
    elif dataset_key == "pubtabnet":
        cases, blockers = pubtabnet_cases(root, limit=limit, split=split)
    elif dataset_key == "ctdar":
        cases, blockers = ctdar_cases(root, limit=limit, split=split)
    return public_benchmark_report(dataset_key, root, cases=cases, blockers=blockers, split=split)


def normalize_dataset_key(dataset: str) -> str:
    key = str(dataset or "").strip().casefold().replace("_", "-")
    aliases = {
        "doclaynet": "doclaynet",
        "doc-lay-net": "doclaynet",
        "pubtabnet": "pubtabnet",
        "pub-tab-net": "pubtabnet",
        "ctdar": "ctdar",
        "icdar2019-ctdar": "ctdar",
        "icdar-2019-ctdar": "ctdar",
    }
    normalized = aliases.get(key)
    if not normalized:
        raise ValueError(f"unsupported public benchmark dataset: {dataset}")
    return normalized


def public_benchmark_report(
    dataset: str,
    root: Path,
    *,
    cases: list[dict[str, Any]],
    blockers: list[str],
    split: str | None,
) -> dict[str, Any]:
    metadata = PUBLIC_BENCHMARK_DATASETS[dataset]
    expected_counts = expected_annotation_counts(cases)
    source_exists = len([case for case in cases if case.get("sourceExists")])
    report_blockers = list(blockers)
    if not cases:
        report_blockers.append("no benchmark cases were indexed")
    return {
        "schemaVersion": "aicheck-ocr-public-benchmark-index-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "dataset": dataset,
        "datasetName": metadata["name"],
        "benchmarkType": metadata["benchmarkType"],
        "sourceUrl": metadata["sourceUrl"],
        "datasetRoot": str(root),
        "split": split,
        "foundationBenchmark": True,
        "productionCertificationEligible": False,
        "certificationPolicy": "Public datasets validate foundation OCR/layout/table capability only; AIcheck OCR 100 requires real labelled business samples.",
        "ok": bool(cases) and not report_blockers,
        "summary": {
            "cases": len(cases),
            "sourceExists": source_exists,
            "sourceMissing": len(cases) - source_exists,
            **expected_counts,
        },
        "blockers": report_blockers,
        "cases": cases,
    }


def doclaynet_cases(root: Path, *, limit: int | None, split: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[str] = []
    annotation_path = find_doclaynet_annotation(root, split=split)
    if annotation_path is None:
        return [], ["DocLayNet COCO annotation JSON was not found"]
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    annotations = payload.get("annotations") if isinstance(payload.get("annotations"), list) else []
    categories = payload.get("categories") if isinstance(payload.get("categories"), list) else []
    category_by_id = {item.get("id"): str(item.get("name") or item.get("id")) for item in categories if isinstance(item, dict)}
    annotations_by_image: dict[Any, list[dict[str, Any]]] = {}
    for annotation in annotations:
        if isinstance(annotation, dict):
            annotations_by_image.setdefault(annotation.get("image_id"), []).append(annotation)
    cases: list[dict[str, Any]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        file_name = str(image.get("file_name") or image.get("path") or "")
        if not file_name:
            continue
        layout_blocks = [
            doclaynet_layout_block(annotation, category_by_id)
            for annotation in annotations_by_image.get(image.get("id"), [])
            if coco_bbox(annotation.get("bbox")) is not None
        ]
        source_path = resolve_dataset_file(root, file_name)
        cases.append(
            {
                "caseId": f"public-doclaynet-{len(cases) + 1:05d}",
                "dataset": "doclaynet",
                "scenario": PUBLIC_BENCHMARK_DATASETS["doclaynet"]["scenario"],
                "foundationBenchmark": True,
                "productionCertificationEligible": False,
                "source": str(source_path) if source_path else file_name,
                "sourceExists": bool(source_path and source_path.exists()),
                "imageId": image.get("id"),
                "width": image.get("width"),
                "height": image.get("height"),
                "expected": {"layoutBlocks": layout_blocks},
            }
        )
        if limit is not None and len(cases) >= max(0, int(limit)):
            break
    if not cases:
        blockers.append("DocLayNet annotation JSON had no usable images")
    return cases, blockers


def doclaynet_layout_block(annotation: dict[str, Any], category_by_id: dict[Any, str]) -> dict[str, Any]:
    return {
        "label": category_by_id.get(annotation.get("category_id"), str(annotation.get("category_id"))),
        "bbox": coco_bbox(annotation.get("bbox")),
        "area": annotation.get("area"),
    }


def find_doclaynet_annotation(root: Path, *, split: str | None) -> Path | None:
    candidates = sorted(path for path in root.rglob("*.json") if path.is_file())
    preferred_terms = [term for term in [split, "coco", "val", "train", "test"] if term]
    for term in preferred_terms:
        for path in candidates:
            if str(term).casefold() in path.name.casefold():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(payload, dict) and isinstance(payload.get("images"), list) and isinstance(payload.get("annotations"), list):
                    return path
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("images"), list) and isinstance(payload.get("annotations"), list):
            return path
    return None


def pubtabnet_cases(root: Path, *, limit: int | None, split: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    jsonl_path = find_pubtabnet_jsonl(root, split=split)
    if jsonl_path is None:
        return [], ["PubTabNet JSONL annotation file was not found"]
    cases: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            if split and str(item.get("split") or "").casefold() not in {"", split.casefold()}:
                continue
            file_name = str(item.get("filename") or item.get("image_path") or item.get("file_name") or "")
            html = pubtabnet_html(item.get("html"))
            source_path = resolve_dataset_file(root, file_name) if file_name else None
            cases.append(
                {
                    "caseId": f"public-pubtabnet-{len(cases) + 1:05d}",
                    "dataset": "pubtabnet",
                    "scenario": PUBLIC_BENCHMARK_DATASETS["pubtabnet"]["scenario"],
                    "foundationBenchmark": True,
                    "productionCertificationEligible": False,
                    "source": str(source_path) if source_path else file_name,
                    "sourceExists": bool(source_path and source_path.exists()),
                    "split": item.get("split"),
                    "expected": {
                        "tables": [
                            {
                                "businessSchema": "pubtabnet_html_table",
                                "html": html,
                                "cellCount": len(item.get("html", {}).get("cells", [])) if isinstance(item.get("html"), dict) else None,
                                "bbox": bbox_or_none(item.get("bbox")),
                            }
                        ]
                    },
                }
            )
            if limit is not None and len(cases) >= max(0, int(limit)):
                break
    blockers = [] if cases else ["PubTabNet JSONL had no usable rows for the requested split"]
    return cases, blockers


def find_pubtabnet_jsonl(root: Path, *, split: str | None) -> Path | None:
    candidates = sorted(path for path in root.rglob("*.jsonl") if path.is_file())
    if split:
        for path in candidates:
            if split.casefold() in path.name.casefold():
                return path
    return candidates[0] if candidates else None


def pubtabnet_html(value: Any) -> str:
    if isinstance(value, dict):
        structure = value.get("structure") if isinstance(value.get("structure"), dict) else {}
        tokens = structure.get("tokens") if isinstance(structure.get("tokens"), list) else None
        if tokens is not None:
            return "".join(str(token) for token in tokens)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or "")


def ctdar_cases(root: Path, *, limit: int | None, split: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    xml_files = sorted(path for path in root.rglob("*.xml") if path.is_file())
    if split:
        xml_files = [path for path in xml_files if split.casefold() in str(path).casefold()]
    cases: list[dict[str, Any]] = []
    for xml_path in xml_files:
        tables = ctdar_tables(xml_path)
        if not tables:
            continue
        source_path = matching_image_for_xml(xml_path)
        cases.append(
            {
                "caseId": f"public-ctdar-{len(cases) + 1:05d}",
                "dataset": "ctdar",
                "scenario": PUBLIC_BENCHMARK_DATASETS["ctdar"]["scenario"],
                "foundationBenchmark": True,
                "productionCertificationEligible": False,
                "source": str(source_path) if source_path else str(xml_path),
                "sourceExists": bool(source_path and source_path.exists()),
                "annotationPath": str(xml_path),
                "expected": {"tables": tables},
            }
        )
        if limit is not None and len(cases) >= max(0, int(limit)):
            break
    blockers = [] if cases else ["cTDaR XML annotations with table coordinates were not found"]
    return cases, blockers


def ctdar_tables(xml_path: Path) -> list[dict[str, Any]]:
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return []
    tables: list[dict[str, Any]] = []
    for element in root.iter():
        if local_name(element.tag) != "Coords":
            continue
        polygon = parse_points(element.attrib.get("points"))
        if not polygon:
            continue
        tables.append(
            {
                "businessSchema": "ctdar_table_region",
                "polygon": polygon,
                "bbox": polygon_bbox(polygon),
            }
        )
    return tables


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse_points(value: str | None) -> list[list[float]]:
    points: list[list[float]] = []
    for item in str(value or "").strip().split():
        if "," not in item:
            continue
        raw_x, raw_y = item.split(",", 1)
        try:
            points.append([float(raw_x), float(raw_y)])
        except ValueError:
            continue
    return points


def polygon_bbox(polygon: list[list[float]]) -> list[float] | None:
    if not polygon:
        return None
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def matching_image_for_xml(xml_path: Path) -> Path | None:
    suffixes = [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"]
    for suffix in suffixes:
        candidate = xml_path.with_suffix(suffix)
        if candidate.exists():
            return candidate
    stem = xml_path.stem
    for candidate in xml_path.parent.glob(stem + ".*"):
        if candidate.suffix.lower() in suffixes:
            return candidate
    return None


def coco_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        x, y, width, height = [float(item) for item in value[:4]]
    except (TypeError, ValueError):
        return None
    return [x, y, x + width, y + height]


def bbox_or_none(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        return [float(item) for item in value[:4]]
    except (TypeError, ValueError):
        return None


def resolve_dataset_file(root: Path, file_name: str) -> Path | None:
    if not file_name:
        return None
    direct = root / file_name
    if direct.exists():
        return direct
    basename = Path(file_name).name
    matches = list(root.rglob(basename))
    return matches[0] if matches else direct


def expected_annotation_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    layout_blocks = 0
    tables = 0
    table_cells = 0
    for case in cases:
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        layout_blocks += len(expected.get("layoutBlocks") or [])
        table_items = [item for item in expected.get("tables") or [] if isinstance(item, dict)]
        tables += len(table_items)
        table_cells += sum(int(item.get("cellCount") or 0) for item in table_items)
    return {
        "expectedLayoutBlocks": layout_blocks,
        "expectedTables": tables,
        "expectedTableCells": table_cells,
    }
