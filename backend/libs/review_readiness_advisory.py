from __future__ import annotations

from copy import deepcopy
from typing import Any


def review_readiness_prompt(value: Any, *, include_reasons: bool = False) -> dict[str, Any]:
    readiness = value if isinstance(value, dict) else {}
    output = {
        "readinessAdvisoryOnly": True,
        "requiredCount": int(readiness.get("requiredCount") or 0),
        "satisfiedCount": int(readiness.get("satisfiedCount") or 0),
        "missingCount": int(readiness.get("missingCount") or 0),
        "pendingCount": int(readiness.get("pendingCount") or 0),
        "supportingDocumentCount": int(readiness.get("supportingDocumentCount") or 0),
        "missingRequirements": [
            {
                "reviewContent": item.get("reviewContent"),
                "materialTypeName": item.get("materialTypeName"),
                "evidenceReviewStatus": item.get("evidenceReviewStatus"),
            }
            for item in (readiness.get("missingRequirements") or [])[:20]
            if isinstance(item, dict)
        ],
    }
    if include_reasons:
        output["advisoryReasons"] = deepcopy(
            readiness.get("advisoryReasons") or readiness.get("blockingReasons") or []
        )
    return output
