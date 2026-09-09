"""Page-scope contract foundations. Public execution remains gated until all readers comply."""
from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from libs.ocr.page_coverage import review_coverage_gap


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
    result["reviewCoverageGap"] = deepcopy(review_coverage_gap(parse, bounds))
    return result


def _nested_locations_in_range(value: Any, bounds: dict[str, int]) -> bool:
    if isinstance(value, list):
        return all(_nested_locations_in_range(item, bounds) for item in value)
    if not isinstance(value, dict):
        return True
    if "pageNo" in value and not page_record_in_range(value, bounds):
        return False
    return all(_nested_locations_in_range(item, bounds) for item in value.values())


def task_page_ranges(ai_run: dict[str, Any]) -> dict[str, dict[str, int]] | None:
    if ({"conditionObjectMapping", "handoffSelection"} & ai_run.keys()) and os.getenv("AICHECK_WORKSTATIONS_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise ValueError("condition_mapping_requires_workstation")
    if "inputDocumentPageRanges" not in ai_run:
        return None
    ranges = normalize_page_ranges(ai_run["inputDocumentPageRanges"], ai_run.get("inputDocumentVersionIds") or [])
    if os.getenv("AICHECK_WORKSTATIONS_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise ValueError("review_page_scope_requires_workstation")
    return ranges


def prompt_grounding(state, run, context, grounder):
    """A scoped prompt must rebuild evidence rather than reuse unbounded context."""
    from libs.review_handoff_inputs import handoff_prompt_payload
    context["verifiedHandoffInputs"] = handoff_prompt_payload(run, state)
    scoped = bool(run.get("inputDocumentPageRanges"))
    grounding = (None if scoped else context.get("groundingInput")) or grounder(
        state, set(run.get("inputDocumentVersionIds") or []),
        **({"review_run": run} if scoped else {}),
    )
    fields = context.get("fields") or []
    if scoped:
        fields = grounding.get("fields") or []
        context["fields"] = fields
        context["evidenceLinks"] = grounding.get("evidenceLinks") or []
    context["groundingInput"] = grounding
    return grounding, fields


def existing_scoped_run(ai_run, ranges, repository, ensure_sources):
    existing_id = ai_run.get("reviewRunId")
    existing = repository.find_one("review_runs", str(existing_id), id_field="reviewRunId") if existing_id else None
    if existing:
        from libs.review_condition_mapping import assert_mapping_reuse
        assert_mapping_reuse(ai_run, existing, repository.state)
        from libs.review_handoff_inputs import assert_handoff_reuse
        assert_handoff_reuse(ai_run, existing, repository.state)
        if (ranges or {}) != (existing.get("inputDocumentPageRanges") or {}):
            raise ValueError("review_page_scope_existing_run_mismatch")
        if ranges:
            ensure_sources(existing, repository.state)
    return existing
