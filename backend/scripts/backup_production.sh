#!/usr/bin/env bash
# 生产数据每日备份：Postgres 全库 + MinIO 对象清单。
#
# ## 为什么必须有
#
# 2026-08-19 我用错管线清掉了标准条款库 31 份文件的分块，能救回来**纯粹是因为
# 迁移前顺手做了一次手工备份**。当时库里没有任何定时备份——真实用户进来之后，
# 同样的失误就是不可逆的。
#
# ## 保留策略
#
# 每天一份，保留 7 天。再往前的价值有限：这套系统的数据是持续演进的，
# 一周前的快照恢复回来同样要人工核对，而磁盘不是无限的。
#
# ## 用法（crontab）
#
#   30 3 * * * /home/dev-bjy/AIcheck/backend/scripts/backup_production.sh >> /home/dev-bjy/backup.log 2>&1
set -euo pipefail

BACKUP_DIR="${AICHECK_BACKUP_DIR:-/home/dev-bjy/backups}"
KEEP_DAYS="${AICHECK_BACKUP_KEEP_DAYS:-7}"
STAMP="$(date +%Y%m%d-%H%M)"
mkdir -p "$BACKUP_DIR"

echo "[$(date '+%F %T')] 开始备份"

# 全库而不是只备 aicheck_state：审计链、幂等记录、向量索引都在别的表里，
# 只备状态表的话恢复出来是个不自洽的库。
if ! docker exec aicheck-postgres pg_dump -U aicheck -d aicheck --clean --if-exists \
    | gzip > "$BACKUP_DIR/pg-$STAMP.sql.gz.partial"; then
  rm -f "$BACKUP_DIR/pg-$STAMP.sql.gz.partial"
  echo "[$(date '+%F %T')] ✗ pg_dump 失败"
  exit 1
fi
# 先写 .partial 再改名：中途失败的半个文件不会被当成可用备份，
# 而「以为有备份、其实是半个」比没有备份更危险。
mv "$BACKUP_DIR/pg-$STAMP.sql.gz.partial" "$BACKUP_DIR/pg-$STAMP.sql.gz"
SIZE="$(du -h "$BACKUP_DIR/pg-$STAMP.sql.gz" | cut -f1)"

# 对象存储只记清单不拷文件：几十 GB 的 PDF 每天拷一份不现实，
# 但清单能回答「哪些文件当时应该存在」——空壳资料就是这么发现的。
docker exec aicheck-minio mc ls --recursive local/documents 2>/dev/null \
  | gzip > "$BACKUP_DIR/minio-manifest-$STAMP.txt.gz" || \
  echo "[$(date '+%F %T')] ⚠ MinIO 清单跳过（mc 不可用）"

find "$BACKUP_DIR" -name 'pg-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'minio-manifest-*.txt.gz' -mtime "+$KEEP_DAYS" -delete

COUNT="$(find "$BACKUP_DIR" -name 'pg-*.sql.gz' | wc -l | tr -d ' ')"
echo "[$(date '+%F %T')] ✓ 备份完成 $SIZE，现存 $COUNT 份"
