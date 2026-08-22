from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import InMemoryRepository, repo
from libs.security.auth import hash_password, issue_token
from scripts.migrate_backend import apply_migrations

pytestmark = pytest.mark.skipif(
    not os.getenv("AICHECK_TEST_POSTGRES_URL"),
    reason="AICHECK_TEST_POSTGRES_URL is required for PostgreSQL integration tests",
)

client = TestClient(app)
PROJECT_ID = "P-REG-PERSISTENCE"
GOOD_PASSWORD = "Aa!234567890x"


def _close(repository: InMemoryRepository) -> None:
    repository.close_sync_postgres()


def _leader_headers() -> dict[str, str]:
    user = next(item for item in repo.state["users"] if item["username"] == "persist-lead")
    return {"Authorization": f"Bearer {issue_token(user)}"}


def test_registration_link_and_request_survive_postgres_restarts(
    isolated_postgres_url: str, monkeypatch
) -> None:
    apply_migrations(isolated_postgres_url)
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_DATA", "false")
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")

    original_state = repo.state
    original_baseline = dict(repo._persistence_baseline)
    original_singleton_baseline = dict(repo._singleton_baseline)
    original_idempotency_baseline = dict(repo._idempotency_baseline)
    first_reload: InMemoryRepository | None = None
    second_reload: InMemoryRepository | None = None
    try:
        repo.reset()
        repo.configure_sync_postgres(isolated_postgres_url)
        repo.state["projects"] = [
            {
                "id": PROJECT_ID,
                "name": "持久化注册项目",
                "contractorOrgName": "持久化施工单位",
                "revision": 1,
            }
        ]
        repo.state["users"] = [
            {
                "id": "U-REG-PERSIST-LEAD",
                "username": "persist-lead",
                "displayName": "持久化项目负责人",
                "passwordHash": hash_password("PersistLead!2026"),
                "role": "inspection",
                "status": "启用",
                "authVersion": 0,
                "mustChangePassword": False,
            }
        ]
        repo.state["project_members"] = [
            {
                "id": "PM-REG-PERSIST-LEAD",
                "projectId": PROJECT_ID,
                "userId": "U-REG-PERSIST-LEAD",
                "role": "inspection",
                "status": "启用",
                "isProjectLeader": True,
                "nodeScope": [1],
                "actions": ["project:view", "project:authorize-member"],
            }
        ]
        repo.state["admin_config"] = {
            "orgUnits": [
                {
                    "id": "ORG-REG-PERSIST-CONTRACTOR",
                    "name": "持久化施工单位",
                    "type": "contractor",
                    "status": "启用",
                }
            ],
            "users": [],
        }
        repo.apply_tenant_scope()
        repo.flush_to_sync_postgres(
            selected_state_keys={"projects", "users", "project_members"},
            selected_singleton_keys={"admin_config"},
        )

        older = client.post(
            f"/api/projects/{PROJECT_ID}/registration-links",
            json={},
            headers=_leader_headers(),
        ).json()
        newer = client.post(
            f"/api/projects/{PROJECT_ID}/registration-links",
            json={},
            headers=_leader_headers(),
        ).json()
        assert older["code"] == 0, older
        assert newer["code"] == 0, newer
        older_token = older["data"]["token"]
        newer_token = newer["data"]["token"]
        applied = client.post(
            f"/api/registration-links/{older_token}/apply",
            json={
                "username": "applicant-persisted",
                "role": "contractor",
                "password": GOOD_PASSWORD,
            },
        ).json()
        assert applied["code"] == 0, applied
        request_id = applied["data"]["requestId"]
        disabled = client.post(
            f"/api/projects/{PROJECT_ID}/registration-links/{older_token}/disable",
            headers=_leader_headers(),
        ).json()
        assert disabled["code"] == 0, disabled

        repo.close_sync_postgres()
        first_reload = InMemoryRepository(seed=False)
        first_reload.configure_sync_postgres(isolated_postgres_url)
        first_reload.load_from_sync_postgres({"project_invitations", "registration_requests"})
        restored_older = next(
            item
            for item in first_reload.state["project_invitations"]
            if item["token"] == older_token
        )
        restored_newer = next(
            item
            for item in first_reload.state["project_invitations"]
            if item["token"] == newer_token
        )
        restored_request = next(
            item
            for item in first_reload.state["registration_requests"]
            if item["id"] == request_id
        )
        assert len(first_reload.state["project_invitations"]) == 2
        assert restored_older["useCount"] == 1
        assert restored_older["disabled"] is True
        assert restored_newer["useCount"] == 0
        assert restored_newer["disabled"] is False
        assert restored_request["status"] == "待审核"
        assert "passwordHash" in restored_request

        repo.postgres_dsn = None
        repo.postgres_enabled = False
        repo.reset()
        repo.configure_sync_postgres(isolated_postgres_url)
        repo.load_from_sync_postgres()
        reviewed = client.post(
            f"/api/projects/{PROJECT_ID}/registration-requests/{request_id}/review",
            json={"approved": True},
            headers=_leader_headers(),
        ).json()
        assert reviewed["code"] == 0, reviewed

        repo.close_sync_postgres()
        second_reload = InMemoryRepository(seed=False)
        second_reload.configure_sync_postgres(isolated_postgres_url)
        second_reload.load_from_sync_postgres()
        approved_request = next(
            item
            for item in second_reload.state["registration_requests"]
            if item["id"] == request_id
        )
        assert approved_request["status"] == "已通过"
        assert any(
            item.get("username") == "applicant-persisted"
            for item in second_reload.state["users"]
        )
        assert any(
            item.get("username") == "applicant-persisted"
            for item in second_reload.state["admin_config"].get("users", [])
        )

        repo.postgres_dsn = None
        repo.postgres_enabled = False
        repo.reset()
        repo.configure_sync_postgres(isolated_postgres_url)
        repo.load_from_sync_postgres()
        listed = client.get(
            f"/api/projects/{PROJECT_ID}/registration-requests", headers=_leader_headers()
        ).json()
        assert listed["code"] == 0, listed
        listed_request = next(item for item in listed["data"]["items"] if item["id"] == request_id)
        assert listed_request["status"] == "已通过"
        assert "passwordHash" not in listed_request
    finally:
        if first_reload is not None:
            _close(first_reload)
        if second_reload is not None:
            _close(second_reload)
        repo.close_sync_postgres()
        repo.postgres_dsn = None
        repo.postgres_enabled = False
        repo.state = original_state
        repo._persistence_baseline = original_baseline
        repo._singleton_baseline = original_singleton_baseline
        repo._idempotency_baseline = original_idempotency_baseline
