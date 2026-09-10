"""Compare source-recorded approval and use times without inventing time precision."""
import re
from datetime import date, datetime, timedelta

from libs.review_tools.r39_tools import _refs

SCOPE = ("projectId", "planVersionId", "ownerOrganizationId", "approvalCycleId")


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed_date = date.fromisoformat(value)
            return "date", parsed_date, parsed_date + timedelta(days=1)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
            return None
        parsed = datetime.fromisoformat(value)
        fraction = re.search(r"\.(\d{1,6})", value)
        resolution = timedelta(microseconds=10 ** (6 - len(fraction[1]))) if fraction else timedelta(seconds=1)
        return ("instant", parsed, parsed + resolution) if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _supported(record, field):
    value = record.get(field)
    refs = _refs(record)
    version = record.get("documentVersionId")
    if not refs or not version or any(ref["documentVersionId"] != version for ref in refs) or _time(value) is None:
        return False
    pattern = r"(?<![\w+.-])" + re.escape(value) + r"(?![\w:+.-])"
    return any(re.search(pattern, ref["quotedText"]) for ref in refs)


def approval_timing(scope, approval, usage):
    result = {"code": "r11_owner_approval_before_use", "result": "evidence_insufficient", "evidenceRefs": []}
    if (not isinstance(approval, dict) or not isinstance(usage, dict)
            or any(record.get(key) != scope.get(key) for record in (approval, usage) for key in SCOPE)
            or approval.get("decision") != "approved" or usage.get("usageStatus") != "started"):
        return result
    if not _supported(approval, "approvedAt") or not _supported(usage, "startedAt"):
        return result
    left, right = _time(approval["approvedAt"]), _time(usage["startedAt"])
    result.update(evidenceRefs=[*_refs(approval), *_refs(usage)], approvedAt=approval["approvedAt"], startedAt=usage["startedAt"])
    # A calendar date has no timezone/time-of-day: do not mix it with an instant.
    # Equal recorded times cannot establish "before", including same-day records.
    if left[0] == right[0]:
        if left[2] <= right[1]:
            result["result"] = "passed"
        elif right[2] <= left[1]:
            result["result"] = "failed"
    return result
