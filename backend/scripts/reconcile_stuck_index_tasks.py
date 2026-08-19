"""把**卡住的**切片/向量化任务重新排队。

## 为什么必须有

任务链是一环派发下一环的：OCR → 切片 → 向量化（向量化本身还分批续跑）。
部署重启会把正在跑的那一环打断，而**断掉的链没有任何人捡起来**——
资料就停在「待切片」「向量化中」，界面上看不出异常，报审却一直不过。

0819 巡检第一次运行就抓到 3 份：其中一份从 2026-06-25 卡到现在，
两个月无人发现。灰度期间部署会反复发生，这个缺口必须补上。

## 判据

只捡「处于中间态、且长时间没有进展」的：
- 状态是 待切片/切片中/待向量化/向量化中；
- updatedAt 超过阈值（默认 30 分钟）没动。

正在正常处理中的不碰——重复派发会让同一份资料被切两遍。

## 用法

    docker exec aicheck-api python3 /app/scripts/reconcile_stuck_index_tasks.py [--apply] [--minutes 30]
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, "/app")

from libs.db.repository import load_state, repo  # noqa: E402
from libs.integrations import task_dispatcher  # noqa: E402

STUCK_SLICE = {"待切片", "切片中"}
STUCK_VECTOR = {"待向量化", "向量化中"}


def main() -> int:
    minutes = 30
    if "--minutes" in sys.argv:
        minutes = int(sys.argv[sys.argv.index("--minutes") + 1])
    cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")

    load_state()
    stuck = []
    for file in repo.state.get("knowledge_files", []):
        if not isinstance(file, dict):
            continue
        slice_status = str(file.get("sliceStatus") or "")
        vector_status = str(file.get("vectorStatus") or "")
        if slice_status not in STUCK_SLICE and vector_status not in STUCK_VECTOR:
            continue
        if str(file.get("updatedAt") or "")[:19] > cutoff:
            continue  # 还在动，别碰
        stuck.append(file)

    print(f"卡住超过 {minutes} 分钟的：{len(stuck)} 份")
    for file in stuck:
        chunks = int(file.get("chunkCount") or 0)
        action = "重新向量化" if chunks > 0 else "重新切片"
        print(
            f"  {file['id']} slice={file.get('sliceStatus')} vector={file.get('vectorStatus')} "
            f"chunks={chunks} → {action}  {str(file.get('fileName'))[:30]}"
        )

    if "--apply" not in sys.argv:
        print("\n（dry-run。加 --apply 才重新排队）")
        return 0

    ok = 0
    for file in stuck:
        file_id = str(file["id"])
        try:
            # 有分块就只补向量化：切片结果是好的，重切等于白跑一遍，
            # 对标准库更是会**毁掉**条款对齐的分块（见 knowledge_indexing 的护栏）。
            if int(file.get("chunkCount") or 0) > 0:
                task_dispatcher.dispatch_embed(file_id)
            else:
                task_dispatcher.dispatch_slice(file_id)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {file_id}: {exc.__class__.__name__} {exc}")
    print(f"\n已重新排队 {ok}/{len(stuck)} 份")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
