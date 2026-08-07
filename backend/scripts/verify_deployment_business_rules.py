#!/usr/bin/env python3
"""对已部署环境做业务规则端到端验证。

只依赖 HTTP API，不依赖前端。用于每次部署后确认业务口径没有回归。

用法：
    export AICHECK_BASE_URL=http://localhost:18080
    export AICHECK_TOKEN_INSPECTION="Bearer ..."
    export AICHECK_TOKEN_CONTRACTOR="Bearer ..."   # 可选，缺省跳过角色隔离用例
    export AICHECK_TOKEN_NDT="Bearer ..."          # 可选
    export AICHECK_PROJECT_ID=P-2026-GDLNG-002
    python3 scripts/verify_deployment_business_rules.py

会写入测试数据（审查意见、事实修正），请在测试环境运行。
脚本结束时会撤销自己创建的事实修正；审查意见按业务规则不可删除，会保留并带
「[自动验证]」前缀。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.getenv("AICHECK_BASE_URL", "http://localhost:18080").rstrip("/")
PROJECT = os.getenv("AICHECK_PROJECT_ID", "P-2026-GDLNG-002")
TOKENS = {
    "inspection": os.getenv("AICHECK_TOKEN_INSPECTION", ""),
    "contractor": os.getenv("AICHECK_TOKEN_CONTRACTOR", ""),
    "ndt": os.getenv("AICHECK_TOKEN_NDT", ""),
}
MARK = "[自动验证]"

results: list[tuple[str, bool, str]] = []
created_corrections: list[tuple[int, str]] = []


def call(method, path, *, role="inspection", body=None, action=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if role != "__anonymous__":
        # 本地无鉴权环境下 token 为空，仅凭 X-Role 即可；生产必须带 token。
        if TOKENS.get(role):
            request.add_header("Authorization", TOKENS[role])
        request.add_header("X-Role", role)
    if action:
        request.add_header("X-Action-Code", action)
    # 走本地隧道时必须绕过系统代理
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode())
        except Exception:
            return {"code": exc.code, "data": {"reason": "HTTP_ERROR"}}


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def node_status(node_id: int) -> str:
    tree = call("GET", f"/api/projects/{PROJECT}/tree")
    stack = [tree.get("data")]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if str(item.get("nodeId")) == str(node_id) and item.get("status"):
                return str(item["status"])
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return "?"


def save_opinion(node_id, result, opinion, evidence=None):
    return call(
        "POST",
        f"/api/projects/{PROJECT}/inspection/nodes/{node_id}/review-opinions",
        body={"result": result, "opinion": f"{MARK}{opinion}", "evidenceLinkIds": evidence or []},
        action="review:save",
    )


# --------------------------------------------------------------- 结论语义

def test_conclusion_semantics(node_na: int, node_ie: int):
    print("\n[1] 人工结论语义（issues #4 #13）")

    r = save_opinion(node_na, "不适用", "本项目无此设计，节点不适用。")
    check("「不适用」保存成功", r.get("code") == 0, str(r.get("message") or ""))
    check(
        "「不适用」不落入「需补正」",
        (r.get("data") or {}).get("nextStatus") == "不适用",
        f"nextStatus={(r.get('data') or {}).get('nextStatus')}",
    )
    check("「不适用」节点状态已落库", node_status(node_na) == "不适用")

    r = save_opinion(node_ie, "证据不足", "资料未齐，待补件后复核。")
    check("「证据不足」为合法结论", r.get("code") == 0, str(r.get("message") or ""))
    check(
        "「证据不足」保持待审查",
        (r.get("data") or {}).get("nextStatus") == "待审查",
        f"nextStatus={(r.get('data') or {}).get('nextStatus')}",
    )

    r = save_opinion(node_ie, "瞎写的结论", "非法结论应被拒绝。")
    check("非法结论被拒绝", r.get("code") != 0, (r.get("data") or {}).get("reason", ""))


# ------------------------------------------------------------------- 留痕

def test_audit_trail(node_id: int):
    print("\n[2] 人工结论留痕（issue #5 / R-7）")

    r = save_opinion(node_id, "不适用", "留痕验证。")
    data = r.get("data") or {}
    opinion = data.get("opinion") or {}
    check("返回审计日志 ID", bool(data.get("auditLogId")), str(data.get("auditLogId")))
    check("记录审查人", bool(opinion.get("reviewerName")), str(opinion.get("reviewerName")))
    for field in ("aiRunId", "aiSuggestedResult", "overriddenFromAi"):
        check(f"携带 AI 关联字段 {field}", field in opinion)

    listed = call("GET", f"/api/projects/{PROJECT}/inspection/nodes/{node_id}/review-opinions")
    saved = next((x for x in (listed.get("data") or []) if x.get("id") == opinion.get("id")), None)
    check("结论可回查且留痕持久化", saved is not None and "overriddenFromAi" in (saved or {}))


# --------------------------------------------------------------- 事实修正

def test_fact_corrections(node_id: int):
    print("\n[3] 人工修正 OCR 事实（issue #5 / D-1）")
    path = f"/api/projects/{PROJECT}/inspection/nodes/{node_id}/fact-corrections"
    fact = "welderCertificate.certificateNo"

    r1 = call("POST", path, body={"factPath": fact, "originalValue": "T2026-O01",
                                  "correctedValue": "TS2026-001", "reason": f"{MARK}OCR 误识别"},
              action="review:save")
    c1 = (r1.get("data") or {}).get("correction") or {}
    check("创建修正成功", r1.get("code") == 0, str(r1.get("message") or ""))
    check("修正写审计日志", bool((r1.get("data") or {}).get("auditLogId")))
    check("记录修正人", bool(c1.get("correctedBy")), str(c1.get("correctedBy")))
    if c1.get("id"):
        created_corrections.append((node_id, c1["id"]))

    r2 = call("POST", path, body={"factPath": fact, "correctedValue": "TS2026-002"}, action="review:save")
    c2 = (r2.get("data") or {}).get("correction") or {}
    check("同字段二次修正 supersede 旧记录", c1.get("id") in (c2.get("supersedes") or []))
    if c2.get("id"):
        created_corrections.append((node_id, c2["id"]))

    active = call("GET", f"{path}?status=active").get("data") or []
    mine = [x for x in active if x.get("factPath") == fact]
    check("同字段仅一条生效", len(mine) == 1, f"生效 {len(mine)} 条")

    bad = call("POST", path, body={"factPath": "bad..path; drop", "correctedValue": "x"}, action="review:save")
    check("非法字段路径被拒绝", bad.get("code") != 0, (bad.get("data") or {}).get("reason", ""))

    nov = call("POST", path, body={"factPath": "a.b"}, action="review:save")
    check("缺 correctedValue 被拒绝", nov.get("code") != 0, (nov.get("data") or {}).get("reason", ""))


# --------------------------------------------------------------- 角色隔离

def test_role_isolation(inspection_node: int, ndt_node: int):
    print("\n[4] 角色权限与数据隔离（S-3）")

    if not TOKENS.get("contractor"):
        print("  SKIP  未提供 contractor token")
        return

    r = call("POST", f"/api/projects/{PROJECT}/inspection/nodes/{inspection_node}/fact-corrections",
             role="contractor", body={"factPath": "a.b", "correctedValue": "x"}, action="review:save")
    check("施工方不能修正事实", r.get("code") != 0, (r.get("data") or {}).get("reason", ""))

    r = call("POST", f"/api/projects/{PROJECT}/inspection/nodes/{inspection_node}/review-opinions",
             role="contractor", body={"result": "满足要求", "opinion": "x", "evidenceLinkIds": []},
             action="review:save")
    check("施工方不能保存审查结论", r.get("code") != 0, (r.get("data") or {}).get("reason", ""))

    if TOKENS.get("ndt"):
        r = call("GET", f"/api/projects/{PROJECT}/inspection/nodes/{inspection_node}/ai-runs", role="ndt")
        check("NDT 不能读焊接节点（节点范围隔离）", r.get("code") != 0,
              (r.get("data") or {}).get("reason", ""))
        r = call("GET", f"/api/projects/{PROJECT}/inspection/nodes/{ndt_node}/ai-runs", role="ndt")
        check("NDT 可读自己范围内节点", r.get("code") == 0)

    r = call("POST", f"/api/projects/{PROJECT}/inspection/nodes/{inspection_node}/fact-corrections",
             role="__anonymous__", body={"factPath": "a.b", "correctedValue": "x"})
    check("未登录被拒绝", r.get("code") != 0, (r.get("data") or {}).get("reason", ""))


# ------------------------------------------------------------- 运行时健康

def test_runtime(deployed: bool):
    print("\n[5] 运行时与部署契约（S-1）")
    ready = call("GET", "/api/readyz")
    check("readyz 暴露 authRequired", "authRequired" in ready, str(ready.get("authRequired")))

    health = (call("GET", "/api/healthz").get("data") or {})
    check("数据库连通", health.get("databaseConnected") is True)
    check("工作流就绪", health.get("workflowReady") is True)

    if deployed:
        check("readyz 就绪", ready.get("ready") is True, json.dumps(ready.get("checks") or {}, ensure_ascii=False))
        check("生产强制鉴权", ready.get("authRequired") is True)
    else:
        print("  SKIP  就绪与强制鉴权断言（本地轻量模式）")


def test_aggregation_locally():
    """聚合器语义（issues #3 #4 #6）——纯函数，直接调库，无需服务。"""
    print("\n[6] 结论聚合语义（本地库调用）")
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    try:
        import libs.review_orchestrator  # noqa: F401  规避循环导入
        from libs.review_tools import dispatch_business_tool
        from libs.review_tools.executor import aggregate_atomic_results, aggregate_tool_results
    except Exception as exc:  # 远端跑脚本时没有代码，跳过
        print(f"  SKIP  无法导入业务库（{type(exc).__name__}）")
        return

    check("字段缺失判证据不足",
          dispatch_business_tool("check_required", {"requiredFields": ["a.b"], "facts": {}})["result"]
          == "evidence_insufficient")
    check("有值不合规仍判不符合",
          dispatch_business_tool("check_scope_coverage",
                                 {"grantedScopes": ["GC3"], "requiredScopes": ["GC1"],
                                  "coverageMap": {"GC1": ["GC1"]}})["result"] == "failed")
    check("文件本体缺失仍判不符合",
          dispatch_business_tool("check_document_set_completeness",
                                 {"requiredDocumentTypes": ["a", "b"], "uploadedDocumentTypes": ["a"],
                                  "parseableDocumentTypes": ["a"]})["result"] == "failed")
    check("保留需人工判断状态",
          aggregate_tool_results([{"toolName": "a", "result": "human_review_required"}])
          == "human_review_required")
    check("原子层同样保留",
          aggregate_atomic_results([{"result": "human_review_required"}]) == "human_review_required")
    check("工具故障不掩盖已确认不符合",
          aggregate_tool_results([{"toolName": "a", "result": "failed"},
                                  {"toolName": "b", "status": "failed"}]) == "failed")
    check("纯故障走独立通道",
          aggregate_tool_results([{"toolName": "a", "result": "passed"},
                                  {"toolName": "b", "status": "error"}]) == "execution_error")
    check("证据锚定失效一票否决",
          aggregate_tool_results([{"toolName": "validate_evidence_grounding",
                                   "result": "evidence_insufficient"},
                                  {"toolName": "c", "result": "failed"}]) == "evidence_insufficient")


def cleanup():
    print("\n[清理] 撤销脚本创建的事实修正")
    for node_id, correction_id in created_corrections:
        r = call("POST",
                 f"/api/projects/{PROJECT}/inspection/nodes/{node_id}/fact-corrections/{correction_id}/revoke",
                 body={}, action="review:save")
        status = ((r.get("data") or {}).get("correction") or {}).get("status")
        if status:
            print(f"  {correction_id}: {status}")
        else:
            # 已被后续修正 supersede 的记录不可撤销，属预期
            print(f"  {correction_id}: 跳过（{(r.get('data') or {}).get('reason') or r.get('message')}）")


def main():
    print(f"目标: {BASE}  项目: {PROJECT}")
    probe = call("GET", "/api/readyz")
    if not probe:
        print("错误：无法连接后端")
        return 2

    node_na = int(os.getenv("AICHECK_TEST_NODE_NA", "51"))
    node_ie = int(os.getenv("AICHECK_TEST_NODE_IE", "50"))
    node_weld = int(os.getenv("AICHECK_TEST_NODE_WELD", "24"))
    node_ndt = int(os.getenv("AICHECK_TEST_NODE_NDT", "40"))

    test_runtime(deployed=bool(TOKENS.get("inspection")))
    test_conclusion_semantics(node_na, node_ie)
    test_audit_trail(node_na)
    test_fact_corrections(node_weld)
    test_role_isolation(node_weld, node_ndt)
    test_aggregation_locally()
    cleanup()

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{'=' * 60}\n通过 {len(results) - len(failed)}/{len(results)}")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
