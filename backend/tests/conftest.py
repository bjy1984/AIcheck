from __future__ import annotations

import pytest

from libs.security.session import security_sessions


@pytest.fixture(autouse=True)
def allow_explicit_test_dev_tokens(monkeypatch):
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "true")
    monkeypatch.delenv("AICHECK_STRICT_PRODUCTION", raising=False)
    security_sessions.reset_for_tests()
    yield
    security_sessions.reset_for_tests()
