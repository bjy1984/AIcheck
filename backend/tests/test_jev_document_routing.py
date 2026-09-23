from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from apps.worker import tasks
from libs import jev_document_routing as routing
from libs.integrations import task_dispatcher


class FakeRepo:
    def __init__(self, state):
        self.state = state

    def require_project(self, project_id):
        return next((item for item in self.state["projects"] if item["id"] == project_id), None)

    def find_one(self, collection, item_id):
        return next((item for item in self.state[collection] if item["id"] == item_id), None)

    def clone(self, value):
        return deepcopy(value)


def source():
    state = {
        "projects": [{"id": "P", "businessPackId": "engineering_inspection_v1"}],
        "documents": [{"id": "D", "projectId": "P", "fileName": "混合资料.pdf", "currentVersionId": "V"}],
        "versions": [{"id": "V", "documentId": "D"}],
        "ocr_parse_results": [{"documentVersionId": "V", "fragments": [
            {"pageNo": 1, "text": "焊接工艺卡 WPS-01 电流 90A"},
        ]}],
        "node_evidence_links": [],
        "admin_config": {"materialReviewPoints": [
            {"id": "P1", "nodeId": 1, "nodeName": "资质", "reviewContent": "设计许可",
             "materialTypeName": "许可证", "businessPackId": "engineering_inspection_v1"},
            {"id": "P25", "nodeId": 25, "nodeName": "焊接工艺", "reviewContent": "核对 WPS",
             "materialTypeName": "焊接工艺卡", "businessPackId": "engineering_inspection_v1"},
        ]},
    }
    return FakeRepo(state)


def test_routing_is_disabled_without_outbound_stage_gate(monkeypatch):
    monkeypatch.setattr(routing, "jev_stage_enabled", lambda _: False)
    monkeypatch.setattr(routing, "ask_jev", lambda *_: 1 / 0)
    assert routing.classify_document_node_routing(source(), "P", "D", "V")["status"] == "disabled"


def test_whole_document_routing_records_shadow_disagreement_without_binding(monkeypatch):
    repo = source()
    sent = []
    monkeypatch.setattr(routing, "jev_stage_enabled", lambda _: True)

    def fake_ask(state, questions):
        sent.append((state, questions))
        return {key: {"type": "choice", "choice": "yes" if key == "node_25" else "no",
                      "confidence": 0.98} for key in questions}

    monkeypatch.setattr(routing, "ask_jev", fake_ask)
    result = routing.classify_document_node_routing(repo, "P", "D", "V")

    assert result["status"] == "completed"
    assert result["suggestedNodeIds"] == [25]
    assert result["disagreementNodeIds"] == [25]
    assert result["nodeScores"] == [
        {"nodeId": 1, "choice": "no", "confidence": 0.98},
        {"nodeId": 25, "choice": "yes", "confidence": 0.98},
    ]
    assert "WPS-01" in sent[0][0] and "node_25" in sent[0][1]
    assert "WPS-01" not in str(result)
    assert repo.state["node_evidence_links"] == []
    assert "bindings" not in repo.state


def test_human_rejection_vetoes_routing_suggestion(monkeypatch):
    repo = source()
    repo.state["node_evidence_links"] = [{
        "projectId": "P", "documentVersionId": "V", "nodeId": 25, "manualStatus": "rejected",
    }]
    monkeypatch.setattr(routing, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(routing, "ask_jev", lambda _state, questions: {
        key: {"type": "choice", "choice": "yes", "confidence": 0.99} for key in questions
    })

    result = routing.classify_document_node_routing(repo, "P", "D", "V")

    assert result["humanRejectedNodeIds"] == [25]
    assert result["suggestedNodeIds"] == [1]
    assert repo.state["node_evidence_links"][0]["manualStatus"] == "rejected"


def test_wrong_project_stale_version_and_missing_ocr_never_call_jev(monkeypatch):
    repo = source()
    monkeypatch.setattr(routing, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(routing, "ask_jev", lambda *_: 1 / 0)

    assert routing.classify_document_node_routing(repo, "OTHER", "D", "V")["status"] == "invalid_scope"
    repo.state["documents"][0]["currentVersionId"] = "V2"
    assert routing.classify_document_node_routing(repo, "P", "D", "V")["status"] == "stale_version"
    repo.state["documents"][0]["currentVersionId"] = "V"
    repo.state["ocr_parse_results"] = []
    assert routing.classify_document_node_routing(repo, "P", "D", "V")["status"] == "no_ocr_text"


def test_oversized_document_is_explicitly_skipped(monkeypatch):
    repo = source()
    repo.state["ocr_parse_results"][0]["fragments"][0]["text"] = "长" * 40_000
    monkeypatch.setattr(routing, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(routing, "ask_jev", lambda *_: 1 / 0)

    result = routing.classify_document_node_routing(repo, "P", "D", "V")

    assert result["status"] == "overlong_document"
    assert result["overlongDocumentVersionIds"] == ["V"]


def test_network_error_does_not_create_an_apparent_suggestion(monkeypatch):
    monkeypatch.setattr(routing, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(routing, "ask_jev", lambda *_: (_ for _ in ()).throw(OSError("offline")))

    result = routing.classify_document_node_routing(source(), "P", "D", "V")

    assert result["status"] == "unavailable"
    assert "suggestedNodeIds" not in result


def test_incomplete_answer_and_overlong_template_are_explicit(monkeypatch):
    repo = source()
    monkeypatch.setattr(routing, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(routing, "ask_jev", lambda *_: {})
    assert routing.classify_document_node_routing(repo, "P", "D", "V")["status"] == "invalid_response"

    repo.state["admin_config"]["materialReviewPoints"].append({
        "id": "P2", "nodeId": 2, "nodeName": "超长模板", "reviewContent": "长" * 6_100,
        "businessPackId": "engineering_inspection_v1",
    })
    monkeypatch.setattr(routing, "ask_jev", lambda _state, questions: {
        key: {"type": "choice", "choice": "no", "confidence": 0.99} for key in questions
    })
    result = routing.classify_document_node_routing(repo, "P", "D", "V")
    assert result["status"] == "partial"
    assert result["overlongNodeIds"] == [2]


def test_same_ocr_and_templates_reuse_recorded_result(monkeypatch):
    repo = source()
    calls = []
    monkeypatch.setattr(routing, "jev_stage_enabled", lambda _: True)

    def fake_ask(_state, questions):
        calls.append(1)
        return {key: {"type": "choice", "choice": "no", "confidence": 0.99} for key in questions}

    monkeypatch.setattr(routing, "ask_jev", fake_ask)
    first = routing.classify_document_node_routing(repo, "P", "D", "V")
    repo.state["documents"][0]["jevRoutingShadow"] = first
    second = routing.classify_document_node_routing(repo, "P", "D", "V")

    assert len(calls) == 1
    assert second["reused"] is True
    repo.state["ocr_parse_results"][0]["fragments"][0]["text"] += " 补充一页"
    routing.classify_document_node_routing(repo, "P", "D", "V")
    assert len(calls) == 2


def test_dispatch_requires_celery_and_carries_tenant(monkeypatch):
    from libs.review_orchestrator import jev_client
    from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id

    monkeypatch.setattr(jev_client, "jev_stage_enabled", lambda _: True)
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")
    assert task_dispatcher.dispatch_document_routing_shadow("P", "D", "V", "OCR-1")["taskId"] is None
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    calls = []
    monkeypatch.setattr(
        tasks.classify_document_node_jev_shadow, "apply_async",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(id="JEV-TASK-1"),
    )
    token = set_request_tenant_id("TENANT-A")
    try:
        dispatched = task_dispatcher.dispatch_document_routing_shadow("P", "D", "V", "OCR-1")
    finally:
        reset_request_tenant_id(token)

    assert dispatched["taskId"] == "JEV-TASK-1"
    assert calls[0]["args"] == ["P", "D", "V", "TENANT-A"]
    assert calls[0]["queue"] == "llm.remote"


def test_worker_persists_only_current_version_shadow(monkeypatch):
    repo = source()
    monkeypatch.setattr(tasks, "repo", repo)
    monkeypatch.setattr(tasks, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(tasks, "classify_document_node_routing", lambda *_: {
        "status": "completed", "documentVersionId": "V", "model": routing.MODEL,
    })
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_: None)
    saved = []
    monkeypatch.setattr(tasks, "flush_state_records", lambda records: saved.append(deepcopy(records)))

    result = tasks.classify_document_node_jev_shadow.run("P", "D", "V")

    assert result["status"] == "completed"
    assert saved[0]["documents"][0]["jevRoutingShadow"] == result


def test_worker_discards_late_shadow_after_new_upload(monkeypatch):
    repo = source()
    monkeypatch.setattr(tasks, "repo", repo)
    monkeypatch.setattr(tasks, "jev_stage_enabled", lambda _: True)
    monkeypatch.setattr(tasks, "classify_document_node_routing", lambda *_: {
        "status": "completed", "documentVersionId": "V", "model": routing.MODEL,
    })
    refresh_count = []

    def refresh(*_args):
        refresh_count.append(1)
        if len(refresh_count) == 2:
            repo.state["documents"][0]["currentVersionId"] = "V2"

    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", refresh)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_: 1 / 0)

    result = tasks.classify_document_node_jev_shadow.run("P", "D", "V")

    assert result["status"] == "stale_version"
    assert "jevRoutingShadow" not in repo.state["documents"][0]
