"""AI 复核对话消息里的引用块组装。

从 apps/api/routes.py 搬出来的纯函数：把节点固定条款与证据链接整理成消息可引用的
`references`，并把内部标准编号翻成人读的显示文本。

搬家理由：这两个函数与 HTTP 请求、鉴权、状态读写都无关，只是数据整形，
留在两万九千行的路由文件里既难找也难测。
"""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any


def review_basis_display_label(item: dict[str, Any]) -> str:
    """把内部标准编号翻成监检看得懂的写法。

    库里存的是 `STD-TSG-D7006-2020` 这类内部编号，直接展示等于让人自己解码。
    引用文本必须用标准编号加条款号，不能露出 LOC/STD 等内部标识。
    """
    standard_code = str(
        item.get("standardCode")
        or item.get("standardRef")
        or item.get("standardName")
        or ""
    ).strip()
    internal_code = standard_code.removeprefix("STD-")
    announcement_match = re.fullmatch(r"SAMR-(\d{4})-(\d+)", internal_code)
    if announcement_match:
        standard_code = (
            f"市场监管总局公告 {announcement_match.group(1)} 年第 "
            f"{announcement_match.group(2)} 号"
        )
    elif standard_code.startswith("STD-"):
        standard_code = internal_code
        standard_code = re.sub(r"^TSG-D", "TSG D", standard_code)
        standard_code = re.sub(r"^TSG-", "TSG ", standard_code)
        standard_code = re.sub(r"^GBT-", "GB/T ", standard_code)
        standard_code = re.sub(r"^NBT-", "NB/T ", standard_code)
        standard_code = re.sub(r"^JBT-", "JB/T ", standard_code)
        standard_code = re.sub(r"^SYT-", "SY/T ", standard_code)
        standard_code = re.sub(r"^GB-", "GB ", standard_code)
        standard_code = re.sub(r"-(\d{4})$", r"—\1", standard_code)
    standard_code = re.sub(
        r"^市场监管总局公告\s*(\d{4})\s*年\s*第\s*(\d+)\s*号$",
        r"市场监管总局公告 \1 年第 \2 号",
        standard_code,
    )

    clause_no = str(item.get("clauseNo") or "").strip()
    clause_no = re.sub(r"(\d)-(?=\d)", r"\1～", clause_no)
    if re.match(r"^附件\s*\d", clause_no):
        clause_label = re.sub(r"^附件\s*(\d+)", r"附件 \1", clause_no.split("：", 1)[0])
    elif re.match(r"^(附件|附录|表|第)", clause_no):
        clause_label = clause_no
    elif clause_no:
        clause_label = f"第 {clause_no} 条"
    else:
        clause_label = ""
    return " ".join(value for value in (standard_code, clause_label) if value).strip()


def review_message_source_references(
    basis_items: list[dict[str, Any]],
    evidence_links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """组装消息可引用的依据与证据清单。

    `aliases` 是给引用解析用的多种写法：模型可能写标准编号、写文件名、写内部 ID，
    都要能落到同一条引用上。少一种写法，引用就会渲染成裸文本。
    """
    references: list[dict[str, Any]] = []
    for item in basis_items[:12]:
        reference_id = str(item.get("sourceLocatorId") or item.get("clauseId") or "")
        if not reference_id:
            continue
        standard_ref = str(item.get("standardCode") or item.get("standardRef") or "").strip()
        clause_no = str(item.get("clauseNo") or "").strip()
        file_name = str(item.get("fileName") or "").strip()
        display_label = review_basis_display_label(item)
        aliases = [
            reference_id,
            standard_ref,
            f"{standard_ref} {clause_no}".strip(),
            standard_ref.removeprefix("STD-"),
            display_label,
            Path(file_name).stem if file_name else "",
        ]
        references.append(
            {
                "kind": "basis",
                "referenceId": reference_id,
                "label": display_label or reference_id,
                "aliases": list(dict.fromkeys(value for value in aliases if value)),
                "basis": deepcopy(item),
            }
        )
    for item in evidence_links[:12]:
        reference_id = str(item.get("id") or "")
        if not reference_id:
            continue
        file_name = str(item.get("fileName") or item.get("documentName") or "").strip()
        aliases = [reference_id, file_name, str(item.get("fieldName") or "").strip()]
        references.append(
            {
                "kind": "evidence",
                "referenceId": reference_id,
                "label": file_name or reference_id,
                "aliases": list(dict.fromkeys(value for value in aliases if value)),
                "evidence": deepcopy(item),
            }
        )
    return references
