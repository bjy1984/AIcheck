"""ReviewRun 已经结束了，ai_run 不许还说「推理中」。

## 线上实测（2026-08-16，监检工作台节点 24）

    ReviewRun RRUN-CECAAFEE2C  status=failed   16:56:04 → 16:56:13（9 秒）
    ai_run   AIRUN-24-2687DF44 status=推理中   至今未变

界面于是显示「7 步 · 进行中 3/7」，**硬刷新也不变**——不是轮询没跟上，
是数据本身就停在那里。全库 80 条 ai_run 里有 15 条这样。

用户看到的就是 PDF 里那句「ai 对话等待了很久，一直在执行中」。

## 两层修复

写侧：收尾时 `repo.find_one("ai_runs", ...)` 返回 None 会让整段回写被
`if ai_run:` 静默跳过。而 None 未必是记录不存在，也可能是并发的作用域加载把
repo.state["ai_runs"] 换成了另一批（这个坑在 review_runs 上已经付过一次学费）。
现在 resolve_ai_run 会重载再找，还找不到就 logging.exception。

读侧：**已经卡住的记录不会自己好**。下发时按关联 ReviewRun 的实况纠正显示，
只改展示不改库——库里那份是执行留痕，事后追责要看原样。
"""

from __future__ import annotations

import inspect

from apps.api import routes
from libs.review_orchestrator import execution


def test_写侧找不到_ai_run_要出声而不是静默跳过():
    source = inspect.getsource(execution.resolve_ai_run)
    assert "load_review_run_state" in source, "内存里找不到时要按作用域重载再找一次"
    assert "logging.exception" in source, "还找不到必须出声——静默跳过等于永远显示执行中"


def test_收尾路径都走解析器():
    """任何一处漏掉，那条运行就会永远卡在推理中。"""
    source = inspect.getsource(execution)
    assert 'repo.find_one("ai_runs", str(review_run.get("aiRunId' not in source, (
        "还有直接 find_one 的收尾路径没走 resolve_ai_run"
    )
    # 两种形式：worker 收尾允许重载，API 路径只读查找。
    # 重载不能在 API 里做——作用域加载会把这次请求正在改的记录整批换掉，
    # 请求随后按旧对象提交，报出来的却是幂等冲突，查起来完全指不到这里。
    assert source.count("resolve_ai_run(review_run") >= 5
    assert source.count("allow_reload=True") == 2, "只有 worker 收尾路径可以重载"


_SEQ = iter(range(1, 999))


def _run(status: str, review_status: str) -> dict:
    # 每个用例用独立 id：共用一套 id 会让后一个用例找到前一个的 ReviewRun，
    # 测出来的是污染，不是行为。
    n = next(_SEQ)
    ai_run = {
        "id": f"AIRUN-T-{n}",
        "status": status,
        "reviewRunId": f"RRUN-T-{n}",
        "projectId": "P-T",
        "nodeId": 24,
    }
    review_run = {
        "id": f"RRUN-T-{n}",
        "reviewRunId": f"RRUN-T-{n}",
        "status": review_status,
        "projectId": "P-T",
        "nodeId": 24,
    }
    routes.repo.state.setdefault("ai_runs", []).append(ai_run)
    routes.repo.state.setdefault("review_runs", []).append(review_run)
    return routes.safe_ai_run_view(ai_run)


def test_运行失败了就显示失败():
    view = _run("推理中", "failed")
    assert view["status"] == "失败"
    assert view["statusReconciledFrom"] == "reviewRun"


def test_运行已交人工就显示待人工确认():
    view = _run("推理中", "waiting_human_review")
    assert view["status"] == "待人工确认"


def test_运行确实还在跑就不改():
    view = _run("推理中", "running")
    assert view["status"] == "推理中"
    assert "statusReconciledFrom" not in view


def test_已终态的_ai_run_不被覆盖():
    """人工已确认过的运行，不能被 ReviewRun 的状态倒回去。"""
    view = _run("已人工确认", "failed")
    assert view["status"] == "已人工确认"
