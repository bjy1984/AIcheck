"""向量化幂等必须识别索引版本过期。

只看「已成功 + 已向量化」的话，换了 embedding 模型后旧索引永远更新不了：
2026-08-29 线上 53 个文件带着 offline-hash-v1 的哈希伪向量（没有语义、
检索近似随机），每次重跑都被幂等短路挡回来报 alreadyCompleted，
运维怎么重跑都不生效。
"""

from __future__ import annotations

import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_embed_idempotency_checks_index_version() -> None:
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    # 短路条件必须包含索引版本判断
    body = source.split("def embed_knowledge", 1)[1][:4000]
    assert "stale_index" in body, "幂等短路必须能识别哈希伪向量"
    assert "OFFLINE_EMBEDDING_MODEL" in body, "判据用降级标记，不比对版本字符串"
    assert "and not stale_index" in body, "哈希向量不得走幂等短路"


def test_stale_detection_does_not_compare_index_version_strings() -> None:
    """不能拿 indexVersion 字符串比对：离线目标与在线目标版本天然不同，
    那会把正常流程也判成过期，每次巡检重跑全库。"""
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    body = source.split("def embed_knowledge", 1)[1][:2000]
    assert "recorded_index" not in body


def test_embed_task_loads_batch_records_before_aggregating() -> None:
    """分批续跑跨进程：最终汇总从内存读**全部**批次记录拼向量，
    而续跑任务可能落在从未加载过这张表的 worker 上——那时只能看到自己
    刚写的那批，汇总出 5/21 条就判「数量不匹配」而整份失败
    （2026-08-29 实测 17 份文件如此）。refresh_worker_state 只刷新
    已加载的集合，必须显式确保加载。"""
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    body = source.split("def embed_knowledge", 1)[1][:1500]
    assert "ensure_collections_loaded" in body
    assert "knowledge_embedding_batches" in body


def test_embed_skips_when_a_continuation_chain_is_in_flight() -> None:
    """重复派发（offset=0）会清掉既有批次。若此刻正有续跑链在跑，
    两条链交织：批次记录互相覆盖，汇总只剩最后一批，判「数量不匹配」
    整份失败（2026-08-29 实测：库里出现 offset=0,8,16,32 而 24 缺失）。

    新派发必须让位给正在跑的链——它会自己跑到终点。"""
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    body = source.split("def embed_knowledge", 1)[1][:6000]
    assert "skipped_in_flight" in body, "进行中的续跑链必须被识别并让位"
    assert "in_flight" in body
    # 判据要看断点进度，不能只看任务状态（状态可能停留在旧值）
    assert "embeddingCheckpoint" in body
    assert "nextOffset" in body
