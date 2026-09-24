"""evidence_validation 的三处误拒（评审指出），以及它们各自不能放过的情形。

- 结论写 ISO 日期、OCR 原文是「2028年9月6日」：同一个日期不能判成「证据里没有」。
- 结论点名的标准号是审查依据，出处是本条引用的知识条款，不是项目资料的引文。
- 公示平台的登记记录没有页码与 bbox，按来源与登记页地址认，不按文档坐标认。
"""
from __future__ import annotations

from copy import deepcopy

from libs.integrations.external_registry_queries import configured_cnse_origin
from libs.review_orchestrator.certificate_facts import certificate_evidence_links
from libs.review_orchestrator.certificate_platform_verify import _platform_evidence
from libs.review_orchestrator.evidence_ref_validation import validate_review_evidence_refs

ANCHOR = {"id": "EV-1", "documentId": "DOC-1", "documentVersionId": "V1", "pageNo": 2,
          "bbox": [10, 20, 80, 45], "quotedText": "有效期至 2028年9月6日 试验压力 1.6MPa"}
RUN = {"reviewRunId": "RR-1", "projectId": "P1", "tenantId": "T1", "inputDocumentVersionIds": ["V1"],
       "inputDocumentPageRanges": {"V1": {"start": 2, "end": 3}}}
STATE = {
    "documents": [{"id": "DOC-1", "projectId": "P1", "tenantId": "T1"}],
    "versions": [{"id": "V1", "documentId": "DOC-1"}],
    "retrieval_traces": [
        {"retrievalTraceId": "RT-1", "reviewRunId": "RR-1",
         "selectedClauses": [{"clauseId": "CL-1", "standardCode": "GB 50235-2010", "clauseNo": "8.6.2"},
                             {"clauseId": "CL-2", "standardCode": "GB 50184-2011", "clauseNo": "8.5.1"}]},
        {"retrievalTraceId": "RT-OTHER", "reviewRunId": "RR-OTHER",
         "selectedClauses": [{"clauseId": "CL-9", "standardCode": "GB 50235-2010"}]},
    ],
    "rule_check_results": [{"reviewRunId": "RR-1", "ruleCode": "R-PRESSURE", "linkedClauseIds": ["CL-1"]}],
}


def _validate(description, *, anchor=ANCHOR, state=STATE, run=RUN, **draft_fields):
    drafts = [{"title": "审查发现", "description": description, "evidenceRefs": [{"evidenceLinkId": anchor["id"]}],
               **deepcopy(draft_fields)}]
    result = validate_review_evidence_refs(drafts, [deepcopy(anchor)], review_run=deepcopy(run),
                                           source_state=deepcopy(state))
    return result, drafts


def _codes(result):
    return {item["code"] for item in result["failures"]}


# ---- 日期 ----

def test_iso_date_in_the_claim_matches_the_chinese_date_in_the_quote():
    assert _validate("证书有效期至 2028-09-06 ，覆盖施工期。")[0]["passed"] is True
    assert _validate("证书有效期至 2028.9.6 ，覆盖施工期。")[0]["passed"] is True
    padded = {**ANCHOR, "quotedText": "有效期至 2028年09月06日"}
    assert _validate("证书有效期至 2028-9-6 ，覆盖施工期。", anchor=padded)[0]["passed"] is True


def test_a_different_date_is_still_a_mismatch():
    result, _ = _validate("证书有效期至 2028-09-16 ，覆盖施工期。")
    assert "CLAIM_TO_EVIDENCE_MISMATCH" in _codes(result)
    assert "20280916" in result["failures"][0]["missingTokens"]


# ---- 标准号 ----

def test_standard_named_in_the_claim_is_checked_against_the_cited_clause():
    claim = "依据 GB 50235-2010 ，试验压力 1.6MPa 不足。"
    by_kb, _ = _validate(claim, kbRefs=[{"retrievalTraceId": "RT-1", "clauseIds": ["CL-1"]}])
    by_rule, _ = _validate(claim, ruleRefs=[{"ruleCode": "R-PRESSURE", "ruleSetVersion": "v1"}])
    assert by_kb["passed"] is True and by_rule["passed"] is True


def test_standard_not_backed_by_a_clause_of_this_run_is_still_a_mismatch():
    claim = "依据 GB 50235-2010 ，试验压力 1.6MPa 不足。"
    uncited, _ = _validate(claim)
    other_standard, _ = _validate(claim, kbRefs=[{"retrievalTraceId": "RT-1", "clauseIds": ["CL-2"]}])
    other_run, _ = _validate(claim, kbRefs=[{"retrievalTraceId": "RT-OTHER", "clauseIds": ["CL-9"]}])
    for result in (uncited, other_standard, other_run):
        assert "CLAIM_TO_EVIDENCE_MISMATCH" in _codes(result)
        assert result["failures"][0]["missingTokens"] == ["GB502352010"]


def test_clause_reference_does_not_ground_the_project_value():
    # 条款能证明标准号，证明不了项目资料里的数值。
    result, _ = _validate("依据 GB 50235-2010 ，试验压力 2.5MPa 不足。",
                          kbRefs=[{"retrievalTraceId": "RT-1", "clauseIds": ["CL-1"]}])
    assert result["failures"][0]["missingTokens"] == ["25MPA"]


# ---- 公示平台登记记录 ----

def _registry_anchor(**changes):
    evidence = _platform_evidence("V1", "安装许可证.pdf", "平台登记单位：示例管道安装有限公司；许可证编号：TS3844617-2026",
                                  f"{configured_cnse_origin()}/info-pub/pub")
    link = certificate_evidence_links({"certificates": [{"certificateNo": "TS3844617-2026",
                                                        "evidenceRefs": [{**evidence, "documentId": "DOC-1"}]}]})[0]
    return {**link, **changes}


def test_platform_registry_record_is_a_valid_anchor_without_page_coordinates():
    anchor = _registry_anchor()
    assert anchor["source"] == "cnse_platform" and anchor["pageNo"] == 0 and anchor["bbox"] is None
    result, drafts = _validate("许可证编号 TS3844617-2026 与平台登记一致。", anchor=anchor)
    assert result["passed"] is True
    assert drafts[0]["evidenceRefs"][0] == {
        "evidenceLinkId": anchor["id"], "documentId": "DOC-1", "documentVersionId": "V1", "pageNo": 0, "bbox": None,
        "quotedText": anchor["quotedText"], "source": "cnse_platform", "sourceUrl": anchor["sourceUrl"]}


def test_page_zero_anchor_that_is_not_a_genuine_registry_record_is_still_rejected():
    claim = "许可证编号 TS3844617-2026 与平台登记一致。"
    cases = [
        _registry_anchor(source=None),
        _registry_anchor(source="manual_upload"),
        _registry_anchor(sourceUrl="https://example.invalid/info-pub/pub"),
        _registry_anchor(sourceUrl=None),
        _registry_anchor(quotedText=""),
        _registry_anchor(bbox=[0, 0, 1, 1]),
        _registry_anchor(pageNo=5),
    ]
    for anchor in cases:
        assert "EVIDENCE_ANCHOR_NOT_LOCATABLE" in _codes(_validate(claim, anchor=anchor)[0]), anchor


def test_registry_record_still_has_to_belong_to_this_run_and_project():
    claim = "许可证编号 TS3844617-2026 与平台登记一致。"
    outside_run, _ = _validate(claim, anchor=_registry_anchor(documentVersionId="V2"))
    wrong_project, _ = _validate(claim, anchor=_registry_anchor(), state={
        **STATE, "documents": [{"id": "DOC-1", "projectId": "P2", "tenantId": "T1"}]})
    assert "EVIDENCE_REF_OUTSIDE_RUN" in _codes(outside_run)
    assert "EVIDENCE_ANCHOR_OUTSIDE_PROJECT" in _codes(wrong_project)
    # 登记记录没有页内位置，引用时自带的 bbox 是编的。
    drafts = [{"title": "", "description": claim,
               "evidenceRefs": [{"evidenceLinkId": _registry_anchor()["id"], "bbox": [1, 2, 3, 4]}]}]
    result = validate_review_evidence_refs(drafts, [_registry_anchor()], review_run=deepcopy(RUN),
                                           source_state=deepcopy(STATE))
    assert "EVIDENCE_REF_ANCHOR_MISMATCH" in _codes(result)
