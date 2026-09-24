"""Scoped typed NDT table rows with recorded source locations, shared by station E."""
from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from libs.ocr.form_tables import form_tables
from libs.review_input_data import current_selected_parse_results
from libs.review_workstations import digest
from libs.table_schema_mapping import classify_table, load_signatures, map_row


def _table_location(table: dict[str, Any]) -> dict[str, Any]:
    bbox = table.get("bbox")
    valid_bbox = (isinstance(bbox, list) and len(bbox) == 4
                  and all(type(value) in (int, float) and math.isfinite(value) for value in bbox)
                  and bbox[0] >= 0 and bbox[1] >= 0 and bbox[2] > bbox[0] and bbox[3] > bbox[1])
    page = table.get("pageNo")
    text = _recorded_table_text(table)
    return {"pageNo": page if type(page) is int and page > 0 else None,
            "bbox": deepcopy(bbox) if valid_bbox else None,
            "quotedText": text}


_TAG_RE = re.compile(r"<[^>]+>")


def _recorded_table_text(table: dict[str, Any]) -> str | None:
    """表格的原文引用，只取**记录下来的**文本，绝不从 normalizedRows 拼。

    normalizedRows 是清洗过的字段值，拿它们拼成"引文"就是编造原文——
    test_r35 那条"不得伪造原文引用"守的正是这个。可引的只有两种：
    contentMarkdown（老路径），或 OCR 引擎自己给的 html（MinerU 的表没有
    contentMarkdown，只有 html，单元格与来源片段逐字一致）。html 去掉标签后
    就是那张表的原文；2026-09-10 前这一路一直是 None，导致判据侧 _refs()
    把表格行的引用整组丢掉，真实资料永远判成"证据不在所选文件"。
    """
    markdown = table.get("contentMarkdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown
    html = table.get("html")
    if isinstance(html, str) and html.strip():
        cells = _TAG_RE.sub(" ", html.replace("</td>", " | ").replace("</tr>", "\n"))
        text = "\n".join(" ".join(line.split()) for line in cells.splitlines())
        text = "\n".join(line.strip(" |") for line in text.splitlines() if line.strip(" |"))
        return text[:2000] if text else None
    return None


_SIGNATURES: list[dict[str, Any]] | None = None


def _signatures() -> list[dict[str, Any]]:
    global _SIGNATURES
    if _SIGNATURES is None:
        _SIGNATURES = load_signatures()
    return _SIGNATURES


def _signature_for(table: dict[str, Any], schemas: dict[str, str]) -> dict[str, Any] | None:
    """只在本次读取要的 schema 里认；认出别的表结构对这个节点没有意义。"""
    name = classify_table(table, _signatures())
    if name is None or name not in schemas:
        return None
    return next(item for item in _signatures() if item["businessSchema"] == name)


def _mapped_payload(row: dict[str, Any], signature: dict[str, Any], run: dict[str, Any], version_id: Any) -> dict[str, Any] | None:
    from libs.table_schema_mapping import normalize_header

    headers = {normalize_header(key): value for key, value in row.items()}
    object_id = next(
        (str(headers[normalize_header(column)]).strip()
         for column in signature.get("objectIdColumns") or []
         if str(headers.get(normalize_header(column)) or "").strip() not in ("", "/", "／", "-", "—")),
        "",
    )
    if not object_id:
        # 没有对象识别的行归属不到任何被审查对象，宁可不产生，也不并到别人名下。
        return None
    return {
        "projectId": run.get("projectId"),
        "objectType": signature.get("objectType"),
        "objectId": object_id,
        # frozen_domain_checks 的 scope 四栏之一；缺了它整域判成证据不足。
        "recordVersionId": version_id,
        **({"domain": signature["domain"]} if signature.get("domain") else {}),
        **({"applicable": True}
           if signature.get("domain") and signature.get("applicableWhen") == "table_present"
           else {}),
        # 这张表按签名能抽出的栏：判据据此区分「表上没写」与「要从别的文件抽、还没抽」。
        "extractedPaths": sorted({str(field["path"]) for field in signature.get("fields") or []}),
        **map_row(row, signature),
    }


def _selected_object_ids(run: dict[str, Any], state: dict[str, Any]) -> set[str] | None:
    """本次审查只审哪个对象；None 表示没有选取（多行即来源含糊）。

    显式的 run["selectedObjectIds"] 优先。没有时沿用工位已冻结的条件对象映射：
    工作台发起审查时把"下次审查对象"随请求送出（conditionObjectMapping），工位初始化
    把它冻成 conditionObjectMappingSnapshot.selection.subject.objectId——这就是产品里
    "审哪一个"的唯一来源，不另造一份。只认经 effective_condition_mapping 验过的快照：
    哈希、规则修订、来源指纹任何一项对不上都视为没有选取，被篡改或过期的映射
    不能悄悄把一张多元件的表收窄到某一行。
    """
    selected = run.get("selectedObjectIds")
    if isinstance(selected, list):
        return {str(item) for item in selected if item not in (None, "")}
    if not run.get("conditionObjectMappingSnapshot"):
        return None
    from libs.review_condition_mapping import effective_condition_mapping

    try:
        mapping = effective_condition_mapping(run, state)
    except ValueError:
        return None
    object_id = ((mapping or {}).get("subject") or {}).get("objectId")
    return {str(object_id)} if object_id not in (None, "") else None


def read_ndt_tables(state: dict[str, Any], run: dict[str, Any], schemas: dict[str, str], *, node_id: int) -> dict[str, list]:
    if (any(not isinstance(run.get(key), str) or not run[key].strip() for key in ("projectId", "tenantId"))
            or run.get("nodeId") != node_id):
        raise ValueError(f"r{node_id}_review_identity_incomplete_or_wrong_node")
    groups: dict[str, list] = {value: [] for value in schemas.values()}
    # 显式的对象选取。真实的元件核查记录一张表列全部元件，而这些规则一次只审一个
    # 对象：构建器遇到多列不会替人挑（挑第一行等于替被审方决定审哪个），于是判
    # "来源含糊"。工位若在 run 上写明 selectedObjectIds，这里就只放行这些对象；
    # 没写就维持原样。它挂在 run 上，fixture 冻结整个 run，重放自然带着这份选取。
    wanted = _selected_object_ids(run, state)
    versions = {row["id"]: row for row in state.get("versions", []) if row.get("tenantId") == run.get("tenantId")}
    documents = {row["id"] for row in state.get("documents", [])
                 if row.get("projectId") == run.get("projectId") and row.get("tenantId") == run.get("tenantId")}
    form_signatures = [item for item in _signatures() if item.get("form") and item["businessSchema"] in schemas]
    for parse in current_selected_parse_results(state, {}, context={"reviewRun": run}):
        version_id = parse.get("documentVersionId")
        if (parse.get("tenantId") != run.get("tenantId") or versions.get(version_id, {}).get("documentId") not in documents):
            continue
        candidates: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for table in parse.get("tables") or []:
            if not isinstance(table, dict):
                continue
            schema = table.get("businessSchema")
            signature = None
            if schema not in schemas:
                # OCR 沒認出來的表，用规则包里的签名再认一次。生产库里 1004 列真实
                # 表格数据就是躺在 businessSchema 为空的表里，而事实构建按名字取表，
                # 于是规则永远拿不到它们。这里按读取时机补认，既有文件不必重跑 OCR。
                signature = _signature_for(table, schemas)
                if signature is None:
                    continue
            candidates.append((table, signature))
        # 扫描件上的固定表格：OCR 只给片段不给表，按签名宣告的表名与表头从片段重建。
        # 同样按读取时机做，既有文件不必重跑 OCR。OCR 已经给了同一种表时不再重建，
        # 否则同一条记录会读成两行，被判成来源含糊。
        present = {signature["businessSchema"] if signature else table.get("businessSchema")
                   for table, signature in candidates}
        missing = [item for item in form_signatures if item["businessSchema"] not in present]
        candidates.extend(form_tables(parse, missing) if missing else [])
        for table, signature in candidates:
            schema = signature["businessSchema"] if signature else table.get("businessSchema")
            for index, row in enumerate(table.get("normalizedRows") or []):
                if not isinstance(row, dict):
                    continue
                ref = {"documentVersionId": version_id, **_table_location(table),
                       "tableId": table.get("tableId") or table.get("id"), "rowIndex": index}
                ref["id"] = f"R{node_id}-REF-" + digest(ref)[:24]
                ref["evidenceRefId"] = ref["id"]
                ref["confidence"] = row.get("confidence", table.get("structureConfidence"))
                # Client/OCR supplied evidenceRefs cannot redirect a record to another document.
                # 签名认出来的表要按签名对映；原样塞进去的话，判据读的是
                # actualPath，而表头是中文列名，一个也对不上。
                payload = _mapped_payload(row, signature, run, version_id) if signature else deepcopy(row)
                if payload is None:
                    continue
                if wanted is not None and str(payload.get("objectId") or "") not in wanted:
                    continue
                record = {**payload, "documentVersionId": version_id, "evidence": ref, "evidenceRefs": [ref]}
                groups[schemas[schema]].append(record)
    return groups
