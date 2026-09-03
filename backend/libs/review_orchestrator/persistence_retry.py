"""审查运行收尾落库的并发冲突重试。

worker 起任务时加载了 ai_run，API 进程在派发返回后又回填了同一行（reviewRunId/
workflowId），worker 跑完收尾整批 flush 时 ai_runs 的 baseline 对不上，事务回滚——
库里的运行永远 queued，而报错的是 ai_runs、丢的是 review_runs（2026-09-03 实测）。

重试的做法：把本次执行改过的对象按 id 留一份，解钉后只增量重载这几个集合
（拿到库里的新 baseline），再把执行结果的字段覆盖回新载入的对象上，重新 flush。
并发方写的字段（workflowId 之类）只在本次没写时保留库里的值。
"""

from __future__ import annotations

import logging
from typing import Any

from libs.db.repository import (
    STATE_COLLECTIONS,
    ConcurrentPersistenceError,
    flush_state_records,
    postgres_persistence_configured,
    repo,
)

from ._shared import REVIEW_STATE_COLLECTIONS

# 其它记录（事件、草稿、trace）都是本次运行新建的，不会被别的进程改。
_CONFLICT_RETRY_COLLECTIONS = ("ai_runs", "review_runs", "tree_nodes")


def flush_review_run_records_with_conflict_retry(
    review_run_id: str,
    records: dict[str, list[dict[str, Any]]],
    *,
    attempts: int = 2,
    inflight_runs: dict[str, dict[str, Any]] | None = None,
) -> None:
    """落库；撞上 ConcurrentPersistenceError 时重载冲突集合、合并本次结果后重试。"""
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            flush_state_records(records)
            return
        except ConcurrentPersistenceError as exc:
            last_error = exc
            if attempt + 1 >= attempts or not postgres_persistence_configured():
                raise
            logging.getLogger(__name__).warning(
                "ReviewRun %s 落库撞上并发修改，重载冲突集合后重试：%s", review_run_id, exc
            )
            _reload_and_merge_conflicting_records(review_run_id, records, inflight_runs)
    if last_error is not None:
        raise last_error


def _reload_and_merge_conflicting_records(
    review_run_id: str,
    records: dict[str, list[dict[str, Any]]],
    inflight_runs: dict[str, dict[str, Any]] | None,
) -> None:
    stale_by_key: dict[str, dict[str, dict[str, Any]]] = {}
    for state_key in _CONFLICT_RETRY_COLLECTIONS:
        rows = [row for row in records.get(state_key) or [] if isinstance(row, dict)]
        if not rows:
            continue
        collection_name = STATE_COLLECTIONS.get(state_key, state_key)
        stale_by_key[state_key] = {}
        for index, row in enumerate(rows):
            object_id = repo.persistence_object_id(collection_name, row, index)
            stale_by_key[state_key][object_id] = dict(row)
            repo.unpin_object(collection_name, object_id)
    if not stale_by_key:
        return
    repo.refresh_collections_incrementally(set(stale_by_key))
    for state_key, stale_rows in stale_by_key.items():
        collection_name = STATE_COLLECTIONS.get(state_key, state_key)
        fresh_rows = repo.state.setdefault(state_key, [])
        merged: list[dict[str, Any]] = []
        for object_id, stale in stale_rows.items():
            fresh = next(
                (
                    row
                    for index, row in enumerate(fresh_rows)
                    if isinstance(row, dict)
                    and repo.persistence_object_id(collection_name, row, index) == object_id
                ),
                None,
            )
            if fresh is None:
                fresh = stale
                fresh_rows.insert(0, fresh)
            else:
                for field, value in stale.items():
                    if field == "workflowId" and not value:
                        continue
                    fresh[field] = value
            merged.append(fresh)
            if state_key == "review_runs" and object_id == review_run_id and inflight_runs is not None:
                inflight_runs[review_run_id] = fresh
        records[state_key] = merged


def review_run_state_records(review_run_id: str) -> dict[str, list[dict[str, Any]]]:
    review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one(
        "review_runs", review_run_id
    )
    if not review_run:
        return {}
    ai_run_id = str(review_run.get("aiRunId") or "")
    project_id = str(review_run.get("projectId") or "")
    node_id = int(review_run.get("nodeId") or 0)
    records: dict[str, list[dict[str, Any]]] = {"review_runs": [review_run]}
    for collection in REVIEW_STATE_COLLECTIONS:
        if collection == "review_runs":
            continue
        records[collection] = [
            item
            for item in repo.state.get(collection, [])
            if str(item.get("reviewRunId") or "") == review_run_id
        ]
    records["ai_runs"] = [
        item for item in repo.state.get("ai_runs", []) if ai_run_id and str(item.get("id") or "") == ai_run_id
    ]
    records["ai_trace_steps"] = [
        item
        for item in repo.state.get("ai_trace_steps", [])
        if ai_run_id and str(item.get("aiRunId") or "") == ai_run_id
    ]
    records["review_findings"] = [
        item
        for item in repo.state.get("review_findings", [])
        if str(item.get("reviewRunId") or "") == review_run_id
    ]
    records["tree_nodes"] = [
        item
        for item in repo.state.get("tree_nodes", [])
        if str(item.get("projectId") or "") == project_id and int(item.get("nodeId") or 0) == node_id
    ]
    return records
