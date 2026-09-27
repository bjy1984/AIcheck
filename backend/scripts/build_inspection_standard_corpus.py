#!/usr/bin/env python3
"""Build a read-only MCP standard corpus from existing MinerU output; no OCR call or DB writes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from libs.db.seed import STANDARD_KNOWLEDGE_SEED
from libs.security.tenant import configured_tenant_id
from libs.inspection_standard_corpus import SCHEMA
from libs.standard_knowledge_canonical import build_standard_knowledge_record
from scripts.reocr_standards_with_mineru import build_sidecar_parse_result


def add_section_paths(parsed: dict) -> None:
    """Conservative OCR hierarchy, in source order; never derive parents from list letters."""
    active = []
    for item in sorted([*parsed.get("layoutBlocks", []), *parsed.get("tables", [])],
                       key=lambda row: row.get("sourceOrder", 10**9)):
        if item.get("sourceOrder") is None:
            continue
        text = str(item.get("text") or "").strip()
        if item.get("blockType") not in {"header", "footer", "page_number", "equation", "image", "table"}:
            # Contents entries are references, not headings. Boundaries must not inherit
            # the last body clause when OCR did not recognize a new heading.
            appendix = re.match(r"^附录\s*([A-Z])(?:\s|[（(]|$)", text)
            if appendix:
                active = [appendix[1]]
            elif re.fullmatch(r"目\s*[次录]|前\s*言|引\s*言|参考文献", text):
                active = []
            else:
                match = re.match(r"^((?:[A-Z]|\d+)(?:\.\d+)*)(?:[ \t]+|$)(.*)", text, re.S)
                if match:
                    number, body = match.groups()
                    # OCR can label decimal quantities as headings. A unit/multiplier,
                    # arithmetic sign, or a TOC leader disqualifies that interpretation.
                    quantity = re.match(r"^(?:倍|[%％℃°≤≥<>＝=±×/]|(?:mm|cm|km|m|MPa|kPa|Pa|kg|s|h|min|N|kN)(?:\b|[²³]))", body, re.I)
                    toc = re.search(r"[.…·]{2,}\s*\d+\s*$", body)
                    parts = number.split(".")
                    if not quantity and not toc and len(parts) <= 6 and (
                        len(parts) > 1 or (parts[0].isdigit() and item.get("headingLevel"))
                    ):
                        active = [".".join(parts[:index]) for index in range(1, len(parts)+1)]
                        item["clauseNo"] = number
        item["sectionPath"] = list(active)


def build(sidecars: Path, output: Path) -> dict:
    # The bundled catalog provides stable KF/document/version identities only.
    files = [deepcopy(f) for f in STANDARD_KNOWLEDGE_SEED["knowledgeFiles"]
             if f.get("sourceType") == "standard" and not f.get("projectId")]
    by_id = {f["id"]: f for f in files}
    targets = sorted(p.name for p in sidecars.iterdir() if p.is_dir() and (p / "content_list.json").is_file())
    unknown = sorted(set(targets) - by_id.keys())
    if unknown:
        raise ValueError(f"Unknown standard IDs: {unknown}")
    state = {key: [] for key in ("knowledge_files", "documents", "versions", "standard_knowledge_records")}
    state["knowledge_sources"] = [deepcopy(STANDARD_KNOWLEDGE_SEED["source"])]
    report = {"files": [], "fileCount": len(targets), "layoutFallbackCount": 0}
    for file_id in targets:
        file = by_id[file_id]
        document = deepcopy(next(d for d in STANDARD_KNOWLEDGE_SEED["documents"] if d["id"] == file["documentId"]))
        version = deepcopy(next(v for v in STANDARD_KNOWLEDGE_SEED["versions"] if v["id"] == document["currentVersionId"]))
        for item in (file, document, version):
            item["tenantId"] = configured_tenant_id()
        if document.get("projectId") or version.get("documentId") != document["id"]:
            raise ValueError(f"Invalid standard document mapping: {file_id}")
        parsed = build_sidecar_parse_result(sidecars, file, document, version)
        add_section_paths(parsed)
        reference_note = any(marker in file.get("fileName", "") for marker in ("临时替代", "变化记录"))
        file.update(contextType="context_only" if reference_note else "standard_reference",
                    sourceMethod="reference_note" if reference_note else "remote_ocr", ocrStatus="已识别")
        current = {"knowledge_files": [file], "documents": [document], "versions": [version],
                   "knowledge_sources": state["knowledge_sources"], "ocr_parse_results": [parsed]}
        canonical = build_standard_knowledge_record(current, file_id, ROOT, include_supplemental=False)
        canonical["pageCount"] = len(parsed.get("pages", []))
        canonical["readingOrderBasis"] = "mineru_content_list_source_order"
        canonical["hierarchyBasis"] = "numeric_and_appendix_headings_in_source_order_requires_verification"
        canonical["tenantId"] = file.get("tenantId")
        canonical["sourceMethod"] = file["sourceMethod"]
        raw_content = json.loads((sidecars/file_id/"content_list.json").read_text())
        source_table_count = sum(item.get("type") == "table" for item in raw_content if isinstance(item, dict))
        if len(parsed["tables"]) != source_table_count:
            raise ValueError(f"Source tables lost during normalization: {file_id}")
        fallback = parsed.get("metadata", {}).get("layoutFallback", False)
        canonical["ocrQuality"] = {"layoutFallback": fallback, "requiresSourceVerification": True}
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (sidecars/file_id).iterdir()
                  if p.is_file() and p.name in {"full.md", "content_list.json", "layout.json", "meta.json"}}
        canonical["sidecarHashes"] = hashes
        for key, item in (("knowledge_files", file), ("documents", document), ("versions", version),
                          ("standard_knowledge_records", canonical)):
            state[key].append(item)
        row = {"fileId": file_id, "fileName": file["fileName"], "pages": len(parsed.get("pages", [])),
               "blocks": len(canonical["blocks"]), "tables": len(canonical["tables"]),
               "sourceTables": source_table_count, "normalizedTables": len(parsed["tables"]),
               "equations": len(canonical["equations"]), "layoutFallback": fallback,
               "sourceFingerprint": canonical["sourceFingerprint"], "sidecarHashes": hashes,
               "sourceKind": "reference_note" if reference_note else "standard_ocr"}
        report["files"].append(row)
        report["layoutFallbackCount"] += int(fallback)
        print(file_id, row["blocks"], "blocks", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=output.parent, prefix=".standard-corpus-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"schemaVersion": SCHEMA, "state": state}, stream, ensure_ascii=False)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    report["corpusSha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar-dir", type=Path, default=ROOT/"rules/results/mineru_sidecar")
    parser.add_argument("--output", type=Path, required=True)
    args=parser.parse_args()
    result=build(args.sidecar_dir.resolve(), args.output.resolve())
    print(json.dumps({key:value for key,value in result.items() if key != "files"}))
