from __future__ import annotations

import json
import sys

import pytest

from scripts.evaluate_jev_document_routing import evaluate_routing, main


def _shadow(version: str = "V1", *, status: str = "completed") -> dict:
    return {
        "projectId": "P1", "documentId": "D1", "documentVersionId": version,
        "status": status,
        "nodeScores": [
            {"nodeId": 1, "choice": "yes", "confidence": 0.95},
            {"nodeId": 2, "choice": "yes", "confidence": 0.92},
            {"nodeId": 3, "choice": "no", "confidence": 0.91},
            {"nodeId": 4, "choice": "uncertain", "confidence": 0.99},
            {"nodeId": 5, "choice": "yes", "confidence": 0.99},
        ],
        "suggestedNodeIds": [1, 2, 5], "existingNodeIds": [1, 3],
        "humanRejectedNodeIds": [],
    }


def _label(version: str = "V1", *, source: str = "inspector") -> dict:
    return {
        "projectId": "P1", "documentId": "D1", "documentVersionId": version,
        "labelSource": source, "annotatedBy": "inspector-01",
        "nodeLabels": [
            {"nodeId": 1, "choice": "belongs"},
            {"nodeId": 2, "choice": "does_not_belong"},
            {"nodeId": 3, "choice": "belongs"},
            {"nodeId": 4, "choice": "does_not_belong"},
            {"nodeId": 6, "choice": "uncertain"},
        ],
    }


def test_only_version_matched_inspector_labels_count_and_unlabelled_nodes_are_not_negative():
    report = evaluate_routing([_shadow(), _shadow("V2", status="overlong_document")],
                              [_label(), _label("V2", source="provisional")])

    assert report["status"] == "ready_for_review"
    assert report["documents"]["completedInspectorLabeled"] == 1
    assert report["documents"]["provisionalLabeled"] == 1
    assert report["documents"]["staleInputHashLabeled"] == 0
    assert report["documents"]["statusCounts"] == {"completed": 1, "overlong_document": 1}
    assert report["labels"] == {
        "comparedNodeCount": 4, "positiveNodeCount": 2, "negativeNodeCount": 2,
        "uncertainNodeCount": 1, "missingScoreCount": 0,
        "humanRejectionContradictions": 0,
    }
    assert report["jev"]["truePositive"] == 1
    assert report["jev"]["falsePositive"] == 1
    assert report["jev"]["missedPositive"] == 1
    assert report["jev"]["explicitNegativeOnPositive"] == 1
    assert report["jev"]["abstained"] == 1
    assert report["jev"]["precision"] == report["jev"]["recall"] == 0.5
    assert report["jev"]["precision95CI"] == report["jev"]["recall95CI"] == [0.0945, 0.9055]
    assert report["existingBindings"]["precision"] == report["existingBindings"]["recall"] == 1.0
    assert not any(item["nodeId"] == 5 for item in report["jev"]["errors"])
    assert report["releaseThresholdApproved"] is False


def test_noncompleted_or_mismatched_versions_cannot_claim_routing_accuracy():
    report = evaluate_routing([_shadow(status="partial")], [_label(), _label("V2")])
    assert report["status"] == "no_comparable_inspector_labels"
    assert report["documents"]["noncompletedInspectorLabeled"] == 1
    assert report["documents"]["labelsWithoutShadow"] == 1
    assert report["jev"]["precision"] is None
    assert report["labels"]["comparedNodeCount"] == 0


def test_missing_score_is_abstention_and_counts_as_missed_positive():
    shadow = _shadow()
    shadow["nodeScores"] = [item for item in shadow["nodeScores"] if item["nodeId"] != 3]
    report = evaluate_routing([shadow], [_label()])
    assert report["labels"]["missingScoreCount"] == 1
    assert report["jev"]["abstained"] == 2
    assert report["jev"]["missedPositive"] == 1
    assert report["jev"]["explicitNegativeOnPositive"] == 0


def test_human_rejection_disagreeing_with_inspector_label_is_visible():
    shadow = _shadow()
    shadow["suggestedNodeIds"] = [2, 5]
    shadow["humanRejectedNodeIds"] = [1]
    report = evaluate_routing([shadow], [_label()])
    assert report["labels"]["humanRejectionContradictions"] == 1
    assert report["jev"]["missedPositive"] == 2


@pytest.mark.parametrize("change,error", [
    ({"humanRejectedNodeIds": [1]}, "human_rejection_veto_violated"),
    ({"nodeScores": [{"nodeId": 1, "choice": "yes", "confidence": True}]}, "invalid_node_score"),
    ({"documentVersionId": ""}, "project_document_version_required"),
])
def test_invalid_shadow_does_not_produce_metrics(change, error):
    with pytest.raises(ValueError, match=error):
        evaluate_routing([{**_shadow(), **change}], [_label()])


def test_cli_report_contains_no_ocr_and_never_approves_threshold(tmp_path, monkeypatch):
    shadows = tmp_path / "shadows.jsonl"
    labels = tmp_path / "labels.jsonl"
    output = tmp_path / "report.json"
    shadows.write_text(json.dumps({**_shadow(), "fullOcrText": "private-ocr-body"}) + "\n", encoding="utf-8")
    labels.write_text(json.dumps(_label()) + "\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["evaluate", "--shadows", str(shadows), "--labels", str(labels),
                                  "--output", str(output)])

    assert main() == 0
    report = output.read_text(encoding="utf-8")
    assert "private-ocr-body" not in report
    assert json.loads(report)["releaseThresholdApproved"] is False
