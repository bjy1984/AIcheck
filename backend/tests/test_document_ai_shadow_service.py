from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "deployment"
    / "document-ai-shadow"
    / "services"
    / "hybrid_service.py"
)


def load_service(monkeypatch):
    monkeypatch.setenv("DOCUMENT_AI_API_KEY", "shadow-test-key")
    module_name = "test_document_ai_hybrid_service"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, SERVICE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def metadata_header(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def base_metadata(selected_pages: list[int]) -> dict:
    return {
        "schemaVersion": "DocumentAiHybridExtractRequest@1",
        "runId": "DOCSH-SERVICE-1",
        "advisoryOnly": True,
        "selectedPageNos": selected_pages,
        "evidencePrior": {
            "schemaVersion": "EvidencePrior@2",
            "selectedPageNos": selected_pages,
            "candidates": [],
        },
        "structuredExtraction": {"fields": ["report_no"], "tables": []},
        "constraints": {"maxOutputTokens": 2048},
    }


def test_service_requires_bearer_auth(monkeypatch) -> None:
    service = load_service(monkeypatch)
    test_client = TestClient(service.app)

    response = test_client.get("/internal/doctor")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "DOCUMENT_AI_AUTH_REQUIRED"


def test_service_rejects_seven_selected_pages_before_inference(monkeypatch, tmp_path: Path) -> None:
    service = load_service(monkeypatch)
    service.UPLOAD_ROOT = tmp_path
    test_client = TestClient(service.app)
    payload = base_metadata([1, 2, 3, 4, 5, 6, 7])

    response = test_client.post(
        "/v1/hybrid/extract",
        headers={
            "Authorization": "Bearer shadow-test-key",
            "X-AICheck-Document-Ai-Metadata-B64": metadata_header(payload),
        },
        content=b"not-used",
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "SELECTED_PAGES_LIMIT"


def test_service_rejects_bad_image_without_calling_models(monkeypatch, tmp_path: Path) -> None:
    service = load_service(monkeypatch)
    service.UPLOAD_ROOT = tmp_path
    test_client = TestClient(service.app)
    payload = base_metadata([1])
    payload["fileName"] = "bad.png"

    response = test_client.post(
        "/v1/hybrid/extract",
        headers={
            "Authorization": "Bearer shadow-test-key",
            "X-AICheck-Document-Ai-Metadata-B64": metadata_header(payload),
        },
        content=b"invalid-image",
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "DOCUMENT_IMAGE_INVALID"


def test_queue_gate_rejects_third_waiting_request(monkeypatch) -> None:
    service = load_service(monkeypatch)
    gate = service.QueueGate()
    gate.active = 1
    gate.waiting = 2

    async def enter_queue():
        async with gate.slot():
            return True

    with pytest.raises(HTTPException) as error:
        asyncio.run(enter_queue())

    assert error.value.status_code == 429
    assert gate.waiting == 2


def test_service_enforces_conservative_prior_token_budget(monkeypatch) -> None:
    service = load_service(monkeypatch)
    payload = base_metadata([1])
    payload["evidencePrior"]["candidates"] = [
        {"candidateId": "EP2-X", "text": "文" * 12_100}
    ]

    with pytest.raises(HTTPException) as error:
        service.validate_request_metadata(payload)

    assert error.value.status_code == 400
    assert error.value.detail["code"] == "EVIDENCE_PRIOR_TOKEN_LIMIT"


def test_service_retries_invalid_json_with_field_only_template(monkeypatch, tmp_path: Path) -> None:
    service = load_service(monkeypatch)
    service.UPLOAD_ROOT = tmp_path
    service.queue_gate = service.QueueGate()
    monkeypatch.setattr(service, "render_selected_pages", lambda source, pages, run_dir: {1: source})
    monkeypatch.setattr(service, "difficult_rois", lambda prior, pages: [])

    async def no_paddle(crops):
        return "", None, []

    calls = []

    async def fake_nuextract(pages, metadata, prior, context, *, include_tables=True):
        calls.append(include_tables)
        if include_tables:
            return {"parsed": None, "elapsedSeconds": 1, "revision": "nu-rev"}
        return {
            "parsed": {"fields": {"report_no": {"value": "RT-001", "sourceCandidateIds": []}}},
            "elapsedSeconds": 2,
            "revision": "nu-rev",
        }

    monkeypatch.setattr(service, "paddle_supplement", no_paddle)
    monkeypatch.setattr(service, "call_nuextract", fake_nuextract)
    payload = base_metadata([1])
    payload["fileName"] = "sample.png"
    test_client = TestClient(service.app)

    response = test_client.post(
        "/v1/hybrid/extract",
        headers={
            "Authorization": "Bearer shadow-test-key",
            "X-AICheck-Document-Ai-Metadata-B64": metadata_header(payload),
        },
        content=b"mock-image",
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == [True, False]
    assert body["jsonRetryCount"] == 1
    assert body["tableExtractionDeferred"] is True
    assert body["inferenceTimeMs"] == 3000
    assert body["formalEvidenceReady"] is False
