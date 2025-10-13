-- Migration 002: Performance Optimization Tables
-- Adds tables for agent analytics, context optimization, and performance tracking

-- Agent Performance Analytics
CREATE TABLE IF NOT EXISTS agent_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(255) NOT NULL,
    task_type VARCHAR(255) NOT NULL,
    success BOOLEAN NOT NULL,
    duration_ms INTEGER NOT NULL,
    run_id VARCHAR(255) NOT NULL,
    correlation_id VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Context Optimization Learning
CREATE TABLE IF NOT EXISTS context_learning (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_hash VARCHAR(64) NOT NULL,
    prompt_text TEXT NOT NULL,
    context_types_used JSONB NOT NULL,
    success_rate DECIMAL(5,2),
    avg_duration_ms INTEGER,
    user_satisfaction_score DECIMAL(3,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Context Prediction Cache
CREATE TABLE IF NOT EXISTS context_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_hash VARCHAR(64) NOT NULL,
    predicted_context_types JSONB NOT NULL,
    confidence_score DECIMAL(3,2),
    prediction_accuracy DECIMAL(3,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Performance Optimization Metrics
CREATE TABLE IF NOT EXISTS performance_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_name VARCHAR(255) NOT NULL,
    metric_value DECIMAL(10,4) NOT NULL,
    metric_unit VARCHAR(50),
    run_id VARCHAR(255),
    phase VARCHAR(100),
    agent_id VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Circuit Breaker State
CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    breaker_name VARCHAR(255) NOT NULL UNIQUE,
    state VARCHAR(20) NOT NULL, -- CLOSED, OPEN, HALF_OPEN
    failure_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    last_failure_time TIMESTAMP WITH TIME ZONE,
    last_state_change_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    config JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Retry Manager State
CREATE TABLE IF NOT EXISTS retry_manager_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation_name VARCHAR(255) NOT NULL,
    attempt_count INTEGER DEFAULT 0,
    last_attempt_time TIMESTAMP WITH TIME ZONE,
    next_retry_time TIMESTAMP WITH TIME ZONE,
    backoff_multiplier DECIMAL(3,2) DEFAULT 2.0,
    max_retries INTEGER DEFAULT 3,
    status VARCHAR(20) NOT NULL, -- ACTIVE, COMPLETED, FAILED
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Batch Operation Logs
CREATE TABLE IF NOT EXISTS batch_operation_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation_type VARCHAR(100) NOT NULL,
    batch_size INTEGER NOT NULL,
    total_records INTEGER NOT NULL,
    success_count INTEGER NOT NULL,
    error_count INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    run_id VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_agent_performance_agent_id ON agent_performance(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_performance_task_type ON agent_performance(task_type);
CREATE INDEX IF NOT EXISTS idx_agent_performance_success ON agent_performance(success);
CREATE INDEX IF NOT EXISTS idx_agent_performance_created_at ON agent_performance(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_performance_run_id ON agent_performance(run_id);

CREATE INDEX IF NOT EXISTS idx_context_learning_prompt_hash ON context_learning(prompt_hash);
CREATE INDEX IF NOT EXISTS idx_context_learning_success_rate ON context_learning(success_rate);
CREATE INDEX IF NOT EXISTS idx_context_learning_created_at ON context_learning(created_at);

CREATE INDEX IF NOT EXISTS idx_context_predictions_prompt_hash ON context_predictions(prompt_hash);
CREATE INDEX IF NOT EXISTS idx_context_predictions_confidence ON context_predictions(confidence_score);
CREATE INDEX IF NOT EXISTS idx_context_predictions_created_at ON context_predictions(created_at);

CREATE INDEX IF NOT EXISTS idx_performance_metrics_name ON performance_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_performance_metrics_run_id ON performance_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_performance_metrics_phase ON performance_metrics(phase);
CREATE INDEX IF NOT EXISTS idx_performance_metrics_created_at ON performance_metrics(created_at);

CREATE INDEX IF NOT EXISTS idx_circuit_breaker_name ON circuit_breaker_state(breaker_name);
CREATE INDEX IF NOT EXISTS idx_circuit_breaker_state ON circuit_breaker_state(state);

CREATE INDEX IF NOT EXISTS idx_retry_manager_operation ON retry_manager_state(operation_name);
CREATE INDEX IF NOT EXISTS idx_retry_manager_status ON retry_manager_state(status);
CREATE INDEX IF NOT EXISTS idx_retry_manager_next_retry ON retry_manager_state(next_retry_time);

CREATE INDEX IF NOT EXISTS idx_batch_operation_type ON batch_operation_logs(operation_type);
CREATE INDEX IF NOT EXISTS idx_batch_operation_run_id ON batch_operation_logs(run_id);
CREATE INDEX IF NOT EXISTS idx_batch_operation_created_at ON batch_operation_logs(created_at);

-- Performance Views
CREATE OR REPLACE VIEW agent_performance_summary AS
SELECT
    agent_id,
    task_type,
    COUNT(*) as total_tasks,
    COUNT(CASE WHEN success = TRUE THEN 1 END) as successful_tasks,
    (COUNT(CASE WHEN success = TRUE THEN 1 END)::numeric * 100) / NULLIF(COUNT(*), 0) as success_rate_percent,
    AVG(duration_ms) as avg_duration_ms,
    MIN(duration_ms) as min_duration_ms,
    MAX(duration_ms) as max_duration_ms,
    STDDEV(duration_ms) as duration_stddev,
    COUNT(DISTINCT run_id) as unique_runs
FROM agent_performance
GROUP BY agent_id, task_type;

CREATE OR REPLACE VIEW top_performing_agents AS
SELECT
    agent_id,
    task_type,
    success_rate_percent,
    avg_duration_ms,
    total_tasks,
    ROW_NUMBER() OVER (PARTITION BY task_type ORDER BY success_rate_percent DESC, avg_duration_ms ASC) as rank
FROM agent_performance_summary
WHERE total_tasks >= 3  -- Minimum tasks for statistical significance
ORDER BY task_type, rank;

CREATE OR REPLACE VIEW performance_trends AS
SELECT
    DATE_TRUNC('hour', created_at) as time_bucket,
    agent_id,
    task_type,
    COUNT(*) as total_tasks,
    COUNT(CASE WHEN success = TRUE THEN 1 END) as successful_tasks,
    AVG(duration_ms) as avg_duration_ms,
    (COUNT(CASE WHEN success = TRUE THEN 1 END)::numeric * 100) / NULLIF(COUNT(*), 0) as success_rate_percent
FROM agent_performance
GROUP BY DATE_TRUNC('hour', created_at), agent_id, task_type
ORDER BY time_bucket DESC;

-- Insert migration record
INSERT INTO schema_migrations (id, name, filename, applied_at) 
VALUES (
    gen_random_uuid(),
    '002_performance_optimization',
    '002_performance_optimization.sql',
    NOW()
) ON CONFLICT (name) DO NOTHING;
