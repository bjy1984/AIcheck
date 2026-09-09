"""Inspect current OCR page locations without approving a handoff's assertions."""
from __future__ import annotations

from typing import Any

from libs.review_workstations import digest


def inspect_handoff_evidence(draft: dict[str, Any], parses: list[dict[str, Any]]) -> dict[str, Any]:
    source = draft["source"]
    allowed = set(source["documentVersionIds"])
    items = []
    for index, ref in enumerate(draft["evidenceRefs"]):
        version_id = ref["documentVersionId"]
        candidates = [row for row in parses if row.get("documentVersionId") == version_id
                      and version_id in allowed and row.get("tenantId") == source["tenantId"]]
        status = "parse_unavailable"
        fingerprint = None
        if len(candidates) > 1:
            status = "parse_ambiguous"
        elif candidates:
            parse = candidates[0]
            fingerprint = digest(parse)
            pages = [page for page in (parse.get("pages") or []) if isinstance(page, dict)
                     and type(page.get("pageNo")) is int and page["pageNo"] == ref["pageNo"]]
            status = "page_located" if len(pages) == 1 else "page_ambiguous" if pages else "page_unavailable"
        items.append({"referenceIndex": index, "documentVersionId": version_id, "pageNo": ref["pageNo"],
                      "status": status, "parseFingerprint": fingerprint})
    return {"basis": "current_ocr", "authoritative": False, "contentSupportStatus": "unverified",
            "status": "no_references" if not items else "locations_found" if all(
                item["status"] == "page_located" for item in items) else "unresolved", "items": items}
