"""节点事实修正与纯 LLM 模式的输入组装。

从 review_orchestrator/execution.py 搬出来的两个纯函数：把监检人工修正的事实
覆盖到本节点业务事实上，以及在 pure_llm 模式下组装不含 OCR 证据的输入。

两者都不碰 repo，只做数据变换——留在四千行的编排文件里既难找也难单测。
"""

from __future__ import annotations

from typing import Any


def apply_node_fact_corrections(
    state: dict[str, Any],
    project_id: str,
    node_id: int,
    facts: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """把监检人员的事实修正覆盖到本节点的业务事实上（issue #5 / D-1）。

    业务口径：修正仅对本节点生效、不跨节点传播；重跑由人工显式触发，
    本函数只在节点重跑的 load_context 步骤被调用。
    """
    if not isinstance(facts, dict):
        return []
    applied: list[dict[str, Any]] = []
    corrections = [
        item
        for item in state.get("fact_corrections", []) or []
        if item.get("projectId") == project_id
        and int(item.get("nodeId") or 0) == int(node_id)
        and item.get("status") == "active"
    ]
    for correction in sorted(corrections, key=lambda item: str(item.get("createdAt") or "")):
        path = str(correction.get("factPath") or "")
        parts = [part for part in path.split(".") if part]
        if not parts:
            continue
        cursor: Any = facts
        for part in parts[:-1]:
            nested = cursor.get(part) if isinstance(cursor, dict) else None
            if not isinstance(nested, dict):
                nested = {}
                if isinstance(cursor, dict):
                    cursor[part] = nested
            cursor = nested
        if isinstance(cursor, dict):
            cursor[parts[-1]] = correction.get("correctedValue")
            applied.append(
                {
                    "correctionId": correction.get("id"),
                    "factPath": path,
                    "correctedBy": correction.get("correctedBy"),
                    "createdAt": correction.get("createdAt"),
                }
            )
    return applied

def pure_llm_grounding_input(version_ids: set[str], audit_runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "PureLlmReviewInput@1.0.0",
        "documentVersionIds": sorted(version_ids),
        "auditInputMode": audit_runtime["mode"],
        "groundingPolicy": audit_runtime["groundingPolicy"],
        "groundingStatus": "insufficient_evidence",
        "blockingIssues": [
            {
                "code": "PURE_LLM_REVIEW_NO_OCR_EVIDENCE",
                "message": "This audit run is configured to skip OCR evidence; all findings are advisory and require human confirmation.",
            }
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "fragments": [],
        "evidenceLinks": [],
        "quality": [],
        "evidenceTextCorpus": [],
        "summary": {
            "fieldCount": 0,
            "tableCount": 0,
            "sealCount": 0,
            "fragmentCount": 0,
            "evidenceLinkCount": 0,
            "lowConfidenceEvidenceCount": 0,
            "missingPositionEvidenceCount": 0,
            "tableContentMissingCount": 0,
            "sealTextRiskCount": 0,
            "criticalQualityFlagCount": 0,
            "blockingIssueCount": 1,
            "groundingStatus": "insufficient_evidence",
            "auditInputMode": audit_runtime["mode"],
        },
        "reviewWarnings": [
            {
                "code": "PURE_LLM_REVIEW_ADVISORY_ONLY",
                "message": "Pure LLM mode does not provide OCR/page/bbox evidence and cannot support automatic compliance conclusions.",
            }
        ],
    }
