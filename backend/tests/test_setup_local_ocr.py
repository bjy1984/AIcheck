from __future__ import annotations

from pathlib import Path

from scripts.setup_local_ocr import (
    LocalOcrInstaller,
    parse_colima_mount_locations,
    path_is_covered_by_mount,
    render_text,
    summarize,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def create_bundled_models(root: Path) -> None:
    for name in ("paddleocr", "paddlex", "paddleocr-vl", "docling"):
        path = root / name
        path.mkdir(parents=True)
        (path / ".keep").write_text(name, encoding="utf-8")


def write_local_ocr_env(path: Path, models: Path, *, storage_prefix: Path | None = None) -> None:
    path.write_text(
        "\n".join(
            [
                f"AICHECK_OCR_MODELS_HOST_PATH={models}",
                "AICHECK_MINIO_SECRET_KEY=strong-minio-secret",
                "AICHECK_POSTGRES_PASSWORD=strong-postgres-secret",
                "AICHECK_POSTGRES_USER=aicheck",
                "AICHECK_POSTGRES_DB=aicheck",
                "AICHECK_MINIO_ACCESS_KEY=aicheck",
                "AICHECK_TASK_DISPATCH=celery",
                "AICHECK_OCR_ALLOW_PLACEHOLDER=false",
                "AICHECK_OCR_OFFLINE_ONLY=true",
                "AICHECK_OCR_DISABLE_NETWORK=true",
                "AICHECK_OCR_SUBPROCESS_PYTHON=/usr/local/bin/python",
                f"AICHECK_DOCKER_STORAGE_HOST_PREFIX={storage_prefix or Path('/Volumes/7up')}",
            ]
        ),
        encoding="utf-8",
    )


def write_colima_mount_config(storage_root: Path, mount: Path) -> None:
    config = storage_root / "default" / "colima.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "\n".join(
            [
                "mounts:",
                f"  - location: {mount}",
                "    writable: true",
                "",
            ]
        ),
        encoding="utf-8",
    )


def make_fake_docker_run(storage_root: Path):
    def fake_docker_run(command, *, cwd=BACKEND_ROOT, timeout=600):
        if Path(command[0]).name == "docker" and command[-1] == "--version":
            return True, "Docker version 28.0.0"
        if Path(command[0]).name == "docker" and command[1:3] == ["compose", "version"]:
            return True, "Docker Compose version v2.35.0"
        if Path(command[0]).name == "docker" and command[1:3] == ["context", "show"]:
            return True, "colima"
        if Path(command[0]).name == "docker" and command[1:3] == ["context", "inspect"]:
            return (
                True,
                (
                    '{"Name":"colima","Endpoints":{"docker":{"Host":'
                    f'"unix://{storage_root}/default/docker.sock"' + "}}}"
                ),
            )
        if Path(command[0]).name == "docker" and command[1:3] == ["compose", "--env-file"]:
            return True, "started"
        return False, "unexpected command"

    return fake_docker_run


def test_local_ocr_installer_builds_compose_command(tmp_path, monkeypatch) -> None:
    models = tmp_path / "models"
    create_bundled_models(models)
    storage_root = tmp_path / "docker" / ".colima"
    write_colima_mount_config(storage_root, tmp_path)
    env_file = tmp_path / ".env"
    write_local_ocr_env(env_file, models, storage_prefix=tmp_path)
    monkeypatch.setattr(
        "scripts.setup_local_ocr.shutil.which",
        lambda name: "/usr/local/bin/docker",
    )
    monkeypatch.setattr(
        "scripts.setup_local_ocr.run_command",
        make_fake_docker_run(storage_root),
    )
    monkeypatch.setattr("scripts.setup_local_ocr.tcp_port_open", lambda host, port: True)

    installer = LocalOcrInstaller(
        env_file=env_file,
        compose_file=BACKEND_ROOT / "docker-compose.local-ocr.yml",
        env={},
    )
    checks = installer.run_checks()

    assert all(item.ok for item in checks)
    start_command = next(item for item in checks if item.name == "start.command")
    assert start_command.data
    assert "docker-compose.local-ocr.yml" in str(start_command.data["command"])
    assert "local-ocr-service" in str(start_command.data["command"])
    assert "local-ocr-worker" in str(start_command.data["command"])
    assert summarize(checks)["fail"] == 0
    assert "AIcheck Local OCR Setup" in render_text(checks)


def test_local_ocr_installer_can_start_service_without_worker(tmp_path, monkeypatch) -> None:
    models = tmp_path / "models"
    create_bundled_models(models)
    storage_root = tmp_path / "docker" / ".colima"
    write_colima_mount_config(storage_root, tmp_path)
    env_file = tmp_path / ".env"
    write_local_ocr_env(env_file, models, storage_prefix=tmp_path)
    commands: list[list[str]] = []
    fake_run = make_fake_docker_run(storage_root)

    def capture_run(command, *, cwd=BACKEND_ROOT, timeout=600):
        commands.append(command)
        return fake_run(command, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(
        "scripts.setup_local_ocr.shutil.which",
        lambda name: "/usr/local/bin/docker",
    )
    monkeypatch.setattr("scripts.setup_local_ocr.run_command", capture_run)
    monkeypatch.setattr("scripts.setup_local_ocr.tcp_port_open", lambda host, port: True)

    installer = LocalOcrInstaller(
        env_file=env_file,
        compose_file=BACKEND_ROOT / "docker-compose.local-ocr.yml",
        include_worker=False,
        env={},
    )
    installer.run_checks()
    result = installer.start()

    assert result.status == "pass"
    up_command = next(command for command in commands if "up" in command)
    assert "local-ocr-service" in up_command
    assert "local-ocr-worker" not in up_command


def test_local_ocr_installer_blocks_bad_dispatch_and_flags(tmp_path, monkeypatch) -> None:
    models = tmp_path / "models"
    create_bundled_models(models)
    storage_root = tmp_path / "docker" / ".colima"
    write_colima_mount_config(storage_root, tmp_path)
    env_file = tmp_path / ".env"
    write_local_ocr_env(env_file, models, storage_prefix=tmp_path)
    env_file.write_text(
        env_file.read_text(encoding="utf-8")
        + "\nAICHECK_TASK_DISPATCH=disabled\nAICHECK_OCR_ALLOW_PLACEHOLDER=true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.setup_local_ocr.shutil.which",
        lambda name: "/usr/local/bin/docker",
    )
    monkeypatch.setattr(
        "scripts.setup_local_ocr.run_command",
        make_fake_docker_run(storage_root),
    )
    monkeypatch.setattr("scripts.setup_local_ocr.tcp_port_open", lambda host, port: True)

    installer = LocalOcrInstaller(
        env_file=env_file,
        compose_file=BACKEND_ROOT / "docker-compose.local-ocr.yml",
        env={},
    )
    checks = installer.run_checks()
    start_result = installer.start()

    assert next(item for item in checks if item.name == "env.dispatch").status == "fail"
    assert next(item for item in checks if item.name == "env.ocr-flags").status == "fail"
    assert start_result.status == "fail"
    assert start_result.data and "env.dispatch" in start_result.data["blockers"]


def test_local_ocr_installer_blocks_colima_storage_outside_7up(tmp_path, monkeypatch) -> None:
    models = tmp_path / "models"
    create_bundled_models(models)
    env_file = tmp_path / ".env"
    write_local_ocr_env(env_file, models)

    def fake_run(command, *, cwd=BACKEND_ROOT, timeout=600):
        if Path(command[0]).name == "docker" and command[-1] == "--version":
            return True, "Docker version 28.0.0"
        if Path(command[0]).name == "docker" and command[1:3] == ["compose", "version"]:
            return True, "Docker Compose version v2.35.0"
        if Path(command[0]).name == "docker" and command[1:3] == ["context", "show"]:
            return True, "colima"
        if Path(command[0]).name == "docker" and command[1:3] == ["context", "inspect"]:
            return (
                True,
                (
                    '{"Name":"colima","Endpoints":{"docker":{"Host":'
                    '"unix:///Users/test/.colima/default/docker.sock"}}}'
                ),
            )
        return True, "ok"

    monkeypatch.setattr(
        "scripts.setup_local_ocr.shutil.which",
        lambda name: "/usr/local/bin/docker",
    )
    monkeypatch.setattr("scripts.setup_local_ocr.run_command", fake_run)
    monkeypatch.setattr("scripts.setup_local_ocr.tcp_port_open", lambda host, port: True)

    installer = LocalOcrInstaller(
        env_file=env_file,
        compose_file=BACKEND_ROOT / "docker-compose.local-ocr.yml",
        env={},
    )
    checks = installer.run_checks()
    start_result = installer.start()

    storage = next(item for item in checks if item.name == "docker.storage")
    assert storage.status == "fail"
    assert storage.remediation
    assert "mv ~/.colima" in storage.remediation[1]
    assert start_result.status == "fail"
    assert start_result.data and "docker.storage" in start_result.data["blockers"]


def test_colima_mount_parser_detects_model_path_coverage(tmp_path) -> None:
    storage_root = tmp_path / "docker" / ".colima"
    mounted_root = tmp_path / "mounted"
    model_path = mounted_root / "aicheck-ocr-models" / "official_models"
    write_colima_mount_config(storage_root, mounted_root)

    mounts = parse_colima_mount_locations(storage_root / "default" / "colima.yaml")

    assert mounts == [mounted_root.resolve(strict=False)]
    assert path_is_covered_by_mount(model_path, mounts)
    assert not path_is_covered_by_mount(tmp_path / "other" / "models", mounts)


def test_local_ocr_compose_is_decoupled_from_full_stack_services() -> None:
    compose_text = (BACKEND_ROOT / "docker-compose.local-ocr.yml").read_text(encoding="utf-8")

    assert "local-ocr-service:" in compose_text
    assert "local-ocr-worker:" in compose_text
    assert "api-service:" not in compose_text
    assert "litellm-service:" not in compose_text
    assert "http://local-ocr-service:8010" in compose_text
