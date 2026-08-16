"""排队了一整天还是 queued 的运行，界面不该继续说「执行中」。

## 线上实测（2026-08-16）

    RRUN-DC8068527E  status=queued  updatedAt=2026-08-15 13:56:11
    —— 20 小时没动过

谁打开这个节点都看到「执行中」，AI 结果永远出不来，也没人知道该重跑。
这就是「现在审计结果出不来」。

成因：inline 模式下派发即执行，中途执行进程没了（部署重建 worker/API 就会），
**没有任何人会回来把它标成失败**——它会永远停在 queued。

## 判据

- 排队/运行中且长期无进展 → 展示为失败，并给出可读原因与重发起提示
- 时限内的运行不动它：真正在跑的任务不能被判死
- 已终态的不动它：失败/取消/人工已确认都不该被这条规则改写
- 只改展示不改库：库里那份是执行留痕，事后追责要看原样
"""

from __future__ import annotations

from libs.contracts.responses import server_time
from libs.review_orchestrator.execution import (
    STALE_QUEUED_AFTER_SECONDS,
    review_run_looks_abandoned,
    review_run_view,
)


def _minutes_ago(minutes: int) -> str:
    from datetime import datetime, timedelta

    now = datetime.strptime(str(server_time())[:19], "%Y-%m-%d %H:%M:%S")
    return (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def test_排队太久判为无人执行():
    stale = {"status": "queued", "updatedAt": _minutes_ago(int(STALE_QUEUED_AFTER_SECONDS / 60) + 5)}
    assert review_run_looks_abandoned(stale) is True


def test_时限内的运行不动它():
    """真正在跑的任务不能被判死——这条比「及时报错」更重要。"""
    fresh = {"status": "queued", "updatedAt": _minutes_ago(1)}
    assert review_run_looks_abandoned(fresh) is False


def test_已终态的不改写():
    for status in ("failed", "cancelled", "accepted_by_human", "completed"):
        assert review_run_looks_abandoned({"status": status, "updatedAt": _minutes_ago(600)}) is False


def test_没有时间戳时不猜():
    assert review_run_looks_abandoned({"status": "queued"}) is False


def test_视图给出可读原因而不是干说失败():
    stale = {
        "id": "RRUN-T",
        "reviewRunId": "RRUN-T",
        "status": "queued",
        "updatedAt": _minutes_ago(int(STALE_QUEUED_AFTER_SECONDS / 60) + 5),
    }
    view = review_run_view(stale)
    assert view["status"] == "failed"
    assert view["statusReconciledFrom"] == "stale_queue"
    assert "重新发起" in view["errorMessage"], "要告诉人下一步能做什么"
    # 只改展示：原记录不能被改写
    assert stale["status"] == "queued"
