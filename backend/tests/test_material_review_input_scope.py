import json
from copy import deepcopy

import pytest

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.r12_agent import build_r12_business_facts, extract_component_items
from libs.review_orchestrator.r13_facts import build_r13_business_facts
from libs.review_orchestrator.r14_facts import build_r14_business_facts
from libs.review_orchestrator.r15_facts import build_r15_business_facts
from libs.review_orchestrator.r16_facts import build_r16_business_facts
from libs.review_orchestrator.r17_facts import build_r17_business_facts
from libs.review_orchestrator.r18_facts import build_r18_business_facts

BUILDERS = [(12, build_r12_business_facts), (13, build_r13_business_facts), (14, build_r14_business_facts),
            (15, build_r15_business_facts), (16, build_r16_business_facts), (17, build_r17_business_facts),
            (18, build_r18_business_facts)]


def material_state():
    parse = {"documentVersionId": "SELECTED", "documentType": "comprehensive_material_list",
             "profileId": "comprehensive_material_list_v1", "tables": [{
                 "tableId": "T", "title": "境外制造压力管道元件材料表", "pageNo": 1,
                 "businessSchemas": ["material_component_table"], "normalizedRows": [{
                     "componentType": "金属阀门", "manufacturerName": "ACME", "manufacturingCountry": "Germany",
                     "specification": "DN100 PN40", "material": "L360", "confidence": 0.98}]}]}
    foreign = deepcopy(parse)
    foreign["documentVersionId"] = "FOREIGN"
    foreign["tables"][0]["normalizedRows"][0]["manufacturerName"] = "SECRET-COMPANY"
    return {"ocr_parse_results": [parse, foreign]}


@pytest.mark.parametrize("node,builder", BUILDERS)
def test_material_fact_builders_enforce_empty_selected_and_frozen_sources(node, builder):
    state = material_state()
    run = {"projectId": "P", "nodeId": node, "inputDocumentVersionIds": []}
    assert builder(state, run) == builder({"ocr_parse_results": []}, run)
    run["inputDocumentVersionIds"] = ["SELECTED"]
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    result = json.dumps(builder(state, run), ensure_ascii=False)
    assert "SELECTED" in result
    assert "SECRET-COMPANY" not in result and "FOREIGN" not in result
    state["ocr_parse_results"][0]["tables"][0]["normalizedRows"][0]["material"] = "CHANGED"
    with pytest.raises(ValueError, match="sources_changed"):
        builder(state, run)


def test_component_certificate_uses_scoped_human_correction_without_mutating_ocr():
    run = {"projectId": "P", "nodeId": 12, "inputDocumentVersionIds": ["CERT"]}
    state = {"ocr_parse_results": [{"documentVersionId": "CERT", "fields": [
        {"fieldName": "manufacturer", "fieldCode": "manufacturer", "fieldValue": "ORIGINAL"},
        {"fieldName": "product_name", "fieldCode": "product_name", "fieldValue": "钢管"}]}],
        "fact_corrections": [{"id": "C", "projectId": "P", "nodeId": 12, "documentVersionId": "CERT",
                              "fieldId": "F", "fieldName": "manufacturer", "correctedValue": "CORRECTED", "status": "active"}]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    original = deepcopy(state)
    result = extract_component_items(state, run)
    assert result and result[0]["manufacturerName"] == "CORRECTED"
    assert state == original
