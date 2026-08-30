"""批量重跑历史积压的知识文件索引（运维工具）。

对账器（reconcile_stuck_index_tasks）只认「待切片/切片中/待向量化/向量化中」
四个中间态，捡不到「未切片/切片失败/向量化失败」——那正是积压的主体。

分类派发（沿用对账器的核心判据：有分块就只补向量化，不重切）：
- 有 chunks 且向量缺口 → dispatch_embed（切片结果是好的，重切等于白跑，
  对标准库更会毁掉条款对齐的分块）
- 无 chunks → dispatch_slice（从头做）
- 无 OCR 解析结果 → 跳过并报告（源头就没识别，切片必然失败，需先解决 OCR）

分流判据（2026-08-29 实测校准）：
- **有 OCR 记录 ≠ 有文本**：扫描件识别出 0 字符时重跑切片必然再次 empty_text，
  纯属烧时间。按实际文本量（≥50 字符）分流，识别失败的单独报告。
- 有分块的只补向量化，不重切（重切会毁掉已对齐的分块）。
- 哈希伪向量（offline-hash-v1）必须重做：数量对得上但没有语义，检索近似随机。

限流：默认每批 20 个，避免一次性把 embedding 配额打满。
文本多的优先——它们的检索价值最高。

## 用法

    docker exec aicheck-api python3 /app/scripts/reprocess_index_backlog.py            # dry-run
    docker exec -e APPLY=1 -e BATCH=50 -e ONLY=slice aicheck-api python3 ...           # 派发
"""
import os
import sys
import time

sys.path.insert(0, "/app")
from libs.db.repository import ensure_collections_loaded, load_state, repo
from libs.integrations import task_dispatcher

APPLY = os.environ.get("APPLY") == "1"
BATCH = int(os.environ.get("BATCH", "20"))
ONLY = os.environ.get("ONLY", "")  # slice / embed / 空=全部

load_state()
ensure_collections_loaded("knowledge_vectors")

# 项目资料（project-file）不再切片/向量化：它们是被审对象，不是检索语料
# （检索已隔离、派发层已拦截）。这里只统计标准库侧的积压。
_project_sources = {
    str(s.get("id"))
    for s in repo.state.get("knowledge_sources", [])
    if isinstance(s, dict) and str(s.get("sourceType") or "") in {"project-file", "project_file"}
}
kfs = [
    f
    for f in repo.state.get("knowledge_files", [])
    if isinstance(f, dict) and str(f.get("sourceId") or "") not in _project_sources
]
parse_by_version = {}
for p in repo.state.get("ocr_parse_results", []):
    if isinstance(p, dict):
        parse_by_version.setdefault(str(p.get("documentVersionId") or ""), []).append(p)

need_slice, need_embed, no_ocr = [], [], []
healthy = 0
for f in kfs:
    slice_status = str(f.get("sliceStatus") or "")
    vector_status = str(f.get("vectorStatus") or "")
    chunks = int(f.get("chunkCount") or 0)
    vectors = int(f.get("vectorCount") or 0)

    # 哈希伪向量：数量对得上但**没有语义**，检索近似随机。必须重做。
    # 它们与真向量同表同维，只有 embeddingModel 能区分。
    if str(f.get("embeddingModel") or "") == "offline-hash-v1" and chunks > 0:
        need_embed.append(f)
        continue

    # 已完整的跳过
    if slice_status == "已切片" and vector_status == "已向量化" and vectors > 0 and vectors >= chunks:
        healthy += 1
        continue

    dvid = str(f.get("documentVersionId") or "")
    parses = parse_by_version.get(dvid) or []

    if chunks > 0 and vectors < chunks:
        need_embed.append(f)          # 有分块、向量缺口 → 只补向量化
    elif chunks == 0:
        # 有 OCR 记录 ≠ 有文本。identify 出 0 字符的（扫描件识别失败）
        # 重跑切片必然再次 empty_text——那是烧时间不解决问题。
        # 按实际文本量分流，并让文本多的排前面。
        text_chars = 0
        for parse in parses:
            for frag in parse.get("fragments") or []:
                if isinstance(frag, dict):
                    text_chars += len(str(frag.get("text") or ""))
            for key in ("fullText", "text", "markdown"):
                text_chars += len(str(parse.get(key) or ""))
        if text_chars >= 50:          # 有实质文本 → 值得切片
            need_slice.append((text_chars, f))
        else:
            no_ocr.append(f)          # 无 OCR 或识别出 0 文本 → 需先修 OCR

print(f"知识文件 {len(kfs)}：健康 {healthy}")
print(f"  需补向量化（有分块、向量缺口）: {len(need_embed)}")
print(f"  需重新切片（有实质文本、无分块）: {len(need_slice)}")
print(f"  无 OCR 文本（识别失败，需先修 OCR）: {len(no_ocr)}")

if no_ocr:
    print("\n无 OCR 结果的文件（前 8 个）:")
    for f in no_ocr[:8]:
        print(f"    {f.get('id')} slice={f.get('sliceStatus')} vector={f.get('vectorStatus')} name={str(f.get('fileName'))[:36]}")

need_slice.sort(key=lambda pair: pair[0], reverse=True)  # 文本多的优先
targets = []
if ONLY in ("", "embed"):
    targets += [("embed", f) for f in need_embed]
if ONLY in ("", "slice"):
    targets += [("slice", f) for _chars, f in need_slice]
targets = targets[:BATCH]

print(f"\n本批将派发 {len(targets)} 个（BATCH={BATCH} ONLY={ONLY or '全部'}）")
if not APPLY:
    for kind, f in targets[:10]:
        print(f"    [{kind}] {f.get('id')} chunks={f.get('chunkCount')} vectors={f.get('vectorCount')} {str(f.get('fileName'))[:30]}")
    print("\n（dry-run。设 APPLY=1 才派发）")
    sys.exit(0)

ok, fail = 0, 0
for kind, f in targets:
    fid = str(f.get("id"))
    try:
        if kind == "embed":
            task_dispatcher.dispatch_embed(fid)
        else:
            task_dispatcher.dispatch_slice(fid)
        ok += 1
    except Exception as exc:  # noqa: BLE001
        fail += 1
        print(f"  ✗ {kind} {fid}: {exc.__class__.__name__}: {exc}")
    time.sleep(0.2)  # 轻微节流，别把队列瞬间灌满
print(f"\n已派发 {ok}，失败 {fail}")
