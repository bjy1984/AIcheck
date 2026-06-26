#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "Scan"
OUTPUT_DIR = ROOT / "output" / "ocr"
TEXT_DIR = OUTPUT_DIR / "texts"
TMP_DIR = ROOT / "tmp" / "ocr_pages"
SWIFT_SOURCE = ROOT / "scripts" / "vision_ocr.swift"
SWIFT_BINARY = ROOT / "tmp" / "vision_ocr"
CREATED_AT = datetime.now().astimezone().date().isoformat()
METHOD = "macos_vision_ocr_v1"
TEXT_LAYER_METHOD = "pdf_text_layer_v1"
VERSION = "knowledge_ocr_classifier_v2"
REPORT_FILENAME = "scan_knowledge_classification_report.md"
REPORT_TITLE = "Scan 知识类型分类与 OCR 结果"
SUPPORTED_SUFFIXES = {".pdf", ".heic", ".heif", ".jpg", ".jpeg", ".png"}
FORCE_OCR_SOURCES = {
    "GB∕T 20801.1-2020 压力管道规范 工业管道 第1部分：总则.pdf",
    "GB∕T 20801.2-2020 压力管道规范 工业管道 第2部分：材料.pdf",
    "GB∕T 20801.3-2020 压力管道规范 工业管道 第3部分：设计和计算.pdf",
    "GB∕T 20801.4-2020 压力管道规范 工业管道 第4部分：制作与安装.pdf",
    "GB∕T 20801.5-2020 压力管道规范 工业管道 第5部分：检验与试验.pdf",
    "GB∕T 20801.6-2020 压力管道规范 工业管道 第6部分：安全防护.pdf",
    "NBT47014承压设备焊接工艺评定.pdf",
}

KNOWLEDGE_LABEL_ORDER = (
    "图纸类数据",
    "设计文件类数据",
    "现场照片类数据",
    "证书 OCR 类数据",
    "标准规范类数据",
    "待人工复核",
)

VISUAL_CLASSIFICATION_OVERRIDES = {
    "21fe60f0448d3fe8db68be35e811c560.jpg": ("standard", "标准规范类数据", "视觉抽检确认：特种设备许可目录页"),
    "IMG_6526.heic": ("drawing", "图纸类数据", "视觉抽检确认：低文本折叠图纸照片"),
    "IMG_6527.heic": ("drawing", "图纸类数据", "视觉抽检确认：低文本折叠图纸照片"),
    "IMG_6528.heic": ("drawing", "图纸类数据", "视觉抽检确认：低文本折叠图纸照片"),
}


@dataclass(frozen=True)
class CategoryRule:
    category: str
    label: str
    keywords: tuple[str, ...]


CATEGORY_RULES = (
    CategoryRule(
        "drawing",
        "图纸类数据",
        (
            "图号",
            "图纸",
            "图名",
            "竣工图",
            "施工图",
            "平面图",
            "系统图",
            "布置图",
            "剖面图",
            "大样图",
            "比例",
            "轴线",
            "设计号",
            "专业",
            "校对",
            "审核",
        ),
    ),
    CategoryRule(
        "design_doc",
        "设计文件类数据",
        (
            "设计说明",
            "技术规格书",
            "计算书",
            "设备清单",
            "材料表",
            "施工方案",
            "采购技术",
            "设计文件",
            "工程量",
            "参数",
            "目录",
            "编制",
            "审批",
        ),
    ),
    CategoryRule(
        "site_photo",
        "现场照片类数据",
        (
            "铭牌",
            "标识牌",
            "设备位号",
            "巡检",
            "隐蔽工程",
            "焊口",
            "现场",
            "安装位置",
            "仪表读数",
            "施工照片",
        ),
    ),
    CategoryRule(
        "certificate",
        "证书 OCR 类数据",
        (
            "合格证",
            "质量证明书",
            "检测报告",
            "检验报告",
            "材质",
            "校准证书",
            "检定证书",
            "报告编号",
            "证书编号",
            "炉批号",
            "批号",
            "检测结论",
            "检验结论",
            "出厂",
            "产品质量",
            "第三方",
            "委托单位",
            "检测机构",
            "检验依据",
            "certificate",
            "calibration",
            "inspection",
            "test report",
        ),
    ),
    CategoryRule(
        "standard",
        "标准规范类数据",
        (
            "标准",
            "规范",
            "规程",
            "条文",
            "术语",
            "总则",
            "附录",
            "发布",
            "实施",
            "gb/t",
            "gb ",
            "jg/t",
            "jgj",
            "hg/t",
            "sh/t",
            "nb/t",
            "dl/t",
            "iso ",
            "iec ",
        ),
    ),
)


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def which(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    bundled = Path("/Users/hankieyooly/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin") / name
    if bundled.exists():
        return str(bundled)
    raise RuntimeError(f"missing required executable: {name}")


def compile_ocr_binary() -> None:
    if not shutil.which("swiftc"):
        raise RuntimeError("missing required executable: swiftc")
    if SWIFT_BINARY.exists() and SWIFT_BINARY.stat().st_mtime >= SWIFT_SOURCE.stat().st_mtime:
        return
    SWIFT_BINARY.parent.mkdir(parents=True, exist_ok=True)
    run(["swiftc", str(SWIFT_SOURCE), "-o", str(SWIFT_BINARY)])


def pdf_page_count(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def page_text_result(text: str, page_number: int) -> dict:
    normalized = normalize_text(text)
    observations = [
        {
            "text": line,
            "confidence": 1.0,
            "boundingBox": None,
            "extraction_method": TEXT_LAYER_METHOD,
            "field_name": "text_line",
        }
        for line in normalized.splitlines()
        if line.strip()
    ]
    return {
        "path": "",
        "text": normalized,
        "observations": observations,
        "error": None,
        "source_page": page_number,
        "extraction_method": TEXT_LAYER_METHOD,
    }


def pdf_text_layer_results(path: Path, min_chars: int = 80) -> tuple[list[dict], list[int]]:
    reader = PdfReader(str(path))
    page_results: list[dict] = []
    ocr_page_numbers: list[int] = []

    if path.name in FORCE_OCR_SOURCES:
        for page_number in range(1, len(reader.pages) + 1):
            page_results.append({
                "path": "",
                "text": "",
                "observations": [],
                "error": "forced_ocr_for_bad_text_layer",
                "source_page": page_number,
                "extraction_method": METHOD,
            })
            ocr_page_numbers.append(page_number)
        return page_results, ocr_page_numbers

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""

        normalized = normalize_text(text)
        if len(normalized) >= min_chars and not text_layer_looks_garbled(normalized):
            page_results.append(page_text_result(normalized, page_number))
        else:
            page_results.append({
                "path": "",
                "text": "",
                "observations": [],
                "error": "text_layer_empty_or_low_signal",
                "source_page": page_number,
                "extraction_method": METHOD,
            })
            ocr_page_numbers.append(page_number)

    return page_results, ocr_page_numbers


def text_layer_looks_garbled(text: str) -> bool:
    if re.search(r"/G[0-9A-Fa-f]{2}", text):
        return True
    if text.count("\ufffd") >= 3:
        return True
    return False


def render_pdf(path: Path) -> list[Path]:
    page_dir = TMP_DIR / path.stem
    page_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(page_dir.glob("page-*.png"), key=page_sort_key)
    if len(existing) == pdf_page_count(path):
        return existing

    for stale in page_dir.glob("page-*.png"):
        stale.unlink()

    pdftoppm = which("pdftoppm")
    prefix = page_dir / "page"
    run([pdftoppm, "-r", "220", "-png", str(path), str(prefix)])
    return sorted(page_dir.glob("page-*.png"), key=page_sort_key)


def rendered_pdf_page_map(path: Path) -> dict[int, Path]:
    return {source_page_for_pdf_image(page_path): page_path for page_path in render_pdf(path)}


def page_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"-(\d+)\.png$", path.name)
    return (int(match.group(1)) if match else 0, path.name)


def ocr_images(paths: list[Path]) -> list[dict]:
    if not paths:
        return []
    command = [str(SWIFT_BINARY), *[str(path) for path in paths]]
    process = subprocess.run(command, check=True, text=True, capture_output=True)
    results = []
    for line in process.stdout.splitlines():
        if line.strip():
            results.append(json.loads(line))
    return results


def normalize_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def score_categories(text: str) -> dict[str, int]:
    lowered = text.lower()
    scores: dict[str, int] = {}
    for rule in CATEGORY_RULES:
        score = 0
        for keyword in rule.keywords:
            score += lowered.count(keyword.lower())
        scores[rule.category] = score
    return scores


def classify(text: str, suffix: str, source_name: str = "") -> tuple[str, str, dict[str, int], str]:
    scores = score_categories(text)
    compact = re.sub(r"\s+", "", text).lower()

    primary = primary_classification(compact, suffix, source_name)
    if primary:
        return primary[0], primary[1], scores, primary[2]

    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]
    if best_score == 0:
        if suffix.lower() in {".heic", ".heif", ".jpg", ".jpeg", ".png"}:
            return "site_photo", "现场照片类数据", scores, "未命中强关键词，按图片采集源临时归为现场照片/待复核"
        return "unknown", "待人工复核", scores, "未命中分类关键词"

    label = next(rule.label for rule in CATEGORY_RULES if rule.category == best_category)
    evidence = top_evidence(text, best_category)
    return best_category, label, scores, evidence


def primary_classification(compact_text: str, suffix: str, source_name: str = "") -> tuple[str, str, str] | None:
    # 主文档类型优先于普通关键词词频，避免“设计说明书引用标准号”被误归为标准规范。
    if source_name in VISUAL_CLASSIFICATION_OVERRIDES:
        return VISUAL_CLASSIFICATION_OVERRIDES[source_name]

    source_key = source_name.lower().replace(" ", "").replace("∕", "/")
    standard_code_signals = ("gb/t", "gbt", "gb", "nb/t", "nbt", "tsg")
    if suffix.lower() == ".pdf" and any(signal in source_key for signal in standard_code_signals):
        return "standard", "标准规范类数据", "文件名命中：标准/规范编号"
    if suffix.lower() == ".pdf" and any(signal in source_name for signal in ("标准", "规范", "规程", "规则", "考核细则")):
        return "standard", "标准规范类数据", "文件名命中：标准/规范类标题"

    prefix = compact_text[:500]
    if "交工资料" in prefix or "质量证明书" in prefix:
        return "certificate", "证书 OCR 类数据", "主类型命中：交工/质量证明资料"
    if "施工方案" in prefix and ("第一章工程概况" in compact_text[:1200] or "目录" in prefix):
        return "design_doc", "设计文件类数据", "主类型命中：施工方案"

    certificate_patterns = (
        "特种设备安装改造维修许可证",
        "特种设备制造许可证",
        "特种设备生产许可证",
        "licenseofspecialequipment",
        "manufacturelicenseofspecialequipment",
        "productionlicenseofspecialequipment",
        "质量证明书",
        "产品质量证明书",
        "安装质量证明书",
        "产品出厂检验合格证",
        "合格证",
        "射线检测报告",
        "检测报告书",
        "检测报告",
        "检验报告",
        "焊接工艺评定报告",
        "报告编号",
    )
    for pattern in certificate_patterns:
        if pattern.lower() in compact_text:
            return "certificate", "证书 OCR 类数据", f"主类型命中：{pattern}"

    design_doc_patterns = (
        "施工方案",
        "工艺设计说明书",
        "设计说明书",
        "设计说明",
        "综合材料表",
        "管道特性表",
        "设备一览表",
        "设备及管道油漆保温一览表",
        "油漆保温一览表",
        "压力管道强度计算书",
        "强度计算书",
        "管道安装材料表",
        "材料表",
        "图纸目录",
        "drawinglist",
        "pipingcharacteristiclist",
        "generalmateriallist",
    )
    for pattern in design_doc_patterns:
        if pattern.lower() in compact_text:
            return "design_doc", "设计文件类数据", f"主类型命中：{pattern}"

    drawing_patterns = (
        "管道及仪表流程图",
        "带控制点流程图",
        "配管平面图",
        "平面布置图",
        "平面图",
        "布置图",
        "流程图",
        "系统图",
        "大样图",
        "剖面图",
    )
    for pattern in drawing_patterns:
        if pattern.lower() in compact_text:
            return "drawing", "图纸类数据", f"主类型命中：{pattern}"

    standard_patterns = (
        "中华人民共和国国家标准",
        "中华人民共和国行业标准",
        "国家标准",
        "行业标准",
        "团体标准",
        "地方标准",
        "企业标准",
    )
    has_standard_document_signal = any(pattern in compact_text for pattern in standard_patterns)
    has_issue_signal = "发布" in compact_text and "实施" in compact_text
    if has_standard_document_signal and has_issue_signal and "设计院有限公司" not in compact_text:
        return "standard", "标准规范类数据", "主类型命中：标准发布/实施页"

    if suffix.lower() in {".heic", ".heif", ".jpg", ".jpeg", ".png"} and len(compact_text) < 80:
        return "site_photo", "现场照片类数据", "OCR 文本较少，按图片采集源临时归为现场照片/待复核"

    return None


def top_evidence(text: str, category: str) -> str:
    lowered = text.lower()
    rule = next(rule for rule in CATEGORY_RULES if rule.category == category)
    hits = []
    for keyword in rule.keywords:
        count = lowered.count(keyword.lower())
        if count:
            hits.append((count, keyword))
    hits.sort(reverse=True)
    return "关键词：" + "、".join(keyword for _, keyword in hits[:5])


def confidence_for_file(page_results: Iterable[dict]) -> float:
    values = []
    for page in page_results:
        for item in page.get("observations", []):
            value = item.get("confidence")
            if isinstance(value, (int, float)):
                values.append(float(value))
    return round(sum(values) / len(values), 4) if values else 0.0


def line_id(source_file: str, page: int, index: int, text: str) -> str:
    raw = f"{source_file}:{page}:{index}:{text}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def source_page_for_pdf_image(path: Path) -> int:
    match = re.search(r"-(\d+)\.png$", path.name)
    return int(match.group(1)) if match else 1


def write_text_file(source: Path, page_results: list[dict]) -> Path:
    target = TEXT_DIR / f"{source.stem}.txt"
    parts = []
    for index, page in enumerate(sorted(page_results, key=lambda item: item.get("source_page", 0)), start=1):
        text = normalize_text(page.get("text", ""))
        if len(page_results) > 1:
            parts.append(f"===== page {page.get('source_page', index)} =====")
        parts.append(text)
    target.write_text("\n\n".join(parts).strip() + "\n", encoding="utf-8")
    return target


def process_source(path: Path) -> dict:
    if path.suffix.lower() == ".pdf":
        page_results, ocr_page_numbers = pdf_text_layer_results(path)
        if ocr_page_numbers:
            page_map = rendered_pdf_page_map(path)
            image_paths = [page_map[page_number] for page_number in ocr_page_numbers if page_number in page_map]
            ocr_results = ocr_images(image_paths)
            for image_path, result in zip(image_paths, ocr_results):
                source_page = source_page_for_pdf_image(image_path)
                result["source_page"] = source_page
                result["extraction_method"] = METHOD
                for observation in result.get("observations", []):
                    observation["extraction_method"] = METHOD
                    observation["field_name"] = "ocr_line"
                page_results[source_page - 1] = result
    else:
        page_results = ocr_images([path])
        for result in page_results:
            result["source_page"] = 1
            result["extraction_method"] = METHOD
            for observation in result.get("observations", []):
                observation["extraction_method"] = METHOD
                observation["field_name"] = "ocr_line"

    text_path = write_text_file(path, page_results)
    full_text = normalize_text("\n".join(page.get("text", "") for page in page_results))
    category, label, scores, evidence = classify(full_text, path.suffix, path.name)
    return {
        "source_file": path.name,
        "source_path": str(path),
        "text_file": str(text_path.relative_to(ROOT)),
        "page_count": len(page_results),
        "char_count": len(full_text),
        "line_count": sum(len(page.get("observations", [])) for page in page_results),
        "avg_confidence": confidence_for_file(page_results),
        "category": category,
        "knowledge_type": label,
        "scores": scores,
        "evidence": evidence,
        "pages": page_results,
    }


def write_records(results: list[dict]) -> None:
    records_path = OUTPUT_DIR / "ocr_records.jsonl"
    with records_path.open("w", encoding="utf-8") as handle:
        for result in results:
            for page in result["pages"]:
                source_page = int(page.get("source_page", 1))
                observations = page.get("observations", [])
                for index, observation in enumerate(observations, start=1):
                    text = observation.get("text", "").strip()
                    if not text:
                        continue
                    extraction_method = (
                        observation.get("extraction_method")
                        or page.get("extraction_method")
                        or METHOD
                    )
                    record = {
                        "field_name": observation.get("field_name", "ocr_line"),
                        "field_value": text,
                        "source_file": result["source_file"],
                        "source_page": source_page,
                        "source_region": observation.get("boundingBox"),
                        "confidence": round(float(observation.get("confidence", 0.0)), 4),
                        "extraction_method": extraction_method,
                        "review_status": "pending",
                        "created_at": CREATED_AT,
                        "version": VERSION,
                        "lineage_id": line_id(result["source_file"], source_page, index, text),
                        "knowledge_type": result["knowledge_type"],
                        "category": result["category"],
                    }
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_classification_csv(results: list[dict]) -> None:
    path = OUTPUT_DIR / "classification.csv"
    fields = [
        "source_file",
        "knowledge_type",
        "category",
        "page_count",
        "line_count",
        "char_count",
        "avg_confidence",
        "evidence",
        "text_file",
        "drawing_score",
        "design_doc_score",
        "site_photo_score",
        "certificate_score",
        "standard_score",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            row = {field: result.get(field, "") for field in fields}
            row.update({
                "drawing_score": result["scores"].get("drawing", 0),
                "design_doc_score": result["scores"].get("design_doc", 0),
                "site_photo_score": result["scores"].get("site_photo", 0),
                "certificate_score": result["scores"].get("certificate", 0),
                "standard_score": result["scores"].get("standard", 0),
            })
            writer.writerow(row)


def first_text_snippet(result: dict, length: int = 180) -> str:
    text_path = ROOT / result["text_file"]
    text = text_path.read_text(encoding="utf-8")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:length] + ("..." if len(text) > length else "")


def write_report(results: list[dict]) -> None:
    report_path = OUTPUT_DIR / REPORT_FILENAME
    grouped: dict[str, list[dict]] = {}
    for result in results:
        grouped.setdefault(result["knowledge_type"], []).append(result)

    method_counts: dict[str, int] = {}
    for result in results:
        for page in result["pages"]:
            for observation in page.get("observations", []):
                method = observation.get("extraction_method") or page.get("extraction_method") or METHOD
                method_counts[method] = method_counts.get(method, 0) + 1

    lines = [
        f"# {REPORT_TITLE}",
        "",
        f"- 处理时间：{CREATED_AT}",
        f"- 分类依据：`knowledge_governance_tooling_plan.md` 中的五类知识来源：图纸、设计文件、现场照片、证书 OCR、标准规范。",
        f"- 提取方法：PDF 优先抽文本层，文本层为空或低信号页用 Poppler 渲染后走 macOS Vision 中英文 OCR；图片直接用 Vision OCR。",
        f"- 输出文本目录：`{str(TEXT_DIR.relative_to(ROOT))}/`",
        f"- 逐行溯源记录：`{str((OUTPUT_DIR / 'ocr_records.jsonl').relative_to(ROOT))}`",
        f"- 分类表：`{str((OUTPUT_DIR / 'classification.csv').relative_to(ROOT))}`",
        "",
        "## 提取方法汇总",
        "",
        "| 方法 | 行数 |",
        "|---|---:|",
    ]

    for method, count in sorted(method_counts.items()):
        lines.append(f"| {method} | {count} |")

    lines.extend([
        "",
        "## 分类汇总",
        "",
        "| 知识类型 | 文件数 | 页/图数 | OCR 行数 | 平均置信度 |",
        "|---|---:|---:|---:|---:|",
    ])

    for label in KNOWLEDGE_LABEL_ORDER:
        items = grouped.get(label, [])
        pages = sum(item["page_count"] for item in items)
        ocr_lines = sum(item["line_count"] for item in items)
        confidences = [item["avg_confidence"] for item in items if item["avg_confidence"]]
        avg = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
        lines.append(f"| {label} | {len(items)} | {pages} | {ocr_lines} | {avg:.4f} |")

    lines.extend([
        "",
        "## 文件级结果",
        "",
        "| 文件 | 知识类型 | 页/图数 | OCR 行数 | 字符数 | 平均置信度 | 分类证据 | OCR 文本 |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ])

    for result in sorted(results, key=lambda item: item["source_file"]):
        lines.append(
            "| {source_file} | {knowledge_type} | {page_count} | {line_count} | {char_count} | "
            "{avg_confidence:.4f} | {evidence} | `{text_file}` |".format(**result)
        )

    lines.extend([
        "",
        "## OCR 文本摘录",
        "",
    ])

    for result in sorted(results, key=lambda item: item["source_file"]):
        snippet = first_text_snippet(result).replace("|", "\\|")
        lines.extend([
            f"### {result['source_file']}",
            "",
            f"- 知识类型：{result['knowledge_type']}",
            f"- OCR 文本：`{result['text_file']}`",
            "",
            "```text",
            snippet,
            "```",
            "",
        ])

    report_path.write_text("\n".join(lines), encoding="utf-8")


def write_raw_page_json(results: list[dict]) -> None:
    raw_path = OUTPUT_DIR / "raw_ocr_pages.json"
    cleaned = []
    for result in results:
        cleaned.append({
            key: value
            for key, value in result.items()
            if key not in {"pages"}
        } | {"pages": result["pages"]})
    raw_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    global SOURCE_DIR, OUTPUT_DIR, TEXT_DIR, TMP_DIR, REPORT_FILENAME, REPORT_TITLE

    parser = argparse.ArgumentParser(description="Classify and OCR engineering knowledge files.")
    parser.add_argument("--input-dir", default="Scan", help="Input directory, relative to repo root or absolute.")
    parser.add_argument("--output-dir", default=None, help="Output directory, relative to repo root or absolute.")
    parser.add_argument("--tmp-dir", default=None, help="Temporary rendered page directory.")
    parser.add_argument("--report-name", default=None, help="Markdown report filename.")
    args = parser.parse_args()

    SOURCE_DIR = Path(args.input_dir)
    if not SOURCE_DIR.is_absolute():
        SOURCE_DIR = ROOT / SOURCE_DIR
    if not SOURCE_DIR.exists():
        raise RuntimeError(f"missing input directory: {SOURCE_DIR}")

    default_output = "output/ocr" if SOURCE_DIR.name == "Scan" else f"output/{SOURCE_DIR.name}_ocr"
    OUTPUT_DIR = Path(args.output_dir or default_output)
    if not OUTPUT_DIR.is_absolute():
        OUTPUT_DIR = ROOT / OUTPUT_DIR
    TEXT_DIR = OUTPUT_DIR / "texts"

    default_tmp = ROOT / "tmp" / f"{SOURCE_DIR.name}_ocr_pages"
    TMP_DIR = Path(args.tmp_dir) if args.tmp_dir else default_tmp
    if not TMP_DIR.is_absolute():
        TMP_DIR = ROOT / TMP_DIR

    REPORT_FILENAME = args.report_name or f"{SOURCE_DIR.name}_knowledge_classification_report.md"
    REPORT_TITLE = f"{SOURCE_DIR.name} 知识类型分类与 OCR 结果"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    compile_ocr_binary()

    sources = sorted(
        path
        for path in SOURCE_DIR.iterdir()
        if path.is_file() and path.name != ".DS_Store" and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    results = []
    for index, source in enumerate(sources, start=1):
        print(f"[{index}/{len(sources)}] {source.name}", file=sys.stderr, flush=True)
        results.append(process_source(source))

    write_records(results)
    write_classification_csv(results)
    write_raw_page_json(results)
    write_report(results)
    print(OUTPUT_DIR / REPORT_FILENAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
