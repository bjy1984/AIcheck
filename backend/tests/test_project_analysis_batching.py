"""一键分析按节点分批（第二阶段 prompt 长度优化）。

上限从「项目 ≤ 单次上下文」变成「无上限，成本线性」。关键约束：
- 单批项目行为与分批前逐字节一致（走冻结请求原文）；
- 装箱确定性 + 共享文件亲和（语料是长度主体，跨批要重复传）；
- 顺序批链逐批落地，中途失败 = partial_failure + 已产出节点可见；
- 重试运行跳过同快照已有结果的节点——只补失败批。
"""

from __future__ import annotations

import json


def _payload(nodes, corpus):
    return {
        "task": "t",
        "requirements": [],
        "outputSchema": {},
        "project": {"projectId": "P-1", "nodes": nodes, "fileCorpus": corpus},
    }


def _corpus_entry(file_id, text, alias=None):
    entry = {"fileId": file_id}
    if alias:
        entry["identicalToFileId"] = alias
    else:
        entry["fullOcrText"] = text
    return entry


def test_packing_is_deterministic_affinity_aware_and_budget_bound() -> None:
    from libs.project_analysis.prompt import plan_project_analysis_batches

    corpus = {
        "F-A": _corpus_entry("F-A", "甲" * 4000),
        "F-B": _corpus_entry("F-B", "乙" * 4000),
        "F-C": _corpus_entry("F-C", "丙" * 4000),
    }
    nodes = [
        {"nodeId": 1, "fileRefs": [{"fileId": "F-A"}]},
        {"nodeId": 2, "fileRefs": [{"fileId": "F-B"}]},
        {"nodeId": 3, "fileRefs": [{"fileId": "F-A"}]},  # 与节点 1 共享 F-A
        {"nodeId": 4, "fileRefs": [{"fileId": "F-C"}]},
    ]
    plan = plan_project_analysis_batches(_payload(nodes, corpus), batch_budget_tokens=5000)
    # 共享 F-A 的节点 1、3 必须同批（语料只传一次）
    batch_of = {n: b["index"] for b in plan for n in b["nodeIds"]}
    assert batch_of[1] == batch_of[3]
    # 预算 5000 装不下两份 4000 字符语料 → 至少 3 批
    assert len(plan) == 3
    assert all(not b.get("oversized") for b in plan)
    # 确定性：同输入同方案
    again = plan_project_analysis_batches(_payload(nodes, corpus), batch_budget_tokens=5000)
    assert [b["nodeIds"] for b in again] == [b["nodeIds"] for b in plan]


def test_single_node_over_budget_is_marked_oversized() -> None:
    from libs.project_analysis.prompt import plan_project_analysis_batches

    corpus = {"F-BIG": _corpus_entry("F-BIG", "大" * 100000)}
    nodes = [{"nodeId": 1, "fileRefs": [{"fileId": "F-BIG"}]}]
    plan = plan_project_analysis_batches(_payload(nodes, corpus), batch_budget_tokens=5000)
    assert plan[0]["oversized"] is True  # 第三阶段检索式裁剪的触发条件


def test_batch_request_subsets_nodes_and_corpus_with_alias_primary() -> None:
    from libs.project_analysis.prompt import build_batch_request

    corpus = {
        "F-A": _corpus_entry("F-A", "正主全文"),
        "F-DUP": _corpus_entry("F-DUP", "", alias="F-A"),
        "F-B": _corpus_entry("F-B", "另一份"),
    }
    nodes = [
        {"nodeId": 1, "fileRefs": [{"fileId": "F-DUP"}]},
        {"nodeId": 2, "fileRefs": [{"fileId": "F-B"}]},
    ]
    request = {
        "model": "m",
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": json.dumps(_payload(nodes, corpus), ensure_ascii=False)},
        ],
    }
    batch = build_batch_request(request, [1])
    payload = json.loads(batch["messages"][1]["content"])
    assert [n["nodeId"] for n in payload["project"]["nodes"]] == [1]
    # 别名条目和它的正主都要带；无关语料不带
    assert set(payload["project"]["fileCorpus"]) == {"F-A", "F-DUP"}
    assert payload["project"]["fileCorpus"]["F-A"]["fullOcrText"] == "正主全文"


def test_sequential_batch_chain_persists_each_batch_then_finishes(monkeypatch) -> None:
    from apps.worker import tasks

    run = {
        "projectAnalysisRunId": "PARUN-BATCH",
        "projectAnalysisSnapshotId": "PASNAP-BATCH",
        "projectId": "P-1",
        "phase": "persisting_results",
        "status": "persisting_results",
        "batchPlan": [
            {"index": 0, "nodeIds": [1]},
            {"index": 1, "nodeIds": [2]},
        ],
        "batchCount": 2,
        "currentBatchIndex": 0,
        "currentBatchValidated": {
            "nodeReviews": [{"nodeId": 1, "reviewResult": "supported", "findings": []}]
        },
        "revision": 1,
    }
    tasks.repo.state["project_analysis_runs"] = [run]
    tasks.repo.state["project_analysis_events"] = []
    tasks.repo.state["review_runs"] = []
    dispatched: list[tuple[str, str | None]] = []
    monkeypatch.setattr(tasks, "load_state", lambda *_a, **_k: None)
    monkeypatch.setattr(tasks, "flush_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        tasks,
        "_dispatch_project_analysis_task",
        lambda name, rid, task_id=None: dispatched.append((name, task_id)),
    )

    first = tasks.project_analysis_persist_results.run("PARUN-BATCH")
    # 第一批落地后：结果已持久、相位拨回 queued 走第二批、重掷计数清零
    assert first["persistedNodeCount"] == 1
    assert first["phase"] == "queued"
    assert first["currentBatchIndex"] == 1
    assert first["modelRerollCount"] == 0
    assert dispatched and dispatched[0][0] == "project_analysis_execute_model"
    assert len(tasks.repo.state["review_runs"]) == 1

    # 第二批（最后一批）落地后：终态 waiting_human_review，derived 累积两个节点
    run.update(
        {
            "phase": "persisting_results",
            "status": "persisting_results",
            "currentBatchValidated": {
                "nodeReviews": [{"nodeId": 2, "reviewResult": "supported", "findings": []}]
            },
        }
    )
    second = tasks.project_analysis_persist_results.run("PARUN-BATCH")
    assert second["phase"] == "waiting_human_review"
    assert second["persistedNodeCount"] == 2
    assert len(second["derivedReviewRunIds"]) == 2


def test_retry_run_skips_nodes_already_persisted_for_same_snapshot(monkeypatch) -> None:
    from apps.worker import tasks

    tasks.repo.state["review_runs"] = [
        {
            "reviewRunId": "RRUN-PA-DONE1",
            "projectAnalysisSnapshotId": "PASNAP-RETRY",
            "projectAnalysisRunId": "PARUN-RETRY-PREV",
            "nodeId": 1,
        },
        {
            # 同快照、但上一次是另一个模型打的（幂等键不同）：不能当成本次结果
            "reviewRunId": "RRUN-PA-OTHER-MODEL",
            "projectAnalysisSnapshotId": "PASNAP-RETRY",
            "projectAnalysisRunId": "PARUN-OTHER-MODEL",
            "nodeId": 2,
        },
    ]
    run = {
        "projectAnalysisRunId": "PARUN-RETRY",
        "projectAnalysisSnapshotId": "PASNAP-RETRY",
        "idempotencyKey": "PAKEY-RETRY",
        "phase": "preparing_snapshot",
        "status": "preparing_snapshot",
        "batchPlan": [
            {"index": 0, "nodeIds": [1, 2]},
            {"index": 1, "nodeIds": [3]},
        ],
        "batchCount": 2,
        "currentBatchIndex": 0,
        "includedNodeCount": 3,
        "uniqueFileCount": 1,
        "revision": 1,
    }
    tasks.repo.state["project_analysis_runs"] = [
        run,
        {"projectAnalysisRunId": "PARUN-RETRY-PREV", "idempotencyKey": "PAKEY-RETRY", "phase": "failed"},
        {
            "projectAnalysisRunId": "PARUN-OTHER-MODEL",
            "idempotencyKey": "PAKEY-OTHER-MODEL",
            "phase": "waiting_human_review",
        },
    ]
    tasks.repo.state["project_analysis_events"] = []
    monkeypatch.setattr(tasks, "load_state", lambda *_a, **_k: None)
    monkeypatch.setattr(tasks, "flush_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        tasks,
        "_dispatch_project_analysis_task",
        lambda *_a, **_k: {"mode": "disabled", "taskId": None},
    )

    result = tasks.project_analysis_prepare.run("PARUN-RETRY")

    # 节点 1 已有同运行身份的结果：从批次方案剔除，历史 id 并入 derived；
    # 节点 2 的历史结果来自另一个模型（幂等键不同），必须重打
    assert result["reusedNodeIds"] == [1]
    assert result["derivedReviewRunIds"] == ["RRUN-PA-DONE1"]
    assert [b["nodeIds"] for b in result["batchPlan"]] == [[2], [3]]
    assert result["batchCount"] == 2


def test_failure_phase_is_partial_when_batches_already_persisted() -> None:
    from libs.project_analysis.execution import project_analysis_failure_phase

    assert project_analysis_failure_phase({"persistedNodeCount": 0}) == "failed"
    assert project_analysis_failure_phase({"persistedNodeCount": 3}) == "partial_failure"
