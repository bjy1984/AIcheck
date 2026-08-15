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


def test_落库认执行时手上那个对象而不是再查一次():
    """跑完了却落库落成旧的——同一个根因咬的第二口。

    实测：事件一路到 review_run.waiting_human_review，库里那条运行仍是
    queued、promptAudit 0。因为并发重载换掉了 repo.state["review_runs"]，
    执行改的那个对象已经和 state 脱钩，再 find_one 查到的是重载来的干净副本。
    """
    source = inspect.getsource(execution.execute_review_run_inline)
    assert "_INFLIGHT_REVIEW_RUNS" in source, "落库要认执行时手上那个对象"
    assert 'records["review_runs"] = [inflight]' in source

    body = inspect.getsource(execution._execute_review_run_inline)
    assert "_INFLIGHT_REVIEW_RUNS[review_run_id] = review_run" in body

    # 用完要清掉，否则长跑进程会把每一条运行记录都留在内存里。
    assert "_INFLIGHT_REVIEW_RUNS.pop" in source


def test_执行期间的运行记录被钉住不许被并发加载覆盖():
    """只「记住对象」不够：执行体里后续还会再 find_one 拿这条运行，
    被覆盖之后拿到的是另一个对象，改在那上面，记住的那份反而成了旧的。

    实测就栽在这：事件一路跑到 review_run.waiting_human，
    库里那条运行仍是 queued、revision=1。
    """
    body = inspect.getsource(execution._execute_review_run_inline)
    assert "repo.pin_object(" in body, "执行期间要钉住，别让并发加载把它换掉"

    wrapper = inspect.getsource(execution.execute_review_run_inline)
    assert "unpin_object" in wrapper, "跑完必须解钉，否则这条记录永远读不到新数据"


def test_钉住的集合名取自_STATE_COLLECTIONS_而不是写死():
    """写死字符串一旦和真实集合名对不上，钉住会**静默失效**：
    钉了个不存在的集合，谁都不会报错，bug 原样回来。"""
    from libs.db.repository import STATE_COLLECTIONS

    assert execution.REVIEW_RUN_COLLECTION_NAME == STATE_COLLECTIONS["review_runs"]


def test_加载时钉住的记录既不被覆盖也不刷新_baseline():
    """baseline 也要一起跳过。只挡覆盖、却把 baseline 换成库里的值，
    落库时就会认为「没改过」而跳过写入——又是一次静默的丢失。"""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "libs" / "db" / "repository.py"
    ).read_text(encoding="utf-8")
    idx = source.index("def load_review_run_scope_from_sync_postgres")
    block = source[idx : idx + 6000]
    assert block.count("object_is_pinned") >= 2, "覆盖与 baseline 两处都要挡"


def test_三条加载路径都要保住钉住的记录():
    """钉住只挡了 review-run 专用加载器，通用作用域加载照样把整张列表丢弃重建——
    轮询走的正是后者。只堵一个入口等于没堵：实测运行照样停在 queued。

    三处替换 state 的地方（两处通用 + 一处 review-run 作用域）必须一致。
    """
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "libs" / "db" / "repository.py"
    ).read_text(encoding="utf-8")
    # 只看真正的语句行——注释和文档字符串里提到这句话是在解释历史，不算违规。
    offending = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("self.state[state_key] = loaded")
    ]
    assert not offending, f"还有加载路径在整张丢弃重建：{offending}"
    assert source.count("apply_loaded_collection(state_key") == 2
    assert source.count("pinned_baseline_entries()") >= 2, "baseline 也要保住，否则落库判为未改动"
