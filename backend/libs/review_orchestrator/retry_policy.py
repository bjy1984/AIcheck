"""失败之后谁来重试（issue #12 R-8 旁支）。

查 R-8 时发现的活 bug：retryable 的失败会把运行标成 retry_pending，而这个状态
的唯一消费方是 Temporal 的审查 worker（apps/review_worker/activities.py）。
线上跑的是 inline 编排、根本没起那个 worker——于是运行永远停在那儿，界面显示
「等待重试」，等的却是一个不存在的人。

这比 R-8 本身更要紧：重试重跑整图是成本翻倍，看得见；永远等待看不见。

两件事要分开：
  失败的性质（瞬时/永久）是事实，与部署无关；
  有没有人来重试是部署状态。
混在一起会让人以为超时变成了不可恢复的错误。
"""

from __future__ import annotations

import os


def has_review_retry_consumer() -> bool:
    """当前部署里有没有东西会真的来重试 retry_pending 的运行。

    只有 Temporal 编排下才有。inline / legacy 下标成 retry_pending，
    就是给出一个永远不会兑现的承诺。
    """
    return os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower() == "temporal"
