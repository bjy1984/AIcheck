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
# 固定的远端工作区一次只能有一个跑在用：并发调用会互相覆盖源码镜像，
# 症状是 rsync 报 output 目录权限被占，以及一批与改动无关的测试失败。
# macOS 没有 flock，用 mkdir 的原子性做互斥；陈旧锁由持有者 PID 是否还在判断。
LOCK="/tmp/.aicheck-tests-$(printf %s "$REMOTE_WS" | tr -c 'a-zA-Z0-9' _).lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  HOLDER="$(cat "$LOCK/pid" 2>/dev/null || echo '')"
  if [ -n "$HOLDER" ] && kill -0 "$HOLDER" 2>/dev/null; then
    echo "另一个 run_tests_in_container.sh (pid $HOLDER) 正在用 $REMOTE_WS；等它跑完，或换 AICHECK_TEST_WORKSPACE" >&2
    exit 3
  fi
  echo "清理陈旧锁 $LOCK（持有者 ${HOLDER:-未知} 已不在）" >&2
  rm -rf "$LOCK"
  mkdir "$LOCK" || { echo "无法取得工作区锁 $LOCK" >&2; exit 3; }
fi
printf %s "$$" > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$LOCK"' EXIT
python3 "$ROOT/backend/scripts/test_workspace.py" manifest "$ROOT" > "$STAGE/manifest"
# A separate bootstrap directory keeps preparation outside the source mirror.
REMOTE_STAGE="$(ssh "$HOST" 'mktemp -d /tmp/aicheck-test-bootstrap.XXXXXXXX')"
[[ "$REMOTE_STAGE" =~ ^/tmp/aicheck-test-bootstrap\.[a-zA-Z0-9]+$ ]] || exit 2
trap 'rm -rf "$STAGE" "$LOCK"; ssh "$HOST" "rm -rf -- $REMOTE_STAGE"' EXIT
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
# Opt-in only: integration tests otherwise skip with an explicit reason. The DSN must
# name a throwaway database on an isolated network -- never the production one, which
# is why the production network is still never attached here.
EXTRA=""
if [ -n "${AICHECK_TEST_POSTGRES_URL:-}" ]; then
  NET="${AICHECK_TEST_NETWORK:-aicheck-tests-net}"
  [[ "$NET" =~ ^aicheck-tests-[a-zA-Z0-9_-]+$ ]] || { echo 'Test network must be a dedicated aicheck-tests-* network' >&2; exit 2; }
  case "$AICHECK_TEST_POSTGRES_URL" in
    *aicheck-postgres*|*aicheck-net*) echo 'Refusing to point tests at the production database' >&2; exit 2 ;;
  esac
  printf -v EXTRA ' --network %q -e AICHECK_TEST_POSTGRES_URL=%q' "$NET" "$AICHECK_TEST_POSTGRES_URL"
fi
ssh "$HOST" "docker run --rm -v '$REMOTE_WS':/ws -w /ws/backend$EXTRA '$IMAGE' python -m pytest -q -p no:cacheprovider$PYTEST_ARGS"
