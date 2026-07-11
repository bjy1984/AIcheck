#!/usr/bin/env bash
set -euo pipefail

BASE=/usrdata/aicheck-document-ai
ENV_FILE="$BASE/config/document-ai.env"

if [[ ! -r "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE" >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
if [[ -z "${DOCUMENT_AI_API_KEY:-}" ]]; then
  echo "DOCUMENT_AI_API_KEY is not configured" >&2
  exit 1
fi

if [[ "$(id -u)" != "0" ]]; then
  echo "start-all.sh must run as root; model programs are dropped to aicheck-docai by Supervisor" >&2
  exit 1
fi
export DOCUMENT_AI_API_KEY

if [[ -f "$BASE/state/supervisord.pid" ]] && kill -0 "$(cat "$BASE/state/supervisord.pid")" 2>/dev/null; then
  "$BASE/venv-control/bin/supervisorctl" -c "$BASE/config/supervisord.conf" status
  exit 0
fi
exec "$BASE/venv-control/bin/supervisord" -c "$BASE/config/supervisord.conf"
