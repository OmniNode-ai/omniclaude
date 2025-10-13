-- Core tables for MVP Debug Loop and Lineage

CREATE TABLE IF NOT EXISTS debug_transform_functions (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    code_repo TEXT,
    commit_sha TEXT,
    file_path TEXT,
    symbol TEXT,
    line_start INT,
    line_end INT,
    is_pure BOOLEAN DEFAULT TRUE,
    lang TEXT,
    license TEXT,
    hash BYTEA,
    inputs_schema JSONB DEFAULT '{}'::jsonb,
    outputs_schema JSONB DEFAULT '{}'::jsonb,
    blocked BOOLEAN DEFAULT FALSE,
    notes JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS model_price_catalog (
    id UUID PRIMARY KEY,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    unit TEXT DEFAULT '1k_tokens',
    input_per_1k NUMERIC,
    output_per_1k NUMERIC,
    effective_from DATE NOT NULL,
    effective_to DATE
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id UUID PRIMARY KEY,
    run_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    model TEXT NOT NULL,
    provider TEXT,
    model_version TEXT,
    provider_region TEXT,
    system_prompt_hash TEXT,
    temperature NUMERIC,
    seed BIGINT,
    input_tokens INT,
    output_tokens INT,
    price_catalog_id UUID REFERENCES model_price_catalog(id),
    effective_input_usd_per_1k NUMERIC,
    effective_output_usd_per_1k NUMERIC,
    computed_cost_usd NUMERIC,
    request JSONB,
    response JSONB
);

CREATE TABLE IF NOT EXISTS workflow_steps (
    id UUID PRIMARY KEY,
    run_id TEXT,
    step_index INT,
    phase TEXT,
    correlation_id UUID,
    applied_tf_id UUID REFERENCES debug_transform_functions(id),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INT,
    success BOOLEAN,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_run_step ON workflow_steps(run_id, step_index);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_tf ON workflow_steps(applied_tf_id, completed_at DESC);

CREATE TABLE IF NOT EXISTS error_events (
    id UUID PRIMARY KEY,
    run_id TEXT,
    correlation_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    error_type TEXT,
    message TEXT,
    details JSONB
);

CREATE TABLE IF NOT EXISTS success_events (
    id UUID PRIMARY KEY,
    run_id TEXT,
    task_id TEXT,
    correlation_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    approval_source TEXT DEFAULT 'auto',
    is_golden BOOLEAN DEFAULT FALSE
);

CREATE UNIQUE INDEX IF NOT EXISTS unique_golden_per_task
    ON success_events(task_id)
    WHERE is_golden = TRUE;

CREATE TABLE IF NOT EXISTS state_snapshots (
    id UUID PRIMARY KEY,
    run_id TEXT,
    is_success_state BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    pii_tags TEXT[],
    redaction_policy TEXT,
    replay_safe BOOLEAN DEFAULT FALSE,
    content_digest BYTEA,
    storage_uri TEXT,
    snapshot JSONB
);
CREATE INDEX IF NOT EXISTS idx_snapshots_success ON state_snapshots(run_id) WHERE is_success_state;

CREATE TABLE IF NOT EXISTS error_success_maps (
    id UUID PRIMARY KEY,
    error_id UUID REFERENCES error_events(id),
    tf_id UUID REFERENCES debug_transform_functions(id),
    uplift_ms INT,
    uplift_cost_usd NUMERIC,
    n_trials INT DEFAULT 0,
    n_success INT DEFAULT 0,
    last_seen_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clarification_tickets (
    id UUID PRIMARY KEY,
    task_id UUID,
    questions JSONB,
    defaults JSONB,
    blocking_flags JSONB,
    owner TEXT,
    status TEXT DEFAULT 'open',
    deadline TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_clarification_tickets_task_status ON clarification_tickets(task_id, status);

CREATE TABLE IF NOT EXISTS clarification_responses (
    id UUID PRIMARY KEY,
    ticket_id UUID REFERENCES clarification_tickets(id),
    responder TEXT,
    answers JSONB,
    submitted_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS quorum_votes (
    id UUID PRIMARY KEY,
    ticket_id UUID REFERENCES clarification_tickets(id),
    agent_id TEXT,
    coverage_ok BOOLEAN,
    risk_ok BOOLEAN,
    decision TEXT,
    rationale TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_quorum_votes_ticket ON quorum_votes(ticket_id, created_at);

CREATE TABLE IF NOT EXISTS reward_events (
    id UUID PRIMARY KEY,
    contributor_id UUID,
    tf_id UUID REFERENCES debug_transform_functions(id),
    run_id TEXT,
    reason_code TEXT,
    reward_usd NUMERIC,
    reward_token NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    notes JSONB
);

-- Lineage edges for Postgres store
CREATE TABLE IF NOT EXISTS lineage_edges (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    edge_type TEXT NOT NULL,
    src_type TEXT NOT NULL,
    src_id TEXT NOT NULL,
    dst_type TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    attributes JSONB
);
CREATE INDEX IF NOT EXISTS idx_lineage_src ON lineage_edges(src_type, src_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lineage_dst ON lineage_edges(dst_type, dst_id, created_at DESC);


