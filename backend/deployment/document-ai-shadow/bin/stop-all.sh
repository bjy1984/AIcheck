#!/usr/bin/env bash
set -euo pipefail
BASE=/usrdata/aicheck-document-ai
if [[ "$(id -u)" != "0" ]]; then
  echo "stop-all.sh must run as root" >&2
  exit 1
fi
"$BASE/venv-control/bin/supervisorctl" -c "$BASE/config/supervisord.conf" shutdown
for _ in $(seq 1 20); do
  if [[ ! -f "$BASE/state/supervisord.pid" ]] || ! kill -0 "$(cat "$BASE/state/supervisord.pid")" 2>/dev/null; then
    rm -f "$BASE/state/supervisord.pid" "$BASE/state/supervisor.sock"*
    exit 0
  fi
  sleep 1
done
echo "Supervisor did not stop within 20 seconds" >&2
exit 1
