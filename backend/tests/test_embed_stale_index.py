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
