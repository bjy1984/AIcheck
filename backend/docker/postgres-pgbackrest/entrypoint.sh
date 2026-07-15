#!/bin/sh
set -eu

secret_dir="${AICHECK_BACKUP_SECRET_DIR:-/run/secrets/aicheck-backup}"

load_secret() {
  variable="$1"
  file_name="$2"
  file_path="${secret_dir}/${file_name}"
  if [ -r "$file_path" ]; then
    value="$(cat "$file_path")"
    export "$variable=$value"
  fi
}

# pgBackRest archive-push runs in the PostgreSQL container, so only repository
# credentials are made available here. Application containers never receive them.
load_secret PGBACKREST_REPO1_S3_KEY pgbackrest_s3_key
load_secret PGBACKREST_REPO1_S3_KEY_SECRET pgbackrest_s3_key_secret
load_secret PGBACKREST_REPO1_CIPHER_PASS pgbackrest_cipher_pass

if [ "$#" -gt 0 ] && [ "$1" = "backup-agent" ]; then
  shift
  exec "$@"
fi

if [ "$#" -gt 0 ] && [ "$1" = "restore-agent" ]; then
  shift
  exec gosu postgres "$@"
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
