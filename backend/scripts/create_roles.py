from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.contracts.responses import server_time
from libs.db.seed import ADMIN_CONFIG, PROJECT_ID, ROLE_ACTIONS
from libs.security.auth import ROLE_DEFAULT_PATHS


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
        "nodeScope": [1, 16, 24, 40, 68],
        "readonly": True,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or repair AIcheck role directory and project member grants."
    )
    parser.add_argument(
        "--roles",
        default="admin,inspection,contractor,ndt,owner",
        help="Comma-separated roles to create. Defaults to all supported roles.",
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("AICHECK_DEFAULT_PROJECT_ID", PROJECT_ID),
        help="Project id for project_members grants. Defaults to demo project.",
    )
    parser.add_argument(
        "--mongo-url",
        default=os.getenv("AICHECK_MONGO_URL"),
        help="MongoDB URL. Defaults to AICHECK_MONGO_URL.",
    )
    parser.add_argument(
        "--db",
        default=os.getenv("AICHECK_MONGO_DB", "aicheck"),
        help="MongoDB database name. Defaults to AICHECK_MONGO_DB or aicheck.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing MongoDB.")
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


def build_plan(roles: list[str], project_id: str) -> dict[str, Any]:
    admin_payload, admin_changes = build_admin_config_payload(None, roles)
    members = [project_member(role, ROLE_SPECS[role], project_id) for role in roles]
    return {
        "projectId": project_id,
        "roles": roles,
        "adminConfigChanges": admin_changes,
        "projectMembers": members,
        "loginAccounts": [
            {
                "username": ROLE_SPECS[role]["username"],
                "password": ROLE_SPECS[role]["username"],
                "role": role,
                "defaultPath": ROLE_DEFAULT_PATHS[role],
            }
            for role in roles
        ],
        "adminConfigPayload": admin_payload,
    }


def sync_mongo(mongo_url: str, db_name: str, roles: list[str], project_id: str) -> dict[str, Any]:
    try:
        from pymongo import MongoClient
    except Exception as exc:  # pragma: no cover - dependency failure is deployment-specific
        raise SystemExit(f"pymongo is required to write MongoDB: {exc}") from exc

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
    database = client[db_name]
    try:
        client.admin.command("ping")
        admin_doc = database["admin_configs"].find_one({"_singleton": "admin_config"})
        existing_payload = (admin_doc or {}).get("payload")
        admin_payload, admin_changes = build_admin_config_payload(existing_payload, roles)
        database["admin_configs"].replace_one(
            {"_singleton": "admin_config"},
            {"_singleton": "admin_config", "payload": admin_payload},
            upsert=True,
        )

        member_changes: list[dict[str, Any]] = []
        for role in roles:
            desired = project_member(role, ROLE_SPECS[role], project_id)
            existing = database["project_members"].find_one(
                {"projectId": project_id, "userId": desired["userId"], "role": role}
            )
            status, merged = merge_project_member(existing, desired)
            merged.pop("_id", None)
            database["project_members"].replace_one(
                {"projectId": project_id, "userId": desired["userId"], "role": role},
                merged,
                upsert=True,
            )
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
        database["audit_logs"].insert_one(
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
            "database": db_name,
            "projectId": project_id,
            "adminConfigChanges": admin_changes,
            "projectMemberChanges": member_changes,
            "auditLogId": audit_id,
        }
    finally:
        client.close()


def print_summary(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    mode = "DRY RUN" if result.get("dryRun") else "APPLIED"
    print(f"[{mode}] projectId={result.get('projectId')}")
    for item in result.get("adminConfigChanges", []):
        identifier = item.get("id") or item.get("role")
        print(f"- {item['collection']}: {item['action']} {identifier}")
    for item in result.get("projectMemberChanges", result.get("projectMembers", [])):
        print(f"- project_members: {item.get('action', 'planned')} {item['role']} {item.get('nodeScope')}")
    if result.get("loginAccounts"):
        print("Login demo accounts:")
        for account in result["loginAccounts"]:
            print(f"- {account['username']} / {account['password']} -> {account['defaultPath']}")


def main() -> None:
    args = parse_args()
    roles = selected_roles(args.roles)
    if args.dry_run:
        result = build_plan(roles, args.project_id)
        result["dryRun"] = True
        result["projectMemberChanges"] = [
            {"collection": "project_members", "action": "planned", "role": item["role"], "nodeScope": item["nodeScope"]}
            for item in result["projectMembers"]
        ]
        result.pop("adminConfigPayload", None)
        result.pop("projectMembers", None)
        print_summary(result, args.json)
        return

    if not args.mongo_url:
        raise SystemExit("AICHECK_MONGO_URL or --mongo-url is required unless --dry-run is used.")
    result = sync_mongo(args.mongo_url, args.db, roles, args.project_id)
    result["loginAccounts"] = build_plan(roles, args.project_id)["loginAccounts"]
    print_summary(result, args.json)


if __name__ == "__main__":
    main()
