"""兜底文案的底线：不能把没做的事说成做了。"""

from __future__ import annotations

import pytest

from libs.review_conversation_fallback import (
    failure_cause_text,
    fallback_answer_text,
)

# 2026-08-14 线上 RSESSION-972DC4ED41 的真实取值
NODE = "焊工资格证及持证合格项目"
READINESS = {"satisfiedCount": 0, "requiredCount": 4, "pendingCount": 0}


def _text(reason: str | None = "INTEGRATIONSERVICEERROR") -> str:
    return fallback_answer_text(
        node_name=NODE,
        run_status="waiting_human_review",
        readiness=READINESS,
        failure_reason=reason,
    )


def test_不得声称自己做过分析():
    """旧文案「我已加载…」的问题就在这里：第一人称完成时。

    监检读到「我已加载固定规则、证据就绪状态和 ReviewRun」，合理理解是系统
    看过这些东西了。实际上模型一次都没被调用。
    """
    text = _text()
    for claim in ("我已加载", "我已分析", "已为你分析", "已完成核查"):
        assert claim not in text, f"兜底文案不得声称做过分析：{claim}"


def test_不得邀请用户再用一次同样会失败的能力():
    """旧文案结尾是「你可以继续让我检索证据、查看标准条款或草拟意见」。

    「让我」= 让模型。模型此刻不可达，这个邀请当场就会再失败一次。
    可以提这三项功能，但必须点明它们不经过模型。
    """
    text = _text()
    assert "让我" not in text
    # 提到这三项时必须同时说明它们是确定性的
    assert "检索证据" in text
    assert "不经过模型" in text


def test_开头就说没答上而不是把状态摆前面():
    """顺序是这个文案的全部价值。

    确定性事实放最前，人扫一眼看到「0/4」就走了，不会注意到问题没被回答。
    """
    text = _text()
    first_line = text.splitlines()[0]
    assert "未能回答" in first_line
    # 状态数字必须在「未能回答」之后出现
    assert text.index("资料就绪") > text.index("未能回答")


def test_原因要说人话且不吞未知原因():
    assert failure_cause_text("INTEGRATIONSERVICEERROR") == "模型服务当前不可达"
    # 早期写法与归一后写法都要认，少认一种就掉进「未知原因」
    assert failure_cause_text("IntegrationServiceError") == "模型服务当前不可达"
    assert failure_cause_text("LLM_EXECUTION_DISABLED") == "本次部署显式关闭了模型调用"
    # 认不出的原因原样带出，不能吞成「未知」——陌生标识至少能拿去问
    unknown = failure_cause_text("SOME_NEW_REASON_X")
    assert "SOME_NEW_REASON_X" in unknown
    # 没有原因时也要有话说
    assert failure_cause_text(None) == "本次没有发起模型调用"
    assert failure_cause_text("") == "本次没有发起模型调用"


def test_确定性事实要标明来源():
    """这些数字是真的，但必须让人知道它们不是模型算出来的。"""
    text = _text()
    assert "不经模型" in text
    assert "0/4" in text


@pytest.mark.parametrize("reason", [None, "", "INTEGRATIONSERVICEERROR", "怪东西"])
def test_任何原因下都不产出空文案(reason: str | None):
    text = fallback_answer_text(
        node_name="", run_status="", readiness=None, failure_reason=reason
    )
    assert len(text.strip()) > 40
    assert "当前节点" in text  # 节点名为空时的兜底称呼


def test_readiness_缺字段时不炸():
    """readiness 由上游拼装，字段缺失时兜底文案在主链路上，不能带崩对话。"""
    text = fallback_answer_text(
        node_name=NODE, run_status="x", readiness={}, failure_reason=None
    )
    assert "0/0" in text
    text = fallback_answer_text(
        node_name=NODE, run_status="x", readiness=None, failure_reason=None
    )
    assert "0/0" in text
