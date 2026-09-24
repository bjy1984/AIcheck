from __future__ import annotations

import pytest

from libs.review_orchestrator.deterministic_tools import (
    check_certificate_validity,
    check_design_license_scope,
)
from libs.review_orchestrator.jev_state import consistent_rule_checks, scoped_document_states


def _rule(atomic_id, code, passed, actual, expected):
    return {"atomicCheckResults": [{"atomicCheckId": atomic_id, "toolResults": [{
        "status": "succeeded", "result": "passed" if passed else "failed",
        "checks": [{"code": code, "passed": passed, "actual": actual, "expected": expected}],
    }]}]}


def _state():
    return {
        "documents": [
            {"id": "DOC-A", "projectId": "P-A", "fileName": "许可.pdf"},
            {"id": "DOC-B", "projectId": "P-B", "fileName": "他人工程.pdf"},
        ],
        "document_versions": [
            {"id": "V-A", "documentId": "DOC-A"},
            {"id": "V-B", "documentId": "DOC-B"},
        ],
        "ocr_parse_results": [
            {"documentVersionId": "V-A", "fragments": [{"pageNo": 1, "text": "许可范围 GC1"}]},
            {"documentVersionId": "V-B", "fragments": [{"pageNo": 1, "text": "姜军"}]},
        ],
    }


def test_conflicting_gc2_checks_are_both_excluded_from_verified_state():
    checks, conflicts = consistent_rule_checks([
        _rule("AC-R01-02", "scope_covers_GC2", True, ["", "GB1", "GB2", "GC1"], ["GC1", "GC2"]),
        _rule("AC-R01-03", "TS1844171:scope_covers_required", False,
              ["", "GB1", "GB2", "GC1"], ["GC2"]),
    ])
    assert checks == []
    assert conflicts == [{"factKey": "scope_covers:GC2", "atomicCheckIds": ["AC-R01-02", "AC-R01-03"]}]


def test_consistent_independent_checks_remain_available():
    checks, conflicts = consistent_rule_checks([
        _rule("A", "scope_covers_GC2", True, ["GC1"], ["GC1", "GC2"]),
        _rule("B", "scope_covers_required", True, ["GC1"], ["GC2"]),
        _rule("C", "valid_date", True, "2028-01-01", "2026-01-01"),
    ])
    assert [row["atomicCheckId"] for row in checks] == ["A", "B", "C"]
    assert conflicts == []


def test_gc1_covering_gc2_real_tool_results_do_not_conflict_in_jev_state():
    design_scope = check_design_license_scope({"licenseScopes": ["GC1"], "requiredPipelineGrades": ["GC2"]})
    certificate = check_certificate_validity({"certificateType": "design_license", "requiredScopes": ["GC2"],
                                              "referenceDate": "2026-09-23", "certificates": [{
                                                  "certificateNo": "TS-1", "validUntil": "2028-01-01", "scopes": ["GC1"]}]})
    assert design_scope["result"] == certificate["result"] == "passed"
    rows, conflicts = consistent_rule_checks([{"atomicCheckResults": [
        {"atomicCheckId": "AC-R01-02", "toolResults": [{"status": "succeeded", **design_scope}]},
        {"atomicCheckId": "AC-R01-03", "toolResults": [{"status": "succeeded", **certificate}]},
    ]}])
    assert conflicts == []
    assert any(row["code"] == "scope_covers_GC2" for row in rows)
    assert any(row["code"].endswith(":scope_covers_required") for row in rows)


def test_jev_state_uses_scoped_whole_document_and_rejects_foreign_project():
    state = _state()
    run = {"projectId": "P-A", "nodeId": 1, "inputDocumentVersionIds": ["V-A"]}
    results, conflicts, overlong = scoped_document_states(state, run, [])
    assert len(results) == 1
    assert "许可范围 GC1" in results[0]["state"]
    assert "姜军" not in results[0]["state"]
    assert not conflicts and not overlong
    with pytest.raises(ValueError, match="jev_document_outside_project"):
        scoped_document_states(state, {**run, "inputDocumentVersionIds": ["V-A", "V-B"]}, [])


def test_oversized_document_is_reported_without_truncation():
    state = _state()
    state["ocr_parse_results"][0]["fragments"][0]["text"] = "长" * 40_000
    run = {"projectId": "P-A", "nodeId": 1, "inputDocumentVersionIds": ["V-A"]}
    results, _, overlong = scoped_document_states(state, run, [])
    assert results == []
    assert overlong == ["V-A"]


def test_same_project_id_from_other_tenant_is_not_jev_input():
    state = _state()
    state["documents"][0]["tenantId"] = "TENANT-B"
    run = {"tenantId": "TENANT-A", "projectId": "P-A", "nodeId": 1,
           "inputDocumentVersionIds": ["V-A"]}
    with pytest.raises(ValueError, match="jev_document_outside_project"):
        scoped_document_states(state, run, [])


def test_duplicate_ocr_attempts_use_only_latest_whole_document():
    state = _state()
    old = state["ocr_parse_results"][0]
    old.update(id="OLD", createdAt="2026-08-01 10:00:00")
    state["ocr_parse_results"].append({
        "id": "NEW", "documentVersionId": "V-A", "status": "success",
        "createdAt": "2026-08-02 10:00:00",
        "fragments": [{"pageNo": 2, "text": "新版许可范围 GC2"}],
    })
    run = {"projectId": "P-A", "nodeId": 1, "inputDocumentVersionIds": ["V-A"]}

    documents, _, _ = scoped_document_states(state, run, [])

    assert len(documents) == 1
    assert "新版许可范围 GC2" in documents[0]["state"]
    assert "许可范围 GC1" not in documents[0]["state"]


@pytest.mark.parametrize("latest_status", ["failed", "needs_human_review"])
def test_latest_unusable_ocr_does_not_fall_back_to_stale_success(latest_status):
    state = _state()
    state["ocr_parse_results"][0].update(id="OLD", status="success", createdAt="2026-08-01 10:00:00")
    state["ocr_parse_results"].append({
        "id": "NEW", "documentVersionId": "V-A", "status": latest_status,
        "createdAt": "2026-08-02 10:00:00",
        "fragments": [{"pageNo": 2, "text": "尚未核实的新 OCR"}],
    })
    run = {"projectId": "P-A", "nodeId": 1, "inputDocumentVersionIds": ["V-A"]}

    documents, _, _ = scoped_document_states(state, run, [])

    assert documents[0]["hasOcrText"] is False
    assert documents[0]["ocrNotReady"] is True
    assert "许可范围 GC1" not in documents[0]["state"]
    assert "尚未核实的新 OCR" not in documents[0]["state"]
