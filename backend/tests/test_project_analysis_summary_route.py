"""P9 R4：工程级结果接口——每节点一行原料 + 共性风险（同一标题 ≥2 个节点）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID

client = TestClient(app)
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
TEMPLATE = "证据不足，需人工确认"


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sqlite_enabled = False


def _finding(title: str, severity: str = "medium", grounded: bool = True) -> dict:
    return {
        "findingType": "qualification_mismatch",
        "severity": severity,
        "title": title,
        "description": "说明",
        "evidenceRefs": [{"fileName": "许可证.pdf", "pageNo": 1}] if grounded else [],
        "ruleRefs": [],
        "groundingStatus": "grounded" if grounded else "insufficient_evidence",
        "unsupportedClaims": [] if grounded else [{"claim": "TS1", "reason": "not_present_in_supplied_evidence"}],
    }


def test_summary_lists_latest_node_results_and_common_risks() -> None:
    repo.state.setdefault("project_analysis_runs", []).append(
        {
            "projectAnalysisRunId": "PARUN-S1",
            "projectAnalysisSnapshotId": "PASNAP-S1",
            "tenantId": "TENANT-DEFAULT",
            "projectId": PROJECT_ID,
            "status": "waiting_human_review",
            "phase": "waiting_human_review",
            "createdAt": "2026-09-06T00:00:00Z",
        }
    )
    repo.state["review_runs"].extend(
        [
            {
                "id": "RRUN-S1-1", "reviewRunId": "RRUN-S1-1", "projectAnalysisRunId": "PARUN-S1", "tenantId": "TENANT-DEFAULT",
                "projectId": PROJECT_ID, "nodeId": 1, "status": "waiting_human_review", "reviewResult": "partially_supported",
                "findingDrafts": [_finding("许可范围不覆盖 GC1", "high"), _finding(TEMPLATE, grounded=False)], "finishedAt": "2026-09-06T01:00:00Z",
            },
            {
                "id": "RRUN-S1-2-old", "reviewRunId": "RRUN-S1-2-old", "projectAnalysisRunId": "PARUN-S1", "tenantId": "TENANT-DEFAULT",
                "projectId": PROJECT_ID, "nodeId": 2, "status": "waiting_human_review", "reviewResult": "supported",
                "findingDrafts": [_finding("旧结果")], "finishedAt": "2026-09-06T00:30:00Z",
            },
            {
                "id": "RRUN-S1-2", "reviewRunId": "RRUN-S1-2", "projectAnalysisRunId": "PARUN-S1", "tenantId": "TENANT-DEFAULT",
                "projectId": PROJECT_ID, "nodeId": 2, "status": "waiting_human_review", "reviewResult": "partially_supported",
                "findingDrafts": [_finding("许可范围不覆盖 GC1", "medium")], "failedEvidenceShardIds": ["ESHARD-9"], "finishedAt": "2026-09-06T01:10:00Z",
            },
            {
                "id": "RRUN-OTHER", "reviewRunId": "RRUN-OTHER", "projectAnalysisRunId": "PARUN-OTHER", "tenantId": "TENANT-DEFAULT",
                "projectId": PROJECT_ID, "nodeId": 3, "status": "waiting_human_review", "findingDrafts": [_finding("许可范围不覆盖 GC1")],
            },
        ]
    )
    response = client.get(f"/api/projects/{PROJECT_ID}/inspection/full-project-analysis/runs/PARUN-S1/summary", headers=HEADERS)
    assert response.status_code == 200, response.text
    summary = response.json()["data"]["summary"]
    assert summary["projectAnalysisRunId"] == "PARUN-S1"
    nodes = {item["nodeId"]: item for item in summary["nodes"]}
    assert set(nodes) == {1, 2}, "只取本次分析的节点，且每节点取最新一次"
    assert nodes[2]["reviewRunId"] == "RRUN-S1-2" and nodes[2]["failedEvidenceShardIds"] == ["ESHARD-9"]
    assert nodes[1]["nodeName"], "节点名来自项目树"
    assert summary["commonRisks"] == [{"title": "许可范围不覆盖 GC1", "nodeIds": [1, 2], "nodeCount": 2}], "模板句不算共性风险"


def test_summary_requires_an_existing_run() -> None:
    response = client.get(f"/api/projects/{PROJECT_ID}/inspection/full-project-analysis/runs/PARUN-NOPE/summary", headers=HEADERS)
    assert response.json()["code"] != 0
