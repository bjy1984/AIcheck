#!/bin/sh
set -eu

action="${1:-verify}"
deploy_dir="${AICHECK_DEPLOY_DIR:?AICHECK_DEPLOY_DIR is required}"
env_file="${AICHECK_ENV_FILE:-/etc/aicheck/production.env}"
receipt_dir="${AICHECK_BACKUP_RECEIPT_DIR:-/home/dev-bjy/aicheck-data/backup-receipts}"
compose_project="${AICHECK_COMPOSE_PROJECT_NAME:-aicheck}"
backup_compose_file="${AICHECK_BACKUP_COMPOSE_FILE:-docker-compose.backup.yml}"
backup_mode="${AICHECK_BACKUP_MODE:-offsite}"

compose() {
  docker compose --env-file "$env_file" --project-directory "$deploy_dir" --project-name "$compose_project" \
    -f "$deploy_dir/docker-compose.deploy.yml" \
    -f "$deploy_dir/docker-compose.production-data.yml" \
    -f "$deploy_dir/$backup_compose_file" "$@"
}

pgbackrest() {
  compose exec -T \
    -e PGBACKREST_PG1_USER="${AICHECK_POSTGRES_USER:-aicheck}" \
    -e PGBACKREST_PG1_DATABASE="${AICHECK_POSTGRES_DB:-aicheck}" \
    postgres aicheck-pgbackrest-entrypoint restore-agent pgbackrest "$@"
}

case "$action" in
  init)
    pgbackrest --stanza=aicheck stanza-create
    pgbackrest --stanza=aicheck check
    ;;
  full|diff|incr)
    pgbackrest --stanza=aicheck --type="$action" backup
    pgbackrest --stanza=aicheck expire
    ;;
  logical)
    [ "$backup_mode" != "local_only" ] || {
      echo "logical upload requires the offsite backup mode" >&2
      exit 2
    }
    compose --profile backup run --rm backup-agent /opt/aicheck-backup/logical_backup.py
    ;;
  restore-drill)
    started_epoch="$(date +%s)"
    canary_lsn="$(compose exec -T postgres psql --no-psqlrc -U "${AICHECK_POSTGRES_USER:-aicheck}" -d "${AICHECK_POSTGRES_DB:-aicheck}" -Atqc 'SELECT pg_switch_wal()')"
    database_inventory="$(compose exec -T postgres psql --no-psqlrc -U "${AICHECK_POSTGRES_USER:-aicheck}" -d "${AICHECK_POSTGRES_DB:-aicheck}" -Atqc "SELECT COALESCE(json_agg(datname ORDER BY datname), '[]'::json) FROM pg_database WHERE datallowconn AND NOT datistemplate")"
    pgbackrest --stanza=aicheck check
    AICHECK_RESTORE_CANARY_LSN="$canary_lsn" AICHECK_RESTORE_STARTED_EPOCH="$started_epoch" AICHECK_RESTORE_EXPECTED_DATABASES_JSON="$database_inventory" \
      compose --profile restore run --rm \
        -e AICHECK_RESTORE_CANARY_LSN="$canary_lsn" \
        -e AICHECK_RESTORE_STARTED_EPOCH="$started_epoch" \
        -e AICHECK_RESTORE_EXPECTED_DATABASES_JSON="$database_inventory" \
        restore-drill /opt/aicheck-backup/restore_drill.sh
    ;;
  verify)
    mkdir -p "$receipt_dir"
    pgbackrest --stanza=aicheck --output=json info > "$receipt_dir/pgbackrest-info.json.tmp"
    mv "$receipt_dir/pgbackrest-info.json.tmp" "$receipt_dir/pgbackrest-info.json"
    if [ "$backup_mode" = "local_only" ]; then
      compose exec -T -u 0 postgres /opt/aicheck-backup/verify_local_backup.py \
        --pgbackrest-info /var/lib/aicheck-backup/receipts/pgbackrest-info.json \
        --restore-receipt /var/lib/aicheck-backup/receipts/latest-restore-drill.json \
        --output /var/lib/aicheck-backup/receipts/local-backup-readiness.json
    else
      compose --profile backup run --rm backup-agent /opt/aicheck-backup/verify_backup_readiness.py \
        --pgbackrest-info /var/lib/aicheck-backup/receipts/pgbackrest-info.json \
        --logical-receipt /var/lib/aicheck-backup/receipts/latest-logical-backup.json \
        --replication-receipt /var/lib/aicheck-backup/receipts/minio-replication-receipt.json \
        --restore-receipt /var/lib/aicheck-backup/receipts/latest-restore-drill.json \
        --output /var/lib/aicheck-backup/receipts/backup-recoverability.json
    fi
    ;;
  *)
    echo "usage: $0 {init|full|diff|incr|logical|restore-drill|verify}" >&2
    exit 2
    ;;
esac
