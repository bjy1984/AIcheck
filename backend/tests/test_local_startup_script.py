from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_local_launcher_starts_independent_mineru_worker(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "start-local-dev.zsh"
    env = {
        **os.environ,
        "AICHECK_DEV_DRY_RUN": "true",
        "AICHECK_DEV_LOG_DIR": str(tmp_path),
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
