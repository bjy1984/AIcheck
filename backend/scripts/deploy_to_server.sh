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

HOST="${AICHECK_DEPLOY_HOST:-dev-bjy}"
REMOTE_HOME=/home/dev-bjy
SERVER_DATA_ROOT="${AICHECK_SERVER_DATA_ROOT:-$REMOTE_HOME/aicheck-data}"
# 网关对外端口（安全组放行的是 8081；改端口时这里要跟着改）
GATEWAY_PORT="${GATEWAY_PORT:-8081}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
MODE="${1:-all}"

# backend/data/visual_extraction_pages 是被误提交的 OCR 页面图产物（1106 个 PNG，
# 约 550MB）。部署不需要它，剔除后包体从 557MB 降到 3.5MB。
sync_backend() {
  echo "==> 打包后端（HEAD=${COMMIT}）"
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
    set -eo pipefail
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

  echo "==> 重建 API 镜像并重建容器"
  # 启动后轮询 /api/readyz 而不是固定 sleep：启动耗时随数据量与迁移内容变化，
  # 写死秒数迟早等不及。实测踩过两次——容器已 Up 但仍在初始化，验证直接报 502
  # 「就绪检查未通过」，而服务其实好好的。
  # 凭证一律从 /home/dev-bjy 下的 600 权限文件读，不写进仓库、不进命令行。
  # 传法用 docker --env-file 而非 shell 的 source：凭证里含特殊字符，
  # source 会把它们当 shell 语法解析（实测报过 command not found）。
  # env-file 按 KEY=VALUE 原样读取，不做任何展开。
  # 必须 rm + run，不能 docker restart：restart 重启的是既有容器实例，它绑定在
  # 旧镜像层上，新构建的镜像根本不会被采用。这个坑真实发生过——镜像 15:09 构建，
  # 容器还是 07:09 那个实例，代码更新静默失效，验证却全绿（因为验的是健康检查，
  # 不是新行为）。
  ssh "$HOST" "
    set -eo pipefail
    cd $REMOTE_HOME/AIcheck/backend
    docker build -q -f Dockerfile.server -t aicheck-api:local . >/dev/null
    python3 /home/dev-bjy/build-runtime-env.py
    docker run --rm --network aicheck-net --env-file /home/dev-bjy/aicheck-runtime.env \
      aicheck-api:local python scripts/migrate_backend.py | tail -1
    docker rm -f aicheck-api >/dev/null 2>&1 || true
    docker run -d --name aicheck-api --network aicheck-net --restart unless-stopped \
      -v $SERVER_DATA_ROOT/files/output:/app/output \
      -v $SERVER_DATA_ROOT/files/rules:/app/rules:ro \
      --env-file /home/dev-bjy/aicheck-runtime.env \
      -p 127.0.0.1:8000:8000 \
      aicheck-api:local uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 >/dev/null
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
      sleep 5
      curl -s --max-time 10 http://127.0.0.1:${GATEWAY_PORT}/api/readyz | grep -q ready.:true && break
    done
  "
  # 确认容器真的换成了新代码，而不是又跑起旧实例
  echo "==> 校验容器代码与本地一致"
  ssh "$HOST" "
    docker exec aicheck-api python -c \"
import hashlib, pathlib
print('容器内 routes.py:', hashlib.sha256(pathlib.Path('/app/apps/api/routes.py').read_bytes()).hexdigest()[:16])
\"
  "
  local_hash=$(LC_ALL=C LANG=C shasum -a 256 "$REPO_ROOT/backend/apps/api/routes.py" | cut -c1-16)
  echo "  本地 routes.py:   $local_hash"
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
  ssh "$HOST" GATEWAY_PORT="$GATEWAY_PORT" 'bash -s' <<'REMOTE_VERIFY'
    set -e
    ready=$(curl -s --max-time 15 http://127.0.0.1:${GATEWAY_PORT}/api/readyz)
    echo "  readyz: $ready"
    echo "$ready" | grep -q "\"ready\":true" || { echo "  就绪检查未通过"; exit 1; }
    echo "$ready" | grep -q "\"authRequired\":true" || { echo "  警告：认证未开启"; exit 1; }
    code=$(curl -s --max-time 10 -o /dev/null -w "%{http_code}" http://127.0.0.1:${GATEWAY_PORT}/)
    echo "  前端首页: HTTP $code"
    [ "$code" = "200" ] || exit 1
    # 口令从 /home/dev-bjy/aicheck-secrets.env 读（600，仓库路径外），不硬编码。
    # 顺带断言弱口令必须被拒——防止有人把口令改回「用户名=口令」而无人察觉。
    tc=$(PYTHONIOENCODING=utf-8 python3 - <<'PROBE_PY'
import json, pathlib, sys, urllib.request, urllib.error, os

BASE = "http://127.0.0.1:" + os.environ["GATEWAY_PORT"]
creds = {}
secrets = pathlib.Path("/home/dev-bjy/aicheck-secrets.env")
if secrets.exists():
    for line in secrets.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip().strip('"').strip("'")

def login(user, password):
    req = urllib.request.Request(
        BASE + "/api/auth/login",
        data=json.dumps({"username": user, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())

def password_for(role):
    return creds.get("AICHECK_BOOTSTRAP_PASSWORD_" + role.upper())

for role in ("inspection", "contractor"):
    pw = password_for(role)
    if not pw:
        print(f"  凭证缺失：{role}（/home/dev-bjy/aicheck-secrets.env）", file=sys.stderr)
        sys.exit(1)
    if login(role, pw).get("code") != 0:
        print(f"  登录失败：{role}", file=sys.stderr)
        sys.exit(1)
    if login(role, role).get("code") == 0:
        print(f"  弱口令回退：{role} 的口令等于用户名", file=sys.stderr)
        sys.exit(1)

print("  登录: 通过（弱口令已拒）", file=sys.stderr)
print(login("contractor", password_for("contractor")).get("data", {}).get("token", ""))
PROBE_PY
    ) || exit 1

    # 行为探针：健康检查全绿并不代表新代码生效（部署过一次旧容器实例才发现）。
    # 挑一条本轮修复的、行为可判定的规则实测——施工方不得读 AI 判定理由（O-1）。
    probe=$(curl -s --max-time 10 \
      http://127.0.0.1:${GATEWAY_PORT}/api/projects/P-2026-HDCP-001/inspection/nodes/24/ai-runs \
      -H "Authorization: Bearer $tc" | python3 -c "import json,sys;print(json.load(sys.stdin).get(\"code\"))")
    if [ "$probe" = "403" ]; then
      echo "  行为探针(O-1 施工方读 AI 判定): 403 已拦截"
    else
      echo "  行为探针失败：施工方读 AI 判定返回 ${probe}（期望 403）——新代码可能没生效"
      exit 1
    fi
    # 业务链探针：断言内容对不对，而不只是接口通不通。
    # 上面的健康检查与行为探针只能证明「服务活着、权限没塌」；这一轮线上找到的
    # 问题全是 200 + 单测全绿，只有真去看返回内容才暴露（预览地址取回 404、
    # 表格列序错乱、失败运行说不出原因）。探针把那些手工核对固定下来。
    pw=$(grep "^AICHECK_BOOTSTRAP_PASSWORD_INSPECTION=" /home/dev-bjy/aicheck-secrets.env \
         | cut -d= -f2- | tr -d "\"'"'"'")
    docker cp "$(docker inspect aicheck-api --format '{{.Id}}'):/app/scripts/business_chain_probe.py" \
      /tmp/probe.py >/dev/null 2>&1 || true
    docker exec -e PYTHONPATH=/app -e AICHECK_PROBE_PASSWORD="$pw" -w /app aicheck-api \
      python scripts/business_chain_probe.py --base-url http://127.0.0.1:8000 || {
        echo "  业务链探针未通过——新代码可能引入了内容层回归"
        exit 1
      }
    docker ps --filter name=aicheck- --format "  {{.Names}}  {{.Status}}"
REMOTE_VERIFY
}

case "$MODE" in
  --backend)  sync_backend ;;
  --frontend) sync_frontend ;;
  *)          sync_backend; sync_frontend ;;
esac
verify
echo "==> 部署完成（${COMMIT}）"
