-- Migration 003: Add tokens_to_compliance and compliance_attempts columns
-- Tracks how many tokens were consumed and how many attempts were needed
-- before the delegated model produced a compliant response (OMN-10789).

ALTER TABLE delegation_events ADD COLUMN tokens_to_compliance INTEGER NOT NULL DEFAULT 0;
ALTER TABLE delegation_events ADD COLUMN compliance_attempts INTEGER NOT NULL DEFAULT 1;
