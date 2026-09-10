#!/usr/bin/env bash
# 本機工作台後端：當前程式碼 + PostgreSQL 持久化。
#
# 為什麼要它：原先 4180／4181 兩個進程用 AICHECK_SQLITE_DISABLE=true 且不接資料庫，
# 狀態全在記憶體。這帶來兩個問題——想更新程式就得重啟，一重啟當天的操作資料全沒；
# 而且沒有任何整體匯出接口，資料只能留在那個進程裡拿不出來。
#
# 這個腳本改成接本機 PostgreSQL：重啟不再丟資料，程式更新和資料保留不再互斥。
#
# 用法（倉庫根目錄）：
#   bash backend/scripts/run_lab_api.sh              # 預設 4186 埠
#   AICHECK_LAB_PORT=4186 bash backend/scripts/run_lab_api.sh
#
# 首次使用需先建庫並套用遷移：
#   createdb aicheck_lab_workbench
#   cd backend && .venv/bin/python -m scripts.migrate_backend \
#     --database-url postgresql://$USER@127.0.0.1:5432/aicheck_lab_workbench
#
# 前端指到這裡：
#   VITE_API_PROXY_TARGET=http://127.0.0.1:4186 pnpm exec vite --mode live --port 4397
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/backend"

PORT="${AICHECK_LAB_PORT:-4186}"
DB="${AICHECK_LAB_DATABASE_URL:-postgresql://${USER}@127.0.0.1:5432/aicheck_lab_workbench}"

export AICHECK_DATABASE_URL="$DB"
export DATABASE_URL="$DB"
export AICHECK_SQLITE_DISABLE=true
export AICHECK_ENABLE_DEMO_DATA=true
export AICHECK_ENABLE_COMPATIBILITY_MOCKS=true
export AICHECK_WORKSTATIONS_ENABLED=true
# 認證沿用原工作台的設定：要求登入、不開發用權杖。
export AICHECK_REQUIRE_AUTH="${AICHECK_REQUIRE_AUTH:-true}"
export AICHECK_ALLOW_DEV_TOKENS="${AICHECK_ALLOW_DEV_TOKENS:-false}"

exec .venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port "$PORT"
