from copy import deepcopy

import pytest
from test_ndt_procedure_ocr_profile import source
from test_r39_facts import evaluate

from apps.ocr_service.service import enrich_parse_result
from libs.ocr.profiles import profile_for


def fixture():
    state = {"documents": [], "versions": [], "ocr_parse_results": []}
    common = ["检测单位：示例检测公司", "检测方法：PT"]
    for document, version, lines in (
        ("INS", "IV1", ["文件类型：操作指导书", "文件编号：PT-I-01", "版次：A", "引用规程编号：PT-P-01", "引用规程版本：B"]),
        ("PROC", "PV1", ["文件类型：工艺规程", "文件编号：PT-P-01", "版次：B"]),
    ):
        parsed = enrich_parse_result(source(*lines, *common), profile=profile_for("ndt_procedure_v1"),
            document_version_id=version, business_pack_id="engineering_inspection_v1", model_manifest={})
        parsed["tenantId"] = "T1"
        state["ocr_parse_results"].append(parsed)
        state["documents"].append({"id": document, "projectId": "P1", "tenantId": "T1"})
        state["versions"].append({"id": version, "documentId": document, "tenantId": "T1"})
    return state, {"projectId": "P1", "tenantId": "T1", "nodeId": 39, "inputDocumentVersionIds": ["IV1", "PV1"]}


@pytest.mark.parametrize("case,expected", [("pass", "passed"), ("different_revision", "failed"), ("missing", "evidence_insufficient"),
    ("low_confidence", "evidence_insufficient"), ("conflict", "evidence_insufficient"), ("different_name", "evidence_insufficient"),
    ("duplicate_field", "evidence_insufficient"), ("extra_file", "evidence_insufficient"), ("outside_project", "evidence_insufficient"),
    ("structured_conflict", "evidence_insufficient"), ("missing_quote", "evidence_insufficient"), ("unrelated_procedure", "evidence_insufficient")])
def test_ocr_enrichment_to_compiled_reference_tool(case, expected):
    state, review = fixture()
    procedure = state["ocr_parse_results"][1]
    field = next(row for row in procedure["fields"] if row["fieldCode"] == "procedure_revision")
    fragment = next(row for row in procedure["fragments"] if row["text"] == "版次：B")
    if case == "different_revision":
        field["fieldValue"] = "C"
        fragment["text"] = "版次：C"
    elif case == "missing": procedure["fields"].remove(field)
    elif case == "low_confidence": field["confidence"] = .1
    elif case == "conflict": field["qualityFlags"] = ["field_value_conflict"]
    elif case == "different_name":
        next(row for row in procedure["fields"] if row["fieldCode"] == "organization_name")["fieldValue"] = "另一公司"
        next(row for row in procedure["fragments"] if "示例检测公司" in row["text"])["text"] = "检测单位：另一公司"
    elif case == "duplicate_field": procedure["fields"].append(deepcopy(field))
    elif case == "extra_file": state["ocr_parse_results"].append(deepcopy(procedure))
    elif case == "outside_project": state["documents"][1]["projectId"] = "OTHER"
    elif case == "structured_conflict":
        procedure["tables"] = [{"tableId": "partial", "businessSchema": "ndt_reference_context", "pageNo": 1,
                                "structureConfidence": .95, "contentMarkdown": "Partial explicit context", "normalizedRows": [{"projectId": "OTHER"}]}]
    elif case == "missing_quote": procedure["fragments"].remove(fragment)
    elif case == "unrelated_procedure":
        next(row for row in procedure["fields"] if row["fieldCode"] == "procedure_no")["fieldValue"] = "OTHER"
        next(row for row in procedure["fragments"] if row["text"] == "文件编号：PT-P-01")["text"] = "文件编号：OTHER"
    before = deepcopy(state)
    facts, output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert output["result"] == expected, output
    assert state == before
    if case in {"pass", "different_revision"}:
        assert "organizationId" not in facts["r39"]["procedureReference"]["scope"]
        assert output["facts"]["identityMode"] == "exact_source_organization_name"
        assert output["facts"]["organizationIdentityVerified"] is False
        assert facts["r39"]["sourceValidation"]["procedureReference"]["result"] == "passed"
        assert all(ref.get("id") and ref["quotedText"] for ref in output["evidenceRefs"])
    from test_r39_node_plan import execute

    node = execute(state, review)
    tool = next(tool for item in node["atomicResults"] for tool in item["toolResults"] if tool["toolName"] == "evaluate_r39_procedure_reference")
    assert tool["result"] == expected
    assert node["result"] == ("failed" if case == "different_revision" else "evidence_insufficient")
