"""Versioned, server-owned skill and document recommendations for important-node review."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "important-node-review"
NODE_IDS = (4, 5, 6, 7, 8, 9, 12, 13, 16, 24, 25, 26)
NODE_LABELS = {
    4: "设计文件批准程序", 5: "施工图审查手续", 6: "强度与应力计算书审批",
    7: "设计变更批准", 8: "规范及标准版本", 9: "无损检测、防腐及试验要求",
    12: "制造单位许可资质", 13: "制造监检证书与型式试验", 16: "产品质量证明文件",
    24: "焊工资格及作业覆盖", 25: "焊接工艺文件", 26: "焊材质量证明文件",
}
# Recommendations are evidence discovery hints, never completeness or applicability verdicts.
HINTS = {
    4: ("设计", "图纸", "管道特性", "管线", "计算书"),
    5: ("审查合格", "审查意见", "备案", "设计变更", "施工图"),
    6: ("计算书", "应力", "强度计算", "管道特性"),
    7: ("变更", "澄清", "材料代用"),
    8: ("设计", "标准", "材料", "工艺", "检测方案"),
    9: ("设计", "管道特性", "检测", "试验", "防腐"),
    12: ("制造许可", "制造单位", "生产许可"),
    13: ("制造监检", "监督检验", "型式试验"),
    16: ("质量证明", "质保书", "材质", "材料表", "PMI"),
    24: ("焊工", "施焊", "焊口", "工艺卡", "WPS"),
    25: ("WPS", "PQR", "焊接工艺", "工艺评定", "施焊", "管道特性", "焊口"),
    26: ("焊材", "焊接材料", "焊条", "焊丝", "焊剂", "WPS", "领用", "烘干"),
}


def skill_catalog():
    text = (SKILL_ROOT / "references/business-nodes-v3.md").read_text(encoding="utf-8")
    instructions = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[2].strip()
    version = hashlib.sha256((instructions + text).encode()).hexdigest()
    nodes = []
    for match in re.finditer(r"^## R(\d+)｜([^\n]+)\n(.*?)(?=^## R|\Z)", text, re.MULTILINE | re.DOTALL):
        node_id = int(match[1])
        if node_id not in NODE_IDS:
            continue
        sections = []
        for section in re.finditer(r"\*\*([^*]+)\*\*\s*\n(.*?)(?=\n\*\*|\Z)", match[3], re.DOTALL):
            sections.append({"title": section[1].replace("（原文）", ""), "text": section[2].strip().removesuffix("---").strip()})
        nodes.append({"nodeId": node_id, "code": f"R{node_id:02d}", "name": match[2].strip(),
                      "displayName": NODE_LABELS[node_id],
                      "group": "设计文件" if node_id < 10 else "元件与材料" if node_id < 20 else "焊接",
                      "sections": sections, "content": match[3].strip(), "source": "业务节点描述 v3",
                      "version": version, "skillId": "important-node-review", "instructions": instructions})
    return nodes


def skill_for_node(node_id):
    return next((node for node in skill_catalog() if node["nodeId"] == node_id), None)


def recommend_nodes(catalog, documents, parses, bindings):
    results = []
    for node in catalog:
        matched = []
        for document in documents:
            version = document["currentVersionId"]
            parsed = [row for row in parses if row.get("documentVersionId") == version]
            text = (str(document.get("fileName", "")) + " " + str(document.get("materialTypeName", ""))
                    + " " + json.dumps(parsed, ensure_ascii=False)).upper()
            hits = [word for word in HINTS[node["nodeId"]] if word.upper() in text]
            bound = any(row.get("documentId") == document["id"] and row.get("nodeId") == node["nodeId"] for row in bindings)
            if hits or bound:
                matched.append({"documentId": document["id"], "versionId": version,
                                "fileName": document["fileName"],
                                "reason": "内容或名称包含：" + "、".join(hits) if hits else "已有节点关联（供参考）"})
        results.append({"nodeId": node["nodeId"], "documents": matched, "recommended": bool(matched),
                        "message": "已找到候选资料，完整性需审查确认" if matched else "适用性待确认，可手动选择"})
    return results
