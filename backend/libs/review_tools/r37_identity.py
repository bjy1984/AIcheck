"""Case-record identity, including explicit event identity when present on either side."""
from __future__ import annotations

from typing import Any


def matches_case_record(record: Any, case: dict[str, Any], fields: tuple[str, ...]) -> bool:
    if not isinstance(record, dict) or any(key not in record or key not in case or record[key] != case[key] or type(record[key]) is not type(case[key]) for key in fields):
        return False
    if "eventId" in case or "eventId" in record:
        event = case.get("eventId")
        return isinstance(event, str) and bool(event.strip()) and record.get("eventId") == event
    return True
