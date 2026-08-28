"""把超时无进展的一键分析运行落 failed 终态。

## 为什么必须有

worker 在模型调用中途猝死（部署重建、OOM、kill）后，运行会永远停在
model_running/queued 等中间相位，且**没有任何人捡起来**：
- status 视图 30 分钟后会把它**显示**成 failed（PROJECT_ANALYSIS_RUN_STALLED），
  但那只骗显示不改库；
- 库里非终态的 run 会被幂等复用——同一份资料从此永远发不起新分析。

收敛器与视图同口径（同 30 分钟阈值、同活动时间取法）把库落掉；
failed 运行不被幂等复用，用户重新点按钮即可得到新运行。

model_running 相位的阈值取 max(30 分钟, 模型超时 + 5 分钟)：
模型调用最长可配 3600 秒且期间无心跳，统一阈值会误杀合法长调用。

## 用法

    docker exec aicheck-api python3 /app/scripts/reconcile_stalled_analysis_runs.py [--apply] [--minutes 30]

不加 --apply 是 dry-run，只报告不动库。
"""

from __future__ import annotations

import sys
from datetime import timedelta

sys.path.insert(0, "/app")

from libs.contracts.responses import server_time  # noqa: E402
from libs.db.repository import flush_state, load_state, repo  # noqa: E402
from libs.project_analysis.domain import (  # noqa: E402
    TERMINAL_PHASES,
    reap_stalled_project_analysis_runs,
)
from libs.project_analysis.execution import (  # noqa: E402
    project_analysis_model_timeout_seconds,
)


def main() -> int:
    minutes = 30
    if "--minutes" in sys.argv:
        minutes = int(sys.argv[sys.argv.index("--minutes") + 1])

    load_state()
    runs = repo.state.get("project_analysis_runs") or []
    pending = [r for r in runs if str(r.get("phase") or "") not in TERMINAL_PHASES]
    print(f"[{server_time()}] 非终态运行 {len(pending)} 个（共 {len(runs)} 个）")

    if "--apply" not in sys.argv:
        # dry-run 在拷贝上判定，绝不动共享 state
        from copy import deepcopy

        preview = reap_stalled_project_analysis_runs(
            {"project_analysis_runs": deepcopy(pending), "project_analysis_events": []},
            stall_timeout=timedelta(minutes=minutes),
            model_running_timeout=timedelta(
                seconds=project_analysis_model_timeout_seconds() + 300
            ),
        )
        for run in preview:
            print(
                f"  将收敛 {run.get('projectAnalysisRunId')} "
                f"from={run.get('failedFromPhase')} project={run.get('projectId')}"
            )
        print(f"（dry-run。命中 {len(preview)} 个，加 --apply 才落库）")
        return 0

    reaped = reap_stalled_project_analysis_runs(
        repo.state,
        stall_timeout=timedelta(minutes=minutes),
        model_running_timeout=timedelta(
            seconds=project_analysis_model_timeout_seconds() + 300
        ),
    )
    for run in reaped:
        print(
            f"  已收敛 {run.get('projectAnalysisRunId')} "
            f"from={run.get('failedFromPhase')} project={run.get('projectId')}"
        )
    if reaped:
        flush_state({"project_analysis_runs", "project_analysis_events"})
    print(f"收敛 {len(reaped)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
