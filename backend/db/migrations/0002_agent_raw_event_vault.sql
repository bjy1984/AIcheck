CREATE TABLE IF NOT EXISTS raw_vault_events (
    tenant_id text NOT NULL,
    id text NOT NULL,
    run_stream_id text NOT NULL,
    project_id text,
    review_run_id text,
    ai_run_id text,
    model_call_attempt_id text,
    provider_tool_call_id text,
    stage text,
    event_type text NOT NULL,
    turn integer,
    sequence bigint NOT NULL CHECK (sequence > 0),
    has_payload boolean NOT NULL,
    payload_media_type text,
    payload_byte_length bigint CHECK (payload_byte_length >= 0),
    payload_hash text,
    object_bucket text,
    object_key text,
    previous_event_hash text NOT NULL,
    event_hash text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, run_stream_id, sequence),
    UNIQUE (event_hash),
    CHECK (
        (
            has_payload
            AND payload_media_type IS NOT NULL
            AND payload_byte_length IS NOT NULL
            AND payload_hash IS NOT NULL
            AND object_bucket IS NOT NULL
            AND object_key IS NOT NULL
        )
        OR
        (
            NOT has_payload
            AND payload_media_type IS NULL
            AND payload_byte_length IS NULL
            AND payload_hash IS NULL
            AND object_bucket IS NULL
            AND object_key IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_raw_vault_events_run_timeline
    ON raw_vault_events (tenant_id, run_stream_id, sequence);

CREATE INDEX IF NOT EXISTS idx_raw_vault_events_review_run
    ON raw_vault_events (tenant_id, review_run_id, sequence)
    WHERE review_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_vault_events_ai_run
    ON raw_vault_events (tenant_id, ai_run_id, sequence)
    WHERE ai_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_vault_events_model_attempt
    ON raw_vault_events (tenant_id, model_call_attempt_id, sequence)
    WHERE model_call_attempt_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS raw_vault_outbox (
    tenant_id text NOT NULL,
    event_id text NOT NULL,
    run_stream_id text NOT NULL,
    payload bytea NOT NULL,
    payload_hash text NOT NULL,
    object_bucket text NOT NULL,
    object_key text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'delivering', 'retry_pending', 'archived', 'hash_mismatch')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_token text,
    lease_until timestamptz,
    next_attempt_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, event_id),
    FOREIGN KEY (tenant_id, event_id)
        REFERENCES raw_vault_events (tenant_id, id)
);

CREATE INDEX IF NOT EXISTS idx_raw_vault_outbox_pending
    ON raw_vault_outbox (status, next_attempt_at, updated_at)
    WHERE status IN ('pending', 'delivering', 'retry_pending');

CREATE INDEX IF NOT EXISTS idx_raw_vault_outbox_run
    ON raw_vault_outbox (tenant_id, run_stream_id, status);

CREATE OR REPLACE FUNCTION aicheck_reject_raw_vault_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'raw_vault_events are append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_raw_vault_events_append_only ON raw_vault_events;
CREATE TRIGGER trg_raw_vault_events_append_only
BEFORE UPDATE OR DELETE ON raw_vault_events
FOR EACH ROW
EXECUTE FUNCTION aicheck_reject_raw_vault_event_mutation();
