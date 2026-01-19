# Pattern Contribution Rewards - Automatic Economic Incentives

**Date**: 2025-11-09
**Integration**: P2P Context-Sharing Model (Phase 3b extension)
**Existing Infrastructure**: Qdrant pattern storage + quality scoring

> **📊 Data Update (2025-11-12)**: This document was updated to reflect actual Qdrant pattern counts. Initial draft referenced ~120 patterns from outdated documentation. Current verified counts:
> - **archon_vectors**: 7,118 patterns (ONEX architectural templates and execution patterns)
> - **code_generation_patterns**: 8,571 patterns (Real Python implementations and code examples)
> - **Total**: 15,689+ patterns
>
> This 130x larger pattern base significantly strengthens the ROI case for pattern contribution rewards and demonstrates the value of the existing ecosystem.

---

## Data Sources

**Pattern inventory verified as of 2025-11-12**:

| Collection | Pattern Count | Data Type | Source |
|-----------|---------------|-----------|--------|
| `archon_vectors` | 7,118 patterns | ONEX architectural templates and execution patterns | Qdrant collection via archon-intelligence |
| `code_generation_patterns` | 8,571 patterns | Real Python implementations and code examples | Qdrant collection via archon-intelligence |
| **Total** | **15,689+ patterns** | Combined pattern library | Qdrant health checks + CLAUDE.md |

**Data Collection Methods**:
- Qdrant health checks: `curl http://localhost:6333/collections`
- Pattern quality scoring: `agents/lib/pattern_quality_scorer.py` (5 dimensions)
- Intelligence queries: Kafka event bus via archon-intelligence adapter
- Database metrics: 34 tables in `omninode_bridge` PostgreSQL database

**Documentation References**:
- `/Volumes/PRO-G40/Code/omniclaude/CLAUDE.md` - OmniClaude architecture and intelligence infrastructure
- `docs/PATTERN_DATA_INVESTIGATION_REPORT.md` - Detailed pattern inventory analysis
- `scripts/health_check.sh` - System health validation script

**Note on Historical Data**: Initial draft of this document (pre-2025-11-12) referenced ~120 patterns from outdated documentation. Current verified counts are 130x larger, significantly strengthening the ROI case for pattern contribution rewards.

---

## Executive Summary

**Vision**: Automatically reward users for contributing new patterns to the shared library. Whenever an agent creates a working solution, extract the pattern, score it for quality, and issue token rewards if it's novel and high-quality.

**Current State**: You already have:
- ✅ Pattern quality scorer (5 dimensions: completeness, documentation, ONEX compliance, metadata, complexity)
- ✅ Pattern storage in Qdrant (`archon_vectors`, `code_generation_patterns`)
- ✅ Pattern reuse system with similarity search
- ✅ 15,689+ patterns already stored (7,118 in archon_vectors + 8,571 in code_generation_patterns)

**New Component**: **Automatic pattern contribution rewards** that trigger when agents create novel, high-quality patterns.

---

## The Pattern Economy

### Three Token-Earning Paths

| Activity | How It Works | Tokens Earned | Frequency |
|----------|--------------|---------------|-----------|
| **1. Contribute STFs** (Phase 3a) | Submit transformation functions | 100-1000 | One-time + ongoing usage |
| **2. Share context** (Phase 3b) | Serve context to peers via P2P | 2/KB | Continuous passive income |
| **3. Contribute patterns** (NEW) | Agent extracts & stores reusable pattern | 50-500 | Automatic when working |

**Economic Model**: Users earn tokens **automatically** just by solving problems - the system extracts and rewards pattern contributions without manual submission.

---

## Current Pattern Infrastructure

### Qdrant Collections

**Two active pattern collections** (from CLAUDE.md):

| Collection | Purpose | Count | Quality Scored |
|-----------|---------|-------|----------------|
| `archon_vectors` | ONEX architectural templates and execution patterns | 7,118 | ✅ Yes |
| `code_generation_patterns` | Real Python implementations and code examples | 8,571 | ✅ Yes |

**Note**: The collections were reorganized from the previous three-collection structure (`execution_patterns`, `code_patterns`, `code_generation_patterns`) into the current two-collection architecture with significantly expanded pattern coverage.

### Pattern Quality Scorer

**Five dimensions** (from `agents/lib/pattern_quality_scorer.py`):

1. **Code Completeness** (0-1.0): Has meaningful code vs stubs
2. **Documentation Quality** (0-1.0): Docstrings, comments, type hints
3. **ONEX Compliance** (0-1.0): Follows ONEX architecture
4. **Metadata Richness** (0-1.0): Use cases, examples, node types
5. **Complexity Appropriateness** (0-1.0): Complexity matches use case

**Composite Score**: Weighted average
```python
composite_score = (
    0.30 * completeness +
    0.25 * documentation +
    0.20 * onex_compliance +
    0.15 * metadata_richness +
    0.10 * complexity
)
```

**Quality Thresholds**:
- **Excellent**: ≥0.9 (top-tier patterns)
- **Good**: ≥0.7 (solid, reusable patterns)
- **Fair**: ≥0.5 (basic patterns)
- **Poor**: <0.5 (needs improvement)

### Pattern Storage & Reuse

**PatternStorage** (`agents/lib/patterns/pattern_storage.py`):
- Stores patterns in Qdrant with vector embeddings
- Similarity search by embedding (cosine distance)
- Metadata filtering (pattern_type, confidence, quality)
- Usage statistics tracking (usage_count, last_used)

**PatternReuse** (`agents/lib/patterns/pattern_reuse.py`):
- Finds applicable patterns for generation context
- Example: Agent needs "Fahrenheit to Celsius" → searches Qdrant → finds verified baseline function
- Template adaptation with Jinja2
- Usage tracking updates

---

## Automatic Pattern Contribution Workflow

### Current Flow (No Rewards)

```
Agent creates code → Stores in Qdrant → Pattern available for reuse
                                              ↓
                                     (no economic incentive)
```

### Proposed Flow (With Rewards)

```
Agent creates code → Pattern extractor runs → Quality scorer evaluates
                                                      ↓
                                            Novelty checker (vs existing patterns)
                                                      ↓
                                      ┌───────────────┴──────────────┐
                                      │                               │
                              High quality + Novel              Low quality OR Duplicate
                                      │                               │
                         Store in Qdrant + Earn tokens        Store but no reward
                                      │
                         Kafka: token.transactions.v1
                         {"type": "earned", "amount": 50-500}
                                      │
                         Token balance updated automatically
```

### Implementation Steps

**1. Pattern Extraction Hook** (after agent execution)

Trigger pattern extraction whenever an agent:
- Writes a file
- Completes a task successfully
- Creates a function/class

**Location**: Add to `agents/lib/agent_execution_logger.py` → `complete()` method

**Pseudocode**:
```python
async def complete(self, status, quality_score):
    # Existing logging...

    # NEW: Extract patterns from execution
    if status == SUCCESS and quality_score > 0.7:
        patterns = await extract_patterns_from_execution(
            execution_id=self.execution_id,
            correlation_id=self.correlation_id
        )

        for pattern in patterns:
            reward = await process_pattern_contribution(
                pattern=pattern,
                contributor_peer_id=self.peer_id
            )

            if reward > 0:
                await publish_token_reward(
                    peer_id=self.peer_id,
                    amount=reward,
                    reason=f"pattern_contribution:{pattern.pattern_id}"
                )
```

**2. Novelty Checker** (deduplication)

Check if pattern is truly novel vs existing patterns in Qdrant:

```python
async def check_pattern_novelty(
    new_pattern: ModelCodePattern,
    embedding: List[float],
    similarity_threshold: float = 0.85
) -> tuple[bool, float]:
    """
    Check if pattern is novel (not a duplicate).

    Returns:
        (is_novel, max_similarity) - True if similarity < threshold
    """
    # Query Qdrant for similar patterns
    similar = await qdrant_client.search(
        collection_name="code_generation_patterns",
        query_vector=embedding,
        limit=5
    )

    if not similar:
        return (True, 0.0)

    max_similarity = max(hit.score for hit in similar)

    # Novel if less than 85% similar to any existing pattern
    is_novel = max_similarity < similarity_threshold

    return (is_novel, max_similarity)
```

**3. Reward Calculation** (based on quality + novelty)

```python
def calculate_pattern_reward(
    quality_score: float,
    novelty_score: float,
    pattern_type: str,
    complexity: float
) -> int:
    """
    Calculate token reward for pattern contribution.

    Factors:
    - Base reward by quality tier
    - Novelty multiplier (1.0 = completely unique, 0.5 = somewhat similar)
    - Pattern type multiplier (ONEX patterns worth more)
    - Complexity bonus (more complex = more valuable)

    Returns:
        Token amount (50-500 range)
    """
    # Base reward by quality
    if quality_score >= 0.9:
        base_reward = 300  # Excellent
    elif quality_score >= 0.7:
        base_reward = 150  # Good
    elif quality_score >= 0.5:
        base_reward = 50   # Fair
    else:
        return 0  # Poor quality, no reward

    # Novelty multiplier (more novel = higher multiplier)
    novelty_multiplier = 0.5 + (novelty_score * 0.5)  # 0.5-1.0 range

    # Pattern type multiplier
    type_multipliers = {
        "onex_effect": 1.3,
        "onex_compute": 1.3,
        "onex_reducer": 1.3,
        "onex_orchestrator": 1.5,  # Most valuable
        "utility": 1.0,
        "example": 0.8,
    }
    type_multiplier = type_multipliers.get(pattern_type, 1.0)

    # Complexity bonus (logarithmic, max 1.2x)
    complexity_bonus = 1.0 + (min(complexity, 0.8) * 0.25)

    # Final reward
    reward = int(
        base_reward * novelty_multiplier * type_multiplier * complexity_bonus
    )

    # Cap at 500 tokens per pattern
    return min(reward, 500)
```

**4. Kafka Event Publishing**

```python
async def publish_pattern_contribution_reward(
    peer_id: str,
    pattern_id: str,
    pattern_name: str,
    quality_score: float,
    novelty_score: float,
    reward_tokens: int
):
    """Publish pattern contribution reward event to Kafka."""

    event = {
        "transaction_id": str(uuid4()),
        "peer_id": peer_id,
        "transaction_type": "earned",
        "amount": reward_tokens,
        "reason": "pattern_contribution",
        "pattern_id": pattern_id,
        "pattern_name": pattern_name,
        "quality_score": quality_score,
        "novelty_score": novelty_score,
        "timestamp": datetime.now(UTC).isoformat()
    }

    await kafka_producer.send(
        topic="token.transactions.v1",
        value=json.dumps(event).encode()
    )
```

---

## Pattern Reuse & Earning Cycles

### Ongoing Revenue from Pattern Usage

**Initial contribution**: Earn 50-500 tokens (one-time)

**Ongoing usage**: Earn tokens whenever someone uses your pattern

**Usage tracking** (already implemented in `PatternStorage`):
```python
async def query_similar_patterns(...):
    # Find patterns
    matches = ...

    # Update usage stats
    for match in matches:
        await update_pattern_usage(
            pattern_id=match.pattern_id,
            usage_count=+1,
            last_used=datetime.now()
        )

    return matches
```

**Ongoing rewards** (NEW):
```python
async def track_pattern_usage_reward(
    pattern_id: str,
    pattern_author_peer_id: str,
    using_peer_id: str
):
    """
    Issue micro-reward when pattern is reused.

    - Pattern author earns 5 tokens per use
    - Using peer spends 5 tokens
    - This incentivizes creating high-quality, reusable patterns
    """
    # Earn for author
    await publish_token_transaction(
        peer_id=pattern_author_peer_id,
        transaction_type="earned",
        amount=5,
        reason=f"pattern_usage:{pattern_id}",
        counterparty_peer_id=using_peer_id
    )

    # Spend for user (optional - could be free to encourage reuse)
    # await publish_token_transaction(
    #     peer_id=using_peer_id,
    #     transaction_type="spent",
    #     amount=5,
    #     reason=f"pattern_usage:{pattern_id}",
    #     counterparty_peer_id=pattern_author_peer_id
    # )
```

**Economics**:
- High-quality pattern (0.9 score) → 300 tokens initial
- Pattern used 100 times → 500 more tokens (5 per use)
- **Total**: 800 tokens over lifetime
- Popular patterns become **passive income streams**

---

## Pattern Discovery UX

### Agent-Facing Pattern Library

**Before** (current): Agent must know what to search for
```python
# Agent needs to explicitly query patterns
patterns = await storage.query_similar_patterns(
    query_embedding=embedding,
    pattern_type="effect",
    min_confidence=0.7
)
```

**After** (proposed): Automatic pattern suggestions in agent prompts

**Example**: Agent receives task "Convert Fahrenheit to Celsius"

**System injects into prompt**:
```
AVAILABLE PATTERNS:

📊 Pattern: Temperature Conversion Utility
   Quality: ⭐⭐⭐⭐⭐ (0.93)
   Author: peer_abc123
   Usage Count: 47 times

   Description:
   Converts temperature between Fahrenheit, Celsius, and Kelvin with
   input validation and type safety.

   Code Preview:
   ```python
   def fahrenheit_to_celsius(temp_f: float) -> float:
       """Convert Fahrenheit to Celsius."""
       return (temp_f - 32) * 5/9
   ```

   [View full pattern] [Use this pattern] [Adapt pattern]

Cost: 5 tokens to use (supports pattern author)
```

**Agent can then**:
1. Use pattern as-is (copy code)
2. Adapt pattern to specific needs
3. Ignore and write from scratch

**Usage automatically tracked** → Pattern author earns 5 tokens

---

## Database Schema

### Pattern Contribution Tracking

**Extend existing `agent_intelligence_usage` table**:

```sql
-- Add pattern contribution fields
ALTER TABLE agent_intelligence_usage
    ADD COLUMN pattern_contribution_id UUID,
    ADD COLUMN pattern_quality_score NUMERIC(5,4),
    ADD COLUMN pattern_novelty_score NUMERIC(5,4),
    ADD COLUMN reward_tokens_earned INT DEFAULT 0;

CREATE INDEX idx_agent_intelligence_usage_contribution
    ON agent_intelligence_usage(pattern_contribution_id)
    WHERE pattern_contribution_id IS NOT NULL;
```

**New table: Pattern contributions** (optional - could use Kafka events only):

```sql
CREATE TABLE pattern_contributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Pattern identification
    pattern_id TEXT NOT NULL,
    pattern_name TEXT NOT NULL,
    pattern_type TEXT NOT NULL,

    -- Contributor
    contributor_peer_id TEXT NOT NULL,
    execution_id UUID, -- Links to agent_execution_logs
    correlation_id UUID,

    -- Quality metrics
    quality_score NUMERIC(5,4) NOT NULL,
    novelty_score NUMERIC(5,4) NOT NULL,
    completeness_score NUMERIC(5,4),
    documentation_score NUMERIC(5,4),
    onex_compliance_score NUMERIC(5,4),
    metadata_richness_score NUMERIC(5,4),
    complexity_score NUMERIC(5,4),

    -- Reward info
    reward_tokens_initial INT NOT NULL,
    reward_tokens_usage INT DEFAULT 0,
    total_reward_tokens INT GENERATED ALWAYS AS (reward_tokens_initial + reward_tokens_usage) STORED,

    -- Usage stats
    usage_count INT DEFAULT 0,
    last_used_at TIMESTAMPTZ,

    -- Qdrant storage
    qdrant_collection TEXT NOT NULL,
    qdrant_point_id UUID NOT NULL,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(qdrant_collection, qdrant_point_id)
);

CREATE INDEX idx_pattern_contributions_peer ON pattern_contributions(contributor_peer_id);
CREATE INDEX idx_pattern_contributions_quality ON pattern_contributions(quality_score DESC);
CREATE INDEX idx_pattern_contributions_usage ON pattern_contributions(usage_count DESC);
CREATE INDEX idx_pattern_contributions_reward ON pattern_contributions(total_reward_tokens DESC);
```

---

## Economics Summary

### Token Earning Comparison

| Activity | Frequency | Tokens/Unit | Daily Potential | Notes |
|----------|-----------|-------------|-----------------|-------|
| **STF Contribution** | One-time | 100-1000 | N/A | Requires manual submission |
| **Context Sharing** | Continuous | 2/KB | 200 (100KB/day) | Passive income, always on |
| **Pattern Contribution** | Automatic | 50-500 | 150-500 | Happens while working |
| **Pattern Usage Royalties** | Ongoing | 5/use | 50-500 | Passive income from popular patterns |

**Combined earning potential**: 400-1200 tokens/day for active contributor

### Token Spending

| Activity | Tokens Spent | Notes |
|----------|--------------|-------|
| **LLM Compute** | Variable | Based on usage |
| **Context Retrieval** | 2/KB | From peers |
| **Pattern Usage** | 5/use (optional) | Could make free to encourage adoption |

### Economic Balance

> **⚠️ ASPIRATIONAL SCENARIO**: The following is an illustrative example with **unvalidated assumptions**. Actual usage patterns will be measured during pilot program (Phase 3, Weeks 5-7) to calibrate token economics.

**Scenario**: Active developer (aspirational - not based on current usage data)

**Earns** (estimated):
- Solve 3 problems/day → extract 3 patterns → 450 tokens (avg 150/pattern)
  - *Assumption: 3 problems/day is unvalidated - actual rate to be measured*
- Share 100KB context → 200 tokens
  - *Assumption: 100KB/day is illustrative - actual sharing volume varies by user*
- 10 past patterns used by others → 50 tokens (5 each)
  - *Assumption: Pattern reuse rate to be validated during pilot*
- **Total earned**: 700 tokens/day *(illustrative - pending pilot validation)*

**Spends** (estimated):
- 50 LLM queries → 500 tokens
  - *Assumption: 50 queries/day is illustrative - actual usage varies widely*
- Retrieve 50KB context from peers → 100 tokens
  - *Assumption: Context retrieval patterns to be measured*
- Use 5 patterns from others → 25 tokens (optional)
  - *Assumption: Pattern usage rate to be validated*
- **Total spent**: 625 tokens/day *(illustrative - pending pilot validation)*

**Net**: +75 tokens/day = **surplus** (encourages participation)
  - *Note: Actual balance depends on token economics calibration (see Phase 3, Weeks 5-7)*
  - *Success criteria: >70% of contributors achieve net surplus (not yet validated)*

---

## Implementation Roadmap

### Phase 1: Basic Pattern Rewards (1-2 weeks)

**Deliverables**:
1. Pattern extraction hook in `agent_execution_logger.py`
2. Novelty checker using Qdrant similarity search
3. Reward calculator with quality/novelty scoring
4. Kafka event publishing for pattern contributions
5. Token balance updates via existing consumer

**Integration points**:
- Uses existing PatternQualityScorer
- Uses existing PatternStorage (Qdrant)
- Uses existing Kafka ledger (token.transactions.v1)

**Success metrics**:
- 10+ patterns contributed per day
- 80%+ novel (not duplicates)
- Average quality score >0.7
- Token rewards issued automatically

### Phase 2: Pattern Discovery UI (1 week)

**Deliverables**:
1. Pattern suggestions in agent prompts
2. Usage tracking with author attribution
3. Pattern preview/adaptation UI
4. Search by natural language ("convert F to C")

**Success metrics**:
- 50%+ pattern reuse rate (vs writing from scratch)
- 80%+ user satisfaction with suggestions
- 100+ pattern uses per day

### Phase 3: Usage Royalties (1 week)

**Deliverables**:
1. Track pattern usage events
2. Issue micro-rewards (5 tokens per use)
3. Leaderboard: Top pattern authors
4. Analytics: Most popular patterns

**Success metrics**:
- 20+ patterns earning royalties
- 500+ total pattern uses per day
- Average pattern earns 50+ tokens over lifetime

**Total**: 3-4 weeks for complete pattern economy

---

## Success Metrics

### Contribution Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Patterns contributed/day** | >20 | Count of new patterns in Qdrant |
| **Pattern novelty rate** | >80% | % patterns that are novel (not duplicates) |
| **Average pattern quality** | >0.75 | Mean quality score of contributed patterns |
| **Contributors with rewards** | >50 | Unique peers earning pattern tokens |

### Reuse Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Pattern reuse rate** | >50% | % of tasks using existing patterns |
| **Patterns with >10 uses** | >20% | % of patterns frequently reused |
| **User satisfaction** | >4/5 | Rating of pattern suggestions |
| **Search success rate** | >80% | % of queries finding relevant pattern |

### Economic Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Pattern rewards issued** | >10K tokens/day | Total tokens for pattern contributions |
| **Usage royalties issued** | >500 tokens/day | Total tokens for pattern reuse |
| **Top pattern earnings** | >1000 tokens | Highest-earning pattern lifetime |
| **Contributors with net surplus** | >70% | % of peers earning more than spending |

---

## Example: Full Cycle

### Scenario: Developer solves "Convert Fahrenheit to Celsius"

**Step 1**: Developer creates function
```python
def fahrenheit_to_celsius(temp_f: float) -> float:
    """Convert Fahrenheit to Celsius with validation."""
    if temp_f < -459.67:  # Absolute zero
        raise ValueError("Temperature below absolute zero")
    return (temp_f - 32) * 5/9
```

**Step 2**: Agent execution completes successfully
- Quality score: 0.88 (good)
- ONEX compliance: 0.85
- Documentation: 0.90
- Completeness: 0.85

**Step 3**: Pattern extracted automatically
- Pattern type: `utility`
- Embedding generated: `[0.123, 0.456, ...]`
- Stored in Qdrant: `code_generation_patterns`

**Step 4**: Novelty check
- Query similar patterns: `similarity < 0.85`
- Result: **Novel pattern** (no close matches)
- Novelty score: 0.92

**Step 5**: Reward calculated
```python
base_reward = 150  # Good quality (0.7-0.9)
novelty_multiplier = 0.5 + (0.92 * 0.5) = 0.96
type_multiplier = 1.0  # utility
complexity_bonus = 1.05  # low complexity

reward = 150 * 0.96 * 1.0 * 1.05 = 151 tokens
```

**Step 6**: Token earned automatically
- Kafka event published to `token.transactions.v1`
- Token balance updated: +151 tokens
- Pattern available in library

**Step 7**: Pattern used by others (ongoing)
- Pattern used 20 times in first week
- Author earns 5 tokens per use = 100 additional tokens
- **Total earnings**: 251 tokens

**Step 8**: Pattern becomes popular
- Used 100 times over 6 months
- Total royalties: 500 tokens
- **Lifetime earnings**: 651 tokens from one contribution

---

## Integration with Existing Systems

### Manifest Injector Integration

**Current**: Manifest includes 15,689+ patterns from Qdrant (7,118 from archon_vectors + 8,571 from code_generation_patterns)

**Enhancement**: Include pattern author attribution and earning potential

```yaml
AVAILABLE PATTERNS (15,689 patterns from archon_vectors + code_generation_patterns):

Top Patterns by Quality (filtered for this context):
  1. ⭐⭐⭐⭐⭐ Node State Management (0.95) - By peer_abc123
     Used 127 times | Earned author 935 tokens

  2. ⭐⭐⭐⭐⭐ Async Event Bus (0.93) - By peer_def456
     Used 89 times | Earned author 695 tokens

Recently Added Patterns (user-contributed):
  - Temperature Conversion (0.88) - By peer_xyz789
    Just added! 5 tokens to use, supports new contributor

Note: Most patterns are system/seed patterns. User contributions tracked separately.
```

### Pattern Quality Backfill

**Current**: `scripts/backfill_pattern_quality.py` scores existing patterns

**Enhancement**: Issue retroactive rewards for high-quality existing patterns

```python
# Backfill script enhancement
for pattern in existing_patterns:
    quality_score = scorer.score_pattern(pattern)

    if quality_score.composite_score >= 0.7:
        # Issue retroactive reward for quality patterns
        reward = calculate_pattern_reward(
            quality_score=quality_score.composite_score,
            novelty_score=1.0,  # All existing patterns assumed novel at contribution time
            pattern_type=pattern['pattern_type'],
            complexity=pattern['complexity']
        )

        await issue_retroactive_reward(
            contributor_peer_id=pattern['author_id'],
            pattern_id=pattern['pattern_id'],
            reward_tokens=reward
        )
```

---

## Conclusion

The pattern contribution reward system **completes the three-sided token economy**:

1. **STF Contributions** (Phase 3a): One-time manual submissions
2. **Context Sharing** (Phase 3b): Continuous P2P bandwidth sharing
3. **Pattern Contributions** (Phase 3c): **Automatic rewards for working code**

**Key innovation**: Users earn tokens **just by working** - no manual submission required. The system automatically:
- Extracts patterns from successful executions
- Scores quality across 5 dimensions
- Checks novelty vs existing patterns
- Issues token rewards immediately
- Tracks ongoing usage royalties

**Economic alignment**:
- High-quality patterns earn more (quality multiplier)
- Novel patterns earn more (novelty multiplier)
- ONEX-compliant patterns earn most (type multiplier)
- Popular patterns earn ongoing royalties (usage rewards)

**Network effects**:
- More contributors → more patterns → more value
- More usage → more royalties → more incentive to contribute quality
- Better patterns → higher adoption → higher author earnings

**This transforms OmniClaude into a self-improving knowledge economy where quality contributions are automatically rewarded.**

---

**Document Version**: 1.0
**Last Updated**: 2025-11-09
**Integration**: P2P Context-Sharing Model (Phase 3c)
**Status**: Proposal for Implementation
**Implementation Effort**: 3-4 weeks (parallel with Phase 3b)
