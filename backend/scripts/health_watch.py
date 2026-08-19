"""生产巡检：几分钟一次，只报**会咬人**的那几件事。

## 为什么需要它

这轮所有问题都是我主动去查才发现的，而它们的共同点是**不报错**：
OCR 成功但切片空转、向量化配置丢失、报审被永久拦下——
容器是 unless-stopped，进程一直活着，日志干干净净。

灰度期间没人盯着的话，同样的故障会安静地存在很久。

## 判据取自「业务是否在推进」，不是「进程是否活着」

- 待处理任务积压且**长时间没有进展**：队列卡住的典型形态；
- 近一小时任务失败率过高：链路坏了，而不是个别难件；
- 知识文件处于失败态的比例；
- API 健康端点。

每条都给出**当前值和判据**，不合格时写进 /home/dev-bjy/health-alert.log，
并把最近一次结果写到 /home/dev-bjy/health-status.txt（人和脚本都能读）。

## 用法

    */10 * * * * docker exec aicheck-api python3 /app/scripts/health_watch.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, "/app")

STATUS_PATH = "/tmp/health-status.txt"
ALERT_PATH = "/tmp/health-alert.log"


def check() -> tuple[list[str], list[str]]:
    from libs.contracts.responses import SERVER_TZ, server_time
    from libs.db.repository import load_state, repo

    load_state()
    # 时间口径必须和库里一致：记录写的是 SERVER_TZ（Asia/Shanghai），
    # 容器跑的是 UTC。拿 UTC 去比会得到**负数**的「多久没动」，
    # 于是「长时间无进展」这条告警永远不触发——
    # 0819 实测 -469 分钟。不会报警的监控比没有监控更糟。
    now = datetime.now(SERVER_TZ)
    alerts: list[str] = []
    facts: list[str] = []

    kfs = [item for item in repo.state.get("knowledge_files", []) if isinstance(item, dict)]
    pending = [k for k in kfs if str(k.get("vectorStatus")) in {"待向量化", "向量化中"}]
    failed = [k for k in kfs if str(k.get("vectorStatus")) == "向量化失败"]
    facts.append(f"知识文件 {len(kfs)}：待处理 {len(pending)}、失败 {len(failed)}")

    # 积压本身不是问题，**长时间不动**才是。用最近更新时间判断有没有进展。
    if pending:
        newest = max(str(k.get("updatedAt") or "") for k in pending)
        stalled_since = str(newest)[:19]
        try:
            moved_at = datetime.fromisoformat(stalled_since).replace(tzinfo=SERVER_TZ)
            idle_minutes = (now - moved_at).total_seconds() / 60
        except ValueError:
            idle_minutes = 0
        facts.append(f"最近一次处理进展：{stalled_since}（{idle_minutes:.0f} 分钟前）")
        if idle_minutes > 30:
            alerts.append(
                f"向量化队列 {len(pending)} 份待处理，但已 {idle_minutes:.0f} 分钟没有进展"
                "（判据：30 分钟）——worker 可能挂了或队列卡住"
            )

    if kfs and len(failed) / len(kfs) > 0.25:
        alerts.append(
            f"知识文件失败率 {len(failed)}/{len(kfs)} = {len(failed) / len(kfs):.0%}"
            "（判据：25%）——多半是链路坏了，不是个别难件"
        )

    tasks = [item for item in repo.state.get("knowledge_tasks", []) if isinstance(item, dict)]
    hour_ago = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    recent = [t for t in tasks if str(t.get("updatedAt") or "") >= hour_ago]
    recent_failed = [t for t in recent if str(t.get("status")) == "失败"]
    if recent:
        facts.append(f"近一小时任务 {len(recent)}：失败 {len(recent_failed)}")
        if len(recent_failed) / len(recent) > 0.5:
            alerts.append(
                f"近一小时任务失败率 {len(recent_failed)}/{len(recent)}（判据：50%）"
            )

    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=15) as response:
            healthy = 200 <= response.status < 300
    except Exception as exc:  # noqa: BLE001
        healthy = False
        facts.append(f"健康端点异常：{exc.__class__.__name__}")
    if not healthy:
        alerts.append("API /healthz 不可用")
    else:
        facts.append("API /healthz 正常")

    return alerts, facts


def main() -> int:
    from libs.contracts.responses import server_time as _server_time

    stamp = _server_time()
    try:
        alerts, facts = check()
    except Exception as exc:  # noqa: BLE001 - 巡检自己挂了也要说出来，不能静默
        alerts, facts = [f"巡检脚本自身异常：{exc.__class__.__name__}: {exc}"], []

    lines = [f"[{stamp}]"] + [f"  {item}" for item in facts]
    lines += [f"  ⚠ {item}" for item in alerts] or ["  ✓ 无异常"]
    report = "\n".join(lines)
    print(report)
    with open(STATUS_PATH, "w", encoding="utf-8") as handle:
        handle.write(report + "\n")
    if alerts:
        with open(ALERT_PATH, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    return 1 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
