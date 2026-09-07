"""P12 F2：从生产库算 §17.3 反馈指标表（只读）。

用法（生产容器）：docker exec -w /app -e PYTHONPATH=/app aicheck-api python scripts/experiments/feedback_metrics.py
输出 Markdown 表 + JSON；贴进优化计划的度量表或看板。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path("/app")
sys.path.insert(0, str(BACKEND_ROOT))

from libs.db.repository import load_state, repo
from libs.feedback.metrics import compute_feedback_metrics, render_markdown


def main() -> int:
    load_state()
    metrics = compute_feedback_metrics(repo.state)
    print(render_markdown(metrics))
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
