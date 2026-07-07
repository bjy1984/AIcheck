#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

: "${AICHECK_REMOTE_HOST:?set AICHECK_REMOTE_HOST}"
: "${AICHECK_REMOTE_USER:=root}"
: "${AICHECK_REMOTE_PORT:=22}"
: "${AICHECK_REMOTE_BASE:=/data/aicheck-ai-services}"
: "${AICHECK_REMOTE_MODELS:=/data/aicheck-models}"
: "${AICHECK_REMOTE_CACHE:=/data/aicheck-cache}"

SSH_TARGET="${AICHECK_REMOTE_USER}@${AICHECK_REMOTE_HOST}"
SSH_OPTS=(-p "$AICHECK_REMOTE_PORT" -o StrictHostKeyChecking=accept-new)
REMOTE_BACKEND="$AICHECK_REMOTE_BASE/backend"

ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "mkdir -p '$REMOTE_BACKEND' '$AICHECK_REMOTE_MODELS' '$AICHECK_REMOTE_CACHE'"

rsync -az --delete \
  -e "ssh -p $AICHECK_REMOTE_PORT -o StrictHostKeyChecking=accept-new" \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'data/' \
  "$BACKEND_DIR/" "$SSH_TARGET:$REMOTE_BACKEND/"

ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "cd '$REMOTE_BACKEND' && docker compose -f docker-compose.remote-ai-services.yml up -d --build"

ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "curl -fsS http://127.0.0.1:8010/healthz >/tmp/aicheck-ocr-health.json && curl -fsS http://127.0.0.1:7997/health >/tmp/aicheck-embedding-health.json && cat /tmp/aicheck-ocr-health.json && printf '\n' && cat /tmp/aicheck-embedding-health.json && printf '\n'"
