"""把 69 个节点的确定性层离线跑一遍，产出「卡在哪里」的全量清单。

## 为什么要有

2026-09-11：生产 69 个节点里只有 14 个真跑过复核，全部优先级都是从这 14 个外推的。
而这一天里三次「以为是代码问题、其实是别的」，都是靠离线跑事实构建器 + 确定性工具
查清的（焊接分类器、规则错挂、焊工证代号）。把那个手法做全，就不用再外推。

## 做什么

对指定项目的每个节点，按审查图的前三步跑：

    load_context → load_ocr_result → run_rule_engine

`run_rule_engine` 就是生产里产出 atomicCheckResults 的那一步，它排在
`llm_generate_findings` **之前**，所以整个确定性层可以一字不差地重放而不调模型。

第一版扫描没这么做，自己用 `dispatch_runtime_tool({}, ...)` 当 tool_runner——
空 state 让读 OCR 的工具什么都拿不到，节点 24 扫出 0 项通过，而生产实际有 12 项。
比生产弱的探针会把「工具没数据」误报成「节点没结论」。

输出每个节点：规则、事实键与非空计数、原子核查项数、各项判定、以及证据不足的原因。

## 只读

`run_rule_engine` 会往 `repo.state["rule_check_results"]` 里追加记录，但**全程不调
flush_state**，所以只停在内存，不落库；构造的 review_run 同样是临时对象。

## 用法

    docker exec aicheck-api python3 /app/scripts/sweep_deterministic_layer.py <projectId> [--json 输出路径]
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

sys.path.insert(0, "/app")


def _fact_summary(facts: Any) -> dict[str, int]:
    if not isinstance(facts, dict):
        return {}
    summary: dict[str, int] = {}
    for key, value in facts.items():
        if isinstance(value, (list, dict)):
            summary[key] = len(value)
        elif value not in (None, "", False):
            summary[key] = 1
        else:
            summary[key] = 0
    return summary


def _reason_of(tool_result: dict[str, Any]) -> str | None:
    facts = tool_result.get("facts") if isinstance(tool_result.get("facts"), dict) else {}
    for key in ("reason", "reasons"):
        value = facts.get(key) or tool_result.get(key)
        if value:
            return "/".join(map(str, value)) if isinstance(value, list) else str(value)
    codes = tool_result.get("reasonCodes") or facts.get("reasonCodes")
    if codes:
        return "/".join(map(str, codes)) if isinstance(codes, list) else str(codes)
    summary = tool_result.get("summary")
    if isinstance(summary, dict) and summary.get("checkCount") == 0:
        return "checkCount=0"
    return None


def sweep_node(project_id: str, node_id: int, evidence: dict[tuple[str, int], list[str]]) -> dict[str, Any]:
    from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID
    from libs.db.repository import repo
    from libs.review_orchestrator.execution import run_step
    from libs.rule_scope import select_published_rule

    row: dict[str, Any] = {"nodeId": node_id, "projectId": project_id}
    document_version_ids = sorted(evidence.get((project_id, node_id)) or [])
    row["documentCount"] = len(document_version_ids)

    rule = select_published_rule(repo.state.get("rule_versions", []), node_id, project_id=project_id)
    if not rule:
        row["blocked"] = "no_published_rule"
        return row
    row["ruleId"] = rule.get("id")

    # tenantId 必须带上：read_ndt_tables 等构建器拿它做身份断言，缺了就抛
    # rNN_review_identity_incomplete_or_wrong_node。第一版扫描漏了这个字段，
    # 26 个节点报「崩在 load_context」——那是探针自己造的，不是生产缺陷。
    project = repo.require_project(project_id) or {}
    review_run = {
        "id": "SWEEP",
        "reviewRunId": "SWEEP",
        "tenantId": str(project.get("tenantId") or "TENANT-DEFAULT"),
        "projectId": project_id,
        "nodeId": node_id,
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "inputDocumentVersionIds": document_version_ids,
        "inputDocumentPageRanges": {},
        "documentSources": [],
        "reviewMode": "advisory",
        "advisoryOnly": True,
    }
    context: dict[str, Any] = {"reviewRun": review_run}
    try:
        run_step(review_run, "load_context", context)
    except Exception as exc:  # noqa: BLE001 -- 扫描要continue，不能被单个节点打断
        row["blocked"] = f"load_context_failed:{exc.__class__.__name__}:{exc}"
        return row

    facts = context.get("businessFacts") if isinstance(context.get("businessFacts"), dict) else {}
    fact_counts = _fact_summary(facts)
    row["factKeys"] = len(fact_counts)
    row["emptyFactKeys"] = sorted(key for key, count in fact_counts.items() if not count)
    row["nonEmptyFactKeys"] = sorted(key for key, count in fact_counts.items() if count)

    for step in ("load_ocr_result", "run_rule_engine"):
        try:
            run_step(review_run, step, context)
        except Exception as exc:  # noqa: BLE001
            row["blocked"] = f"{step}_failed:{exc.__class__.__name__}:{exc}"
            row["traceback"] = traceback.format_exc()[-600:]
            return row

    execution = context.get("atomicToolExecution") or {}
    row["atomicCheckCount"] = len(execution.get("atomicResults") or [])
    if not execution.get("atomicResults"):
        row["blocked"] = "no_atomic_check_bindings"
        return row

    results: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for item in execution.get("atomicResults") or []:
        verdict = str(item.get("result") or "")
        results[verdict] = results.get(verdict, 0) + 1
        if verdict != "evidence_insufficient":
            continue
        found = next(
            (
                _reason_of(tool)
                for tool in item.get("toolResults") or []
                if isinstance(tool, dict) and tool.get("result") == "evidence_insufficient" and _reason_of(tool)
            ),
            None,
        )
        key = found or "（工具没说原因）"
        reasons[key] = reasons.get(key, 0) + 1
    row["result"] = execution.get("result")
    row["resultCounts"] = results
    row["insufficientReasons"] = reasons
    return row


def main() -> int:
    from libs.db.repository import load_state, repo

    args = [item for item in sys.argv[1:] if not item.startswith("--")]
    if not args:
        print("用法：sweep_deterministic_layer.py <projectId> [--json 路径]", file=sys.stderr)
        return 2
    project_id = args[0]
    json_path = next((sys.argv[i + 1] for i, item in enumerate(sys.argv) if item == "--json"), None)

    load_state()
    evidence: dict[tuple[str, int], list[str]] = {}
    for link in repo.state.get("node_evidence_links", []) or []:
        if not isinstance(link, dict) or link.get("nodeId") is None:
            continue
        key = (str(link.get("projectId") or ""), int(link["nodeId"]))
        version_id = str(link.get("documentVersionId") or "")
        if version_id and version_id not in evidence.setdefault(key, []):
            evidence[key].append(version_id)

    rows = [sweep_node(project_id, node_id, evidence) for node_id in range(1, 70)]
    if json_path:
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=1)
        print(f"明细已写入 {json_path}")

    blocked: dict[str, list[int]] = {}
    for row in rows:
        if row.get("blocked"):
            blocked.setdefault(str(row["blocked"]).split(":")[0], []).append(row["nodeId"])
    print(f"项目 {project_id}：扫描 {len(rows)} 个节点")
    print("\n=== 卡住的节点 ===")
    for reason, nodes in sorted(blocked.items()):
        print(f"  {reason:28s} {len(nodes):3d} 个: {nodes}")
    ran = [row for row in rows if row.get("resultCounts")]
    print(f"\n=== 真跑出核查项的 {len(ran)} 个节点 ===")
    for row in ran:
        print(f"  节点 {row['nodeId']:3d} {row.get('ruleId')!s:22s} 文档{row['documentCount']:3d} "
              f"原子项{row.get('atomicCheckCount', 0):3d} -> {row['resultCounts']}")
    print("\n=== 证据不足的原因合计 ===")
    totals: dict[str, int] = {}
    for row in rows:
        for reason, count in (row.get("insufficientReasons") or {}).items():
            totals[reason] = totals.get(reason, 0) + count
    for reason, count in sorted(totals.items(), key=lambda item: -item[1]):
        print(f"  {count:4d}  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
