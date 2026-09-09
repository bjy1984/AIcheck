import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs import rule_draft_generation as generation
from libs.db.repository import repo

BASE = "/api/projects/P-2026-HDCP-001/rules/draft-suggestion"
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
SUGGESTION = {"draft": {"inspectionItem": "材料厚度", "standardText": "厚度至少10mm", "witnessText": "核对测量原文",
                       "executionConditions": {"schemaVersion": "rule-conditions-v1", "checks": [
                           {"id": "thickness", "field": "thickness", "operator": "gte", "expected": 10, "unit": "mm"}]}},
              "questions": ["请确认适用材料和取值对象。"]}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    repo.reset()
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")


def test_real_route_returns_unstored_draft_and_preserves_rules(monkeypatch):
    calls = []
    class Client:
        def chat_sync(self, messages, **options):
            calls.append((messages, options))
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(SUGGESTION)}}]}
    monkeypatch.setattr(generation, "build_qwen_runtime_client", lambda *_: Client())
    before = deepcopy(repo.state["rule_versions"])
    result = TestClient(app).post(BASE, headers=HEADERS, json={"nodeId": 16, "description": "厚度至少10mm"}).json()
    assert result["code"] == 0, result
    assert result["data"]["draft"] == SUGGESTION["draft"]
    assert result["data"]["saved"] is False
    assert result["data"]["requiresHumanConfirmation"] is True
    assert repo.state["rule_versions"] == before
    assert len(calls) == 1
    assert json.loads(calls[0][0][1]["content"])["nodeId"] == 16


@pytest.mark.parametrize("mutation", [
    lambda v: v.update(status="published"),
    lambda v: v["draft"].update(projectId="OTHER"),
    lambda v: v["draft"]["executionConditions"]["checks"][0].update(expected="10"),
    lambda v: v["draft"]["executionConditions"]["checks"][0].update(atomicCheckId="R16"),
    lambda v: v.update(questions="not a list"),
])
def test_invalid_model_output_rejected(mutation):
    value = deepcopy(SUGGESTION)
    mutation(value)
    with pytest.raises(ValueError):
        generation.validate_suggestion(value)


@pytest.mark.parametrize("headers,body", [
    ({"X-Role": "construction"}, {"nodeId": 16, "description": "rule"}),
    (HEADERS, {"nodeId": 99999, "description": "rule"}),
    (HEADERS, {"nodeId": True, "description": "rule"}),
    (HEADERS, {"nodeId": 16, "description": " "}),
    (HEADERS, {"nodeId": 16, "description": "rule", "status": "published"}),
])
def test_invalid_requests_do_not_call_provider(monkeypatch, headers, body):
    def forbidden(*_):
        pytest.fail("provider must not run")
    monkeypatch.setattr(generation, "generate_rule_draft", forbidden)
    assert TestClient(app).post(BASE, headers=headers, json=body).json()["code"] != 0


def test_provider_failure_is_actionable_and_does_not_store(monkeypatch):
    def bad(*_):
        raise ValueError("bad response")
    monkeypatch.setattr(generation, "generate_rule_draft", bad)
    before = deepcopy(repo.state["rule_versions"])
    result = TestClient(app).post(BASE, headers=HEADERS, json={"nodeId": 16, "description": "rule"}).json()
    assert result["code"] != 0
    assert "原规则未变" in result["message"]
    assert repo.state["rule_versions"] == before


@pytest.mark.parametrize("response", [
    {"choices": []},
    {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
    {"choices": [{"message": {"content": "not json"}}]},
])
def test_malformed_provider_reply_is_rejected_by_route(monkeypatch, response):
    class Client:
        def chat_sync(self, *_args, **_kwargs):
            return response
    monkeypatch.setattr(generation, "build_qwen_runtime_client", lambda *_: Client())
    result = TestClient(app).post(BASE, headers=HEADERS, json={"nodeId": 16, "description": "rule"}).json()
    assert result["code"] != 0


@pytest.mark.parametrize("value,applicable,expected", [(10, True, "pass"), (9, True, "fail"),
                                                     (None, True, "evidence_insufficient"),
                                                     (None, False, "not_applicable")])
def test_generated_condition_uses_existing_four_state_trial(value, applicable, expected):
    from libs.rule_conditions import evaluate_conditions
    suggestion = deepcopy(SUGGESTION)
    conditions = suggestion["draft"]["executionConditions"]
    conditions["applicability"] = {"id": "required", "field": "required", "operator": "eq", "expected": True}
    generation.validate_suggestion(suggestion)
    assert evaluate_conditions(conditions, {
        "required": {"value": applicable, "evidenceRefs": ["DESIGN-1"]},
        "thickness": {"value": value, "unit": "mm", "evidenceRefs": ["MEASURE-1"]},
    })["result"] == expected
