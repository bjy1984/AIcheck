"""重跑不能带着上一次的死亡证明重生。

## 线上实测（2026-08-16）

用户报「AI 审计显示执行异常，然后显示失败」。查 RRUN-REPLAY-D748CE0E：

    graph_node.succeeded  QwenRuntime 生成审查草稿
    graph_node.succeeded  Schema 校验 / 证据校验 / 依据校验 / Critic 复核
    quality_gate.evaluated
    graph_node.succeeded  持久化草稿
    review_run.waiting_human  等待人工确认

**全程 succeeded**，而记录上挂着
`errorCode: REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED`——那是被重跑的**父运行**的。
`clone_review_run_for_replay` 用 repo.clone 整份复制，清了
startedAt/finishedAt/humanDecision，唯独漏了 errorCode/errorMessage。

于是界面照实显示「执行异常」：数据没说谎，是它抄错了来源。
**重跑的意义就是再试一次；带着上次的失败重生，等于没重跑。**

## 判据

- 父运行的失败字段一个都不许带进子运行
- 其余可继承的上下文（节点、业务包、证据快照）要照常带，
  否则重跑就不是「同一份输入再跑一次」了
"""

from __future__ import annotations

from libs.review_orchestrator import execution as ex


def _failed_parent() -> dict:
    return {
        "id": "RRUN-PARENT",
        "reviewRunId": "RRUN-PARENT",
        "nodeId": 24,
        "projectId": "P-TEST",
        "businessPackId": "engineering_inspection_v1",
        "status": "failed",
        "errorCode": "REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED",
        "errorMessage": "QwenRuntime review.chat failed: reason REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED",
        "failureReason": "budget",
        "findingDrafts": [{"id": "D1"}],
        "humanDecision": {"decision": "rejected"},
        "startedAt": "2026-08-15 16:56:04",
        "finishedAt": "2026-08-15 16:56:20",
    }


def test_重跑不继承失败字段():
    child = ex.clone_review_run_for_replay(_failed_parent(), run_mode="production", reason="验证")
    assert child["errorCode"] is None, "带着父运行的错误码，界面会把成功的运行显示成失败"
    assert child["errorMessage"] is None
    assert child["failureReason"] is None
    assert child["status"] == "queued"
    assert child["startedAt"] is None and child["finishedAt"] is None
    assert child["humanDecision"] is None
    assert child["findingDrafts"] == []


def test_重跑仍继承输入上下文():
    """清错误不能顺手把输入也清了——那样就不是同一份输入再跑一次。"""
    child = ex.clone_review_run_for_replay(_failed_parent(), run_mode="production", reason="验证")
    assert child["nodeId"] == 24
    assert child["projectId"] == "P-TEST"
    assert child["businessPackId"] == "engineering_inspection_v1"
    assert child["parentReviewRunId"] == "RRUN-PARENT"


def test_父运行本身不被改动():
    parent = _failed_parent()
    ex.clone_review_run_for_replay(parent, run_mode="production", reason="验证")
    assert parent["errorCode"] == "REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED", (
        "父运行是执行留痕，不能因为重跑就把它的失败记录抹掉"
    )
