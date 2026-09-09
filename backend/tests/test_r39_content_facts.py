from copy import deepcopy

import pytest
from test_r39_content import arguments
from test_r39_facts import evaluate
from test_r39_facts import fixture as source_fixture


def fixture():
    state, run = source_fixture()
    body = arguments()

    def table(schema, records):
        rows = deepcopy(records)
        for row in rows:
            row["reviewedDocumentVersionId"] = row.pop("documentVersionId")
        return {"tableId": schema, "businessSchema": schema, "pageNo": 2, "structureConfidence": .95,
                "contentMarkdown": "Synthetic original document content", "normalizedRows": rows}

    state["ocr_parse_results"][0]["tables"].append(table("ndt_content_basis", [body["basis"]]))
    state["ocr_parse_results"][1]["tables"].extend([
        table("ndt_content_context", [body["scope"]]),
        table("ndt_content_inventory", [body["contentInventory"]]),
        table("ndt_content_fields", body["contentInventory"]["fields"])])
    return state, run


@pytest.mark.parametrize("case,expected", [("ok", "passed"), ("absent", "failed"), ("missing", "evidence_insufficient"),
    ("not_applicable", "not_applicable"), ("duplicate_context", "evidence_insufficient"),
    ("wrong_version", "evidence_insufficient"), ("no_original_text", "evidence_insufficient"),
    ("embedded_only", "evidence_insufficient"), ("source_wrong_document", "evidence_insufficient")])
def test_content_sources_through_registered_builder_executor_and_runtime(case, expected):
    state, run = fixture()
    doc = state["ocr_parse_results"][1]["tables"]
    qms = state["ocr_parse_results"][0]["tables"]
    if case == "absent":
        doc[-1]["normalizedRows"][0].update(presence="absent", value=None)
    elif case == "missing":
        doc[-1]["normalizedRows"].pop()
    elif case == "not_applicable":
        qms[-1]["normalizedRows"][0]["applicable"] = False
    elif case == "duplicate_context":
        doc[-3]["normalizedRows"] *= 2
    elif case == "wrong_version":
        doc[-1]["normalizedRows"][0]["reviewedDocumentVersionId"] = "OLD"
    elif case == "no_original_text":
        doc[-1].pop("contentMarkdown")
    elif case == "embedded_only":
        doc[-1]["normalizedRows"] = []
    elif case == "source_wrong_document":
        qms.append(doc.pop())
    before = deepcopy(state)
    facts, output = evaluate(state, run, "evaluate_r39_document_content")
    assert output["result"] == expected, output
    assert state == before
    assert output["facts"]["technicalCompliance"] == "not_evaluated"
    if case == "ok":
        inventory = facts["r39"]["documentContent"]["contentInventory"]
        assert all(row["evidenceRefs"][0]["documentVersionId"] == "DV1" for row in inventory["fields"])
