#!/usr/bin/env bash
set -euo pipefail

: "${AICHECK_REMOTE_HOST:?set AICHECK_REMOTE_HOST}"
: "${AICHECK_REMOTE_USER:=root}"
: "${AICHECK_REMOTE_PORT:=22}"
: "${AICHECK_LOCAL_OCR_TUNNEL_PORT:=18010}"
: "${AICHECK_LOCAL_EMBEDDING_TUNNEL_PORT:=17997}"

exec ssh \
  -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new \
  -p "$AICHECK_REMOTE_PORT" \
  -L "127.0.0.1:${AICHECK_LOCAL_OCR_TUNNEL_PORT}:127.0.0.1:8010" \
  -L "127.0.0.1:${AICHECK_LOCAL_EMBEDDING_TUNNEL_PORT}:127.0.0.1:7997" \
  "${AICHECK_REMOTE_USER}@${AICHECK_REMOTE_HOST}"
