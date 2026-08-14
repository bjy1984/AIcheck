from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from apps.ocr_service.routing import seal_text_variants, structure_variants
from apps.worker import tasks as worker_tasks
from libs.aliyun_ocr import (
    AliyunOcrRetryableError,
    AliyunQwenOcrClient,
    OfficialOcrCircuitBreaker,
    advanced_fragments,
    grounded_kie_fields,
)
from libs.integrations import task_dispatcher
from libs.ocr_accuracy_pipeline import render_pages
from libs.ocr_runtime import (
    ocr_runtime_config,
    ocr_runtime_public_config,
    official_ocr_primary_enabled,
)
from libs.official_ocr_pipeline import (
    detect_color_seal_rois,
    official_ocr_extract,
    selected_source_pages,
)


def official_env(**overrides: str) -> dict[str, str]:
    values = {
        "AICHECK_OCR_PROVIDER_MODE": "hybrid_auto",
        "AICHECK_ALIYUN_OCR_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "AICHECK_ALIYUN_OCR_API_KEY": "test-key",
    }
    values.update(overrides)
    return values


def test_ocr_runtime_is_redacted_and_clamps_render_size() -> None:
    runtime = ocr_runtime_config(
        env=official_env(AICHECK_OCR_MAX_LONG_SIDE="2600"),
        validate=True,
    )
    public = ocr_runtime_public_config(env=official_env())
    assert runtime["mode"] == "hybrid_auto"
    assert runtime["render"]["maxLongSide"] == 1920
    assert runtime["render"]["maxPagesPerBatch"] == 10
    assert runtime["render"]["maxDocumentPages"] == 200
    assert runtime["render"]["maxCostCnyPerDocument"] == 5.0
    assert runtime["official"]["maxOutputTokens"] == 4096
    assert public["apiKeyConfigured"] is True
    assert "apiKey" not in public
    assert public["allowLocalHeavyFallback"] is False
    assert public["allowSilentProviderFallback"] is False


def test_official_runtime_requires_key() -> None:
    with pytest.raises(RuntimeError, match="AICHECK_ALIYUN_OCR_API_KEY"):
        ocr_runtime_config(
            env={
                "AICHECK_OCR_PROVIDER_MODE": "official",
                "AICHECK_ALIYUN_OCR_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            },
            validate=True,
        )


def test_empty_env_mapping_does_not_inherit_process_secret(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_ALIYUN_OCR_API_KEY", "process-secret")
    runtime = ocr_runtime_config(env={})
    assert runtime["official"]["apiKeyConfigured"] is False


def test_official_ocr_is_primary_only_in_active_pipeline_mode() -> None:
    runtime = ocr_runtime_config(env=official_env(), validate=True)
    assert official_ocr_primary_enabled("active", runtime) is True
    assert official_ocr_primary_enabled("shadow", runtime) is False


def test_shadow_official_ocr_never_applies_business_state_directly() -> None:
    parse_source = inspect.getsource(worker_tasks.parse_document.run)
    official_source = inspect.getsource(worker_tasks.ocr_pipeline_official_extract.run)
    assert "official_shadow" in parse_source
    assert "officialOcrJobRecordId" in parse_source
    assert "pipeline_apply_result" not in official_source


def test_compatible_client_uses_chat_completions_and_1920_image(tmp_path: Path) -> None:
    image_path = tmp_path / "large.png"
    Image.new("RGB", (2400, 1200), "white").save(image_path)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "req-ocr-1",
                "choices": [
                    {
                        "message": {
                            "content": [
                                {
                                    "ocr_result": {
                                        "words_info": [
                                            {
                                                "text": "TS123456",
                                                "location": [10, 10, 110, 10, 110, 30, 10, 30],
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                ],
                "usage": {"input_tokens": 2500, "output_tokens": 20, "total_tokens": 2520},
            },
        )

    runtime = ocr_runtime_config(env=official_env(), validate=True)
    client = AliyunQwenOcrClient(
        runtime=runtime,
        transport=httpx.MockTransport(handler),
        circuit_breaker=OfficialOcrCircuitBreaker(3, 60),
    )
    result = client.call(image_path, task="advanced_recognition", page_no=1)

    assert captured["url"].endswith("/compatible-mode/v1/chat/completions")
    payload = captured["payload"]
    assert payload["ocr_options"] == {"task": "advanced_recognition"}
    image_payload = payload["messages"][0]["content"][0]
    assert image_payload["type"] == "image_url"
    assert result["input"]["width"] == 1920
    assert result["input"]["height"] == 960
    assert result["requestId"] == "req-ocr-1"
    assert result["costCny"] > 0


def test_native_client_uses_dashscope_payload_and_surfaces_retry_after(tmp_path: Path) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    requests: list[dict] = []

    def success_handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "request_id": "native-1",
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {
                                        "ocr_result": {
                                            "words_info": [
                                                {
                                                    "text": "ok",
                                                    "location": [1, 1, 20, 1, 20, 10, 1, 10],
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        )

    runtime = ocr_runtime_config(
        env=official_env(
            AICHECK_ALIYUN_OCR_BASE_URL=(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
                "multimodal-generation/generation"
            )
        ),
        validate=True,
    )
    client = AliyunQwenOcrClient(
        runtime=runtime,
        transport=httpx.MockTransport(success_handler),
        circuit_breaker=OfficialOcrCircuitBreaker(3, 60),
    )
    result = client.call(image_path, task="advanced_recognition", page_no=1)
    assert requests[0]["parameters"]["max_tokens"] == 4096
    assert requests[0]["parameters"]["ocr_options"]["task"] == "advanced_recognition"
    assert len(advanced_fragments(result)) == 1

    def rate_limit_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "7"},
            json={"code": "Throttling", "message": "retry later"},
        )

    limited = AliyunQwenOcrClient(
        runtime=runtime,
        transport=httpx.MockTransport(rate_limit_handler),
        circuit_breaker=OfficialOcrCircuitBreaker(3, 60),
    )
    with pytest.raises(AliyunOcrRetryableError) as captured:
        limited.call(image_path, task="advanced_recognition", page_no=1)
    assert captured.value.status_code == 429
    assert captured.value.retry_after == 7


def test_kie_value_requires_matching_advanced_candidate() -> None:
    advanced = {
        "pageNo": 1,
        "ocrResult": {
            "words_info": [
                {"text": "证书号 TS123456", "location": [1, 2, 101, 2, 101, 22, 1, 22]}
            ]
        },
        "text": "",
    }
    fragments = advanced_fragments(advanced)
    fields = grounded_kie_fields(
        [
            {
                "pageNo": 1,
                "ocrResult": {"kv_result": {"certificate_no": "TS123456", "expiry": "2099-01-01"}},
                "text": "",
            }
        ],
        fragments,
    )
    by_code = {item["fieldCode"]: item for item in fields}
    assert by_code["certificate_no"]["formalEvidenceEligible"] is True
    assert by_code["certificate_no"]["sourceCandidateIds"]
    assert by_code["expiry"]["formalEvidenceEligible"] is False
    assert by_code["expiry"]["advisoryOnly"] is True


def test_official_pipeline_runs_one_table_call_per_page(tmp_path: Path) -> None:
    source = tmp_path / "report.png"
    Image.new("RGB", (1200, 800), "white").save(source)

    class FakeClient:
        def __init__(self) -> None:
            self.tasks: list[str] = []

        def call(self, _path: Path, *, task: str, page_no: int, result_schema=None, model=None):
            self.tasks.append(task)
            base = {
                "provider": "aliyun_model_studio",
                "model": "qwen3.5-ocr",
                "task": task,
                "pageNo": page_no,
                "requestId": f"req-{task}",
                "usage": {"inputTokens": 100, "outputTokens": 10, "totalTokens": 110},
                "costCny": 0.0001,
                "durationMs": 5,
                "input": {"width": 1200, "height": 800, "sha256": "abc"},
                "text": "",
                "ocrResult": None,
            }
            if task == "advanced_recognition":
                base["ocrResult"] = {
                    "words_info": [
                        {
                            "text": "TS123456",
                            "location": [10, 10, 110, 10, 110, 30, 10, 30],
                        }
                    ]
                }
            elif task == "key_information_extraction":
                base["ocrResult"] = {"kv_result": {"certificate_no": "TS123456"}}
            elif task == "table_parsing":
                base["text"] = "<table><tr><td>TS123456</td></tr></table>"
            return base

    client = FakeClient()
    profile = {
        "profileId": "test_profile",
        "documentType": "test",
        "requiredFields": ["certificate_no"],
        "requiredTables": ["items"],
        "sealRules": {"required": False},
        "structuredExtraction": {
            "fields": ["certificate_no"],
            "fieldDefinitions": {"certificate_no": "Certificate number"},
            "maxPages": 1,
        },
    }
    page_cache: dict[int, list[dict]] = {}

    def completed(page_no: int, _completed: int, _total: int, calls: list[dict]) -> None:
        page_cache[page_no] = calls

    result = official_ocr_extract(
        source,
        profile=profile,
        runtime=ocr_runtime_config(env=official_env(), validate=True),
        client=client,
        work_directory=tmp_path / "work",
        page_completed=completed,
    )
    assert page_cache[1]
    assert client.tasks == [
        "advanced_recognition",
        "key_information_extraction",
        "table_parsing",
    ]
    assert result["metadata"]["modelCallCount"] == 3
    assert result["fields"][0]["formalEvidenceEligible"] is True
    assert result["tables"][0]["formalEvidenceEligible"] is True
    assert result["tables"][0]["cells"][0]["sourceCandidateIds"]
    assert "TABLE_EVIDENCE_MISSING" not in result["quality"]["reasons"]

    cached_client = FakeClient()
    cached = official_ocr_extract(
        source,
        profile=profile,
        runtime=ocr_runtime_config(env=official_env(), validate=True),
        client=cached_client,
        work_directory=tmp_path / "work-cached",
        page_call_cache=page_cache,
    )
    assert cached_client.tasks == []
    assert cached["metadata"]["modelCallCount"] == 3


def test_color_seal_roi_detection_is_lightweight_and_bounded(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    source = tmp_path / "seal.png"
    image = np.full((800, 1200, 3), 255, dtype=np.uint8)
    cv2.circle(image, (900, 580), 90, (0, 0, 210), 16)
    assert cv2.imwrite(str(source), image)

    candidates = detect_color_seal_rois(source, tmp_path / "rois")
    assert 1 <= len(candidates) <= 2
    assert candidates[0]["color"] == "red"
    assert candidates[0]["path"].is_file()


def test_official_pdf_pages_are_not_silently_truncated(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    source = tmp_path / "long.pdf"
    document = fitz.open()
    for _ in range(35):
        document.new_page()
    document.save(source)
    document.close()

    runtime = ocr_runtime_config(env=official_env(), validate=True)
    assert selected_source_pages(source, {}, runtime) == list(range(1, 36))


def test_official_pdf_over_hard_limit_fails_closed(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    source = tmp_path / "too-long.pdf"
    document = fitz.open()
    for _ in range(4):
        document.new_page()
    document.save(source)
    document.close()
    runtime = ocr_runtime_config(
        env=official_env(
            AICHECK_ALIYUN_OCR_MAX_PAGES_PER_BATCH="3",
            AICHECK_ALIYUN_OCR_MAX_DOCUMENT_PAGES="3",
        ),
        validate=True,
    )
    with pytest.raises(Exception, match="exceeds official OCR limit"):
        selected_source_pages(source, {}, runtime)


def test_render_and_local_heavy_variants_are_bounded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_PROVIDER_MODE", "local")
    source = tmp_path / "large.png"
    Image.new("RGB", (2500, 1000), "white").save(source)
    rendered = render_pages(source, [1], tmp_path / "rendered")
    with Image.open(rendered[1]) as image:
        assert max(image.size) == 1920

    variants = [
        {"variantId": "page_1_original", "pageNo": 1, "purpose": "text"},
        {"variantId": "page_1_gray_clahe", "pageNo": 1, "purpose": "text"},
        {"variantId": "page_1_seal_color_mask", "pageNo": 1, "purpose": "seal"},
    ]
    quality = {1: {"isLowQuality": False, "hasVisualSealCandidate": True}}
    routed_structure = structure_variants(variants, quality, profile={"requiredTables": ["items"]})
    routed_seal = seal_text_variants(
        variants,
        quality,
        profile={"sealRules": {"required": True}},
        include_mask=True,
    )
    assert len(routed_structure) == 1
    assert len(routed_seal) == 1
    assert routed_seal[0]["purpose"] == "seal"


def test_dispatcher_routes_ocr_prepare_to_provider_neutral_queue(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    monkeypatch.setenv("AICHECK_OCR_PROVIDER_MODE", "hybrid_auto")
    monkeypatch.setenv("AICHECK_ALIYUN_OCR_API_KEY", "test-key")
    captured: dict = {}

    def apply_async(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="task-1")

    from apps.worker import tasks

    monkeypatch.setattr(tasks.parse_document, "apply_async", apply_async)
    result = task_dispatcher.dispatch_parse_document("DOC-1", "VER-1", "minio://documents/a.pdf", "a.pdf")
    assert result["queue"] == "ocr.parse_document"
    assert captured["queue"] == "ocr.parse_document"
