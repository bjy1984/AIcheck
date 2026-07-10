from __future__ import annotations

import argparse
import json
import os
from typing import Any

from libs.db.repository import repo
from libs.security.auth import hash_password


def migrate_users(users: list[dict[str, Any]], *, apply: bool) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for user in users:
        username = str(user.get("username") or user.get("id") or "unknown")
        password_hash = str(user.get("passwordHash") or "")
        legacy_password = str(user.get("password") or "")
        next_action = "unchanged"
        source_password = ""
        if password_hash.startswith("plain:"):
            source_password = password_hash.removeprefix("plain:")
            next_action = "migrated_plain_hash"
        elif not password_hash and legacy_password:
            source_password = legacy_password
            next_action = "migrated_legacy_password"
        elif not password_hash:
            next_action = "disabled_missing_password"
        elif legacy_password:
            next_action = "removed_legacy_password"

        if apply and next_action != "unchanged":
            if source_password:
                user["passwordHash"] = hash_password(source_password)
                user["mustChangePassword"] = True
            elif next_action == "disabled_missing_password":
                user["status"] = "停用"
                user["mustChangePassword"] = True
            user.pop("password", None)
            user["authVersion"] = int(user.get("authVersion") or 0) + 1
        actions.append(
            {
                "userId": user.get("id"),
                "username": username,
                "action": next_action,
                "requiresPasswordChange": next_action.startswith("migrated_"),
            }
        )
    return {
        "total": len(users),
        "changed": sum(1 for item in actions if item["action"] != "unchanged"),
        "disabled": sum(1 for item in actions if item["action"] == "disabled_missing_password"),
        "actions": actions,
        "applied": apply,
        "secretsIncluded": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate AIcheck authentication users away from legacy plain passwords.")
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")
    repo.configure_sync_postgres(args.database_url)
    if repo.sync_postgres is None:
        raise SystemExit("psycopg is required and the PostgreSQL database must be reachable")
    repo.ensure_postgres_schema()
    repo.load_from_sync_postgres()
    report = migrate_users(repo.state.get("users", []), apply=not args.dry_run)
    if not args.dry_run:
        repo.add_audit("迁移认证账号", "SecurityMigration", "auth-users-v1")
        repo.flush_to_sync_postgres()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        mode = "DRY RUN" if args.dry_run else "APPLIED"
        print(f"[{mode}] users={report['total']} changed={report['changed']} disabled={report['disabled']}")
        for item in report["actions"]:
            print(f"- {item['username']}: {item['action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
