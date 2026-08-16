"""输入 token 上限默认不设——那道闸原本在替模型拒绝请求。

## 线上实测（2026-08-16）

    RRUN-CECAAFEE2C  P-2026-8FC0B5 节点 24  failed
    QwenRuntime review.chat failed: reason REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED

上限写死 24000，而生产模型的上下文远大于它。节点资料一多就整次失败，
监检**一份资料都没审到**，界面只显示「执行异常」。

顺带记一次我自己的错判：此前我用「缺项预审」跑通就宣布这条已修——
那是另一条路径。**换条路验证等于没验证。**

## 判据

- 默认（不设环境变量）＝不限：不裁减、不报超预算
- 显式给正数才重新设闸
- 0 不是「上限为 0」。把 0 当上限会让每次运行都超预算，
  从「偶尔失败」变成「永远失败」——这种翻转比原问题更糟
- 不限模式下误调裁减函数要当场报错，不能算出负余量把证据全裁光
"""

from __future__ import annotations

import pytest

from libs.review_orchestrator import execution as ex


def test_默认不限(monkeypatch):
    monkeypatch.delenv("AICHECK_REVIEW_MAX_INPUT_TOKENS", raising=False)
    assert ex._review_max_input_tokens() == 0


def test_显式正数才设闸(monkeypatch):
    monkeypatch.setenv("AICHECK_REVIEW_MAX_INPUT_TOKENS", "60000")
    assert ex._review_max_input_tokens() == 60000


def test_零和负数都表示不限(monkeypatch):
    for raw in ("0", "-1", "", "  "):
        monkeypatch.setenv("AICHECK_REVIEW_MAX_INPUT_TOKENS", raw)
        assert ex._review_max_input_tokens() == 0, raw


def test_乱填不炸也不误设闸(monkeypatch):
    """配置写错时宁可不限，也不要设成一个莫名其妙的小数字。"""
    monkeypatch.setenv("AICHECK_REVIEW_MAX_INPUT_TOKENS", "两万四")
    assert ex._review_max_input_tokens() == 0


def test_不限时误调裁减要当场报错():
    """用 0 算余量会得到负数，把证据全裁光再报超预算——
    症状是「明明没设上限却永远超预算」，最难查的那种。"""
    with pytest.raises(ValueError, match="不应调用证据裁减"):
        ex.trim_review_input_to_budget(
            {"reviewRunId": "RRUN-TEST"},
            {"groundingInput": {}},
            {"maxInputTokens": 0},
        )


def test_判断处都带了不限分支():
    """两处判断必须都看 input_cap > 0——**同一条规则写两处、只改一处**
    是这个仓库反复出现的形态。"""
    import inspect

    source = inspect.getsource(ex.generate_finding_drafts)
    assert source.count("input_cap > 0") == 2, "裁减入口和最终判断都要认「不限」"
