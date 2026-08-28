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
    # 运行时 env 生成器以仓库版本为准，覆盖服务器上可能被手改过的副本。
    # 此前它只存在于服务器，部署逻辑有一半没有版本管理。
    cp deploy/build_runtime_env.py /home/dev-bjy/build-runtime-env.py
    python3 /home/dev-bjy/build-runtime-env.py
    docker run --rm --network aicheck-net --env-file /home/dev-bjy/aicheck-runtime.env \
      aicheck-api:local python scripts/migrate_backend.py | tail -1
    # 蓝绿切换：新容器先起在旁边，自己 readyz 绿了再顶替旧的。
    #
    # 原先是 rm -f 之后再 run，中间必然有一段真空：新容器要加载三万行的
    # routes.py 再起 uvicorn，实测约 60 秒。2026-08-14 20:56 就是这么造成
    # 一分钟 502 的，而脚本这边照样报「部署完成」——因为它等的是最终 readyz
    # 变绿，看不见中间那一分钟。**部署方自己看不到的停机，才是最容易长期存在的。**
    # 端口在两次部署之间轮换：旧容器占着 8000 时新容器用 8001，反之亦然。
    # 让新容器完全不映射端口更简单，但那样切换后就没有直连后端的入口了，
    # 而 business_chain_probe 等工具都在用它——静默拿掉一个调试入口，
    # 下次有人查问题时会以为是服务坏了。
    # 按**宿主侧**端口判断。docker port 的输出形如 `8000/tcp -> 127.0.0.1:8001`，
    # 直接 grep 8000 会命中容器侧那个 8000，于是永远选 8001——当前正好在 8001
    # 时就撞端口。实测报过 "Bind for 127.0.0.1:8001 failed: port is already allocated"。
    if docker port aicheck-api 2>/dev/null | grep -q "127.0.0.1:8000"; then
      NEXT_PORT=8001
    else
      NEXT_PORT=8000
    fi
    docker rm -f aicheck-api-next >/dev/null 2>&1 || true
    docker run -d --name aicheck-api-next --network aicheck-net \
      -p 127.0.0.1:\$NEXT_PORT:8000 \
      -v $SERVER_DATA_ROOT/files/output:/app/output \
      -v $SERVER_DATA_ROOT/files/rules:/app/rules:ro \
      --env-file /home/dev-bjy/aicheck-runtime.env \
      aicheck-api:local uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 >/dev/null
    # 直接问新容器自己，不经网关——此刻网关还指着旧容器
    ready=no
    for i in \$(seq 1 60); do
      sleep 3
      if docker exec aicheck-api-next python -c \
        \"import urllib.request,sys; sys.exit(0 if b'ready' in urllib.request.urlopen('http://127.0.0.1:8000/api/readyz',timeout=5).read() else 1)\" \
        >/dev/null 2>&1; then ready=yes; break; fi
    done
    if [ \"\$ready\" != yes ]; then
      echo '新容器未能就绪，保留旧容器继续服务' >&2
      docker logs aicheck-api-next --tail 30 >&2 || true
      docker rm -f aicheck-api-next >/dev/null 2>&1 || true
      exit 1
    fi
    # 顶替：旧容器让出名字与端口，新容器接手，随即 reload 网关。
    # nginx 的 proxy_pass 写的是字面主机名，只在启动时解析一次并缓存，
    # 所以改完名字必须 reload 才会重新解析——不 reload 会一直打向已死的旧 IP。
    docker rm -f aicheck-api >/dev/null 2>&1 || true
    docker rename aicheck-api-next aicheck-api
    docker update --restart unless-stopped aicheck-api >/dev/null 2>&1 || true
    docker exec aicheck-web nginx -s reload >/dev/null 2>&1 || docker restart aicheck-web >/dev/null
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
      sleep 2
      curl -s --max-time 10 http://127.0.0.1:${GATEWAY_PORT}/api/readyz | grep -q ready.:true && break
    done
    echo \"    直连后端端口：127.0.0.1:\$NEXT_PORT（蓝绿轮换，每次部署会换）\"
  "
  # worker 也要跟着换。这一段是补上的洞：脚本此前只重建 API，
  # 四个 worker 从创建那天起就没动过——跑的是当天的镜像、当天的 env-file。
  # 症状不会是报错，是**任务默默按旧逻辑执行**：2026-08-15 查 MinerU 时发现
  # ocr-remote worker 里 AICHECK_MINERU_API_KEY / AICHECK_OCR_DEFAULT_PROVIDER
  # 全是空的——配置早已写进 runtime.env，容器却还揣着三天前那份。
  #
  # 与 API 不同，worker 不做蓝绿：它们没有入口流量，任务在 Redis 队列里等着，
  # 重建期间只是没人消费，恢复后照常取走。用 rm + run 而非 restart，
  # 理由与上面 API 那段完全相同——restart 绑定旧镜像层。
  # 本地 OCR 服务（印章读字）。镜像与 API 不同：带 paddle，2.4 GB，
  # 构建一次约十分钟，所以只在镜像不存在或代码变了时重建，其余情况只重启容器。
  #
  # 模型 360 MB 挂在宿主机 /home/dev-bjy/aicheck-ocr-models，只读；
  # paddlex 缓存必须另给一个**可写**卷——它启动时要在缓存目录下建 temp，
  # 挂只读会让 import paddlex 直接抛 PermissionError，报错长得像模型坏了。
  echo "==> 重建本地 OCR 服务（印章）"
  ssh "$HOST" "
    set -eo pipefail
    cd $REMOTE_HOME/AIcheck/backend
    # **每次都构建**，不要写成「镜像不存在才构建」。
    # 那样写过一版，当天就踩到：给 ocr-service 加了 /internal/ocr/seal-read，
    # 部署跑完一切正常，调用返回 404——容器跑的还是加端点之前的镜像。
    # 层缓存会让没变化时只花几秒；省这几秒的代价是代码更新静默失效。
    docker build -q -f Dockerfile.ocr -t aicheck-ocr:local \
      --build-arg AICHECK_PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
      --build-arg AICHECK_APT_DEBIAN_MIRROR=http://mirrors.aliyun.com/debian \
      --build-arg AICHECK_APT_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security \
      --build-arg AICHECK_OCR_REQUIREMENTS=requirements-ocr-core.txt . >/dev/null
    mkdir -p /home/dev-bjy/aicheck-paddlex-cache && chmod 777 /home/dev-bjy/aicheck-paddlex-cache
    docker rm -f aicheck-ocr-service >/dev/null 2>&1 || true
    docker run -d --name aicheck-ocr-service --network aicheck-net --restart unless-stopped \
      -v /home/dev-bjy/aicheck-ocr-models/official_models:/models/official_models:ro \
      -v /home/dev-bjy/aicheck-paddlex-cache:/paddlex-cache \
      --env-file /home/dev-bjy/aicheck-runtime.env \
      -e AICHECK_PADDLEX_MODEL_CACHE=/paddlex-cache \
      -e PADDLE_PDX_CACHE_HOME=/paddlex-cache \
      -e AICHECK_SEAL_DET_MODEL_DIR=/models/official_models/PP-OCRv4_server_seal_det \
      -e AICHECK_SEAL_REC_MODEL_DIR=/models/official_models/PP-OCRv4_server_rec \
      -e AICHECK_SEAL_LAYOUT_MODEL_DIR=/models/official_models/PP-DocLayoutV3 \
      -e AICHECK_SEAL_DOC_ORI_MODEL_DIR=/models/official_models/PP-LCNet_x1_0_doc_ori \
      -e AICHECK_SEAL_DOC_UNWARP_MODEL_DIR=/models/official_models/UVDoc \
      -e AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE=true \
      -e AICHECK_OCR_SUBPROCESS_PYTHON=/usr/local/bin/python \
      -e AICHECK_OCR_OFFLINE_ONLY=true -e AICHECK_OCR_DISABLE_NETWORK=true \
      aicheck-ocr:local uvicorn apps.ocr_service.main:app --host 0.0.0.0 --port 8010 >/dev/null
    sleep 15
    if [ \"\$(docker inspect aicheck-ocr-service --format '{{.State.Status}}')\" != running ]; then
      echo '    OCR 服务未起来' >&2; docker logs aicheck-ocr-service --tail 20 >&2; exit 1
    fi
    # 容器起来了 ≠ 新代码进去了。直接探印章端点存不存在——
    # 404 说明跑的是旧镜像，这种情况部署必须失败，而不是报「完成」。
    code=\$(docker exec aicheck-ocr-service python -c \"
import urllib.request, urllib.error
req = urllib.request.Request('http://127.0.0.1:8010/internal/ocr/seal-read', data=b'x', method='POST')
try:
    print(urllib.request.urlopen(req, timeout=30).status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print(0)
\")
    if [ \"\$code\" = 404 ] || [ \"\$code\" = 0 ]; then
      echo \"    印章端点不可用（HTTP \$code）——容器可能跑着旧镜像\" >&2; exit 1
    fi
    echo \"    OCR 服务已重建，印章端点在（HTTP \$code）\"
  "

  echo "==> 重建 worker 容器（同镜像同 env-file）"
  ssh "$HOST" "
    set -eo pipefail
    recreate_worker() {
      name=\$1; shift
      docker rm -f \$name >/dev/null 2>&1 || true
      docker run -d --name \$name --network aicheck-net --restart unless-stopped \
        --env-file /home/dev-bjy/aicheck-runtime.env aicheck-api:local \
        sh -c \"celery -A apps.worker.celery_app.celery_app worker --loglevel=INFO --prefetch-multiplier=1 \$*\" >/dev/null
    }
    # -B 内嵌 beat：compose 权威（docker-compose.deploy.yml）一直这么声明，
    # 部署脚本此前把 -B 弄丢了——auto_review 的四个 60 秒周期任务
    # （consume/scan/start/finalize）因此从不执行，「每上传自动分析」的事件
    # 在 outbox 里永远无人消费（2026-08-29 审计实锤）。
    recreate_worker aicheck-worker-business --concurrency=2 -B --schedule=/tmp/auto-review-celerybeat-schedule -Q business.light,ocr.parse_document,ocr.recognize_seals,knowledge.slice,knowledge.embed,inspection.ai_recheck,llm.compare,export.package
    recreate_worker aicheck-worker-cpu-heavy --concurrency=1 -Q cpu.heavy
    recreate_worker aicheck-worker-llm --concurrency=1 -Q llm.remote
    recreate_worker aicheck-worker-ocr-remote --concurrency=1 -Q ocr.remote
    sleep 5
    for c in aicheck-worker-business aicheck-worker-cpu-heavy aicheck-worker-llm aicheck-worker-ocr-remote; do
      state=\$(docker inspect \$c --format '{{.State.Status}}' 2>/dev/null || echo missing)
      if [ \"\$state\" != running ]; then
        echo \"    worker \$c 未起来（\$state）\" >&2
        docker logs \$c --tail 20 >&2 || true
        exit 1
      fi
    done
    echo '    四个 worker 均已用新镜像重建'
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
  scp -q "$REPO_ROOT/backend/deploy/nginx-default.conf" "$HOST:$REMOTE_HOME/aicheck-nginx.conf"
  echo "==> 发布静态资源"
  # 用 rm+解包而不是替换目录：容器按 inode 绑定挂载，换目录会让它看到空目录
  #
  # tar 的错误不再丢进 /dev/null。曾经因此出过事（2026-08-14）：新 chunk 解开了、
  # index.html 没换掉，dist 里同时躺着两次构建的产物，浏览器照旧加载旧入口。
  # 而部署一路绿灯——它当时只查 `/` 返回 200，而一份陈旧但完整的 index.html
  # 当然是 200。查错了对象的验证比不验证更坏，它会让人停止怀疑。
  ssh "$HOST" "
    set -e
    rm -rf $REMOTE_HOME/aicheck-web/dist/*
    tar xzf $REMOTE_HOME/aicheck-dist.tar.gz -C $REMOTE_HOME/aicheck-web/dist
    cp $REMOTE_HOME/aicheck-nginx.conf $REMOTE_HOME/aicheck-web/conf/default.conf
    docker exec aicheck-web nginx -t >/dev/null 2>&1 && docker exec aicheck-web nginx -s reload >/dev/null 2>&1 || {
      echo "nginx 配置校验失败，保留原配置" >&2; exit 1; }
    docker exec aicheck-web nginx -s reload
  "
  # 验的是「浏览器拿到的 index.html 引用的入口，正是这次构建出来的那个」。
  local expected served
  expected="$(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' "$REPO_ROOT/frontend/dist-pro/index.html" | head -1)"
  [ -n "$expected" ] || { echo "  ✗ 构建产物里没找到入口，无法校验发布是否生效"; exit 1; }
  served="$(ssh "$HOST" "curl -s --max-time 10 http://127.0.0.1:${GATEWAY_PORT}/" \
    | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -1)"
  echo "==> 校验前端入口：本次构建 ${expected}"
  echo "                  线上返回 ${served:-（未找到）}"
  [ "$served" = "$expected" ] || { echo "  ✗ 线上仍是旧入口，静态资源发布未生效"; exit 1; }
  echo "  ✓ 入口一致"

  # 入口一致只证明「传上去的正是刚构建的」，不证明「构建的正是仓库里的」。
  #
  # 2026-08-14 实测：线上跑的 chunk 与本地任何一次构建都对不上，
  # 推荐问题功能在界面上一条都不显示，而入口校验全程报「✓ 一致」——
  # 因为它比对的两端同源。**同源比对不是校验。**
  #
  # 这里改成用源码里的特征串反查线上产物：挑几个只可能来自当前源码的标记，
  # 去构建产物里搜。搜不到就是发布没生效。
  #
  # **标记必须是字符串字面量**（CSS 类名、界面文案），不能用 JS 标识符——
  # 第一版挑了 inspectionOnlyAttentionNodes，压缩时被重命名，校验当场误报
  # 「发布的不是当前源码」。压缩改不掉的只有字面量。
  echo "==> 校验线上产物确实来自当前源码"
  local marker_file marker missing
  missing=0
  for marker_file in \
    "frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue:composer-suggestion" \
    "frontend/src/views/AICheck/Workbench.vue:只看需处理"
  do
    local f="${marker_file%%:*}" m="${marker_file##*:}"
    grep -q "$m" "$REPO_ROOT/$f" 2>/dev/null || continue   # 源码里没有就跳过，不误判
    # 查**服务器实际提供的文件**，不是本地构建目录。
    #
    # 第一版查的是 $REPO_ROOT/frontend/dist-pro/assets/，结果是「源码 → 本地构建」
    # 通过、「本地构建 → 线上」由入口校验通过，两段都绿而中间断了：
    # 2026-08-15 实测线上 chunk 里没有 composer-suggestion，而源码有 9 处引用，
    # 两道校验全程报 ✓。**只要有一段不是在线上量的，整条链就不成立。**
    # 注意别写成 grep -rql：-q 会压掉 -l 的输出，命令永远没结果、校验永远报缺失。
    # 第一版就是这么写的，把一次成功的发布判成了失败。
    if ssh "$HOST" "docker exec aicheck-web sh -c \"grep -rl '$m' /usr/share/nginx/html/assets/ 2>/dev/null | head -1\"" | grep -q .; then
      echo "  ✓ ${m}"
    else
      echo "  ✗ 源码有 ${m}，线上产物里没有——线上跑的不是当前源码" >&2
      missing=1
    fi
  done
  [ "$missing" = 0 ] || exit 1
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
    #
    # 口令用 --env-file 传给容器，不在命令行拼——命令行会进 shell 历史和进程表，
    # 而且远端 heredoc 里手工转义引号极易散架（写这段时就散过一次）。
    grep "^AICHECK_BOOTSTRAP_PASSWORD_INSPECTION=" /home/dev-bjy/aicheck-secrets.env \
      | sed "s/^AICHECK_BOOTSTRAP_PASSWORD_INSPECTION=/AICHECK_PROBE_PASSWORD=/" \
      > /tmp/aicheck-probe.env
    chmod 600 /tmp/aicheck-probe.env
    docker exec --env-file /tmp/aicheck-probe.env -e PYTHONPATH=/app -w /app aicheck-api \
      python scripts/business_chain_probe.py --base-url http://aicheck-web || {
        rm -f /tmp/aicheck-probe.env
        echo "  业务链探针未通过——新代码可能引入了内容层回归"
        exit 1
      }
    rm -f /tmp/aicheck-probe.env

    # 生产拓扑漂移：docker-compose.deploy.yml 名为部署权威，却既不驱动部署
    # 也不描述现状——线上跑着的 aicheck-web 和 aicheck-onlyoffice 曾经压根不在
    # 里面。加服务只是让这份谎言更详细，有东西校验它才让它开始有意义。
    #
    # docker ps 必须在宿主机跑（容器里没有 docker 客户端，也不该有）；
    # 检查脚本本身不连 docker，正是为了能这样拆开跑。
    running=$(docker ps --format "{{.Names}}" | grep "^aicheck-" | paste -sd, -)
    docker exec -e PYTHONPATH=/app -w /app aicheck-api \
      python scripts/compose_drift_check.py --running "$running" || true

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
