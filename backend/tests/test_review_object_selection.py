"""一張記錄表多個對象：列出候選、由監檢員指定、凍結進審查。"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api import review_input_selection as selection
from libs.business_pack import load_business_pack
from libs.review_object_selection import collect_object_candidates, validated_selected_object_ids
from libs.review_orchestrator import execution as ex
from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
from tests.test_form_tables import GROUNDING_PAGE


def _state():
    return {"documents": [{"id": "D", "projectId": "P", "tenantId": "T", "fileName": "交工资料.pdf"}],
            "versions": [{"id": "V", "documentId": "D", "tenantId": "T"}],
            "ocr_parse_results": [{"id": "O", "documentVersionId": "V", "tenantId": "T", "status": "success",
                                   "fragments": GROUNDING_PAGE, "tables": []}]}


def _run(**extra):
    return {"projectId": "P", "tenantId": "T", "nodeId": 47, "reviewMode": "formal",
            "inputDocumentVersionIds": ["V"], "reviewRunId": "RUN", **extra}


def test_a_record_with_two_pipelines_lists_both_as_candidates_with_their_page():
    facts = NDT_FACT_BUILDERS[47](_state(), _run())
    grounding = facts["r47"]["staticGrounding"]
    assert grounding["domains"] == [] and grounding["sourceIssues"] == ["r47_source_object_conflict"]
    assert collect_object_candidates(facts) == [
        {"objectId": "PL8303-100", "objectType": "pipeline", "documentVersionId": "V", "pageNo": 16},
        {"objectId": "PL8306-100", "objectType": "pipeline", "documentVersionId": "V", "pageNo": 16}]


def test_a_selected_pipeline_is_reviewed_alone_and_lists_no_candidates():
    facts = NDT_FACT_BUILDERS[47](_state(), _run(selectedObjectIds=["PL8306-100"]))
    assert [row["objectId"] for row in facts["r47"]["staticGrounding"]["domains"]] == ["PL8306-100"]
    assert collect_object_candidates(facts) == []


@pytest.mark.parametrize("value", [None, [], "PL8303-100", [""], ["A", "A"], [1], ["x" * 121], ["O"] * 21])
def test_selected_objects_must_be_a_short_list_of_distinct_ids(value):
    with pytest.raises(ValueError):
        validated_selected_object_ids(value)


@pytest.fixture
def input_selection(monkeypatch):
    state = {"versions": [{"id": "V", "documentId": "D", "tenantId": "T"}],
             "documents": [{"id": "D", "currentVersionId": "V"}], "node_evidence_links": []}
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    monkeypatch.setattr(selection, "actor_visible_evidence_repository", lambda *args: SimpleNamespace(state=deepcopy(state)))
    monkeypatch.setattr(selection, "build_node_evidence_readiness", lambda *args: {"readyForFormalReview": False})
    return SimpleNamespace(tenant_id_for_record=lambda row: row.get("tenantId"), request_tenant_id=lambda _: "T",
                           document_body_uploaded=lambda *args: True)


def test_input_selection_records_the_chosen_objects(input_selection):
    _versions, readiness = selection.resolve_review_input_selection(
        input_selection, None, "P", 47, {"inputDocumentVersionIds": ["V"], "selectedObjectIds": [" PL8303-100 "]})
    assert readiness["inputSelection"]["selectedObjectIds"] == ["PL8303-100"]


@pytest.mark.parametrize(("body", "reason"), [
    ({"selectedObjectIds": ["PL8303-100"]}, "明确指定本次文件版本"),
    ({"inputDocumentVersionIds": ["V"], "selectedObjectIds": []}, "审查对象"),
    ({"inputDocumentVersionIds": ["V"], "selectedObjectIds": ["A"], "conditionObjectMapping": {}}, "不能同时"),
])
def test_invalid_object_selection_is_refused(input_selection, body, reason):
    with pytest.raises(selection.ReviewInputSelectionError, match=reason):
        selection.resolve_review_input_selection(input_selection, None, "P", 47, body)


def test_selected_objects_are_frozen_into_the_run_and_its_input_hash(monkeypatch):
    pack = load_business_pack("engineering_inspection_v1")
    state = {"review_runs": [], "ocr_parse_results": []}
    monkeypatch.setattr(ex, "repo", SimpleNamespace(state=state, clone=deepcopy, find_one=lambda *_a, **_k: None,
                                                    require_project=lambda _: {"id": "P", "businessPackSnapshot": pack}))
    for name in ("ensure_review_state", "seed_graph_nodes", "append_review_event",
                 "bind_evidence_package_to_review_run", "freeze_review_run_clause_snapshot", "flush_state_records"):
        monkeypatch.setattr(ex, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(ex, "review_run_state_records", lambda _: {})
    monkeypatch.setattr(ex, "existing_scoped_run", lambda *args, **kwargs: None)
    monkeypatch.delenv("AICHECK_WORKSTATIONS_ENABLED", raising=False)
    base = {"id": "AI-T", "projectId": "P", "nodeId": 47, "tenantId": "T", "businessPackId": pack["id"],
            "inputDocumentVersionIds": ["V"]}
    plain = ex.create_review_run_from_ai_run(dict(base), mode="inline")
    chosen = ex.create_review_run_from_ai_run({**base, "selectedObjectIds": ["PL8303-100"]}, mode="inline")
    other = ex.create_review_run_from_ai_run({**base, "selectedObjectIds": ["PL8306-100"]}, mode="inline")
    assert "selectedObjectIds" not in plain and chosen["selectedObjectIds"] == ["PL8303-100"]
    assert len({plain["inputHash"], chosen["inputHash"], other["inputHash"]}) == 3
