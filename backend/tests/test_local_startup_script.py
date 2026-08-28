from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_local_launcher_starts_independent_mineru_worker(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "start-local-dev.zsh"
    hermetic_env_file = tmp_path / "empty.env"
    hermetic_env_file.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "AICHECK_DEV_DRY_RUN": "true",
        "AICHECK_DEV_LOG_DIR": str(tmp_path),
        # 断言的是脚本的**默认姿态**（postgres 直连、无 celery/redis）。
        # 不隔离的话，开发者本机 backend/.env 里的 AICHECK_TASK_DISPATCH=celery
        # 会被 source 进来，把断言变成「测我的个人配置」。
        "AICHECK_DEV_ENV_FILE": str(hermetic_env_file),
        "AICHECK_TASK_DISPATCH": "disabled",
    }

    completed = subprocess.run(
        ["zsh", str(script)],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "AICHECK_MINERU_EXECUTION_MODE=postgres" in completed.stdout
    assert "python -m apps.mineru_worker.main" in completed.stdout
    assert "mineru-worker.pid" in completed.stdout
    assert "mineru-worker.log" in completed.stdout
    assert "celery" not in completed.stdout.lower()
    assert "redis" not in completed.stdout.lower()
