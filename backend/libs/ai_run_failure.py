"""把 AI 运行失败翻译成监检看得懂、且知道下一步该干什么的说法。

线上失败记录里躺着这么一条 errorMessage：

    Failed client connect: Server connection error:
    tonic::transport::Error(Transport, ConnectError(ConnectionRefused))

界面把它整个吞掉，只显示两个字「异常」。监检看到「异常」既不知道是模型没配、
超时、还是这份资料本身有问题，也不知道该不该重跑——于是只能去问人。

这就是这轮审计反复撞见的同一件事：**静默的失败比响亮的失败更贵**。
错误信息本来就在库里，缺的只是把它说成人话。

分类的意义不在措辞好看，在于回答两个问题：
  1. 这是谁的问题——环境没起来，还是资料本身不合格？
  2. 重跑有没有用？环境类的重跑之前先修环境，否则只是再失败一次。
"""

from __future__ import annotations

import re
from typing import Any

# 失败状态的多种写法。中英混用是历史遗留：ai_runs 写中文，review_runs 写英文。
FAILED_STATUSES = {"失败", "failed", "failed_to_start", "error"}


class FailureKind:
    ORCHESTRATION = "orchestration"
    MODEL = "model"
    TIMEOUT = "timeout"
    MATERIAL = "material"
    UNKNOWN = "unknown"


# 顺序有意义：先匹配到的先用。编排层连不上要排在模型之前——Temporal 都没起来时，
# 模型配没配根本轮不到。
_SIGNATURES: tuple[tuple[str, str, str, bool], ...] = (
    (
        # 只认编排层自己的特征串。别拿泛化的 "connection refused" 去认——模型代理
        # 连不上也是这句话，会被误判成编排问题，把人引到错的方向去查。
        r"tonic::transport|temporal|workflow.*not.*found",
        FailureKind.ORCHESTRATION,
        "编排服务（Temporal）连不上，本次审查没有真正开始执行。",
        False,
    ),
    (
        r"litellm|openai|deepseek|qwen|api[_ ]?key|unauthorized|401|invalid.*model",
        FailureKind.MODEL,
        "模型服务不可用或未正确配置，AI 无法给出判定。",
        False,
    ),
    (
        r"timeout|timed out|deadline",
        FailureKind.TIMEOUT,
        "调用超时。资料较大或服务繁忙时会出现，通常可以重跑。",
        True,
    ),
    (
        r"no.*ocr|ocr.*missing|empty.*text|no.*evidence|资料.*缺",
        FailureKind.MATERIAL,
        "资料侧缺少可用的 OCR 结果，AI 没有可判定的依据。",
        False,
    ),
)


def classify_failure(message: str) -> tuple[str, str, bool]:
    """返回 (类别, 中文说明, 重跑是否可能有用)。"""
    text = str(message or "").lower()
    for pattern, kind, reason, retryable in _SIGNATURES:
        if re.search(pattern, text):
            return kind, reason, retryable
    return (
        FailureKind.UNKNOWN,
        "AI 审查未能完成，原始报错见下方详情。",
        True,
    )


def next_step_for(kind: str) -> str:
    """告诉人下一步做什么。只说「失败了」等于把问题原样丢回给用户。"""
    return {
        FailureKind.ORCHESTRATION: "属于环境问题，重跑无用。请联系运维确认编排服务已启动。",
        FailureKind.MODEL: "属于环境问题，重跑无用。请联系运维确认模型服务与密钥配置。",
        FailureKind.TIMEOUT: "可以直接重跑；反复超时请联系运维。",
        FailureKind.MATERIAL: "先确认该节点资料已完成 OCR 抽取，再重跑。",
        FailureKind.UNKNOWN: "可以重跑一次；仍失败请把下方详情提供给运维。",
    }.get(kind, "可以重跑一次；仍失败请把下方详情提供给运维。")


def ai_run_failure_view(run: dict[str, Any]) -> dict[str, Any] | None:
    """失败运行的可读归因；没失败返回 None。

    detail 保留原始报错——归因是给监检看的，原文是给运维查的，两个都要有。
    真出了没预料到的错时，原文是唯一能追下去的线索。
    """
    status = str(run.get("status") or "")
    if status not in FAILED_STATUSES:
        return None
    # 各链路的字段名不统一：ai_runs 写 errorMessage，review_runs 的对账脚本写 errorCode
    detail = str(
        run.get("errorMessage") or run.get("error") or run.get("errorCode") or ""
    ).strip()
    kind, reason, retryable = classify_failure(detail)
    return {
        "kind": kind,
        "reason": reason,
        "nextStep": next_step_for(kind),
        "retryable": retryable,
        # 没有原始报错时明说，而不是给一个空字符串让人以为界面坏了
        "detail": detail or "（未记录原始报错——这本身是个需要修的问题）",
        "detailRecorded": bool(detail),
    }
