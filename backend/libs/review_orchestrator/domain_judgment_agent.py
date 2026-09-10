"""让 agent 读正文，把冻结判据要的事实填出来——**只填事实，不下结论**。

为什么需要这一层：2026-09-10 的盘点发现冻结判据要读 465 个字段路径，其中 431 次
是布尔结论（例如"是否已审阅并确信材料为规定等级"）。这些不是文件上的一栏，任何
OCR 都变不出来。判据自己的 `sourceReview.method` 写着 `agent_text_layer_reading`，
设计意图就是由 agent 读正文得出。

这一层的边界写死在程序里，不是写在提示词里——提示词是请求，代码才是约束：

1. **agent 不产生结论。** 它只填 actualPath 的值；符合／不符合由冻结判据算。
   把判定权交给模型，等于把整套冻结判据架空。
2. **每个值都要附原文引用，且引用必须在该页正文里逐字找得到。** 对不上就丢掉
   那个值——这是机械检查，不靠模型自律。
3. **拿不准就留空。** 值为 null 的路径整个不出现，判据那边会判成缺证据。
   模型"猜一个合理的"比留空危险得多。
4. **不认识的路径一律丢掉。** 只有判据宣告过的路径能进来。
"""

from __future__ import annotations

import json
import re
from typing import Any

# 引用比对前先把空白与全角标点归一；OCR 正文常带零宽空白，而模型抄回来的引用
# 往往把全角标点写成半角，直接逐字比对会全军覆没。
_WIDE = {"（": "(", "）": ")", "：": ":", "，": ",", "；": ";", "　": "", "”": '"', "“": '"'}


def normalize_quote(value: Any) -> str:
    text = str(value or "")
    for wide, narrow in _WIDE.items():
        text = text.replace(wide, narrow)
    return re.sub(r"\s+", "", text)


def page_text(parse_results: list[dict[str, Any]], document_version_id: str, page_no: Any) -> str:
    """把一页的正文片段接起来，供引用比对。"""
    parts = []
    for parse in parse_results:
        if parse.get("documentVersionId") != document_version_id:
            continue
        for fragment in parse.get("fragments") or []:
            if isinstance(fragment, dict) and fragment.get("pageNo") == page_no:
                parts.append(str(fragment.get("text") or ""))
    return normalize_quote("".join(parts))


def declared_paths(domain_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """判据宣告过的路径，连同它期望的形状——提示词和验收都以这份为准。"""
    paths: dict[str, dict[str, Any]] = {}
    for path in domain_spec.get("requiredPaths") or []:
        paths[str(path)] = {"kind": "value", "operator": "present"}
    for rule in domain_spec.get("checks") or []:
        if not isinstance(rule, dict):
            continue
        for key in ("actualPath", "applicabilityPath"):
            path = rule.get(key)
            if not path:
                continue
            expected = rule.get("expected")
            paths.setdefault(str(path), {
                "kind": "boolean" if key == "applicabilityPath" or isinstance(expected, bool) else "value",
                "operator": rule.get("operator"),
                "sourceClause": rule.get("sourceClause"),
            })
    return paths


def build_messages(
    domain_name: str,
    domain_spec: dict[str, Any],
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """`pages` 是 [{documentVersionId, pageNo, text}]，正文原样给模型。"""
    wanted = [
        {"path": path, "shape": meta["kind"], "clause": meta.get("sourceClause")}
        for path, meta in declared_paths(domain_spec).items()
    ]
    instructions = (
        "你在读一份工程资料的正文，任务是把下列字段从正文里读出来。\n"
        "规矩：\n"
        "1. 只读正文写了的东西。正文没有明确写的，value 一律填 null——不要推测、"
        "不要按常理补、不要因为“通常都会做”就填 true。\n"
        "2. 每个非 null 的 value 都要附 quotedText，必须是正文里**逐字**出现的一段，"
        "不得改写、不得节略成大意。\n"
        "3. shape 为 boolean 的字段只填 true / false / null。\n"
        "4. 不要下“符合”“不符合”的结论——那不是你的工作，你只提供事实。\n"
        '输出 JSON：{"fields":[{"path":..., "value":..., "documentVersionId":..., '
        '"pageNo":..., "quotedText":...}]}'
    )
    body = {"domain": domain_name, "fields": wanted, "pages": pages}
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
    ]


def parse_response(
    content: str,
    domain_spec: dict[str, Any],
    parse_results: list[dict[str, Any]],
    *,
    allowed_document_version_ids: set[str],
) -> dict[str, Any]:
    """把模型回复变成事实，并逐条验证引用。返回 {values, evidenceRefs, rejected}。

    `rejected` 不是调试信息，是证据——它记录模型给了值但引用对不上的那些路径。
    这种情况必须看得见，不能悄悄当成"没填"。
    """
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return {"values": {}, "evidenceRefs": [], "rejected": [{"reason": "response_not_json"}]}
    declared = declared_paths(domain_spec)
    values: dict[str, Any] = {}
    refs: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in (payload.get("fields") if isinstance(payload, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        meta = declared.get(path)
        if meta is None:
            rejected.append({"path": path, "reason": "path_not_declared_by_criteria"})
            continue
        value = item.get("value")
        if value is None:
            continue  # 留空是允许的，也是被鼓励的。
        if meta["kind"] == "boolean" and not isinstance(value, bool):
            rejected.append({"path": path, "reason": "boolean_field_got_non_boolean"})
            continue
        version_id = str(item.get("documentVersionId") or "")
        if version_id not in allowed_document_version_ids:
            rejected.append({"path": path, "reason": "evidence_outside_selected_documents"})
            continue
        page_no = item.get("pageNo")
        quote = str(item.get("quotedText") or "")
        if not quote.strip():
            rejected.append({"path": path, "reason": "value_without_quotation"})
            continue
        if normalize_quote(quote) not in page_text(parse_results, version_id, page_no):
            # 模型引了一段正文里找不到的话。这是编造，不是误读，值一律不采。
            rejected.append({"path": path, "reason": "quotation_not_found_in_page", "quotedText": quote})
            continue
        values[path] = value
        refs.append({"documentVersionId": version_id, "pageNo": page_no, "quotedText": quote})
    return {"values": values, "evidenceRefs": refs, "rejected": rejected}


def assign_paths(values: dict[str, Any]) -> dict[str, Any]:
    """把 a.b.c 形式的路径摊成嵌套，供判据按 actualPath 读取。"""
    row: dict[str, Any] = {}
    for path, value in values.items():
        target = row
        keys = path.split(".")
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value
    return row
