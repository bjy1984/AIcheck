"""Preliminary R39 source gate before metadata is projected into tool inputs."""
from __future__ import annotations

from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding
from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_tools.r39_reference import SCOPE_FIELDS

SOURCE_GROUPS = {
    "ptEmulsifierApplication": ("ptContexts", "ptBases", "ptProcesses"),
    "procedureReference": ("referenceContexts", "referenceBases", "instructionReferences", "procedureIdentities", "referenceInventories", "referenceMembers"),
    "firstUseValidation": ("applications", "bases", "validations"),
    "approvalChain": ("approvalContexts", "requirements", "steps", "signatureInventories", "signatures"),
    "documentContent": ("contentContexts", "contentBases", "contentInventories", "contentFields"),
}


def validate_r39_sources(groups, input_name):
    selected = [(name, groups[name]) for name in SOURCE_GROUPS[input_name]]
    rows = [row for _, values in selected for row in values]
    # Validate before the shared grounding checker: booleans and non-finite numeric
    # values must not be treated as trustworthy confidence scores or raise decimal errors.
    malformed = []
    for index, row in enumerate(rows):
        confidence = row["evidence"].get("confidence")
        conflict = row.get("conflicted", False)
        if (type(confidence) not in (int, float) or not 0 <= confidence <= 1 or type(conflict) is not bool):
            malformed.append(index)
    if malformed:
        return {"result": "evidence_insufficient", "invalidSourceRows": malformed, "minConfidence": .75}
    judgment = build_material_judgment([(name, values, ("projectId",)) for name, values in selected])["judgment"]
    checked = validate_evidence_grounding({"facts": judgment["claimedFacts"], "evidenceRefs": judgment["evidenceRefs"], "minConfidence": .75})
    return {"result": checked["result"], "checks": checked["checks"], "minConfidence": .75}


def _isolate_reference_sources(groups, facts, checked):
    """Retain independent pairs only when their shared inventory is trustworthy."""
    value = facts.get("procedureReference")
    if not isinstance(value, dict) or "inventory" not in value:
        return False
    names = SOURCE_GROUPS["procedureReference"]
    shared = {name: groups[name] if name in {"referenceInventories", "referenceMembers"} else [] for name in names}
    checked["inventoryValidation"] = validate_r39_sources(shared, "procedureReference")
    if checked["inventoryValidation"]["result"] != "passed":
        return False
    retained = []
    checked["pairValidation"] = []
    for pair in value["referencePairs"]:
        scope = pair.get("scope")
        if not isinstance(scope, dict):
            continue
        selected = {name: [row for row in groups[name] if all(row.get(key) == scope[key] for key in SCOPE_FIELDS)]
                    if name not in {"referenceInventories", "referenceMembers"} else [] for name in names}
        validation = validate_r39_sources(selected, "procedureReference")
        checked["pairValidation"].append({"scope": dict(scope), **validation})
        if validation["result"] == "passed":
            retained.append(pair)
    # Keep coverage incomplete even if the unreliable row was outside the inventory.
    value["referencePairs"] = [*retained, {}]
    return True


def gate_r39_inputs(groups, facts):
    """Keep diagnostics but do not pass unreliable inputs to a business subtool."""
    checks = {name: validate_r39_sources(groups, name) for name in SOURCE_GROUPS}
    facts["sourceValidation"] = checks
    for name, checked in checks.items():
        if checked["result"] != "passed":
            if name != "procedureReference" or not _isolate_reference_sources(groups, facts, checked):
                facts.pop(name, None)
            facts["sourceIssues"].append("r39_" + name + "_source_gate_failed")
