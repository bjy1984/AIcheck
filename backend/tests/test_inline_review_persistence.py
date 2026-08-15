"""同步执行的 ReviewRun 必须落库。

## 线上症状（2026-08-15 前端操作审计）

监检点「发起缺项预审」，接口返回 `status: waiting_human_review`，
而数据库里那条运行永远停在 `queued`、promptAudit 0 字符、findingDrafts 0 条，
等 45 秒仍是 queued。界面轮询读的是落库状态，所以**永远显示排队中**。

三个来源三种说法：

    API 返回   : waiting_human_review
    数据库     : queued，无提示词、无结论
    再用 API 读 : None

## 根因与形状

`_execute_review_run_inline` 有 6 个返回点，一次 flush_state_records 都没有。
失败能落库是因为异常路径在 dispatcher 和各 except 分支里另外显式调了 flush——
于是形成最坏的那种不对称：**失败看得见，成功看不见**。

这个形状值得单独钉住：用 try/finally 而不是在每个 return 前加一行，
因为出口还会再增加，加一个忘一个，同样的 bug 会原样回来。
"""

from __future__ import annotations

import inspect

from libs.review_orchestrator import execution


def test_每条出口都落库而不是逐个_return_前手动加():
    """包装函数必须用 try/finally 覆盖全部出口，包括抛异常那条。"""
    source = inspect.getsource(execution.execute_review_run_inline)
    assert "try:" in source and "finally:" in source, "落库必须在 finally 里，别指望逐个 return 都记得加"
    assert "_execute_review_run_inline" in source, "真正的执行体应当被包在里面"
    assert "flush_state_records" in source


def test_落库失败不吞掉已经跑完的结果():
    """落库出问题时，不能把审查结果连带丢掉。

    那会从「结果看不见」变成「结果没了」——后者严重得多：
    模型算过、token 花过，人却拿不到任何东西。
    """
    source = inspect.getsource(execution.execute_review_run_inline)
    finally_block = source[source.index("finally:"):]
    assert "except Exception" in finally_block, "落库要尽力而为，不该让它掀翻主流程"


def test_执行体本身仍然只管执行():
    """包装层负责落库，执行体负责跑——两件事分开，改哪个都不牵连另一个。"""
    body = inspect.getsource(execution._execute_review_run_inline)
    assert "ensure_review_state()" in body
    # 出口数量本身不做断言（会随业务增加），只确认它确实是多出口结构，
    # 这正是「逐个 return 前加 flush」不可靠的原因。
    assert body.count("        return ") + body.count("            return ") >= 3
