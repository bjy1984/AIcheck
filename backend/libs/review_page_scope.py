"""Page-scope contract foundations. Public execution remains gated until all readers comply."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_page_ranges(value: Any, version_ids: list[str]) -> dict[str, dict[str, int]]:
    """One inclusive range per selected version; omission means the whole fixed version."""
    if not isinstance(value, dict):
        raise ValueError("invalid_review_page_ranges")  # noqa: TRY004 - shared scope validators use ValueError
    allowed = set(version_ids)
    normalized = {}
    for version, bounds in value.items():
        if version not in allowed:
            raise ValueError("review_page_range_version_not_selected")
        if not isinstance(bounds, dict) or set(bounds) != {"start", "end"}:
            raise ValueError("invalid_review_page_range_bounds")
        start, end = bounds["start"], bounds["end"]
        if type(start) is not int or type(end) is not int or not 1 <= start <= end:
            raise ValueError("invalid_review_page_range_bounds")
        normalized[version] = {"start": start, "end": end}
    return dict(sorted(normalized.items()))


def page_record_in_range(record: dict[str, Any], bounds: dict[str, int]) -> bool:
    """Do not guess page one for missing positions or truncate a cross-page table."""
    start = record.get("pageNo")
    end = record.get("endPage", start)
    return (type(start) is int and type(end) is int
            and bounds["start"] <= start <= end <= bounds["end"])


def located_record_in_range(record: dict[str, Any], bounds: dict[str, int]) -> bool:
    return page_record_in_range(record, bounds) and _nested_locations_in_range(record, bounds)


def restrict_parse_result(parse: dict[str, Any], bounds: dict[str, int]) -> dict[str, Any]:
    """Copy located evidence only; whole-document text/summary must not survive as fallback."""
    metadata_keys = ("id", "parseResultId", "documentVersionId", "documentId", "tenantId",
                     "status", "fileName", "documentType", "profileId")
    result = {key: deepcopy(parse[key]) for key in metadata_keys if key in parse}
    for key in ("fields", "tables", "seals", "fragments"):
        result[key] = [deepcopy(row) for row in parse.get(key) or []
                       if isinstance(row, dict) and located_record_in_range(row, bounds)]
    result["reviewPageScope"] = deepcopy(bounds)
    return result


def _nested_locations_in_range(value: Any, bounds: dict[str, int]) -> bool:
    if isinstance(value, list):
        return all(_nested_locations_in_range(item, bounds) for item in value)
    if not isinstance(value, dict):
        return True
    if "pageNo" in value and not page_record_in_range(value, bounds):
        return False
    return all(_nested_locations_in_range(item, bounds) for item in value.values())
