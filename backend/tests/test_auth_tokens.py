from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.security import auth
from libs.security.auth import decode_token, issue_token

client = TestClient(app)


class BrokenJose:
    def encode(self, *args, **kwargs):
        raise RuntimeError("jose backend unavailable")

    def decode(self, *args, **kwargs):
        raise RuntimeError("jose backend unavailable")


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def test_tokens_fail_closed_when_jwt_backend_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(auth, "jwt", BrokenJose())

    with pytest.raises(RuntimeError, match="jose backend unavailable"):
        issue_token({"username": "ndt", "role": "ndt"})

    assert decode_token("Bearer unavailable-token") is None


def test_login_fails_closed_when_jwt_backend_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(auth, "jwt", BrokenJose())

    response = client.post("/api/auth/login", json={"username": "ndt", "password": "ndt"})
    payload = response.json()

    assert response.status_code == 503
    assert payload["code"] != 0
    assert payload["data"]["reason"] == "SECURITY_BACKEND_UNAVAILABLE"
