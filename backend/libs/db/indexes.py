from __future__ import annotations

POSTGRES_SCHEMA_OBJECTS = {
    "aicheck_state",
    "aicheck_singletons",
    "idempotency_records",
    "knowledge_vector_index",
}

POSTGRES_INDEXES = {
    "aicheck_state": [
        {"name": "aicheck_state_pkey", "fields": ["tenant_id", "collection", "object_id"], "unique": True},
        {"name": "idx_aicheck_state_collection", "fields": ["tenant_id", "collection"]},
        {"name": "idx_aicheck_state_payload_gin", "fields": ["payload"], "type": "gin"},
    ],
    "aicheck_singletons": [
        {"name": "aicheck_singletons_pkey", "fields": ["tenant_id", "name"], "unique": True},
    ],
    "idempotency_records": [
        {"name": "idempotency_records_pkey", "fields": ["tenant_id", "scope"], "unique": True},
        {"name": "idx_idempotency_updated_at", "fields": ["tenant_id", "updated_at"]},
    ],
    "knowledge_vector_index": [
        {"name": "knowledge_vector_index_pkey", "fields": ["tenant_id", "id"], "unique": True},
        {"name": "idx_kvi_source", "fields": ["source_id"]},
        {"name": "idx_kvi_index_version", "fields": ["index_version"]},
        {"name": "idx_kvi_embedding_cosine", "fields": ["embedding"], "type": "ivfflat"},
    ],
}
