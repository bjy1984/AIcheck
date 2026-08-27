from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_local_dev_dry_run_includes_full_analysis_dependencies() -> None:
    result = subprocess.run(
        ["zsh", "scripts/start-local-dev.zsh"],
        cwd=REPO_ROOT,
        env={**os.environ, "AICHECK_DEV_DRY_RUN": "true"},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Redis:" in result.stdout
    assert "Celery queues: business.light,llm.remote" in result.stdout
