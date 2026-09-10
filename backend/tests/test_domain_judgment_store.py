"""agent 的产出当作证据存取，事实构建不调模型——重放才不会飘。"""

import pytest

from libs.review_orchestrator.domain_judgment_store import (
    COLLECTION,
    judgment_for,
    merge_judgment,
)

KEY = {
    "projectId": "P1", "nodeId": 43, "domain": "materialCertificate",
    "objectId": "C1", "recordVersionId": "DV-1",
}


def judgment(**overrides):
    return {
        **KEY,
        "values": {"certificate.certificatesAndMarksReviewed": True},
        "evidenceRefs": [{"documentVersionId": "DV-1", "pageNo": 1, "quotedText": "已审阅"}],
        "rejected": [],
        **overrides,
    }


def state(rows):
    return {COLLECTION: rows}


_KWARGS = {
    "projectId": "project_id", "nodeId": "node_id", "domain": "domain",
    "objectId": "object_id", "recordVersionId": "record_version_id",
}


def lookup(rows, **overrides):
    wanted = {**KEY, **overrides}
    return judgment_for(state(rows), **{_KWARGS[key]: value for key, value in wanted.items()})


def test_a_judgment_is_found_when_all_five_keys_match():
    assert lookup([judgment()])["values"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("projectId", "P-OTHER"),
        ("nodeId", 44),
        ("domain", "coatingConstruction"),
        ("objectId", "C-OTHER"),
        ("recordVersionId", "DV-OTHER"),
    ],
)
def test_any_key_that_differs_means_no_match(field, value):
    """少比一项就可能把甲管线的结论安到乙管线头上。"""
    assert lookup([judgment(**{field: value})]) is None


def test_two_judgments_for_the_same_object_give_nothing():
    assert lookup([judgment(), judgment(values={})]) is None


def test_merging_adds_the_agent_value_to_the_row():
    row = {"objectId": "C1", "certificate": {"documentNo": "X1"}}
    merged = merge_judgment(row, judgment())
    assert merged["certificate"]["documentNo"] == "X1"
    assert merged["certificate"]["certificatesAndMarksReviewed"] is True


def test_a_value_the_table_already_supplied_is_not_overwritten():
    """表格是结构化原件；一次模型调用不能悄悄改写 OCR 抽出来的值。"""
    row = {"certificate": {"documentNo": "FROM-TABLE"}}
    merged = merge_judgment(row, judgment(values={"certificate.documentNo": "FROM-MODEL"}))
    assert merged["certificate"]["documentNo"] == "FROM-TABLE"


def test_the_agents_evidence_is_appended_not_replaced():
    row = {"evidenceRefs": [{"documentVersionId": "DV-1", "pageNo": 9}]}
    merged = merge_judgment(row, judgment())
    assert len(merged["evidenceRefs"]) == 2


def test_rejected_paths_are_kept_on_the_row():
    """模型答了但引用对不上，必须看得见，不能只留在日志里。"""
    rejected = [{"path": "certificate.gradeMatchesSpecification", "reason": "quotation_not_found_in_page"}]
    merged = merge_judgment({}, judgment(rejected=rejected))
    assert merged["judgmentRejections"] == rejected


def test_no_judgment_leaves_the_row_exactly_as_it_was():
    row = {"certificate": {"documentNo": "X1"}, "evidenceRefs": []}
    assert merge_judgment(row, None) == row


def test_merging_does_not_mutate_the_stored_judgment_or_the_row():
    row = {"certificate": {"documentNo": "X1"}}
    stored = judgment()
    merge_judgment(row, stored)["certificate"]["injected"] = True
    assert row == {"certificate": {"documentNo": "X1"}}
    assert "injected" not in str(stored)
