"""这一层的价值全在挡得住编造，所以测试主要在测它挡不挡得住。"""

import json

import pytest

from libs.review_orchestrator.domain_judgment_agent import (
    assign_paths,
    build_messages,
    declared_paths,
    parse_response,
    raw_page_text,
)

SPEC = {
    "requiredPaths": ["certificate.documentNo"],
    "checks": [
        {
            "code": "certificates_and_marks_reviewed",
            "actualPath": "certificate.certificatesAndMarksReviewed",
            "operator": "equals",
            "expected": True,
            "sourceClause": "GB/T 20801.1-2025 8.5",
        },
        {
            "code": "grade_matches",
            "actualPath": "certificate.gradeMatchesSpecification",
            "operator": "equals",
            "expected": True,
            "applicabilityPath": "certificate.applies",
        },
    ],
}
PARSE_RESULTS = [
    {
        "documentVersionId": "DV-1",
        "fragments": [
            {"pageNo": 1, "text": "检查人员已审阅合格证、质量证明书与标记，"},
            {"pageNo": 1, "text": "确认材料均为规定等级。"},
            {"pageNo": 2, "text": "无关内容"},
        ],
    }
]
ALLOWED = {"DV-1"}


def response(fields):
    return json.dumps({"fields": fields}, ensure_ascii=False)


def field(path, value, quote, version="DV-1", page=1):
    return {
        "path": path,
        "value": value,
        "documentVersionId": version,
        "pageNo": page,
        "quotedText": quote,
    }


def test_declared_paths_cover_required_actual_and_applicability():
    paths = declared_paths(SPEC)
    assert set(paths) == {
        "certificate.documentNo",
        "certificate.certificatesAndMarksReviewed",
        "certificate.gradeMatchesSpecification",
        "certificate.applies",
    }
    assert paths["certificate.certificatesAndMarksReviewed"]["kind"] == "boolean"
    assert paths["certificate.applies"]["kind"] == "boolean"


def test_a_quoted_value_is_accepted():
    out = parse_response(
        response([field("certificate.certificatesAndMarksReviewed", True, "已审阅合格证、质量证明书与标记")]),
        SPEC,
        PARSE_RESULTS,
        allowed_document_version_ids=ALLOWED,
    )
    assert out["values"] == {"certificate.certificatesAndMarksReviewed": True}
    assert out["evidenceRefs"][0]["pageNo"] == 1
    assert out["rejected"] == []


def test_a_quotation_that_is_not_in_the_page_is_refused():
    """编造的引用要被机械挡掉，不能靠模型自律。"""
    out = parse_response(
        response([field("certificate.certificatesAndMarksReviewed", True, "本项目全部材料均已复验合格")]),
        SPEC,
        PARSE_RESULTS,
        allowed_document_version_ids=ALLOWED,
    )
    assert out["values"] == {}
    assert out["rejected"][0]["reason"] == "quotation_not_found_in_page"


def test_a_quotation_from_the_wrong_page_is_refused():
    out = parse_response(
        response([field("certificate.certificatesAndMarksReviewed", True, "已审阅合格证", page=2)]),
        SPEC,
        PARSE_RESULTS,
        allowed_document_version_ids=ALLOWED,
    )
    assert out["values"] == {}
    assert out["rejected"][0]["reason"] == "quotation_not_found_in_page"


def test_a_value_with_no_quotation_is_refused():
    out = parse_response(
        response([field("certificate.certificatesAndMarksReviewed", True, "  ")]),
        SPEC,
        PARSE_RESULTS,
        allowed_document_version_ids=ALLOWED,
    )
    assert out["rejected"][0]["reason"] == "value_without_quotation"


def test_evidence_from_a_document_outside_the_run_is_refused():
    out = parse_response(
        response([field("certificate.certificatesAndMarksReviewed", True, "已审阅合格证", version="DV-OTHER")]),
        SPEC,
        PARSE_RESULTS,
        allowed_document_version_ids=ALLOWED,
    )
    assert out["rejected"][0]["reason"] == "evidence_outside_selected_documents"


def test_a_path_the_criteria_never_declared_is_dropped():
    out = parse_response(
        response([field("certificate.somethingInvented", True, "已审阅合格证")]),
        SPEC,
        PARSE_RESULTS,
        allowed_document_version_ids=ALLOWED,
    )
    assert out["values"] == {}
    assert out["rejected"][0]["reason"] == "path_not_declared_by_criteria"


def test_a_boolean_field_answered_with_prose_is_refused():
    out = parse_response(
        response([field("certificate.certificatesAndMarksReviewed", "是", "已审阅合格证")]),
        SPEC,
        PARSE_RESULTS,
        allowed_document_version_ids=ALLOWED,
    )
    assert out["rejected"][0]["reason"] == "boolean_field_got_non_boolean"


def test_leaving_a_field_null_is_allowed_and_silent():
    """留空是被鼓励的，不该被记成拒绝。"""
    out = parse_response(
        response([field("certificate.certificatesAndMarksReviewed", None, "")]),
        SPEC,
        PARSE_RESULTS,
        allowed_document_version_ids=ALLOWED,
    )
    assert out["values"] == {} and out["rejected"] == []


def test_a_non_json_reply_does_not_crash_the_run():
    out = parse_response("抱歉，我无法回答", SPEC, PARSE_RESULTS, allowed_document_version_ids=ALLOWED)
    assert out["values"] == {}
    assert out["rejected"][0]["reason"] == "response_not_json"


@pytest.mark.parametrize(
    "quote", ["已审阅合格证 、 质量证明书", "已审阅合格证、质量证明书", "已审阅合格证、质量证明书"]
)
def test_whitespace_and_fullwidth_differences_do_not_break_a_real_quotation(quote):
    out = parse_response(
        response([field("certificate.certificatesAndMarksReviewed", True, quote)]),
        SPEC,
        PARSE_RESULTS,
        allowed_document_version_ids=ALLOWED,
    )
    assert out["values"] == {"certificate.certificatesAndMarksReviewed": True}


def test_the_prompt_never_asks_the_model_for_a_verdict():
    messages = build_messages("materialCertificate", SPEC, [{"documentVersionId": "DV-1", "pageNo": 1, "text": "x"}])
    system = messages[0]["content"]
    assert "不要下" in system and "结论" in system
    # 判定用词不该出现在要模型填的字段里。
    body = messages[1]["content"]
    assert "passed" not in body and "failed" not in body


def test_paths_become_the_nested_shape_the_criteria_read():
    row = assign_paths({"certificate.documentNo": "X1", "certificate.applies": True})
    assert row == {"certificate": {"documentNo": "X1", "applies": True}}


def test_the_text_shown_to_the_model_keeps_its_whitespace():
    """第一次真实调用六个字段全 null：给模型的正文被归一化吃掉空白，编号黏成一串。"""
    text = raw_page_text(PARSE_RESULTS, "DV-1", 1)
    assert "检查人员已审阅合格证、质量证明书与标记，\n确认材料均为规定等级。" == text
    # 比对用的归一化形态是另一回事
    assert " " not in __import__("libs.review_orchestrator.domain_judgment_agent", fromlist=["page_text"]).page_text(PARSE_RESULTS, "DV-1", 1)


def test_the_prompt_names_the_object_and_the_column_labels():
    """一页列六个元件；不说是哪一个，documentNo 就没有答案。"""
    messages = build_messages(
        "materialCertificate", SPEC, [{"documentVersionId": "DV-1", "pageNo": 1, "text": "x"}],
        object_scope={"objectId": "20260213951", "knownValues": {"certificate.documentNo": "20260213951"}},
        labels={"certificate.documentNo": "产品质量证明书编号"},
    )
    assert "只针对那一个对象" in messages[0]["content"]
    body = json.loads(messages[1]["content"])
    assert body["objectScope"]["objectId"] == "20260213951"
    # 表格已读出的 documentNo 不再问模型；其余路径仍在，且带中文列名（若有）
    paths = {f["path"] for f in body["fields"]}
    assert "certificate.documentNo" not in paths
    assert "certificate.certificatesAndMarksReviewed" in paths


def test_without_scope_the_prompt_is_unchanged_in_shape():
    body = json.loads(build_messages("d", SPEC, [])[1]["content"])
    assert "objectScope" not in body and all("label" not in f for f in body["fields"])
