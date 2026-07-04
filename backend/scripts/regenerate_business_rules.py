from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from libs.business_rule_generation import (  # noqa: E402
    STANDARD_VERSION,
    build_rule_sets,
    list_standard_files,
    render_standard_match_section,
    replace_generated_standard_section,
)


BLOCK_LITERAL_KEYS = {
    "criteria",
    "standardText",
    "checkMethod",
    "witnessText",
    "agentThinking",
    "toolchainThinking",
    "sourceWitness",
    "promptContext",
    "text",
}


class LiteralString(str):
    pass


def literal_representer(dumper: yaml.SafeDumper, data: LiteralString):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.SafeDumper.add_representer(LiteralString, literal_representer)


def use_literal_strings(value: Any, *, parent_key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {key: use_literal_strings(item, parent_key=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [use_literal_strings(item, parent_key=parent_key) for item in value]
    if isinstance(value, str) and ("\n" in value or parent_key in BLOCK_LITERAL_KEYS):
        return LiteralString(value)
    return value


def load_existing_rules(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = payload.get("ruleSets") or []
    return {
        str(rule.get("sourceRuleId")): rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("sourceRuleId")
    }


def load_node_names(path: Path) -> dict[int, str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    templates = payload.get("nodeTemplates") or []
    names: dict[int, str] = {}
    for item in templates:
        if not isinstance(item, dict):
            continue
        try:
            node_id = int(item.get("nodeId"))
        except (TypeError, ValueError):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names[node_id] = name
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate business-pack rules.yaml from rules/业务规则.md.")
    parser.add_argument("--check", action="store_true", help="Only print generation summary without writing files.")
    args = parser.parse_args()

    rules_md_path = WORKSPACE_ROOT / "rules" / "业务规则.md"
    root_rules_md_path = WORKSPACE_ROOT / "业务规则.md"
    standards_root = WORKSPACE_ROOT / "rules" / "standards"
    pack_root = WORKSPACE_ROOT / "backend" / "business_packs" / "engineering_inspection_v1"
    rules_yaml_path = pack_root / "rules.yaml"
    nodes_yaml_path = pack_root / "nodes.yaml"

    markdown_text = rules_md_path.read_text(encoding="utf-8")
    standard_files = list_standard_files(standards_root, workspace_root=WORKSPACE_ROOT)
    existing_rules = load_existing_rules(rules_yaml_path)
    rule_sets = build_rule_sets(
        markdown_text,
        standard_files=standard_files,
        existing_rules_by_source=existing_rules,
        node_name_by_id=load_node_names(nodes_yaml_path),
        import_version=STANDARD_VERSION.replace("rules-standards-", "v"),
    )
    section = render_standard_match_section(standard_files, rule_sets)
    updated_markdown = replace_generated_standard_section(markdown_text, section)

    yaml_payload = {
        "ruleSets": rule_sets,
    }
    yaml_text = "# Generated from /rules/业务规则.md. Keep sourceRuleId for traceability; nodeIds bind runtime nodes.\n"
    yaml_text += yaml.safe_dump(
        use_literal_strings(yaml_payload),
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )

    matched_files = {
        match.get("file")
        for rule in rule_sets
        for match in rule.get("referencedStandards") or []
        if match.get("file")
    }
    print(
        "regenerated rules:",
        len(rule_sets),
        "standard files:",
        len(standard_files),
        "matched files:",
        len(matched_files),
    )
    if args.check:
        return

    rules_yaml_path.write_text(yaml_text, encoding="utf-8")
    rules_md_path.write_text(updated_markdown, encoding="utf-8")
    root_rules_md_path.write_text(updated_markdown, encoding="utf-8")


if __name__ == "__main__":
    main()
