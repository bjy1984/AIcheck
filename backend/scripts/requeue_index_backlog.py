"""把切片/向量化积压重新排队。

## 为什么会有积压

MinerU 路径的 OCR 成功后从不派发切片（见 tasks.py 里 dispatch_slice
那处注释）。修复只对**新上传**生效：存量那些 OCR 已成功、却从没被派过
切片的文件，不推一把就会一直停在「待切片」，报审也就一直被拦。

## 用法

    docker exec aicheck-api python3 /app/scripts/requeue_index_backlog.py [--apply]

只捞「OCR 已成功但切片没完成」的，默认 dry-run —— 带 --apply 才真派。
先看清单再动手：这个脚本会重置派生索引并重新排队，不该误伤正在切片中的。
"""
import os
import sys
sys.path.insert(0, "/app")

from libs.db.repository import load_state, repo, flush_state
from apps.api.routes import dispatch_knowledge_file_index_pipeline

load_state()

# 这个脚本专给**项目资料**补切片（判据就是 projectId 且非 standard）。
# 2026-08-29 起项目资料不再做切片/向量化——它们是被审查的对象，不是检索语料。
# 于是这个脚本的使命结束了：再跑只会把 211 份不该索引的资料派进管线，
# 被 project_file_indexing_blocker 一一拦下，白跑一趟还报出一个吓人的积压数。
#
# 不删除是因为开关还在：真要做项目资料语义搜索时，打开它这个脚本仍然有用。
if str(os.getenv("AICHECK_PROJECT_FILE_INDEXING") or "").strip().lower() not in {
    "1",
    "true",
    "yes",
    "on",
}:
    print(
        "项目资料已不做切片/向量化（2026-08-29 架构调整），本脚本无事可做。\n"
        "标准库的积压请用 scripts/reprocess_index_backlog.py；\n"
        "确要为项目资料建索引，先设 AICHECK_PROJECT_FILE_INDEXING=true。"
    )
    raise SystemExit(0)

OCR_OK = {"已识别", "人工修正", "抽取不完整"}
targets = [
    f for f in repo.state.get("knowledge_files", [])
    # 标准库排除在外：它的分块由专用摄取路径生成，重建管线会把它们清掉
    if f.get("projectId")
    and str(f.get("sourceType")) != "standard"
    and str(f.get("ocrStatus") or "") in OCR_OK
    and str(f.get("sliceStatus") or "") != "已切片"
]
print(f"OCR 已成功但未完成切片：{len(targets)} 份")
for f in targets[:60]:
    print(f"  {f['id']} slice={f.get('sliceStatus')} vector={f.get('vectorStatus')} {str(f.get('fileName'))[:40]}")

if "--apply" not in sys.argv:
    print("\n（dry-run。加 --apply 才真正重新排队）")
    raise SystemExit(0)

ok = err = 0
for f in targets:
    try:
        dispatch_knowledge_file_index_pipeline(f, reason="MinerU 链路缺陷修复后重排切片")
        ok += 1
    except Exception as exc:  # noqa: BLE001
        err += 1
        print(f"  ✗ {f['id']}: {exc.__class__.__name__} {exc}")
flush_state()
print(f"\n重新排队 {ok} 份，失败 {err} 份")
