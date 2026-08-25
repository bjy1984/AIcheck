from __future__ import annotations


def _node_state() -> dict:
    documents = [
        {"id": "DOC-1", "projectId": "P-1", "currentVersionId": "DV-1"},
        {"id": "DOC-2", "projectId": "P-1", "currentVersionId": "DV-2"},
        {"id": "DOC-3", "projectId": "P-1", "currentVersionId": "DV-3"},
    ]
    versions = [
        {"id": "DV-1", "documentId": "DOC-1", "contentHash": "sha256:doc1"},
        {"id": "DV-2", "documentId": "DOC-2", "contentHash": "sha256:doc2"},
        {"id": "DV-3", "documentId": "DOC-3", "contentHash": "sha256:doc3"},
    ]
    return {
        "documents": documents,
        "document_versions": versions,
        "versions": versions,
        "node_evidence_links": [
            {
                "id": "NEL-1",
                "projectId": "P-1",
                "nodeId": 1,
                "documentId": "DOC-1",
                "documentVersionId": "DV-1",
                "manualStatus": "confirmed",
            },
            {
                "id": "NEL-2",
                "projectId": "P-1",
                "nodeId": 2,
                "documentId": "DOC-2",
                "documentVersionId": "DV-2",
                "manualStatus": "confirmed",
            },
            {
                "id": "NEL-3",
                "projectId": "P-1",
                "nodeId": 3,
                "documentId": "DOC-3",
                "documentVersionId": "DV-3",
                "manualStatus": "rejected",
            },
        ],
        "ocr_parse_results": [
            {
                "id": f"OCR-{index}",
                "documentVersionId": f"DV-{index}",
                "artifactHash": f"sha256:ocr{index}",
                "status": "success",
            }
            for index in (1, 2, 3)
        ],
        "review_runs": [],
        "ai_runs": [],
        "auto_review_candidates": [],
        "project_review_runs": [],
    }


def _policy() -> dict:
    return {
        "id": "ARP-1",
        "tenantId": "TENANT-1",
        "projectId": "P-1",
        "enabled": True,
        "triggerModes": ["ocr_mounted", "daily_schedule"],
        "reviewMode": "gap_precheck",
        "revision": 3,
    }


def test_active_mounted_node_ids_excludes_rejected_evidence() -> None:
    from libs.auto_review import active_mounted_node_ids

    assert active_mounted_node_ids(_node_state(), "P-1") == [1, 2]


def test_dirty_nodes_excludes_latest_successful_identical_snapshot() -> None:
    from libs.auto_review import current_node_snapshot, dirty_nodes_for_project

    state = _node_state()
    node1_snapshot = current_node_snapshot(state, "P-1", 1)
    state["review_runs"].append(
        {
            "reviewRunId": "RRUN-OLD-1",
            "projectId": "P-1",
            "nodeId": 1,
            "status": "waiting_human_review",
            "evidenceSnapshotHash": node1_snapshot["snapshotHash"],
        }
    )

    dirty = dirty_nodes_for_project(state, "P-1", node_ids=[1, 2])

    assert [row["nodeId"] for row in dirty] == [2]


def test_create_parent_run_records_scope_and_policy_snapshot() -> None:
    from libs.auto_review import create_project_review_run

    state = _node_state()
    parent = create_project_review_run(
        state,
        tenant_id="TENANT-1",
        project_id="P-1",
        trigger_type="manual_full",
        policy=_policy(),
        node_ids=[1, 2],
    )

    assert parent["projectId"] == "P-1"
    assert parent["expectedNodeIds"] == [1, 2]
    assert parent["policySnapshot"]["revision"] == 3
    assert parent["status"] == "queued"
    assert state["project_review_runs"] == [parent]


def test_dispatch_parent_starts_dirty_children_and_isolates_node_failure() -> None:
    from libs.auto_review import create_project_review_run, dispatch_project_review_run

    state = _node_state()
    parent = create_project_review_run(
        state,
        tenant_id="TENANT-1",
        project_id="P-1",
        trigger_type="manual_full",
        policy=_policy(),
        node_ids=[1, 2],
    )

    def start_node(project_id: str, node_id: int, metadata: dict) -> dict:
        assert metadata["projectReviewRunId"] == parent["projectReviewRunId"]
        assert metadata["reviewMode"] == "gap_precheck"
        if node_id == 2:
            raise RuntimeError("node two unavailable")
        return {"aiRunId": "AIRUN-1", "reviewRunId": "RRUN-1", "status": "queued"}

    result = dispatch_project_review_run(state, parent, start_node_review=start_node)

    assert result["childAiRunIds"] == ["AIRUN-1"]
    assert result["childReviewRunIds"] == ["RRUN-1"]
    assert result["failedNodeIds"] == [2]
    assert result["status"] == "partial"


def test_finalize_parent_summarizes_child_terminal_states_without_business_decision() -> None:
    from libs.auto_review import create_project_review_run, finalize_project_review_run

    state = _node_state()
    parent = create_project_review_run(
        state,
        tenant_id="TENANT-1",
        project_id="P-1",
        trigger_type="daily_schedule",
        policy=_policy(),
        node_ids=[1, 2],
    )
    parent["childReviewRunIds"] = ["RRUN-1", "RRUN-2"]
    state["review_runs"] = [
        {"reviewRunId": "RRUN-1", "nodeId": 1, "status": "waiting_human_review"},
        {"reviewRunId": "RRUN-2", "nodeId": 2, "status": "failed"},
    ]

    result = finalize_project_review_run(state, parent)

    assert result["completedNodeIds"] == [1]
    assert result["failedNodeIds"] == [2]
    assert result["status"] == "partial"
    assert "businessConclusion" not in result


def test_dispatch_parent_with_no_mounted_nodes_completes_immediately() -> None:
    from libs.auto_review import create_project_review_run, dispatch_project_review_run

    state = _node_state()
    parent = create_project_review_run(
        state,
        tenant_id="TENANT-1",
        project_id="P-1",
        trigger_type="manual_full",
        policy=_policy(),
        node_ids=[],
    )

    result = dispatch_project_review_run(
        state,
        parent,
        start_node_review=lambda *_args: (_ for _ in ()).throw(
            AssertionError("an empty project must not dispatch a node review")
        ),
    )

    assert result["status"] == "completed"
    assert result["expectedNodeIds"] == []
    assert result["childReviewRunIds"] == []
    assert result["finishedAt"]
