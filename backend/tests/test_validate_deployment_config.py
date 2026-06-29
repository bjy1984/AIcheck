from __future__ import annotations

from pathlib import Path

import yaml

from scripts.validate_deployment_config import DeploymentConfigValidator, default_value


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_deployment_config_validator_passes_repository_compose_with_warnings() -> None:
    validator = DeploymentConfigValidator(
        BACKEND_ROOT / "docker-compose.yml",
        BACKEND_ROOT / "config/litellm.yaml",
    )

    results = validator.run()

    assert results
    assert all(item.status in {"pass", "warn"} for item in results)
    assert any(item.name == "compose.services" and item.status == "pass" for item in results)
    assert any(item.name == "dockerfile.load" and item.status == "pass" for item in results)
    assert any(item.name == "dockerfile.build-contract" and item.status == "pass" for item in results)
    assert any(item.name == "dockerfile.ocr-load" and item.status == "pass" for item in results)
    assert any(item.name == "requirements.ocr-load" and item.status == "pass" for item in results)
    assert any(item.name == "requirements.ocr-baseline" and item.status == "pass" for item in results)
    assert any(item.name == "dockerfile.ocr-build-contract" and item.status == "pass" for item in results)
    assert any(item.name == "compose.depends-on" and item.status == "pass" for item in results)
    assert any(item.name == "compose.commands-ports" and item.status == "pass" for item in results)
    assert any(item.name == "compose.healthchecks" and item.status == "pass" for item in results)
    assert any(item.name == "compose.environment" and item.status == "pass" for item in results)
    assert any(item.name == "compose.ocr-artifacts" and item.status == "pass" for item in results)
    assert any(item.name == "compose.volumes" and item.status == "pass" for item in results)
    assert any(item.name == "litellm.config" and item.status == "pass" for item in results)


def test_deployment_config_validator_strict_production_passes_repository_compose() -> None:
    validator = DeploymentConfigValidator(
        BACKEND_ROOT / "docker-compose.yml",
        BACKEND_ROOT / "config/litellm.yaml",
        strict_production=True,
    )

    results = validator.run()

    assert all(item.status == "pass" for item in results)


def test_strict_production_fails_when_ocr_dependency_baseline_is_incomplete(tmp_path) -> None:
    incomplete_requirements = tmp_path / "requirements-ocr.txt"
    incomplete_requirements.write_text(
        "\n".join(
            [
                "PyMuPDF==1.27.2.3",
                "paddlepaddle==3.3.1",
                "paddlex[ocr]>=3.7.0,<3.8.0",
                "opencv-python-headless>=4.10,<5",
            ]
        ),
        encoding="utf-8",
    )
    validator = DeploymentConfigValidator(
        BACKEND_ROOT / "docker-compose.yml",
        BACKEND_ROOT / "config/litellm.yaml",
        dockerfile=BACKEND_ROOT / "Dockerfile",
        ocr_dockerfile=BACKEND_ROOT / "Dockerfile.ocr",
        ocr_requirements=incomplete_requirements,
        strict_production=True,
    )

    results = validator.run()

    assert any(
        item.name == "requirements.ocr-baseline" and item.status == "fail" and "paddleocr" in item.detail
        for item in results
    )
    assert not all(item.ok for item in results)


def test_strict_production_fails_when_ocr_service_uses_generic_image(tmp_path) -> None:
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        (BACKEND_ROOT / "docker-compose.yml").read_text(encoding="utf-8").replace(
            "dockerfile: Dockerfile.ocr",
            "dockerfile: Dockerfile",
            1,
        ),
        encoding="utf-8",
    )
    validator = DeploymentConfigValidator(
        compose_file,
        BACKEND_ROOT / "config/litellm.yaml",
        dockerfile=BACKEND_ROOT / "Dockerfile",
        ocr_dockerfile=BACKEND_ROOT / "Dockerfile.ocr",
        ocr_requirements=BACKEND_ROOT / "requirements-ocr.txt",
        strict_production=True,
    )

    results = validator.run()

    assert any(
        item.name == "compose.ocr-artifacts" and item.status == "fail" and "Dockerfile.ocr" in item.detail
        for item in results
    )
    assert not all(item.ok for item in results)


def test_strict_production_fails_when_litellm_healthcheck_only_checks_http_200(tmp_path) -> None:
    compose_file = tmp_path / "docker-compose.yml"
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    compose["services"]["litellm-service"]["healthcheck"]["test"] = [
        "CMD-SHELL",
        "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health', timeout=3).read()\"",
    ]
    compose_file.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
    validator = DeploymentConfigValidator(
        compose_file,
        BACKEND_ROOT / "config/litellm.yaml",
        dockerfile=BACKEND_ROOT / "Dockerfile",
        ocr_dockerfile=BACKEND_ROOT / "Dockerfile.ocr",
        ocr_requirements=BACKEND_ROOT / "requirements-ocr.txt",
        strict_production=True,
    )

    results = validator.run()

    assert any(
        item.name == "compose.healthchecks"
        and item.status == "fail"
        and "LITELLM_MASTER_KEY" in item.detail
        and "unhealthy providers" in item.detail
        for item in results
    )
    assert not all(item.ok for item in results)


def test_strict_production_fails_when_litellm_proxy_bypass_is_missing(tmp_path) -> None:
    compose_file = tmp_path / "docker-compose.yml"
    compose = yaml.safe_load((BACKEND_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    compose["services"]["litellm-service"]["environment"].pop("NO_PROXY")
    compose["services"]["litellm-service"]["environment"]["no_proxy"] = "postgres"
    compose_file.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
    validator = DeploymentConfigValidator(
        compose_file,
        BACKEND_ROOT / "config/litellm.yaml",
        dockerfile=BACKEND_ROOT / "Dockerfile",
        ocr_dockerfile=BACKEND_ROOT / "Dockerfile.ocr",
        ocr_requirements=BACKEND_ROOT / "requirements-ocr.txt",
        strict_production=True,
    )

    results = validator.run()

    assert any(
        item.name == "compose.environment"
        and item.status == "fail"
        and "NO_PROXY" in item.detail
        and "Prisma query-engine" in item.detail
        for item in results
    )
    assert not all(item.ok for item in results)


def test_default_value_extracts_compose_fallback() -> None:
    assert default_value("${AICHECK_REQUIRE_AUTH:-true}") == "true"
    assert default_value("${OPENAI_API_KEY:-}") == ""
    assert default_value("${OPENAI_API_KEY:?OPENAI_API_KEY is required}") == "${OPENAI_API_KEY:?OPENAI_API_KEY is required}"
    assert default_value("literal") == "literal"
