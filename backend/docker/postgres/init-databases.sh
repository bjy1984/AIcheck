#!/bin/sh
set -eu

litellm_db="${LITELLM_POSTGRES_DB:-litellm}"
workflow_db="${WORKFLOW_POSTGRES_DB:-workflow}"

create_database_if_missing() {
  db_name="$1"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v db_name="$db_name" \
    -v owner_name="$POSTGRES_USER" <<'EOSQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'owner_name')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name')\gexec
EOSQL
}

create_database_if_missing "$litellm_db"
create_database_if_missing "$workflow_db"
