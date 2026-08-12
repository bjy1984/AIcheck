#!/usr/bin/env bash
set -euo pipefail

if [ "${AICHECK_MIGRATION_WRITERS_FROZEN:-}" != "true" ]; then
  echo "refusing inconsistent snapshot: stop all source and target writers, then set AICHECK_MIGRATION_WRITERS_FROZEN=true" >&2
  exit 64
fi

backend_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
repo_root="$(cd "$backend_dir/.." && pwd -P)"
source_root="${AICHECK_MIGRATION_SOURCE_ROOT:-$repo_root}"
output_root="${AICHECK_MIGRATION_OUTPUT_ROOT:-$backend_dir/data-migrations}"
ssh_host="${AICHECK_MIGRATION_SSH_HOST:-dev-bjy}"
remote_root="${AICHECK_MIGRATION_REMOTE_ROOT:-/home/dev-bjy/aicheck-migrations}"
migration_id="${AICHECK_MIGRATION_ID:-migration-$(date -u +%Y%m%dT%H%M%SZ)}"
python_bin="${AICHECK_MIGRATION_PYTHON:-python3}"
pg_bin="${AICHECK_MIGRATION_PG_BIN:-/opt/homebrew/opt/postgresql@16/bin}"
pg_host="${AICHECK_MIGRATION_PG_HOST:-}"
pg_port="${AICHECK_MIGRATION_PG_PORT:-}"
pg_user="${AICHECK_MIGRATION_PG_USER:-}"

git_commit="$(git -C "$repo_root" rev-parse HEAD)"
archive="$output_root/$migration_id.tar.gz"
checksum="$archive.sha256"
remote_dir="$remote_root/$migration_id"

pg_args=()
export_args=(--pg-bin "$pg_bin")
if [ -n "$pg_host" ]; then pg_args+=(--host "$pg_host"); export_args+=(--pg-host "$pg_host"); fi
if [ -n "$pg_port" ]; then pg_args+=(--port "$pg_port"); export_args+=(--pg-port "$pg_port"); fi
if [ -n "$pg_user" ]; then pg_args+=(--username "$pg_user"); export_args+=(--pg-user "$pg_user"); fi

echo "==> source preflight"
source_major="$("$pg_bin/psql" "${pg_args[@]}" -d postgres -Atc 'show server_version_num' | cut -c1-2)"
[ "$source_major" = "16" ] || { echo "source PostgreSQL must be 16" >&2; exit 67; }
source_databases="$("$pg_bin/psql" "${pg_args[@]}" -d postgres -Atc "select string_agg(datname,',' order by datname) from pg_database where datname in ('aicheck','litellm','workflow')")"
[ "$source_databases" = "aicheck,litellm,workflow" ] || { echo "source database inventory mismatch" >&2; exit 67; }
active_writers="$("$pg_bin/psql" "${pg_args[@]}" -d postgres -Atc "select count(*) from pg_stat_activity where pid <> pg_backend_pid() and datname in ('aicheck','litellm','workflow') and state <> 'idle'")"
[ "$active_writers" = "0" ] || { echo "source still has active database sessions" >&2; exit 67; }

echo "==> export $migration_id from $source_root"
"$python_bin" "$backend_dir/scripts/data_migration.py" export \
  --migration-id "$migration_id" \
  --source-root "$source_root" \
  --output-root "$output_root" \
  --git-commit "$git_commit" \
  "${export_args[@]}"

echo "==> upload through $ssh_host"
"$python_bin" "$backend_dir/scripts/data_migration.py" upload \
  --migration-id "$migration_id" \
  --archive "$archive" \
  --checksum "$checksum" \
  --ssh-host "$ssh_host" \
  --remote-root "$remote_root"

scp "$backend_dir/scripts/restore_data_migration.sh" \
  "$backend_dir/scripts/data_migration.py" \
  "$backend_dir/scripts/verify_restored_migration.py" \
  "$ssh_host:$remote_dir/"

echo "==> destructive restore on $ssh_host"
ssh "$ssh_host" 'writers=$(docker ps --format "{{.Names}}" | grep -E "^aicheck-(api|litellm|workflow|.*worker)$" || true); if [ -n "$writers" ]; then docker stop $writers >/dev/null; fi'
ssh "$ssh_host" \
  "bash '$remote_dir/restore_data_migration.sh' --migration-id '$migration_id' --archive '$remote_dir/$migration_id.tar.gz' --checksum '$remote_dir/$migration_id.tar.gz.sha256' --writers-frozen --confirm-replace"

echo "==> deploy API code with persistent file mounts"
AICHECK_DEPLOY_HOST="$ssh_host" bash "$backend_dir/scripts/deploy_to_server.sh" --backend

echo "==> automated restored-data acceptance"
ssh "$ssh_host" "LC_ALL=en_US.utf8 python3 '$remote_dir/verify_restored_migration.py' --bundle-root '$remote_dir/$migration_id' --data-root '/home/dev-bjy/aicheck-data/files' --receipt '$remote_dir/receipts/restore-receipt.json'"

echo "==> migration complete: $migration_id"
