"""资料指纹不依赖内存列表的先后：同一资料版本有两条解析结果时，接口进程（新行插在最前）和
worker 进程（整表加载按 object_id 排）算出同一个指纹；旧算法冻结的指纹仍被认得。"""
import pytest

from libs.review_document_scope import (
    document_source_fingerprint,
    freeze_document_scope,
    validate_document_sources,
)

OLD = {"id": "PARSE-52D6", "documentVersionId": "DV-A", "createdAt": "2026-08-30 23:57:41", "text": "旧"}
NEW = {"id": "PARSE-FBA9", "documentVersionId": "DV-A", "createdAt": "2026-10-30 12:20:11", "text": "新"}
OTHER = {"id": "PARSE-89DF", "documentVersionId": "DV-B", "createdAt": "2026-08-30 23:36:23", "text": "别的"}
RUN = {"projectId": "P-1", "nodeId": 4, "businessPackId": "pack", "inputDocumentVersionIds": ["DV-A", "DV-B"]}


def state_of(*rows):
    return {"ocr_parse_results": list(rows), "fact_corrections": []}


def test_fingerprint_is_the_same_in_every_list_order():
    api_order = state_of(NEW, OLD, OTHER)       # 增量刷新：新行插在最前
    worker_order = state_of(OLD, OTHER, NEW)    # 整表加载：按 object_id
    assert document_source_fingerprint(RUN, api_order) == document_source_fingerprint(RUN, worker_order)


def test_run_frozen_in_one_order_validates_in_another():
    run = dict(RUN)
    run["documentScopeSnapshot"] = freeze_document_scope(run, state_of(NEW, OLD, OTHER))
    validate_document_sources(run, state_of(OLD, OTHER, NEW))


def test_a_changed_parse_still_invalidates_the_run():
    run = dict(RUN)
    run["documentScopeSnapshot"] = freeze_document_scope(run, state_of(NEW, OLD, OTHER))
    with pytest.raises(ValueError, match="review_document_sources_changed_recreate_run"):
        validate_document_sources(run, state_of(OLD, OTHER, {**NEW, "text": "改过"}))
    with pytest.raises(ValueError, match="review_document_sources_changed_recreate_run"):
        validate_document_sources(run, state_of(OLD, OTHER))


def test_fingerprint_frozen_by_the_old_list_order_algorithm_is_still_accepted():
    state = state_of(NEW, OLD, OTHER)
    run = dict(RUN)
    snapshot = freeze_document_scope(run, state)
    snapshot["sourceFingerprint"] = document_source_fingerprint(run, state, list_order=True)
    snapshot.pop("snapshotHash")
    from libs.review_rule_snapshot import _hash
    snapshot["snapshotHash"] = _hash(snapshot)
    run["documentScopeSnapshot"] = snapshot
    validate_document_sources(run, state)
