#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 --migration-id ID --archive PATH --checksum PATH --writers-frozen --confirm-replace" >&2
  exit 64
}

migration_id=""
archive=""
checksum=""
confirmed=false
writers_frozen=false
postgres_container="${AICHECK_POSTGRES_CONTAINER:-aicheck-postgres}"
api_container="${AICHECK_API_CONTAINER:-aicheck-api}"
postgres_user="aicheck"
data_root="${AICHECK_SERVER_DATA_ROOT:-/home/dev-bjy/aicheck-data}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --migration-id) migration_id="${2:-}"; shift 2 ;;
    --archive) archive="${2:-}"; shift 2 ;;
    --checksum) checksum="${2:-}"; shift 2 ;;
    --confirm-replace) confirmed=true; shift ;;
    --writers-frozen) writers_frozen=true; shift ;;
    *) usage ;;
  esac
done

if [ "$confirmed" != true ]; then
  echo "destructive restore requires --confirm-replace" >&2
  exit 64
fi
if [ "$writers_frozen" != true ]; then
  echo "restore requires --writers-frozen after every source and target writer is stopped" >&2
  exit 64
fi
if [ -z "$migration_id" ] || [ -z "$archive" ] || [ -z "$checksum" ]; then
  usage
fi
case "$migration_id" in
  *[!A-Za-z0-9_-]*) echo "invalid migration ID" >&2; exit 64 ;;
esac

archive_dir="$(cd "$(dirname "$archive")" && pwd -P)"
archive_path="$archive_dir/$(basename "$archive")"
checksum_path="$(cd "$(dirname "$checksum")" && pwd -P)/$(basename "$checksum")"
expected_archive="$migration_id.tar.gz"
if [ "$(basename "$archive_path")" != "$expected_archive" ]; then
  echo "archive name does not match migration ID" >&2
  exit 65
fi
if [ ! -f "$archive_path" ] || [ ! -f "$checksum_path" ]; then
  echo "archive or checksum is missing" >&2
  exit 66
fi

(cd "$archive_dir" && sha256sum -c "$(basename "$checksum_path")")
tar -tzf "$archive_path" >/dev/null
python3 - "$archive_path" "$archive_dir" "$migration_id" <<'PY'
import pathlib
import sys
import tarfile

archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2]).resolve()
migration_id = sys.argv[3]
with tarfile.open(str(archive), "r:gz") as source:
    for member in source.getmembers():
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != migration_id:
            raise SystemExit("unsafe archive member: " + member.name)
        if member.issym() or member.islnk() or member.isdev():
            raise SystemExit("archive links and devices are not allowed: " + member.name)
    source.extractall(str(destination))
PY
bundle_root="$archive_dir/$migration_id"

python3 - "$bundle_root" "$migration_id" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
migration_id = sys.argv[2]
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
if manifest.get("schemaVersion") != "aicheck-data-migration-v1":
    raise SystemExit("invalid migration manifest schema")
if manifest.get("migrationId") != migration_id:
    raise SystemExit("manifest migration ID mismatch")
if (root / "READY").read_text(encoding="utf-8").strip() != migration_id:
    raise SystemExit("bundle READY marker mismatch")
if set(manifest.get("databases", [])) != {"aicheck", "litellm", "workflow"}:
    raise SystemExit("database inventory mismatch")
PY
python3 "$(dirname "$0")/data_migration.py" validate-bundle --bundle-root "$bundle_root"

postgres_major="$(docker exec "$postgres_container" psql -U "$postgres_user" -d postgres -Atc "show server_version_num" | cut -c1-2)"
if [ "$postgres_major" != "16" ]; then
  echo "target PostgreSQL major version must be 16, got $postgres_major" >&2
  exit 67
fi

receipt_dir="$archive_dir/receipts"
mkdir -p "$receipt_dir"
docker exec "$postgres_container" pg_dumpall -U "$postgres_user" --globals-only > "$receipt_dir/target-before-globals.sql"
for database in aicheck litellm workflow; do
  docker exec "$postgres_container" pg_dump -U "$postgres_user" -d "$database" -Fc > "$receipt_dir/target-before-$database.dump"
done
docker inspect "$api_container" > "$receipt_dir/target-api-before.json"
docker stop "$api_container" >/dev/null

docker exec "$postgres_container" psql -U "$postgres_user" -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('aicheck','litellm','workflow') AND pid <> pg_backend_pid();"
for database in aicheck litellm workflow; do
  docker exec "$postgres_container" dropdb -U "$postgres_user" --if-exists --force "$database"
  docker exec "$postgres_container" createdb -U "$postgres_user" --owner="$postgres_user" "$database"
done

docker exec -i "$postgres_container" psql -U "$postgres_user" -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DO $block$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT rolname FROM pg_roles
    WHERE rolname <> 'aicheck' AND rolname <> 'postgres' AND rolname NOT LIKE 'pg\_%'
  LOOP
    EXECUTE format('DROP ROLE IF EXISTS %I', item.rolname);
  END LOOP;
END
$block$;
SQL

filtered_globals="$receipt_dir/globals.filtered.sql"
awk '
  $0 == "CREATE ROLE aicheck;" { next }
  $0 ~ /^ALTER ROLE aicheck WITH / { next }
  { print }
' "$bundle_root/globals.sql" > "$filtered_globals"
docker exec -i "$postgres_container" psql -U "$postgres_user" -d postgres -v ON_ERROR_STOP=1 < "$filtered_globals"

# The existing cluster's bootstrap role cannot lose SUPERUSER, but its password
# verifier must still match the source so the restored application credentials work.
python3 "$(dirname "$0")/data_migration.py" bootstrap-role-password-sql \
  --globals "$bundle_root/globals.sql" --role "$postgres_user" \
  | docker exec -i "$postgres_container" psql -U "$postgres_user" -d postgres -v ON_ERROR_STOP=1

for database in aicheck litellm workflow; do
  docker exec -i "$postgres_container" pg_restore -U "$postgres_user" -d "$database" \
    --clean --if-exists --no-owner < "$bundle_root/databases/$database.dump"
done

next_files="$data_root/files-$migration_id"
mkdir -p "$data_root"
if [ -e "$next_files" ]; then
  echo "staging file directory already exists: $next_files" >&2
  exit 68
fi
mkdir "$next_files"
cp -a "$bundle_root/files/." "$next_files/"
chown -R 1001:1001 "$next_files"
if [ -e "$data_root/files" ]; then
  mv "$data_root/files" "$data_root/files-before-$migration_id"
fi
mv "$next_files" "$data_root/files"

python3 - "$receipt_dir/restore-receipt.json" "$migration_id" <<'PY'
import datetime
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
    "schemaVersion": "aicheck-data-restore-receipt-v1",
    "migrationId": sys.argv[2],
    "databaseRestore": "complete",
    "fileRestore": "complete",
    "applicationRestart": "pending",
    "completedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, indent=2) + "\n", encoding="utf-8")
PY

echo "restore complete; API remains stopped until deployment and verification"
