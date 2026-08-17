"""节点的自动审核状态（0817 第 3 条）。

    「监检平台显示自动审核状态，可以自动回复以及人工回复」

## 为什么这个口径要单独守

这个仓库反复出现的问题是**状态和实际不符**：显示 failed 实际成功了、
显示执行中实际早停了。所以每个状态都必须带 reason，
说明它是从哪条记录推出来的。

**说不出理由的状态标签，和没有标签一样没用**——它只是让人以为自己知道了。

## 人工优先，但要留痕

人看过之后的判断压过机器的判断。但覆盖要看得出来：
overriddenAutoConclusion 让监检知道「机器原本说的是另一回事」，
不然人工改判之后，AI 那次判断就凭空消失了。
"""

from __future__ import annotations

from libs.auto_review_status import (
    AUTO_PASSED,
    FAILED,
    HUMAN_PASSED,
    NEEDS_FIX,
    NEEDS_HUMAN,
    NOT_STARTED,
    RUNNING,
    auto_review_status,
)


def test_没跑过和跑了没结果要分开():
    """处置方式不同：一个是去发起，一个是去看为什么没结论。"""
    never = auto_review_status(None)
    assert never["status"] == NOT_STARTED
    assert "还没有发起" in never["reason"]

    finished_without_conclusion = auto_review_status({"status": "已完成", "conclusion": ""})
    assert finished_without_conclusion["status"] == NEEDS_HUMAN
    assert finished_without_conclusion["status"] != NOT_STARTED


def test_运行中():
    for status in ("运行中", "排队中", "RUNNING"):
        result = auto_review_status({"status": status})
        assert result["status"] == RUNNING
        assert status in result["reason"], "没说清楚是哪种运行态"


def test_失败必须能归因():
    """只说「失败」的话，监检不知道该重跑还是该补资料。"""
    result = auto_review_status({"status": "失败", "errorMessage": "输入超出上限"})
    assert result["status"] == FAILED
    assert "输入超出上限" in result["reason"]


def test_失败但没记原因时如实说没记():
    result = auto_review_status({"status": "失败"})
    assert result["status"] == FAILED
    assert "未记录失败原因" in result["reason"], "编一个原因比不说更糟"


def test_自动结论():
    assert auto_review_status({"status": "已完成", "conclusion": "满足要求"})["status"] == AUTO_PASSED
    assert auto_review_status({"status": "已完成", "conclusion": "需补正"})["status"] == NEEDS_FIX


def test_人工结论压过自动结论():
    result = auto_review_status(
        {"status": "已完成", "conclusion": "需补正"},
        {"conclusion": "满足要求"},
    )
    assert result["status"] == HUMAN_PASSED
    assert result["source"] == "human"


def test_人工改判要留痕():
    """不留痕的话，AI 那次判断在界面上就凭空消失了。"""
    result = auto_review_status(
        {"status": "已完成", "conclusion": "需补正"},
        {"conclusion": "满足要求"},
    )
    assert result["overriddenAutoConclusion"] == "需补正"


def test_人工和自动结论一致时不报覆盖():
    """一致就不是「覆盖」。硬说成覆盖会让人以为发生过分歧。"""
    result = auto_review_status(
        {"status": "已完成", "conclusion": "满足要求"},
        {"conclusion": "满足要求"},
    )
    assert result["overriddenAutoConclusion"] == ""


def test_不适用是终态不是需补正():
    """N-1 修过一次的老坑：不适用被映射成需补正。"""
    assert auto_review_status(None, {"conclusion": "不适用"})["status"] == HUMAN_PASSED


def test_证据不足停在待人工():
    assert auto_review_status(None, {"conclusion": "证据不足"})["status"] == NEEDS_HUMAN


def test_每个状态都有理由():
    """**说不出理由的状态标签和没有标签一样没用。**"""
    cases = [
        auto_review_status(None),
        auto_review_status({"status": "运行中"}),
        auto_review_status({"status": "失败"}),
        auto_review_status({"status": "已完成", "conclusion": "满足要求"}),
        auto_review_status({"status": "已完成", "conclusion": "需补正"}),
        auto_review_status({"status": "已完成", "conclusion": ""}),
        auto_review_status(None, {"conclusion": "满足要求"}),
        auto_review_status(None, {"conclusion": ""}),
    ]
    for result in cases:
        assert result["reason"], f"{result['status']} 没有理由"
        assert result["source"] in {"none", "auto", "human"}
