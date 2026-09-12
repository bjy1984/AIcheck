"""设计文件上的「设计单位」：图签里写的，和设计许可章盖的。

## 为什么必须有

节点 1（设计单位资质）的 AC-R01-01 用 check_all_equal 比三处：
designLicense.holderName / designDocument.titleBlockOrganization / designDocument.designSealOrganization。
2026-09-11 全节点扫描：后两处在全库**没有任何地方产出**，执行器只读不写，于是这条核对
永远只有许可证一侧、永远 fewer_than_two_comparable_values。

## 数据从哪来（按生产样本）

地上甲类储罐区2（含泵区）施工图.pdf，节点 1 的输入之一：
- 图签：首页「项目名称」字段 / 首页 table 片段的开头
  `广东政和工程有限公司GEM-HORSE ENGINEERING CO.,LTD(原广东政和石油化工建筑设计有限公司) 资质等级…`
  ——图签第一格就是设计单位，后面跟英文名与「资质等级」。
- 设计章：seals[] 第 1/3/4 页 text=「广东政和工程有限公司」；许可证那份上的章是
  「广东省市场监督管理局」（发证机关，不是设计单位）——按后缀筛：公司/设计院/研究院/设计所。

两处都只在 materialTypeCode=design_document 的输入里找；证书文件本身不算。
"""
from __future__ import annotations

import re
from typing import Any

from libs.review_input_data import selected_parse_results
from libs.review_orchestrator.certificate_facts import _documents_by_version, _evidence, _confidence_unavailable

FACT_PATHS = {"titleBlockOrganization": "designDocument.titleBlockOrganization",
              "designSealOrganization": "designDocument.designSealOrganization"}

_ORG_SUFFIX = r"(?:有限公司|股份有限公司|有限责任公司|公司|设计院|研究院|设计所|勘察设计院)"
# 图签开头的中文单位名：从行首到第一个单位后缀为止，后面通常紧跟英文名或「资质等级」。
_TITLE_BLOCK_ORG = re.compile(r"^\s*([一-龥（）()·]{2,40}?" + _ORG_SUFFIX + ")")
_ORG_SEAL = re.compile(r"[一-龥（）()·]{2,40}" + _ORG_SUFFIX + r"$")
_TITLE_BLOCK_MARKERS = ("资质等级", "GRADE OF QUALIFICATION", "设计阶段", "图名", "DWG", "建设单位", "图号")


def _title_block_texts(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    """首页里像图签的文本。字段优先，其次 table 片段。

    带上 fieldName / humanCorrected：图签来自某个抽取字段时，界面才能让人「核对无误」
    （人工确认要按字段名回查 ocr-fields）。片段没有字段名，确认不了，如实留空。
    """
    output: list[dict[str, Any]] = []
    for field in parse_result.get("fields") or []:
        if not isinstance(field, dict):
            continue
        value = str(field.get("fieldValue") or field.get("value") or "")
        if any(marker in value for marker in _TITLE_BLOCK_MARKERS):
            output.append({"text": value, "pageNo": field.get("pageNo"), "bbox": field.get("bbox"),
                           "fieldName": str(field.get("fieldName") or ""), "humanCorrected": field.get("humanCorrected") is True})
    for fragment in parse_result.get("fragments") or []:
        if not isinstance(fragment, dict) or int(fragment.get("pageNo") or 0) != 1:
            continue
        text = str(fragment.get("text") or "")
        if any(marker in text for marker in _TITLE_BLOCK_MARKERS):
            output.append({"text": text, "pageNo": fragment.get("pageNo"), "bbox": fragment.get("bbox"),
                           "fieldName": "", "humanCorrected": False})
    return output


def _human_confirmed_paths(state: dict[str, Any], review_run: dict[str, Any]) -> set[str]:
    """本节点已被人工核对过的事实路径。

    图签来自抽取字段，人工确认走 fieldId；设计章来自印章，没有字段可指，只能按 factPath 确认。
    两条路都要让证据变成「有分」，否则节点 1 永远停在「需人工判断」。
    """
    project_id = str(review_run.get("projectId") or "")
    node_id = review_run.get("nodeId")
    return {
        str(item.get("factPath") or "")
        for item in state.get("fact_corrections") or []
        if isinstance(item, dict)
        and item.get("status") == "active"
        and item.get("projectId") == project_id
        and str(item.get("nodeId")) == str(node_id)
        and item.get("factPath")
    }


def build_design_org_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    """返回 {"designDocument": {...}} 或空 dict（输入里没有设计文件时）。"""
    project_id = str(review_run.get("projectId") or "")
    documents = _documents_by_version(state, project_id)
    title_block: dict[str, Any] | None = None
    seal: dict[str, Any] | None = None
    for parse_result in selected_parse_results(state, {}, context={"reviewRun": review_run}):
        version_id = str(parse_result.get("documentVersionId") or "")
        document = documents.get(version_id)
        if not document or str(document.get("materialTypeCode") or "") != "design_document":
            continue
        file_name = str(document.get("fileName") or "")
        unavailable = _confidence_unavailable(parse_result)
        document_id = str(document.get("id") or "")
        if title_block is None:
            for candidate in _title_block_texts(parse_result):
                text = str(candidate["text"])
                match = _TITLE_BLOCK_ORG.match(text)
                if match:
                    title_block = {
                        "value": match.group(1),
                        "documentId": document_id,
                        "evidence": _evidence(version_id, file_name, candidate["pageNo"] or 1, candidate["bbox"], text[:200],
                                              confidence_unavailable=unavailable, field_name=candidate["fieldName"] or None,
                                              human_corrected=bool(candidate["humanCorrected"])),
                    }
                    break
        if seal is None:
            for item in parse_result.get("seals") or []:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or item.get("sealText") or item.get("name") or "").strip()
                if _ORG_SEAL.search(text):
                    seal = {
                        "value": text,
                        # 印章不是抽取字段，没有 fieldName——界面据此不给「核对无误」，因为无处回写。
                        "documentId": document_id,
                        "evidence": _evidence(version_id, file_name, item.get("pageNo") or 1, item.get("bbox"), text,
                                              confidence=item.get("confidence"), confidence_unavailable=unavailable),
                    }
                    break
        if title_block and seal:
            break
    if not title_block and not seal:
        return {}
    confirmed = _human_confirmed_paths(state, review_run)
    for key, item in (("titleBlockOrganization", title_block), ("designSealOrganization", seal)):
        if item and FACT_PATHS[key] in confirmed:
            item["evidence"].update({"humanCorrected": True, "confidence": 1.0, "confidenceUnavailable": False})
    facts: dict[str, Any] = {
        "titleBlockOrganization": (title_block or {}).get("value"),
        "designSealOrganization": (seal or {}).get("value"),
        "evidence": [item["evidence"] for item in (title_block, seal) if item],
        # 每处单位名配自己的那条证据与文件 id：两处名字常常一样，按引文包含去猜会互相串。
        "sources": {key: {"documentId": item["documentId"], "evidence": item["evidence"], "factPath": FACT_PATHS[key]}
                    for key, item in (("titleBlockOrganization", title_block), ("designSealOrganization", seal)) if item},
    }
    return {"designDocument": facts}
