#!/usr/bin/env bash
set -euo pipefail
BASE=/usrdata/aicheck-document-ai
if [[ "$(id -u)" != "0" ]]; then
  echo "status.sh must run as root" >&2
  exit 1
fi
exec "$BASE/venv-control/bin/supervisorctl" -c "$BASE/config/supervisord.conf" status
