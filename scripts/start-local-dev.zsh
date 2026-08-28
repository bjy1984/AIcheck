#!/bin/zsh
set -u

SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
LOG_DIR="${AICHECK_DEV_LOG_DIR:-$REPO_ROOT/tmp/dev-server-logs}"
# 可覆盖：测试用它指向密闭的空文件，避免被开发者本机 .env 里的
# AICHECK_TASK_DISPATCH=celery 之类影响断言（0827 实测就是这么翻的）。
ENV_FILE="${AICHECK_DEV_ENV_FILE:-$BACKEND_DIR/.env}"

BACKEND_PORT="${AICHECK_DEV_BACKEND_PORT:-8000}"
FRONTEND_PORT="${AICHECK_DEV_FRONTEND_PORT:-4000}"
BACKEND_LOG="$LOG_DIR/backend.log"
MINERU_WORKER_LOG="$LOG_DIR/mineru-worker.log"
REDIS_LOG="$LOG_DIR/redis.log"
CELERY_LOG="$LOG_DIR/celery.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
CELERY_QUEUES="business.light,llm.remote"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }
log() { print "[$(timestamp)] $*"; }
truthy() { [[ "${1:l}" == "true" || "$1" == "1" || "${1:l}" == "yes" ]]; }

load_backend_env() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
  fi
  export AICHECK_DATABASE_URL="${AICHECK_DEV_DATABASE_URL:-postgresql:///aicheck}"
  export AICHECK_MINERU_EXECUTION_MODE="postgres"
  export AICHECK_MINIO_ENDPOINT="${AICHECK_DEV_MINIO_ENDPOINT:-}"
  export AICHECK_REQUIRE_OBJECT_STORAGE="${AICHECK_DEV_REQUIRE_OBJECT_STORAGE:-false}"
}

pid_on_port() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -n 1
}

pid_is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid="$(<"$pid_file")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

BACKEND_HEALTHZ_URL="http://127.0.0.1:$BACKEND_PORT/api/healthz"

wait_for_url() {
  local url="$1" name="$2"
  local attempts="${3:-90}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name 已就绪：$url"
      return 0
    fi
    sleep 0.5
  done
  log "$name 未通过健康检查：$url"
  return 1
}

backend_has_postgres_mineru() {
  curl -fsS "$BACKEND_HEALTHZ_URL" 2>/dev/null \
    | "$BACKEND_DIR/.venv/bin/python" -c "import json, sys; body=json.load(sys.stdin); data=body.get('data') or {}; worker=data.get('mineruWorker') or {}; raise SystemExit(0 if worker.get('required') is True else 1)" \
      >/dev/null 2>&1
}

ensure_postgres() {
  if pg_isready -q -d "$AICHECK_DATABASE_URL" 2>/dev/null; then
    log "PostgreSQL 已就绪。"
    return 0
  fi
  log "PostgreSQL 未就绪，尝试启动本机服务…"
  if command -v brew >/dev/null 2>&1; then
    brew services start postgresql@16 >/dev/null 2>&1 \
      || brew services start postgresql@15 >/dev/null 2>&1 \
      || brew services start postgresql >/dev/null 2>&1 \
      || true
  fi
  local i
  for i in {1..30}; do
    pg_isready -q -d "$AICHECK_DATABASE_URL" 2>/dev/null && return 0
    sleep 0.5
  done
  log "错误：PostgreSQL 不可用。"
  return 1
}

redis_ready() {
  redis-cli -u "${AICHECK_REDIS_URL:-redis://127.0.0.1:6379/0}" ping 2>/dev/null \
    | grep -q '^PONG$'
}

start_redis() {
  if redis_ready; then
    log "Redis 已就绪。"
    return 0
  fi
  if ! command -v redis-server >/dev/null 2>&1; then
    log "错误：未找到 redis-server。"
    return 1
  fi
  local redis_port
  redis_port="$($BACKEND_DIR/.venv/bin/python - <<'PY'
import os
from urllib.parse import urlparse
url = urlparse(os.getenv("AICHECK_REDIS_URL", "redis://127.0.0.1:6379/0"))
if url.hostname not in {"127.0.0.1", "localhost", "::1"}:
    raise SystemExit(1)
print(url.port or 6379)
PY
)" || {
    log "错误：配置的 Redis 不是本机地址，请先启动对应服务。"
    return 1
  }
  (
    nohup redis-server --bind 127.0.0.1 --port "$redis_port" --save "" --appendonly no \
      > "$REDIS_LOG" 2>&1 &!
    print $! > "$LOG_DIR/redis.pid"
  )
  local i
  for i in {1..30}; do
    redis_ready && { log "Redis 已就绪。"; return 0; }
    sleep 0.25
  done
  log "错误：Redis 未就绪，请查看 $REDIS_LOG"
  return 1
}

start_backend() {
  local pid="$(pid_on_port "$BACKEND_PORT")"
  if [[ -n "$pid" ]]; then
    if backend_has_postgres_mineru; then
      log "后端已运行且 MinerU PostgreSQL 模式生效，PID: $pid"
      return 0
    fi
    log "后端未加载 MinerU PostgreSQL 模式，重启 PID: $pid"
    kill "$pid" 2>/dev/null || true
    local i
    for i in {1..20}; do
      [[ -z "$(pid_on_port "$BACKEND_PORT")" ]] && break
      sleep 0.25
    done
  fi
  (
    cd "$BACKEND_DIR" || exit 1
    nohup .venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port "$BACKEND_PORT" > "$BACKEND_LOG" 2>&1 &!
    print $! > "$LOG_DIR/backend.pid"
  )
}

start_mineru_worker() {
  if pid_is_running "$LOG_DIR/mineru-worker.pid"; then
    log "MinerU worker 已运行，PID: $(<"$LOG_DIR/mineru-worker.pid")"
    return 0
  fi
  (
    cd "$BACKEND_DIR" || exit 1
    nohup .venv/bin/python -m apps.mineru_worker.main > "$MINERU_WORKER_LOG" 2>&1 &!
    print $! > "$LOG_DIR/mineru-worker.pid"
  )
}

start_celery_worker() {
  [[ "${AICHECK_TASK_DISPATCH:-disabled}" == "celery" ]] || return 0
  if pid_is_running "$LOG_DIR/celery.pid"; then
    log "Celery worker 已运行，PID: $(<"$LOG_DIR/celery.pid")"
    return 0
  fi
  (
    cd "$BACKEND_DIR" || exit 1
    nohup .venv/bin/celery -A apps.worker.celery_app:celery_app worker \
      --loglevel=INFO --queues="$CELERY_QUEUES" --concurrency=2 \
      --hostname='aicheck-local@%h' > "$CELERY_LOG" 2>&1 &!
    print $! > "$LOG_DIR/celery.pid"
  )
}

wait_for_celery_worker() {
  [[ "${AICHECK_TASK_DISPATCH:-disabled}" == "celery" ]] || return 0
  local i
  for i in {1..60}; do
    if pid_is_running "$LOG_DIR/celery.pid" && grep -q 'ready\.' "$CELERY_LOG" 2>/dev/null; then
      log "Celery worker 已就绪：$CELERY_QUEUES"
      return 0
    fi
    sleep 0.5
  done
  log "Celery worker 未就绪，请查看 $CELERY_LOG"
  return 1
}

wait_for_mineru_worker() {
  local i
  for i in {1..60}; do
    if (
      cd "$BACKEND_DIR" || exit 1
      .venv/bin/python -c "import os, psycopg; c=psycopg.connect(os.environ['AICHECK_DATABASE_URL']); r=c.execute(\"select 1 from service_heartbeats where service_role='mineru-worker' and last_seen_at >= now() - interval '30 seconds' limit 1\").fetchone(); c.close(); raise SystemExit(0 if r else 1)" >/dev/null 2>&1
    ); then
      log "MinerU worker 心跳已就绪。"
      return 0
    fi
    sleep 0.5
  done
  log "MinerU worker 未产生新鲜心跳，请查看 $MINERU_WORKER_LOG"
  return 1
}

start_frontend() {
  local pid="$(pid_on_port "$FRONTEND_PORT")"
  if [[ -n "$pid" ]]; then
    log "前端已运行，PID: $pid"
    return 0
  fi
  (
    cd "$FRONTEND_DIR" || exit 1
    export VITE_API_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT"
    nohup zsh -lc 'if command -v pnpm >/dev/null 2>&1; then exec pnpm run dev:live; else exec corepack pnpm run dev:live; fi' > "$FRONTEND_LOG" 2>&1 &!
    print $! > "$LOG_DIR/frontend.pid"
  )
}

dry_run() {
  print "AICHECK_MINERU_EXECUTION_MODE=postgres"
  # Redis/Celery 只在显式选择 celery 派发时才打印：本地默认是 postgres 直连模式，
  # 不依赖这两样——测试据此断言 dry-run 输出里不出现它们（test_local_startup_script）。
  if [[ "${AICHECK_TASK_DISPATCH:-disabled}" == "celery" ]]; then
    print "Redis: ${AICHECK_REDIS_URL:-redis://127.0.0.1:6379/0}"
    print "Celery queues: $CELERY_QUEUES"
  fi
  print "backend: .venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port $BACKEND_PORT"
  print "backend healthz: $BACKEND_HEALTHZ_URL"
  print "backend log: $BACKEND_LOG ($LOG_DIR/backend.pid)"
  print "mineru: .venv/bin/python -m apps.mineru_worker.main -> $MINERU_WORKER_LOG ($LOG_DIR/mineru-worker.pid)"
  print "frontend: pnpm run dev:live (preflight $BACKEND_HEALTHZ_URL) -> $FRONTEND_LOG ($LOG_DIR/frontend.pid)"
}

require_backend_ready() {
  if wait_for_url "$BACKEND_HEALTHZ_URL" "后端" 180; then
    return 0
  fi
  log "错误：后端未在 :$BACKEND_PORT 就绪，已跳过前端启动。"
  log "请检查：$BACKEND_LOG"
  log "手动启动示例：cd backend && .venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port $BACKEND_PORT"
  return 1
}

main() {
  mkdir -p "$LOG_DIR"
  load_backend_env
  if truthy "${AICHECK_DEV_DRY_RUN:-false}"; then
    dry_run
    return 0
  fi
  touch "$BACKEND_LOG" "$MINERU_WORKER_LOG" "$FRONTEND_LOG"
  ensure_postgres || return 1
  start_redis || return 1
  start_backend
  require_backend_ready || return 1
  touch "$CELERY_LOG" "$REDIS_LOG"
  start_celery_worker
  wait_for_celery_worker || return 1
  start_mineru_worker
  wait_for_mineru_worker || true
  start_frontend
  wait_for_url "http://127.0.0.1:$FRONTEND_PORT/" "前端" || true
  log "后端：http://127.0.0.1:$BACKEND_PORT"
  log "后端健康检查：$BACKEND_HEALTHZ_URL"
  log "前端：http://127.0.0.1:$FRONTEND_PORT"
  log "日志：$LOG_DIR"
  if ! truthy "${AICHECK_DEV_NO_FOLLOW:-false}"; then
    tail -n 20 "$BACKEND_LOG" "$MINERU_WORKER_LOG" "$FRONTEND_LOG"
    tail -f "$BACKEND_LOG" "$MINERU_WORKER_LOG" "$FRONTEND_LOG"
  fi
}

main "$@"
