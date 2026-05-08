-- Migration 002: Align delegation_events with HandlerProjectionDelegation.project()
-- The omnimarket projection handler upserts columns that the original SQLite
-- schema did not include. Add them so the generic upsert path works.

ALTER TABLE delegation_events ADD COLUMN timestamp TEXT;
ALTER TABLE delegation_events ADD COLUMN delegated_by TEXT NOT NULL DEFAULT '';
ALTER TABLE delegation_events ADD COLUMN quality_gates_checked INTEGER NOT NULL DEFAULT 0;
ALTER TABLE delegation_events ADD COLUMN quality_gates_failed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE delegation_events ADD COLUMN delegation_latency_ms INTEGER;
ALTER TABLE delegation_events ADD COLUMN repo TEXT;
ALTER TABLE delegation_events ADD COLUMN is_shadow INTEGER NOT NULL DEFAULT 0;
ALTER TABLE delegation_events ADD COLUMN llm_call_id TEXT;
ALTER TABLE delegation_events ADD COLUMN tokens_input INTEGER NOT NULL DEFAULT 0;
ALTER TABLE delegation_events ADD COLUMN tokens_output INTEGER NOT NULL DEFAULT 0;
ALTER TABLE delegation_events ADD COLUMN cost_savings_usd REAL NOT NULL DEFAULT 0.0;
