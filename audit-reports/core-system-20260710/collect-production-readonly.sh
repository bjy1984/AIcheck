#!/bin/sh
set -eu

echo '=== containers ==='
docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}' | grep '^aicheck-' | sort

echo '=== image_ids ==='
for container in \
  aicheck-api-service-1 \
  aicheck-worker-service-1 \
  aicheck-review-worker-service-1 \
  aicheck-ocr-service-1 \
  aicheck-embedding-service-1 \
  aicheck-postgres-1 \
  aicheck-redis-1 \
  aicheck-minio-1 \
  aicheck-temporal-service-1
do
  docker inspect "$container" --format '{{.Name}}|{{.Image}}'
done

echo '=== source_hashes ==='
cd /home/dev-bjy/AIcheck
sha256sum \
  backend/docker-compose.yml \
  backend/config/qwen_runtime.yaml \
  backend/config/material_review_points.json \
  frontend/dist-pro/index.html

echo '=== database_schema_hash ==='
docker exec aicheck-postgres-1 sh -lc '
  psql -U "$POSTGRES_USER" -d aicheck -Atc "
    select table_schema || '\''.'\'' || table_name || '\''.'\'' || column_name || '\'':'\'' || data_type
    from information_schema.columns
    where table_schema not in ('\''pg_catalog'\'', '\''information_schema'\'')
    order by 1
  " | sha256sum
'

echo '=== database_sizes ==='
docker exec aicheck-postgres-1 sh -lc '
  psql -U "$POSTGRES_USER" -d postgres -Atc "
    select datname || '\''|'\'' || pg_database_size(datname)
    from pg_database
    where datname in ('\''aicheck'\'', '\''workflow'\'', '\''litellm'\'')
    order by datname
  "
'

echo '=== state_collections ==='
docker exec aicheck-postgres-1 sh -lc '
  psql -U "$POSTGRES_USER" -d aicheck -Atc "
    select collection || '\''|'\'' || jsonb_array_length(payload)
    from aicheck_state
    where jsonb_typeof(payload) = '\''array'\''
    order by collection
  "
' | grep -E '^(projects|users|documents|versions|knowledge_files|knowledge_chunks|knowledge_vectors|review_runs|ai_runs|reports|archive_items|evidence_links)\|'

echo '=== ocr_health ==='
curl -fsS http://127.0.0.1:18010/healthz
echo

echo '=== embedding_health ==='
curl -fsS http://127.0.0.1:17997/health
echo
