# Debug Loop Implementation Plan — Two-Part Build

**Status**: Ready for Implementation
**Last Updated**: 2025-11-09
**Version**: 1.0
**Branch**: `claude/omninode-debug-rewards-clarification-011CUxhsawPLtZFyyC5capVP`

---

## Executive Summary

This document provides a detailed implementation plan for the Debug Loop Enhancements (Phase 1) following a **two-part build strategy**:

1. **Part 1: Debug Intelligence Core** (3-4 weeks) — Build debug information capture and recall first for **immediate intelligence value**
2. **Part 2: Token Economy Integration** (4-6 weeks) — Add compute token rewards after Part 1 is delivering value

**User's Direction**: _"let's build it in two parts, let's build the debug information part first and then we can add in the compute tokens, I want to use the enhancements to the debug system so we can start using that intelligence intelligence immediately and then we can build the rest but make sure that that is shown in the planning"_

---

## Table of Contents

1. [Part 1: Debug Intelligence Core](#part-1-debug-intelligence-core)
   - [Overview](#part-1-overview)
   - [Database Schema](#part-1-database-schema)
   - [Implementation Tasks](#part-1-implementation-tasks)
   - [Timeline](#part-1-timeline)
   - [Success Criteria](#part-1-success-criteria)
2. [Part 2: Token Economy Integration](#part-2-token-economy-integration)
   - [Overview](#part-2-overview)
   - [Kafka Event Schema](#part-2-kafka-event-schema)
   - [Implementation Tasks](#part-2-implementation-tasks)
   - [Timeline](#part-2-timeline)
   - [Success Criteria](#part-2-success-criteria)
3. [Dependencies and Prerequisites](#dependencies-and-prerequisites)
4. [Migration Strategy](#migration-strategy)
5. [Testing Strategy](#testing-strategy)
6. [Rollout Plan](#rollout-plan)

---

## Part 1: Debug Intelligence Core

### Part 1 Overview

**Goal**: Capture debug intelligence from agent executions to enable learning from past successes and failures.

**Value Proposition**: Immediate intelligence enhancement — agents can:
- Avoid retrying known-failed approaches
- Reuse proven solutions for similar problems
- Reference successful execution patterns
- Track which LLM models work best for specific tasks

**Duration**: 3-4 weeks (single developer)

**Key Components**:
1. STF (Specific Transformation Functions) Registry
2. Model Price Catalog
3. Enhanced Correlation Tracking
4. Confidence Metrics for Error→Success Mappings
5. Golden State Approval Workflow

---

### Part 1 Database Schema

All tables created in existing PostgreSQL database (`omninode_bridge`).

#### 1. `debug_transform_functions` (STF Registry)

```sql
CREATE TABLE debug_transform_functions (
    stf_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identification
    stf_name VARCHAR(255) NOT NULL,
    stf_description TEXT,
    stf_hash VARCHAR(64) NOT NULL UNIQUE,  -- SHA-256 of normalized STF code

    -- Source tracking
    source_execution_id UUID,
    source_correlation_id UUID,
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    contributor_agent_name VARCHAR(255),

    -- STF content
    stf_code TEXT NOT NULL,
    stf_language VARCHAR(50) DEFAULT 'python',
    stf_parameters JSONB,  -- Input/output schema

    -- Classification
    problem_category VARCHAR(100),  -- e.g., "data_transformation", "api_integration"
    problem_signature TEXT,  -- Normalized problem description

    -- Quality metrics
    quality_score DECIMAL(3, 2),  -- 0.00 to 1.00
    complexity_score DECIMAL(3, 2),  -- 0.00 to 1.00

    -- Usage tracking
    usage_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP WITH TIME ZONE,

    -- Approval status
    approval_status VARCHAR(50) DEFAULT 'pending',  -- pending, approved, rejected
    approved_by VARCHAR(255),
    approved_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Indexes
    INDEX idx_stf_hash (stf_hash),
    INDEX idx_stf_category (problem_category),
    INDEX idx_stf_quality (quality_score),
    INDEX idx_stf_approval (approval_status),
    INDEX idx_stf_usage (usage_count DESC)
);

-- Trigger to update updated_at
CREATE TRIGGER update_stf_updated_at
    BEFORE UPDATE ON debug_transform_functions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2. `model_price_catalog`

```sql
CREATE TABLE model_price_catalog (
    catalog_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Model identification
    provider VARCHAR(100) NOT NULL,  -- anthropic, openai, google, zai
    model_name VARCHAR(255) NOT NULL,
    model_version VARCHAR(50),

    -- Pricing (per 1M tokens)
    input_price_per_million DECIMAL(10, 6) NOT NULL,
    output_price_per_million DECIMAL(10, 6) NOT NULL,
    currency VARCHAR(10) DEFAULT 'USD',

    -- Performance characteristics
    avg_latency_ms INTEGER,
    max_tokens INTEGER,
    context_window INTEGER,

    -- Capabilities
    supports_streaming BOOLEAN DEFAULT false,
    supports_function_calling BOOLEAN DEFAULT false,
    supports_vision BOOLEAN DEFAULT false,

    -- Rate limits
    requests_per_minute INTEGER,
    tokens_per_minute INTEGER,

    -- Availability
    is_active BOOLEAN DEFAULT true,
    deprecated_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    effective_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Composite unique constraint
    UNIQUE (provider, model_name, model_version, effective_date),

    -- Indexes
    INDEX idx_model_provider (provider),
    INDEX idx_model_active (is_active),
    INDEX idx_model_price (input_price_per_million, output_price_per_million)
);
```

#### 3. `debug_execution_attempts` (Enhanced Correlation Tracking)

```sql
CREATE TABLE debug_execution_attempts (
    attempt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Correlation
    correlation_id UUID NOT NULL,
    execution_id UUID,
    parent_attempt_id UUID,  -- For retry tracking

    -- Agent context
    agent_name VARCHAR(255) NOT NULL,
    agent_type VARCHAR(100),

    -- Problem identification
    user_request TEXT NOT NULL,
    user_request_hash VARCHAR(64),  -- For similarity matching
    problem_category VARCHAR(100),

    -- Approach taken
    approach_description TEXT,
    stf_ids UUID[],  -- Array of STFs attempted
    model_used VARCHAR(255),
    tools_used JSONB,  -- ["Read", "Edit", "Bash"]

    -- Execution details
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,

    -- Outcome
    status VARCHAR(50) NOT NULL,  -- success, error, timeout, cancelled
    error_type VARCHAR(100),
    error_message TEXT,
    error_stacktrace TEXT,

    -- Quality metrics
    quality_score DECIMAL(3, 2),
    confidence_score DECIMAL(3, 2),  -- How confident we are in this approach

    -- Cost tracking
    tokens_input INTEGER,
    tokens_output INTEGER,
    estimated_cost_usd DECIMAL(10, 6),

    -- Golden state tracking
    is_golden_state BOOLEAN DEFAULT false,
    golden_state_approved_by VARCHAR(255),
    golden_state_approved_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Indexes
    INDEX idx_attempt_correlation (correlation_id),
    INDEX idx_attempt_execution (execution_id),
    INDEX idx_attempt_status (status),
    INDEX idx_attempt_golden (is_golden_state),
    INDEX idx_attempt_request_hash (user_request_hash),
    INDEX idx_attempt_agent (agent_name),
    INDEX idx_attempt_timestamp (started_at DESC)
);
```

#### 4. `debug_error_success_mappings` (Confidence Metrics)

```sql
CREATE TABLE debug_error_success_mappings (
    mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Error identification
    error_type VARCHAR(100) NOT NULL,
    error_pattern TEXT NOT NULL,  -- Normalized error signature
    error_context JSONB,  -- Additional context (file types, tools used, etc.)

    -- Successful resolution
    successful_attempt_id UUID NOT NULL REFERENCES debug_execution_attempts(attempt_id),
    successful_stf_ids UUID[],
    successful_approach TEXT,

    -- Failed attempts (for learning)
    failed_attempt_ids UUID[],

    -- Confidence tracking
    confidence_score DECIMAL(3, 2) NOT NULL,  -- 0.00 to 1.00
    success_count INTEGER DEFAULT 1,
    failure_count INTEGER DEFAULT 0,

    -- Last updated
    last_success_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_failure_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Indexes
    INDEX idx_mapping_error_type (error_type),
    INDEX idx_mapping_confidence (confidence_score DESC),
    INDEX idx_mapping_success_count (success_count DESC)
);

-- Trigger to auto-calculate confidence score
CREATE OR REPLACE FUNCTION calculate_error_mapping_confidence()
RETURNS TRIGGER AS $$
BEGIN
    -- Simple confidence formula: success_count / (success_count + failure_count)
    -- With minimum of 0.1 to avoid zero confidence
    NEW.confidence_score = GREATEST(
        0.10,
        LEAST(
            1.00,
            NEW.success_count::DECIMAL / GREATEST(1, NEW.success_count + NEW.failure_count)
        )
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_error_mapping_confidence
    BEFORE INSERT OR UPDATE ON debug_error_success_mappings
    FOR EACH ROW
    EXECUTE FUNCTION calculate_error_mapping_confidence();
```

#### 5. `debug_golden_states` (Golden State Registry)

```sql
CREATE TABLE debug_golden_states (
    golden_state_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reference to successful execution
    execution_attempt_id UUID NOT NULL REFERENCES debug_execution_attempts(attempt_id),
    correlation_id UUID NOT NULL,

    -- Problem solved
    problem_description TEXT NOT NULL,
    problem_category VARCHAR(100),
    problem_hash VARCHAR(64) NOT NULL,  -- For similarity matching

    -- Solution summary
    solution_summary TEXT NOT NULL,
    stf_ids UUID[],
    tools_used JSONB,
    model_used VARCHAR(255),

    -- Quality metrics
    quality_score DECIMAL(3, 2) NOT NULL,
    complexity_score DECIMAL(3, 2),
    reusability_score DECIMAL(3, 2),

    -- Approval workflow
    nominated_by VARCHAR(255),
    nominated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    approved_by VARCHAR(255),
    approved_at TIMESTAMP WITH TIME ZONE,
    approval_notes TEXT,

    -- Reuse tracking
    reuse_count INTEGER DEFAULT 0,
    last_reused_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Indexes
    INDEX idx_golden_category (problem_category),
    INDEX idx_golden_quality (quality_score DESC),
    INDEX idx_golden_reuse (reuse_count DESC),
    INDEX idx_golden_problem_hash (problem_hash)
);
```

---

### Part 1 Implementation Tasks

#### Week 1: Database Schema & Core Infrastructure

**Days 1-2: Database Setup**
- [ ] Create migration script with all 5 tables
- [ ] Add indexes and triggers
- [ ] Create helper functions (problem signature normalization, hash generation)
- [ ] Add to existing PostgreSQL database (`omninode_bridge`)
- [ ] Test schema with sample data
- [ ] Update `config/settings.py` if needed

**Days 3-5: Core Data Models**
- [ ] Create Pydantic models for all tables:
  - `agents/lib/models/debug_stf.py` — STF registry models
  - `agents/lib/models/debug_execution.py` — Execution attempt models
  - `agents/lib/models/debug_golden_state.py` — Golden state models
- [ ] Create database connection utilities:
  - `agents/lib/db/debug_repository.py` — Database access layer
- [ ] Add validation logic (quality scores, confidence calculations)
- [ ] Write unit tests for models

#### Week 2: STF Registry & Discovery

**Days 6-8: STF Extraction**
- [ ] Create `agents/lib/stf_extractor.py`:
  - Extract STFs from successful executions
  - Generate STF hash (SHA-256 of normalized code)
  - Calculate quality and complexity scores
  - Store in `debug_transform_functions` table
- [ ] Create `agents/lib/stf_matcher.py`:
  - Match current problem to existing STFs
  - Similarity search by problem signature
  - Rank STFs by quality and usage count
- [ ] Integrate with `AgentExecutionLogger.complete()`:
  - Auto-extract STFs on successful completion
  - Calculate quality score from execution metrics

**Days 9-10: STF Reuse System**
- [ ] Create `agents/lib/stf_recommender.py`:
  - Recommend STFs for current problem
  - Template adaptation for parameter differences
  - Confidence scoring for recommendations
- [ ] Update manifest injector to include relevant STFs:
  - Add STF section to agent manifest
  - Include top 5 relevant STFs with confidence scores
  - Show success/failure rates

#### Week 3: Model Catalog & Cost Tracking

**Days 11-12: Model Price Catalog**
- [ ] Create `agents/lib/model_catalog.py`:
  - Load model prices from database
  - Calculate execution cost estimates
  - Track actual costs per execution
- [ ] Populate `model_price_catalog` with current providers:
  - Anthropic (Claude 3.5 Sonnet, Opus, Haiku)
  - OpenAI (GPT-4, GPT-3.5)
  - Google (Gemini Pro, Flash, 2.5 Flash)
  - Z.ai (GLM-4.5-Air, GLM-4.5, GLM-4.6)
  - Together AI (Llama variants)
- [ ] Create admin script to update prices:
  - `scripts/update_model_prices.py`

**Days 13-14: Cost Tracking Integration**
- [ ] Update `AgentExecutionLogger` to track costs:
  - Count tokens (input/output)
  - Look up model price from catalog
  - Calculate and store `estimated_cost_usd`
- [ ] Create cost analytics queries:
  - Cost per agent type
  - Cost per problem category
  - Most expensive executions
- [ ] Add cost summary to manifest:
  - Show average cost for similar problems
  - Recommend cheaper models when appropriate

#### Week 4: Error→Success Mapping & Golden States

**Days 15-16: Error Pattern Extraction**
- [ ] Create `agents/lib/error_pattern_extractor.py`:
  - Normalize error messages
  - Extract error signatures
  - Classify error types
- [ ] Create `agents/lib/error_success_mapper.py`:
  - Link failed attempts to successful retries
  - Calculate confidence scores
  - Update `debug_error_success_mappings` table
- [ ] Integrate with `AgentExecutionLogger`:
  - Track parent_attempt_id for retries
  - Auto-create mappings on retry success

**Days 17-18: Golden State Workflow**
- [ ] Create `agents/lib/golden_state_manager.py`:
  - Nominate high-quality executions
  - Approval workflow (threshold-based auto-approval initially)
  - Golden state registry
- [ ] Update manifest injector:
  - Include relevant golden states in manifest
  - Show proven solutions for similar problems
- [ ] Create golden state browser:
  - `agents/lib/golden_state_browser.py` (CLI tool)
  - Search, view, and export golden states

**Days 19-20: Integration & Testing**
- [ ] End-to-end integration testing:
  - Execute agent → Extract STF → Store in registry
  - Execute agent with error → Retry → Create error mapping
  - High-quality execution → Nominate as golden state
- [ ] Performance testing:
  - STF matching latency (<100ms)
  - Database query performance
  - Manifest injection overhead (<200ms)
- [ ] Create test fixtures and sample data
- [ ] Write integration tests

---

### Part 1 Timeline

**Total Duration**: 3-4 weeks (20 working days)

```
Week 1: Database & Models        [Days 1-5]
Week 2: STF Registry & Discovery [Days 6-10]
Week 3: Model Catalog & Costs    [Days 11-14]
Week 4: Error Mapping & Golden   [Days 15-20]
```

**Milestones**:
- ✅ End of Week 1: Database schema complete, core models tested
- ✅ End of Week 2: STF extraction and reuse working
- ✅ End of Week 3: Cost tracking integrated
- ✅ End of Week 4: Full debug intelligence system operational

---

### Part 1 Success Criteria

**Functional Requirements**:
- [ ] STFs automatically extracted from successful executions
- [ ] STF recommendations included in agent manifests
- [ ] Model costs tracked for all executions
- [ ] Error→success mappings created automatically on retries
- [ ] Golden states nominated and stored
- [ ] All data persisted in PostgreSQL

**Performance Requirements**:
- [ ] STF matching: <100ms for top 5 recommendations
- [ ] Manifest injection overhead: <200ms added latency
- [ ] Database queries: <50ms for indexed lookups

**Quality Requirements**:
- [ ] STF quality scores calculated (5 dimensions)
- [ ] Confidence scores for error mappings
- [ ] Golden state approval workflow

**Observability**:
- [ ] All debug data queryable via SQL
- [ ] CLI browser tools for STFs and golden states
- [ ] Analytics views for cost and quality metrics

**User Value**:
- [ ] Agents avoid retrying known-failed approaches
- [ ] Agents reuse proven solutions (STFs)
- [ ] Users see cost estimates before execution
- [ ] Intelligence accumulates over time (learning system)

---

## Part 2: Token Economy Integration

### Part 2 Overview

**Goal**: Add compute token rewards for contributing valuable debug intelligence (STFs, golden states, pattern contributions).

**Value Proposition**: Self-sustaining economy where contributors earn tokens for sharing knowledge, then spend tokens on compute.

**Duration**: 4-6 weeks (after Part 1 complete)

**Key Components**:
1. Kafka Token Ledger (event sourcing)
2. Token Reward Calculation Engine
3. Token Balance Tracking (Valkey cache + Kafka compaction)
4. Pattern Contribution Rewards (automatic)
5. P2P Context Sharing (optional extension)

**Dependencies**: Requires Part 1 complete (STF registry, golden states, execution tracking)

---

### Part 2 Kafka Event Schema

All token transactions flow through Kafka/Redpanda (already deployed at `192.168.86.200:9092`).

#### Topic: `token.transactions.v1`

**Purpose**: Source of truth for all token transactions (immutable event log)

**Configuration**:
```yaml
topic: token.transactions.v1
partitions: 10  # Partition by peer_id for ordered processing
retention: unlimited  # Keep all transactions forever
cleanup_policy: delete
```

**Event Schema**:
```json
{
  "transaction_id": "550e8400-e29b-41d4-a716-446655440000",
  "peer_id": "peer_abc123",
  "transaction_type": "earned",  // earned | spent | transferred | bonus
  "amount": 150,
  "reason": "stf_contribution",  // stf_contribution | golden_state | pattern_contribution | llm_query | context_served
  "
_hash": "sha256:abc123...",  // STF hash, pattern hash, or context hash
  "quality_score": 0.85,
  "novelty_score": 0.72,
  "counterparty_peer_id": null,  // For transfers or context sharing
  "metadata": {
    "stf_id": "uuid",
    "execution_id": "uuid",
    "correlation_id": "uuid",
    "model_used": "claude-3-5-sonnet-20241022",
    "complexity": 0.65
  },
  "timestamp": "2025-11-09T10:30:00Z"
}
```

#### Topic: `token.balances.v1`

**Purpose**: Materialized view of peer balances (compacted for fast reads)

**Configuration**:
```yaml
topic: token.balances.v1
partitions: 10  # Partition by peer_id
retention: unlimited
cleanup_policy: compact  # Only keep latest balance per peer_id
```

**Event Schema**:
```json
{
  "peer_id": "peer_abc123",  // Kafka key (for compaction)
  "balance": 4550,
  "lifetime_earned": 5000,
  "lifetime_spent": 450,
  "last_transaction_id": "550e8400-e29b-41d4-a716-446655440000",
  "last_updated": "2025-11-09T10:30:00Z"
}
```

---

### Part 2 Implementation Tasks

#### Week 5: Kafka Token Ledger

**Days 21-23: Kafka Infrastructure**
- [ ] Create Kafka topics (`token.transactions.v1`, `token.balances.v1`)
- [ ] Create Pydantic models:
  - `agents/lib/models/token_transaction.py`
  - `agents/lib/models/token_balance.py`
- [ ] Create Kafka producers:
  - `agents/lib/token_ledger_publisher.py`
- [ ] Create Kafka consumers:
  - `agents/lib/token_balance_consumer.py` (materializes balances)
- [ ] Add to deployment:
  - Update `deployment/docker-compose.yml` with token-balance-consumer service

**Days 24-25: Token Balance Service**
- [ ] Create `agents/services/token_balance_service.py`:
  - Consume `token.transactions.v1`
  - Materialize balances to `token.balances.v1`
  - Cache balances in Valkey for fast reads
- [ ] Create `agents/lib/token_balance_client.py`:
  - Read balance from Valkey (cache hit)
  - Fallback to Kafka compacted topic (cache miss)
  - Publish transaction events
- [ ] Add Valkey cache layer:
  - Key format: `token:balance:{peer_id}`
  - TTL: 3600 seconds (1 hour)
  - Refresh on transaction

#### Week 6: Reward Calculation Engine

**Days 26-27: STF Contribution Rewards**
- [ ] Create `agents/lib/rewards/stf_reward_calculator.py`:
  - Quality score → base reward (0.9+ = 300, 0.7+ = 150, 0.5+ = 50)
  - Novelty multiplier (0.5 + novelty_score * 0.5)
  - Complexity bonus (1.0 + complexity_score * 0.3)
  - Cap at 500 tokens per STF
- [ ] Integrate with `stf_extractor.py`:
  - Calculate reward on STF extraction
  - Publish transaction event to Kafka
  - Update STF record with reward amount

**Days 28-29: Golden State Rewards**
- [ ] Create `agents/lib/rewards/golden_state_reward_calculator.py`:
  - Base reward: 200 tokens
  - Quality multiplier (1.0 to 2.0)
  - Reusability bonus (+50 tokens per reuse, cap at +500)
  - Total cap: 1000 tokens
- [ ] Integrate with `golden_state_manager.py`:
  - Calculate reward on approval
  - Publish transaction event
  - Bonus rewards on reuse (diminishing returns)

**Day 30: Pattern Contribution Rewards**
- [ ] Create `agents/lib/rewards/pattern_reward_calculator.py`:
  - Reuse existing `PatternQualityScorer`
  - Quality score → base reward (same tiers as STF)
  - Pattern type multiplier (orchestrator 1.5x, effect 1.3x)
  - Novelty multiplier (similarity search)
- [ ] Integrate with `PatternStorage`:
  - Auto-calculate reward on pattern save
  - Publish transaction event
  - Track reward in pattern metadata

#### Week 7: Token Spending & Quorum

**Days 31-32: LLM Query Cost Deduction**
- [ ] Create `agents/lib/token_spender.py`:
  - Convert USD cost → token cost (1 token = $0.001)
  - Deduct tokens on LLM query
  - Publish "spent" transaction event
  - Handle insufficient balance (graceful degradation)
- [ ] Integrate with `AgentExecutionLogger`:
  - Calculate LLM cost (from `model_price_catalog`)
  - Deduct tokens after execution
  - Log spend transaction

**Days 33-34: Quorum Voting (Token-Weighted)**
- [ ] Create `agents/lib/quorum/token_weighted_quorum.py`:
  - Voting power = sqrt(token_balance) (diminishing returns)
  - Require 3+ voters with 66% agreement
  - Reward voters: 10 tokens per vote
- [ ] Integrate with clarification workflow (Phase 2, deferred):
  - Placeholder for future quorum votes
  - Token-weighted voting mechanism ready

**Day 35: Balance Queries & CLI**
- [ ] Create `agents/lib/token_balance_viewer.py` (CLI tool):
  - Check peer balance
  - View transaction history (query Kafka)
  - Export to CSV/JSON
- [ ] Create admin commands:
  - Grant bonus tokens (admin only)
  - Adjust balances (audit log)

#### Week 8: Integration & Testing

**Days 36-37: End-to-End Flow Testing**
- [ ] Test STF contribution → reward:
  - Execute agent → Extract STF → Calculate reward → Publish to Kafka → Update balance
- [ ] Test LLM spend:
  - Execute agent → Deduct tokens → Publish spend event → Update balance
- [ ] Test pattern contribution → reward:
  - Execute agent → Extract pattern → Calculate reward → Publish to Kafka
- [ ] Test golden state reward:
  - Nominate golden state → Approve → Calculate reward → Publish to Kafka
  - Reuse golden state → Bonus reward → Publish to Kafka

**Days 38-39: Performance & Load Testing**
- [ ] Kafka throughput testing:
  - 1000 transactions/sec target
  - Verify compaction performance
  - Test Valkey cache hit rate (target: >80%)
- [ ] Balance materialization latency:
  - Transaction → Balance update < 100ms
- [ ] Reward calculation overhead:
  - <50ms per reward calculation

**Day 40: Documentation & Rollout**
- [ ] Create user documentation:
  - How token economy works
  - How to earn tokens (automatic)
  - How to check balance
  - Token value and spending
- [ ] Create operator documentation:
  - Kafka topic management
  - Balance reconciliation procedures
  - Admin commands
- [ ] Create migration guide (Part 1 → Part 2)
- [ ] Deploy to production

---

### Part 2 Timeline

**Total Duration**: 4 weeks (20 working days, after Part 1 complete)

```
Week 5: Kafka Token Ledger      [Days 21-25]
Week 6: Reward Calculators       [Days 26-30]
Week 7: Token Spending & Quorum  [Days 31-35]
Week 8: Integration & Testing    [Days 36-40]
```

**Milestones**:
- ✅ End of Week 5: Token ledger operational, balances materialized
- ✅ End of Week 6: Rewards calculated and distributed automatically
- ✅ End of Week 7: Token spending integrated, balances tracked
- ✅ End of Week 8: Full token economy deployed to production

---

### Part 2 Success Criteria

**Functional Requirements**:
- [ ] Token transactions published to Kafka
- [ ] Balances materialized and cached
- [ ] STF contributions rewarded automatically
- [ ] Golden state contributions rewarded
- [ ] Pattern contributions rewarded
- [ ] LLM costs deducted from balance
- [ ] Quorum voting (token-weighted) ready for Phase 2

**Performance Requirements**:
- [ ] Transaction → balance update: <100ms
- [ ] Kafka throughput: >1000 transactions/sec
- [ ] Valkey cache hit rate: >80%
- [ ] Reward calculation: <50ms

**Economic Requirements**:
- [ ] Token value: 1 token = $0.001 USD
- [ ] Reward tiers validated (STF: 50-500, Golden: 200-1000, Pattern: 50-500)
- [ ] Self-sustaining: earnings ≥ spending for active contributors

**Observability**:
- [ ] Transaction history queryable (Kafka offset)
- [ ] Balance auditing (reconciliation script)
- [ ] Reward analytics (top contributors, total rewards)
- [ ] Spend analytics (most expensive models, cost trends)

**User Value**:
- [ ] Contributors earn tokens automatically (no manual submission)
- [ ] Tokens have intrinsic value (compute credits)
- [ ] Clear visibility into balance and transactions
- [ ] Fair reward distribution (quality-based)

---

## Dependencies and Prerequisites

### Part 1 Prerequisites

**Infrastructure** (already deployed):
- ✅ PostgreSQL database (`omninode_bridge` at `192.168.86.200:5436`)
- ✅ Existing agent execution logging (`agent_execution_logs` table)
- ✅ Pattern quality scorer (`agents/lib/pattern_quality_scorer.py`)
- ✅ Manifest injector (`agents/lib/manifest_injector.py`)

**Required Before Starting Part 1**:
- [ ] Verify PostgreSQL connection and schema access
- [ ] Confirm `AgentExecutionLogger` integration points
- [ ] Review existing debug intelligence tables
- [ ] Set up development environment

### Part 2 Prerequisites

**Infrastructure** (already deployed):
- ✅ Kafka/Redpanda (`192.168.86.200:9092` external, `omninode-bridge-redpanda:9092` internal)
- ✅ Valkey cache (Redis-compatible, `localhost:6379`)
- ✅ Docker Compose deployment framework

**Required Before Starting Part 2**:
- ✅ Part 1 fully complete and tested
- [ ] Verify Part 1 data flowing (STFs extracted, golden states created)
- [ ] Kafka topics created and configured
- [ ] Valkey cache operational
- [ ] Part 1 → Part 2 migration plan approved

---

## Migration Strategy

### Part 1 Deployment (No Breaking Changes)

Part 1 is **additive only** — no breaking changes to existing systems.

**Migration Steps**:
1. Deploy database schema (5 new tables)
2. Deploy code with Part 1 features (backward compatible)
3. Enable STF extraction (feature flag: `ENABLE_STF_EXTRACTION=true`)
4. Enable cost tracking (feature flag: `ENABLE_COST_TRACKING=true`)
5. Monitor for 1 week to verify data quality
6. Enable golden state nomination (feature flag: `ENABLE_GOLDEN_STATES=true`)

**Rollback Strategy**:
- Feature flags allow instant disable
- Database tables can be dropped (no foreign keys to existing tables)
- No impact on existing agent executions

### Part 2 Deployment (Requires Part 1)

Part 2 depends on Part 1 data (STFs, golden states, execution attempts).

**Migration Steps**:
1. Verify Part 1 data quality (STFs extracted, golden states nominated)
2. Create Kafka topics (`token.transactions.v1`, `token.balances.v1`)
3. Deploy token balance consumer service
4. Seed initial balances (optional: grant early adopter bonus)
5. Enable reward calculation (feature flag: `ENABLE_TOKEN_REWARDS=true`)
6. Enable token spending (feature flag: `ENABLE_TOKEN_SPENDING=true`)
7. Monitor token velocity and balance distribution
8. Adjust reward tiers if needed (configurable in `.env`)

**Rollback Strategy**:
- Feature flags allow instant disable
- Kafka topics retain all transactions (can replay)
- Valkey cache can be flushed (will rebuild from Kafka)
- No data loss (event sourcing)

---

## Testing Strategy

### Part 1 Testing

**Unit Tests**:
- Database models (Pydantic validation)
- STF extraction logic
- Quality score calculation
- Error pattern normalization
- Hash generation (SHA-256)

**Integration Tests**:
- End-to-end STF extraction and storage
- STF matching and recommendation
- Cost calculation and tracking
- Error→success mapping creation
- Golden state nomination and approval

**Performance Tests**:
- STF matching latency (<100ms for top 5)
- Database query performance (<50ms indexed lookups)
- Manifest injection overhead (<200ms)

**Test Data**:
- 50+ sample STFs (varied quality scores)
- 20+ error→success mappings
- 10+ golden states
- 5+ agent types with different execution patterns

### Part 2 Testing

**Unit Tests**:
- Reward calculation logic (STF, golden state, pattern)
- Token balance calculation
- Transaction event schema validation
- Novelty score calculation

**Integration Tests**:
- End-to-end transaction flow (earn → Kafka → balance update)
- Spend flow (LLM query → cost deduction → balance update)
- Kafka compaction (verify latest balance retained)
- Valkey cache (hit/miss scenarios)

**Load Tests**:
- 1000 transactions/sec (Kafka throughput)
- 10,000 balance queries/sec (Valkey cache)
- Concurrent reward calculations

**Economic Tests**:
- Verify self-sustaining economy (earnings ≥ spending for active users)
- Test reward tier fairness (quality-based distribution)
- Test token velocity (turnover rate)

---

## Rollout Plan

### Part 1 Rollout (Weeks 1-4)

**Week 1: Internal Alpha**
- Deploy to development environment
- Test with synthetic data
- Developer-only access

**Week 2: Private Beta**
- Deploy to staging environment
- Invite 5-10 power users
- Collect feedback on STF quality and relevance

**Week 3: Public Beta**
- Deploy to production (feature flags off by default)
- Enable for opted-in users
- Monitor data quality and performance

**Week 4: General Availability**
- Enable for all users (feature flags on by default)
- Announce debug intelligence enhancements
- Publish user documentation

### Part 2 Rollout (Weeks 5-8, after Part 1 stable)

**Week 5: Internal Alpha**
- Deploy token ledger to development
- Test reward calculations with Part 1 data
- Verify balance materialization

**Week 6: Private Beta**
- Deploy to staging environment
- Grant seed tokens to beta testers
- Test earning and spending flows

**Week 7: Public Beta**
- Deploy to production (feature flags off by default)
- Enable for opted-in users
- Monitor token velocity and balance distribution

**Week 8: General Availability**
- Enable for all users
- Announce token economy launch
- Publish token economy documentation
- Monitor for economic imbalances (adjust reward tiers if needed)

---

## Risk Mitigation

### Part 1 Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| STF extraction false positives | Medium | Medium | Quality score threshold (>0.5), manual approval workflow |
| Performance degradation | High | Low | Feature flags, manifest injection timeout, database indexes |
| Database schema conflicts | Medium | Low | Additive schema only, no foreign keys to existing tables |
| STF matching irrelevant | Medium | Medium | Similarity search tuning, user feedback loop |

### Part 2 Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Token inflation | High | Medium | Reward tier caps, quality thresholds, spending requirements |
| Kafka consumer lag | Medium | Low | Partition scaling, consumer group rebalancing, monitoring |
| Balance inconsistencies | High | Low | Event sourcing immutability, reconciliation script, audit log |
| Gaming reward system | Medium | Medium | Quality-based rewards, novelty checks, rate limiting |
| Insufficient token value | Medium | Medium | Adjust token→USD ratio, monitor earnings vs spending |

---

## Success Metrics

### Part 1 Metrics (Debug Intelligence)

**Adoption Metrics**:
- STFs extracted per day (target: >50)
- STF reuse rate (target: >30%)
- Golden states created per week (target: >10)
- Error→success mappings created per day (target: >20)

**Quality Metrics**:
- Average STF quality score (target: >0.7)
- STF recommendation relevance (user feedback, target: >70% helpful)
- Golden state approval rate (target: >80%)
- Error mapping confidence scores (target: >0.8 for top 10)

**Performance Metrics**:
- STF matching latency (target: <100ms p95)
- Manifest injection overhead (target: <200ms p95)
- Database query latency (target: <50ms p95)

**Business Metrics**:
- Cost savings from STF reuse (vs building from scratch)
- Time savings from error→success mappings
- Developer satisfaction (NPS survey)

### Part 2 Metrics (Token Economy)

**Adoption Metrics**:
- Active contributors (earned >0 tokens in last 7 days, target: >100)
- Token transactions per day (target: >500)
- Average balance per user (target: 1000-5000 tokens)

**Economic Metrics**:
- Token velocity (transactions/total supply, target: >0.1/day)
- Earnings vs spending ratio (target: 1.0-1.5 for active users)
- Top contributor concentration (target: <20% of rewards to top 10%)
- Reward distribution fairness (Gini coefficient, target: <0.5)

**Quality Metrics**:
- Average quality score of rewarded contributions (target: >0.7)
- Novelty rate of rewarded patterns (target: >60%)
- Golden state reuse rate (target: >40%)

**Performance Metrics**:
- Transaction→balance update latency (target: <100ms p95)
- Valkey cache hit rate (target: >80%)
- Kafka consumer lag (target: <1 second)

---

## Documentation Deliverables

### Part 1 Documentation

**User Documentation**:
- [ ] How debug intelligence works (STFs, golden states, error mappings)
- [ ] How to view your contributions (CLI tools)
- [ ] How to use STF recommendations
- [ ] FAQ and troubleshooting

**Operator Documentation**:
- [ ] Database schema reference
- [ ] Admin queries and analytics
- [ ] Performance tuning guide
- [ ] Backup and recovery procedures

**Developer Documentation**:
- [ ] API reference (`stf_extractor`, `golden_state_manager`)
- [ ] Integration guide (adding new STF types)
- [ ] Testing guide (fixtures, sample data)

### Part 2 Documentation

**User Documentation**:
- [ ] How the token economy works
- [ ] How to earn tokens (automatic)
- [ ] How to check balance and transactions
- [ ] Token value and spending
- [ ] FAQ and troubleshooting

**Operator Documentation**:
- [ ] Kafka topic management
- [ ] Balance reconciliation procedures
- [ ] Reward tier configuration
- [ ] Admin commands (grant tokens, adjust balances)

**Developer Documentation**:
- [ ] Token ledger API reference
- [ ] Reward calculator integration
- [ ] Testing guide (Kafka event fixtures)

---

## Next Steps

### Immediate Actions (Before Starting Part 1)

1. **Review and Approve Plan**
   - [ ] User review of this implementation plan
   - [ ] Confirm two-part approach (debug first, tokens second)
   - [ ] Approve timeline (3-4 weeks Part 1, 4 weeks Part 2)

2. **Environment Preparation**
   - [ ] Verify PostgreSQL access (`source .env && psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE}`)
   - [ ] Verify Kafka access (`192.168.86.200:9092`)
   - [ ] Verify Valkey access (`localhost:6379`)
   - [ ] Set up development branch (already on `claude/omninode-debug-rewards-clarification-011CUxhsawPLtZFyyC5capVP`)

3. **Day 1 Kickoff**
   - [ ] Create database migration script
   - [ ] Run migration in development
   - [ ] Verify schema created successfully
   - [ ] Begin Pydantic model development

### Transition to Part 2 (After Part 1 Complete)

1. **Part 1 Validation**
   - [ ] Review Part 1 metrics (STFs extracted, golden states created)
   - [ ] Verify data quality (quality scores, confidence metrics)
   - [ ] User acceptance testing
   - [ ] Performance benchmarks met

2. **Part 2 Planning**
   - [ ] Review Part 2 design with Part 1 learnings
   - [ ] Adjust reward tiers based on Part 1 data
   - [ ] Create Part 2 development branch
   - [ ] Kafka topic creation

3. **Part 2 Kickoff**
   - [ ] Begin Day 21 tasks (Kafka infrastructure)
   - [ ] Follow Part 2 timeline (Weeks 5-8)

---

## Appendix: Reference Documents

### Related Analysis Documents

1. **`docs/analysis/DEBUG_REWARDS_CLARIFICATION_ANALYSIS.md` (v2.0)**
   - Comprehensive feasibility analysis
   - Three initiatives: Debug Loop, Clarification, Rewards
   - Compute token model (v2.0 update)
   - Cost and timeline estimates

2. **`docs/analysis/P2P_CONTEXT_SHARING_MODEL.md` (v1.1)**
   - BitTorrent-like P2P architecture
   - 90% LLM cost reduction
   - Kafka token ledger (v1.1 update)
   - Dual earning paths: STFs + bandwidth sharing

3. **`docs/analysis/PATTERN_CONTRIBUTION_REWARDS.md` (v1.0)**
   - Automatic pattern extraction
   - Integration with existing PatternQualityScorer
   - Pattern type multipliers
   - Novelty scoring

### Architecture Documents

- **`CLAUDE.md`**: OmniClaude architecture reference
- **`config/README.md`**: Type-safe configuration framework
- **`deployment/README.md`**: Docker Compose deployment guide
- **`agents/polymorphic-agent.md`**: ONEX compliance and agent framework

### Database Schema Reference

- **Existing Tables**:
  - `agent_execution_logs` — Current execution tracking
  - `agent_manifest_injections` — Manifest traceability
  - `agent_routing_decisions` — Router performance

- **Part 1 Tables** (to be created):
  - `debug_transform_functions` — STF registry
  - `model_price_catalog` — LLM pricing
  - `debug_execution_attempts` — Enhanced correlation tracking
  - `debug_error_success_mappings` — Error→success confidence
  - `debug_golden_states` — Golden state registry

- **Part 2 Infrastructure** (Kafka topics):
  - `token.transactions.v1` — Immutable transaction log
  - `token.balances.v1` — Compacted balance materialization

---

**End of Implementation Plan**

**Version**: 1.0
**Last Updated**: 2025-11-09
**Next Review**: After Part 1 Week 1 milestone (Day 5)
**Owner**: OmniNode Development Team
**Status**: Ready for Part 1 Day 1 implementation
