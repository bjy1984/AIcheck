"""四级签字（R04-03）：文件没挂到具体管线时，只在工程里确有管线会触发四级签字（或参数不全）才算「链接缺失」。

ECD202 储罐 4：拆页后选中的「管道材料等级代号说明」没有管线号，工程 10 条管线全是 GC2，
不会有哪条触发四级签字，文件挂哪条都不影响结论，原来却报证据不足。"""
from __future__ import annotations

import pytest

from libs.review_tools.business_tools import evaluate_design_document_approval

ROLES = ["设计", "校核", "审核", "审定"]


def run(pipelines: list[dict], *, covered: list[str] | None = None, roles: list[str] | None = None) -> dict:
    document = {"documentId": "GRADE-TABLE", "documentType": "pipeline_material_grade_table", "bodyUploaded": True,
                "signatureRoles": roles if roles is not None else ["设计", "校核", "审核"]}
    if covered is not None:
        document["coveredPipelineIds"] = covered
    return evaluate_design_document_approval({
        "approvalMode": "four_level_conditional", "targetDocumentTypes": ["pipeline_material_grade_table"],
        "requiredRoles": ROLES, "documents": [document], "pipelines": pipelines,
    })


def pipe(pipeline_id: str, grade: str, pressure=0.275, temperature=60.0) -> dict:
    return {"pipelineId": pipeline_id, "pipelineGrade": grade, "designPressureMPa": pressure, "designTemperatureC": temperature}


def test_unlinked_document_is_not_applicable_when_no_pipeline_can_trigger():
    out = run([pipe(f"A0{i}-PL-02", "GC2") for i in range(1, 9)] + [pipe("LP7103→ST7102", "GC2")])
    assert out["result"] == "not_applicable"
    assert out["documentResults"] == []


def test_gcd_below_every_threshold_does_not_trigger_either():
    out = run([pipe("P1", "GCD", pressure=3.9, temperature=600), pipe("P2", "GC3")])
    assert out["result"] == "not_applicable"


@pytest.mark.parametrize(
    "pipelines",
    [
        [pipe("P1", "GC1"), pipe("P2", "GC2")],
        [pipe("P1", "GCD", pressure=16.7), pipe("P2", "GC2")],
        [pipe("P1", "GC2"), {"pipelineId": "P2", "designPressureMPa": 1}],
        [pipe("P1", "GCD", pressure=None), pipe("P2", "GC2")],
        [pipe("P1", "GCD", pressure=4.0, temperature=None), pipe("P2", "GC2")],
    ],
)
def test_unlinked_document_still_needs_a_link_when_a_pipeline_could_trigger_or_is_incomplete(pipelines):
    out = run(pipelines)
    assert out["result"] == "evidence_insufficient"
    assert out["facts"]["reason"] == "document_pipeline_link_missing"


def test_linked_documents_are_judged_exactly_as_before():
    gc1 = [pipe("P1", "GC1"), pipe("P2", "GC2")]
    assert run(gc1, covered=["P1"])["result"] == "failed", "挂在 GC1 管线上，缺审定签字照旧不符合"
    assert run(gc1, covered=["P2"])["result"] == "not_applicable"
    assert run(gc1, covered=["P1"], roles=ROLES)["result"] == "passed"
