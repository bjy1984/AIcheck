"""并发重载不能把正在派发的 ReviewRun 弄丢。

## 线上实测（2026-08-15，真实浏览器操作）

同一个 ai-recheck 调用，唯一差别是监检工作台开着与否：

    工作台开着（每 3 秒轮询一次）: 5.4s 返回，result.status=missing，运行永远停在 queued
    工作台关掉                  : 91.1s 返回，waiting_human_review，AiRun 完成

作用域加载会**整体替换** repo.state["review_runs"] 这个列表。ai-recheck 把新运行
插进内存后还没轮到执行，一次轮询把列表换掉，记录就没了 → 执行体报 missing。

而 dispatcher 里 `"status": "completed"` 是写死的，于是：
**执行体说没跑，上层说完成，界面说排队中——三个说法，没有一个报错。**

库里那一串永久 queued 的运行全是这么来的。
"""

from __future__ import annotations

import inspect

from libs.review_orchestrator import dispatcher, execution


def test_找不到时从库里捞回来再判定丢失():
    """建记录时已经落过库，所以「内存里没有」不等于「不存在」。"""
    source = inspect.getsource(execution._execute_review_run_inline)
    head = source[: source.index('return {"reviewRunId": review_run_id, "status": "missing"}')]
    assert "load_review_run_state" in head, "内存里找不到就直接判 missing，会被并发重载误伤"


def test_执行体说没跑就不能对上层报完成():
    """写死的 completed 是这次事故里最贵的一行：它让失败看起来像成功。"""
    source = inspect.getsource(dispatcher.dispatch_existing_review_run)
    inline_block = source[source.index('if mode == "inline":') :]
    inline_block = inline_block[: inline_block.index('if mode == "temporal":')]
    assert '"status": "completed", "reviewRunId"' not in inline_block, "别再写死 completed"
    assert "missing" in inline_block, "要按执行体的真实结果判定"
    assert "failed_to_start" in inline_block


def test_等待人工的状态仍然算启动成功():
    """waiting_human_review / waiting_human_input 是正常终点，不能被判成失败。"""
    source = inspect.getsource(dispatcher.dispatch_existing_review_run)
    inline_block = source[source.index('if mode == "inline":') :]
    inline_block = inline_block[: inline_block.index('if mode == "temporal":')]
    # 判据是「排除法」而不是「白名单」：新增的中间状态默认算启动成功，
    # 免得每加一个状态就要回来改一次，漏改就又变成静默失败。
    assert "not in" in inline_block
    assert "waiting" not in inline_block, "别用白名单，新状态会漏"
