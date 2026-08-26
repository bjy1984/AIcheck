from __future__ import annotations


def test_project_output_creates_idempotent_advisory_node_review_runs() -> None:
    from libs.project_analysis.results import persist_project_analysis_node_results

    state = {
        "review_runs": [
            {
                "id": "RRUN-OLD",
                "reviewRunId": "RRUN-OLD",
                "projectId": "P-1",
                "nodeId": 1,
                "status": "waiting_human_review",
            }
        ],
        "tree_nodes": [
            {"projectId": "P-1", "nodeId": 1, "status": "待提交"},
            {"projectId": "P-1", "nodeId": 2, "status": "待提交"},
        ],
    }
    project_run = {
        "projectAnalysisRunId": "PARUN-1",
        "projectAnalysisSnapshotId": "PASNAP-1",
        "tenantId": "TENANT-1",
        "projectId": "P-1",
        "modelAttemptId": "MCALL-SHARED",
        "status": "persisting_results",
    }
    validated = {
        "nodeReviews": [
            {
                "nodeId": 1,
                "nodeName": "节点一",
                "reviewResult": "supported",
                "findings": [
                    {
                        "findingType": "document_present",
                        "severity": "low",
                        "title": "资料存在",
                        "description": "资料存在，等待人工确认",
                        "confidence": 0.8,
                        "suggestedAction": "human_confirm",
                        "evidenceRefs": [],
                        "ruleRefs": [],
                        "kbRefs": [],
                        "groundingStatus": "insufficient_evidence",
                        "unsupportedClaims": [],
                        "requiresHumanConfirmation": True,
                    }
                ],
            },
            {
                "nodeId": 2,
                "nodeName": "节点二",
                "reviewResult": "insufficient_evidence",
                "findings": [],
            },
        ],
        "projectSummary": {"humanReviewNodeCount": 2},
    }

    first = persist_project_analysis_node_results(state, project_run, validated)
    second = persist_project_analysis_node_results(state, project_run, validated)

    assert len(first) == 2
    assert [row["reviewRunId"] for row in second] == [
        row["reviewRunId"] for row in first
    ]
    assert len(state["review_runs"]) == 3
    assert state["review_runs"][0]["reviewRunId"] == "RRUN-OLD"
    assert all(row["projectAnalysisRunId"] == "PARUN-1" for row in first)
    assert all(row["sharedModelAttemptId"] == "MCALL-SHARED" for row in first)
    assert all(row["triggerType"] == "manual_full_project_analysis" for row in first)
    assert all(row["status"] == "waiting_human_review" for row in first)
    finding = first[0]["findingDrafts"][0]
    assert finding["projectId"] == "P-1"
    assert finding["nodeId"] == 1
    assert finding["reviewRunId"] == first[0]["reviewRunId"]
    assert [row["status"] for row in state["tree_nodes"]] == ["待提交", "待提交"]
    assert project_run["derivedReviewRunIds"] == [row["reviewRunId"] for row in first]
