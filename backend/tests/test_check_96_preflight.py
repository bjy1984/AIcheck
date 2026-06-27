from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_96_preflight import PreflightChecker, parse_env_file


def write_env(path: Path, agentdesign: Path) -> None:
    path.write_text(
        "\n".join(
            [
                f"AICHECK_AGENTDESIGN_HOST_PATH={agentdesign}",
                "AICHECK_MINIO_SECRET_KEY=strong-minio-secret",
                "AICHECK_JWT_SECRET=strong-jwt-secret-with-more-than-random-text",
                "LITELLM_API_KEY=sk-litellm-master",
                "LITELLM_POSTGRES_PASSWORD=strong-postgres-secret",
                "OPENAI_API_KEY=sk-provider",
                "AICHECK_REQUIRE_AUTH=true",
                "AICHECK_ENABLE_DEMO_USERS=false",
                "AICHECK_OCR_ALLOW_PLACEHOLDER=false",
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

    assert any(item.name == "runtime.docker" and item.status == "fail" for item in results)
    assert any(item.name == "env.file" and item.status == "fail" for item in results)
    assert any(item.name == "probe.command-ready" and item.status == "fail" for item in results)


def test_preflight_passes_with_env_and_mocked_docker(tmp_path, monkeypatch) -> None:
    agentdesign = tmp_path / "agentdesign"
    create_agentdesign(agentdesign)
    env_file = tmp_path / ".env"
    write_env(env_file, agentdesign)
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
    create_agentdesign(agentdesign)
    env_file = tmp_path / ".env"
    write_env(env_file, agentdesign)
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
        item.name == "env.required" and item.status == "fail" and "OPENAI_API_KEY" in item.detail
        for item in results
    )
