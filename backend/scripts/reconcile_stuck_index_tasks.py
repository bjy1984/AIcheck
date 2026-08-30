"""把**卡住的**切片/向量化任务重新排队。

## 为什么必须有

任务链是一环派发下一环的：OCR → 切片 → 向量化（向量化本身还分批续跑）。
部署重启会把正在跑的那一环打断，而**断掉的链没有任何人捡起来**——
资料就停在「待切片」「向量化中」，界面上看不出异常，报审却一直不过。

0819 巡检第一次运行就抓到 3 份：其中一份从 2026-06-25 卡到现在，
两个月无人发现。灰度期间部署会反复发生，这个缺口必须补上。

## 判据

只捡「处于中间态、且长时间没有进展」的：
- **只看标准库**：项目资料不做切片/向量化，它们身上的「待切片」是历史残留；
- 状态是 待切片/切片中/待向量化/向量化中；
- **OCR 停在「排队中」而 ocr_job 仍是 queued**（2026-08-30 补：这一段此前
  完全没人管。测试项目3 批量传 41 份，35 份因为增量刷新漏行永久卡在这里，
  没有任何收敛器会捡起来）；
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
    # 项目资料（施工方上传的审计材料）**不做切片/向量化**——它们是被审查的对象，
    # 不是检索语料（2026-08-29 架构调整）。它们身上残留的「待切片/待向量化」
    # 是那次调整之前留下的历史状态，不代表任何待办。
    #
    # 不排除的后果不是派错任务（派发层会拦），而是**每小时报一次「卡住 52 份」**：
    # 运维以为有积压，真正该关注的标准库积压反而淹没在噪音里。
    project_sources = {
        str(source.get("id"))
        for source in repo.state.get("knowledge_sources", [])
        if isinstance(source, dict)
        and str(source.get("sourceType") or "") in {"project-file", "project_file"}
    }
    stuck = []
    for file in repo.state.get("knowledge_files", []):
        if not isinstance(file, dict):
            continue
        if str(file.get("sourceId") or "") in project_sources:
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

    reconcile_stuck_ocr_jobs(minutes, apply=True)
    return 0


def reconcile_stuck_ocr_jobs(minutes: int, *, apply: bool) -> int:
    """OCR 停在「排队中」、job 仍是 queued 且长时间没动的，重新派发。

    这一段此前没有任何收敛器。2026-08-30 测试项目3 批量传 41 份，35 份因为
    增量刷新漏行（worker 读不到刚建的 job）永久卡在「排队中」——修好漏行之后，
    存量仍需要有人捡起来，否则就得靠人手工发现。

    **必须用 retry=True**：确定性 task_id 会让重派被 celery 当成重复投递
    静默丢弃（实测派 17 个只有 6 个真的被接收）。
    """
    from libs.contracts.responses import SERVER_TZ

    now = datetime.now(SERVER_TZ)
    threshold = now - timedelta(minutes=minutes)
    jobs_by_version: dict[str, list[dict]] = {}
    for job in repo.state.get("ocr_jobs", []):
        if isinstance(job, dict):
            jobs_by_version.setdefault(str(job.get("documentVersionId") or ""), []).append(job)

    stuck: list[tuple[str, str]] = []
    for document in repo.state.get("documents", []):
        if not isinstance(document, dict):
            continue
        if str(document.get("currentOcrStatus") or "") != "排队中":
            continue
        jobs = jobs_by_version.get(str(document.get("currentVersionId") or "")) or []
        if not jobs or str(jobs[-1].get("status") or "") != "queued":
            continue
        try:
            moved = datetime.fromisoformat(str(document.get("updatedAt") or "")[:19])
        except ValueError:
            continue
        if moved.replace(tzinfo=SERVER_TZ) > threshold:
            continue  # 还在动，别碰
        stuck.append((str(jobs[-1]["id"]), str(document.get("fileName") or "")[:30]))

    print(f"\nOCR 卡在「排队中」超过 {minutes} 分钟的：{len(stuck)} 份")
    for job_id, name in stuck[:10]:
        print(f"  {job_id}  {name}")
    if not apply or not stuck:
        return 0
    ok = 0
    for job_id, _name in stuck:
        try:
            if task_dispatcher.dispatch_mineru_ocr(job_id, retry=True).get("taskId"):
                ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {job_id}: {exc.__class__.__name__} {exc}")
    print(f"已重新派发 OCR {ok}/{len(stuck)} 份")
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
