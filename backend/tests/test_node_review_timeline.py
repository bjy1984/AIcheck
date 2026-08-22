"""AI 回复和人工回复排在同一条时间线上（0817 第 3 条）。

    「资料 ai 识别。可以自动回复以及人工回复。」

## 原先的问题

两条信息分在两处：AI 运行在 aiRuns 里，人工结论在 reviewOpinions 里。
监检要判断「这个节点到底经历了什么」，得自己在两个列表之间按时间对一遍——
**而人一旦要自己对时间，就一定会对错**，尤其是 AI 跑了几轮、
中间还夹着人工改判的时候。

## 三条判据

1. 谁说的要写清楚（actor）。只有结论没有来源的条目，
   在界面上和另一种来源的条目长得一模一样。
2. 人工改判要带上它覆盖了哪条 AI 结论。不然翻时间线只看到两条并列的结论，
   看不出后一条是在推翻前一条。
3. 时间缺失的排最后。用空串排序会跑到最前，被读成「最早发生的事」。
"""

from __future__ import annotations

from libs.node_review_timeline import node_review_timeline


def test_按时间正序合并():
    events = node_review_timeline(
        ai_runs=[{"id": "R2", "finishedAt": "2026-08-17 10:00:00", "conclusion": "需补正"}],
        review_opinions=[{"id": "O1", "createdAt": "2026-08-17 12:00:00", "conclusion": "满足要求"}],
        rectifications=[{"id": "F1", "createdAt": "2026-08-17 11:00:00", "reason": "补交材质证明"}],
    )
    assert [event["refId"] for event in events] == ["R2", "F1", "O1"]


def test_每条都标出是谁说的():
    """只有结论没有来源的条目，和另一种来源的条目长得一模一样。"""
    events = node_review_timeline(
        [{"id": "R1", "createdAt": "1", "conclusion": "满足要求"}],
        [{"id": "O1", "createdAt": "2", "conclusion": "需补正"}],
    )
    assert [event["actor"] for event in events] == ["ai", "human"]
    assert all(event["title"] for event in events)


def test_人工改判带出被覆盖的那条():
    """不带的话，翻时间线只看到两条并列的结论，看不出后一条在推翻前一条。"""
    events = node_review_timeline(
        [{"id": "R1", "createdAt": "1", "conclusion": "需补正"}],
        [{"id": "O1", "createdAt": "2", "conclusion": "满足要求", "aiRunId": "R1"}],
    )
    human = next(event for event in events if event["actor"] == "human")
    assert human["overrides"] == "R1"


def test_没有结论时如实说没有():
    """留空会被读成「通过」——这是最危险的一种默认。"""
    events = node_review_timeline([{"id": "R1", "createdAt": "1", "status": "运行中"}], [])
    assert "未给出结论" in events[0]["summary"]
    assert "运行中" in events[0]["summary"]


def test_已完成运行优先采用嵌套建议结论():
    """防止时间线读取旧 conclusion 而把已完成的 AI 建议显示错。"""
    events = node_review_timeline(
        [
            {
                "id": "R1",
                "status": "completed",
                "conclusion": "满足要求",
                "suggestion": {"result": "证据不足"},
            }
        ],
        [],
    )
    event = events[0]
    assert event["conclusion"] == "证据不足"
    assert event["summary"] == "证据不足"


def test_失败运行没有结论时显示归一化失败原因():
    """防止失败记录沿用排队阶段的“未给出结论”占位文案。"""
    events = node_review_timeline(
        [{"id": "R1", "status": "failed", "errorMessage": "TEMPORAL_START_FAILED"}],
        [],
    )
    assert events[0]["summary"] == "编排服务（Temporal）连不上，本次审查没有真正开始执行。"
    assert "未给出结论" not in events[0]["summary"]


def test_失败状态覆盖已播种的建议结论和排队草稿():
    """防止失败运行误把排队时写入的 suggestion/opinionDraft 当成最终结论。"""
    events = node_review_timeline(
        [
            {
                "id": "R1",
                "status": "failed",
                "errorMessage": "TEMPORAL_START_FAILED",
                "suggestion": {"result": "需人工确认"},
                "opinionDraft": "排队中，等待 AI 审查完成。",
            }
        ],
        [],
    )
    event = events[0]
    assert event["conclusion"] == ""
    assert event["summary"] == "编排服务（Temporal）连不上，本次审查没有真正开始执行。"
    assert "排队中" not in event["summary"]


def test_人工未填结论也不留空():
    events = node_review_timeline([], [{"id": "O1", "createdAt": "1"}])
    assert events[0]["summary"] == "（未填写结论）"


def test_时间缺失的排最后():
    """用空串排序会跑到最前，被读成「最早发生的事」——它其实只是没记时间。"""
    events = node_review_timeline(
        [{"id": "NO-TIME", "conclusion": "满足要求"}],
        [{"id": "O1", "createdAt": "2026-08-17 09:00:00", "conclusion": "需补正"}],
    )
    assert [event["refId"] for event in events] == ["O1", "NO-TIME"]


def test_时间字段有多种写法都能取到():
    """finishedAt / updatedAt / createdAt 在不同记录里各有各的写法。"""
    events = node_review_timeline(
        [
            {"id": "A", "createdAt": "2026-08-17 08:00:00"},
            {"id": "B", "updatedAt": "2026-08-17 07:00:00"},
            {"id": "C", "finishedAt": "2026-08-17 06:00:00"},
        ],
        [],
    )
    assert [event["refId"] for event in events] == ["C", "B", "A"]


def test_空输入和脏数据不炸():
    assert node_review_timeline(None, None, None) == []
    assert node_review_timeline([None, "x"], ["y"], [1]) == []
