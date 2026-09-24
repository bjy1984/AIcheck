"""Jev 在审查提示词里只是分歧提示：不能让草稿以 Jev 的选择为节点建议。"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from libs.business_pack import load_business_pack
from libs.review_orchestrator import execution as ex


def _requirements(monkeypatch, jev_status, *, selected=True):
    state = {"ocr_parse_results": [{"documentVersionId": "V", "status": "success",
                                    "fragments": [{"pageNo": 1, "text": "焊接工艺卡"}]}]}
    run = {"projectId": "P", "nodeId": 16, "inputDocumentVersionIds": ["V"],
           "jevDecision": {"status": jev_status, "atomic": [
               {"atomicCheckId": "AC-1", "choice": "failed", "confidence": 0.93}]},
           "reviewPluginSnapshot": {"jev": {"enabled": selected, "source": "project_setting"}}}
    monkeypatch.setattr(ex, "repo", SimpleNamespace(state=state, clone=deepcopy))
    monkeypatch.setattr(ex, "select_prompt_template", lambda _: None)
    monkeypatch.setattr(ex, "build_ai_review_prompt", lambda *args, **kwargs: {
        "system": "Review", "user": "{{reviewTaskJson}}", "template": {}})
    monkeypatch.setattr(ex, "audit_runtime_public_config", lambda **kwargs: {})
    monkeypatch.setattr(ex.checklist_mode, "checklist_enabled", lambda: False)
    context = {"project": {"businessPackSnapshot": load_business_pack("engineering_inspection_v1")},
               "auditRuntime": {"mode": "structured"},
               "ruleResults": [{"ruleId": "R16", "atomicCheckResults": [
                   {"atomicCheckId": "AC-1", "result": "passed"}]}]}
    payload = ex.build_review_prompt_parts(run, context)["userPayload"]
    return payload, "\n".join(item for item in payload["requirements"] if isinstance(item, str))


def test_completed_jev_is_described_as_a_disagreement_hint_only(monkeypatch):
    payload, text = _requirements(monkeypatch, "completed")
    assert payload["jevDecision"]["atomic"][0]["choice"] == "failed"
    assert "分歧提示" in text and "以规则工具结果" in text
    assert "由 Jev" not in text and "不得改写 Jev" not in text


@pytest.mark.parametrize("status", ["disabled", "unavailable"])
def test_no_jev_instruction_without_a_completed_decision(monkeypatch, status):
    payload, text = _requirements(monkeypatch, status)
    assert "jevDecision" not in payload
    assert "Jev" not in text


def test_a_run_that_did_not_select_the_jev_plugin_never_mentions_jev(monkeypatch):
    payload, text = _requirements(monkeypatch, "completed", selected=False)
    assert "jevDecision" not in payload
    assert "Jev" not in text
