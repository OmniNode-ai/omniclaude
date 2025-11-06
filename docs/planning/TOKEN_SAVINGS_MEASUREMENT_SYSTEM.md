# Token Savings Measurement System

**Date**: 2025-11-06
**Status**: Architecture Proposal - Ready for Implementation
**Context**: Measure and report token/cost savings from intelligence + agent systems without A/B testing

---

## Executive Summary

**Goal**: Quantify token savings and ROI from OmniClaude's intelligence infrastructure for customer reporting.

**Challenge**: Can't run A/B tests (same task with/without system) for every workflow.

**Solution**: Counterfactual estimation + intervention tracking to measure savings without benchmarks.

### Key Metrics

| Savings Source | Typical Saving | Measurement Method |
|----------------|----------------|-------------------|
| **Hook corrections** | 3-5x tokens | Error cycle prevention tracking |
| **Manifest intelligence** | 30-50% tokens | Baseline estimation vs actual |
| **Pattern discovery** | 10-50K tokens | Pattern usage attribution |
| **Debug intelligence** | 2-10x tokens | Failure avoidance tracking |
| **Agent specialization** | 20-40% tokens | Specialist vs generalist comparison |
| **Context optimization** | 50-70% tokens | Heredoc → direct write tracking |

**Total estimated savings**: **60-80% reduction in tokens** across typical workflows

---

## Token Savings Sources

### 1. Hook Corrections (Error Cycle Prevention)

**What we save**:
- Wrong passwords/URLs → corrected by hooks before reaching Claude
- Prevents error → retry → fix cycle (3-5x tokens)

**Example**:
```
Without hook:
  User: "Connect to postgres at 192.168.86.200:5436"
  Claude: Uses wrong password from docs
  Error: "Authentication failed"
  Claude: Tries alternative
  Error: "Authentication failed"
  User: "Use password from .env"
  Claude: Reads .env, retries
  Success: (total: 15K tokens)

With hook:
  User: "Connect to postgres at 192.168.86.200:5436"
  Hook: Injects correct credentials from .env
  Claude: Uses correct password
  Success: (total: 3K tokens)

Savings: 12K tokens (80%)
```

**Measurement**:
- Track hook interventions (password corrections, URL fixes, etc.)
- Estimate typical error cycle cost (5-15K tokens)
- Multiply by intervention count

**Database schema**:
```sql
CREATE TABLE token_savings_hook_interventions (
    id BIGSERIAL PRIMARY KEY,
    correlation_id UUID NOT NULL,
    intervention_type VARCHAR(100) NOT NULL,  -- 'password_correction', 'url_fix', etc.
    intervention_description TEXT,
    estimated_tokens_saved INT NOT NULL,  -- Based on typical error cycle
    confidence FLOAT NOT NULL,  -- How confident in estimate (0.0-1.0)
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 2. Manifest Intelligence (Context Upfront)

**What we save**:
- Provides relevant context (patterns, schemas, debug intelligence) upfront
- Reduces back-and-forth questions and exploration
- Prevents trial-and-error implementations

**Example**:
```
Without manifest:
  User: "Implement ONEX node with PostgreSQL persistence"
  Claude: "What's ONEX? Let me search..."
  Claude: "How should I structure the node?"
  Claude: "What's the database schema?"
  Claude: Implements, gets wrong
  User: "No, use ONEX patterns"
  Claude: Fixes implementation
  (total: 40K tokens)

With manifest:
  User: "Implement ONEX node with PostgreSQL persistence"
  Manifest: Provides ONEX patterns, DB schemas, working examples
  Claude: Implements correctly first time
  (total: 12K tokens)

Savings: 28K tokens (70%)
```

**Measurement**:
- Track manifest injections and their content size
- Estimate baseline task complexity (heuristic or historical)
- Compare actual tokens to estimated baseline
- Attribution: "tokens saved by having patterns upfront"

**Database schema**:
```sql
CREATE TABLE token_savings_manifest_impact (
    id BIGSERIAL PRIMARY KEY,
    correlation_id UUID NOT NULL,
    manifest_injection_id BIGINT REFERENCES agent_manifest_injections(id),
    task_description TEXT NOT NULL,
    task_complexity_score FLOAT NOT NULL,  -- 0.0-1.0 (simple to complex)

    -- Actual usage
    actual_tokens_used INT NOT NULL,
    actual_iterations INT NOT NULL,  -- How many back-and-forth cycles

    -- Estimated baseline (without manifest)
    estimated_baseline_tokens INT NOT NULL,
    estimated_baseline_iterations INT NOT NULL,

    -- Savings
    estimated_tokens_saved INT NOT NULL,
    estimated_cost_saved_usd DECIMAL(10,4) NOT NULL,

    -- Attribution
    patterns_provided INT NOT NULL,  -- Number of patterns in manifest
    schemas_provided INT NOT NULL,   -- Number of schemas in manifest
    debug_intelligence_provided BOOLEAN NOT NULL,

    confidence FLOAT NOT NULL,  -- How confident in estimate
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3. Pattern Discovery Savings

**What we save**:
- Provides working implementations from Qdrant (120+ patterns)
- Avoids research + experimentation cycles
- Typical pattern discovery: 10-50K tokens

**Example**:
```
Without patterns:
  User: "How do I implement ONEX Effect node?"
  Claude: "Let me think about the architecture..."
  Claude: Tries approach 1 (wrong)
  User: "That's not quite right"
  Claude: Tries approach 2 (closer)
  User: "We have a pattern for this"
  Claude: Finds pattern, implements correctly
  (total: 35K tokens)

With patterns:
  User: "How do I implement ONEX Effect node?"
  Manifest: Provides NodeStateManagerEffect pattern
  Claude: Implements from pattern
  (total: 8K tokens)

Savings: 27K tokens (77%)
```

**Measurement**:
- Track pattern usage (when patterns from manifest are applied)
- Estimate discovery cost for each pattern type
- Attribution: "tokens saved by having pattern available"

**Database schema**:
```sql
CREATE TABLE token_savings_pattern_usage (
    id BIGSERIAL PRIMARY KEY,
    correlation_id UUID NOT NULL,
    pattern_name VARCHAR(255) NOT NULL,
    pattern_source VARCHAR(100) NOT NULL,  -- 'execution_patterns', 'code_patterns'
    pattern_confidence FLOAT NOT NULL,

    -- Usage context
    task_description TEXT NOT NULL,
    pattern_applied BOOLEAN NOT NULL,  -- Did agent actually use it?

    -- Savings estimate
    estimated_discovery_tokens INT NOT NULL,  -- Typical: 10-50K
    estimated_tokens_saved INT NOT NULL,
    confidence FLOAT NOT NULL,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 4. Debug Intelligence (Failure Avoidance)

**What we save**:
- Provides history of similar workflows (successes + failures)
- Avoids repeating known failures
- Typical failure cycle: 2-10x tokens

**Example**:
```
Without debug intelligence:
  User: "Write to file without reading first"
  Claude: Uses Write tool
  Error: "Must read file first"
  Claude: Uses Read, then Write
  Success (total: 12K tokens)

With debug intelligence:
  Manifest: "FAILED APPROACH: Write without Read (permission error)"
  User: "Write to file"
  Claude: Reads first, then writes
  Success (total: 4K tokens)

Savings: 8K tokens (67%)
```

**Measurement**:
- Track debug intelligence usage (when failures are avoided)
- Compare to historical failure rate
- Estimate typical failure cycle cost

**Database schema**:
```sql
CREATE TABLE token_savings_failure_avoidance (
    id BIGSERIAL PRIMARY KEY,
    correlation_id UUID NOT NULL,
    failure_pattern TEXT NOT NULL,  -- What failure was avoided
    similar_past_failures INT NOT NULL,  -- Count from workflow_events

    -- Evidence of avoidance
    avoided_approach TEXT NOT NULL,  -- What agent didn't try
    successful_approach TEXT NOT NULL,  -- What agent did instead

    -- Savings estimate
    estimated_failure_cost_tokens INT NOT NULL,  -- Typical: 5-20K
    estimated_tokens_saved INT NOT NULL,
    confidence FLOAT NOT NULL,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 5. Agent Specialization Savings

**What we save**:
- Specialized agents are more efficient than generic
- Domain expertise reduces trial-and-error
- Typical saving: 20-40% tokens

**Example**:
```
Without specialization (generic agent):
  User: "Fix database query performance"
  Agent: General troubleshooting approach
  Agent: Tries multiple strategies
  Agent: Eventually finds solution
  (total: 25K tokens)

With specialization (agent-debug-database):
  User: "Fix database query performance"
  Agent: Database-specific debugging workflow
  Agent: Immediately checks indexes, query plan
  Agent: Finds solution quickly
  (total: 12K tokens)

Savings: 13K tokens (52%)
```

**Measurement**:
- Compare specialized agent performance to polymorphic baseline
- Track agent routing decisions and outcomes
- Estimate efficiency gain from specialization

**Database schema**:
```sql
CREATE TABLE token_savings_agent_specialization (
    id BIGSERIAL PRIMARY KEY,
    correlation_id UUID NOT NULL,
    agent_name VARCHAR(255) NOT NULL,
    agent_domain VARCHAR(100) NOT NULL,
    task_description TEXT NOT NULL,

    -- Performance comparison
    actual_tokens_used INT NOT NULL,
    estimated_generic_tokens INT NOT NULL,  -- What polymorphic would use

    -- Savings
    estimated_tokens_saved INT NOT NULL,
    estimated_cost_saved_usd DECIMAL(10,4) NOT NULL,

    -- Attribution
    specialization_benefit TEXT,  -- Why specialist was better
    confidence FLOAT NOT NULL,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 6. Context Optimization Savings

**What we save**:
- Heredoc → direct write: 2-5x reduction
- Minimal logging: 5-10x reduction in reports
- Total: 50-70% reduction

**Example**:
```
Without optimization (heredoc):
  Claude: "I'll create the file..."
  Claude: "cat <<'EOF' > file.py"
  Claude: (1000 lines of heredoc)
  Claude: "EOF"
  Claude: "File created successfully"
  (total: 6K tokens)

With optimization (direct write):
  Claude: Uses Write tool directly
  Claude: (minimal logging)
  (total: 2K tokens)

Savings: 4K tokens (67%)
```

**Measurement**:
- Track tool usage patterns (Write vs Bash+heredoc)
- Track logging verbosity
- Compare to baseline expectations

**Database schema**:
```sql
CREATE TABLE token_savings_context_optimization (
    id BIGSERIAL PRIMARY KEY,
    correlation_id UUID NOT NULL,
    optimization_type VARCHAR(100) NOT NULL,  -- 'direct_write', 'minimal_logging', etc.

    -- Before/after comparison
    baseline_approach TEXT NOT NULL,  -- What would have been done
    optimized_approach TEXT NOT NULL,  -- What was actually done

    -- Token comparison
    baseline_tokens INT NOT NULL,
    actual_tokens INT NOT NULL,
    tokens_saved INT NOT NULL,

    confidence FLOAT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Counterfactual Estimation Models

### Model 1: Error Cycle Cost

**Typical error cycle**:
1. Wrong attempt (3-5K tokens)
2. Error message (0.5K tokens)
3. Analysis (2-3K tokens)
4. Correction attempt (3-5K tokens)
5. Success (1-2K tokens)

**Total**: 10-15K tokens per error cycle

**Hook intervention savings** = Error cycles prevented × 10-15K

### Model 2: Pattern Discovery Cost

**Typical pattern discovery**:
1. Research (5-10K tokens) - reading docs, examples
2. Experimentation (10-20K tokens) - trying different approaches
3. Refinement (5-10K tokens) - fixing issues
4. Validation (2-5K tokens) - testing

**Total**: 20-45K tokens per pattern

**Pattern provision savings** = Patterns provided × 20-45K

### Model 3: Debug Intelligence Cost

**Typical failure scenario**:
1. Attempt (3-5K tokens)
2. Failure (0.5K tokens)
3. Debugging (5-10K tokens)
4. Retry (3-5K tokens)

**Total**: 12-20K tokens per failure

**Failure avoidance savings** = Failures avoided × 12-20K

### Model 4: Specialist Efficiency Gain

**Generic agent**: 100% baseline
**Domain specialist**: 60-80% of baseline (20-40% savings)

**Specialization savings** = Baseline estimate × (1 - 0.7) = 30% average

### Model 5: Context Optimization

**Heredoc overhead**: 2-5x tokens vs direct write
**Logging overhead**: 5-10x tokens for verbose reports

**Optimization savings** = 50-70% reduction

---

## Implementation Architecture

### 1. Token Savings Tracker Service

```python
# services/token_savings_tracker.py

from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

class SavingsSource(Enum):
    HOOK_CORRECTION = "hook_correction"
    MANIFEST_INTELLIGENCE = "manifest_intelligence"
    PATTERN_USAGE = "pattern_usage"
    FAILURE_AVOIDANCE = "failure_avoidance"
    AGENT_SPECIALIZATION = "agent_specialization"
    CONTEXT_OPTIMIZATION = "context_optimization"

@dataclass
class TokenSavingsEstimate:
    source: SavingsSource
    correlation_id: str
    estimated_tokens_saved: int
    estimated_cost_saved_usd: float
    confidence: float  # 0.0-1.0
    attribution: Dict[str, any]  # Source-specific details

class TokenSavingsTracker:
    """Track and estimate token savings across all system features."""

    def __init__(self, db_connection):
        self.db = db_connection
        self.models = EstimationModels()

    async def track_hook_intervention(
        self,
        correlation_id: str,
        intervention_type: str,
        description: str
    ) -> TokenSavingsEstimate:
        """Track token savings from hook corrections."""

        # Estimate error cycle cost based on intervention type
        error_cycle_cost = self.models.error_cycle_cost(intervention_type)

        # Store in database
        await self.db.execute("""
            INSERT INTO token_savings_hook_interventions
            (correlation_id, intervention_type, intervention_description,
             estimated_tokens_saved, confidence)
            VALUES ($1, $2, $3, $4, $5)
        """, correlation_id, intervention_type, description,
            error_cycle_cost, 0.8)

        return TokenSavingsEstimate(
            source=SavingsSource.HOOK_CORRECTION,
            correlation_id=correlation_id,
            estimated_tokens_saved=error_cycle_cost,
            estimated_cost_saved_usd=self._tokens_to_cost(error_cycle_cost),
            confidence=0.8,
            attribution={"intervention_type": intervention_type}
        )

    async def track_manifest_impact(
        self,
        correlation_id: str,
        manifest_injection_id: int,
        task_description: str,
        actual_tokens: int,
        patterns_provided: int,
        schemas_provided: int,
        debug_intelligence: bool
    ) -> TokenSavingsEstimate:
        """Track token savings from manifest intelligence."""

        # Estimate baseline cost (what task would have cost without manifest)
        task_complexity = self._estimate_task_complexity(task_description)
        baseline_tokens = self.models.baseline_task_cost(
            task_complexity,
            patterns_provided,
            schemas_provided,
            debug_intelligence
        )

        tokens_saved = max(0, baseline_tokens - actual_tokens)
        confidence = self._confidence_from_complexity(task_complexity)

        # Store in database
        await self.db.execute("""
            INSERT INTO token_savings_manifest_impact
            (correlation_id, manifest_injection_id, task_description,
             task_complexity_score, actual_tokens_used, estimated_baseline_tokens,
             estimated_tokens_saved, estimated_cost_saved_usd, patterns_provided,
             schemas_provided, debug_intelligence_provided, confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """, correlation_id, manifest_injection_id, task_description,
            task_complexity, actual_tokens, baseline_tokens, tokens_saved,
            self._tokens_to_cost(tokens_saved), patterns_provided,
            schemas_provided, debug_intelligence, confidence)

        return TokenSavingsEstimate(
            source=SavingsSource.MANIFEST_INTELLIGENCE,
            correlation_id=correlation_id,
            estimated_tokens_saved=tokens_saved,
            estimated_cost_saved_usd=self._tokens_to_cost(tokens_saved),
            confidence=confidence,
            attribution={
                "patterns_provided": patterns_provided,
                "schemas_provided": schemas_provided,
                "baseline_tokens": baseline_tokens,
                "actual_tokens": actual_tokens
            }
        )

    async def track_pattern_usage(
        self,
        correlation_id: str,
        pattern_name: str,
        pattern_applied: bool,
        task_description: str
    ) -> TokenSavingsEstimate:
        """Track token savings from pattern discovery avoidance."""

        # Estimate discovery cost for this pattern
        discovery_cost = self.models.pattern_discovery_cost(pattern_name)
        tokens_saved = discovery_cost if pattern_applied else 0

        # Store in database
        await self.db.execute("""
            INSERT INTO token_savings_pattern_usage
            (correlation_id, pattern_name, task_description, pattern_applied,
             estimated_discovery_tokens, estimated_tokens_saved, confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, correlation_id, pattern_name, task_description, pattern_applied,
            discovery_cost, tokens_saved, 0.7)

        return TokenSavingsEstimate(
            source=SavingsSource.PATTERN_USAGE,
            correlation_id=correlation_id,
            estimated_tokens_saved=tokens_saved,
            estimated_cost_saved_usd=self._tokens_to_cost(tokens_saved),
            confidence=0.7,
            attribution={"pattern_name": pattern_name, "applied": pattern_applied}
        )

    async def track_failure_avoidance(
        self,
        correlation_id: str,
        failure_pattern: str,
        avoided_approach: str,
        successful_approach: str
    ) -> TokenSavingsEstimate:
        """Track token savings from debug intelligence."""

        # Estimate failure cycle cost
        failure_cost = self.models.failure_cycle_cost(failure_pattern)

        # Store in database
        await self.db.execute("""
            INSERT INTO token_savings_failure_avoidance
            (correlation_id, failure_pattern, avoided_approach,
             successful_approach, estimated_failure_cost_tokens,
             estimated_tokens_saved, confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, correlation_id, failure_pattern, avoided_approach,
            successful_approach, failure_cost, failure_cost, 0.75)

        return TokenSavingsEstimate(
            source=SavingsSource.FAILURE_AVOIDANCE,
            correlation_id=correlation_id,
            estimated_tokens_saved=failure_cost,
            estimated_cost_saved_usd=self._tokens_to_cost(failure_cost),
            confidence=0.75,
            attribution={"failure_pattern": failure_pattern}
        )

    def _tokens_to_cost(self, tokens: int, model: str = "claude-opus") -> float:
        """Convert tokens to USD cost."""
        # Claude Opus: $15/1M input tokens, $75/1M output tokens
        # Average: ~$30/1M tokens (accounting for input/output mix)
        return (tokens / 1_000_000) * 30.0

    def _estimate_task_complexity(self, task_description: str) -> float:
        """Estimate task complexity (0.0-1.0) from description."""
        # Simple heuristic: length + keywords
        # Can be improved with ML model
        length_score = min(len(task_description) / 1000, 1.0)

        complex_keywords = [
            "implement", "architecture", "refactor", "optimize",
            "debug", "analyze", "design", "integrate"
        ]
        keyword_score = sum(
            1 for kw in complex_keywords
            if kw in task_description.lower()
        ) / len(complex_keywords)

        return (length_score + keyword_score) / 2

    def _confidence_from_complexity(self, complexity: float) -> float:
        """Higher complexity = lower confidence in estimate."""
        return 1.0 - (complexity * 0.3)  # 0.7-1.0 range
```

### 2. Estimation Models

```python
# services/token_savings_models.py

class EstimationModels:
    """Models for estimating baseline token costs."""

    def error_cycle_cost(self, intervention_type: str) -> int:
        """Estimate tokens for typical error cycle."""

        costs = {
            "password_correction": 12000,  # Auth errors are expensive
            "url_fix": 8000,               # Connection errors
            "env_var_fix": 10000,          # Config errors
            "path_correction": 6000,       # File not found errors
            "default": 10000
        }

        return costs.get(intervention_type, costs["default"])

    def pattern_discovery_cost(self, pattern_name: str) -> int:
        """Estimate tokens to discover pattern manually."""

        # Pattern complexity tiers
        if "orchestrator" in pattern_name.lower():
            return 45000  # Complex architecture
        elif "effect" in pattern_name.lower():
            return 30000  # I/O patterns
        elif "compute" in pattern_name.lower():
            return 25000  # Algorithm patterns
        elif "reducer" in pattern_name.lower():
            return 28000  # State patterns
        else:
            return 20000  # Simple patterns

    def failure_cycle_cost(self, failure_pattern: str) -> int:
        """Estimate tokens for typical failure cycle."""

        # Analysis based on failure type
        if "permission" in failure_pattern.lower():
            return 15000  # Permission debugging is expensive
        elif "network" in failure_pattern.lower():
            return 12000  # Connection issues
        elif "syntax" in failure_pattern.lower():
            return 5000   # Quick fixes
        else:
            return 10000  # Average

    def baseline_task_cost(
        self,
        complexity: float,
        patterns_provided: int,
        schemas_provided: int,
        debug_intelligence: bool
    ) -> int:
        """Estimate baseline task cost without intelligence."""

        # Base cost from complexity
        base = int(complexity * 50000)  # 0-50K base

        # Add discovery costs
        pattern_discovery = patterns_provided * 25000  # 25K per pattern
        schema_discovery = schemas_provided * 5000     # 5K per schema
        debug_discovery = 15000 if debug_intelligence else 0

        total = base + pattern_discovery + schema_discovery + debug_discovery

        return total
```

### 3. Reporting & Analytics

```python
# services/token_savings_reporter.py

class TokenSavingsReporter:
    """Generate token savings reports for customers."""

    async def generate_project_report(
        self,
        project_name: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """Generate comprehensive savings report for project."""

        savings_by_source = await self.db.fetch_all("""
            SELECT
                'hook_correction' as source,
                COUNT(*) as intervention_count,
                SUM(estimated_tokens_saved) as total_tokens_saved
            FROM token_savings_hook_interventions
            WHERE correlation_id IN (
                SELECT correlation_id FROM agent_routing_decisions
                WHERE project_name = $1 AND created_at BETWEEN $2 AND $3
            )
            GROUP BY source

            UNION ALL

            SELECT
                'manifest_intelligence' as source,
                COUNT(*) as intervention_count,
                SUM(estimated_tokens_saved) as total_tokens_saved
            FROM token_savings_manifest_impact
            WHERE correlation_id IN (
                SELECT correlation_id FROM agent_routing_decisions
                WHERE project_name = $1 AND created_at BETWEEN $2 AND $3
            )
            GROUP BY source

            UNION ALL

            SELECT
                'pattern_usage' as source,
                COUNT(*) as intervention_count,
                SUM(estimated_tokens_saved) as total_tokens_saved
            FROM token_savings_pattern_usage
            WHERE correlation_id IN (
                SELECT correlation_id FROM agent_routing_decisions
                WHERE project_name = $1 AND created_at BETWEEN $2 AND $3
            )
            GROUP BY source

            -- Add other sources...
        """, project_name, start_date, end_date)

        total_savings = sum(row['total_tokens_saved'] for row in savings_by_source)
        total_cost_savings = (total_savings / 1_000_000) * 30.0  # $30/1M avg

        return {
            "project_name": project_name,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "total_tokens_saved": total_savings,
            "total_cost_saved_usd": round(total_cost_savings, 2),
            "savings_by_source": [
                {
                    "source": row['source'],
                    "interventions": row['intervention_count'],
                    "tokens_saved": row['total_tokens_saved'],
                    "cost_saved_usd": round((row['total_tokens_saved'] / 1_000_000) * 30.0, 2)
                }
                for row in savings_by_source
            ],
            "top_savings_events": await self._top_savings_events(project_name, start_date, end_date)
        }

    async def generate_customer_dashboard(self, customer_id: str) -> Dict:
        """Generate customer-facing savings dashboard."""

        # Roll up all projects for customer
        projects = await self.db.fetch_all("""
            SELECT DISTINCT project_name
            FROM agent_routing_decisions
            WHERE customer_id = $1
        """, customer_id)

        total_savings = 0
        project_reports = []

        for project in projects:
            report = await self.generate_project_report(
                project['project_name'],
                datetime.now() - timedelta(days=30),
                datetime.now()
            )
            project_reports.append(report)
            total_savings += report['total_tokens_saved']

        return {
            "customer_id": customer_id,
            "period": "Last 30 days",
            "total_tokens_saved": total_savings,
            "total_cost_saved_usd": round((total_savings / 1_000_000) * 30.0, 2),
            "savings_percentage": await self._calculate_savings_percentage(customer_id),
            "projects": project_reports,
            "roi_metrics": await self._calculate_roi(customer_id)
        }

    async def _calculate_savings_percentage(self, customer_id: str) -> float:
        """Calculate percentage of tokens saved vs baseline."""

        actual_tokens = await self.db.fetch_val("""
            SELECT SUM(actual_tokens_used)
            FROM token_savings_manifest_impact
            WHERE correlation_id IN (
                SELECT correlation_id FROM agent_routing_decisions
                WHERE customer_id = $1
            )
        """, customer_id)

        baseline_tokens = await self.db.fetch_val("""
            SELECT SUM(estimated_baseline_tokens)
            FROM token_savings_manifest_impact
            WHERE correlation_id IN (
                SELECT correlation_id FROM agent_routing_decisions
                WHERE customer_id = $1
            )
        """, customer_id)

        if not baseline_tokens or baseline_tokens == 0:
            return 0.0

        savings_pct = ((baseline_tokens - actual_tokens) / baseline_tokens) * 100
        return round(savings_pct, 1)
```

---

## Integration Points

### 1. Hook Integration

```python
# claude_hooks/user-prompt-submit.sh (add tracking)

# After correcting password/URL
python3 "${HOOKS_LIB}/track_token_savings.py" \
    --correlation-id "$CORRELATION_ID" \
    --source "hook_correction" \
    --intervention-type "password_correction" \
    --description "Corrected PostgreSQL password from .env"
```

### 2. Manifest Injection Integration

```python
# agents/lib/manifest_injector.py (add tracking)

async def inject_manifest(self, user_request: str, correlation_id: str):
    # ... existing manifest generation ...

    # Track token savings
    await self.savings_tracker.track_manifest_impact(
        correlation_id=correlation_id,
        manifest_injection_id=manifest_id,
        task_description=user_request,
        actual_tokens=self._count_tokens(final_response),
        patterns_provided=len(patterns),
        schemas_provided=len(schemas),
        debug_intelligence=bool(debug_intelligence)
    )
```

### 3. Agent Router Integration

```python
# agents/lib/agent_router.py (add tracking)

async def route(self, user_request: str, correlation_id: str):
    # ... existing routing ...

    if selected_agent != "polymorphic-agent":
        # Track specialization savings
        await self.savings_tracker.track_agent_specialization(
            correlation_id=correlation_id,
            agent_name=selected_agent,
            agent_domain=agent_domain,
            task_description=user_request,
            actual_tokens=0,  # Will be updated later
            estimated_generic_tokens=self._estimate_generic_cost(user_request)
        )
```

---

## Dashboard & Reporting

### Customer Dashboard (Web UI)

```
╔════════════════════════════════════════════════════════════════╗
║  OmniClaude Token Savings Dashboard                            ║
║  Project: omniclaude-production                                ║
║  Period: Last 30 days                                          ║
╚════════════════════════════════════════════════════════════════╝

┌────────────────────────────────────────────────────────────────┐
│ Summary                                                        │
├────────────────────────────────────────────────────────────────┤
│  Total Tokens Saved:        3,450,000 tokens                  │
│  Total Cost Saved:          $103.50 USD                       │
│  Savings Percentage:        68%                               │
│  Tasks Completed:           247                               │
│  Average Savings/Task:      13,967 tokens ($0.42)            │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ Savings by Source                                              │
├────────────────────────────────────────────────────────────────┤
│  ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇ Manifest Intelligence    1,450,000 ($43.50) │
│  ▇▇▇▇▇▇▇▇▇▇ Pattern Discovery             980,000 ($29.40)   │
│  ▇▇▇▇▇▇▇ Hook Corrections                 650,000 ($19.50)   │
│  ▇▇▇▇▇ Failure Avoidance                  420,000 ($12.60)   │
│  ▇▇▇ Agent Specialization                 280,000 ($8.40)    │
│  ▇▇ Context Optimization                  170,000 ($5.10)    │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ Top Savings Events                                             │
├────────────────────────────────────────────────────────────────┤
│  1. ONEX Architecture Implementation                           │
│     Patterns provided upfront saved pattern discovery          │
│     Saved: 45,000 tokens ($1.35) - 72% confidence            │
│                                                                │
│  2. PostgreSQL Connection Error Prevention                     │
│     Hook corrected password before error cycle                 │
│     Saved: 12,000 tokens ($0.36) - 85% confidence            │
│                                                                │
│  3. Database Schema Query                                      │
│     Manifest provided schemas, avoided exploration             │
│     Saved: 8,500 tokens ($0.26) - 78% confidence             │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ ROI Analysis                                                   │
├────────────────────────────────────────────────────────────────┤
│  System Cost:               $50/month (infrastructure)         │
│  Savings This Month:        $103.50                           │
│  Net Benefit:               $53.50                            │
│  ROI:                       107%                               │
│  Payback Period:            15 days                           │
└────────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: Database Schema (1 day)

**Tasks**:
1. Create 6 token savings tables
2. Add indexes for performance
3. Add foreign key constraints
4. Test schema

**Deliverable**: SQL migration script

### Phase 2: Estimation Models (2 days)

**Tasks**:
1. Implement `EstimationModels` class
2. Calibrate model parameters (error cycle costs, pattern discovery costs)
3. Add confidence scoring
4. Test models with historical data

**Deliverable**: `token_savings_models.py`

### Phase 3: Tracking Service (3 days)

**Tasks**:
1. Implement `TokenSavingsTracker` service
2. Add tracking methods for all 6 sources
3. Add database persistence
4. Test end-to-end tracking

**Deliverable**: `token_savings_tracker.py`

### Phase 4: Integration (3 days)

**Tasks**:
1. Integrate with hooks (password corrections, URL fixes)
2. Integrate with manifest injector
3. Integrate with agent router
4. Integrate with pattern discovery
5. Test all integration points

**Deliverable**: Tracking working across all components

### Phase 5: Reporting (2 days)

**Tasks**:
1. Implement `TokenSavingsReporter`
2. Create project-level reports
3. Create customer-level dashboards
4. Add export functionality (CSV, PDF)

**Deliverable**: `token_savings_reporter.py`

### Phase 6: Dashboard UI (3 days)

**Tasks**:
1. Create web dashboard (FastAPI + React)
2. Add visualization (charts, graphs)
3. Add filtering and date ranges
4. Mobile-responsive design

**Deliverable**: Customer-facing dashboard

### Phase 7: Documentation & Rollout (1 day)

**Tasks**:
1. Document API endpoints
2. Create customer guide
3. Add configuration options
4. Roll out to production

**Deliverable**: Production-ready system

**Total**: 15 days

---

## Validation & Confidence

### Validation Strategies

1. **Historical Comparison**
   - Compare estimates to known benchmarks
   - Adjust models based on real data
   - Continuous calibration

2. **Confidence Scoring**
   - High confidence (0.8-1.0): Direct measurements (hook corrections)
   - Medium confidence (0.6-0.8): Model-based estimates (pattern discovery)
   - Low confidence (0.4-0.6): Complex estimates (manifest impact)

3. **Conservative Estimates**
   - Use lower bounds for savings estimates
   - Better to under-promise and over-deliver
   - Adjust upward with more data

4. **A/B Testing (Optional)**
   - Run occasional benchmarks for validation
   - Compare estimates to actual measurements
   - Fine-tune models

### Confidence Intervals

```python
# Example: Pattern discovery savings
estimate = 25000  # tokens
confidence = 0.7  # 70% confidence
range = (estimate * 0.7, estimate * 1.3)  # 17.5K - 32.5K tokens

# Report with range
"Estimated savings: 25,000 tokens (17,500 - 32,500 range, 70% confidence)"
```

---

## Expected Outcomes

### Quantitative

| Metric | Target |
|--------|--------|
| **Total token savings tracked** | 80-90% of actual savings |
| **Reporting accuracy** | ±20% of true value |
| **Customer visibility** | 100% (all projects) |
| **Dashboard uptime** | >99% |

### Qualitative

1. ✅ **Customer ROI visibility**: Clear demonstration of value
2. ✅ **Feature attribution**: Know which features save most tokens
3. ✅ **Continuous improvement**: Data-driven optimization
4. ✅ **Marketing material**: Real savings numbers for sales
5. ✅ **Product decisions**: Prioritize high-impact features

---

## Example Report Output

```json
{
  "project_name": "omniclaude-production",
  "period": {
    "start": "2025-10-01T00:00:00Z",
    "end": "2025-10-31T23:59:59Z"
  },
  "total_tokens_saved": 3450000,
  "total_cost_saved_usd": 103.50,
  "savings_percentage": 68.0,
  "tasks_completed": 247,
  "average_savings_per_task": 13967,
  "savings_by_source": [
    {
      "source": "manifest_intelligence",
      "interventions": 247,
      "tokens_saved": 1450000,
      "cost_saved_usd": 43.50,
      "percentage_of_total": 42.0
    },
    {
      "source": "pattern_usage",
      "interventions": 89,
      "tokens_saved": 980000,
      "cost_saved_usd": 29.40,
      "percentage_of_total": 28.4
    },
    {
      "source": "hook_correction",
      "interventions": 54,
      "tokens_saved": 650000,
      "cost_saved_usd": 19.50,
      "percentage_of_total": 18.8
    }
  ],
  "top_savings_events": [
    {
      "correlation_id": "abc-123",
      "task": "ONEX Architecture Implementation",
      "tokens_saved": 45000,
      "cost_saved_usd": 1.35,
      "source": "manifest_intelligence",
      "confidence": 0.72
    }
  ],
  "roi_metrics": {
    "system_cost_monthly": 50.00,
    "savings_this_month": 103.50,
    "net_benefit": 53.50,
    "roi_percentage": 107.0,
    "payback_period_days": 15
  }
}
```

---

## Next Steps

1. Review and approve architecture
2. Prioritize implementation phases
3. Calibrate estimation models with historical data
4. Begin Phase 1 (database schema)
5. Integrate tracking across all components

---

## Questions for User

### Q1: Estimation Model Calibration

Should we calibrate models using historical data from existing workflows?
- **Option A**: Start with conservative estimates, adjust over time
- **Option B**: Run benchmark tests on sample tasks
- **Option C**: Use industry averages

**Recommendation**: **Option A** (conservative, adjust with real data)

### Q2: Confidence Thresholds

What minimum confidence level should we report to customers?
- **Option A**: Report all estimates (with confidence scores)
- **Option B**: Only report high-confidence estimates (>0.7)
- **Option C**: Report ranges instead of point estimates

**Recommendation**: **Option C** (ranges provide clearer expectations)

### Q3: Dashboard Deployment

Where should the customer dashboard be hosted?
- **Option A**: Integrated into existing OmniClaude dashboard
- **Option B**: Standalone dashboard (separate domain)
- **Option C**: API-only (customers build their own dashboards)

**Recommendation**: **Option A** (integrated for better UX)

---

**Last Updated**: 2025-11-06
**Documentation Version**: 1.0.0
**Status**: Ready for Implementation
