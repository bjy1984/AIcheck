from test_evaluate_jev_atomic_opinions import _state

from scripts.compile_jev_decision_report import decision_report
from scripts.evaluate_jev_atomic_opinions import candidates_from_state, r19_candidates_from_state


def _labels(candidates):
    return [{"caseId": row["caseId"], "inputHash": row["inputHash"],
             "labelSource": "inspector", "annotatedBy": "I-1", "choice": row["jevChoice"]}
            for row in candidates]


def test_empty_report_exposes_every_missing_dependency():
    report = decision_report()
    assert report["status"] == "incomplete"
    assert "routing_live_requests_missing" in report["blockers"]
    assert "atomic_inspector_truth_missing" in report["blockers"]
    assert "provider_billing_unverified" in report["blockers"]
    assert report["releaseThresholdApproved"] is False


def test_interim_report_carries_recomputable_input_capacity_without_document_ids():
    report = decision_report(
        routing_preflight={"projectCount": 7, "documentCount": 3, "readyCount": 1,
                           "requestCount": 4, "ocrAttemptCount": 4,
                           "duplicateOcrVersionCount": 1, "invalidEvidenceLinks": {},
                           "projects": [{"files": [{"documentId": "PRIVATE-A", "status": "ready"},
                                                   {"documentId": "PRIVATE-B", "status": "ocr_not_ready"},
                                                   {"documentId": "PRIVATE-C", "status": "overlong_document"}]}]},
        input_snapshot_sha256="snapshot-hash",
        atomic_run={"send": False, "discoveryStatusCounts": {"eligible": 2}},
    )
    assert report["routingInputCapacity"]["statusCounts"] == {
        "ocr_not_ready": 1, "overlong_document": 1, "ready": 1}
    assert report["inputSnapshotSha256"] == "snapshot-hash"
    assert report["atomicDiscoveryStatusCounts"] == {"eligible": 2}
    assert "PRIVATE-A" not in str(report)


def test_complete_recorded_artifacts_are_recomputable_but_do_not_approve_release():
    routing_shadows, routing_labels = [], []
    for index in range(28):
        base = {"projectId": f"P-{index // 4}", "documentId": f"D-{index}",
                "documentVersionId": f"V-{index}", "inputHash": f"hash-{index}"}
        routing_shadows.append({**base, "status": "completed", "nodeScores": [
            {"nodeId": 25, "choice": "yes", "confidence": 0.95}],
            "suggestedNodeIds": [25], "existingNodeIds": [], "humanRejectedNodeIds": []})
        routing_labels.append({**base, "labelSource": "inspector", "annotatedBy": "I-1",
                               "expectedNodeIds": [25],
                               "nodeLabels": [{"nodeId": 25, "choice": "belongs"}]})
    atomic = _state()
    atomic.update(send=True, attemptedRequestCount=40, plannedRequestCount=40, elapsedSeconds=40.0)
    r19 = {"send": True, "attemptedRequestCount": 1, "plannedRequestCount": 1,
           "review_runs": [{"reviewRunId": "RR-R19", "projectId": "P", "nodeId": 19,
                            "inputHash": "h-r19", "jevSecondOpinions": {
                                "status": "completed", "model": "jev-1.13.0",
                                "comparisonSource": "r19_semantic_review", "atomic": [
                                    {"atomicCheckId": f"AC-R19-{index:02d}", "choice": "passed",
                                     "confidence": 0.8} for index in range(1, 9)]}}],
           "rule_check_results": [{"reviewRunId": "RR-R19", "atomicCheckResults": [
               {"atomicCheckId": f"AC-R19-{index:02d}", "result": "passed"}
               for index in range(1, 9)]}]}
    report = decision_report(
        routing_run={"send": True, "attemptedRequestCount": 28, "plannedRequestCount": 28},
        routing_shadows=routing_shadows, routing_labels=routing_labels,
        atomic_run=atomic, atomic_labels=_labels(candidates_from_state(atomic)["candidates"]),
        r19_run=r19, r19_labels=_labels(r19_candidates_from_state(r19)["candidates"]),
        billing={"source": "provider_invoice", "amountUSD": 1.23, "invoiceRef": "invoice-1"},
    )
    assert report == decision_report(
        routing_run={"send": True, "attemptedRequestCount": 28, "plannedRequestCount": 28},
        routing_shadows=routing_shadows, routing_labels=routing_labels,
        atomic_run=atomic, atomic_labels=_labels(candidates_from_state(atomic)["candidates"]),
        r19_run=r19, r19_labels=_labels(r19_candidates_from_state(r19)["candidates"]),
        billing={"source": "provider_invoice", "amountUSD": 1.23, "invoiceRef": "invoice-1"},
    )
    assert report["status"] == "ready_for_decision"
    assert report["routing"]["documents"]["completedInspectorLabeled"] == 28
    assert report["atomicRiskSample"]["inspectorComparedCount"] == 33
    assert report["r19"]["inspectorComparedCount"] == 8
    assert report["billingUSD"] == 1.23
    assert report["releaseThresholdApproved"] is False
