"""同一次复核的各证据分片要共享一段完全相同的提示词前缀，才能命中前缀缓存。

2026-11-02 生产实测：一次节点复核切 8 片，每片 3.4–5 万 token，规则口径、条款包、检索条款、
规则执行结果、工具清单每片原样重发；10 月节点复核 1801 万输入 token 只命中缓存 4.8 万，
因为每片不同的 nodeFields 紧跟在当前规则后面。
"""
from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

from libs.business_pack import load_business_pack
from libs.review_orchestrator import execution as ex
from libs.review_orchestrator.output_contract import (
    SHARD_VARIANT_PROMPT_KEYS,
    shard_variant_keys_last,
)


def test_variant_keys_move_to_the_end_without_adding_or_dropping_anything() -> None:
    payload = {
        "task": "t",
        "currentRule": {"id": "R16"},
        "nodeFields": [{"name": "牌号"}],
        "requirements": ["a"],
        "fieldCount": 1,
        "groundedOcrEvidence": {"fields": []},
        "ruleResults": [{"ruleId": "R16"}],
        "outputSchema": {},
    }

    reordered = shard_variant_keys_last(payload)

    assert reordered == payload
    assert list(reordered) == [
        "task", "currentRule", "requirements", "ruleResults", "outputSchema",
        "nodeFields", "fieldCount", "groundedOcrEvidence",
    ]
    # 本来没有的键不补
    assert "evidenceLinkIds" not in reordered and "groundingStatus" not in reordered


def _shard_context(base: dict, *, text: str, link_id: str, version_id: str) -> dict:
    """照 shard_execution 的做法：复制整个上下文，只换证据集合和 groundingInput。"""
    context = deepcopy(base)
    link = {"id": link_id, "documentVersionId": version_id, "pageNo": 1,
            "bbox": [1, 2, 30, 40], "quotedText": text}
    field = {"id": f"F-{link_id}", "documentVersionId": version_id, "fieldName": "许可证编号",
             "fieldValue": text, "pageNo": 1, "bbox": [1, 2, 30, 40]}
    context["groundingInput"] = {
        "schemaVersion": "EvidenceGroundedReviewInput@1.0.0",
        "groundingStatus": "grounded",
        "documentVersionIds": [version_id],
        "fields": [field],
        "evidenceLinks": [link],
        "evidenceTextCorpus": [text],
    }
    context["fields"] = [field]
    context["evidenceLinks"] = [link]
    return context


def test_two_shards_of_one_review_share_everything_but_their_evidence(monkeypatch) -> None:
    state = {"ocr_parse_results": []}
    run = {"projectId": "P", "nodeId": 1, "reviewRunId": "RRUN-1",
           "inputDocumentVersionIds": ["DV-1", "DV-2"]}
    monkeypatch.setattr(ex, "repo", SimpleNamespace(state=state, clone=deepcopy))
    monkeypatch.setattr(ex, "select_prompt_template", lambda _: None)
    monkeypatch.setattr(ex, "station_snapshot", lambda _run: {
        "systemPrompt": "你是监检工位。", "stationId": "ST-1", "role": "inspection"})
    monkeypatch.setattr(ex, "scope_catalog", lambda _run, _catalog: ([{"name": "locate_evidence_fragment"}], {}))
    monkeypatch.setattr(ex, "audit_runtime_public_config", lambda **kwargs: {})
    monkeypatch.setattr(ex.checklist_mode, "checklist_enabled", lambda: False)
    base = {
        "project": {"businessPackSnapshot": load_business_pack("engineering_inspection_v1")},
        "auditRuntime": {"mode": "structured"},
        "currentRule": {"id": "RULE-ENG-INSP-R01", "criteria": "设计单位应具备相应许可"},
        "ruleResults": [{"ruleId": "R01", "atomicCheckResults": [
            {"atomicCheckId": "AC-R01-01", "result": "passed"}]}],
        "clausePackageSnapshot": {"packageId": "CLAUSE-PKG-R01", "clauses": [
            {"standardRef": "STD-TSG-31-2025", "clauseNo": "3.1.1"}]},
        "knowledgeClauses": [{"clauseId": "CL-1", "text": "设计单位应当取得许可", "sourceTitle": "TSG 31"}],
    }
    first = _shard_context(base, text="设计许可证TS1844171-2028", link_id="EL-1", version_id="DV-1")
    second = _shard_context(base, text="施工图压力管道级别GC2", link_id="EL-2", version_id="DV-2")

    one = ex.build_review_prompt_parts(run, first)["messages"]
    two = ex.build_review_prompt_parts(run, second)["messages"]

    assert one[0] == two[0]
    payload_one, payload_two = json.loads(one[1]["content"]), json.loads(two[1]["content"])
    variant = [key for key in SHARD_VARIANT_PROMPT_KEYS if key in payload_one]
    assert variant and list(payload_one)[-len(variant):] == variant
    assert list(payload_two)[-len(variant):] == variant
    # 第一个随分片变化的键之前，两片的提示词逐字相同——这一段就是可以命中缓存的前缀
    cut_one = one[1]["content"].index(f'"{variant[0]}"')
    cut_two = two[1]["content"].index(f'"{variant[0]}"')
    assert one[1]["content"][:cut_one] == two[1]["content"][:cut_two]
    shared = one[1]["content"][:cut_one]
    for key in ("currentRule", "ruleResults", "fixedClausePackage", "retrievedClauses",
                "availableRuntimeTools", "requirements", "outputSchema"):
        assert f'"{key}"' in shared, key
    # 证据确实还在各自的分片里，没有被挪丢
    assert "TS1844171-2028" in one[1]["content"] and "TS1844171-2028" not in two[1]["content"]
    assert "GC2" in two[1]["content"] and "GC2" not in one[1]["content"]
