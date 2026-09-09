"""P8 H5 清单填表模式：结构由代码给，模型只填 verdict/note，肯定结论词只在代码标题里。"""

from __future__ import annotations

import json

import pytest

from libs.business_pack import load_business_pack
from libs.integrations.errors import IntegrationServiceError
from libs.review_grounding import apply_grounding_guardrails
from libs.review_orchestrator import checklist_mode
from libs.review_orchestrator import execution as ex

PACK = load_business_pack("engineering_inspection_v1")


def _node_24() -> dict:
    for value in PACK.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict) and int(item.get("nodeId") or 0) == 24 and item.get("requiredMaterials"):
                return item
    raise AssertionError("业务包里找不到带 requiredMaterials 的节点 24")


def _items() -> list[dict]:
    return checklist_mode.build_checklist_items(PACK, 24, _node_24().get("requiredMaterials") or [])


def _grounding_input() -> dict:
    return {
        "groundingStatus": "grounded",
        "documentVersionIds": ["DV-1"],
        "evidenceTextCorpus": ["姓名 姜军 项目代号 GTAW-FeⅡ-6G-3/57 有效期至 2026-12-25"],
        "fragments": [{"id": "FRAG-1", "documentVersionId": "DV-1", "text": "姓名 姜军 项目代号 GTAW-FeⅡ-6G-3/57 有效期至 2026-12-25", "pageNo": 1, "bbox": [1, 1, 9, 9]}],
        "fields": [],
        "tables": [],
        "seals": [],
        "evidenceLinks": [{"id": "EVL-1", "documentVersionId": "DV-1", "pageNo": 1, "bbox": [1, 1, 9, 9], "quotedText": "姜军"}],
        "reviewMode": "gap_precheck",
    }


def _base() -> dict:
    return {"findingType": "ai_review_suggestion", "severity": "medium", "title": "AI 证据化审查草稿", "description": "草稿", "confidence": 0.5, "groundingStatus": "insufficient_evidence"}


def _normalize(content: str, items: list[dict], review_run: dict | None = None):
    run = review_run if review_run is not None else {}
    return checklist_mode.normalize_checklist_output(
        run,
        {"checklistItems": items},
        content,
        base=_base(),
        grounding_input=_grounding_input(),
        guard=apply_grounding_guardrails,
        clone=lambda value: json.loads(json.dumps(value)),
        bounded_confidence=ex.bounded_confidence,
    )


def test_checklist_items_come_from_node_atomic_checks_and_required_materials() -> None:
    items = _items()
    ids = [item["itemId"] for item in items]
    assert "AC-R24-01" in ids and "AC-R24-05" in ids
    assert "REQ-24-01" in ids, "焊工资格证（必传）进清单"
    assert "REQ-24-02" not in ids, "焊工名册已降为可选（N-34），不进清单"
    first = next(item for item in items if item["itemId"] == "AC-R24-01")
    assert first["ruleCode"] == "engineering-inspection-r24" and first["severity"] == "medium"
    assert first["question"].startswith("焊工资格证及持证合格项目·证书有效性和核验来源：")


def test_payload_switches_task_schema_and_requirements() -> None:
    payload = checklist_mode.apply_to_payload(
        {"task": "Generate ReviewFindingDraftList JSON only.", "requirements": ["a"], "outputSchema": {"findings": [{"evidenceRefs": [{"evidenceLinkId": "string"}]}]}},
        _items(),
    )
    assert payload["promptMode"] == "checklist"
    assert "checklist" in payload["outputSchema"] and "extraFindings" in payload["outputSchema"]
    assert payload["checklist"][0]["itemId"] == "AC-R24-01"
    assert payload["requirements"][0] == "a" and any("清单填表" in item for item in payload["requirements"])


def test_findings_are_assembled_by_code_with_rule_severity_and_verdict_titles() -> None:
    items = _items()
    content = json.dumps(
        {
            "checklist": [
                {"itemId": "AC-R24-02", "verdict": "不符合", "evidenceRefs": [{"evidenceLinkId": "EVL-1", "documentVersionId": "DV-1", "pageNo": 1, "bbox": [1, 1, 9, 9]}], "note": "证书项目代号 GTAW-FeⅡ-6G-3/57 与工艺卡要求的方法不一致，请补正。"},
                {"itemId": "AC-R24-04", "verdict": "不符合", "evidenceRefs": [{"evidenceLinkId": "EVL-1", "documentVersionId": "DV-1", "pageNo": 1, "bbox": [1, 1, 9, 9]}], "note": "证书 TS7777777-2031 厚度范围 0-6mm 不覆盖 12mm，符合要求的仅 3 人。"},
                {"itemId": "AC-R24-01", "verdict": "符合", "evidenceRefs": [{"evidenceLinkId": "EVL-1", "documentVersionId": "DV-1", "pageNo": 1, "bbox": [1, 1, 9, 9]}], "note": "证书有效期至 2026-12-25。"},
                {"itemId": "AC-R24-03", "verdict": "符合", "evidenceRefs": [], "note": "看不出位置。"},
                {"itemId": "NOT-AN-ITEM", "verdict": "符合", "evidenceRefs": [], "note": ""},
            ],
            "extraFindings": [{"title": f"额外 {index}", "description": "清单外问题", "severity": "low"} for index in range(5)],
        },
        ensure_ascii=False,
    )
    run: dict = {}
    drafts = _normalize(content, items, run)
    by_item = {draft.get("checklistItemId"): draft for draft in drafts if draft.get("checklistItemId")}
    failed = by_item["AC-R24-02"]
    assert failed["severity"] == "medium" and failed["suggestedAction"] == "request_correction"
    assert failed["findingType"] == "checklist_fail"
    assert failed["title"].endswith("：不符合")
    passed = by_item["AC-R24-01"]
    assert passed["groundingStatus"] == "grounded", passed.get("unsupportedClaims")
    assert passed["title"].endswith("：符合"), "肯定结论词只在代码标题里，守卫不核对它"
    assert passed["severity"] == "low"
    # note 里写了证据中没有的证书号：守卫照常降级，动作回到人工确认——清单模式不给模型开后门
    downgraded = by_item["AC-R24-04"]
    assert downgraded["groundingStatus"] == "insufficient_evidence"
    assert downgraded["suggestedAction"] == "human_confirm"
    assert downgraded["modelTitle"].endswith("：不符合"), "代码标题留作原文，模板标题照旧"
    no_evidence = by_item["AC-R24-03"]
    assert no_evidence["checklistVerdict"] == "证据不足", "没有证据的“符合”不成立"
    assert no_evidence["groundingStatus"] == "insufficient_evidence"
    extras = [draft for draft in drafts if draft.get("checklistExtra")]
    assert len(extras) == checklist_mode.MAX_EXTRA_FINDINGS
    assert run["llmMetadata"]["checklistSummary"]["unknownItems"] == 1
    assert run["llmMetadata"]["checklistSummary"]["不符合"] == 2


def test_missing_checklist_key_is_an_envelope_error() -> None:
    with pytest.raises(IntegrationServiceError) as error:
        _normalize(json.dumps({"findings": []}), _items())
    assert error.value.reason == "LLM_OUTPUT_INVALID_ENVELOPE"


def test_mode_defaults_to_freeform_and_normalizer_dispatches_only_when_enabled(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_REVIEW_PROMPT_MODE", raising=False)
    assert checklist_mode.review_prompt_mode() == "freeform"
    monkeypatch.setenv("AICHECK_REVIEW_PROMPT_MODE", "checklist")
    assert checklist_mode.checklist_enabled() is True
    called: list = []
    monkeypatch.setattr(ex, "build_finding_draft", lambda _run, _ctx: _base())
    monkeypatch.setattr(ex, "grounding_input_with_supplements", lambda _ctx: _grounding_input())
    monkeypatch.setattr(ex.checklist_mode, "normalize_checklist_output", lambda *args, **kwargs: called.append(1) or [])
    assert ex.normalize_llm_findings({}, {"checklistItems": [{"itemId": "X"}]}, '{"checklist": []}') == []
    assert called == [1]


def test_complete_checklist_retains_extras_beyond_legacy_limit():
    content = json.dumps({"checklist": [], "extraFindings": [
        {"title": f"独立问题 {i}", "description": "待核对", "evidenceRefs": []} for i in range(7)
    ]})
    run = {}
    drafts = checklist_mode.normalize_checklist_output(
        run, {"checklistItems": _items()}, content, base=_base(), grounding_input=_grounding_input(),
        guard=lambda drafts, _: drafts, clone=lambda value: json.loads(json.dumps(value)),
        bounded_confidence=ex.bounded_confidence, complete=True,
    )
    assert len([draft for draft in drafts if draft.get("checklistExtra")]) == 7
    assert run["llmMetadata"]["checklistSummary"]["extraFindings"] == 7
    payload = checklist_mode.apply_to_payload({}, [], complete=True)
    assert "最多 3 条" not in str(payload["requirements"])


def test_condition_checklist_replaces_only_mapped_instructions_and_keeps_requirements():
    from copy import deepcopy

    rule = {"id": "CUSTOM", "version": "v2", "nodeIds": [24], "businessPackId": PACK["id"],
            "executionConditions": {"schemaVersion": "rule-conditions-v1", "checks": [
                {"id": "C", "atomicCheckId": "AC-R24-01", "field": "thickness", "operator": "gte", "expected": 10}]}}
    original = deepcopy(rule)
    before = _items()
    after = checklist_mode.build_checklist_items(PACK, 24, _node_24().get("requiredMaterials"), effective_rule=rule)
    assert [item["itemId"] for item in after] == [item["itemId"] for item in before]
    assert after[0]["question"] != before[0]["question"]
    assert [row["question"] for row in after[1:]] == [row["question"] for row in before[1:]]
    assert all(row["ruleSetVersion"] == "v2" for row in after if row["kind"] == "atomic_check")
    payload = checklist_mode.apply_to_payload({}, after)
    assert any("不得使用旧原子项门槛" in item for item in payload["requirements"])
    after[0]["conditionReplacement"]["checks"][0]["expected"] = 99
    assert rule == original
    with pytest.raises(ValueError, match="node_mismatch"):
        checklist_mode.build_checklist_items(PACK, 25, effective_rule=rule)
