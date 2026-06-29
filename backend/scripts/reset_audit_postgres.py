from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.db.repository import repo
from scripts.create_roles import apply_role_bootstrap_to_state, resolve_role_passwords, selected_roles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset a local/audit PostgreSQL database to the AIcheck seed state and bootstrap role accounts."
    )
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL"), help="PostgreSQL URL.")
    parser.add_argument("--roles", default="admin,inspection,contractor,ndt,owner,fde")
    parser.add_argument("--project-id", default=os.getenv("AICHECK_DEFAULT_PROJECT_ID", "P-2026-HDCP-001"))
    parser.add_argument("--yes", action="store_true", help="Required to reset persisted data.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.yes:
        raise SystemExit("Refusing to reset PostgreSQL without --yes.")
    if not args.database_url:
        raise SystemExit("--database-url or AICHECK_DATABASE_URL is required.")

    roles = selected_roles(args.roles)
    repo.reset()
    repo.configure_sync_postgres(args.database_url)
    if repo.sync_postgres is None:
        raise SystemExit("Failed to connect to PostgreSQL.")
    repo.ensure_postgres_schema()
    apply_role_bootstrap_to_state(
        roles,
        args.project_id,
        passwords=resolve_role_passwords(roles),
        rotate_passwords=True,
    )
    repo.flush_to_sync_postgres()
    print(f"Reset PostgreSQL seed state and bootstrapped roles: {', '.join(roles)}")


if __name__ == "__main__":
    main()
