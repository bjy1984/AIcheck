"""一键分析可用性探针：preview 可用 + 最新运行状态健康 + 工作台载荷可见。

不发起新分析（不烧 LLM、不产生数据）：全链路的深度验证由夜间写审计和
按需的 E2E 承担，这里只回答「用户现在点得动吗、已有结果看得见吗」。

状态文件落宿主机挂载目录（/app/output/ops/，跨部署持久），
由 health_watch 每 10 分钟判新鲜度与结果。

## 用法

    docker exec aicheck-api python3 /app/scripts/analysis_probe.py [--project P-2026-HDCP-001]
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/scripts")

from libs.contracts.responses import server_time  # noqa: E402


def _auto_review_chain_checks() -> list[tuple[str, bool, str]]:
    """自动审查链（每上传自动分析）的活体检查。

    这条链 2026-08-29 之前**自上线从未生效过**，四处断裂互相掩护：策略读不到、
    没有 beat、周期任务活锁、scoped flush 覆写单例。修通后必须有人站岗——
    没有探针的话，同类回归只能靠人撞见（上次撞见花了三个月）。

    只读状态，不上传、不烧 LLM。beat 停摆没有直接可读的心跳字段，
    用**积压**间接判断（这也正是用户会感受到的形态）：
    - outbox 无积压：pending 事件超 15 分钟未消费 → beat 或 consume 任务死了
    - 候选无卡死：pending 候选超 15 分钟未派发 → start 任务死了或活锁
    - 无僵尸会话执行：心跳停摆超 30 分钟 → 会话收敛器没跑
    """
    import time as _time
    from datetime import datetime

    from libs.contracts.responses import SERVER_TZ
    from libs.db.repository import load_state, repo

    load_state()
    now = datetime.now(SERVER_TZ)
    checks: list[tuple[str, bool, str]] = []

    def _age_minutes(value: object) -> float | None:
        try:
            parsed = datetime.strptime(str(value or "")[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        return (now - parsed.replace(tzinfo=SERVER_TZ)).total_seconds() / 60

    policies = [
        row
        for row in repo.state.get("auto_review_policies", [])
        if isinstance(row, dict) and row.get("enabled") is True
    ]
    checks.append(
        (
            "自动审查策略可读（链路守卫的输入）",
            True,  # 读得到即可：全关是合法业务状态，不是故障
            f"启用中的项目 {len(policies)} 个",
        )
    )

    # 只有开着策略的部署才需要检查积压：全关时链路本就不该动。
    stale_events = []
    for row in repo.state.get("auto_review_outbox", []):
        if not isinstance(row, dict) or str(row.get("status") or "") != "pending":
            continue
        age = _age_minutes(row.get("createdAt"))
        if age is not None and age > 15:
            stale_events.append((row.get("id"), age))
    checks.append(
        (
            "outbox 无积压（beat 在消费事件）",
            not stale_events,
            f"超 15 分钟未消费 {len(stale_events)} 条"
            + (f"，最旧 {max(a for _, a in stale_events):.0f} 分钟" if stale_events else ""),
        )
    )

    stale_candidates = []
    for row in repo.state.get("auto_review_candidates", []):
        if not isinstance(row, dict) or str(row.get("status") or "") != "pending":
            continue
        age = _age_minutes(row.get("availableAt") or row.get("createdAt"))
        if age is not None and age > 15:
            stale_candidates.append((row.get("id"), age))
    checks.append(
        (
            "候选无卡死（周期任务在派发）",
            not stale_candidates,
            f"超 15 分钟未派发 {len(stale_candidates)} 个"
            + (
                f"，最旧 {max(a for _, a in stale_candidates):.0f} 分钟"
                if stale_candidates
                else ""
            ),
        )
    )

    # 哈希伪向量：与真语义向量同表同维，只有 embeddingModel 能区分。
    # 它们没有语义，检索命中近似随机——这是**静默的质量塌方**，
    # 界面上一切正常（2026-08-29 审计：全库 48% 向量是哈希的）。
    from libs.db.repository import ensure_collections_loaded

    ensure_collections_loaded("knowledge_vectors")
    vectors = [v for v in repo.state.get("knowledge_vectors", []) if isinstance(v, dict)]
    hash_vectors = [v for v in vectors if str(v.get("embeddingModel") or "") == "offline-hash-v1"]
    hash_ratio = (len(hash_vectors) / len(vectors)) if vectors else 0.0
    checks.append(
        (
            "无哈希伪向量污染检索",
            hash_ratio < 0.05,  # 判据：5%（重跑过程中允许残留，长期应归零）
            f"{len(hash_vectors)}/{len(vectors)} = {hash_ratio:.0%}"
            + ("（哈希向量没有语义，检索近似随机）" if hash_ratio >= 0.05 else ""),
        )
    )

    # 会话 Agent 执行僵尸：与 reconcile_stalled_agent_executions 同口径。
    zombie = []
    for row in repo.state.get("agent_executions", []):
        if not isinstance(row, dict) or str(row.get("status") or "") != "running":
            continue
        epoch = row.get("heartbeatEpoch") or row.get("startedEpoch")
        try:
            idle = _time.time() - float(epoch)
        except (TypeError, ValueError):
            idle = 10_000.0
        if idle > 1800:
            zombie.append((row.get("id"), idle / 60))
    checks.append(
        (
            "无僵尸会话执行（收敛器在跑）",
            not zombie,
            f"心跳停摆超 30 分钟 {len(zombie)} 个"
            + (f"，最旧 {max(m for _, m in zombie):.0f} 分钟" if zombie else ""),
        )
    )
    return checks


def main() -> int:
    from write_ops_audit import api

    project_id = "P-2026-HDCP-001"
    if "--project" in sys.argv:
        project_id = sys.argv[sys.argv.index("--project") + 1]
    base = f"/api/projects/{project_id}/inspection/full-project-analysis"
    checks: list[tuple[str, bool, str]] = []

    pv = api(f"{base}/preview", "inspection")
    preview = (pv.get("data") or {}).get("preview") or {}
    checks.append(
        (
            "preview 可用且范围非空",
            pv.get("code") == 0 and int(preview.get("includedNodeCount") or 0) > 0,
            f"code={pv.get('code')} 节点={preview.get('includedNodeCount')}",
        )
    )

    runs = api(f"{base}/runs", "inspection")
    items = (runs.get("data") or {}).get("items") or []
    checks.append(("运行列表可用", runs.get("code") == 0, f"共 {len(items)} 个"))
    if items:
        latest = items[0]
        st = api(f"{base}/runs/{latest.get('projectAnalysisRunId')}/status", "inspection")
        status = (st.get("data") or {}).get("status") or {}
        # 收敛器保证僵尸会被落 failed；探针只要求视图口径不是 STALLED——
        # 出现 STALLED 说明收敛器没跑或没跑赢，值得报警。
        checks.append(
            (
                "最新运行状态健康（无 STALLED）",
                st.get("code") == 0
                and status.get("errorCode") != "PROJECT_ANALYSIS_RUN_STALLED",
                f"phase={status.get('phase')} error={status.get('errorCode')}",
            )
        )
        node_runs = [
            r
            for r in items
            if str(r.get("phase") or "") == "waiting_human_review"
        ]
        if node_runs:
            derived = node_runs[0].get("derivedReviewRunIds") or []
            if derived:
                probe_node = None
                ws_ok = False
                detail = "无派生结果"
                run_id = node_runs[0].get("projectAnalysisRunId")
                full = api(f"{base}/runs/{run_id}", "inspection")
                for review in ((full.get("data") or {}).get("run") or {}).get(
                    "validatedOutput", {}
                ).get("nodeReviews", []) or []:
                    probe_node = int(review.get("nodeId") or 0)
                    break
                if probe_node:
                    ws = api(
                        f"/api/projects/{project_id}/inspection/nodes/{probe_node}/review-workspace",
                        "inspection",
                    )
                    results = (ws.get("data") or {}).get("projectAnalysisResults") or []
                    ws_ok = ws.get("code") == 0 and bool(results)
                    detail = f"node={probe_node} 结果 {len(results)} 条"
                checks.append(("工作台载荷含分析结果", ws_ok, detail))

    checks.extend(_auto_review_chain_checks())

    failed = [(step, detail) for step, ok, detail in checks if not ok]
    for step, ok, detail in checks:
        print(f"  {'✓' if ok else '✗'} {step}：{detail}")
    print(f"共 {len(checks)} 步，失败 {len(failed)}")

    try:
        os.makedirs("/app/output/ops", exist_ok=True)
        with open("/app/output/ops/last-analysis-probe.json", "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "at": server_time(),
                    "total": len(checks),
                    "failed": len(failed),
                    "failedSteps": [step for step, _ in failed],
                },
                handle,
                ensure_ascii=False,
            )
    except OSError as exc:
        print(f"（探针状态文件写入失败：{exc}）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
