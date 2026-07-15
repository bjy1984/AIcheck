#!/bin/sh
set -eu

pgdata="${PGDATA:-/var/lib/postgresql/restore-drill}"
canary_lsn="${AICHECK_RESTORE_CANARY_LSN:?AICHECK_RESTORE_CANARY_LSN is required}"
started_epoch="${AICHECK_RESTORE_STARTED_EPOCH:?AICHECK_RESTORE_STARTED_EPOCH is required}"
expected_databases="${AICHECK_EXPECTED_DATABASES:-aicheck,litellm,workflow}"
expected_databases_json="${AICHECK_RESTORE_EXPECTED_DATABASES_JSON:-}"
receipt="${AICHECK_RESTORE_RECEIPT:-/var/lib/aicheck-backup/receipts/latest-restore-drill.json}"
socket_dir="/tmp/aicheck-restore-drill"
port=55432

if [ "$pgdata" != "/var/lib/postgresql/restore-drill" ]; then
  echo "refusing to restore outside the dedicated drill volume" >&2
  exit 1
fi

password_file="${PGPASSWORD_FILE:-/run/secrets/aicheck-backup/postgres_password}"
[ -r "$password_file" ] || { echo "PostgreSQL password file is missing" >&2; exit 1; }
export PGPASSWORD="$(cat "$password_file")"

mkdir -p "$pgdata" "$socket_dir" "$(dirname "$receipt")"
find "$pgdata" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
pgbackrest --stanza=aicheck --pg1-path="$pgdata" restore

pg_ctl -D "$pgdata" -o "-k $socket_dir -p $port -c listen_addresses=''" -w start >/dev/null
cleanup() {
  pg_ctl -D "$pgdata" -m fast -w stop >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

attempt=0
in_recovery=t
while [ "$attempt" -lt 120 ]; do
  in_recovery="$(psql -h "$socket_dir" -p "$port" -U "$PGUSER" -d postgres -Atqc 'SELECT pg_is_in_recovery()')"
  [ "$in_recovery" = "f" ] && break
  attempt=$((attempt + 1))
  sleep 5
done
[ "$in_recovery" = "f" ] || { echo "restore did not finish WAL replay within 10 minutes" >&2; exit 1; }

recovered_lsn="$(psql -h "$socket_dir" -p "$port" -U "$PGUSER" -d postgres -Atqc 'SELECT pg_current_wal_lsn()')"
canary_recovered="$(psql -h "$socket_dir" -p "$port" -U "$PGUSER" -d postgres -Atqc "SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '$canary_lsn'::pg_lsn) >= 0")"
[ "$canary_recovered" = "t" ] || { echo "restored WAL does not include the pre-drill canary LSN" >&2; exit 1; }

database_json="$(psql -h "$socket_dir" -p "$port" -U "$PGUSER" -d postgres -Atqc "SELECT COALESCE(json_agg(datname ORDER BY datname), '[]'::json) FROM pg_database WHERE datallowconn AND NOT datistemplate")"
if [ -n "$expected_databases_json" ]; then
  [ "$(printf '%s' "$expected_databases_json" | jq -c 'sort')" = "$(printf '%s' "$database_json" | jq -c 'sort')" ] \
    || { echo "restored database inventory does not exactly match the source inventory" >&2; exit 1; }
else
  for database in $(printf '%s' "$expected_databases" | tr ',' ' '); do
    printf '%s' "$database_json" | jq -e --arg database "$database" 'index($database) != null' >/dev/null \
      || { echo "restored cluster is missing database $database" >&2; exit 1; }
  done
fi

completed_epoch="$(date +%s)"
rto_seconds=$((completed_epoch - started_epoch))
completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
jq -n \
  --arg completedAt "$completed_at" \
  --arg canaryLsn "$canary_lsn" \
  --arg recoveredLsn "$recovered_lsn" \
  --argjson databases "$database_json" \
  --argjson rtoSeconds "$rto_seconds" \
  '{schemaVersion:"aicheck-restore-drill-receipt-v1",status:"verified",completedAt:$completedAt,rpoSeconds:0,rtoSeconds:$rtoSeconds,canaryLsn:$canaryLsn,recoveredLsn:$recoveredLsn,databases:$databases,isolatedVolume:true}' > "$receipt.tmp"
mv "$receipt.tmp" "$receipt"
cat "$receipt"
