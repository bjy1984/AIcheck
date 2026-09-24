"""Blind, double inspector packet for every fact the rules extract from the approved snapshot.

Every extracted fact the Jev fact check would ask about (certificates, design test
requirements, welders, material/component and welding records) becomes one row.
Inspectors see the document, page, field and extracted value, plus where the value
was found locally, and answer whether that is what the document states for that
certificate or record. They never see a Jev answer or any system flag: those go
to a separate key file that is only opened for scoring. Two identical sheets (A
and B) are for two inspectors working independently. The packet holds real
project data and is written 0600 into a private directory outside the repository.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from libs.review_orchestrator.design_facts import DESIGN_FACT_NODES, build_design_business_facts
from libs.review_orchestrator.fact_builders import NODE_FACT_BUILDERS
from libs.review_orchestrator.jev_fact_check import (
    certificate_fact_items,
    design_fact_items,
    locate_value,
    record_fact_items,
    welder_fact_items,
)
from scripts.evaluate_jev_fact_check_real import certificates, load_snapshot

SCHEMA_VERSION = "jev-fact-labels-v1"
VERDICTS = ("正确", "错误", "原文没有", "看不清")
COLUMNS = ("条目编号", "项目", "节点", "文件名", "页码", "核对对象", "栏目", "系统抽取值",
           "原文定位（仅供查找，不代表正确）", "判定（正确/错误/原文没有/看不清）", "正确值（判定为错误时填写）", "备注")
# Fixed placeholders so the item builders accept facts without a real rule run.
_RULES = [{"atomicCheckResults": [{"atomicCheckId": "LABEL", "toolResults": [
    {"toolName": "evaluate_design_special_requirements"}, {"toolName": "extract_welder_certificate"}]}]}]
_FIELD_NAMES = {
    "validUntil": "有效期截止日", "validFrom": "有效期起始日", "certificateNo": "证书编号", "holder": "持证单位或持证人",
    "qualificationCode": "合格项目", "reportNo": "报告编号", "manufacturerName": "制造单位", "productName": "产品名称",
    "material": "材质", "wpsNo": "WPS 编号", "pqrNo": "PQR 编号", "materialGrade": "母材牌号", "fillerMetal": "焊接材料",
    "conclusion": "检验结论",
}
GUIDE = """# Jev 事实核对 · 监检员盲标说明

每一行是规则从资料里抽出的一个事实。请打开对应文件，翻到页码，核对「系统抽取值」是不是这份资料里
**这张证书／这条记录的这一栏**写明的内容。

- **正确**：原文这一栏写的就是这个值（写法不同但意思相同也算，例如 2028-09-06 与 2028年9月6日）。
- **错误**：原文这一栏有值，但不是这个；或者这个值属于别的证书、别的人、别的记录，或是表头、栏目名。请在「正确值」写出原文的值。
- **原文没有**：这份资料里根本没有写这一栏。
- **看不清**：扫描模糊、被遮挡，无法判断。

规则：
1. 两位监检员分别填 A、B 两份，**互不交流、互不查看**，填完再交。
2. 只看原文，不参考系统的其他结论。表里没有、也不会给出模型的答案。
3. 「原文定位」只是帮忙找位置，它引的那段不一定就是正确的那一栏。
4. 「核对对象」写的是这一行说的是哪张证或哪条记录；对象不对，也判「错误」。
5. 判定只能填上面四个词之一；其他情况写在「备注」。
"""


def _item_id(item: dict[str, Any]) -> str:
    raw = json.dumps([item["documentVersionIds"], item["field"], item["value"], item["instructions"]],
                     ensure_ascii=False, sort_keys=True)
    return "F-" + hashlib.sha256(raw.encode()).hexdigest()[:10].upper()


def _subject(item: dict[str, Any]) -> str:
    """The certificate or record the question is about, in the words of the question."""
    text = item["instructions"]
    if text.startswith("只看这份资料："):
        # 记录类：「只看这份资料：不锈钢工业弯头的证书编号是否写为…」→「不锈钢工业弯头」。
        target = text.removeprefix("只看这份资料：").split("是否写为", 1)[0]
        return target.rsplit("的", 1)[0] if "的" in target else "（表格中的一条记录，请按原文定位查找）"
    if text.startswith("只看") and "：" in text:
        return text[2: text.index("：")]
    return item.get("certificateLabel") or ""


def collect(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Every fact the fact check would ask about, tagged with project and node."""
    items: list[dict[str, Any]] = []
    for row in certificates(snapshot):
        cert = {**row["cert"], "evidenceRefs": [{"documentVersionId": row["version"]}]}
        for item in certificate_fact_items({"certificateType": cert.get("certificateType"), "certificates": [cert]}):
            items.append({**item, "projectId": row["projectId"], "tenantId": row["tenantId"], "nodeId": row["nodeId"]})
    for project in snapshot["projects"]:
        tenant = project.get("tenantId") or "TENANT-DEFAULT"
        for node in sorted({*DESIGN_FACT_NODES, *NODE_FACT_BUILDERS}):
            versions = sorted({str(link["documentVersionId"]) for link in snapshot.get("node_evidence_links") or []
                               if link.get("projectId") == project["id"] and int(link.get("nodeId") or 0) == node
                               and link.get("documentVersionId")})
            if not versions:
                continue
            run = {"projectId": project["id"], "tenantId": tenant, "nodeId": node, "reviewMode": "formal",
                   "inputDocumentVersionIds": versions, "reviewRunId": "LABELS"}
            try:
                facts = (build_design_business_facts(snapshot, run) if node in DESIGN_FACT_NODES
                         else NODE_FACT_BUILDERS[node](snapshot, run))
            except ValueError:
                continue
            found = (design_fact_items(facts, _RULES) + welder_fact_items(facts, _RULES)
                     + record_fact_items(facts, _RULES))
            items.extend({**item, "projectId": project["id"], "tenantId": tenant, "nodeId": node} for item in found)
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        unique.setdefault(_item_id(item), {**item, "id": _item_id(item)})
    # Order by id, which is a hash: inspectors see no grouping by node or by any system flag.
    return [unique[key] for key in sorted(unique)]


def packet_rows(snapshot: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, str]]:
    files = {str(document.get("id")): str(document.get("fileName") or "") for document in snapshot.get("documents") or []}
    versions = {str(version.get("id")): str(version.get("documentId")) for version in
                snapshot.get("versions") or snapshot.get("document_versions") or []}
    rows = []
    for item in items:
        version = item["documentVersionIds"][0]
        located = locate_value(snapshot, {"projectId": item["projectId"], "tenantId": item["tenantId"]},
                               item["documentVersionIds"], item["field"], item["value"]) or {}
        rows.append({
            "条目编号": item["id"], "项目": item["projectId"], "节点": str(item["nodeId"]),
            "文件名": files.get(versions.get(version, ""), version), "页码": str(located.get("pageNo") or ""),
            "核对对象": _subject(item), "栏目": _FIELD_NAMES.get(item["field"].split(".")[-1], item["field"]),
            "系统抽取值": item["value"], "原文定位（仅供查找，不代表正确）": located.get("quote") or "（原文中没有找到这个值）",
            "判定（正确/错误/原文没有/看不清）": "", "正确值（判定为错误时填写）": "", "备注": "",
        })
    return rows


def _private_open(path: Path, mode: str = "w"):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, mode, encoding="utf-8-sig" if path.suffix == ".csv" else "utf-8", newline="")


def write_packet(output_dir: Path, snapshot_path: Path, snapshot: dict[str, Any],
                 items: list[dict[str, Any]]) -> dict[str, Any]:
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    rows = packet_rows(snapshot, items)
    for sheet in ("A", "B"):
        with _private_open(output_dir / f"fact_labels_{sheet}.csv") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
    with _private_open(output_dir / "README.md") as handle:
        handle.write(GUIDE)
    key = {"schemaVersion": SCHEMA_VERSION, "snapshot": str(snapshot_path),
           "snapshotSha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
           "items": [{key: item.get(key) for key in ("id", "projectId", "tenantId", "nodeId", "documentVersionIds",
                                                     "field", "value", "instructions", "plausible", "certificateLabel",
                                                     "suspectLabel")}
                     for item in items]}
    with _private_open(output_dir / "fact_labels_key.json") as handle:
        json.dump(key, handle, ensure_ascii=False, indent=2)
    families: dict[str, int] = {}
    for item in items:
        family = item["field"].split(".")[0]
        families[family] = families.get(family, 0) + 1
    return {"items": len(items), "documents": len({tuple(item["documentVersionIds"]) for item in items}),
            "projects": len({item["projectId"] for item in items}), "fields": families}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    os.environ["AICHECK_CERT_PLATFORM_VERIFY"] = "off"
    snapshot = load_snapshot(args.snapshot)
    summary = write_packet(args.output_dir, args.snapshot, snapshot, collect(snapshot))
    print(json.dumps({"status": "written", "outputDir": str(args.output_dir), **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
