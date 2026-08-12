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

git_commit="$(git -C "$repo_root" rev-parse HEAD)"
archive="$output_root/$migration_id.tar.gz"
checksum="$archive.sha256"
remote_dir="$remote_root/$migration_id"

echo "==> export $migration_id from $source_root"
"$python_bin" "$backend_dir/scripts/data_migration.py" export \
  --migration-id "$migration_id" \
  --source-root "$source_root" \
  --output-root "$output_root" \
  --git-commit "$git_commit"

echo "==> upload through $ssh_host"
"$python_bin" "$backend_dir/scripts/data_migration.py" upload \
  --migration-id "$migration_id" \
  --archive "$archive" \
  --checksum "$checksum" \
  --ssh-host "$ssh_host" \
  --remote-root "$remote_root"

scp "$backend_dir/scripts/restore_data_migration.sh" \
  "$backend_dir/scripts/data_migration.py" \
  "$ssh_host:$remote_dir/"

echo "==> destructive restore on $ssh_host"
ssh "$ssh_host" \
  "bash '$remote_dir/restore_data_migration.sh' --migration-id '$migration_id' --archive '$remote_dir/$migration_id.tar.gz' --checksum '$remote_dir/$migration_id.tar.gz.sha256' --writers-frozen --confirm-replace"

echo "==> deploy API code with persistent file mounts"
AICHECK_DEPLOY_HOST="$ssh_host" bash "$backend_dir/scripts/deploy_to_server.sh" --backend

echo "==> migration complete: $migration_id"
