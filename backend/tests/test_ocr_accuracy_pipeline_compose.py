from __future__ import annotations

from pathlib import Path

import yaml


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_accuracy_pipeline_timeouts_allow_cpu_heavy_engines_to_finish() -> None:
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.accuracy-pipeline.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    ocr_environment = services["ocr-service"]["environment"]

    assert int(ocr_environment["AICHECK_PP_STRUCTURE_TIMEOUT"]) >= 600
    assert int(ocr_environment["AICHECK_PADDLEX_SEAL_TIMEOUT"]) >= 600

    for service_name in (
        "worker-service",
        "cpu-heavy-worker-service",
        "ocr-local-worker-service",
        "ocr-remote-worker-service",
        "llm-remote-worker-service",
    ):
        environment = services[service_name]["environment"]
        assert int(environment["AICHECK_OCR_JOB_TIMEOUT_SECONDS"]) > int(
            ocr_environment["AICHECK_PP_STRUCTURE_TIMEOUT"]
        )
        assert int(environment["AICHECK_OCR_PARSE_TIMEOUT_SECONDS"]) > int(
            ocr_environment["AICHECK_PADDLEX_SEAL_TIMEOUT"]
        )


def test_accuracy_pipeline_official_ocr_workers_and_runtime_are_isolated() -> None:
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.accuracy-pipeline.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert "ocr.parse_document" in services["ocr-local-worker-service"]["command"]
    assert "--concurrency=1" in services["ocr-local-worker-service"]["command"]
    assert "ocr.remote" in services["ocr-remote-worker-service"]["command"]
    assert "--concurrency=2" in services["ocr-remote-worker-service"]["command"]
    worker_env = services["ocr-remote-worker-service"]["environment"]
    assert worker_env["AICHECK_OCR_PROVIDER_MODE"].endswith("hybrid_auto}")
    assert worker_env["AICHECK_OCR_USE_JOB_API"] == "false"
    assert worker_env["AICHECK_OCR_MAX_LONG_SIDE"] == "1920"
    assert worker_env["AICHECK_OCR_ALLOW_LOCAL_HEAVY_FALLBACK"] == "false"
