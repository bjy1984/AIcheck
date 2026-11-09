"""「AI审查」对话的存量整理：压缩已落定回答的流式增量、归档闲置超期的会话（F 项，2026-11-09）。

规则在 apps/api/review_session_retention.py，新数据由 API 自己处理；这个脚本只管上线前的存量。

    docker exec aicheck-api python3 /app/scripts/review_session_retention.py
    docker exec aicheck-api python3 /app/scripts/review_session_retention.py --apply --backup-dir /app/output/ops/review-session-retention

- 不加 --apply 是只预览：报每个院要压几条增量、省多少字，要归档哪几本会话。
- --apply 必须给 --backup-dir：先把要改的每一行原样写进备份文件（JSONL，0600），再改、再只落这几行。
  回滚：按备份文件里的整行写回（review_session_events / review_sessions 两个集合）。
- 只载入 review_sessions / review_messages / review_session_events 三个集合，逐院跑，不整库 load_state。
- 整点、半点前后 3 分钟不跑（那时宿主机 cron 在整库载入，2026-10-27 API 就是这么被 OOM 杀的），
  非要跑加 --force-window。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

KEYS = {"review_sessions", "review_messages", "review_session_events"}


def in_cron_window(now: datetime) -> bool:
    return now.minute in {57, 58, 59, 0, 1, 2, 3, 27, 28, 29, 30, 31, 32, 33}


def plan_for_current_tenant(tenant_id: str) -> dict[str, Any]:
    from apps.api import review_session_retention as retention
    from libs.db.repository import repo

    compact: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    kept = {"archiveIncomplete": 0, "answerNotCompleted": 0, "earlierTurnText": 0}
    for message in repo.state.get("review_messages", []):
        if message.get("role") != "assistant":
            continue
        events = retention.stream_deltas_with_content(message)
        if not events:
            continue
        if retention.answer_archive_complete(message):
            compactable = retention.compactable_stream_deltas(message)
            kept["earlierTurnText"] += len(events) - len(compactable)  # 前几轮的正文：别处没有
            if compactable:
                compact.append((message, compactable))
        elif str(message.get("status") or "") == "completed":
            kept["archiveIncomplete"] += len(events)  # 存档被截过：增量是唯一的全量记录
        else:
            kept["answerNotCompleted"] += len(events)  # 失败、停止、还在跑：留着查问题
    idle = [session for session in repo.state.get("review_sessions", []) if retention.session_idle_expired(session)]
    return {"tenantId": tenant_id, "compact": compact, "kept": kept, "idle": idle}


def summarize(plan: dict[str, Any]) -> dict[str, Any]:
    from apps.api import review_session_retention as retention

    events = [event for _, items in plan["compact"] for event in items]
    return {
        "tenantId": plan["tenantId"],
        "answersToCompact": len(plan["compact"]),
        "deltaEventsToCompact": len(events),
        "charsRemoved": sum(len(str(event["payload"].get("content") or "")) for event in events),
        "deltaEventsKept": plan["kept"],
        "idleSessionsToArchive": [
            {
                "sessionId": session.get("id"),
                "createdBy": session.get("createdBy"),
                "projectId": session.get("projectId"),
                "nodeId": session.get("nodeId"),
                "lastActivity": str(retention.session_last_activity(session) or ""),
            }
            for session in plan["idle"]
        ],
        "archiveAfterMonths": retention.ARCHIVE_AFTER_MONTHS,
    }


def write_backup(backup_dir: Path, plan: dict[str, Any]) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    from libs.contracts.responses import SERVER_TZ

    stamp = datetime.now(SERVER_TZ).strftime("%Y%m%dT%H%M%S")
    path = backup_dir / f"review-session-retention-{plan['tenantId']}-{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for _, events in plan["compact"]:
            for event in events:
                handle.write(json.dumps({"collection": "review_session_events", "row": event}, ensure_ascii=False) + "\n")
        for session in plan["idle"]:
            handle.write(json.dumps({"collection": "review_sessions", "row": session}, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)
    return path


def apply_plan(plan: dict[str, Any]) -> dict[str, int]:
    from apps.api import review_session_retention as retention
    from libs.db.repository import flush_state_records

    compacted: list[dict[str, Any]] = []
    for message, _ in plan["compact"]:
        compacted.extend(retention.compact_stream_deltas(message))
    for session in plan["idle"]:
        retention.mark_archived(session, reason="idle", actor="system:retention-script")
    # 事件行没有 tenantId 字段，落库时会被补成部署默认院；先按载入它的院补上，别写串院
    for row in [*compacted, *plan["idle"]]:
        row.setdefault("tenantId", plan["tenantId"])
    records = {
        key: rows
        for key, rows in (("review_session_events", compacted), ("review_sessions", plan["idle"]))
        if rows
    }
    if records:
        flush_state_records(records)
    return {"eventsCompacted": len(compacted), "sessionsArchived": len(plan["idle"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="真的改库（默认只预览）")
    parser.add_argument("--backup-dir", type=Path, help="--apply 时必填：改之前把原行备份到这里")
    parser.add_argument("--tenant", action="append", help="只跑这几个院（可重复）；默认库里有数据的全部院")
    parser.add_argument("--force-window", action="store_true", help="整点/半点前后也跑")
    args = parser.parse_args()

    from libs.contracts.responses import SERVER_TZ
    from libs.db.repository import load_state, repo
    from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id

    if args.apply and not args.backup_dir:
        print("--apply 必须同时给 --backup-dir", file=sys.stderr)
        return 2
    if in_cron_window(datetime.now(SERVER_TZ)) and not args.force_window:
        print("整点/半点前后 3 分钟不跑（宿主机 cron 在整库载入）；稍后再跑，或加 --force-window", file=sys.stderr)
        return 3

    report = []
    for tenant_id in args.tenant or repo.persisted_tenant_ids():
        token = set_request_tenant_id(tenant_id)
        try:
            load_state(KEYS, tenant_id=tenant_id)
            plan = plan_for_current_tenant(tenant_id)
            summary = summarize(plan)
            if args.apply and (plan["compact"] or plan["idle"]):
                summary["backup"] = str(write_backup(args.backup_dir, plan))
                summary["applied"] = apply_plan(plan)
            report.append(summary)
        finally:
            reset_request_tenant_id(token)
    print(json.dumps({"apply": args.apply, "tenants": report}, ensure_ascii=False, indent=2, default=str))
    if not args.apply:
        print("（只预览。加 --apply --backup-dir … 才改库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
