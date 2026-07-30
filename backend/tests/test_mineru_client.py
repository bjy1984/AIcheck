from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from libs.integrations.mineru_client import (
    MinerUClient,
    MinerUConfig,
    MinerUJobFailed,
    MinerUProtocolError,
    load_mineru_config,
)


def _config(**overrides: object) -> MinerUConfig:
    values: dict[str, object] = {
        "base_url": "https://mineru.net",
        "api_key": "sk-test-secret",
        "model_version": "vlm",
        "request_timeout_seconds": 5,
        "poll_interval_seconds": 0,
        "job_timeout_seconds": 5,
        "max_download_bytes": 1024 * 1024,
    }
    values.update(overrides)
    return MinerUConfig(**values)  # type: ignore[arg-type]


def test_submit_url_uses_precise_v4_vlm_contract() -> None:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={"code": 0, "data": {"task_id": "TASK-1"}, "msg": "ok"},
        )

    client = MinerUClient(_config(), transport=httpx.MockTransport(handler))
    submission = client.submit_url(
        "https://files.example/document.pdf",
        data_id="OCRJOB-1",
        options={
            "language": "ch",
            "pageRanges": "1-3",
            "noCache": True,
            "cacheTolerance": 12,
            "unexpected": "must-not-pass-through",
        },
    )

    request = seen["request"]
    assert request.url.path == "/api/v4/extract/task"
    assert request.headers["Authorization"] == "Bearer sk-test-secret"
    body = json.loads(request.content)
    assert body == {
        "url": "https://files.example/document.pdf",
        "data_id": "OCRJOB-1",
        "model_version": "vlm",
        "is_ocr": True,
        "enable_formula": True,
        "enable_table": True,
        "language": "ch",
        "page_ranges": "1-3",
        "no_cache": True,
        "cache_tolerance": 12,
    }
    assert submission == {"kind": "task", "providerTaskId": "TASK-1"}


def test_submit_file_puts_bytes_without_content_type(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-test")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["files"] == [
                {"name": "scan.pdf", "data_id": "OCRJOB-1", "is_ocr": True}
            ]
            assert body["model_version"] == "vlm"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "BATCH-1",
                        "file_urls": ["https://upload.example/signed-secret"],
                    },
                    "msg": "ok",
                },
            )
        assert request.url.host == "upload.example"
        assert request.headers.get("Content-Type") is None
        return httpx.Response(200)

    client = MinerUClient(_config(), transport=httpx.MockTransport(handler))
    submission = client.submit_file(source, data_id="OCRJOB-1", options={})

    assert submission == {"kind": "batch", "providerTaskId": "BATCH-1"}
    assert seen[1].content == b"%PDF-test"


@pytest.mark.parametrize(
    ("submission", "expected_path", "response_data"),
    [
        (
            {"kind": "task", "providerTaskId": "TASK-1"},
            "/api/v4/extract/task/TASK-1",
            {"state": "done", "full_zip_url": "https://result.example/task.zip"},
        ),
        (
            {"kind": "batch", "providerTaskId": "BATCH-1"},
            "/api/v4/extract-results/batch/BATCH-1",
            {
                "extract_result": [
                    {
                        "state": "done",
                        "full_zip_url": "https://result.example/batch.zip",
                    }
                ]
            },
        ),
    ],
)
def test_wait_for_result_supports_task_and_batch(
    submission: dict[str, str],
    expected_path: str,
    response_data: dict[str, object],
) -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"code": 0, "data": response_data})

    client = MinerUClient(_config(), transport=httpx.MockTransport(handler))

    assert client.wait_for_result(submission) == {
        "state": "done",
        "full_zip_url": (
            "https://result.example/task.zip"
            if submission["kind"] == "task"
            else "https://result.example/batch.zip"
        ),
        "extract_progress": None,
    }
    assert seen_paths == [expected_path]


def test_wait_for_result_reports_progress_until_done() -> None:
    responses = iter(
        [
            {"state": "pending", "extract_progress": {"extracted_pages": 0}},
            {"state": "running", "extract_progress": {"extracted_pages": 1}},
            {"state": "converting", "extract_progress": {"extracted_pages": 2}},
            {
                "state": "done",
                "extract_progress": {"extracted_pages": 2},
                "full_zip_url": "https://result.example/result.zip",
            },
        ]
    )
    progress: list[dict[str, object]] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"code": 0, "data": next(responses)}
        )

    client = MinerUClient(_config(), transport=httpx.MockTransport(handler))
    result = client.wait_for_result(
        {"kind": "task", "providerTaskId": "TASK-1"},
        progress_callback=progress.append,
    )

    assert result["state"] == "done"
    assert [item["state"] for item in progress] == [
        "pending",
        "running",
        "converting",
        "done",
    ]


def test_failed_provider_job_raises_safe_error() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "state": "failed",
                    "err_msg": "signed=https://secret.example&token=sk-test-secret",
                },
            },
        )
    )
    client = MinerUClient(_config(), transport=transport)

    with pytest.raises(MinerUJobFailed) as raised:
        client.wait_for_result({"kind": "task", "providerTaskId": "TASK-1"})

    assert str(raised.value) == "MinerU parsing failed."
    assert "sk-test-secret" not in str(raised.value)


@pytest.mark.parametrize(
    ("status_code", "provider_code", "retryable"),
    [
        (429, None, True),
        (503, None, True),
        (200, -10001, True),
        (200, -60007, True),
        (200, -60009, True),
        (200, "A0202", False),
    ],
)
def test_provider_and_http_errors_are_classified_and_sanitized(
    status_code: int,
    provider_code: int | str | None,
    retryable: bool,
) -> None:
    if provider_code is None:
        response_factory = lambda: httpx.Response(  # noqa: E731
            status_code, text="Token sk-test-secret invalid"
        )
    else:
        response_factory = lambda: httpx.Response(  # noqa: E731
            status_code,
            json={
                "code": provider_code,
                "msg": "Token sk-test-secret invalid",
            },
        )
    client = MinerUClient(
        _config(),
        transport=httpx.MockTransport(lambda _request: response_factory()),
    )

    with pytest.raises(MinerUProtocolError) as raised:
        client.submit_url(
            "https://files.example/document.pdf",
            data_id="JOB-1",
            options={},
        )

    assert "sk-test-secret" not in str(raised.value)
    assert raised.value.retryable is retryable
    if provider_code is not None:
        assert raised.value.code == str(provider_code)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"code": 0, "data": {}}),
    ],
)
def test_submit_url_rejects_malformed_responses(response: httpx.Response) -> None:
    client = MinerUClient(
        _config(),
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(MinerUProtocolError):
        client.submit_url(
            "https://files.example/document.pdf",
            data_id="JOB-1",
            options={},
        )


def test_done_without_zip_url_is_rejected() -> None:
    client = MinerUClient(
        _config(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"code": 0, "data": {"state": "done"}}
            )
        ),
    )

    with pytest.raises(MinerUProtocolError) as raised:
        client.wait_for_result({"kind": "task", "providerTaskId": "TASK-1"})

    assert raised.value.code == "MINERU_RESULT_URL_MISSING"


def test_download_result_enforces_byte_limit() -> None:
    client = MinerUClient(
        _config(max_download_bytes=4),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"12345")
        ),
    )

    with pytest.raises(MinerUProtocolError) as raised:
        client.download_result("https://result.example/result.zip")

    assert raised.value.code == "MINERU_DOWNLOAD_TOO_LARGE"


def test_load_config_requires_key_and_vlm_model() -> None:
    with pytest.raises(MinerUProtocolError) as missing:
        load_mineru_config({})
    assert missing.value.code == "MINERU_NOT_CONFIGURED"

    with pytest.raises(MinerUProtocolError) as invalid:
        load_mineru_config(
            {
                "AICHECK_MINERU_API_KEY": "test",
                "AICHECK_MINERU_MODEL_VERSION": "pipeline",
            }
        )
    assert invalid.value.code == "MINERU_MODEL_INVALID"

