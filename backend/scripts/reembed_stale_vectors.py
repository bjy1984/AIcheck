"""把非当前索引版本的向量重建一遍。

## 为什么需要

线上索引是混的（0818 实测 120 份已向量化里）：
- 60 份 knowledge-index-qwen3-0.6b@1024（本地 Infinity 服务，早已不在生产）
- **51 份 knowledge-index-offline-hash-v1@1024**——哈希伪向量，没有语义，
  检索结果近似随机。它们和真向量同表同维存放，看状态是「已向量化」，
  用起来却在污染每一次召回。这比缺向量更危险：缺了会被发现，
  假的不会。
- 9 份没有记录模型

切到 Qwen 官方 text-embedding-v4 之后当前索引是
knowledge-index-text-embedding-v4@1024，上面三类全都对不上。
向量空间不同的向量放在一起比较距离，等于把尺子换了还继续读数。

## 用法

    docker exec aicheck-api python3 /app/scripts/reembed_stale_vectors.py [--apply] [--only-hash]

默认 dry-run。--only-hash 只重建伪向量那批（最该先清的）。
重建走正常的切片/向量化链路，不直接改向量表。
"""

from __future__ import annotations

import sys
from collections import Counter

sys.path.insert(0, "/app")

from apps.api.routes import dispatch_knowledge_file_index_pipeline  # noqa: E402
from libs.db.repository import flush_state, load_state, repo  # noqa: E402
from libs.integrations.embedding_client import EmbeddingClient  # noqa: E402

load_state()
client = EmbeddingClient()
current_index = client.index_version
if not client.enabled:
    raise SystemExit("当前没有可用的 embedding 服务——先把配置修好再重建，否则只是把状态推回待向量化")

only_hash = "--only-hash" in sys.argv
files = [f for f in repo.state.get("knowledge_files", []) if f.get("projectId")]
vectorized = [f for f in files if f.get("vectorStatus") == "已向量化"]

print(f"当前索引版本：{current_index}")
print("现存分布：", dict(Counter(str(f.get("indexVersion") or "(无)") for f in vectorized)))

stale = [f for f in vectorized if str(f.get("indexVersion") or "") != current_index]
if only_hash:
    stale = [f for f in stale if "offline-hash" in str(f.get("indexVersion") or "")]
print(f"\n需要重建：{len(stale)} 份" + ("（只算伪向量）" if only_hash else ""))

if "--apply" not in sys.argv:
    for f in stale[:15]:
        print(f"  {f['id']} {str(f.get('indexVersion') or '(无)')} {str(f.get('fileName'))[:36]}")
    print("\n（dry-run。加 --apply 才真正重建）")
    raise SystemExit(0)

ok = err = 0
for f in stale:
    try:
        dispatch_knowledge_file_index_pipeline(f, reason=f"索引版本迁移到 {current_index}")
        ok += 1
    except Exception as exc:  # noqa: BLE001
        err += 1
        print(f"  ✗ {f['id']}: {exc.__class__.__name__} {exc}")
flush_state()
print(f"\n已排队重建 {ok} 份，失败 {err} 份")
