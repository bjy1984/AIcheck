from __future__ import annotations

import re


SAFE_REASON_PATTERN = re.compile(r"^[A-Z][A-Z0-9_.-]{1,79}$")


class IntegrationServiceError(RuntimeError):
    """Sanitized error for internal service/provider calls."""

    def __init__(
        self,
        service: str,
        operation: str,
        *,
        status_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        self.service = service
        self.operation = operation
        self.status_code = status_code
        self.reason = safe_reason(reason)

        parts = [f"{service} {operation} failed"]
        if status_code is not None:
            parts.append(f"HTTP {status_code}")
        if self.reason:
            parts.append(f"reason {self.reason}")
        super().__init__(": ".join(parts))


def safe_reason(reason: object | None) -> str | None:
    if reason is None:
        return None
    text = str(reason).strip()
    if SAFE_REASON_PATTERN.fullmatch(text):
        return text
    return None
