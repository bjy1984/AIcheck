from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.db.repository import IDEMPOTENCY_COLLECTION, SINGLETON_COLLECTIONS, STATE_COLLECTIONS, repo
from libs.db.seed import PROJECT_ID
from scripts.create_roles import (
    build_plan,
    load_password_overrides,
    resolve_role_passwords,
    selected_roles,
    validate_strong_passwords,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset a local/audit MongoDB database to the AIcheck seed state and bootstrap role accounts."
    )
    parser.add_argument("--mongo-url", default=os.getenv("AICHECK_MONGO_URL"), help="MongoDB URL.")
    parser.add_argument("--db", default=os.getenv("AICHECK_MONGO_DB", "aicheck"), help="MongoDB database name.")
    parser.add_argument(
        "--roles",
        default="admin,inspection,contractor,ndt,owner,fde",
        help="Comma-separated roles to bootstrap after resetting the seed.",
    )
    parser.add_argument("--project-id", default=os.getenv("AICHECK_DEFAULT_PROJECT_ID", PROJECT_ID))
    parser.add_argument("--password-file", help="JSON file mapping role or username to password.")
    parser.add_argument(
        "--allow-weak-passwords",
        action="store_true",
        help="Allow default/demo passwords. Do not use for live audit.",
    )
    parser.add_argument("--yes", action="store_true", help="Required confirmation for destructive reset.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    return parser.parse_args()


def reset_state_with_roles(roles: list[str], project_id: str, passwords: dict[str, str]) -> dict[str, Any]:
    repo.reset()
    plan = build_plan(roles, project_id, passwords=passwords, show_passwords=False)
    repo.state["users"] = plan["authUsers"]
    repo.state["roles"] = plan["authRoles"]
    repo.state["project_members"] = plan["projectMembers"]
    repo.state["admin_config"] = plan["adminConfigPayload"]
    repo.state["idempotency"] = {}
    return plan


def main() -> int:
    args = parse_args()
    if not args.yes:
        raise SystemExit("Refusing to reset MongoDB without --yes.")
    if not args.mongo_url:
        raise SystemExit("--mongo-url or AICHECK_MONGO_URL is required.")

    roles = selected_roles(args.roles)
    passwords = resolve_role_passwords(roles, load_password_overrides(args.password_file))
    if not args.allow_weak_passwords:
        validate_strong_passwords(roles, passwords)

    os.environ["AICHECK_MONGO_URL"] = args.mongo_url
    os.environ["AICHECK_MONGO_DB"] = args.db
    plan = reset_state_with_roles(roles, args.project_id, passwords)
    repo.sync_mongo = None
    repo.flush_to_sync_mongo()
    if repo.sync_mongo is None:
        raise SystemExit("Failed to connect to MongoDB.")

    summary = {
        "database": args.db,
        "projectId": args.project_id,
        "roles": roles,
        "collections": sorted([*STATE_COLLECTIONS.values(), *SINGLETON_COLLECTIONS.values(), IDEMPOTENCY_COLLECTION]),
        "users": len(plan["authUsers"]),
        "projectMembers": len(plan["projectMembers"]),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"Reset {args.db}: users={summary['users']} projectMembers={summary['projectMembers']} "
            f"collections={len(summary['collections'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
