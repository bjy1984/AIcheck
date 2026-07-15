#!/bin/sh
set -eu

action="${1:-verify}"
connect_address="${AICHECK_TLS_CONNECT_ADDRESS:-127.0.0.1:443}"
server_name="${AICHECK_TLS_SERVER_NAME:-39.108.128.107}"
minimum_validity="${AICHECK_TLS_MIN_VALIDITY_SECONDS:-172800}"
proxy_container="${AICHECK_TLS_PROXY_CONTAINER:-aicheck-tls-proxy}"
certificate="$(mktemp)"
trap 'rm -f "$certificate"' EXIT INT TERM

case "$action" in
  verify|reload) ;;
  *)
    echo "usage: $0 {verify|reload}" >&2
    exit 2
    ;;
esac

if [ "$action" = "reload" ]; then
  docker exec "$proxy_container" nginx -t
  docker exec "$proxy_container" nginx -s reload
fi

openssl s_client \
  -connect "$connect_address" \
  -servername "$server_name" \
  -verify_ip "$server_name" \
  -verify_return_error \
  -showcerts </dev/null 2>/dev/null \
  | openssl x509 -out "$certificate"

openssl x509 -in "$certificate" -noout -checkend "$minimum_validity"
not_after="$(openssl x509 -in "$certificate" -noout -enddate | cut -d= -f2-)"
fingerprint="$(openssl x509 -in "$certificate" -noout -fingerprint -sha256 | cut -d= -f2-)"
curl -ksSf "https://${connect_address}/" -H "Host: ${server_name}" -o /dev/null

printf '{"ok":true,"action":"%s","serverName":"%s","notAfter":"%s","sha256Fingerprint":"%s","minimumValiditySeconds":%s}\n' \
  "$action" "$server_name" "$not_after" "$fingerprint" "$minimum_validity"
