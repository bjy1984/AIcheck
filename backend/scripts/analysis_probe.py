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
