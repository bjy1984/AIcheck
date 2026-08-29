"""把心跳停摆的会话 Agent 执行收敛为 interrupted。

## 为什么必须有

一键分析侧有 reconcile_stalled_analysis_runs 站岗，**会话侧没有**：
recover_interrupted_agent_executions 只在「用户下一次给这个会话发消息」时
才跑（routes.py 唯一调用点）。API 容器在 Agent 执行中途被重建（每次部署都会），
留下的记录就是：

- agent_executions 永远 running；
- 占位 assistant 消息永远 running（前端一直转圈）；
- 会话执行槽被占，该会话**再也发不出下一条消息**——而「发下一条消息」
  恰好是唯一能触发自愈的动作，于是自愈永远不会发生。

判据与在线路径完全一致（同一个 heartbeatEpoch 阈值），只是不再等用户来敲门。

## 用法

    docker exec aicheck-api python3 /app/scripts/reconcile_stalled_agent_executions.py [--apply] [--seconds 600]

不加 --apply 是 dry-run。默认阈值取在线阈值的 2 倍且不低于 600 秒：
巡检比在线路径保守，避免抢在正常执行前面把活人打死。
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, "/app")

from libs.contracts.responses import server_time  # noqa: E402
from libs.db.repository import flush_state, load_state, repo  # noqa: E402


def main() -> int:
    from apps.api.routes import REVIEW_SESSION_HEARTBEAT_STALE_SECONDS

    threshold = max(600.0, float(REVIEW_SESSION_HEARTBEAT_STALE_SECONDS) * 2)
    if "--seconds" in sys.argv:
        threshold = float(sys.argv[sys.argv.index("--seconds") + 1])
    apply_changes = "--apply" in sys.argv

    load_state()
    now = time.time()
    stalled = []
    for record in repo.state.get("agent_executions", []):
        if str(record.get("status") or "") != "running":
            continue
        epoch = record.get("heartbeatEpoch") or record.get("startedEpoch")
        try:
            idle = now - float(epoch)
        except (TypeError, ValueError):
            idle = threshold + 1  # 无 epoch 视为停摆（与在线判据一致）
        if idle > threshold:
            stalled.append((record, idle))

    print(f"[{server_time()}] 心跳停摆超过 {threshold:.0f}s 的执行：{len(stalled)} 个")
    for record, idle in stalled:
        print(
            f"  {record.get('id')} session={record.get('sessionId')} "
            f"停摆 {idle / 60:.1f} 分钟 message={record.get('assistantMessageId')}"
        )
    if not apply_changes:
        print("（dry-run。加 --apply 才收敛）")
        return 0

    messages = []
    for record, _idle in stalled:
        record.update(
            {
                "status": "interrupted",
                "failureReason": "EXECUTION_INTERRUPTED",
                "finishedAt": server_time(),
                "updatedAt": server_time(),
            }
        )
        message = repo.find_one("review_messages", str(record.get("assistantMessageId") or ""))
        if message is not None and message.get("status") == "running":
            # 占位消息必须一起终结：只收执行记录的话，前端仍然一直转圈。
            message["status"] = "failed"
            message["contentBlocks"] = [
                {
                    "type": "text",
                    "text": "本次 AI 回答在执行中被中断（服务重启或进程退出），请重新提问。",
                }
            ]
            message["updatedAt"] = server_time()
            messages.append(message)
    if stalled:
        flush_state({"agent_executions", "review_messages"})
    print(f"收敛 {len(stalled)} 个执行，终结 {len(messages)} 条占位消息")
    return 0


if __name__ == "__main__":
    sys.exit(main())
