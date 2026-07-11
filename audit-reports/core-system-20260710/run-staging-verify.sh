#!/bin/sh
set -eu

ROOT=${AICHECK_AUDIT_ROOT:-/home/dev-bjy/aicheck-audit-staging}
OUTPUT=${AICHECK_AUDIT_OUTPUT:-verify-full.json}

docker exec aicheck-audit-api sh -lc '
  python scripts/verify_deployment.py \
    --api-base http://127.0.0.1:8000 \
    --ocr-base http://ocr-service:8010 \
    --skip-litellm \
    --project-id P-2026-HDCP-001 \
    --roles admin,inspection,contractor,ndt,owner,fde \
    --strict-production \
    --write-probes \
    --ocr-object-probe \
    --review-run-probe \
    --review-run-wait-seconds 180 \
    --timeout 120 \
    --qwen-official-probe \
    --json
' >"$ROOT/$OUTPUT" 2>"$ROOT/$OUTPUT.err"
