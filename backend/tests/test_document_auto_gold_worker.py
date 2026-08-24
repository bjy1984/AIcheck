from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.worker import tasks
from libs.db.repository import InMemoryRepository
from libs.db.seed import PROJECT_ID
from libs.integrations import task_dispatcher


MARKDOWN = """# 中华人民共和国特种设备生产许可证

许可项目：压力管道设计
许可子项目：公用管道（GB1、GB2）
"""


class FakeQwenClient:
    def __init__(self, output: dict) -> None:
        self.output = output
        self.calls: list[dict] = []

    def chat_sync(self, messages, model="default-chat", **kwargs):
        self.calls.append({"messages": messages, "model": model, **kwargs})
        return {
            "id": "QWEN-CLASSIFY-1",
            "model": "qwen3.8-max",
            "provider": "Model Studio / DashScope",
            "choices": [{"message": {"content": json.dumps(self.output, ensure_ascii=False)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
        }


def accepted_output() -> dict:
    return {
        "labels": [
            {
                "category": "资质证照",
                "confidence": 0.98,
                "decisionSummary": "Markdown正文是特种设备生产许可证。",
                "contentEvidence": [
                    {
                        "quote": "中华人民共和国特种设备生产许可证",
                        "purpose": "证明文件属于资质证照",
                    }
                ],
            },
            {
                "category": "设计基础资料",
                "confidence": 0.83,
                "decisionSummary": "正文包含压力管道设计许可内容。",
                "contentEvidence": [
                    {
                        "quote": "许可项目：压力管道设计",
                        "purpose": "证明文件包含设计依据",
                    }
                ],
            },
        ],
        "documentSummary": "压力管道设计许可证",
        "classificationComplete": True,
        "unclassifiedReason": None,
    }


def repository_with_ocr_result() -> tuple[InMemoryRepository, dict, dict, dict]:
    repository = InMemoryRepository()
    document, version = repository.create_document(
        PROJECT_ID,
        "MISLEADING_SECRET_NAME.pdf",
        "application/pdf",
    )
    job = repository.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        provider="mineru",
    )
    parse_result = repository.finish_ocr_job_record(
        job,
        {
            "parseResultId": "PARSE-AUTO-GOLD-1",
            "status": "success",
            "outcomeStatus": "completed",
            "profileId": "qualification_certificate_v1",
            "documentType": "qualification_certificate",
            "fragments": [{"pageNo": 1, "text": "许可证", "bbox": [0, 0, 10, 10]}],
            "fields": [],
            "tables": [],
            "seals": [],
        },
    )
    assert parse_result is not None
    repository.apply_ocr_result(document["id"], version["id"], parse_result)
    return repository, document, version, parse_result


def prepare_run(repository, document, version, parse_result):
    markdown_sha256 = "sha256:" + hashlib.sha256(MARKDOWN.encode("utf-8")).hexdigest()
    return tasks.prepare_document_auto_gold_run(
        repository,
        document_id=document["id"],
        document_version_id=version["id"],
        ocr_parse_result_id=parse_result["parseResultId"],
        markdown=MARKDOWN,
        markdown_sha256=markdown_sha256,
    )


def test_dispatch_document_classification_targets_existing_llm_queue(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    monkeypatch.setattr(
        tasks.classify_document_auto_gold,
        "apply_async",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(id="CELERY-CLASSIFY-1"),
    )

    output = task_dispatcher.dispatch_document_classification("DCR-1")

    assert output == {
        "mode": "celery",
        "taskId": "CELERY-CLASSIFY-1",
        "queue": "llm.remote",
        "priority": 9,
        "statusReason": "document_classification_queued",
    }
    assert calls[0]["args"] == ["DCR-1"]
    assert calls[0]["queue"] == "llm.remote"
    assert calls[0]["task_id"].startswith("aicheck-document-auto-gold-")


def test_prepare_run_is_idempotent_and_contains_markdown_only_context(monkeypatch: pytest.MonkeyPatch):
    repository, document, version, parse_result = repository_with_ocr_result()

    first = prepare_run(repository, document, version, parse_result)
    second = prepare_run(repository, document, version, parse_result)

    assert first["id"] == second["id"]
    assert len(repository.state["document_classification_runs"]) == 1
    assert first["ocrMarkdown"] == MARKDOWN
    assert first["markdownSha256"].startswith("sha256:")
    serialized_context = json.dumps(first["modelInput"], ensure_ascii=False)
    assert "MISLEADING_SECRET_NAME.pdf" not in serialized_context
    assert "fileName" not in serialized_context
    assert set(first["modelInput"]) == {"categoryDefinitionsJson", "ocrMarkdown"}


def test_one_call_success_persists_auto_gold_and_projects_multiple_labels(monkeypatch: pytest.MonkeyPatch):
    repository, document, version, parse_result = repository_with_ocr_result()
    run = prepare_run(repository, document, version, parse_result)
    initial_material_type = document["materialTypeCode"]
    client = FakeQwenClient(accepted_output())
    persisted: list[dict] = []

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda records, *_args, **_kwargs: persisted.append(records))
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: client)

    result = tasks.classify_document_auto_gold.run(run["id"])

    assert result["status"] == "accepted"
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "document-classifier"
    assert call["stream"] is False
    assert call["response_format"]["type"] == "json_schema"
    serialized_messages = json.dumps(call["messages"], ensure_ascii=False)
    assert MARKDOWN in call["messages"][1]["content"]
    assert "MISLEADING_SECRET_NAME.pdf" not in serialized_messages
    assert "fileName" not in serialized_messages

    assert run["status"] == "accepted"
    assert run["model"] == "qwen3.8-max"
    assert run["rawResponse"]["id"] == "QWEN-CLASSIFY-1"
    gold = repository.state["document_gold_labels"][0]
    assert gold["classificationRunId"] == run["id"]
    assert [item["category"] for item in gold["labels"]] == ["资质证照", "设计基础资料"]
    assert document["materialCategoryLabels"] == ["资质证照", "设计基础资料"]
    assert document["materialCategory"] == "资质证照"
    assert document["materialTypeCode"] == initial_material_type
    knowledge_file = repository.knowledge_file_for_version(version["id"])
    assert knowledge_file is not None
    assert knowledge_file["materialCategoryLabels"] == ["资质证照", "设计基础资料"]
    assert persisted


def test_ungrounded_response_fails_without_gold(monkeypatch: pytest.MonkeyPatch):
    repository, document, version, parse_result = repository_with_ocr_result()
    run = prepare_run(repository, document, version, parse_result)
    output = accepted_output()
    output["labels"][0]["contentEvidence"][0]["quote"] = "Markdown中不存在的证据"

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: FakeQwenClient(output))

    result = tasks.classify_document_auto_gold.run(run["id"])

    assert result["status"] == "failed"
    assert result["failureReason"] == "UNGROUNDED_EVIDENCE"
    assert repository.state["document_gold_labels"] == []
    assert "materialCategoryLabels" not in document


def test_stale_document_version_does_not_call_qwen_or_write_gold(monkeypatch: pytest.MonkeyPatch):
    repository, document, version, parse_result = repository_with_ocr_result()
    run = prepare_run(repository, document, version, parse_result)
    document["currentVersionId"] = "DV-NEWER-V2"
    client = FakeQwenClient(accepted_output())

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "qwen_runtime_client", lambda: client)

    result = tasks.classify_document_auto_gold.run(run["id"])

    assert result["status"] == "stale"
    assert client.calls == []
    assert repository.state["document_gold_labels"] == []


def test_mineru_success_preserves_fine_type_targeting_and_queues_auto_gold(monkeypatch: pytest.MonkeyPatch):
    repository, document, version, _parse_result = repository_with_ocr_result()
    repository.state["ocr_parse_results"] = []
    document["currentOcrStatus"] = "排队中"
    version["ocrStatus"] = "排队中"
    job = repository.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        provider="mineru",
    )
    dispatches: list[str] = []
    fine_type_calls: list[str] = []

    def fake_mineru(current_job):
        current_job["classificationMarkdown"] = MARKDOWN
        current_job["classificationMarkdownSha256"] = "sha256:" + hashlib.sha256(MARKDOWN.encode("utf-8")).hexdigest()
        return {
            "parseResultId": "PARSE-MINERU-AUTO-GOLD",
            "status": "success",
            "outcomeStatus": "completed",
            "profileId": "qualification_certificate_v1",
            "documentType": "qualification_certificate",
            "fragments": [{"pageNo": 1, "text": "许可证", "bbox": [0, 0, 10, 10]}],
            "fields": [],
            "tables": [],
            "seals": [],
            "metadata": {"provider": "mineru"},
        }

    monkeypatch.setattr(tasks, "repo", repository)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "refresh_ocr_worker_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "run_mineru_job", fake_mineru)
    monkeypatch.setattr(tasks, "_finalize_mineru_pipeline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "flush_state_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks.task_dispatcher, "dispatch_slice", lambda *_args, **_kwargs: {"mode": "disabled"})
    monkeypatch.setattr(
        tasks.task_dispatcher,
        "dispatch_document_classification",
        lambda run_id: dispatches.append(run_id) or {"mode": "celery", "taskId": "CLASSIFY-1"},
    )
    monkeypatch.setattr(
        tasks,
        "process_document_classification_and_targeting",
        lambda _repo, _project_id, current_document_id, _version_id, **_kwargs: (
            fine_type_calls.append(current_document_id)
            or {"status": "completed", "classification": {"materialTypeCode": "design_license"}}
        ),
    )

    result = tasks.mineru_ocr_extract.run(job["id"])

    assert result["status"] == "success"
    assert len(dispatches) == 1
    assert fine_type_calls == [document["id"]]
    run = repository.state["document_classification_runs"][0]
    assert dispatches[0] == run["id"]
    assert run["ocrMarkdown"] == MARKDOWN
    assert result["documentClassification"]["id"] == run["id"]
    assert result["documentIntelligence"]["autoGoldClassification"]["classificationRunId"] == run["id"]
