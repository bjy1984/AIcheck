#!/bin/sh
set -eu

: "${AICHECK_SOURCE_MINIO_ENDPOINT:?required}"
: "${AICHECK_SOURCE_MINIO_ACCESS_KEY:?required}"
: "${AICHECK_SOURCE_MINIO_SECRET_KEY:?required}"
: "${AICHECK_OFFSITE_MINIO_ENDPOINT:?required}"
: "${AICHECK_OFFSITE_MINIO_ACCESS_KEY:?required}"
: "${AICHECK_OFFSITE_MINIO_SECRET_KEY:?required}"

receipt="${AICHECK_REPLICATION_RECEIPT:-./minio-replication-receipt.json}"
buckets="${AICHECK_REPLICATION_BUCKETS:-documents previews exports ocr-artifacts audit-anchors-v2}"
wait_seconds="${AICHECK_REPLICATION_WAIT_SECONDS:-900}"
src="aicheck-source"
dst="aicheck-offsite"

umask 077
mc alias set "$src" "$AICHECK_SOURCE_MINIO_ENDPOINT" "$AICHECK_SOURCE_MINIO_ACCESS_KEY" "$AICHECK_SOURCE_MINIO_SECRET_KEY" >/dev/null
mc alias set "$dst" "$AICHECK_OFFSITE_MINIO_ENDPOINT" "$AICHECK_OFFSITE_MINIO_ACCESS_KEY" "$AICHECK_OFFSITE_MINIO_SECRET_KEY" >/dev/null

source_version="$(mc admin info --json "$src" | jq -r 'select(.info.servers) | .info.servers[].version' | sort -u)"
target_version="$(mc admin info --json "$dst" | jq -r 'select(.info.servers) | .info.servers[].version' | sort -u)"
if [ -z "$source_version" ] || [ "$source_version" != "$target_version" ]; then
  echo "MinIO source and offsite versions must match before replication is configured" >&2
  exit 1
fi

bucket_json=""
for bucket in $buckets; do
  mc stat "$src/$bucket" >/dev/null
  mc version enable "$src/$bucket" >/dev/null
  if [ "$bucket" = "audit-anchors-v2" ]; then
    mc mb --ignore-existing --with-lock "$dst/$bucket" >/dev/null
    mc retention set --default COMPLIANCE 3650d "$dst/$bucket" >/dev/null
  else
    mc mb --ignore-existing "$dst/$bucket" >/dev/null
  fi
  mc version enable "$dst/$bucket" >/dev/null
  mc encrypt set sse-s3 "$dst/$bucket" >/dev/null
  if ! mc replicate ls --json "$src/$bucket" | jq -e --arg remote "$AICHECK_OFFSITE_MINIO_ENDPOINT/$bucket" 'select(.status == "success")' >/dev/null 2>&1; then
    mc replicate add "$src/$bucket" --remote-bucket "$dst/$bucket" --replicate "existing-objects" >/dev/null
  fi
  rule_count="$(mc replicate ls --json "$src/$bucket" | jq -s '[.[] | select(.status == "success")] | length')"
  [ "$rule_count" -gt 0 ] || { echo "no replication rule for $bucket" >&2; exit 1; }
  source_objects="$(mc ls --recursive --versions --json "$src/$bucket" | jq -s 'length')"
  target_objects="$(mc ls --recursive --versions --json "$dst/$bucket" | jq -s 'length')"
  waited=0
  while [ "$target_objects" -lt "$source_objects" ] && [ "$waited" -lt "$wait_seconds" ]; do
    sleep 10
    waited=$((waited + 10))
    target_objects="$(mc ls --recursive --versions --json "$dst/$bucket" | jq -s 'length')"
  done
  [ "$target_objects" -ge "$source_objects" ] || { echo "offsite inventory is behind for $bucket" >&2; exit 1; }
  row="$(jq -cn --arg name "$bucket" --argjson source "$source_objects" --argjson target "$target_objects" '{name:$name,sourceObjectVersions:$source,targetObjectVersions:$target}')"
  bucket_json="${bucket_json}${row}\n"
done

completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%b' "$bucket_json" | jq -s --arg completed "$completed_at" --arg version "$source_version" \
  '{schemaVersion:"aicheck-minio-replication-receipt-v1",status:"verified",completedAt:$completed,minioVersion:$version,deleteReplication:false,buckets:.}' > "$receipt.tmp"
mv "$receipt.tmp" "$receipt"
echo "$receipt"
