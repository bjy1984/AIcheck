"""Public projection of finalized OCR evidence, independent of engineering records."""
from copy import deepcopy

CONTENT_KEYS = ("pages", "fragments", "fields", "tables", "layoutBlocks", "seals", "signatures")
METADATA_KEYS = ("provider", "model", "providerMode", "requestedProfileId", "detectedProfileId",
                 "profileRouteReason", "profileRoutingVersion", "coordinateContract", "postProcessing", "fallback")


def project_ocr_result(parsed: dict, *, page_no: int | None = None) -> dict:
    """Page filters must not silently discard fields whose evidence is document-level."""
    content = {key: deepcopy([row for row in parsed.get(key) or [] if isinstance(row, dict)
                              and (page_no is None or row.get("pageNo") == page_no)])
               for key in CONTENT_KEYS}
    unlocated = {key: deepcopy([row for row in parsed.get(key) or []
                               if isinstance(row, dict) and row.get("pageNo") is None])
                 for key in CONTENT_KEYS if key != "pages"}
    metadata = parsed.get("metadata") or {}
    return {
        **content,
        "documentFields": unlocated.pop("fields"),
        "unlocatedContent": unlocated,
        "resultKind": "processed_ocr",
        "scope": {"pageNo": page_no, "quality": "document", "documentFields": "document"},
        **{key: deepcopy(parsed.get(key)) for key in ("profileId", "documentType", "parserVersion",
           "profilePostprocessVersion", "engineVersion", "outcomeStatus", "formalEvidenceReady", "quality")},
        "processing": {"rawProviderOutput": False,
                       "provenanceAvailable": bool(metadata.get("postProcessing")),
                       **{key: deepcopy(metadata[key]) for key in METADATA_KEYS if key in metadata}},
        "diagnostics": [{key: deepcopy(row[key]) for key in ("code", "level", "stage", "pageNo", "retryable") if key in row}
                        for row in parsed.get("diagnostics") or [] if isinstance(row, dict)
                        and (page_no is None or row.get("pageNo") in (None, page_no))],
    }
