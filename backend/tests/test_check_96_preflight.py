from __future__ import annotations

import subprocess
from dataclasses import asdict
from pathlib import Path

from scripts.check_96_preflight import (
    PRODUCTION_FLAG_DEFAULTS,
    REQUIRED_ENV,
    PreflightChecker,
    parse_env_file,
    render_text,
    summarize,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def write_env(path: Path, agentdesign: Path, models: Path) -> None:
    path.write_text(
        "\n".join(
            [
                f"AICHECK_AGENTDESIGN_HOST_PATH={agentdesign}",
                f"AICHECK_OCR_MODELS_HOST_PATH={models}",
                "AICHECK_MINIO_SECRET_KEY=strong-minio-secret",
                "AICHECK_JWT_SECRET=strong-jwt-secret-with-more-than-random-text",
                "LITELLM_API_KEY=sk-litellm-master",
                "LITELLM_POSTGRES_PASSWORD=strong-postgres-secret",
                "OPENAI_API_KEY=sk-provider",
                "AICHECK_REQUIRE_AUTH=true",
                "AICHECK_ENABLE_DEMO_USERS=false",
                "AICHECK_OCR_ALLOW_PLACEHOLDER=false",
                "AICHECK_OCR_OFFLINE_ONLY=true",
                "AICHECK_OCR_DISABLE_NETWORK=true",
                "AICHECK_MONGO_TRANSACTIONS=true",
            ]
        ),
        encoding="utf-8",
    )


def create_agentdesign(root: Path) -> None:
    (root / "mvp-system" / "backend" / "seal_ocr").mkdir(parents=True)
    (root / "requirements").mkdir()
    (root / "mvp-system" / "backend" / "seal_ocr" / "pipeline.py").write_text("", encoding="utf-8")
    (root / "requirements" / "mvp-ocr.txt").write_text("paddleocr\n", encoding="utf-8")


def create_ocr_models(root: Path) -> None:
    for name in ["paddleocr", "paddlex", "paddleocr-vl", "docling"]:
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / ".keep").write_text(name, encoding="utf-8")


def test_env_example_covers_preflight_required_variables() -> None:
    values = parse_env_file(BACKEND_ROOT / ".env.example")

    missing_required = sorted(key for key in REQUIRED_ENV if key not in values)
    missing_flags = sorted(key for key in PRODUCTION_FLAG_DEFAULTS if key not in values)

    assert missing_required == []
    assert missing_flags == []
    for key, expected in PRODUCTION_FLAG_DEFAULTS.items():
        assert values[key] == expected


def test_parse_env_file_handles_quotes_and_comments(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # ignored
        AICHECK_JWT_SECRET="quoted secret"
        LITELLM_API_KEY='single quoted'
        OPENAI_API_KEY=plain
        """,
        encoding="utf-8",
    )

    values = parse_env_file(env_file)

    assert values["AICHECK_JWT_SECRET"] == "quoted secret"
    assert values["LITELLM_API_KEY"] == "single quoted"
    assert values["OPENAI_API_KEY"] == "plain"


def test_preflight_fails_without_runtime_and_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("scripts.check_96_preflight.shutil.which", lambda name: None)

    results = PreflightChecker(env_file=tmp_path / ".env", strict_production=True, env={}).run()

    docker = next(item for item in results if item.name == "runtime.docker")
    env_file = next(item for item in results if item.name == "env.file")
    command_ready = next(item for item in results if item.name == "probe.command-ready")

    assert docker.status == "fail"
    assert docker.remediation
    assert any("docker --version" in step for step in docker.remediation)
    assert env_file.status == "fail"
    assert env_file.remediation
    assert any("cp .env.example .env" in step for step in env_file.remediation)
    assert command_ready.status == "fail"
    assert command_ready.data and "runtime.docker" in command_ready.data["blockers"]
    assert command_ready.remediation

    text = render_text(results)
    payload = {
        "ok": all(item.ok for item in results),
        "summary": summarize(results),
        "checks": [asdict(item) for item in results],
    }

    assert "remediation: Verify `docker --version` succeeds" in text
    assert payload["ok"] is False
    assert payload["summary"]["fail"] >= 1
    assert any(
        check["name"] == "env.file" and check["remediation"] and "cp .env.example .env" in check["remediation"][0]
        for check in payload["checks"]
    )


def test_preflight_passes_with_env_and_mocked_docker(tmp_path, monkeypatch) -> None:
    agentdesign = tmp_path / "agentdesign"
    models = tmp_path / "models"
    create_agentdesign(agentdesign)
    create_ocr_models(models)
    env_file = tmp_path / ".env"
    write_env(env_file, agentdesign, models)
    monkeypatch.setattr("scripts.check_96_preflight.shutil.which", lambda name: "/usr/local/bin/docker")
    monkeypatch.setattr("scripts.check_96_preflight.tcp_port_open", lambda port: False)

    def fake_run(command, check, capture_output, text, timeout):
        return subprocess.CompletedProcess(command, 0, stdout="Docker version 28.0.0", stderr="")

    monkeypatch.setattr("scripts.check_96_preflight.subprocess.run", fake_run)

    results = PreflightChecker(env_file=env_file, strict_production=True, env={}).run()

    assert all(item.ok for item in results)
    assert any(item.name == "probe.command-ready" and item.status == "pass" for item in results)


def test_strict_preflight_rejects_placeholders(tmp_path, monkeypatch) -> None:
    agentdesign = tmp_path / "agentdesign"
    models = tmp_path / "models"
    create_agentdesign(agentdesign)
    create_ocr_models(models)
    env_file = tmp_path / ".env"
    write_env(env_file, agentdesign, models)
    env_file.write_text(
        env_file.read_text(encoding="utf-8").replace("sk-provider", "replace-with-provider-api-key"),
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.check_96_preflight.shutil.which", lambda name: "/usr/local/bin/docker")

    def fake_run(command, check, capture_output, text, timeout):
        return subprocess.CompletedProcess(command, 0, stdout="Docker version 28.0.0", stderr="")

    monkeypatch.setattr("scripts.check_96_preflight.subprocess.run", fake_run)

    results = PreflightChecker(env_file=env_file, strict_production=True, env={}).run()

    assert any(
        item.name == "env.required"
        and item.status == "fail"
        and "OPENAI_API_KEY" in item.detail
        and item.remediation
        and any("OPENAI_API_KEY" in step for step in item.remediation)
        for item in results
    )


def test_strict_preflight_rejects_weak_internal_secrets(tmp_path, monkeypatch) -> None:
    agentdesign = tmp_path / "agentdesign"
    models = tmp_path / "models"
    create_agentdesign(agentdesign)
    create_ocr_models(models)
    env_file = tmp_path / ".env"
    write_env(env_file, agentdesign, models)
    env_file.write_text(
        env_file.read_text(encoding="utf-8")
        .replace("strong-jwt-secret-with-more-than-random-text", "short")
        .replace("strong-postgres-secret", "aaaaaaaaaaaaaaaa"),
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.check_96_preflight.shutil.which", lambda name: "/usr/local/bin/docker")
    monkeypatch.setattr("scripts.check_96_preflight.tcp_port_open", lambda port: False)

    def fake_run(command, check, capture_output, text, timeout):
        return subprocess.CompletedProcess(command, 0, stdout="Docker version 28.0.0", stderr="")

    monkeypatch.setattr("scripts.check_96_preflight.subprocess.run", fake_run)

    results = PreflightChecker(env_file=env_file, strict_production=True, env={}).run()
    secret_strength = next(item for item in results if item.name == "env.secret-strength")
    command_ready = next(item for item in results if item.name == "probe.command-ready")

    assert secret_strength.status == "fail"
    assert secret_strength.data
    assert "AICHECK_JWT_SECRET" in secret_strength.data["problems"]
    assert "LITELLM_POSTGRES_PASSWORD" in secret_strength.data["problems"]
    assert any("Regenerate AICHECK_JWT_SECRET" in step for step in secret_strength.remediation or [])
    assert command_ready.status == "fail"
    assert command_ready.data and "env.secret-strength" in command_ready.data["blockers"]
