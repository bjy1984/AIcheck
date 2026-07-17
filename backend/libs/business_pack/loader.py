from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_BUSINESS_PACK_ID = "engineering_inspection_v1"

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BUSINESS_PACK_ROOT = BACKEND_ROOT / "business_packs"
PACK_FILES = (
    "manifest.yaml",
    "roles.yaml",
    "nodes.yaml",
    "materials.yaml",
    "workflow.yaml",
    "rules.yaml",
    "standard_clause_catalog.yaml",
    "standard_clause_bindings.yaml",
    "atomic_checks.yaml",
    "atomic_check_tool_bindings.yaml",
    "standard_clause_packages.yaml",
    "reports.yaml",
    "agents.yaml",
    "fixtures.yaml",
)

REQUIRED_TOP_LEVEL = {
    "id",
    "name",
    "version",
    "domainType",
    "roles",
    "nodeTemplates",
    "materialTypes",
    "workflowStateMachines",
    "ruleSets",
    "reportTemplates",
}

ROLE_KEYS = {"code", "label", "platformRole", "defaultPath", "actions"}
NODE_KEYS = {"nodeId", "code", "name", "groupName", "inspectionType", "defaultStatus"}
MATERIAL_KEYS = {"code", "name", "requiredType"}
WORKFLOW_KEYS = {"id", "name", "states", "transitions"}
RULE_KEYS = {"id", "name", "ruleKey", "version", "status", "nodeIds"}
STANDARD_CLAUSE_BINDING_KEYS = {
    "bindingId",
    "ruleId",
    "sourceRuleId",
    "nodeId",
    "standardRef",
    "clauseNo",
    "bindingRole",
    "lifecycleStatus",
    "verificationStatus",
    "knowledgeFileId",
    "documentVersionId",
    "sourcePage",
    "startPage",
    "endPage",
    "sourceLocatorId",
    "locatorPrecision",
    "locators",
}
ATOMIC_CHECK_KEYS = {
    "id",
    "sourceRuleId",
    "ruleId",
    "nodeId",
    "name",
    "checkType",
    "instruction",
    "evidenceRequired",
    "failurePolicy",
}
ATOMIC_CHECK_TOOL_BINDING_KEYS = {
    "atomicCheckId",
    "sourceRuleId",
    "requiredFacts",
    "tools",
    "parameters",
    "outputSchema",
    "implementationStatus",
}
STANDARD_CLAUSE_PACKAGE_KEYS = {
    "packageId",
    "batchId",
    "sourceRuleId",
    "ruleId",
    "nodeId",
    "nodeName",
    "lifecycleStatus",
    "primaryBindingId",
    "applicability",
    "professionalClauses",
    "atomicCheckIds",
    "decisionModel",
}
REPORT_KEYS = {"id", "name", "version", "sections"}
FIXTURE_COLLECTION_KEYS = (
    "projects",
    "documents",
    "bindings",
    "evidenceLinks",
    "extractedFields",
    "aiRuns",
    "reviewFindings",
    "projectMembers",
    "todos",
    "messages",
    "knowledgeSources",
    "knowledgeTasks",
)


class BusinessPackError(ValueError):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        content = yaml.safe_load(handle) or {}
    if not isinstance(content, dict):
        raise BusinessPackError(f"{path} must contain a mapping.")
    return content


@lru_cache(maxsize=32)
def load_business_pack(pack_id: str = DEFAULT_BUSINESS_PACK_ID) -> dict[str, Any]:
    pack_dir = BUSINESS_PACK_ROOT / pack_id
    if not pack_dir.is_dir():
        raise BusinessPackError(f"Business pack not found: {pack_id}")

    pack: dict[str, Any] = {}
    for file_name in PACK_FILES:
        path = pack_dir / file_name
        if path.exists():
            pack.update(_read_yaml(path))
    validation = validate_business_pack(pack)
    if not validation["ok"]:
        raise BusinessPackError("; ".join(validation["errors"]))
    pack["snapshotHash"] = snapshot_hash(pack)
    return pack


def default_business_pack() -> dict[str, Any]:
    return load_business_pack(DEFAULT_BUSINESS_PACK_ID)


def list_business_packs() -> list[dict[str, Any]]:
    packs = []
    if not BUSINESS_PACK_ROOT.exists():
        return packs
    for path in sorted(item for item in BUSINESS_PACK_ROOT.iterdir() if item.is_dir()):
        pack = load_business_pack(path.name)
        packs.append(business_pack_summary(pack))
    return packs


def business_pack_summary(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pack["id"],
        "name": pack["name"],
        "version": pack["version"],
        "domainType": pack["domainType"],
        "description": pack.get("description", ""),
        "pipelineTypeCode": pack.get("pipelineTypeCode", ""),
        "pipelineTypeName": pack.get("pipelineTypeName") or pack["name"],
        "commonGrades": pack.get("commonGrades", ""),
        "scopeDescription": pack.get("scopeDescription", ""),
        "projectType": pack.get("projectType") or pack["name"],
        "status": pack.get("status", "published"),
        "snapshotHash": pack.get("snapshotHash") or snapshot_hash(pack),
        "roleCount": len(pack.get("roles") or []),
        "nodeCount": len(pack.get("nodeTemplates") or []),
        "materialTypeCount": len(pack.get("materialTypes") or []),
        "ruleSetCount": len(pack.get("ruleSets") or []),
        "standardClauseBindingCount": len(pack.get("standardClauseBindings") or []),
        "standardClausePackageCount": len(pack.get("standardClausePackages") or []),
        "atomicCheckCount": len(pack.get("atomicChecks") or []),
        "atomicCheckToolBindingCount": len(pack.get("atomicCheckToolBindings") or []),
        "agentSopCount": len(pack.get("agentSops") or []),
        "fixtureProjectCount": len((pack.get("fixtures") or {}).get("projects") or []),
        "roles": [
            {
                "code": role.get("code"),
                "label": role.get("label"),
                "platformRole": role.get("platformRole"),
            }
            for role in pack.get("roles") or []
            if role.get("code") != "admin"
        ],
    }


def business_pack_snapshot(pack: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        key: value
        for key, value in pack.items()
        if key not in {"loadedAt"}
    }
    snapshot["snapshotHash"] = pack.get("snapshotHash") or snapshot_hash(pack)
    return snapshot


def snapshot_hash(pack: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in pack.items()
        if key not in {"snapshotHash", "loadedAt"}
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def validate_business_pack(pack: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    missing = sorted(REQUIRED_TOP_LEVEL - set(pack))
    if missing:
        errors.append(f"Missing required top-level keys: {', '.join(missing)}")
        return {"ok": False, "errors": errors, "warnings": warnings}

    _validate_items(pack, "roles", ROLE_KEYS, errors)
    _validate_items(pack, "nodeTemplates", NODE_KEYS, errors)
    _validate_items(pack, "materialTypes", MATERIAL_KEYS, errors)
    _validate_items(pack, "workflowStateMachines", WORKFLOW_KEYS, errors)
    _validate_items(pack, "ruleSets", RULE_KEYS, errors)
    _validate_items(pack, "reportTemplates", REPORT_KEYS, errors)

    role_codes = {item["code"] for item in pack.get("roles", []) if isinstance(item, dict) and item.get("code")}
    action_codes = {
        action
        for role in pack.get("roles", [])
        if isinstance(role, dict)
        for action in role.get("actions", [])
    }
    material_codes = {
        item["code"] for item in pack.get("materialTypes", []) if isinstance(item, dict) and item.get("code")
    }
    workflow_actions = {
        action
        for action in pack.get("workflowActions", [])
        if isinstance(action, str) and action
    }
    node_ids = {
        int(item["nodeId"])
        for item in pack.get("nodeTemplates", [])
        if isinstance(item, dict) and str(item.get("nodeId", "")).isdigit()
    }

    if len(role_codes) != len(pack.get("roles") or []):
        errors.append("Role codes must be unique and present.")
    for role in pack.get("roles") or []:
        if not role.get("actions"):
            errors.append(f"Role {role.get('code')} must declare at least one action.")
        if role.get("defaultNodeId") is not None and int(role["defaultNodeId"]) not in node_ids:
            errors.append(f"Role {role.get('code')} references unknown default node: {role.get('defaultNodeId')}")
    if len(material_codes) != len(pack.get("materialTypes") or []):
        errors.append("Material type codes must be unique and present.")
    if len(node_ids) != len(pack.get("nodeTemplates") or []):
        errors.append("Node ids must be unique integers.")

    for node in pack.get("nodeTemplates") or []:
        for requirement in node.get("requiredMaterials") or []:
            material_code = requirement.get("materialTypeCode")
            if material_code not in material_codes:
                errors.append(
                    f"Node {node.get('code')} references unknown material type: {material_code}"
                )

    for workflow in pack.get("workflowStateMachines") or []:
        states = {item.get("code") for item in workflow.get("states") or []}
        if not states:
            errors.append(f"Workflow {workflow.get('id')} must declare states.")
        for transition in workflow.get("transitions") or []:
            action = transition.get("action")
            if action and action not in action_codes and action not in workflow_actions:
                warnings.append(f"Workflow {workflow.get('id')} action {action} is not listed in role actions.")
            if transition.get("from") not in states:
                errors.append(f"Workflow {workflow.get('id')} transition has unknown from state.")
            if transition.get("to") not in states:
                errors.append(f"Workflow {workflow.get('id')} transition has unknown to state.")
            for role in transition.get("roles") or []:
                if role not in role_codes:
                    errors.append(f"Workflow {workflow.get('id')} references unknown role: {role}")

    for rule in pack.get("ruleSets") or []:
        missing_nodes = sorted({int(item) for item in rule.get("nodeIds") or []} - node_ids)
        if missing_nodes:
            errors.append(f"Rule {rule.get('id')} references unknown nodes: {missing_nodes}")
        if not rule.get("outputSchemaVersion"):
            warnings.append(f"Rule {rule.get('id')} has no outputSchemaVersion.")

    _validate_standard_clause_bindings(
        pack,
        node_ids=node_ids,
        errors=errors,
        warnings=warnings,
    )
    _validate_standard_clause_packages(
        pack,
        node_ids=node_ids,
        errors=errors,
        warnings=warnings,
    )
    _validate_atomic_check_tool_bindings(pack, errors=errors)

    for report in pack.get("reportTemplates") or []:
        if not report.get("sections"):
            warnings.append(f"Report template {report.get('id')} has no sections.")
        for section in report.get("sections") or []:
            if not section.get("code") or not section.get("source"):
                errors.append(f"Report template {report.get('id')} has an invalid section.")

    for agent in pack.get("agentSops") or []:
        if not agent.get("id") or not agent.get("version"):
            errors.append("Agent SOP must declare id and version.")
        for tool in agent.get("allowedTools") or []:
            if not isinstance(tool, str) or not tool:
                errors.append(f"Agent SOP {agent.get('id')} contains invalid allowed tool.")

    _validate_fixtures(
        pack,
        role_codes=role_codes,
        material_codes=material_codes,
        node_ids=node_ids,
        errors=errors,
        warnings=warnings,
    )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def business_pack_fixtures(pack: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fixtures = pack.get("fixtures") or {}
    return {
        key: list(fixtures.get(key) or [])
        for key in FIXTURE_COLLECTION_KEYS
    }


def validate_all_business_packs() -> dict[str, Any]:
    results = []
    ok = True
    for summary in list_business_packs():
        pack = load_business_pack(summary["id"])
        validation = validate_business_pack(pack)
        ok = ok and validation["ok"]
        results.append({"summary": business_pack_summary(pack), "validation": validation})
    from .readiness import build_business_pack_portability_scorecard

    scorecard = build_business_pack_portability_scorecard()
    return {"ok": ok and bool(scorecard.get("ok")), "results": results, "scorecard": scorecard}


def _validate_items(pack: dict[str, Any], key: str, required_keys: set[str], errors: list[str]) -> None:
    items = pack.get(key)
    if not isinstance(items, list) or not items:
        errors.append(f"{key} must be a non-empty list.")
        return
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{key}[{index}] must be a mapping.")
            continue
        missing = sorted(required_keys - set(item))
        if missing:
            errors.append(f"{key}[{index}] missing keys: {', '.join(missing)}")


def _validate_source_locators(record: dict[str, Any], *, label: str, errors: list[str]) -> None:
    required = {
        "knowledgeFileId", "documentVersionId", "sourcePage", "startPage", "endPage",
        "sourceLocatorId", "locatorPrecision", "locators",
    }
    missing = sorted(required - set(record))
    if missing:
        errors.append(f"{label} missing locator keys: {', '.join(missing)}")
        return
    if not str(record.get("knowledgeFileId") or "").strip() or not str(record.get("documentVersionId") or "").strip():
        errors.append(f"{label} must resolve to a knowledge file and document version.")
    try:
        source_page = int(record.get("sourcePage"))
        start_page = int(record.get("startPage"))
        end_page = int(record.get("endPage"))
    except (TypeError, ValueError):
        errors.append(f"{label} contains non-integer page locator values.")
        return
    if start_page < 1 or source_page < start_page or end_page < source_page:
        errors.append(f"{label} contains an invalid top-level page range.")

    locators = record.get("locators")
    if not isinstance(locators, list) or not locators:
        errors.append(f"{label} must contain at least one source locator.")
        return
    locator_ids: set[str] = set()
    for index, locator in enumerate(locators):
        locator_label = f"{label}.locators[{index}]"
        if not isinstance(locator, dict):
            errors.append(f"{locator_label} must be a mapping.")
            continue
        locator_required = {
            "locatorId", "clauseNo", "sourcePage", "startPage", "endPage",
            "precision", "verificationStatus",
        }
        locator_missing = sorted(locator_required - set(locator))
        if locator_missing:
            errors.append(f"{locator_label} missing keys: {', '.join(locator_missing)}")
            continue
        locator_id = str(locator.get("locatorId") or "")
        if not locator_id or locator_id in locator_ids:
            errors.append(f"{label} contains an empty or duplicated locator id: {locator_id}")
        locator_ids.add(locator_id)
        try:
            locator_source = int(locator.get("sourcePage"))
            locator_start = int(locator.get("startPage"))
            locator_end = int(locator.get("endPage"))
        except (TypeError, ValueError):
            errors.append(f"{locator_label} contains non-integer page values.")
            continue
        if locator_start < start_page or locator_source != locator_start or locator_end < locator_start or locator_end > end_page:
            errors.append(f"{locator_label} is outside the top-level page range.")
        if locator.get("precision") not in {"page", "page_range"}:
            errors.append(f"{locator_label} has invalid precision.")
        if locator.get("verificationStatus") not in {"source_verified", "text_verified", "visual_verified"}:
            errors.append(f"{locator_label} has invalid verificationStatus.")
    if record.get("sourceLocatorId") not in locator_ids:
        errors.append(f"{label} sourceLocatorId does not reference one of its locators.")


def _validate_standard_clause_bindings(
    pack: dict[str, Any],
    *,
    node_ids: set[int],
    errors: list[str],
    warnings: list[str],
) -> None:
    bindings = pack.get("standardClauseBindings")
    if bindings is None:
        return
    if not isinstance(bindings, list):
        errors.append("standardClauseBindings must be a list.")
        return

    standard_refs = {
        item.get("id")
        for item in pack.get("standardCatalog") or []
        if isinstance(item, dict) and item.get("id")
    }
    rule_ids = {
        item.get("id")
        for item in pack.get("ruleSets") or []
        if isinstance(item, dict) and item.get("id")
    }
    binding_ids: set[str] = set()
    published_primary_rules: set[str] = set()
    allowed_lifecycle_statuses = {"draft", "published", "retired"}
    allowed_verification_statuses = {"source_verified", "candidate", "rejected"}
    allowed_binding_roles = {"primary", "supplemental"}

    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            errors.append(f"standardClauseBindings[{index}] must be a mapping.")
            continue
        missing = sorted(STANDARD_CLAUSE_BINDING_KEYS - set(binding))
        if missing:
            errors.append(
                f"standardClauseBindings[{index}] missing keys: {', '.join(missing)}"
            )
            continue

        binding_id = str(binding.get("bindingId") or "")
        if binding_id in binding_ids:
            errors.append(f"Standard clause binding id is duplicated: {binding_id}")
        binding_ids.add(binding_id)

        rule_id = binding.get("ruleId")
        if rule_id not in rule_ids:
            errors.append(f"Binding {binding_id} references unknown rule: {rule_id}")
        try:
            node_id = int(binding.get("nodeId"))
        except (TypeError, ValueError):
            errors.append(f"Binding {binding_id} has invalid nodeId: {binding.get('nodeId')}")
        else:
            if node_id not in node_ids:
                errors.append(f"Binding {binding_id} references unknown node: {node_id}")

        standard_ref = binding.get("standardRef")
        if standard_ref not in standard_refs:
            errors.append(f"Binding {binding_id} references unknown standard: {standard_ref}")
        if binding.get("lifecycleStatus") not in allowed_lifecycle_statuses:
            errors.append(f"Binding {binding_id} has invalid lifecycleStatus.")
        if binding.get("verificationStatus") not in allowed_verification_statuses:
            errors.append(f"Binding {binding_id} has invalid verificationStatus.")
        if binding.get("bindingRole") not in allowed_binding_roles:
            errors.append(f"Binding {binding_id} has invalid bindingRole.")
        _validate_source_locators(binding, label=f"Binding {binding_id}", errors=errors)

        if (
            binding.get("lifecycleStatus") == "published"
            and binding.get("verificationStatus") != "source_verified"
        ):
            errors.append(f"Binding {binding_id} must be source_verified before publication.")
        if binding.get("lifecycleStatus") == "published" and binding.get("bindingRole") == "primary":
            if rule_id in published_primary_rules:
                errors.append(f"Rule {rule_id} has more than one published primary clause binding.")
            published_primary_rules.add(str(rule_id))

    if bindings and not published_primary_rules:
        warnings.append("No primary standard clause binding is published; runtime must not consume draft bindings.")


def _validate_standard_clause_packages(
    pack: dict[str, Any],
    *,
    node_ids: set[int],
    errors: list[str],
    warnings: list[str],
) -> None:
    packages = pack.get("standardClausePackages")
    checks = pack.get("atomicChecks")
    if packages is None and checks is None:
        return
    if not isinstance(packages, list) or not packages:
        errors.append("standardClausePackages must be a non-empty list when clause packages are enabled.")
        return
    if not isinstance(checks, list) or not checks:
        errors.append("atomicChecks must be a non-empty list when clause packages are enabled.")
        return

    catalog_by_ref = {
        item.get("id"): item
        for item in pack.get("standardCatalog") or []
        if isinstance(item, dict) and item.get("id")
    }
    catalog_refs = set(catalog_by_ref)
    rule_by_id = {
        item.get("id"): item
        for item in pack.get("ruleSets") or []
        if isinstance(item, dict) and item.get("id")
    }
    expected_source_rules = {
        str(item.get("sourceRuleId"))
        for item in rule_by_id.values()
        if item.get("sourceRuleId")
    }
    binding_by_id = {
        item.get("bindingId"): item
        for item in pack.get("standardClauseBindings") or []
        if isinstance(item, dict) and item.get("bindingId")
    }

    check_by_id: dict[str, dict[str, Any]] = {}
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(f"atomicChecks[{index}] must be a mapping.")
            continue
        missing = sorted(ATOMIC_CHECK_KEYS - set(check))
        if missing:
            errors.append(f"atomicChecks[{index}] missing keys: {', '.join(missing)}")
            continue
        check_id = str(check.get("id") or "")
        if check_id in check_by_id:
            errors.append(f"Atomic check id is duplicated: {check_id}")
        check_by_id[check_id] = check
        if check.get("ruleId") not in rule_by_id:
            errors.append(f"Atomic check {check_id} references unknown rule: {check.get('ruleId')}")
        try:
            check_node_id = int(check.get("nodeId"))
        except (TypeError, ValueError):
            errors.append(f"Atomic check {check_id} has invalid nodeId: {check.get('nodeId')}")
        else:
            if check_node_id not in node_ids:
                errors.append(f"Atomic check {check_id} references unknown node: {check_node_id}")
        if not str(check.get("instruction") or "").strip():
            errors.append(f"Atomic check {check_id} must contain an instruction.")

    package_ids: set[str] = set()
    package_source_rules: set[str] = set()
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            errors.append(f"standardClausePackages[{index}] must be a mapping.")
            continue
        missing = sorted(STANDARD_CLAUSE_PACKAGE_KEYS - set(package))
        if missing:
            errors.append(f"standardClausePackages[{index}] missing keys: {', '.join(missing)}")
            continue
        package_id = str(package.get("packageId") or "")
        if package_id in package_ids:
            errors.append(f"Standard clause package id is duplicated: {package_id}")
        package_ids.add(package_id)
        source_rule_id = str(package.get("sourceRuleId") or "")
        if source_rule_id in package_source_rules:
            errors.append(f"Source rule has more than one standard clause package: {source_rule_id}")
        package_source_rules.add(source_rule_id)

        rule = rule_by_id.get(package.get("ruleId"))
        if rule is None:
            errors.append(f"Package {package_id} references unknown rule: {package.get('ruleId')}")
            continue
        if rule.get("sourceRuleId") != source_rule_id:
            errors.append(f"Package {package_id} sourceRuleId does not match its rule.")
        try:
            package_node_id = int(package.get("nodeId"))
        except (TypeError, ValueError):
            errors.append(f"Package {package_id} has invalid nodeId: {package.get('nodeId')}")
            continue
        if package_node_id not in node_ids or package_node_id not in {int(item) for item in rule.get("nodeIds") or []}:
            errors.append(f"Package {package_id} nodeId does not match its rule: {package_node_id}")

        primary = binding_by_id.get(package.get("primaryBindingId"))
        if primary is None:
            errors.append(f"Package {package_id} references unknown primary binding: {package.get('primaryBindingId')}")
        else:
            if primary.get("ruleId") != package.get("ruleId") or primary.get("bindingRole") != "primary":
                errors.append(f"Package {package_id} primary binding does not match its rule.")
            if package.get("lifecycleStatus") == "published" and (
                primary.get("lifecycleStatus") != "published"
                or primary.get("verificationStatus") != "source_verified"
            ):
                errors.append(f"Published package {package_id} requires a published, source-verified primary binding.")

        check_ids = package.get("atomicCheckIds") or []
        if not isinstance(check_ids, list) or len(check_ids) < 2:
            errors.append(f"Package {package_id} must reference at least two atomic checks.")
        for check_id in check_ids:
            check = check_by_id.get(check_id)
            if check is None:
                errors.append(f"Package {package_id} references unknown atomic check: {check_id}")
            elif check.get("ruleId") != package.get("ruleId") or int(check.get("nodeId")) != package_node_id:
                errors.append(f"Package {package_id} atomic check {check_id} does not match its rule and node.")

        clauses = package.get("professionalClauses") or []
        if not isinstance(clauses, list) or not clauses:
            errors.append(f"Package {package_id} must contain professional clauses.")
        for clause in clauses:
            if not isinstance(clause, dict):
                errors.append(f"Package {package_id} contains an invalid professional clause.")
                continue
            if clause.get("standardRef") not in catalog_refs:
                errors.append(f"Package {package_id} references unknown standard: {clause.get('standardRef')}")
            if not clause.get("clauseNo") or not clause.get("purpose"):
                errors.append(f"Package {package_id} contains a professional clause without clauseNo or purpose.")
            if clause.get("verificationStatus") not in {"source_verified", "visual_verified", "candidate"}:
                errors.append(f"Package {package_id} contains an invalid professional clause verificationStatus.")
            if clause.get("verificationStatus") == "candidate":
                warnings.append(f"Package {package_id} contains candidate supplemental clause {clause.get('clauseNo')}.")
            _validate_source_locators(
                clause,
                label=f"Package {package_id} professional clause {clause.get('clauseNo')}",
                errors=errors,
            )
            catalog_item = catalog_by_ref.get(clause.get("standardRef")) or {}
            if clause.get("knowledgeFileId") != catalog_item.get("knowledgeFileId"):
                errors.append(f"Package {package_id} professional clause knowledgeFileId does not match its standard catalog record.")
            if clause.get("documentVersionId") != catalog_item.get("documentVersionId"):
                errors.append(f"Package {package_id} professional clause documentVersionId does not match its standard catalog record.")

        decision_model = package.get("decisionModel") or {}
        expected_execution = (
            "llm_semantic_primary_with_evidence_validation"
            if package.get("sourceRuleId") == "R19"
            else "deterministic_tools_only"
        )
        if decision_model.get("ruleExecution") != expected_execution:
            errors.append(f"Package {package_id} must use {expected_execution} rule execution.")
        required_results = {"符合", "不符合", "证据不足", "不适用", "待人工确认"}
        if not required_results <= set(decision_model.get("resultValues") or []):
            errors.append(f"Package {package_id} does not declare the complete conclusion set.")

    missing_packages = sorted(expected_source_rules - package_source_rules)
    extra_packages = sorted(package_source_rules - expected_source_rules)
    if missing_packages:
        errors.append(f"Standard clause packages are missing source rules: {missing_packages}")
    if extra_packages:
        errors.append(f"Standard clause packages contain unknown source rules: {extra_packages}")


def _validate_atomic_check_tool_bindings(
    pack: dict[str, Any],
    *,
    errors: list[str],
) -> None:
    checks = pack.get("atomicChecks")
    bindings = pack.get("atomicCheckToolBindings")
    if checks is None and bindings is None:
        return
    if not isinstance(checks, list) or not checks:
        errors.append("atomicChecks must be present when atomicCheckToolBindings are enabled.")
        return
    if not isinstance(bindings, list) or not bindings:
        errors.append("atomicCheckToolBindings must cover all atomicChecks.")
        return

    check_by_id = {
        str(item.get("id")): item
        for item in checks
        if isinstance(item, dict) and item.get("id")
    }
    binding_ids: set[str] = set()
    allowed_statuses = {"planned", "pilot_implemented", "implemented", "deprecated"}
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            errors.append(f"atomicCheckToolBindings[{index}] must be a mapping.")
            continue
        missing = sorted(ATOMIC_CHECK_TOOL_BINDING_KEYS - set(binding))
        if missing:
            errors.append(f"atomicCheckToolBindings[{index}] missing keys: {', '.join(missing)}")
            continue
        check_id = str(binding.get("atomicCheckId") or "")
        if check_id in binding_ids:
            errors.append(f"Atomic check tool binding is duplicated: {check_id}")
        binding_ids.add(check_id)
        check = check_by_id.get(check_id)
        if check is None:
            errors.append(f"Atomic check tool binding references unknown check: {check_id}")
            continue
        if binding.get("sourceRuleId") != check.get("sourceRuleId"):
            errors.append(f"Atomic check tool binding {check_id} sourceRuleId does not match its check.")
        if not isinstance(binding.get("requiredFacts"), list) or not binding.get("requiredFacts"):
            errors.append(f"Atomic check tool binding {check_id} must declare requiredFacts.")
        if not isinstance(binding.get("tools"), list) or not binding.get("tools"):
            errors.append(f"Atomic check tool binding {check_id} must declare tools.")
        if not all(isinstance(item, str) and item for item in binding.get("tools") or []):
            errors.append(f"Atomic check tool binding {check_id} contains an invalid tool name.")
        if not isinstance(binding.get("parameters"), dict):
            errors.append(f"Atomic check tool binding {check_id} parameters must be a mapping.")
        if not str(binding.get("outputSchema") or "").strip():
            errors.append(f"Atomic check tool binding {check_id} must declare outputSchema.")
        if binding.get("implementationStatus") not in allowed_statuses:
            errors.append(f"Atomic check tool binding {check_id} has invalid implementationStatus.")

    missing_bindings = sorted(set(check_by_id) - binding_ids)
    extra_bindings = sorted(binding_ids - set(check_by_id))
    if missing_bindings:
        errors.append(f"Atomic checks are missing tool bindings: {missing_bindings}")
    if extra_bindings:
        errors.append(f"Tool bindings contain unknown atomic checks: {extra_bindings}")


def _validate_fixtures(
    pack: dict[str, Any],
    *,
    role_codes: set[str],
    material_codes: set[str],
    node_ids: set[int],
    errors: list[str],
    warnings: list[str],
) -> None:
    fixtures = pack.get("fixtures") or {}
    if not fixtures:
        warnings.append(f"Business pack {pack.get('id')} has no fixtures.")
        return
    if not isinstance(fixtures, dict):
        errors.append("fixtures must be a mapping.")
        return

    project_ids: set[str] = set()
    for project in fixtures.get("projects") or []:
        project_id = project.get("id") or project.get("code")
        if not project_id:
            errors.append("Fixture project must declare id or code.")
            continue
        if project_id in project_ids:
            errors.append(f"Fixture project id is duplicated: {project_id}")
        project_ids.add(project_id)
        if project.get("businessPackId") not in {None, pack["id"]}:
            errors.append(f"Fixture project {project_id} references a different business pack.")
        current_node_id = project.get("currentNodeId")
        if current_node_id is not None and int(current_node_id) not in node_ids:
            errors.append(f"Fixture project {project_id} references unknown current node: {current_node_id}")

    document_ids: set[str] = set()
    for document in fixtures.get("documents") or []:
        document_id = document.get("id")
        if not document_id:
            errors.append("Fixture document must declare id.")
            continue
        if document_id in document_ids:
            errors.append(f"Fixture document id is duplicated: {document_id}")
        document_ids.add(document_id)
        if document.get("projectId") and document["projectId"] not in project_ids:
            errors.append(f"Fixture document {document_id} references unknown project: {document['projectId']}")
        material_type = document.get("materialTypeCode")
        if material_type and material_type not in material_codes:
            errors.append(f"Fixture document {document_id} references unknown material type: {material_type}")

    requirement_ids = {
        requirement.get("id")
        for node in pack.get("nodeTemplates") or []
        for requirement in node.get("requiredMaterials") or []
        if requirement.get("id")
    }
    for binding in fixtures.get("bindings") or []:
        binding_id = binding.get("id") or "unknown"
        if binding.get("projectId") and binding["projectId"] not in project_ids:
            errors.append(f"Fixture binding {binding_id} references unknown project: {binding['projectId']}")
        if int(binding.get("nodeId") or 0) not in node_ids:
            errors.append(f"Fixture binding {binding_id} references unknown node: {binding.get('nodeId')}")
        if binding.get("documentId") and binding["documentId"] not in document_ids:
            errors.append(f"Fixture binding {binding_id} references unknown document: {binding['documentId']}")
        if binding.get("requirementId") and binding["requirementId"] not in requirement_ids:
            errors.append(f"Fixture binding {binding_id} references unknown requirement: {binding['requirementId']}")

    for finding in fixtures.get("reviewFindings") or []:
        finding_id = finding.get("id") or "unknown"
        if finding.get("projectId") and finding["projectId"] not in project_ids:
            errors.append(f"Fixture finding {finding_id} references unknown project: {finding['projectId']}")
        if int(finding.get("nodeId") or 0) not in node_ids:
            errors.append(f"Fixture finding {finding_id} references unknown node: {finding.get('nodeId')}")
        if finding.get("source") == "ai" and (not finding.get("evidenceLinkIds") or not finding.get("ruleRefs")):
            errors.append(f"Fixture AI finding {finding_id} must contain evidenceLinkIds and ruleRefs.")

    for member in fixtures.get("projectMembers") or []:
        role = member.get("role")
        if role not in role_codes:
            errors.append(f"Fixture member references unknown role: {role}")


def role_actions_map(pack: dict[str, Any] | None = None) -> dict[str, list[str]]:
    source = pack or default_business_pack()
    return {role["code"]: list(role.get("actions") or []) for role in source["roles"]}


def role_default_node_map(pack: dict[str, Any] | None = None) -> dict[str, int]:
    source = pack or default_business_pack()
    return {
        role["code"]: int(role.get("defaultNodeId") or source["nodeTemplates"][0]["nodeId"])
        for role in source["roles"]
    }


def build_project_tree(project_id: str, pack: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    source = pack or default_business_pack()
    nodes = []
    for template in source["nodeTemplates"]:
        node_id = int(template["nodeId"])
        nodes.append(
            {
                "id": f"{project_id}-{node_id}",
                "projectId": project_id,
                "nodeId": node_id,
                "templateId": template.get("id") or f"{source['id']}-node-{node_id}",
                "templateCode": template["code"],
                "businessPackId": source["id"],
                "businessPackVersion": source["version"],
                "code": template["code"],
                "name": template["name"],
                "groupName": template["groupName"],
                "inspectionType": template["inspectionType"],
                "status": template["defaultStatus"],
                "fileCount": int(template.get("fileCount", node_id % 5)),
                "requiredProgress": template.get("requiredProgress")
                or {"done": int(template.get("requiredDone", 0)), "total": len(template.get("requiredMaterials") or []) or 1},
                "actions": list(template.get("actions") or ["project:view", "file:bind"]),
                "revision": 1,
            }
        )
    return nodes


def build_project_requirements(
    pack: dict[str, Any] | None = None,
    *,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    source = pack or default_business_pack()
    requirements = []
    material_by_code = {item["code"]: item for item in source["materialTypes"]}
    for template in source["nodeTemplates"]:
        node_id = int(template["nodeId"])
        for index, requirement in enumerate(template.get("requiredMaterials") or [], start=1):
            material = material_by_code.get(requirement["materialTypeCode"], {})
            requirements.append(
                {
                    "id": requirement.get("id") or f"REQ-{node_id}-{index:02d}",
                    "projectId": project_id,
                    "nodeId": node_id,
                    "name": requirement.get("name") or material.get("name") or requirement["materialTypeCode"],
                    "requiredType": requirement.get("requiredType") or material.get("requiredType") or "必传",
                    "materialTypeCode": requirement["materialTypeCode"],
                    "businessPackId": source["id"],
                    "businessPackVersion": source["version"],
                    "templateNodeCode": template["code"],
                    "note": requirement.get("note"),
                    "responsibleParty": requirement.get("responsibleParty"),
                    "applicability": requirement.get("applicability"),
                }
            )
    return requirements


def matching_rule_for_node(pack: dict[str, Any], node_id: int) -> dict[str, Any] | None:
    return next(
        (
            rule
            for rule in pack.get("ruleSets") or []
            if int(node_id) in {int(item) for item in rule.get("nodeIds") or []}
        ),
        None,
    )


def default_agent_sop(pack: dict[str, Any]) -> dict[str, Any] | None:
    return next(iter(pack.get("agentSops") or []), None)


def _template_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def render_prompt_template(template: str, context: dict[str, Any]) -> str:
    def replace_double(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return _template_value(context.get(key, match.group(0)))

    rendered = re.sub(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}", replace_double, template or "")
    for key, value in context.items():
        rendered = rendered.replace("{" + key + "}", _template_value(value))
    return rendered


def build_ai_review_prompt(
    pack: dict[str, Any],
    *,
    node: dict[str, Any] | None,
    fields: list[dict[str, Any]],
    rule: dict[str, Any] | None = None,
    prompt_template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agent = default_agent_sop(pack) or {}
    effective_rule = rule or matching_rule_for_node(pack, int((node or {}).get("nodeId") or 0)) or {}
    node_name = (node or {}).get("name") or "review node"
    material_names = [
        material.get("name")
        for material in pack.get("materialTypes") or []
        if material.get("name")
    ][:8]
    default_system = (
        f"You are {agent.get('name') or 'review assistant'} for business pack "
        f"{pack['id']} version {pack['version']}. "
        "Return evidence-backed review suggestions only. Do not approve final business state."
    )
    user = {
        "businessPack": {
            "id": pack["id"],
            "name": pack["name"],
            "domainType": pack["domainType"],
        },
        "node": {
            "id": (node or {}).get("nodeId"),
            "name": node_name,
            "groupName": (node or {}).get("groupName"),
        },
        "rule": {
            "id": effective_rule.get("id"),
            "version": effective_rule.get("version"),
            "sequence": effective_rule.get("sourceSequence"),
            "inspectionCategory": effective_rule.get("inspectionCategory") or effective_rule.get("businessModule"),
            "inspectionItem": effective_rule.get("inspectionItem") or effective_rule.get("name"),
            "inspectionClass": effective_rule.get("inspectionClass") or effective_rule.get("reviewClass"),
            "standardText": effective_rule.get("standardText") or effective_rule.get("criteria"),
            "witnessText": effective_rule.get("witnessText") or effective_rule.get("checkMethod"),
            "description": effective_rule.get("description"),
            "aiExecution": effective_rule.get("aiExecution"),
        },
        "materialTypes": material_names,
        "ocrFields": fields[:12],
        "requiredOutput": "ReviewFindingDraftList with findingType, severity, description, evidenceLinkIds, ruleRefs, confidence, suggestedAction.",
    }
    base_prompt_json = json.dumps(user, ensure_ascii=False)
    template_context = {
        "agentName": agent.get("name") or "review assistant",
        "agentId": agent.get("id") or "",
        "agentVersion": agent.get("version") or "",
        "businessPackId": pack["id"],
        "businessPackName": pack["name"],
        "businessPackVersion": pack["version"],
        "domainType": pack.get("domainType") or "",
        "nodeId": (node or {}).get("nodeId"),
        "nodeName": node_name,
        "groupName": (node or {}).get("groupName") or "",
        "ruleId": effective_rule.get("id") or "",
        "ruleVersion": effective_rule.get("version") or "",
        "basePromptJson": base_prompt_json,
        "ocrFieldCount": len(fields),
    }
    system_template = (prompt_template or {}).get("systemPrompt") or default_system
    user_template = (prompt_template or {}).get("userPromptTemplate") or "{{basePromptJson}}"
    return {
        "system": render_prompt_template(system_template, template_context),
        "user": render_prompt_template(user_template, template_context),
        "template": {
            "id": (prompt_template or {}).get("id"),
            "name": (prompt_template or {}).get("name"),
            "version": (prompt_template or {}).get("version"),
            "promptKey": (prompt_template or {}).get("promptKey"),
            "plannerPrompt": render_prompt_template(
                (prompt_template or {}).get("plannerPromptTemplate") or "",
                template_context,
            ),
            "criticPrompt": render_prompt_template(
                (prompt_template or {}).get("criticPromptTemplate") or "",
                template_context,
            ),
        },
    }
