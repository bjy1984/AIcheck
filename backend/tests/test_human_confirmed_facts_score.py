"""人核过的字段要有分，否则人核一百次系统也不记得。

证书节点现在落在「需人工判断」，原因是 MinerU 通道的字段没有置信度。监检在界面上核对了引文，
这个确认必须落回事实：fact_corrections 打补丁时给 1.0，下次跑 grounding 就是有分的。
同时逐项核查结果要把「没分的事实」和它们引用的抽取字段列出来，界面才有东西可核。
"""
from __future__ import annotations

from libs.review_input_data import apply_field_corrections_to_parse_results
from libs.review_orchestrator.certificate_facts import build_certificate_facts
from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding
from libs.review_orchestrator.output_contract import atomic_check_outcomes


def _state(*, corrected: bool) -> dict:
    state = {
        "documents": [{"id": "DOC-1", "projectId": "P-1", "currentVersionId": "DV-1",
                       "fileName": "设计资质.png", "materialTypeCode": "design_license"}],
        "versions": [{"id": "DV-1", "documentId": "DOC-1"}],
        "projects": [{"id": "P-1"}],
        "ocr_parse_results": [{
            "documentVersionId": "DV-1", "status": "success", "profileId": "qualification_certificate_v1",
            "quality": {"reasons": ["provider_confidence_unavailable"]},
            "fields": [
                {"fieldCode": "certificate_no", "fieldName": "许可证编号", "fieldValue": "TS1844171-2028", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.0},
                {"fieldCode": "valid_until", "fieldName": "有效期至", "fieldValue": "2028年1月17日", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.0},
            ],
            "fragments": [],
        }],
        "fact_corrections": [],
    }
    if corrected:
        state["fact_corrections"].append({
            "id": "FCOR-1", "status": "active", "projectId": "P-1", "nodeId": 1, "fieldId": "FIELD-DV-1-1",
            "fieldName": "许可证编号", "documentVersionId": "DV-1", "correctedValue": "TS1844171-2028", "reason": "人工核对无误",
        })
    return state


def _run() -> dict:
    return {"projectId": "P-1", "nodeId": 1, "inputDocumentVersionIds": ["DV-1"]}


def test_人核过的字段打补丁后有分且不再受引擎影响():
    state = _state(corrected=True)
    patched = apply_field_corrections_to_parse_results(state, state["ocr_parse_results"], context={"reviewRun": _run()})
    field = next(item for item in patched[0]["fields"] if item["fieldName"] == "许可证编号")
    assert field["humanCorrected"] is True and field["confidence"] == 1.0 and field["confidenceUnavailable"] is False
    untouched = next(item for item in patched[0]["fields"] if item["fieldName"] == "有效期至")
    assert untouched["confidence"] == 0.0 and "humanCorrected" not in untouched


def test_人核过的证据进judgment后grounding能通过():
    facts = build_certificate_facts(_state(corrected=True), "P-1", 1, ["DV-1"], review_run=_run())
    cert = facts["certificateFacts"]["certificates"][0]
    corrected = [item for item in cert["evidence"] if item.get("humanCorrected")]
    assert corrected and corrected[0]["fieldName"] == "许可证编号" and corrected[0]["confidence"] == 1.0
    # 有效期那条没核过，仍是没分；事实整体按最弱一环算，所以还是 unscored——
    # 但字段清单里能看出来哪条核过、哪条没核。
    fact = facts["judgment"]["claimedFacts"][0]
    assert {(item["fieldName"], item["humanCorrected"]) for item in fact["fields"]} == {("许可证编号", True), ("有效期至", False)}

    # 两条都核过 → 有分 → grounding 通过。
    state = _state(corrected=True)
    state["fact_corrections"].append({
        "id": "FCOR-2", "status": "active", "projectId": "P-1", "nodeId": 1, "fieldId": "FIELD-DV-1-2",
        "fieldName": "有效期至", "documentVersionId": "DV-1", "correctedValue": "2028年1月17日",
    })
    facts = build_certificate_facts(state, "P-1", 1, ["DV-1"], review_run=_run())
    out = validate_evidence_grounding({"facts": facts["judgment"]["claimedFacts"], "evidenceRefs": facts["judgment"]["evidenceRefs"], "minConfidence": 0.75})
    assert out["result"] == "passed"


def test_逐项核查结果带出没分的事实和它引用的字段():
    facts = build_certificate_facts(_state(corrected=False), "P-1", 1, ["DV-1"], review_run=_run())
    grounding = validate_evidence_grounding({"facts": facts["judgment"]["claimedFacts"], "evidenceRefs": facts["judgment"]["evidenceRefs"], "minConfidence": 0.75})
    assert grounding["result"] == "human_review_required"
    outcomes = atomic_check_outcomes(
        [{"reviewRunId": "R", "ruleCode": "r01", "atomicCheckResults": [
            {"atomicCheckId": "AC-R01-02", "result": "human_review_required", "toolResults": [grounding]},
            # 同一次 grounding 会挂在这个节点的每个原子项上；只有「需人工判断」那条列得出来。
            {"atomicCheckId": "AC-R01-03", "result": "failed", "toolResults": [grounding]},
        ]}],
        {"businessPackId": "engineering_inspection_v1"},
    )
    assert outcomes[1]["unscoredFacts"] == []
    unscored = outcomes[0]["unscoredFacts"]
    assert len(unscored) == 1
    assert unscored[0]["value"] == "TS1844171-2028"
    assert {item["fieldName"] for item in unscored[0]["fields"]} == {"许可证编号", "有效期至"}
    assert all(item["documentVersionId"] == "DV-1" for item in unscored[0]["fields"])
