#!/usr/bin/env bash
# 起/停一个一次性测试用 PostgreSQL，供整合测试使用。
#
# 为什么需要：77 个整合测试在没有 AICHECK_TEST_POSTGRES_URL 时全部按"环境跳过"处理，
# 其中包括交接提交竞态那三条。2026-09-10 首次真的跑起来就抓出一个生产 bug——
# psycopg 的 connection.info.dsn 不含口令，用它开新连接在需要口令的库上必然失败，
# 交接来源核验因此一路 503。**没跑过的测试不能当成通过。**
#
# 安全边界：独立 docker 网络、不发布端口、数据放 tmpfs、容器 --rm；
# 绝不指向生产库（run_tests_in_container.sh 里另有 DSN 拒绝规则）。
#
#   backend/scripts/start_test_postgres.sh up     # 起库并打印 DSN
#   backend/scripts/start_test_postgres.sh down   # 拆掉容器与网络
#   AICHECK_TEST_POSTGRES_URL="$(backend/scripts/start_test_postgres.sh up --quiet)" \
#     backend/scripts/run_tests_in_container.sh tests
set -euo pipefail
HOST="${AICHECK_DEPLOY_HOST:-aicheck-prod-new}"
NET="${AICHECK_TEST_NETWORK:-aicheck-tests-net}"
NAME="${AICHECK_TEST_PG_CONTAINER:-aicheck-tests-pg}"
IMAGE="${AICHECK_TEST_PG_IMAGE:-pgvector/pgvector:pg16}"
DB="aicheck_test"
USER="postgres"
PASS="testonly"

[[ "$NET" =~ ^aicheck-tests-[a-zA-Z0-9_-]+$ ]] || { echo '测试网络名必须是 aicheck-tests-*' >&2; exit 2; }
[[ "$NAME" =~ ^aicheck-tests-[a-zA-Z0-9_-]+$ ]] || { echo '测试容器名必须是 aicheck-tests-*' >&2; exit 2; }

case "${1:-up}" in
  up)
    ssh "$HOST" "set -eu
      docker network inspect '$NET' >/dev/null 2>&1 || docker network create '$NET' >/dev/null
      if ! docker ps --format '{{.Names}}' | grep -qx '$NAME'; then
        docker rm -f '$NAME' >/dev/null 2>&1 || true
        docker run -d --rm --name '$NAME' --network '$NET' \
          -e POSTGRES_PASSWORD='$PASS' -e POSTGRES_USER='$USER' -e POSTGRES_DB='$DB' \
          --tmpfs /var/lib/postgresql/data '$IMAGE' >/dev/null
        for _ in \$(seq 1 30); do
          docker exec '$NAME' pg_isready -U '$USER' -q && break
          sleep 2
        done
        docker exec '$NAME' psql -U '$USER' -d '$DB' -qc 'CREATE EXTENSION IF NOT EXISTS vector;'
      fi"
    [ "${2:-}" = "--quiet" ] || echo "测试库就绪（独立网络 $NET，未发布端口，数据在 tmpfs）" >&2
    echo "postgresql://$USER:$PASS@$NAME:5432/$DB"
    ;;
  down)
    ssh "$HOST" "docker rm -f '$NAME' >/dev/null 2>&1 || true
      docker network rm '$NET' >/dev/null 2>&1 || true"
    echo "已拆除 $NAME 与 $NET" >&2
    ;;
  *)
    echo "用法: $0 [up [--quiet] | down]" >&2
    exit 2
    ;;
esac
