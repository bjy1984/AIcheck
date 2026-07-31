from __future__ import annotations

from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.accuracy-pipeline.yml",
    "docker-compose.deploy.yml",
)


def _compose(name: str) -> dict:
    return yaml.safe_load((BACKEND / name).read_text(encoding="utf-8"))


def test_compose_files_isolate_mineru_secret_to_remote_worker() -> None:
    for name in COMPOSE_FILES:
        services = _compose(name)["services"]
        remote = services["ocr-remote-worker-service"]
        assert "ocr.remote" in remote["command"], name
        assert remote["environment"]["AICHECK_MINERU_API_KEY"].startswith(
            "${AICHECK_MINERU_API_KEY:"
        ), name
        assert remote["environment"]["AICHECK_MINERU_MODEL_VERSION"] == "vlm"
        for service_name, service in services.items():
            if service_name == "ocr-remote-worker-service":
                continue
            assert "AICHECK_MINERU_API_KEY" not in (
                service.get("environment") or {}
            ), f"{name}:{service_name}"


def test_local_ocr_service_remains_offline_without_mineru_configuration() -> None:
    for name in COMPOSE_FILES:
        environment = (
            _compose(name)["services"]["ocr-service"].get("environment") or {}
        )
        assert "AICHECK_MINERU_API_KEY" not in environment
        offline_value = environment.get(
            "AICHECK_OCR_OFFLINE_ONLY",
            "true",
        )
        assert offline_value is True or "true" in str(offline_value).lower()


def test_compose_workers_default_unified_ocr_to_mineru() -> None:
    for name in COMPOSE_FILES:
        services = _compose(name)["services"]
        worker_environment = services["worker-service"]["environment"]
        assert worker_environment[
            "AICHECK_OCR_DEFAULT_PROVIDER"
        ].endswith(":-mineru}"), name
        assert "AICHECK_MINERU_API_KEY" not in worker_environment, name
        assert "AICHECK_OCR_DEFAULT_PROVIDER" not in (
            services["ocr-service"].get("environment") or {}
        ), name
        consumers = [
            (service_name, service)
            for service_name, service in services.items()
            if "ocr.parse_document" in str(service.get("command") or "")
        ]
        assert consumers, f"{name}: no ocr.parse_document consumer"
        for service_name, service in consumers:
            environment = service.get("environment") or {}
            assert environment[
                "AICHECK_OCR_DEFAULT_PROVIDER"
            ].endswith(":-mineru}"), f"{name}:{service_name}"
            assert "AICHECK_MINERU_API_KEY" not in environment, (
                f"{name}:{service_name}"
            )


def test_env_example_documents_fixed_vlm_provider() -> None:
    text = (BACKEND / ".env.example").read_text(encoding="utf-8")

    assert "AICHECK_OCR_DEFAULT_PROVIDER=mineru" in text
    assert "AICHECK_MINERU_API_KEY=replace-with-mineru-api-key" in text
    assert "AICHECK_MINERU_MODEL_VERSION=vlm" in text
    assert "AICHECK_MINERU_BASE_URL=https://mineru.net" in text
