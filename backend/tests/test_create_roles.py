from __future__ import annotations

import json
from copy import deepcopy

import pytest

from libs.security.auth import verify_password
from scripts.create_roles import (
    apply_role_bootstrap,
    build_plan,
    load_password_overrides,
    redact_plan_secrets,
    resolve_role_passwords,
    validate_strong_passwords,
)


class FakeCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = [deepcopy(item) for item in docs or []]

    def find_one(self, query: dict, session=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return deepcopy(doc)
        return None

    def replace_one(self, query: dict, replacement: dict, upsert: bool = False, session=None) -> None:
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = deepcopy(replacement)
                return
        if upsert:
            self.docs.append(deepcopy(replacement))

    def insert_one(self, doc: dict, session=None) -> None:
        self.docs.append(deepcopy(doc))


class FakeDatabase(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


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
    database = FakeDatabase()
    database["users"].docs.append(
        {
            "id": "USER-ADMIN-001",
            "username": "admin",
            "passwordHash": "plain:existing-secret",
            "role": "admin",
        }
    )

    result = apply_role_bootstrap(
        database,
        ["admin"],
        "P-2026-HDCP-001",
        passwords={"admin": "Adm!Secure-2026"},
    )
    stored = database["users"].find_one({"username": "admin"})

    assert stored["passwordHash"] == "plain:existing-secret"
    assert next(item for item in result["authChanges"] if item["collection"] == "users")["password"] == "preserved"


def test_create_roles_rotates_existing_password_when_requested() -> None:
    database = FakeDatabase()
    database["users"].docs.append(
        {
            "id": "USER-ADMIN-001",
            "username": "admin",
            "passwordHash": "plain:existing-secret",
            "role": "admin",
        }
    )

    result = apply_role_bootstrap(
        database,
        ["admin"],
        "P-2026-HDCP-001",
        passwords={"admin": "Adm!Secure-2026"},
        rotate_passwords=True,
    )
    stored = database["users"].find_one({"username": "admin"})

    assert verify_password("Adm!Secure-2026", stored["passwordHash"])
    assert next(item for item in result["authChanges"] if item["collection"] == "users")["password"] == "rotated"
