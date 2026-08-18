"""落库主键必须是稳定身份，不能是列表下标。

## 这条 bug 长什么样

persistence_object_id 找不到已知 id 字段时会退化成**列表下标**。而
submissions 是 insert(0, …) 插到头部的：新来一条，其余记录的主键整体
位移一格，所有 baseline 同时失效。

更糟的是进程数：api 和 4 个 worker 各自持有一份 state、各自 flush。
列表顺序一旦分叉，它们就开始互相覆盖对方的行，而且**再也协调不回来**——
这不是偶发竞态，是永久性的。

0818 线上实测：62 条 submissions 里 60 条按下标落库，
embed_knowledge 反复抛 `submissions/2` 冲突，新 API 容器连启动都过不去。
排查时最误导人的一点是：**报错指向 submissions，被卡死的却是向量化和整个进程**。

## 判据

不是「submissions 有主键了」，而是「没有任何集合退化到下标」——
下一个用 xxxId 命名主键的集合会掉进同一个坑，而它同样不会报错。
"""

from __future__ import annotations

from libs.db.repository import STATE_COLLECTIONS, InMemoryRepository, repo


def test_已知的按下标落库集合已经有稳定主键() -> None:
    """三个线上实测中招的集合。"""
    repository = InMemoryRepository()
    cases = [
        ("submissions", {"submissionId": "SUB-1"}, "SUB-1"),
        ("llm_compare_runs", {"runId": "RUN-1"}, "RUN-1"),
        ("ocr_annotation_tasks", {"taskId": "TASK-1"}, "TASK-1"),
    ]
    for collection, doc, expected in cases:
        assert repository.persistence_object_id(collection, doc, 7) == expected, (
            f"{collection} 还在按下标落库——插一条就会让其余记录主键整体位移"
        )


def test_下标只在真的没有任何身份字段时才用() -> None:
    repository = InMemoryRepository()
    assert repository.persistence_object_id("whatever", {"name": "无主键"}, 3) == "3"


def test_种子数据里没有任何记录靠下标当身份() -> None:
    """比逐个集合断言更管用：新集合掉进同一个坑时这条会红。

    用当前进程已加载的 state（含种子/演示数据）扫一遍——
    真实形状比构造的样例更能暴露命名不一致的集合。
    """
    positional: list[str] = []
    for state_key, collection_name in STATE_COLLECTIONS.items():
        for index, doc in enumerate(repo.state.get(state_key) or []):
            if not isinstance(doc, dict):
                continue
            if repo.persistence_object_id(collection_name, doc, index) == str(index):
                id_like = [key for key in doc if key.lower().endswith("id")][:4]
                positional.append(f"{state_key}[{index}] 候选字段={id_like}")
                break
    assert not positional, (
        "这些集合按下标落库，任何插入都会让其余记录主键整体位移：\n  "
        + "\n  ".join(positional)
        + "\n把它们的主键字段加进 InMemoryRepository.PERSISTENCE_ID_FIELDS"
    )
