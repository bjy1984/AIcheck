"""The conversational scope tool must use the same frozen R01 profile as formal review."""

from __future__ import annotations

from copy import deepcopy

from apps.api import routes
from libs.business_pack import load_business_pack


def _run(project: dict, *, arguments: dict | None = None, review_run: dict | None = None) -> dict:
    return routes.review_conversation_agent_tool_output(
        "check_design_license_scope",
        arguments or {"licenseScopes": ["GCD"], "requiredPipelineGrades": ["GC2"]},
        session={}, project=project, node={"nodeId": 1}, basis={}, basis_items=[],
        readiness={}, evidence_links=[], review_run=review_run,
    )


def test_conversation_uses_project_frozen_profile_not_tool_default():
    pack = load_business_pack()
    project = {"businessPackId": pack["id"], "businessPackVersion": pack["version"],
               "businessPackSnapshot": deepcopy(pack)}
    assert _run(project)["result"] == "passed"

    old = deepcopy(project)
    old["businessPackVersion"] = "2026.07.16"
    old["businessPackSnapshot"]["version"] = "2026.07.16"
    for binding in old["businessPackSnapshot"]["atomicCheckToolBindings"]:
        if binding["atomicCheckId"] == "AC-R01-02":
            binding["parameters"]["scopeProfile"] = "design-license-scope-cn-v1"
    assert _run(old)["result"] == "failed"
    assert _run(project, review_run={"atomicCheckToolBindingsSnapshot":
                            old["businessPackSnapshot"]["atomicCheckToolBindings"]})["result"] == "failed"


def test_conversation_cannot_override_frozen_profile_or_guess_missing_old_release():
    pack = load_business_pack()
    project = {"businessPackId": pack["id"], "businessPackVersion": pack["version"],
               "businessPackSnapshot": deepcopy(pack)}
    override = _run(project, arguments={"licenseScopes": ["GCD"], "requiredPipelineGrades": ["GC2"],
                                        "scopeProfile": "design-license-scope-cn-v1"})
    assert override["errorCode"] == "REVIEW_AGENT_RULE_PROFILE_OVERRIDE"
    invalid_type = _run(project, arguments={"licenseScopes": ["GCD"], "requiredPipelineGrades": ["GC2"],
                                            "scopeProfile": ["design-license-scope-cn-v2"]})
    assert invalid_type["errorCode"] == "REVIEW_AGENT_RULE_PROFILE_OVERRIDE"

    missing_snapshot = {"businessPackId": pack["id"], "businessPackVersion": "2026.07.16"}
    assert _run(missing_snapshot)["errorCode"] == "REVIEW_AGENT_RULE_PROFILE_UNAVAILABLE"
    assert _run(project, review_run={"businessPackVersion": "2026.07.16"})["errorCode"] == (
        "REVIEW_AGENT_RULE_PROFILE_UNAVAILABLE"
    )
