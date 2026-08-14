from __future__ import annotations

from typing import Any

from .boundary import scan_core_boundary
from .loader import (
    business_pack_summary,
    list_business_packs,
    load_business_pack,
    validate_business_pack,
)

REQUIRED_PACK_COMPONENTS = (
    "roles",
    "nodeTemplates",
    "materialTypes",
    "workflowStateMachines",
    "ruleSets",
    "reportTemplates",
    "agentSops",
    "fixtures",
)


def build_business_pack_portability_scorecard() -> dict[str, Any]:
    pack_scorecards = [build_single_pack_scorecard(load_business_pack(item["id"])) for item in list_business_packs()]
    sections = [
        pack_catalog_section(pack_scorecards),
        boundary_section(),
        fixture_section(pack_scorecards),
        delivery_section(pack_scorecards),
    ]
    score = round(sum(float(section["score"]) for section in sections), 2)
    blockers = [
        blocker
        for section in sections
        for blocker in section.get("blockers", [])
    ]
    return {
        "schemaVersion": "aicheck-business-pack-portability-scorecard-v1",
        "targetScore": 100,
        "score": score,
        "ok": score >= 100 and not blockers,
        "sections": sections,
        "blockers": blockers,
        "packs": pack_scorecards,
    }


def build_single_pack_scorecard(pack: dict[str, Any]) -> dict[str, Any]:
    validation = validate_business_pack(pack)
    fixtures = pack.get("fixtures") if isinstance(pack.get("fixtures"), dict) else {}
    component_status = {
        component: component_available(pack, component)
        for component in REQUIRED_PACK_COMPONENTS
    }
    fixture_status = {
        "projects": bool(fixtures.get("projects")),
        "documents": bool(fixtures.get("documents")),
        "bindings": bool(fixtures.get("bindings")),
        "evidenceLinks": bool(fixtures.get("evidenceLinks")),
        "reviewFindings": bool(fixtures.get("reviewFindings")),
        "projectMembers": bool(fixtures.get("projectMembers")),
    }
    portability_status = {
        "hasDomainType": bool(pack.get("domainType")),
        "hasSnapshotHash": bool(pack.get("snapshotHash")),
        "hasWorkflowActions": bool(pack.get("workflowActions")),
        "hasAgentSops": bool(pack.get("agentSops")),
        "hasRoleMappings": all(bool(role.get("platformRole")) for role in pack.get("roles") or []),
    }
    blockers: list[str] = []
    if not validation.get("ok"):
        blockers.extend([f"{pack.get('id')}: {item}" for item in validation.get("errors") or []])
    missing_components = [key for key, ok in component_status.items() if not ok]
    if missing_components:
        blockers.append(f"{pack.get('id')}: missing components {', '.join(missing_components)}")
    missing_fixtures = [key for key, ok in fixture_status.items() if not ok]
    if missing_fixtures:
        blockers.append(f"{pack.get('id')}: missing fixture coverage {', '.join(missing_fixtures)}")
    missing_portability = [key for key, ok in portability_status.items() if not ok]
    if missing_portability:
        blockers.append(f"{pack.get('id')}: missing portability metadata {', '.join(missing_portability)}")
    component_score = sum(1 for ok in component_status.values() if ok) / len(component_status)
    fixture_score = sum(1 for ok in fixture_status.values() if ok) / len(fixture_status)
    portability_score = sum(1 for ok in portability_status.values() if ok) / len(portability_status)
    score = round(
        (25 if validation.get("ok") else 0)
        + component_score * 30
        + fixture_score * 25
        + portability_score * 20,
        2,
    )
    return {
        "packId": pack["id"],
        "domainType": pack["domainType"],
        "summary": business_pack_summary(pack),
        "score": score,
        "ok": score >= 100 and not blockers,
        "componentStatus": component_status,
        "fixtureStatus": fixture_status,
        "portabilityStatus": portability_status,
        "blockers": blockers,
    }


def pack_catalog_section(pack_scorecards: list[dict[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    points = 0.0
    domain_types = {
        item.get("summary", {}).get("domainType")
        for item in pack_scorecards
        if item.get("summary", {}).get("domainType")
    }
    if len(pack_scorecards) >= 3:
        points += 7
    else:
        blockers.append("business pack catalog must include at least three reusable packs")
    if len(domain_types) >= 3:
        points += 6
    else:
        blockers.append("business pack catalog must cover at least three domain types")
    if all(item.get("score", 0) >= 90 for item in pack_scorecards):
        points += 7
    else:
        blockers.append("one or more business packs score below 90")
    if all(item.get("summary", {}).get("snapshotHash") for item in pack_scorecards):
        points += 5
    else:
        blockers.append("one or more business packs lack snapshotHash")
    return section("catalog", points, 25, blockers)


def boundary_section() -> dict[str, Any]:
    violations = scan_core_boundary()
    blockers: list[str] = []
    points = 0.0
    if not violations:
        points += 25
    else:
        blockers.append(f"core business pack boundary has {len(violations)} industry term violations")
    return section("core-boundary", points, 25, blockers, data={"violations": violations[:10]})


def fixture_section(pack_scorecards: list[dict[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    points = 0.0
    required_fixture_keys = {"projects", "documents", "bindings", "evidenceLinks", "reviewFindings", "projectMembers"}
    for key in required_fixture_keys:
        if all(item.get("fixtureStatus", {}).get(key) for item in pack_scorecards):
            points += 25 / len(required_fixture_keys)
        else:
            blockers.append(f"fixture coverage missing for {key}")
    return section("fixtures", points, 25, blockers)


def delivery_section(pack_scorecards: list[dict[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    points = 0.0
    checks = {
        "domain metadata": lambda item: item.get("portabilityStatus", {}).get("hasDomainType"),
        "workflow actions": lambda item: item.get("portabilityStatus", {}).get("hasWorkflowActions"),
        "agent sop": lambda item: item.get("portabilityStatus", {}).get("hasAgentSops"),
        "role mappings": lambda item: item.get("portabilityStatus", {}).get("hasRoleMappings"),
        "validation clean": lambda item: not item.get("blockers"),
    }
    for label, predicate in checks.items():
        if all(predicate(item) for item in pack_scorecards):
            points += 25 / len(checks)
        else:
            blockers.append(f"business pack delivery check failed: {label}")
    return section("delivery", points, 25, blockers)


def component_available(pack: dict[str, Any], component: str) -> bool:
    if component == "fixtures":
        return isinstance(pack.get(component), dict) and bool(pack.get(component))
    return bool(pack.get(component))


def section(
    name: str,
    score: float,
    max_score: float,
    blockers: list[str],
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score = round(min(max(score, 0.0), max_score), 2)
    payload = {
        "name": name,
        "score": score,
        "maxScore": max_score,
        "status": "pass" if score >= max_score and not blockers else "fail",
        "blockers": blockers,
    }
    if data:
        payload["data"] = data
    return payload
