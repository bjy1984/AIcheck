"""把 regulatory_tables.yaml 里所有未签字的表导成一份逐格勾选清单（法规核对人用）。

为什么要这份东西：verifiedBy 空着时规则只出预警，签字后才判不符合。核对人要做的
不该是"重读四本标准"，而是"翻到指定页对一个数"。所以清单按 标准 → 条款 → 数值
排好，每格带上抽取方式（正文/文字层/扫描件识别），可信度低的排前面先核。

    python -m scripts.build_regulatory_signoff_checklist > 法规数值核对清单.md
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from libs.regulatory_tables import load_tables

# 越靠前越需要人核：扫描件识别 > 版面文字层 > 官方全文
CONFIDENCE_ORDER = {
    "none": 0,
    "vendor_page": 1,
    "secondary_sources": 1,
    "ocr": 2,
    "official_pdf_ocr": 3,
    "official_pdf_ocr_page_images": 3,
    "official_pdf_text_layer": 4,
    "official_pdf_text_layer_positional": 4,
    "official_full_text_preview": 5,
}
CONFIDENCE_LABEL = {
    0: "无数据（未预填）",
    1: "厂商页/二手来源",
    2: "扫描件 OCR",
    3: "扫描件逐页看图",
    4: "PDF 文字层解析",
    5: "官方全文正文",
}


INHERITED = ("source", "sourceClause", "sourceFile", "sourceUrl", "extractedFrom", "caveat", "standard")


def _walk(node: Any, path: tuple[str, ...] = (), inherited: dict[str, Any] | None = None) -> Any:
    """带元数据继承：条目挂在父段落下时（如焊条的 items），出处与抽取方式跟父段落走。"""
    inherited = inherited or {}
    if isinstance(node, dict):
        merged = {**inherited, **{key: node[key] for key in INHERITED if node.get(key) is not None}}
        if "verifiedBy" in node:
            yield path, {**merged, **node}
        for key, value in node.items():
            yield from _walk(value, (*path, str(key)), merged)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, (*path, f"[{index}]"), inherited)


def _values(node: Any, prefix: str = "", depth: int = 0) -> list[tuple[str, str]]:
    """把一张表里的数值摊平成 (位置, 值) 供逐格打钩；元数据字段不摊。"""
    skip = {"verifiedBy", "verifiedOn", "extractedFrom", "sourceFile", "sourceUrl", "sourceClause", "note", "caveat", "source", "readOn"}
    out: list[tuple[str, str]] = []
    if depth > 4:
        return out
    if isinstance(node, dict):
        for key, value in node.items():
            if key in skip:
                continue
            out.extend(_values(value, f"{prefix}.{key}" if prefix else str(key), depth + 1))
    elif isinstance(node, list):
        if node and all(not isinstance(item, dict | list) for item in node):
            out.append((prefix, "、".join(str(item) for item in node)))
        else:
            for index, item in enumerate(node):
                out.extend(_values(item, f"{prefix}[{index}]", depth + 1))
    elif node is not None:
        out.append((prefix, str(node)))
    return out


def build(tables: dict[str, Any] | None = None) -> str:
    tables = tables if tables is not None else load_tables()
    sections = [(path, node) for path, node in _walk(tables) if not node.get("verifiedBy")]
    sections.sort(key=lambda item: CONFIDENCE_ORDER.get(str(item[1].get("extractedFrom") or "none"), 2))

    lines = [
        "# 法规数值核对清单",
        "",
        "填写方式：对照采购的标准正本逐格核对，一致就在「核对」列打 ✔；不一致把正本上的值写进「正本值」列。",
        "整张表核完后，把核对人姓名与日期写进 `regulatory_tables.yaml` 对应表的 `verifiedBy` / `verifiedOn`。",
        "签字前该表只出预警；签字后同样的情况才判「不符合」并进整改流程。",
        "",
        f"待核表共 {len(sections)} 张，按可信度从低到高排列——排在前面的最需要人核。",
        "",
    ]
    for index, (path, node) in enumerate(sections, start=1):
        method = str(node.get("extractedFrom") or "none")
        confidence = CONFIDENCE_ORDER.get(method, 2)
        source = node.get("standard") or node.get("source") or ".".join(path)
        lines.append(f"## {index}. {source}")
        lines.append("")
        lines.append(f"- YAML 位置：`{'.'.join(path)}`")
        if node.get("sourceClause"):
            lines.append(f"- 条款：{node['sourceClause']}")
        if node.get("sourceFile"):
            lines.append(f"- 我用的文件：{node['sourceFile']}")
        lines.append(f"- 抽取方式：{CONFIDENCE_LABEL.get(confidence, method)}")
        if node.get("caveat"):
            lines.append(f"- 提醒：{node['caveat']}")
        if node.get("note"):
            lines.append(f"- 备注：{node['note']}")
        lines.append("")
        rows = _values(node)
        lines.append("| 位置 | 我读到的值 | 正本值（不一致时填） | 核对 |")
        lines.append("|---|---|---|---|")
        for where, value in rows[:400]:
            safe = value.replace("|", "\\|")
            lines.append(f"| {where} | {safe[:120]} |  |  |")
        if len(rows) > 400:
            lines.append(f"| …… | 另有 {len(rows) - 400} 格，见 YAML |  |  |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.write(build())
