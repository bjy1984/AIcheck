"""节点的「自动审核状态」（0817 第 3 条）。

    「监检平台显示自动审核状态，可以自动回复以及人工回复」

## 为什么要有这个口径

监检打开一个节点，想先知道一件事：**这个节点现在到哪一步了。**
原先要自己看：有没有 review_run、跑到什么状态、有没有人工结论、
结论是什么。四处信息拼一遍才知道，而且每个界面拼法还不一样。

## 每个状态都要说得出为什么

这个仓库反复出现的问题是**状态和实际不符**：显示 failed 实际成功了、
显示执行中实际早停了。所以这里的每个状态都带 reason，
说明它是从哪条记录推出来的。

**说不出理由的状态标签，和没有标签一样没用**——它只是让人以为自己知道了。

## 人工结论优先于自动结论

人看过之后的判断压过机器的判断，这一点没有争议。
但覆盖要留痕：状态里带 overriddenAutoConclusion，
让人看得出「机器说的是另一回事」。
"""

from __future__ import annotations

from typing import Any

# 对外的状态词。别在别处再造一套近义词——
# 「审查中」和「运行中」并存的话，用户会以为是两种不同的东西。
NOT_STARTED = "未审查"
RUNNING = "自动审查中"
AUTO_PASSED = "自动通过"
NEEDS_HUMAN = "待人工确认"
HUMAN_PASSED = "人工通过"
NEEDS_FIX = "需补正"
FAILED = "自动审查失败"

_RUNNING_STATUSES = {"运行中", "排队中", "执行中", "RUNNING", "QUEUED", "PENDING"}
_FAILED_STATUSES = {"失败", "已失败", "FAILED", "ERROR"}

# 人工结论 -> 对外状态。和 routes.py 的 REVIEW_OPINION_NODE_STATUS 一致；
# 不一致的话，节点状态和这里的自动审核状态会互相打架。
_HUMAN_CONCLUSION = {
    "满足要求": HUMAN_PASSED,
    "需补正": NEEDS_FIX,
    "不适用": HUMAN_PASSED,
    "证据不足": NEEDS_HUMAN,
}


def auto_review_status(
    latest_run: dict[str, Any] | None,
    human_opinion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """算出节点的自动审核状态。

    返回 {status, reason, source, overriddenAutoConclusion}。
    reason 不是给日志看的，是**给界面显示**的：用户点开状态就该知道凭什么。
    """
    auto_conclusion = str((latest_run or {}).get("conclusion") or "")

    # 人工结论优先，但要留痕说明机器原本说的是什么
    if human_opinion:
        conclusion = str(human_opinion.get("conclusion") or "")
        status = _HUMAN_CONCLUSION.get(conclusion, NEEDS_HUMAN)
        overridden = auto_conclusion if auto_conclusion and auto_conclusion != conclusion else ""
        return {
            "status": status,
            "reason": f"监检人工结论：{conclusion or '（未填写结论）'}",
            "source": "human",
            "overriddenAutoConclusion": overridden,
        }

    if not latest_run:
        return {
            "status": NOT_STARTED,
            # 说清楚是「没跑过」而不是「跑了没结果」——处置方式不同
            "reason": "该节点还没有发起过 AI 审查",
            "source": "none",
            "overriddenAutoConclusion": "",
        }

    run_status = str(latest_run.get("status") or "")
    if run_status in _RUNNING_STATUSES:
        return {
            "status": RUNNING,
            "reason": f"审查运行中（{run_status}）",
            "source": "auto",
            "overriddenAutoConclusion": "",
        }
    if run_status in _FAILED_STATUSES:
        # 失败必须能归因。只说「失败」的话，监检不知道该重跑还是该补资料。
        detail = str(latest_run.get("errorMessage") or latest_run.get("failureReason") or "")
        return {
            "status": FAILED,
            "reason": f"审查失败：{detail or '未记录失败原因'}",
            "source": "auto",
            "overriddenAutoConclusion": "",
        }

    if auto_conclusion == "满足要求":
        return {
            "status": AUTO_PASSED,
            "reason": "AI 判定满足要求，等待监检确认",
            "source": "auto",
            "overriddenAutoConclusion": "",
        }
    if auto_conclusion == "需补正":
        return {
            "status": NEEDS_FIX,
            "reason": "AI 判定需补正",
            "source": "auto",
            "overriddenAutoConclusion": "",
        }

    # 跑完了但没有明确结论——这既不是通过也不是失败，
    # 混进上面任何一档都会误导人，所以单独一档。
    return {
        "status": NEEDS_HUMAN,
        "reason": f"审查已结束但未给出明确结论（{auto_conclusion or '无结论'}）",
        "source": "auto",
        "overriddenAutoConclusion": "",
    }
