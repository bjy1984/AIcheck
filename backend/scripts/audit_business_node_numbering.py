#!/usr/bin/env python3
"""Audit engineering business-node numbering against files/checklist.docx.

The checklist's first contiguous 1-69 inspection table is the sole identity
authority.  This audit deliberately checks both explicit IDs and duplicated
display-name artifacts so a renumbering cannot leave stale UI or seed data.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
PACK_DIR = BACKEND_ROOT / "business_packs" / "engineering_inspection_v1"
CHECKLIST = REPO_ROOT / "files" / "checklist.docx"
WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
INSPECTION_CLASSES = {"A", "B", "C", "C/B", "B/C", "□C □B"}


def compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def expected_rule_id(node_id: int) -> str:
    return f"R{node_id:02d}"


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def extract_checklist_nodes(path: Path = CHECKLIST) -> list[dict[str, Any]]:
    """Extract the first contiguous 1-69 inspection-node table from OOXML."""

    with ZipFile(path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))

    nodes: list[dict[str, Any]] = []
    current_group = ""
    started = False
    for table in document.findall(".//w:tbl", WORD_NS):
        for row in table.findall("./w:tr", WORD_NS):
            cells = [
                compact("".join(text.text or "" for text in cell.findall(".//w:t", WORD_NS)))
                for cell in row.findall("./w:tc", WORD_NS)
            ]
            if not cells or not cells[0].isdigit():
                continue
            node_id = int(cells[0])
            if not started:
                if node_id != 1 or "设计单位许可资质" not in cells:
                    continue
                started = True
            if node_id != len(nodes) + 1:
                continue

            second = cells[1] if len(cells) > 1 else ""
            third = cells[2] if len(cells) > 2 else ""
            if second:
                current_group = second
            name = third if third and third not in INSPECTION_CLASSES else second
            if not name:
                raise ValueError(f"checklist node {node_id} has no inspection item")
            nodes.append(
                {
                    "nodeId": node_id,
                    "sourceRuleId": expected_rule_id(node_id),
                    "groupName": current_group or name,
                    "name": name,
                }
            )
            if node_id == 69:
                return nodes
    raise ValueError(f"expected checklist nodes 1-69, extracted {len(nodes)}")


def add(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def audit_identity_rows(
    errors: list[str],
    label: str,
    rows: Iterable[dict[str, Any]],
    expected: dict[int, dict[str, Any]],
    *,
    node_key: str = "nodeId",
    name_key: str = "name",
    group_key: str | None = None,
    require_complete: bool = True,
) -> None:
    values = list(rows)
    ids: list[int] = []
    for row in values:
        try:
            node_id = int(row[node_key])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{label}: invalid {node_key}: {row.get(node_key)!r}")
            continue
        ids.append(node_id)
        if node_id not in expected:
            errors.append(f"{label}: node {node_id} is outside checklist 1-69")
            continue
        actual_name = compact(row.get(name_key))
        if actual_name != expected[node_id]["name"]:
            errors.append(
                f"{label}: R{node_id:02d} name mismatch: {actual_name!r} != {expected[node_id]['name']!r}"
            )
        if group_key and compact(row.get(group_key)) != expected[node_id]["groupName"]:
            errors.append(
                f"{label}: R{node_id:02d} group mismatch: {compact(row.get(group_key))!r} "
                f"!= {expected[node_id]['groupName']!r}"
            )
    duplicates = sorted(node_id for node_id, count in Counter(ids).items() if count > 1)
    if duplicates and require_complete:
        errors.append(f"{label}: duplicate node IDs: {duplicates}")
    if require_complete and set(ids) != set(expected):
        errors.append(f"{label}: coverage is not exactly node 1-69")


def markdown_rule_rows(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8")
    headings = [
        {"nodeId": int(match.group(1)), "name": match.group(2).strip()}
        for match in re.finditer(r"^### R(\d{2})｜(.+?)\s*$", text, re.MULTILINE)
    ]
    index_rows = []
    for line in text.splitlines():
        match = re.match(r"\| R(\d{2}) \| [^|]+ \| 序号(\d+) \| (.*?) \|", line)
        if match:
            index_rows.append(
                {
                    "nodeId": int(match.group(1)),
                    "sourceSequence": int(match.group(2)),
                    "name": match.group(3).strip(),
                }
            )
    return headings, index_rows


def markdown_rule_mapping_rows(path: Path) -> list[dict[str, Any]]:
    """Read the duplicated R01-R69 identities in section 8.5."""

    rows: list[dict[str, Any]] = []
    in_mapping = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "### 8.5 逐条规则映射":
            in_mapping = True
            continue
        if in_mapping and line.startswith("### "):
            break
        if not in_mapping:
            continue
        match = re.match(r"\| R(\d{2}) (.*?) \|", line)
        if match:
            rows.append({"nodeId": int(match.group(1)), "name": match.group(2).strip()})
    return rows


def parse_analysis_headings(path: Path) -> tuple[list[int], list[dict[str, Any]]]:
    """Read ordered top-level sections and single-node analysis headings."""

    section_numbers: list[int] = []
    node_rows: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    for match in re.finditer(r"^## (\d+)\. (.+?)\s*$", text, re.MULTILINE):
        section_numbers.append(int(match.group(1)))
        node_match = re.match(r"R(\d{2}) (.+)$", match.group(2))
        if node_match:
            node_rows.append(
                {"nodeId": int(node_match.group(1)), "name": node_match.group(2).strip()}
            )
    return section_numbers, node_rows


def parse_frontend_rules(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"export const generatedKnowledgeRuleVersions = (\[.*\])(?: as const)?\s*$",
        text,
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"cannot parse generated rules from {path}")
    return json.loads(match.group(1))


def parse_mapping_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 3."):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section:
            continue
        columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(columns) >= 5 and columns[0].isdigit() and re.fullmatch(r"R\d{2}", columns[1]):
            rows.append({"nodeId": int(columns[0]), "sourceRuleId": columns[1], "name": columns[3]})
    return rows


def parse_binding_plan_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 3. "):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section:
            continue
        columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(columns) >= 4 and re.fullmatch(r"R\d{2}", columns[0]) and columns[1].isdigit():
            rows.append(
                {
                    "nodeId": int(columns[1]),
                    "sourceRuleId": columns[0],
                    "name": columns[3],
                }
            )
    return rows


def parse_matrix_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| BATCH-"):
            continue
        columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
        identity = re.fullmatch(r"R(\d{2}) / (\d+)", columns[1])
        if identity:
            rows.append({"nodeId": int(identity.group(2)), "sourceRuleId": f"R{identity.group(1)}", "name": columns[2]})
    return rows


def parse_migration_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\| R(\d{2}) \| (?:R\d{2}|-|—) \| (\d+) \| (.*?) \|", line)
        if match:
            rows.append({"nodeId": int(match.group(2)), "sourceRuleId": f"R{match.group(1)}", "name": match.group(3).strip()})
    return rows


def audit() -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    checklist = extract_checklist_nodes()
    expected = {item["nodeId"]: item for item in checklist}
    expected_rule_ids = {item["sourceRuleId"] for item in checklist}

    nodes = load_yaml(PACK_DIR / "nodes.yaml").get("nodeTemplates") or []
    rules = load_yaml(PACK_DIR / "rules.yaml").get("ruleSets") or []
    bindings = load_yaml(PACK_DIR / "standard_clause_bindings.yaml").get("standardClauseBindings") or []
    packages = load_yaml(PACK_DIR / "standard_clause_packages.yaml").get("standardClausePackages") or []
    checks = load_yaml(PACK_DIR / "atomic_checks.yaml").get("atomicChecks") or []
    tool_bindings = load_yaml(PACK_DIR / "atomic_check_tool_bindings.yaml").get("atomicCheckToolBindings") or []

    audit_identity_rows(errors, "nodes.yaml", nodes, expected, group_key="groupName")
    audit_identity_rows(errors, "rules.yaml", rules, expected, node_key="sourceSequence")
    audit_identity_rows(errors, "standard_clause_packages.yaml", packages, expected, name_key="nodeName")

    for row in nodes:
        node_id = int(row["nodeId"])
        add(errors, row.get("code") == f"{node_id:02d}", f"nodes.yaml: node {node_id} code mismatch")
    for row in rules:
        node_id = int(row["sourceSequence"])
        source_rule = expected_rule_id(node_id)
        add(errors, row.get("sourceRuleId") == source_rule, f"rules.yaml: node {node_id} sourceRuleId mismatch")
        add(errors, row.get("id") == f"RULE-ENG-INSP-{source_rule}", f"rules.yaml: {source_rule} rule id mismatch")
        add(errors, row.get("nodeIds") == [node_id], f"rules.yaml: {source_rule} nodeIds mismatch")
        add(errors, compact(row.get("inspectionItem")) == expected[node_id]["name"], f"rules.yaml: {source_rule} inspectionItem mismatch")

    for label, rows in (("standard bindings", bindings), ("clause packages", packages), ("atomic checks", checks)):
        for row in rows:
            source_rule = str(row.get("sourceRuleId") or "")
            add(errors, source_rule in expected_rule_ids, f"{label}: unknown sourceRuleId {source_rule!r}")
            if source_rule in expected_rule_ids:
                node_id = int(source_rule[1:])
                add(errors, int(row.get("nodeId") or 0) == node_id, f"{label}: {source_rule} nodeId mismatch")
                add(errors, row.get("ruleId") == f"RULE-ENG-INSP-{source_rule}", f"{label}: {source_rule} ruleId mismatch")

    check_by_id = {row.get("id"): row for row in checks}
    add(errors, len(check_by_id) == len(checks), "atomic checks: duplicate IDs")
    for row in checks:
        source_rule = row["sourceRuleId"]
        add(errors, str(row["id"]).startswith(f"AC-{source_rule}-"), f"atomic checks: {row['id']} prefix mismatch")
        add(errors, compact(row.get("name")).startswith(expected[int(source_rule[1:])]["name"] + "·"), f"atomic checks: {row['id']} name mismatch")
    tool_ids = [row.get("atomicCheckId") for row in tool_bindings]
    add(errors, len(tool_ids) == len(set(tool_ids)), "tool bindings: duplicate atomicCheckId")
    add(errors, set(tool_ids) == set(check_by_id), "tool bindings: coverage does not equal atomic checks")
    for row in tool_bindings:
        check = check_by_id.get(row.get("atomicCheckId"))
        if check:
            add(errors, row.get("sourceRuleId") == check.get("sourceRuleId"), f"tool bindings: {row.get('atomicCheckId')} sourceRuleId mismatch")

    for path in (REPO_ROOT / "rules" / "业务规则.md", REPO_ROOT / "业务规则.md"):
        label = str(path.relative_to(REPO_ROOT))
        headings, index_rows = markdown_rule_rows(path)
        mapping_rows = markdown_rule_mapping_rows(path)
        audit_identity_rows(errors, f"{label} headings", headings, expected)
        audit_identity_rows(errors, f"{label} index", index_rows, expected)
        audit_identity_rows(errors, f"{label} rule mapping", mapping_rows, expected)
        for row in index_rows:
            add(errors, row["nodeId"] == row["sourceSequence"], f"{label}: R{row['nodeId']:02d} sequence mismatch")
    add(
        errors,
        (REPO_ROOT / "rules" / "业务规则.md").read_bytes() == (REPO_ROOT / "业务规则.md").read_bytes(),
        "root 业务规则.md is not identical to rules/业务规则.md",
    )

    frontend_rules = parse_frontend_rules(REPO_ROOT / "frontend" / "mock" / "aicheck" / "generatedBusinessRules.ts")
    audit_identity_rows(errors, "generatedBusinessRules.ts", frontend_rules, expected, node_key="sourceSequence")
    for row in frontend_rules:
        node_id = int(row["sourceSequence"])
        add(errors, row.get("sourceRuleId") == expected_rule_id(node_id), f"generatedBusinessRules.ts: node {node_id} sourceRuleId mismatch")
        add(errors, row.get("nodeIds") == [node_id], f"generatedBusinessRules.ts: node {node_id} nodeIds mismatch")

    seed_text = (REPO_ROOT / "frontend" / "mock" / "aicheck" / "seed.ts").read_text(encoding="utf-8")
    seed_rows = [
        {"nodeId": int(node_id), "name": name}
        for node_id, name in re.findall(r"\[(\d+), '([^']+)', '(?:A|B|C|C/B|需确认)'\]", seed_text)
    ]
    audit_identity_rows(errors, "frontend seed groupDefinitions", seed_rows, expected)

    static_tree_text = (REPO_ROOT / "ui" / "workbench_project_tree.js").read_text(encoding="utf-8")
    static_tree_rows = [
        {"nodeId": int(node_id), "name": name}
        for node_id, name in re.findall(r'\[(\d+), "([^"]+)", "(?:A|B|C|C/B|需确认)"\]', static_tree_text)
    ]
    audit_identity_rows(errors, "ui/workbench_project_tree.js", static_tree_rows, expected)

    ui_design_rows = []
    in_ui_node_table = False
    for line in (REPO_ROOT / "uidesign.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("### 2.3 "):
            in_ui_node_table = True
            continue
        if in_ui_node_table and line.startswith("### "):
            break
        if not in_ui_node_table:
            continue
        columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(columns) == 4 and columns[0].isdigit():
            ui_design_rows.append(
                {"nodeId": int(columns[0]), "groupName": columns[1], "name": columns[2]}
            )
    audit_identity_rows(errors, "uidesign.md", ui_design_rows, expected, group_key="groupName")

    analysis_section_numbers, analysis_rows = parse_analysis_headings(REPO_ROOT / "业务节点分析.md")
    audit_identity_rows(errors, "业务节点分析.md", analysis_rows, expected)
    add(
        errors,
        [row["nodeId"] for row in analysis_rows] == list(range(1, 70)),
        "业务节点分析.md: node sections must appear in R01-R69 order",
    )
    add(
        errors,
        analysis_section_numbers == list(range(1, len(analysis_section_numbers) + 1)),
        "业务节点分析.md: top-level section numbers must be contiguous",
    )

    frontend_top_level_blocks = re.findall(
        r"^  \{\n(.*?)^  \}(?:,)?$", seed_text, re.MULTILINE | re.DOTALL
    )
    archived_current_nodes = []
    archived_report_nodes = []
    for block in frontend_top_level_blocks:
        if "status: '已归档'" not in block:
            continue
        current_match = re.search(r"currentNodeId: (\d+)", block)
        if current_match:
            archived_current_nodes.append(int(current_match.group(1)))
        if "type: 'report'" in block:
            node_match = re.search(r"nodeId: (\d+)", block)
            if node_match:
                archived_report_nodes.append(int(node_match.group(1)))
    add(
        errors,
        bool(archived_current_nodes) and set(archived_current_nodes) == {69},
        "frontend seed: archived projects must end at manual evaluation node 69",
    )
    add(
        errors,
        bool(archived_report_nodes) and set(archived_report_nodes) == {69},
        "frontend seed: archived project reports must bind to node 69",
    )

    backend_seed_text = (BACKEND_ROOT / "libs" / "db" / "seed.py").read_text(encoding="utf-8")
    backend_archived_nodes = [
        int(node_id)
        for node_id in re.findall(
            r'"status": "已归档",.*?"currentNodeId": (\d+)', backend_seed_text, re.DOTALL
        )
    ]
    add(
        errors,
        bool(backend_archived_nodes) and set(backend_archived_nodes) == {69},
        "backend seed: archived projects must end at manual evaluation node 69",
    )

    material_payload = json.loads((BACKEND_ROOT / "config" / "material_review_points.json").read_text(encoding="utf-8"))
    material_rows = material_payload.get("items") or []
    audit_identity_rows(errors, "material_review_points.json", material_rows, expected, name_key="nodeName", require_complete=False)
    add(errors, {int(row["nodeId"]) for row in material_rows} == set(expected) - {69}, "material_review_points.json: expected coverage R01-R68 only")
    for row in material_rows:
        node_id = int(row["nodeId"])
        add(errors, row.get("ruleId") == expected_rule_id(node_id), f"material_review_points.json: node {node_id} ruleId mismatch")

    mapping_rows = parse_mapping_rows(REPO_ROOT / "docs" / "工程监检资料映射表.md")
    audit_identity_rows(errors, "工程监检资料映射表.md", mapping_rows, expected, require_complete=False)
    add(errors, {row["nodeId"] for row in mapping_rows} == set(expected), "工程监检资料映射表.md: node coverage is not 1-69")
    for row in mapping_rows:
        add(errors, row["sourceRuleId"] == expected_rule_id(row["nodeId"]), f"工程监检资料映射表.md: node {row['nodeId']} rule mismatch")

    binding_plan_rows = parse_binding_plan_rows(
        REPO_ROOT / "docs" / "业务节点与固定标准条款绑定方案.md"
    )
    audit_identity_rows(errors, "业务节点与固定标准条款绑定方案.md", binding_plan_rows, expected)
    for row in binding_plan_rows:
        add(
            errors,
            row["sourceRuleId"] == expected_rule_id(row["nodeId"]),
            f"业务节点与固定标准条款绑定方案.md: node {row['nodeId']} rule mismatch",
        )

    matrix_rows = parse_matrix_rows(REPO_ROOT / "docs" / "业务节点具体标准条款审核矩阵.md")
    audit_identity_rows(errors, "业务节点具体标准条款审核矩阵.md", matrix_rows, expected)
    migration_rows = parse_migration_rows(REPO_ROOT / "docs" / "业务规则编号迁移表.md")
    audit_identity_rows(errors, "业务规则编号迁移表.md", migration_rows, expected)

    fixture = load_yaml(PACK_DIR / "fixtures.yaml").get("fixtures") or {}
    fixture_binding_nodes = {row.get("id"): int(row.get("nodeId")) for row in fixture.get("bindings") or []}
    add(errors, fixture_binding_nodes.get("BIND-24-001") == 24, "fixtures.yaml: welder binding must use node 24")
    add(errors, fixture_binding_nodes.get("BIND-16-001") == 16, "fixtures.yaml: quality-certificate binding must use node 16")

    r69_rule = next((row for row in rules if row.get("sourceRuleId") == "R69"), {})
    r69_package = next((row for row in packages if row.get("sourceRuleId") == "R69"), {})
    add(errors, r69_rule.get("executionMode") == "manual_evaluation", "R69 must use manual_evaluation")
    add(errors, r69_rule.get("automatedDecisionAllowed") is False, "R69 rule must prohibit automated decisions")
    add(errors, (r69_package.get("decisionModel") or {}).get("automatedDecisionAllowed") is False, "R69 package must prohibit automated decisions")

    stats = {
        "checklist_nodes": len(checklist),
        "pack_nodes": len(nodes),
        "rules": len(rules),
        "standard_bindings": len(bindings),
        "clause_packages": len(packages),
        "atomic_checks": len(checks),
        "tool_bindings": len(tool_bindings),
        "material_review_points": len(material_rows),
        "errors": len(errors),
    }
    return errors, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print a machine-readable result.")
    args = parser.parse_args()
    errors, stats = audit()
    if args.json:
        print(json.dumps({"ok": not errors, "stats": stats, "errors": errors}, ensure_ascii=False, indent=2))
    else:
        print("PASS" if not errors else "FAIL", stats)
        for error in errors:
            print("ERROR", error)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
