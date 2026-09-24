import json

import pytest

from scripts.evaluate_jev_document_routing import _read_labels, evaluate_routing
from scripts.prepare_jev_routing_labels import blind_packet


def _case(index):
    project = f"P-{index}"
    version = f"V-{index}"
    return {"state": {"documents": [{"id": version, "projectId": project}],
                      "versions": [{"id": version, "documentId": version}],
                      "ocr_parse_results": [{"documentVersionId": version,
                                             "fragments": [{"pageNo": 1, "text": "approved OCR"}]}]},
            "scope": {"projectId": project, "nodeId": "待归属",
                      "inputDocumentVersionIds": [version]},
            "projectId": project, "documentId": version, "documentVersionId": version,
            "questions": {f"node_{node}": {"type": "choice", "instructions": "固定节点题",
                                          "criteria": {"yes": "归属", "no": "不归属"}}
                          for node in (25, 26)},
            "nodeIds": {"node_25": 25, "node_26": 26}, "overlongNodeIds": [],
            "existingNodeIds": [25], "humanRejectedNodeIds": [26]}


def test_blind_packet_is_deterministic_and_omits_predictions_and_bindings(tmp_path):
    cases = [_case(index) for index in range(7)]
    first = blind_packet(cases, per_project=1)
    assert first == blind_packet(list(reversed(cases)), per_project=1)
    assert first["status"] == "ready_for_inspector"
    assert first["labelPairCount"] == 14
    assert all(row["expectedNodeIds"] == [25, 26] for row in first["cases"])
    assert all(item["choice"] is None for row in first["cases"] for item in row["nodeLabels"])
    text = json.dumps(first)
    assert all(secret not in text for secret in ("approved OCR", "existingNodeIds", "suggestedNodeIds",
                                                  "humanRejectedNodeIds", "confidence"))
    path = tmp_path / "labels.json"
    path.write_text(text, encoding="utf-8")
    assert _read_labels(path) == first["cases"]


def test_hash_and_complete_node_labels_are_required_for_new_packet():
    row = blind_packet([_case(index) for index in range(7)], per_project=1)["cases"][0]
    row["annotatedBy"] = "inspector-01"
    for item in row["nodeLabels"]:
        item["choice"] = "belongs" if item["nodeId"] == 25 else "does_not_belong"
    shadow = {"projectId": row["projectId"], "documentId": row["documentId"],
              "documentVersionId": row["documentVersionId"], "inputHash": row["inputHash"],
              "status": "completed", "nodeScores": [
                  {"nodeId": 25, "choice": "yes", "confidence": 0.95},
                  {"nodeId": 26, "choice": "no", "confidence": 0.95}]}
    assert evaluate_routing([shadow], [row])["labels"]["comparedNodeCount"] == 2
    assert evaluate_routing([shadow], [{**row, "inputHash": "stale"}])["documents"][
        "staleInputHashLabeled"] == 1
    with pytest.raises(ValueError, match="incomplete_blind_node_labels"):
        evaluate_routing([shadow], [{**row, "nodeLabels": row["nodeLabels"][:1]}])
