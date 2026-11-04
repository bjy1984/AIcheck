"""自动重审按「证据本身」判断审没审过（2026-11-03 审计第 3 条）。

原来自动重审用写死的占位版本算快照哈希，真实运行用真实的规则、条款包、提示词版本算，
两个哈希永远不等：手动复核过的证据照样排自动复核，「这份证据审过没有」根本判断不了。
"""
from __future__ import annotations

from datetime import UTC, datetime

from libs.auto_review import consume_auto_review_evidence_events, dirty_nodes_for_project
from libs.review_evidence import build_evidence_snapshot, evidence_content_hash
from tests.test_auto_review_scheduler import _state_with_node


def _reviewed(state: dict, status: str = "waiting_human_review") -> dict:
    """模拟一次真实复核：用真实运行的版本（规则版本、条款包哈希、提示词版本）冻结快照。"""
    snapshot = build_evidence_snapshot(
        state, "P-1", 1, rule_version="R01@v3", clause_package_version="sha256:clauses",
        prompt_version="node-1-v1", strategy_version="node-review-strategy-v1")
    state.setdefault("evidence_snapshots", []).append(snapshot)
    state["review_runs"].append({
        "reviewRunId": "RRUN-MANUAL", "projectId": "P-1", "nodeId": 1, "status": status,
        "evidenceSnapshotId": snapshot["evidenceSnapshotId"], "evidenceSnapshotHash": snapshot["snapshotHash"],
        "finishedAt": "2026-11-04 10:00:00"})
    return snapshot


def _event(state: dict) -> None:
    state["auto_review_outbox"].append({
        "id": "AREVT-1", "eventType": "node.evidence.mounted", "tenantId": "TENANT-1", "projectId": "P-1",
        "documentVersionId": "DV-1", "nodeIds": [1], "policyRevision": 2, "status": "pending", "attemptCount": 0})


def test_证据指纹不受规则条款提示词版本影响_也不受重新挂载影响():
    state = _state_with_node()
    a = build_evidence_snapshot(state, "P-1", 1, rule_version="auto-review-rule-v1", clause_package_version="x",
                                prompt_version="y", strategy_version="z")
    b = build_evidence_snapshot(state, "P-1", 1, rule_version="R01@v3", clause_package_version="sha256:c",
                                prompt_version="node-1-v1", strategy_version="node-review-strategy-v1")
    assert a["snapshotHash"] != b["snapshotHash"], "前提：两种快照哈希本来就不等"
    assert evidence_content_hash(a) == evidence_content_hash(b)
    state["node_evidence_links"][0]["mountRevision"] = 7
    c = build_evidence_snapshot(state, "P-1", 1, rule_version="r", clause_package_version="c", prompt_version="p",
                                strategy_version="s")
    assert evidence_content_hash(c) == evidence_content_hash(b), "同一文件重新挂一次不算证据变了"


def test_手动复核过的证据_扫描不再判为待审():
    state = _state_with_node()
    assert [row["nodeId"] for row in dirty_nodes_for_project(state, "P-1")] == [1], "没审过：待审"
    _reviewed(state)
    assert dirty_nodes_for_project(state, "P-1") == []


def test_手动复核过的证据_挂载事件不再排自动复核():
    state = _state_with_node()
    _reviewed(state)
    _event(state)
    result = consume_auto_review_evidence_events(state, now=datetime(2026, 11, 4, 3, 0, tzinfo=UTC))
    assert result["completedEventIds"] == ["AREVT-1"] and not result["createdCandidateIds"]
    assert state["auto_review_candidates"] == []


def test_证据真的变了才重审_新版本或OCR结果变了():
    state = _state_with_node()
    _reviewed(state)
    state["ocr_parse_results"][0]["artifactHash"] = "sha256:ocr-v2"
    assert [row["nodeId"] for row in dirty_nodes_for_project(state, "P-1")] == [1], "OCR 结果变了"
    state = _state_with_node()
    _reviewed(state)
    state["document_versions"].append({"id": "DV-2", "documentId": "DOC-1", "contentHash": "sha256:doc2"})
    state["versions"].append({"id": "DV-2", "documentId": "DOC-1", "contentHash": "sha256:doc2"})
    state["documents"][0]["currentVersionId"] = "DV-2"
    state["node_evidence_links"][0]["documentVersionId"] = "DV-2"
    assert [row["nodeId"] for row in dirty_nodes_for_project(state, "P-1")] == [1], "传了新版本"


def test_失败的复核不算审过_老运行没存快照时按原来的去重走():
    state = _state_with_node()
    _reviewed(state, status="failed")
    assert [row["nodeId"] for row in dirty_nodes_for_project(state, "P-1")] == [1]
    state = _state_with_node()
    _reviewed(state)
    state["evidence_snapshots"] = []
    assert [row["nodeId"] for row in dirty_nodes_for_project(state, "P-1")] == [1]


# ── 第 5 条：人工挂载提交、确认或不采用证据也要触发 ─────────────────────────────

def test_证据变化入队按证据去重_改回原样不重复排():
    from libs.auto_review import enqueue_node_evidence_change

    state = _state_with_node()
    first = enqueue_node_evidence_change(state, tenant_id="TENANT-1", project_id="P-1", node_ids=[1], reason="evidence_rejected")
    again = enqueue_node_evidence_change(state, tenant_id="TENANT-1", project_id="P-1", node_ids=[1], reason="evidence_confirmed")
    assert len(state["auto_review_outbox"]) == 1 and first[0]["id"] == again[0]["id"], "证据没变：同一个事件"
    assert first[0]["reason"] == "evidence_rejected" and first[0]["eventType"] == "node.evidence.mounted"
    state["ocr_parse_results"][0]["artifactHash"] = "sha256:ocr-v2"
    enqueue_node_evidence_change(state, tenant_id="TENANT-1", project_id="P-1", node_ids=[1], reason="manual_mount_submitted")
    assert len(state["auto_review_outbox"]) == 2, "证据变了：新事件"


def test_策略没开不入队_出错也不影响业务请求(monkeypatch):
    from libs import auto_review
    from libs.auto_review import enqueue_node_evidence_change

    state = _state_with_node()
    state["auto_review_policies"][0]["enabled"] = False
    assert enqueue_node_evidence_change(state, tenant_id="TENANT-1", project_id="P-1", node_ids=[1], reason="x") == []
    state = _state_with_node()
    monkeypatch.setattr(auto_review, "current_node_snapshot", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert enqueue_node_evidence_change(state, tenant_id="TENANT-1", project_id="P-1", node_ids=[1], reason="x") == []


def test_确认和不采用证据_人工挂载提交三处都接上了触发():
    import inspect

    from apps.api import routes

    source = inspect.getsource(routes)
    assert 'reason=f"evidence_{manual_status}"' in source
    assert source.count('reason="manual_mount_submitted"') == 3
