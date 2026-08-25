from __future__ import annotations

import json

from libs.review_grounding import build_grounded_review_input
from libs.review_orchestrator.execution import normalize_llm_findings


def _grounding_state(
    *,
    field_count: int = 0,
    table_count: int = 0,
    seal_count: int = 0,
    fragment_count: int = 0,
    evidence_link_count: int = 0,
) -> dict:
    version_id = "DV-FULL-1"
    return {
        "extracted_fields": [
            {
                "id": f"FIELD-{index:03d}",
                "documentVersionId": version_id,
                "fieldName": f"字段-{index}",
                "fieldValue": f"值-{index}",
                "pageNo": 1,
                "bbox": [1, 2, 30, 40],
                "confidence": 0.99,
            }
            for index in range(1, field_count + 1)
        ],
        "ocr_parse_results": [
            {
                "id": "OCR-FULL-1",
                "parseResultId": "OCR-FULL-1",
                "documentVersionId": version_id,
                "status": "success",
                "tables": [
                    {
                        "id": f"TABLE-{index:03d}",
                        "pageNo": index,
                        "rows": [{"column": f"row-{index}"}],
                        "cells": [
                            {"rowIndex": 0, "columnIndex": 0, "text": f"cell-{index}"}
                        ],
                    }
                    for index in range(1, table_count + 1)
                ],
                "seals": [
                    {
                        "id": f"SEAL-{index:03d}",
                        "pageNo": index,
                        "text": f"seal-{index}",
                        "bbox": [1, 2, 30, 40],
                        "ocrConfidence": 0.99,
                    }
                    for index in range(1, seal_count + 1)
                ],
                "fragments": [
                    {
                        "id": f"FRAGMENT-{index:03d}",
                        "pageNo": index,
                        "text": f"fragment-{index}",
                        "bbox": [1, 2, 30, 40],
                        "confidence": 0.99,
                    }
                    for index in range(1, fragment_count + 1)
                ],
            }
        ],
        "evidence_links": [
            {
                "id": f"EV-{index:03d}",
                "documentVersionId": version_id,
                "quotedText": f"evidence-link-{index}",
                "pageNo": index,
                "bbox": [1, 2, 30, 40],
                "confidence": 0.99,
            }
            for index in range(1, evidence_link_count + 1)
        ],
    }


def test_grounding_keeps_every_item_beyond_all_legacy_collection_caps() -> None:
    state = _grounding_state(
        field_count=95,
        table_count=24,
        seal_count=23,
        fragment_count=130,
        evidence_link_count=90,
    )

    grounded = build_grounded_review_input(state, {"DV-FULL-1"})

    assert len(grounded["fields"]) == 95
    assert len(grounded["tables"]) == 24
    assert len(grounded["seals"]) == 23
    assert len(grounded["fragments"]) == 130
    assert len(grounded["evidenceLinks"]) == 90


def test_grounding_preserves_full_table_markdown_rows_cells_keys_and_values() -> None:
    state = _grounding_state(table_count=1)
    long_key = "字段名" * 40
    long_value = "许可证许可范围" * 80
    markdown = "M" * 9000
    rows = [{long_key: long_value}, *({"row": index} for index in range(1, 75))]
    cells = [
        {"rowIndex": index // 5, "columnIndex": index % 5, "text": f"cell-{index}-" + "X" * 240}
        for index in range(205)
    ]
    table = state["ocr_parse_results"][0]["tables"][0]
    table.update({"contentMarkdown": markdown, "rows": rows, "cells": cells})

    grounded = build_grounded_review_input(state, {"DV-FULL-1"})
    result = grounded["tables"][0]

    assert result["contentMarkdown"] == markdown
    assert len(result["rows"]) == 75
    assert len(result["cells"]) == 205
    assert list(result["rows"][0]) == [long_key]
    assert result["rows"][0][long_key] == long_value
    assert result["cells"][-1]["text"] == cells[-1]["text"]


def test_grounding_evidence_text_corpus_does_not_truncate_long_source_text() -> None:
    state = _grounding_state(evidence_link_count=1)
    original = "完整许可证原文" * 500
    state["evidence_links"][0]["quotedText"] = original

    grounded = build_grounded_review_input(state, {"DV-FULL-1"})

    assert original in grounded["evidenceTextCorpus"]


def test_model_output_keeps_every_shard_finding_and_full_diagnostic_text() -> None:
    long_description = "逐项核查诊断" * 400
    content = json.dumps(
        {
            "findings": [
                {
                    "findingType": f"finding_{index}",
                    "severity": "medium",
                    "title": f"第 {index} 条审查发现" + ("标题" * 80),
                    "description": long_description + str(index),
                    "evidenceRefs": [],
                    "ruleRefs": [],
                    "kbRefs": [],
                    "confidence": 0.5,
                    "suggestedAction": "human_confirm",
                    "groundingStatus": "insufficient_evidence",
                    "unsupportedClaims": [],
                }
                for index in range(15)
            ]
        },
        ensure_ascii=False,
    )
    context = {
        "groundingInput": {
            "groundingStatus": "insufficient_evidence",
            "documentVersionIds": ["DV-1"],
            "evidenceLinks": [],
            "evidenceTextCorpus": [long_description],
        },
        "auditRuntime": {"mode": "ocr_llm"},
    }

    drafts = normalize_llm_findings(
        {
            "reviewRunId": "RRUN-FULL-OUTPUT",
            "projectId": "P-1",
            "nodeId": 1,
            "reviewMode": "gap_precheck",
            "advisoryOnly": True,
        },
        context,
        content,
    )

    assert len(drafts) == 15
    assert drafts[-1]["modelTitle"].endswith("标题" * 80)
    assert drafts[-1]["modelDescription"] == long_description + "14"
