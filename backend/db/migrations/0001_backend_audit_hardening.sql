CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS aicheck_state (
    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
    collection text NOT NULL,
    object_id text NOT NULL,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, collection, object_id)
);

CREATE TABLE IF NOT EXISTS aicheck_singletons (
    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
    name text NOT NULL,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
    scope text NOT NULL,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, scope)
);

CREATE TABLE IF NOT EXISTS service_heartbeats (
    service_id text PRIMARY KEY,
    service_role text NOT NULL,
    instance_id text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_service_heartbeats_role_seen
    ON service_heartbeats (service_role, last_seen_at DESC);

ALTER TABLE aicheck_state ADD COLUMN IF NOT EXISTS tenant_id text;
UPDATE aicheck_state
SET tenant_id = COALESCE(NULLIF(payload ->> 'tenantId', ''), 'TENANT-DEFAULT')
WHERE tenant_id IS NULL;
ALTER TABLE aicheck_state ALTER COLUMN tenant_id SET DEFAULT 'TENANT-DEFAULT';
ALTER TABLE aicheck_state ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE aicheck_singletons ADD COLUMN IF NOT EXISTS tenant_id text;
UPDATE aicheck_singletons
SET tenant_id = COALESCE(NULLIF(payload ->> 'tenantId', ''), 'TENANT-DEFAULT')
WHERE tenant_id IS NULL;
ALTER TABLE aicheck_singletons ALTER COLUMN tenant_id SET DEFAULT 'TENANT-DEFAULT';
ALTER TABLE aicheck_singletons ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE idempotency_records ADD COLUMN IF NOT EXISTS tenant_id text;
UPDATE idempotency_records
SET tenant_id = COALESCE(NULLIF(payload ->> 'tenantId', ''), NULLIF(split_part(scope, ':', 1), ''), 'TENANT-DEFAULT')
WHERE tenant_id IS NULL;
ALTER TABLE idempotency_records ALTER COLUMN tenant_id SET DEFAULT 'TENANT-DEFAULT';
ALTER TABLE idempotency_records ALTER COLUMN tenant_id SET NOT NULL;

DO $$
DECLARE
    columns text[];
BEGIN
    SELECT array_agg(att.attname ORDER BY key.ordinality)
    INTO columns
    FROM pg_constraint con
    JOIN unnest(con.conkey) WITH ORDINALITY AS key(attnum, ordinality) ON TRUE
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = key.attnum
    WHERE con.conrelid = 'aicheck_state'::regclass AND con.contype = 'p';
    IF columns IS DISTINCT FROM ARRAY['tenant_id', 'collection', 'object_id']::text[] THEN
        ALTER TABLE aicheck_state DROP CONSTRAINT IF EXISTS aicheck_state_pkey;
        ALTER TABLE aicheck_state ADD PRIMARY KEY (tenant_id, collection, object_id);
    END IF;

    SELECT array_agg(att.attname ORDER BY key.ordinality)
    INTO columns
    FROM pg_constraint con
    JOIN unnest(con.conkey) WITH ORDINALITY AS key(attnum, ordinality) ON TRUE
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = key.attnum
    WHERE con.conrelid = 'aicheck_singletons'::regclass AND con.contype = 'p';
    IF columns IS DISTINCT FROM ARRAY['tenant_id', 'name']::text[] THEN
        ALTER TABLE aicheck_singletons DROP CONSTRAINT IF EXISTS aicheck_singletons_pkey;
        ALTER TABLE aicheck_singletons ADD PRIMARY KEY (tenant_id, name);
    END IF;

    SELECT array_agg(att.attname ORDER BY key.ordinality)
    INTO columns
    FROM pg_constraint con
    JOIN unnest(con.conkey) WITH ORDINALITY AS key(attnum, ordinality) ON TRUE
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = key.attnum
    WHERE con.conrelid = 'idempotency_records'::regclass AND con.contype = 'p';
    IF columns IS DISTINCT FROM ARRAY['tenant_id', 'scope']::text[] THEN
        ALTER TABLE idempotency_records DROP CONSTRAINT IF EXISTS idempotency_records_pkey;
        ALTER TABLE idempotency_records ADD PRIMARY KEY (tenant_id, scope);
    END IF;
END
$$;

ALTER TABLE aicheck_state
    ADD COLUMN IF NOT EXISTS revision bigint NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_aicheck_state_collection
    ON aicheck_state (tenant_id, collection);

CREATE INDEX IF NOT EXISTS idx_aicheck_state_payload_gin
    ON aicheck_state USING gin (payload);

CREATE INDEX IF NOT EXISTS idx_idempotency_updated_at
    ON idempotency_records (tenant_id, updated_at DESC);

UPDATE aicheck_state
SET payload = jsonb_set(payload, '{tenantId}', '"TENANT-DEFAULT"'::jsonb, true),
    revision = revision + 1,
    updated_at = now()
WHERE NOT (payload ? 'tenantId');

UPDATE aicheck_singletons
SET payload = jsonb_set(payload, '{tenantId}', '"TENANT-DEFAULT"'::jsonb, true),
    updated_at = now()
WHERE NOT (payload ? 'tenantId');

CREATE INDEX IF NOT EXISTS idx_aicheck_state_tenant_collection
    ON aicheck_state ((payload ->> 'tenantId'), collection, object_id);

CREATE INDEX IF NOT EXISTS idx_aicheck_state_tenant_project_node
    ON aicheck_state (
        (payload ->> 'tenantId'),
        (payload ->> 'projectId'),
        (CASE
            WHEN payload ->> 'nodeId' ~ '^[0-9]+$' THEN (payload ->> 'nodeId')::integer
            ELSE NULL
        END),
        updated_at DESC,
        object_id
    )
    WHERE payload ? 'projectId' AND payload ? 'nodeId';

CREATE INDEX IF NOT EXISTS idx_review_runs_tenant_status_updated
    ON aicheck_state (
        (payload ->> 'tenantId'),
        (payload ->> 'status'),
        updated_at DESC,
        object_id
    )
    WHERE collection = 'review_runs';

CREATE INDEX IF NOT EXISTS idx_aicheck_state_review_run_id
    ON aicheck_state ((payload ->> 'reviewRunId'), collection, object_id)
    WHERE payload ? 'reviewRunId';

CREATE INDEX IF NOT EXISTS idx_aicheck_state_ai_run_id
    ON aicheck_state ((payload ->> 'aiRunId'), collection, object_id)
    WHERE payload ? 'aiRunId';

CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_sequence
    ON aicheck_state (
        tenant_id,
        (CASE
            WHEN payload ->> 'sequence' ~ '^[0-9]+$' THEN (payload ->> 'sequence')::bigint
            ELSE NULL
        END),
        object_id
    )
    WHERE collection = 'audit_logs' AND payload ? 'sequence';

CREATE INDEX IF NOT EXISTS idx_workflow_outbox_pending
    ON aicheck_state (
        tenant_id,
        (payload ->> 'status'),
        updated_at,
        object_id
    )
    WHERE collection = 'workflow_outbox';

DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS vector;
    EXCEPTION
        WHEN insufficient_privilege OR undefined_file OR feature_not_supported THEN
            RAISE NOTICE 'pgvector extension must be provisioned by the database administrator';
    END;
    IF to_regtype('vector') IS NOT NULL THEN
        EXECUTE $sql$
            CREATE TABLE IF NOT EXISTS knowledge_vector_index (
                tenant_id text NOT NULL DEFAULT 'TENANT-DEFAULT',
                id text NOT NULL,
                file_id text,
                chunk_id text,
                document_id text,
                document_version_id text,
                source_id text,
                embedding vector(1024) NOT NULL,
                dimensions integer NOT NULL,
                embedding_model text NOT NULL,
                index_version text NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_id, id)
            )
        $sql$;
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_kvi_tenant_id ON knowledge_vector_index (tenant_id, id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_kvi_tenant_source ON knowledge_vector_index (tenant_id, source_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_kvi_tenant_index_version ON knowledge_vector_index (tenant_id, index_version)';
        BEGIN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_kvi_embedding_cosine ON knowledge_vector_index USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)';
        EXCEPTION
            WHEN undefined_object OR feature_not_supported THEN
                RAISE NOTICE 'pgvector HNSW index is unavailable and must be provisioned separately';
        END;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS audit_events (
    tenant_id text NOT NULL,
    id text NOT NULL,
    project_id text,
    node_id integer,
    sequence bigint,
    previous_hash text,
    event_hash text,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

DO $$
DECLARE
    columns text[];
BEGIN
    SELECT array_agg(att.attname ORDER BY key.ordinality)
    INTO columns
    FROM pg_constraint con
    JOIN unnest(con.conkey) WITH ORDINALITY AS key(attnum, ordinality) ON TRUE
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = key.attnum
    WHERE con.conrelid = 'audit_events'::regclass AND con.contype = 'p';
    IF columns IS DISTINCT FROM ARRAY['tenant_id', 'id']::text[] THEN
        ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_pkey;
        ALTER TABLE audit_events ADD PRIMARY KEY (tenant_id, id);
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_events_tenant_sequence
    ON audit_events (tenant_id, sequence)
    WHERE sequence IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_events_event_hash
    ON audit_events (event_hash)
    WHERE event_hash IS NOT NULL;

INSERT INTO audit_events (
    id,
    tenant_id,
    project_id,
    node_id,
    sequence,
    previous_hash,
    event_hash,
    payload,
    created_at
)
SELECT
    object_id,
    COALESCE(payload ->> 'tenantId', 'TENANT-DEFAULT'),
    payload ->> 'projectId',
    CASE WHEN payload ->> 'nodeId' ~ '^[0-9]+$' THEN (payload ->> 'nodeId')::integer END,
    CASE WHEN payload ->> 'sequence' ~ '^[0-9]+$' THEN (payload ->> 'sequence')::bigint END,
    payload ->> 'previousHash',
    payload ->> 'eventHash',
    payload,
    updated_at
FROM aicheck_state
WHERE collection = 'audit_logs'
ON CONFLICT (tenant_id, id) DO NOTHING;

CREATE TABLE IF NOT EXISTS audit_chain_anchors (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL,
    head_sequence bigint NOT NULL,
    head_hash text NOT NULL,
    sink_type text NOT NULL,
    sink_reference text NOT NULL,
    anchored_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, head_sequence, sink_type)
);

CREATE OR REPLACE FUNCTION aicheck_mirror_audit_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.collection = 'audit_logs' THEN
        INSERT INTO audit_events (
            id,
            tenant_id,
            project_id,
            node_id,
            sequence,
            previous_hash,
            event_hash,
            payload,
            created_at
        ) VALUES (
            NEW.object_id,
            NEW.tenant_id,
            NEW.payload ->> 'projectId',
            CASE WHEN NEW.payload ->> 'nodeId' ~ '^[0-9]+$' THEN (NEW.payload ->> 'nodeId')::integer END,
            CASE WHEN NEW.payload ->> 'sequence' ~ '^[0-9]+$' THEN (NEW.payload ->> 'sequence')::bigint END,
            NEW.payload ->> 'previousHash',
            NEW.payload ->> 'eventHash',
            NEW.payload,
            NEW.updated_at
        );
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_aicheck_audit_mirror_insert ON aicheck_state;
CREATE TRIGGER trg_aicheck_audit_mirror_insert
AFTER INSERT ON aicheck_state
FOR EACH ROW
EXECUTE FUNCTION aicheck_mirror_audit_insert();

CREATE OR REPLACE FUNCTION aicheck_reject_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.collection = 'audit_logs' THEN
        RAISE EXCEPTION 'audit_logs are append-only';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_aicheck_audit_append_only ON aicheck_state;
CREATE TRIGGER trg_aicheck_audit_append_only
BEFORE UPDATE OR DELETE ON aicheck_state
FOR EACH ROW
EXECUTE FUNCTION aicheck_reject_audit_mutation();

CREATE OR REPLACE FUNCTION aicheck_reject_append_only_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'append-only relation cannot be updated or deleted';
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;
CREATE TRIGGER trg_audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW
EXECUTE FUNCTION aicheck_reject_append_only_mutation();

DROP TRIGGER IF EXISTS trg_audit_chain_anchors_append_only ON audit_chain_anchors;
CREATE TRIGGER trg_audit_chain_anchors_append_only
BEFORE UPDATE OR DELETE ON audit_chain_anchors
FOR EACH ROW
EXECUTE FUNCTION aicheck_reject_append_only_mutation();
