"""AI 复核对话：模型没跑成时，回给监检的那段话。

## 为什么单独拎出来写

2026-08-14 线上实测：监检点了推荐问题「还缺哪些必传资料的已确认证据？分别对应
哪个审查点？」，系统回的是——

    我已加载当前节点“焊工资格证及持证合格项目”的固定规则、证据就绪状态和
    ReviewRun。当前运行状态：waiting_human_review；资料就绪：0/4，待确认证据：0。
    你可以继续让我检索证据、查看标准条款或草拟意见。

而同一条消息的 execution 是 `modelCalled: false`、`toolCallCount: 0`、
`failureReason: INTEGRATIONSERVICEERROR`，status 却写着 `completed`。

这段话的问题不是不好看，是**它把没做的事说成做了**：

  「我已加载…」     第一人称完成时，读起来像分析过了
  「你可以继续让我…」 邀请你再用一次同样会失败的能力
  提问只字未提       监检问的那个问题，回答里没有任何痕迹

监检是拿这套系统出具监督检验意见的。一段读起来像回答的话，配一行 11px 的
「确定性降级」脚注，正文与脚注互相打脸——而人只会读正文。

在这个行业里，**说不出来比说错强**。所以这里的规则是：先说没做什么，再说
为什么，最后才给手上确实有的确定性事实。

## 与 R-8 是同一类错误

上游提交 `5eef7c5 inline 编排下不再承诺一个没人兑现的重试` 修的是同一件事：
状态里承诺了一个没人会去做的动作。这里承诺的是一个当场就会再失败的能力。
"""

from __future__ import annotations

from typing import Any

# 失败原因 → 给监检看的人话。
#
# 键统一按大写比对：同一个原因在库里同时存在 `IntegrationServiceError`（早期
# 写法）和 `INTEGRATIONSERVICEERROR`（review_conversation_model_failure_kind
# 归一后的写法），两种都要认，少认一种就会掉进「未知原因」。
_REASON_TEXT = {
    "LLM_EXECUTION_DISABLED": "本次部署显式关闭了模型调用",
    "INTEGRATIONSERVICEERROR": "模型服务当前不可达",
    "CONNECTERROR": "模型服务当前不可达",
    "CONNECTTIMEOUT": "模型服务连接超时",
    "READTIMEOUT": "模型服务响应超时",
    "TIMEOUTEXCEPTION": "模型服务响应超时",
    "REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED": "本次上下文超出输入预算，未发起调用",
    "LLM_OUTPUT_TRUNCATED": "模型输出被截断，结果不完整",
    "LLM_OUTPUT_INVALID": "模型输出无法解析",
    "LLM_OUTPUT_EMPTY": "模型没有产出可用回答",
    # 推理模型专有：推理过程占满了输出额度，轮到写结论时已经没有余量。
    # 与「模型没话说」分开说，因为处置不同——这个调大预算就能解决。
    "LLM_OUTPUT_BUDGET_EXHAUSTED_BY_REASONING": (
        "模型的推理过程占满了本次输出额度，没能写出结论"
        "（可调大 AICHECK_REVIEW_CONVERSATION_MAX_OUTPUT_TOKENS）"
    ),
}


def failure_cause_text(failure_reason: str | None) -> str:
    """把内部失败原因翻成一句监检看得懂的话。

    认不出的原因**不吞掉**，原样带出来：一个陌生的英文标识至少能让人拿去问，
    而「未知原因」什么也不能。
    """
    reason = str(failure_reason or "").strip()
    if not reason:
        return "本次没有发起模型调用"
    mapped = _REASON_TEXT.get(reason.upper())
    if mapped:
        return mapped
    return f"模型调用失败（{reason[:80]}）"


def _readiness_line(run_status: str, readiness: dict[str, Any] | None) -> str:
    data = readiness if isinstance(readiness, dict) else {}
    satisfied = data.get("satisfiedCount", 0)
    required = data.get("requiredCount", 0)
    pending = data.get("pendingCount", 0)
    return f"当前状态（由系统直接读取，不经模型）：运行状态 {run_status}；资料就绪 {satisfied}/{required}；待确认证据 {pending}。"


def fallback_answer_text(
    *,
    node_name: str,
    run_status: str,
    readiness: dict[str, Any] | None,
    failure_reason: str | None,
) -> str:
    """模型没跑成时的回复正文。

    顺序是刻意的：**先说没答上，再说原因，最后才给确定性事实**。

    确定性事实放最后而不是最前——放最前就又变成了「看起来像个回答」的样子，
    人扫一眼看到数字就走了，不会注意到问题根本没被回答。
    """
    node_label = str(node_name or "").strip() or "当前节点"
    lines = [
        f"⚠️ 本次未能回答你的问题：{failure_cause_text(failure_reason)}。",
        f"节点「{node_label}」的这次提问没有经过模型分析，以下内容不构成对该问题的回答。",
        "",
        _readiness_line(str(run_status or "未发起"), readiness),
        "",
        # 这三条是确定性命令，不经模型，当前确实可用——所以可以提。
        # （已核对 review_deterministic_command_blocks：三者均为纯数据组装。）
        (
            "现在仍可使用的确定性功能：「检索证据」列出可定位证据候选、「标准条款」"
            "展示本节点已固化的条款、「草拟意见」基于 ReviewRun 现有草稿生成文本。"
            "它们不经过模型，结果可直接核对。"
        ),
        "",
        "需要模型分析的问题，请在模型服务恢复后重试。",
    ]
    return "\n".join(lines)
