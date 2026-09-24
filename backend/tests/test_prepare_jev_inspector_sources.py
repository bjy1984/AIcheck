"""The inspector source packet is complete, blind, and bound to the label hash."""

import json

import pytest
from test_export_jev_seven_project_snapshot import _state

from scripts.export_jev_seven_project_snapshot import build_snapshot
from scripts.prepare_jev_inspector_sources import inspector_sources
from scripts.prepare_jev_routing_labels import blind_packet
from scripts.run_jev_routing_evaluation import snapshot_cases


def test_source_packet_has_full_ocr_and_fixed_questions_but_no_predictions():
    snapshot = build_snapshot(_state())
    cases = snapshot_cases(snapshot)
    labels = blind_packet(cases, per_project=1)
    source = inspector_sources(snapshot, labels)
    assert source["caseCount"] == 7
    assert source["cases"][0]["ocrText"].startswith("[第 1 页] approved OCR")
    assert source["cases"][0]["nodes"][0]["nodeId"] == 25
    assert "材料文件归属" in source["cases"][0]["nodes"][0]["question"]
    encoded = json.dumps(source)
    assert all(key not in encoded for key in ("nodeScores", "existingNodeIds",
                                               "suggestedNodeIds", "humanRejectedNodeIds"))
    labels["cases"][0]["inputHash"] = "stale"
    with pytest.raises(ValueError, match="blind_case_input_hash_changed"):
        inspector_sources(snapshot, labels)
