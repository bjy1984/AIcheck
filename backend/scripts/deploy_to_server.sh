#!/usr/bin/env bash
# 把当前 HEAD 同步部署到目标服务器（39.108.65.148，经 47.120.63.210 跳板）。
#
# 为什么不是直接 git push：
#   目标机没装 git（无 sudo 装不了），也没有 git-receive-pack，ssh push 走不通；
#   GitHub 在该网络不可达。所以用 git archive 导出 HEAD 的精确树 → 传输 →
#   服务器侧解包并 commit 进本地 git 仓库，版本仍然可追溯、可 diff、可回滚。
#
# 镜像通道：docker hub / ghcr 均不可达，走 docker.m.daocloud.io 镜像源。
#
# 用法：
#   bash scripts/deploy_to_server.sh            # 全量（代码 + 前端）
#   bash scripts/deploy_to_server.sh --backend  # 只更新后端并重启 API
#   bash scripts/deploy_to_server.sh --frontend # 只更新前端静态资源
set -euo pipefail

HOST=aicheck-prod-new
REMOTE_HOME=/home/dev-bjy
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
MODE="${1:-all}"

# backend/data/visual_extraction_pages 是被误提交的 OCR 页面图产物（1106 个 PNG，
# 约 550MB）。部署不需要它，剔除后包体从 557MB 降到 3.5MB。
sync_backend() {
  echo "==> 打包后端（HEAD=$COMMIT）"
  git -C "$REPO_ROOT" archive --format=tar HEAD backend openapi > "$STAGE/src.tar"
  python3 - "$STAGE/src.tar" "$STAGE/src.tar.gz" <<'PY'
import sys, tarfile
src, dst = sys.argv[1], sys.argv[2]
SKIP = ("backend/data/visual_extraction_pages/",)
with tarfile.open(src) as si, tarfile.open(dst, "w:gz", compresslevel=9) as so:
    for m in si:
        if m.name.startswith(SKIP):
            continue
        so.addfile(m, si.extractfile(m) if m.isfile() else None)
PY
  scp -q "$STAGE/src.tar.gz" "$HOST:$REMOTE_HOME/aicheck-src.tar.gz"

  echo "==> 服务器解包并提交到本地 git 仓库"
  ssh "$HOST" "
    set -e
    cd $REMOTE_HOME
    rm -rf AIcheck/backend AIcheck/openapi
    tar xzf aicheck-src.tar.gz -C AIcheck
    docker run --rm --entrypoint sh -v $REMOTE_HOME:/w -w /w/AIcheck docker.m.daocloud.io/alpine/git:latest -c '
      git config --global --add safe.directory /w/AIcheck
      git config --global user.email deploy@aicheck.local
      git config --global user.name aicheck-deploy
      git add -A
      git commit -q -m \"deploy: $COMMIT\" 2>/dev/null || echo \"（无变更）\"
      git log --oneline -1
    '
    docker run --rm --entrypoint sh -v $REMOTE_HOME:/w docker.m.daocloud.io/alpine/git:latest -c 'chown -R 1001:1001 /w/AIcheck'
  "

  echo "==> 重建 API 镜像并重启"
  ssh "$HOST" "
    set -e
    cd $REMOTE_HOME/AIcheck/backend
    docker build -q -f Dockerfile.server -t aicheck-api:local . >/dev/null
    docker run --rm --network aicheck-net \
      -e AICHECK_DATABASE_URL=postgresql://aicheck:AicheckProd2026@aicheck-postgres:5432/aicheck \
      -e AICHECK_TENANT_ID=TENANT-DEFAULT \
      aicheck-api:local python scripts/migrate_backend.py | tail -1
    docker restart aicheck-api >/dev/null
  "
}

sync_frontend() {
  echo "==> 构建前端"
  (cd "$REPO_ROOT/frontend" && node node_modules/vite/bin/vite.js build --mode pro >/dev/null)
  tar czf "$STAGE/dist.tar.gz" -C "$REPO_ROOT/frontend/dist-pro" .
  scp -q "$STAGE/dist.tar.gz" "$HOST:$REMOTE_HOME/aicheck-dist.tar.gz"
  echo "==> 发布静态资源"
  # 用 rm+解包而不是替换目录：容器按 inode 绑定挂载，换目录会让它看到空目录
  ssh "$HOST" "
    set -e
    rm -rf $REMOTE_HOME/aicheck-web/dist/*
    tar xzf $REMOTE_HOME/aicheck-dist.tar.gz -C $REMOTE_HOME/aicheck-web/dist 2>/dev/null
    docker exec aicheck-web nginx -s reload
  "
}

verify() {
  echo "==> 部署后验证"
  ssh "$HOST" '
    set -e
    ready=$(curl -s --max-time 15 http://127.0.0.1:8090/api/readyz)
    echo "  readyz: $ready"
    echo "$ready" | grep -q "\"ready\":true" || { echo "  就绪检查未通过"; exit 1; }
    echo "$ready" | grep -q "\"authRequired\":true" || { echo "  警告：认证未开启"; exit 1; }
    code=$(curl -s --max-time 10 -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/)
    echo "  前端首页: HTTP $code"
    [ "$code" = "200" ] || exit 1
    login=$(curl -s --max-time 10 -X POST http://127.0.0.1:8090/api/auth/login \
      -H "Content-Type: application/json" -d "{\"username\":\"inspection\",\"password\":\"inspection\"}")
    echo "$login" | grep -q "\"code\": *0" && echo "  登录: 通过" || { echo "  登录失败: $login"; exit 1; }
    docker ps --filter name=aicheck- --format "  {{.Names}}  {{.Status}}"
  '
}

case "$MODE" in
  --backend)  sync_backend ;;
  --frontend) sync_frontend ;;
  *)          sync_backend; sync_frontend ;;
esac
verify
echo "==> 部署完成（$COMMIT）"
