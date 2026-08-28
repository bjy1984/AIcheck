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

    # 当日 LLM 成本：按 model_call_attempts 的 costNormalized.total 汇总。
    # 供应商故障引发的重试风暴或 prompt 膨胀都会先体现在这里；
    # 超阈值只告警不熔断——审批型业务宁可花钱也不能静默停摆。
    import os as _os

    today = now.strftime("%Y-%m-%d")
    attempts_today = [
        item
        for item in repo.state.get("model_call_attempts", [])
        if isinstance(item, dict) and str(item.get("createdAt") or "").startswith(today)
    ]
    cost_today = sum(
        float((item.get("costNormalized") or {}).get("total") or 0)
        for item in attempts_today
    )
    cost_limit = float(_os.getenv("AICHECK_LLM_DAILY_COST_ALERT_CNY", "50"))
    facts.append(f"当日 LLM 调用 {len(attempts_today)} 次，成本 ¥{cost_today:.2f}")
    if cost_today > cost_limit:
        alerts.append(
            f"当日 LLM 成本 ¥{cost_today:.2f} 超过告警线 ¥{cost_limit:.0f}"
            "（AICHECK_LLM_DAILY_COST_ALERT_CNY）——检查是否有重试风暴或 prompt 膨胀"
        )

    # 夜间探针（六角色写审计 + 一键分析可用性）必须**新鲜且全绿**。
    # 探针只在夜里跑，坏了没人看日志等于没跑；状态文件在宿主机挂载目录，
    # 跨部署持久，文件缺失本身就是异常（要么探针从没跑过，要么写不进去）。
    for label, path in (
        ("写审计探针", "/app/output/ops/last-write-probe.json"),
        ("一键分析探针", "/app/output/ops/last-analysis-probe.json"),
    ):
        probe_alert = probe_status_alert(label, path, now)
        if probe_alert:
            alerts.append(probe_alert)
        else:
            facts.append(f"{label}：新鲜且全绿")

    return alerts, facts


def probe_status_alert(label: str, path: str, now: datetime) -> str | None:
    """探针状态文件的判定：缺失/过期(26h)/有失败步 → 告警文案，健康 → None。"""
    try:
        with open(path, encoding="utf-8") as handle:
            status = json.load(handle)
    except FileNotFoundError:
        return f"{label}状态文件缺失（{path}）——探针没跑过或写不进去"
    except (OSError, ValueError) as exc:
        return f"{label}状态文件读取失败：{exc.__class__.__name__}"
    try:
        ran_at = datetime.strptime(str(status.get("at") or ""), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=now.tzinfo
        )
    except ValueError:
        return f"{label}状态文件时间戳不合法：{status.get('at')!r}"
    age_hours = (now - ran_at).total_seconds() / 3600
    if age_hours > 26:
        return f"{label}已 {age_hours:.0f} 小时未跑（判据：26 小时）——定时任务可能没了"
    failed = int(status.get("failed") or 0)
    if failed:
        steps = "、".join(str(s) for s in (status.get("failedSteps") or [])[:3])
        return f"{label}失败 {failed}/{status.get('total')} 步：{steps}"
    return None


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
