#!/usr/bin/env bash
# Sync tracked and unignored new files into a dedicated test workspace.
# The test-only image supplies git/zsh; test2 fixtures are included. No accepted failures.
set -euo pipefail
HOST="${AICHECK_DEPLOY_HOST:-aicheck-prod-new}"
IMAGE="${AICHECK_TEST_IMAGE:-aicheck-tests:local}"
BASE_IMAGE="${AICHECK_TEST_BASE_IMAGE:-aicheck-api:local}"
REMOTE_WS="${AICHECK_TEST_WORKSPACE:-/tmp/aicheck-tests-repair}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ "$REMOTE_WS" =~ ^/tmp/aicheck-tests-[a-zA-Z0-9_-]+$ ]] || { echo 'Unsafe test workspace' >&2; exit 2; }
[[ "$IMAGE" =~ ^[a-zA-Z0-9._/:@-]+$ && "$BASE_IMAGE" =~ ^[a-zA-Z0-9._/:@-]+$ ]] || exit 2
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
python3 "$ROOT/backend/scripts/test_workspace.py" manifest "$ROOT" > "$STAGE/manifest"
# A separate bootstrap directory keeps preparation outside the source mirror.
REMOTE_STAGE="$(ssh "$HOST" 'mktemp -d /tmp/aicheck-test-bootstrap.XXXXXXXX')"
[[ "$REMOTE_STAGE" =~ ^/tmp/aicheck-test-bootstrap\.[a-zA-Z0-9]+$ ]] || exit 2
trap 'rm -rf "$STAGE"; ssh "$HOST" "rm -rf -- $REMOTE_STAGE"' EXIT
scp -q "$STAGE/manifest" "$ROOT/backend/scripts/test_workspace.py" "$HOST:$REMOTE_STAGE/"
ssh "$HOST" "set -eu
  test ! -L '$REMOTE_WS'
  docker run --rm -u root -v /tmp:/tmp '$BASE_IMAGE' python '$REMOTE_STAGE/test_workspace.py' prepare '$REMOTE_WS' --manifest '$REMOTE_STAGE/manifest'
  docker run --rm -u root -v '$REMOTE_WS':/ws '$BASE_IMAGE' chown -R \$(id -u):\$(id -g) /ws
"
rsync -a --files-from="$STAGE/manifest" "$ROOT/" "$HOST:$REMOTE_WS/"
# No runtime env-file or production network is passed to test containers.
ssh "$HOST" "set -eu
  docker build -f '$REMOTE_WS/backend/Dockerfile.test' --build-arg AICHECK_TEST_BASE_IMAGE='$BASE_IMAGE' -t '$IMAGE' '$REMOTE_WS/backend'
  mkdir -p '$REMOTE_WS/output' '$REMOTE_WS/tmp' '$REMOTE_WS/backend/ocr_eval/reports'
  docker run --rm -u root -v '$REMOTE_WS':/ws '$IMAGE' sh -c 'chmod -R a+rwX /ws'
"
if [ "$#" = 0 ]; then set -- tests; fi
printf -v PYTEST_ARGS ' %q' "$@"
ssh "$HOST" "docker run --rm -v '$REMOTE_WS':/ws -w /ws/backend '$IMAGE' python -m pytest -q -p no:cacheprovider$PYTEST_ARGS"
