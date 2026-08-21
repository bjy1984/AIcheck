from __future__ import annotations

from typing import Any

from libs.contracts.responses import server_time
from libs.material_auto_classify import (
    UNCLASSIFIED_MATERIAL_CODE,
    classify_material,
    unclassified_material_result,
)
from libs.material_targeting import latest_parse_result, run_material_targeting


CLASSIFICATION_FIELDS = (
    "materialCategory",
    "materialTypeCode",
    "materialTypeName",
    "classificationStatus",
    "classificationConfidence",
    "classificationSource",
    "classificationReasons",
    "classifierVersion",
    "classificationError",
)


def _classification_text(parse_result: dict[str, Any] | None, *, limit: int = 120_000) -> str:
    parts: list[str] = []
    total = 0

    def visit(value: Any) -> None:
        nonlocal total
        if total >= limit or value is None:
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in {"bbox", "polygon", "metadata", "diagnostics", "engineRuns"}:
                    continue
                visit(nested)
            return
        if isinstance(value, list):
            for nested in value:
                visit(nested)
            return
        text = str(value).strip()
        if text:
            parts.append(text)
            total += len(text) + 1

    for key in ("fragments", "fields", "tables", "seals"):
        visit((parse_result or {}).get(key))
    return " ".join(parts)[:limit]


def persist_document_classification(
    repo: Any,
    document: dict[str, Any],
    knowledge_file: dict[str, Any] | None,
    classification: dict[str, Any],
) -> dict[str, Any]:
    now = server_time()
    persisted = {
        key: repo.clone(classification.get(key))
        for key in CLASSIFICATION_FIELDS
        if classification.get(key) is not None
    }
    persisted["classifiedAt"] = now
    for record in (document, knowledge_file):
        if record is None:
            continue
        if classification.get("classificationError") is None:
            record.pop("classificationError", None)
        record.update(repo.clone(persisted))
        record["autoClassification"] = repo.clone(classification)
        record["updatedAt"] = now
    return persisted


def process_document_classification_and_targeting(
    repo: Any,
    project_id: str,
    document_id: str,
    document_version_id: str,
    *,
    triggered_by: str,
) -> dict[str, Any]:
    document = repo.find_one("documents", document_id)
    if not document or str(document.get("projectId") or "") != str(project_id):
        return {
            "status": "missing_document",
            "documentId": document_id,
            "documentVersionId": document_version_id,
        }
    version = repo.find_one("versions", document_version_id)
    if not version or str(version.get("documentId") or "") != str(document_id):
        return {
            "status": "version_mismatch",
            "documentId": document_id,
            "documentVersionId": document_version_id,
        }
    if str(document.get("currentVersionId") or "") != str(document_version_id):
        return {
            "status": "stale_version",
            "documentId": document_id,
            "documentVersionId": document_version_id,
            "currentDocumentVersionId": document.get("currentVersionId"),
        }
    parse_result = latest_parse_result(repo, document_version_id)
    if not parse_result:
        return {
            "status": "awaiting_ocr",
            "documentId": document_id,
            "documentVersionId": document_version_id,
        }
    try:
        classification = classify_material(
            file_name=str(document.get("fileName") or parse_result.get("fileName") or ""),
            ocr_text=_classification_text(parse_result),
            profile_id=str(parse_result.get("profileId") or ""),
            document_type=str(parse_result.get("documentType") or ""),
        )
    except Exception as exc:  # Classification failure must not stop slice/vector processing.
        classification = {
            **unclassified_material_result(reason="自动分类服务异常，已进入未分类资料库"),
            "classificationError": exc.__class__.__name__,
        }

    knowledge_file = repo.knowledge_file_for_version(document_version_id)
    persist_document_classification(repo, document, knowledge_file, classification)

    if classification.get("materialTypeCode") == UNCLASSIFIED_MATERIAL_CODE:
        targeting: dict[str, Any] = {
            "status": "skipped_unclassified",
            "documentId": document_id,
            "documentVersionId": document_version_id,
            "createdBindingCount": 0,
            "createdLinkCount": 0,
        }
    else:
        try:
            targeting = run_material_targeting(
                repo,
                project_id,
                document_id,
                document_version_id,
                triggered_by=triggered_by,
            )
        except Exception as exc:  # Targeting is advisory to the upload processing lifecycle.
            targeting = {
                "status": "failed",
                "documentId": document_id,
                "documentVersionId": document_version_id,
                "createdBindingCount": 0,
                "createdLinkCount": 0,
                "error": exc.__class__.__name__,
            }

    return {
        "status": "completed",
        "documentId": document_id,
        "documentVersionId": document_version_id,
        "classification": repo.clone(classification),
        "targeting": repo.clone(targeting),
    }
