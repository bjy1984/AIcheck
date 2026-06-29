from __future__ import annotations

import json

import pytest

from libs.db.repository import repo
from libs.security.auth import verify_password
from scripts.create_roles import (
    apply_role_bootstrap_to_state,
    build_plan,
    load_password_overrides,
    redact_plan_secrets,
    resolve_role_passwords,
    validate_strong_passwords,
)


def setup_function() -> None:
    repo.reset()


def test_create_roles_strong_password_validation_rejects_default_passwords() -> None:
    roles = ["admin", "inspection"]
    passwords = resolve_role_passwords(roles)

    with pytest.raises(SystemExit) as exc:
        validate_strong_passwords(roles, passwords)

    message = str(exc.value)
    assert "admin" in message
    assert "inspection" in message
    assert "contains username/default" in message


def test_create_roles_password_file_overrides_and_redacts_output(tmp_path) -> None:
    password_file = tmp_path / "role-passwords.json"
    password_file.write_text(
        json.dumps(
            {
                "admin": "Adm!Secure-2026",
                "inspection": "Insp!Secure-2026",
            }
        ),
        encoding="utf-8",
    )
    roles = ["admin", "inspection"]
    passwords = resolve_role_passwords(roles, load_password_overrides(str(password_file)))

    validate_strong_passwords(roles, passwords)
    plan = build_plan(roles, "P-2026-HDCP-001", passwords=passwords, show_passwords=False)
    redacted = redact_plan_secrets(plan)

    assert plan["loginAccounts"][0]["password"] == "<redacted>"
    assert all(account["passwordConfigured"] for account in plan["loginAccounts"])
    assert all(user["passwordHash"].startswith("pbkdf2_sha256$") for user in plan["authUsers"])
    assert all(user["passwordHash"] == "<redacted>" for user in redacted["authUsers"])


def test_create_roles_preserves_existing_password_hash_by_default() -> None:
    repo.state["users"].append(
        {
            "id": "USER-ADMIN-001",
            "username": "admin",
            "passwordHash": "plain:existing-secret",
            "role": "admin",
        }
    )

    result = apply_role_bootstrap_to_state(
        ["admin"],
        "P-2026-HDCP-001",
        passwords={"admin": "Adm!Secure-2026"},
    )
    stored = next(item for item in repo.state["users"] if item["username"] == "admin")

    assert stored["passwordHash"] == "plain:existing-secret"
    assert next(item for item in result["authChanges"] if item["collection"] == "users")["password"] == "preserved"


def test_create_roles_rotates_existing_password_when_requested() -> None:
    repo.state["users"].append(
        {
            "id": "USER-ADMIN-001",
            "username": "admin",
            "passwordHash": "plain:existing-secret",
            "role": "admin",
        }
    )

    result = apply_role_bootstrap_to_state(
        ["admin"],
        "P-2026-HDCP-001",
        passwords={"admin": "Adm!Secure-2026"},
        rotate_passwords=True,
    )
    stored = next(item for item in repo.state["users"] if item["username"] == "admin")

    assert verify_password("Adm!Secure-2026", stored["passwordHash"])
    assert next(item for item in result["authChanges"] if item["collection"] == "users")["password"] == "rotated"
