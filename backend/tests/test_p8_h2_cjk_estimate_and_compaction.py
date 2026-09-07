"""P8 H2：分片估算中文感知 + 分片层无损压缩。

2026-09-06 审计：目标 12,000"估算 token"的分片计费 5.5 万 token（估算按 len/4，中文一字一 token）；
节点 2 一次审查 9 片 52 万 token。这里钉三件事：估算对中文诚实、切分可原样拼回、
压缩只去重复副本与空值。
"""

from __future__ import annotations

from libs.model_usage import estimate_text_tokens
from libs.review_evidence import (
    _collapse_empty_fragments,
    _split_text_by_tokens,
    build_evidence_manifest,
    build_evidence_shards,
    compact_artifact_payload,
)


def test_cjk_text_counts_one_token_per_character() -> None:
    assert estimate_text_tokens("焊工证有效期至") == 7
    assert estimate_text_tokens("abcdefgh") == 2
    assert estimate_text_tokens("焊工 TS1234") == 2 + 2  # 两个汉字 + " TS1234" 7 字符 → 2
    assert estimate_text_tokens("") == 0


def test_text_split_by_tokens_is_reconstructable_and_respects_budget() -> None:
    text = "设计许可证许可范围GC1覆盖GC2。" * 300
    ranges = _split_text_by_tokens(text, 100)
    assert "".join(text[start:end] for start, end in ranges) == text
    assert len(ranges) >= 30
    for start, end in ranges:
        assert estimate_text_tokens(text[start:end]) <= 100


def test_cjk_heavy_manifest_now_splits_into_honest_shards() -> None:
    text = "焊接工艺评定报告覆盖本工程焊接工艺规程。" * 300  # 约 6,000 个汉字 ≈ 6,000 token
    manifest = {
        "evidenceManifestId": "EMAN-1",
        "evidenceSnapshotId": "ESNAP-1",
        "projectId": "P-1",
        "nodeId": 2,
        "artifacts": [
            {
                "artifactId": "EART-1",
                "artifactType": "fragment",
                "documentVersionId": "DV-1",
                "sourceId": "FRAG-1",
                "payload": {"pageNo": 1, "text": text},
                "contentHash": "sha256:1",
            }
        ],
    }
    shards = build_evidence_shards(manifest, max_shard_estimated_tokens=1500)
    # len/4 时代：6,000 汉字 ≈ 1,500 "token" → 1 片；中文感知后至少 4 片
    assert len(shards) >= 4
    for shard in shards:
        assert shard["estimatedTokens"] <= 1500 + 50


def test_table_payload_drops_alias_copies_html_and_null_cells_losslessly() -> None:
    rows = [{"焊工": "姜军", "项目": "GTAW-FeⅡ-6G", "备注": None}]
    cells = [{"rowIndex": 0, "columnIndex": 0, "text": "姜军", "bbox": None, "confidence": None}]
    payload = {
        "tableId": "T1",
        "pageNo": 1,
        "html": "<table><tr><td>姜军</td></tr></table>",
        "rows": rows,
        "normalizedRows": rows,
        "cells": cells,
        "cellsSummary": cells,
    }
    compact = compact_artifact_payload("table", payload)
    assert "html" not in compact
    assert "normalizedRows" not in compact and "cellsSummary" not in compact
    assert compact["rows"] == [{"焊工": "姜军", "项目": "GTAW-FeⅡ-6G"}]
    assert compact["cells"] == [{"rowIndex": 0, "columnIndex": 0, "text": "姜军"}]
    # 原对象不被改动
    assert "html" in payload and payload["cells"][0]["bbox"] is None
    # 别名不相等时不能当重复删掉
    different = compact_artifact_payload("table", {"rows": rows, "normalizedRows": [{"焊工": "李卫伍"}]})
    assert "normalizedRows" in different


def test_fragment_payload_drops_duplicate_table_html_and_nulls() -> None:
    compact = compact_artifact_payload(
        "fragment",
        {"pageNo": 1, "text": "焊工 姜军", "tableHtml": "<table/>", "bbox": None, "blockType": "table"},
    )
    assert compact == {"pageNo": 1, "text": "焊工 姜军", "blockType": "table"}
    # 没有文本时 tableHtml 是唯一内容，保留
    kept = compact_artifact_payload("fragment", {"pageNo": 1, "text": "", "tableHtml": "<table/>"})
    assert kept["tableHtml"] == "<table/>"


def test_empty_fragments_collapse_per_page_but_text_fragments_stay() -> None:
    rows = [
        {"fragmentId": "F1", "pageNo": 1, "text": "焊工证"},
        {"fragmentId": "F2", "pageNo": 2, "text": ""},
        {"fragmentId": "F3", "pageNo": 2, "text": "   "},
        {"fragmentId": "F4", "pageNo": 3, "text": ""},
    ]
    collapsed = _collapse_empty_fragments(rows, "PR-1")
    assert [row["fragmentId"] for row in collapsed] == ["F1", "PR-1:page-2:no-text", "PR-1:page-3:no-text"]
    assert collapsed[1]["collapsedFragmentCount"] == 2
    assert collapsed[1]["ocrTextUnavailable"] is True


def test_manifest_applies_compaction_to_parse_results() -> None:
    rows = [{"焊工": "姜军"}]
    state = {
        "ocr_parse_results": [
            {
                "parseResultId": "PR-1",
                "documentVersionId": "DV-1",
                "finishedAt": "2026-09-06T00:00:00Z",
                "tables": [{"tableId": "T1", "pageNo": 1, "html": "<table/>", "rows": rows, "normalizedRows": rows, "cells": []}],
                "fragments": [
                    {"fragmentId": "F1", "pageNo": 1, "text": "焊工证", "tableHtml": "<table/>", "bbox": None},
                    {"fragmentId": "F2", "pageNo": 1, "text": ""},
                    {"fragmentId": "F3", "pageNo": 1, "text": ""},
                ],
                "seals": [],
            }
        ],
        "extracted_fields": [],
        "evidence_links": [],
    }
    manifest = build_evidence_manifest(
        state,
        {"evidenceSnapshotId": "ESNAP-1", "snapshotHash": "sha256:x", "projectId": "P-1", "nodeId": 2, "documentVersions": [{"documentVersionId": "DV-1"}]},
    )
    by_type = {}
    for artifact in manifest["artifacts"]:
        by_type.setdefault(artifact["artifactType"], []).append(artifact["payload"])
    assert "html" not in by_type["table"][0] and "normalizedRows" not in by_type["table"][0]
    assert len(by_type["fragment"]) == 2  # 一条有文本 + 一条合并的空碎片
    assert "tableHtml" not in by_type["fragment"][0] and "bbox" not in by_type["fragment"][0]
    assert by_type["fragment"][1]["collapsedFragmentCount"] == 2
