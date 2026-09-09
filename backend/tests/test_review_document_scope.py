from copy import deepcopy

import pytest

from libs.review_document_scope import freeze_document_scope, validate_document_scope
from libs.review_orchestrator.runtime_tools import selected_parse_results


def frozen_run():
    run = {"projectId": "P1", "nodeId": 24, "businessPackId": "B1", "inputDocumentVersionIds": ["D1", "D2"]}
    run["documentScopeSnapshot"] = freeze_document_scope(run)
    return run


@pytest.mark.parametrize("key,value", [("projectId", "P2"), ("nodeId", 25), ("businessPackId", "B2"),
                                       ("inputDocumentVersionIds", ["D1", "D2", "SECRET"]),
                                       ("inputDocumentVersionIds", []), ("inputDocumentVersionIds", ["D2"])])
def test_changed_run_cannot_read_documents(key, value):
    run = frozen_run()
    run[key] = value
    with pytest.raises(ValueError, match="document_scope"):
        selected_parse_results({"ocr_parse_results": []}, {}, context={"reviewRun": run})


def test_snapshot_is_independent_and_tamper_is_rejected():
    run = frozen_run()
    run["inputDocumentVersionIds"].append("D3")
    assert run["documentScopeSnapshot"]["documentVersionIds"] == ["D1", "D2"]
    run = frozen_run()
    run["documentScopeSnapshot"]["documentVersionIds"].append("D3")
    with pytest.raises(ValueError, match="hash_mismatch"):
        validate_document_scope(run)


def test_shard_context_can_narrow_but_cannot_expand_frozen_run():
    run = frozen_run()
    original = deepcopy(run)
    state = {"ocr_parse_results": [{"documentVersionId": item} for item in ["D1", "D2", "SECRET"]]}
    rows = selected_parse_results(state, {}, context={"reviewRun": run, "documentVersionIds": ["D2", "SECRET"]})
    assert [row["documentVersionId"] for row in rows] == ["D2"]
    assert run == original


def test_legacy_scope_and_empty_frozen_scope():
    validate_document_scope({"inputDocumentVersionIds": ["OLD"]})
    run = frozen_run()
    run["inputDocumentVersionIds"] = []
    run["documentScopeSnapshot"] = freeze_document_scope(run)
    assert selected_parse_results({"ocr_parse_results": [{"documentVersionId": "SECRET"}]}, {}, context={"reviewRun": run}) == []


def test_initialization_detaches_ai_inputs_and_pins_document_hash():
    from libs.business_pack import load_business_pack
    from libs.review_orchestrator.runtime_tools import runtime_tool_catalog
    from libs.review_workstations import digest, initialize_run_workstation, station_snapshot

    pack = load_business_pack("engineering_inspection_v1")
    source = ["D1"]
    run = {"projectId": "P1", "nodeId": 24, "businessPackId": pack["id"],
           "inputDocumentVersionIds": source, "inputHash": "old", "ruleSetVersion": "old"}
    second = deepcopy(run)
    second["inputDocumentVersionIds"] = ["D2"]
    for record in (run, second):
        initialize_run_workstation(record, {"businessPackSnapshot": pack}, None, runtime_tool_catalog(), digest)
    source.append("FOREIGN")
    assert run["inputDocumentVersionIds"] == ["D1"]
    assert run["inputHash"] != second["inputHash"]
    assert station_snapshot(run)["stationId"] == "A"
    run["inputDocumentVersionIds"].append("FOREIGN")
    with pytest.raises(ValueError, match="versions_mismatch"):
        station_snapshot(run)
