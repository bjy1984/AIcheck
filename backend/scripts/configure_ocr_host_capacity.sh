#!/usr/bin/env bash
set -euo pipefail

SERVICE_USER="${AICHECK_SERVICE_USER:-dev-bjy}"
SERVICE_GROUP="${AICHECK_SERVICE_GROUP:-${SERVICE_USER}}"
CACHE_PATH="${AICHECK_OCR_CACHE_HOST_PATH:-/data/aicheck/ocr-cache}"
SWAP_PATH="${AICHECK_SWAP_PATH:-/data/aicheck.swap}"
SWAP_SIZE="${AICHECK_SWAP_SIZE:-8G}"
SUDO_BIN="${SUDO_BIN:-sudo}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This capacity setup is only supported on the Linux OCR host." >&2
  exit 2
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "Service user does not exist: ${SERVICE_USER}" >&2
  exit 2
fi

${SUDO_BIN} install -d -m 0770 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" "${CACHE_PATH}"

if [[ ! -f "${SWAP_PATH}" ]]; then
  if command -v fallocate >/dev/null 2>&1; then
    ${SUDO_BIN} fallocate -l "${SWAP_SIZE}" "${SWAP_PATH}"
  else
    ${SUDO_BIN} dd if=/dev/zero of="${SWAP_PATH}" bs=1M count=8192 status=progress
  fi
fi
${SUDO_BIN} chmod 0600 "${SWAP_PATH}"

if ! ${SUDO_BIN} /sbin/blkid "${SWAP_PATH}" 2>/dev/null | grep -q 'TYPE="swap"'; then
  ${SUDO_BIN} /sbin/mkswap "${SWAP_PATH}" >/dev/null
fi
if ! grep -qF "${SWAP_PATH}" /proc/swaps; then
  ${SUDO_BIN} /sbin/swapon "${SWAP_PATH}"
fi
if ! grep -qE "^[[:space:]]*${SWAP_PATH//\//\\/}[[:space:]]" /etc/fstab; then
  printf '%s none swap sw 0 0\n' "${SWAP_PATH}" | ${SUDO_BIN} tee -a /etc/fstab >/dev/null
fi

printf 'vm.swappiness=10\n' | ${SUDO_BIN} tee /etc/sysctl.d/99-aicheck-ocr.conf >/dev/null
${SUDO_BIN} /sbin/sysctl -p /etc/sysctl.d/99-aicheck-ocr.conf >/dev/null

echo "OCR cache: ${CACHE_PATH}"
df -h / "${CACHE_PATH}"
echo "Swap:"
cat /proc/swaps
echo "vm.swappiness=$(cat /proc/sys/vm/swappiness)"
