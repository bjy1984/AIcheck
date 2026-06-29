from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.contracts.responses import server_time
from libs.db.repository import repo
from libs.db.seed import ADMIN_CONFIG, PROJECT_ID, ROLE_ACTIONS
from libs.security.auth import ROLE_DEFAULT_PATHS, hash_password


ROLE_SPECS: dict[str, dict[str, Any]] = {
    "admin": {
        "userId": "USER-ADMIN-001",
        "username": "admin",
        "name": "系统管理员",
        "roleLabel": "系统管理员",
        "orgId": "ORG-ADMIN-001",
        "orgName": "省特检院平台组",
        "orgType": "admin",
        "mobile": "13800000000",
        "nodeScope": [16, 24, 40, 59],
        "readonly": False,
    },
    "inspection": {
        "userId": "USER-INSPECTION-001",
        "username": "inspection",
        "name": "张工",
        "roleLabel": "监检人员",
        "orgId": "ORG-INSPECTION-001",
        "orgName": "省特检院一部",
        "orgType": "inspection",
        "mobile": "13800000004",
        "nodeScope": [16, 24, 40, 59],
        "readonly": False,
    },
    "contractor": {
        "userId": "USER-CONTRACTOR-001",
        "username": "contractor",
        "name": "李工",
        "roleLabel": "施工方",
        "orgId": "ORG-CONTRACTOR-001",
        "orgName": "中石化安装有限公司",
        "orgType": "contractor",
        "mobile": "13800000002",
        "nodeScope": [16, 24, 25],
        "readonly": False,
    },
    "ndt": {
        "userId": "USER-NDT-001",
        "username": "ndt",
        "name": "王工",
        "roleLabel": "无损检测",
        "orgId": "ORG-NDT-001",
        "orgName": "华测检测有限公司",
        "orgType": "ndt",
        "mobile": "13800000003",
        "nodeScope": [35, 36, 40, 41, 42],
        "readonly": False,
    },
    "owner": {
        "userId": "USER-OWNER-001",
        "username": "owner",
        "name": "赵经理",
        "roleLabel": "建设方",
        "orgId": "ORG-OWNER-001",
        "orgName": "华东管网建设公司",
        "orgType": "owner",
        "mobile": "13800000001",
        "nodeScope": [1, 16, 24, 40, 59, 68],
        "readonly": True,
    },
    "fde": {
        "userId": "USER-FDE-001",
        "username": "fde",
        "name": "FDE 工程师",
        "roleLabel": "FDE",
        "orgId": "ORG-FDE-001",
        "orgName": "AI 交付治理组",
        "orgType": "fde",
        "mobile": "13800000061",
        "nodeScope": [],
        "readonly": False,
        "platformOnly": True,
    },
}


def role_id_for(role: str) -> str:
    ordered_roles = [
        "admin",
        "inspection",
        "contractor",
        "ndt",
        "owner",
        "fde",
    ]
    return str(ordered_roles.index(role) + 1 if role in ordered_roles else 99)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or repair AIcheck role directory and project member grants."
    )
    parser.add_argument(
        "--roles",
        default="admin,inspection,contractor,ndt,owner,fde",
        help="Comma-separated roles to create. Defaults to all supported roles.",
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("AICHECK_DEFAULT_PROJECT_ID", PROJECT_ID),
        help="Project id for project_members grants. Defaults to demo project.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL"),
        help="PostgreSQL URL. Defaults to AICHECK_DATABASE_URL.",
    )
    parser.add_argument(
        "--db",
        default=os.getenv("AICHECK_POSTGRES_DB", "aicheck"),
        help="PostgreSQL business database name. Defaults to AICHECK_POSTGRES_DB or aicheck.",
    )
    parser.add_argument(
        "--password-file",
        help="JSON file mapping role or username to initial password. Environment variables AICHECK_BOOTSTRAP_PASSWORD_<ROLE> also work.",
    )
    parser.add_argument(
        "--require-strong-passwords",
        action="store_true",
        help="Fail if any selected role uses a weak/default initial password.",
    )
    parser.add_argument(
        "--rotate-passwords",
        action="store_true",
        help="Replace existing user password hashes with supplied passwords. Default preserves existing hashes.",
    )
    parser.add_argument(
        "--show-passwords",
        action="store_true",
        help="Print initial passwords in output. Avoid this in production logs.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing PostgreSQL.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    return parser.parse_args()


def selected_roles(raw_roles: str) -> list[str]:
    roles = [role.strip() for role in raw_roles.split(",") if role.strip()]
    unknown = [role for role in roles if role not in ROLE_SPECS]
    if unknown:
        raise SystemExit(f"Unsupported roles: {', '.join(unknown)}")
    return roles


def unique_values(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def load_password_overrides(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Failed to read password file: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("Password file must be a JSON object mapping role or username to password.")
    overrides: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            raise SystemExit("Password file keys and values must be non-empty strings.")
        overrides[key] = value
    valid_keys = set(ROLE_SPECS)
    valid_keys.update(spec["username"] for spec in ROLE_SPECS.values())
    unknown = sorted(set(overrides) - valid_keys)
    if unknown:
        raise SystemExit(f"Password file contains unsupported role/user keys: {', '.join(unknown)}")
    return overrides


def resolve_role_passwords(roles: list[str], overrides: dict[str, str] | None = None) -> dict[str, str]:
    overrides = overrides or {}
    passwords: dict[str, str] = {}
    for role in roles:
        spec = ROLE_SPECS[role]
        env_keys = [
            f"AICHECK_BOOTSTRAP_PASSWORD_{role.upper()}",
            f"AICHECK_BOOTSTRAP_PASSWORD_{spec['username'].upper()}",
        ]
        password = overrides.get(role) or overrides.get(spec["username"])
        if password is None:
            password = next((os.getenv(key) for key in env_keys if os.getenv(key)), None)
        passwords[role] = password or spec["username"]
    return passwords


def password_strength_errors(role: str, password: str) -> list[str]:
    spec = ROLE_SPECS[role]
    username = spec["username"]
    errors: list[str] = []
    if len(password) < 12:
        errors.append("length < 12")
    if password == username or username.lower() in password.lower():
        errors.append("contains username/default")
    classes = [
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"\d", password)),
        bool(re.search(r"[^A-Za-z0-9]", password)),
    ]
    if sum(classes) < 3:
        errors.append("requires at least 3 character classes")
    if password.lower() in {"password", "password123", "admin", "aicheck", role, username}:
        errors.append("common password")
    return errors


def validate_strong_passwords(roles: list[str], passwords: dict[str, str]) -> None:
    failures = []
    for role in roles:
        errors = password_strength_errors(role, passwords[role])
        if errors:
            failures.append(f"{role}: {', '.join(errors)}")
    if failures:
        raise SystemExit("Weak bootstrap passwords: " + "; ".join(failures))


def login_accounts(roles: list[str], passwords: dict[str, str], *, show_passwords: bool) -> list[dict[str, Any]]:
    return [
        {
            "username": ROLE_SPECS[role]["username"],
            "password": passwords[role] if show_passwords else "<redacted>",
            "passwordConfigured": passwords[role] != ROLE_SPECS[role]["username"],
            "role": role,
            "defaultPath": ROLE_DEFAULT_PATHS[role],
        }
        for role in roles
    ]


def upsert_by_key(items: list[dict[str, Any]], item: dict[str, Any], key: str) -> tuple[str, dict[str, Any]]:
    for index, existing in enumerate(items):
        if existing.get(key) == item.get(key):
            merged = {**existing, **item}
            items[index] = merged
            return "updated", merged
    items.append(item)
    return "created", item


def role_org_unit(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": spec["orgId"],
        "name": spec["orgName"],
        "type": spec["orgType"],
        "contactName": spec["name"],
        "contactPhone": spec["mobile"],
        "status": "启用",
        "projectCount": 1,
    }


def role_user(role: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": spec["userId"],
        "username": spec["username"],
        "name": spec["name"],
        "orgName": spec["orgName"],
        "role": role,
        "roleLabel": spec["roleLabel"],
        "mobile": spec["mobile"],
        "status": "启用",
        "defaultPath": ROLE_DEFAULT_PATHS[role],
        "lastLoginAt": None,
    }


def auth_user(role: str, spec: dict[str, Any], password: str) -> dict[str, Any]:
    return {
        "id": spec["userId"],
        "username": spec["username"],
        "passwordHash": hash_password(password),
        "role": role,
        "roleId": role_id_for(role),
        "roleLabel": spec["roleLabel"],
        "permissions": ROLE_ACTIONS[role],
        "displayName": spec["name"],
        "orgUnitName": spec["orgName"],
        "status": "启用",
        "defaultPath": ROLE_DEFAULT_PATHS[role],
        "updatedAt": server_time(),
    }


def role_record(role: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"ROLE-{role.upper()}",
        "role": role,
        "label": spec["roleLabel"],
        "actions": ROLE_ACTIONS[role],
        "readonly": spec["readonly"],
        "status": "启用",
        "defaultPath": ROLE_DEFAULT_PATHS[role],
        "updatedAt": server_time(),
    }


def permission_matrix_item(role: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": role,
        "label": spec["roleLabel"],
        "projectScope": "全部项目" if role == "admin" else "授权项目",
        "nodeScope": "全部节点" if role == "admin" else "授权节点",
        "actions": ROLE_ACTIONS[role],
        "readonly": spec["readonly"],
        "defaultPath": ROLE_DEFAULT_PATHS[role],
    }


def project_member(role: str, spec: dict[str, Any], project_id: str) -> dict[str, Any]:
    return {
        "id": f"PM-{role.upper()}-001",
        "projectId": project_id,
        "userId": spec["userId"],
        "name": spec["name"],
        "orgName": spec["orgName"],
        "role": role,
        "nodeScope": spec["nodeScope"],
        "actions": ROLE_ACTIONS[role],
        "status": "启用",
        "expiresAt": None,
        "updatedAt": server_time(),
    }


def build_admin_config_payload(existing_payload: dict[str, Any] | None, roles: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = deepcopy(existing_payload or ADMIN_CONFIG)
    payload.setdefault("orgUnits", [])
    payload.setdefault("users", [])
    payload.setdefault("permissionMatrix", [])
    changes: list[dict[str, Any]] = []

    for role in roles:
        spec = ROLE_SPECS[role]
        status, item = upsert_by_key(payload["orgUnits"], role_org_unit(spec), "id")
        changes.append({"collection": "admin_configs.payload.orgUnits", "action": status, "id": item["id"]})
        status, item = upsert_by_key(payload["users"], role_user(role, spec), "id")
        changes.append({"collection": "admin_configs.payload.users", "action": status, "id": item["id"]})
        status, item = upsert_by_key(payload["permissionMatrix"], permission_matrix_item(role, spec), "role")
        changes.append({"collection": "admin_configs.payload.permissionMatrix", "action": status, "role": item["role"]})

    return payload, changes


def merge_project_member(existing: dict[str, Any] | None, desired: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not existing:
        return "created", desired
    merged = {**existing, **desired}
    merged["id"] = existing.get("id") or desired["id"]
    merged["nodeScope"] = unique_values([*(existing.get("nodeScope") or []), *desired["nodeScope"]])
    merged["actions"] = unique_values([*(existing.get("actions") or []), *desired["actions"]])
    merged["updatedAt"] = server_time()
    return "updated", merged


def redact_plan_secrets(plan: dict[str, Any]) -> dict[str, Any]:
    safe_plan = deepcopy(plan)
    for user in safe_plan.get("authUsers", []):
        if "passwordHash" in user:
            user["passwordHash"] = "<redacted>"
    return safe_plan


def build_plan(
    roles: list[str],
    project_id: str,
    *,
    passwords: dict[str, str] | None = None,
    show_passwords: bool = False,
) -> dict[str, Any]:
    passwords = passwords or resolve_role_passwords(roles)
    admin_payload, admin_changes = build_admin_config_payload(None, roles)
    member_roles = [role for role in roles if not ROLE_SPECS[role].get("platformOnly")]
    members = [project_member(role, ROLE_SPECS[role], project_id) for role in member_roles]
    users = [auth_user(role, ROLE_SPECS[role], passwords[role]) for role in roles]
    role_records = [role_record(role, ROLE_SPECS[role]) for role in roles]
    return {
        "projectId": project_id,
        "roles": roles,
        "adminConfigChanges": admin_changes,
        "authUsers": users,
        "authRoles": role_records,
        "projectMembers": members,
        "loginAccounts": login_accounts(roles, passwords, show_passwords=show_passwords),
        "adminConfigPayload": admin_payload,
    }


def apply_role_bootstrap_to_state(
    roles: list[str],
    project_id: str,
    *,
    passwords: dict[str, str] | None = None,
    rotate_passwords: bool = False,
) -> dict[str, Any]:
    passwords = passwords or resolve_role_passwords(roles)
    admin_payload, admin_changes = build_admin_config_payload(repo.state.get("admin_config"), roles)
    repo.state["admin_config"] = admin_payload

    auth_changes: list[dict[str, Any]] = []
    for role in roles:
        spec = ROLE_SPECS[role]
        user = auth_user(role, spec, passwords[role])
        role_doc = role_record(role, spec)
        existing_user = next((item for item in repo.state["users"] if item.get("username") == user["username"]), None)
        password_action = "created"
        if existing_user and existing_user.get("passwordHash") and not rotate_passwords:
            user["passwordHash"] = existing_user["passwordHash"]
            password_action = "preserved"
        elif existing_user:
            password_action = "rotated"
        user_status, merged_user = upsert_by_key(repo.state["users"], user, "username")
        upsert_by_key(repo.state["roles"], role_doc, "role")
        auth_changes.extend(
            [
                {
                    "collection": "users",
                    "action": user_status,
                    "id": merged_user["id"],
                    "password": password_action,
                },
                {"collection": "roles", "action": "upserted", "role": role},
            ]
        )

    member_changes: list[dict[str, Any]] = []
    for role in roles:
        if ROLE_SPECS[role].get("platformOnly"):
            continue
        desired = project_member(role, ROLE_SPECS[role], project_id)
        existing_index = next(
            (
                index
                for index, item in enumerate(repo.state["project_members"])
                if item.get("projectId") == project_id and item.get("userId") == desired["userId"] and item.get("role") == role
            ),
            None,
        )
        existing = repo.state["project_members"][existing_index] if existing_index is not None else None
        status, merged = merge_project_member(existing, desired)
        if existing_index is None:
            repo.state["project_members"].append(merged)
        else:
            repo.state["project_members"][existing_index] = merged
        member_changes.append(
            {
                "collection": "project_members",
                "action": status,
                "id": merged["id"],
                "role": role,
                "nodeScope": merged["nodeScope"],
            }
        )

    audit_id = f"AUD-{uuid4().hex[:10].upper()}"
    repo.state["audit_logs"].append(
        {
            "id": audit_id,
            "actorId": "USER-SYSTEM",
            "actorName": "部署初始化脚本",
            "actorOrgName": "AIcheck",
            "action": "初始化角色与项目成员授权",
            "objectType": "RoleBootstrap",
            "objectId": project_id,
            "result": "成功",
            "createdAt": server_time(),
        }
    )
    return {
        "dryRun": False,
        "projectId": project_id,
        "adminConfigChanges": admin_changes,
        "authChanges": auth_changes,
        "projectMemberChanges": member_changes,
        "auditLogId": audit_id,
    }

def sync_postgres(
    database_url: str,
    roles: list[str],
    project_id: str,
    *,
    passwords: dict[str, str],
    rotate_passwords: bool,
) -> dict[str, Any]:
    repo.configure_sync_postgres(database_url)
    if repo.sync_postgres is None:
        raise SystemExit("psycopg is required and AICHECK_DATABASE_URL must point to a reachable PostgreSQL database.")
    repo.ensure_postgres_schema()
    repo.load_from_sync_postgres()
    result = apply_role_bootstrap_to_state(
        roles,
        project_id,
        passwords=passwords,
        rotate_passwords=rotate_passwords,
    )
    repo.flush_to_sync_postgres()
    result.update({"database": "postgresql", "transactional": True})
    return result


def print_summary(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    mode = "DRY RUN" if result.get("dryRun") else "APPLIED"
    print(f"[{mode}] projectId={result.get('projectId')}")
    if not result.get("dryRun"):
        print(f"- postgres transaction: {'enabled' if result.get('transactional') else 'disabled'}")
    for item in result.get("adminConfigChanges", []):
        identifier = item.get("id") or item.get("role")
        print(f"- {item['collection']}: {item['action']} {identifier}")
    for item in result.get("authChanges", []):
        identifier = item.get("id") or item.get("role")
        print(f"- {item['collection']}: {item['action']} {identifier}")
    for item in result.get("authUsers", []):
        print(f"- users: planned {item['username']} ({item['role']})")
    for item in result.get("projectMemberChanges", result.get("projectMembers", [])):
        print(f"- project_members: {item.get('action', 'planned')} {item['role']} {item.get('nodeScope')}")
    if result.get("loginAccounts"):
        print("Login demo accounts:")
        for account in result["loginAccounts"]:
            print(f"- {account['username']} / {account['password']} -> {account['defaultPath']}")


def main() -> None:
    args = parse_args()
    roles = selected_roles(args.roles)
    passwords = resolve_role_passwords(roles, load_password_overrides(args.password_file))
    if args.require_strong_passwords or os.getenv("AICHECK_STRICT_PRODUCTION", "false").lower() == "true":
        validate_strong_passwords(roles, passwords)
    if args.dry_run:
        result = build_plan(roles, args.project_id, passwords=passwords, show_passwords=args.show_passwords)
        result["dryRun"] = True
        result["projectMemberChanges"] = [
            {"collection": "project_members", "action": "planned", "role": item["role"], "nodeScope": item["nodeScope"]}
            for item in result["projectMembers"]
        ]
        result.pop("adminConfigPayload", None)
        result.pop("projectMembers", None)
        result = redact_plan_secrets(result)
        print_summary(result, args.json)
        return

    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required unless --dry-run is used.")
    result = sync_postgres(
        args.database_url,
        roles,
        args.project_id,
        passwords=passwords,
        rotate_passwords=args.rotate_passwords,
    )
    result["loginAccounts"] = login_accounts(roles, passwords, show_passwords=args.show_passwords)
    print_summary(result, args.json)


if __name__ == "__main__":
    main()
