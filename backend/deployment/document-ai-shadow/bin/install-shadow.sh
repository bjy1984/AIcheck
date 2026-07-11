#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" != "0" ]]; then
  echo "install-shadow.sh must run as root" >&2
  exit 1
fi

SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE=/usrdata/aicheck-document-ai
SERVICE_USER=aicheck-docai

if [[ -f "$BASE/state/supervisord.pid" ]] && kill -0 "$(cat "$BASE/state/supervisord.pid")" 2>/dev/null; then
  echo "stop the existing Document AI Supervisor before installing" >&2
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$BASE" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
for group in video render; do
  if getent group "$group" >/dev/null 2>&1; then
    usermod -aG "$group" "$SERVICE_USER"
  fi
done

install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 \
  "$BASE/services" "$BASE/config" "$BASE/bin" "$BASE/logs" "$BASE/state" \
  "$BASE/reports" /usrdata/aicheck-cache/document-ai/uploads
chown -R "$SERVICE_USER:$SERVICE_USER" /usrdata/aicheck-cache/document-ai
rm -f "$BASE/state/supervisor.sock" "$BASE/state/supervisord.pid"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/services/"*.py "$BASE/services/"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0640 "$SOURCE_DIR/config/supervisord.conf" "$BASE/config/supervisord.conf"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$SOURCE_DIR/bin/start-all.sh" "$BASE/bin/start-all.sh"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$SOURCE_DIR/bin/stop-all.sh" "$BASE/bin/stop-all.sh"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$SOURCE_DIR/bin/status.sh" "$BASE/bin/status.sh"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$SOURCE_DIR/bin/generate-shadow-manifest.py" "$BASE/bin/generate-shadow-manifest.py"

if [[ ! -f "$BASE/config/document-ai.env" ]]; then
  umask 0077
  printf 'DOCUMENT_AI_API_KEY=%s\n' "$(openssl rand -hex 32)" >"$BASE/config/document-ai.env"
fi
chown "$SERVICE_USER:$SERVICE_USER" "$BASE/config/document-ai.env"
chmod 0600 "$BASE/config/document-ai.env"

"$BASE/venv-control/bin/pip" install --disable-pip-version-check -r "$SOURCE_DIR/requirements-control.txt"
echo "installed Document AI Shadow bundle; API key remains in $BASE/config/document-ai.env"
