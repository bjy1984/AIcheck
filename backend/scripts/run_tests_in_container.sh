#!/usr/bin/env bash
# 在部署主机的一次性容器里跑后端全量测试。
#
# 为什么需要它：本机装不上 psycopg/temporalio/fitz 这些依赖，pytest 根本起不来；
# 而直接钻进生产的 aicheck-api 容器跑，会把测试代码和改动写进正在服务的容器——
# 2026-09-08 干过一次，只能按镜像逐个文件还原。这个脚本把仓库同步到主机的一个
# 工作目录，用同一个镜像起一个 --rm 容器跑，跑完即弃，碰不到生产。
#
# 用 rsync 增量同步而不是每次 tar+scp：追踪文件有 1.6GB（扫描件、图纸 PDF、OCR 产物），
# 打包重传一次要十几分钟，增量同步第二次起只传改动的那几个文件。
#
# 这个环境里有 8 条测试跑不过，都不是回归，别当成红灯：
#   · 3 条 release_manifest —— 镜像里没有 git 可执行文件
#   · 2 条 local_startup / start_local_dev —— 镜像里没有 zsh
#   · 2 条 import_offline_test_projects（test2 项目）+ 1 条 contract 的 knowledgeFileId
#     —— 用到被排除的 test2/ 夹具
# 基线是 2932 passed / 8 failed / 65 skipped（2026-09-08）。失败数超过 8 才需要看。
#
# 用法：AICHECK_DEPLOY_HOST=aicheck-prod-new bash backend/scripts/run_tests_in_container.sh [pytest 参数...]
set -euo pipefail
HOST="${AICHECK_DEPLOY_HOST:-aicheck-prod-new}"
IMAGE="${AICHECK_TEST_IMAGE:-aicheck-api:local}"
REMOTE_WS="${AICHECK_TEST_WORKSPACE:-/tmp/aicheck-ws}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# 只同步追踪中的文件，跳过测试用不到的大件：标准 PDF、扫描原图、OCR 页面图、审计归档。
# 追踪文件总共 1.6GB，其中 backend/data/visual_extraction_pages 一个目录 589MB、Scan/ 515MB，
# 测试都不打开（测试里的 Scan 路径都是 tmp_path 造的假目录）。排除后约 400MB。
#
# macOS 自带的是 openrsync：没有 --from0 / --delete-missing-args，清单只能按行分隔；
# 且必须 core.quotePath=false，否则 git 会把中文路径转义成 \344\270\255，rsync 找不到文件。
LIST="$(mktemp)"
trap 'rm -f "$LIST"' EXIT
git -c core.quotePath=false ls-files \
  | grep -vE '^(rules/results/|rules/standards/|audit-reports/|Scan/|test2/|backend/data/visual_extraction_pages/|.*\.(zip|dump|mp4)$)' \
  > "$LIST"

# 上一轮容器以 uid 999 写下的产物（output/ 下的上传件等）主机用户删不掉，也会挡住 rsync；
# 先用同一个镜像以 root 身份清掉它们。
ssh "$HOST" "
  mkdir -p '$REMOTE_WS'
  docker run --rm -u root -v '$REMOTE_WS':/ws '$IMAGE' \
    sh -c 'rm -rf /ws/output /ws/tmp /ws/backend/data/runtime-exports /ws/backend/ocr_eval/reports' || true
"
rsync -a --files-from="$LIST" ./ "$HOST:$REMOTE_WS/"

ssh "$HOST" "
  set -e
  # macOS 的 tar/rsync 可能带出 ._ 开头的 AppleDouble 文件；迁移清单校验会把
  # ._0001_xxx 当成一个迁移，整条报 order/content mismatch。
  find '$REMOTE_WS' -name '._*' -delete
  # 容器里跑的是 uid 999，这些目录测试要写
  mkdir -p '$REMOTE_WS'/output '$REMOTE_WS'/tmp '$REMOTE_WS'/backend/data/runtime-exports '$REMOTE_WS'/backend/ocr_eval/reports
  chmod -R a+rwX '$REMOTE_WS'/output '$REMOTE_WS'/tmp '$REMOTE_WS'/backend/data '$REMOTE_WS'/backend/ocr_eval
  docker run --rm -v '$REMOTE_WS':/ws -w /ws/backend '$IMAGE' python -m pytest -q -p no:cacheprovider ${*:-tests}
"
