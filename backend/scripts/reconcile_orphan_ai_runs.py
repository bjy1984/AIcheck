"""把界面上永远「推理中」的孤儿 AI 运行落终态。

## 为什么必须有

2026-09-04 巡检：17 条 ai_runs 停在「推理中」超过 1 小时——
- 6 条（09-03 16:30–19:01）：review_run 早已 waiting_human_review/failed，ai_run 没回填。
  那是收尾落库撞并发冲突（commit 60da011 之前）留下的：review_run 靠重试落了，
  ai_run 那一行的增量丢了；
- 11 条（08-29/30）：旧版 ai_recheck 路径派发后 worker 死掉，review_run 永远 queued，
  没有任何收敛器管它（reconcile_stalled_analysis_runs 只管一键分析）。
model_call_attempts 里对应的 8 条 running 也一并落 failed（orphaned）。

节点页按最新一次 ai_run 显示状态：孤儿在前就是「AI 正在分析」，用户以为还在跑。

## 做什么

- ai_run 推理中 且 review_run 终态 → 按 review_run 结果回填：
  waiting_human_review → 完成；failed/review_incomplete → 审查未完成（errorCode ORPHANED_*）。
- ai_run 推理中 且 review_run queued/created/缺失、超过 --hours（默认 2）→ ai_run/review_run
  同落失败（PROCESSING_ORPHANED），用户重新点复核即可。
- 关联的 running model_call_attempts → failed（ORPHANED）。

## 用法

    docker exec aicheck-api python3 /app/scripts/reconcile_orphan_ai_runs.py [--apply] [--hours 2]
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/app")

from libs.contracts.responses import SERVER_TZ, server_time  # noqa: E402

TERMINAL_REVIEW = {"waiting_human_review", "failed", "review_incomplete", "completed", "cancelled"}
PENDING_REVIEW = {"queued", "created", "running", "推理中", ""}


def _parse(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ)
    except ValueError:
        return None


def plan(state: dict, *, hours: float, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(SERVER_TZ)
    cutoff = now - timedelta(hours=hours)
    review_runs = {
        str(row.get("reviewRunId") or row.get("id") or ""): row
        for row in state.get("review_runs") or []
        if isinstance(row, dict)
    }
    actions: list[dict] = []
    for run in state.get("ai_runs") or []:
        if not isinstance(run, dict) or str(run.get("status") or "") != "推理中":
            continue
        started = _parse(run.get("startedAt") or run.get("createdAt"))
        if started is not None and started > cutoff:
            continue
        review = review_runs.get(str(run.get("reviewRunId") or ""))
        review_status = str((review or {}).get("status") or "")
        if review is not None and review_status in TERMINAL_REVIEW:
            actions.append(
                {
                    "aiRun": run,
                    "reviewRun": review,
                    "kind": "backfill",
                    "status": "完成" if review_status == "waiting_human_review" else "审查未完成",
                    "errorCode": None if review_status == "waiting_human_review" else f"ORPHANED_{review_status.upper()}",
                }
            )
        elif review is None or review_status in PENDING_REVIEW:
            actions.append(
                {
                    "aiRun": run,
                    "reviewRun": review,
                    "kind": "fail",
                    "status": "审查未完成",
                    "errorCode": "PROCESSING_ORPHANED",
                }
            )
    return actions


def apply(state: dict, actions: list[dict]) -> dict:
    now = server_time()
    touched_ai, touched_rr, touched_attempts = 0, 0, 0
    for action in actions:
        run = action["aiRun"]
        run["status"] = action["status"]
        run["finishedAt"] = run.get("finishedAt") or now
        run["updatedAt"] = now
        run["revision"] = int(run.get("revision") or 0) + 1
        run["reconciledAt"] = now
        run["reconciledFrom"] = "推理中"
        if action["errorCode"]:
            run["errorCode"] = action["errorCode"]
            run["failure"] = {
                "reason": "AI 复核未产出结果，已由巡检收敛；请重新发起复核。",
                "retryable": True,
                "code": action["errorCode"],
            }
        touched_ai += 1
        review = action.get("reviewRun")
        if action["kind"] == "fail" and review is not None:
            review["status"] = "failed"
            review["currentStep"] = "failed"
            review["errorCode"] = "PROCESSING_ORPHANED"
            review["finishedAt"] = review.get("finishedAt") or now
            review["updatedAt"] = now
            review["revision"] = int(review.get("revision") or 0) + 1
            touched_rr += 1
        review_id = str(run.get("reviewRunId") or "")
        for attempt in state.get("model_call_attempts") or []:
            if (
                isinstance(attempt, dict)
                and str(attempt.get("status") or "") == "running"
                and str(attempt.get("reviewRunId") or "") == review_id
            ):
                attempt["status"] = "failed"
                attempt["failureReason"] = "ORPHANED"
                attempt["finishedAt"] = now
                attempt["updatedAt"] = now
                touched_attempts += 1
    return {"aiRuns": touched_ai, "reviewRuns": touched_rr, "attempts": touched_attempts}


def main() -> int:
    from libs.db.repository import flush_state, load_state, repo

    hours = 2.0
    if "--hours" in sys.argv:
        hours = float(sys.argv[sys.argv.index("--hours") + 1])
    load_state()
    actions = plan(repo.state, hours=hours)
    print(f"[{server_time()}] 孤儿 AI 运行 {len(actions)} 条（推理中超过 {hours} 小时）")
    for action in actions:
        run = action["aiRun"]
        print(
            f"  {action['kind']:8s} {run.get('id')} {run.get('projectId')} 节点 {run.get('nodeId')} "
            f"起于 {run.get('startedAt')} → {action['status']} {action['errorCode'] or ''}"
        )
    if "--apply" not in sys.argv:
        print("（dry-run。加 --apply 才落库）")
        return 0
    if not actions:
        print("无需变更")
        return 0
    summary = apply(repo.state, actions)
    flush_state({"ai_runs", "review_runs", "model_call_attempts"})
    print(f"已收敛 ai_runs {summary['aiRuns']}、review_runs {summary['reviewRuns']}、model_call_attempts {summary['attempts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
