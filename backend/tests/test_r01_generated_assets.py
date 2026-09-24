"""R01's new business version must not trigger unrelated atomic-check regeneration."""

from __future__ import annotations

from pathlib import Path

import yaml

from libs.business_rule_generation import build_rule_sets, list_standard_files
from scripts.generate_atomic_check_tool_plan import make_binding
from scripts.generate_standard_clause_artifacts import clean_checks
from scripts.regenerate_business_rules import load_node_names, replace_single_rule_yaml

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "backend/business_packs/engineering_inspection_v1"


def test_r01_scoped_regeneration_and_all_five_atomic_bindings_match_source():
    markdown = (ROOT / "rules/业务规则.md").read_text(encoding="utf-8")
    assert markdown == (ROOT / "业务规则.md").read_text(encoding="utf-8")
    rules_text = (PACK / "rules.yaml").read_text(encoding="utf-8")
    rules = yaml.safe_load(rules_text)["ruleSets"]
    generated = build_rule_sets(
        markdown,
        standard_files=list_standard_files(ROOT / "rules/standards", workspace_root=ROOT),
        existing_rules_by_source={item["sourceRuleId"]: item for item in rules},
        node_name_by_id=load_node_names(PACK / "nodes.yaml"),
        import_version="v20260714",
    )
    r01 = next(item for item in generated if item["sourceRuleId"] == "R01")
    assert replace_single_rule_yaml(rules_text, r01) == rules_text

    atomic_payload = yaml.safe_load((PACK / "atomic_checks.yaml").read_text(encoding="utf-8"))
    checks = [item for item in atomic_payload["atomicChecks"] if item["sourceRuleId"] == "R01"]
    assert len(checks) == 5
    assert [item["instruction"] for item in checks] == clean_checks(r01)
    binding_payload = yaml.safe_load((PACK / "atomic_check_tool_bindings.yaml").read_text(encoding="utf-8"))
    bindings = {item["atomicCheckId"]: item for item in binding_payload["atomicCheckToolBindings"]}
    assert binding_payload["atomicCheckToolBindingSet"]["atomicCheckCount"] == len(bindings) == 194
    for item in checks:
        assert bindings[item["id"]] == make_binding(item)


def test_r01_pack_asset_versions_move_together():
    expected = "2026.09.23"
    assert yaml.safe_load((PACK / "manifest.yaml").read_text(encoding="utf-8"))["version"] == expected
    for filename, key in (
        ("atomic_checks.yaml", "atomicCheckSet"),
        ("atomic_check_tool_bindings.yaml", "atomicCheckToolBindingSet"),
        ("standard_clause_catalog.yaml", "standardCatalogSet"),
        ("standard_clause_bindings.yaml", "standardClauseBindingSet"),
        ("standard_clause_packages.yaml", "standardClausePackageSet"),
    ):
        payload = yaml.safe_load((PACK / filename).read_text(encoding="utf-8"))
        assert payload[key]["version"] == expected
