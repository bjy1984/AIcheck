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
