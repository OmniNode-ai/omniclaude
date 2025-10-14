# Context Recovery Implementation Plan
## Intelligent Quorum Feedback Parsing with Langextract Integration

**Created:** 2025-10-11
**Status:** Planning
**Estimated Effort:** 10 hours
**Priority:** High
**Goal:** Enable automatic context recovery when AI quorum validation fails, reducing manual intervention and improving token efficiency

---

## Executive Summary

This plan implements an intelligent context recovery system that automatically gathers missing context when AI quorum validation fails. By integrating the existing langextract semantic analysis service, the system can parse vague quorum feedback into structured context requests, automatically gather the needed information, and retry validation - all without manual intervention.

**Key Benefits:**
- **Automated Recovery:** System handles 80%+ of context failures without user intervention
- **Intelligent Parsing:** Langextract extracts concepts, themes, and domains from free-form feedback
- **Token Efficiency:** Reduces wasted tokens from failed workflows by recovering automatically
- **Better UX:** Fewer "quorum failed" dead ends for users

---

## Problem Statement

### Current Failure Mode

```
User: "coordinate workflow to review debug loop design..."
↓
Phase 1: Context Gathering (✓ Success - 117ms)
↓
Phase 2: Task Decomposition + AI Quorum
↓
Quorum: 55% confidence - FAIL
Reasoning: "Task needs ONEX architecture context"
↓
System: STOPS ❌
↓
Manual Intervention: Claude steps in, creates subtasks manually
↓
Result: Test FAILED - No token metrics captured
```

**Problems:**
1. **Vague Feedback:** "needs ONEX architecture context" - what specifically?
2. **No Recovery:** System just stops, wasting all previous work
3. **Manual Overhead:** Requires Claude to interpret and fix
4. **No Metrics:** Can't measure token savings if test fails

### Specific Example (User's Test Case)

**Task:** Review 17-section debug loop design document and adapt to ONEX architecture

**Quorum Feedback (55% confidence):**
> "This task requires understanding of ONEX architecture patterns, specifically Node type conventions (Effect, Compute, Reducer, Orchestrator), database schema design patterns, and integration with existing hook_events table structure."

**What We Need To Parse:**
- **Concepts:** ONEX architecture, Node types, database schema, hook_events
- **Domains:** Architecture, Database Design, Integration Patterns
- **File Suggestions:** ONEX_PATTERNS.md, DEBUG_LOOP_SCHEMA.md, migrations/*.sql
- **Priority:** Which context is critical (P1) vs helpful (P2)?

---

## Proposed Solution

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│              Workflow Executor                              │
│  (workflow_executor.py)                                     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Phase 2: Task Decomposition
                     ↓
┌─────────────────────────────────────────────────────────────┐
│         ValidatedTaskArchitect                              │
│  validate_with_quorum_and_recover()                         │
└────────────┬────────────────────────────────────────────────┘
             │
             │ Quorum Fails (confidence < 0.75)
             ↓
┌─────────────────────────────────────────────────────────────┐
│         ContextRecoveryManager (NEW)                        │
│  • parse_context_request() via langextract                  │
│  • gather_missing_context()                                 │
│  • merge_context()                                          │
└────────────┬────────────────────────────────────────────────┘
             │
             │ Langextract Semantic Analysis
             ↓
┌─────────────────────────────────────────────────────────────┐
│         Langextract Service                                 │
│  http://localhost:8156                                       │
│  • Extracts concepts, themes, domains                       │
│  • Returns confidence scores                                │
│  • Identifies patterns                                      │
└────────────┬────────────────────────────────────────────────┘
             │
             │ Structured Context Requests
             ↓
┌─────────────────────────────────────────────────────────────┐
│         Context Gathering                                   │
│  • Read suggested files (via Read tool)                     │
│  • Ask Claude Code for concepts (via callback)              │
│  • Search for examples (via Grep tool)                      │
└────────────┬────────────────────────────────────────────────┘
             │
             │ Enhanced Context
             ↓
┌─────────────────────────────────────────────────────────────┐
│         Retry Quorum Validation                             │
│  With enhanced task context                                 │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

#### 1. Enhanced Quorum Response

**File:** `agents/parallel_execution/validated_task_architect.py`

```python
class QuorumResult(BaseModel):
    """Enhanced with structured feedback"""
    confidence: float
    pass_status: bool
    reasoning: str

    # NEW: Structured context requests
    missing_context: Optional[List[Dict[str, Any]]] = None
    failure_category: Optional[str] = None  # "missing_context", "bad_decomposition", etc.
    suggestions: Optional[List[str]] = None  # Specific file/concept suggestions
```

**Changes:**
- Update AI quorum prompt to return structured JSON
- Include failure categorization
- Provide specific suggestions when possible

#### 2. Context Recovery Manager

**File:** `agents/parallel_execution/context_recovery.py` (NEW)

```python
class ContextRecoveryManager:
    """
    Manages automatic context gathering for failed quorum validations.

    Features:
    - Langextract integration for semantic parsing
    - File suggestion mapping
    - Context type detection (file vs concept)
    - Priority-based gathering
    - Token budget enforcement
    - Repeat failure detection
    """

    async def parse_context_request(
        self, quorum_reasoning: str
    ) -> List[ContextRequest]:
        """Use langextract to parse vague feedback into structured requests"""

    async def gather_missing_context(
        self, context_requests: List[ContextRequest]
    ) -> Dict[str, Any]:
        """Gather specific context from files, concepts, examples"""

    async def recover_from_quorum_failure(
        self, quorum_result: QuorumResult, current_context: Dict,
        decomposed_tasks: DecomposedTasks
    ) -> Tuple[bool, Optional[DecomposedTasks]]:
        """Main recovery orchestration"""
```

**Dependencies:**
- `ClientLangextractHttp` from omniarchon (already exists)
- Pydantic models for structured requests
- Project file index (optional enhancement)

#### 3. Workflow Integration

**File:** `agents/parallel_execution/workflow_executor.py`

```python
# In execute_workflow()

# Phase 2: Task decomposition with recovery
recovery_manager = ContextRecoveryManager(
    max_retries=2,
    token_budget=50000,
    langextract_url="http://localhost:8156"
)

for attempt in range(recovery_manager.max_retries + 1):
    quorum_result = task_architect.validate_with_quorum(decomposed_tasks)

    if quorum_result.pass_status:
        break

    # Attempt automatic recovery
    success, enhanced_tasks = await recovery_manager.recover_from_quorum_failure(
        quorum_result=quorum_result,
        current_context=context,
        decomposed_tasks=decomposed_tasks
    )

    if success:
        decomposed_tasks = enhanced_tasks
        continue
    else:
        # Recovery failed - check if user intervention needed
        if quorum_result.failure_category == "missing_context":
            user_context = await ask_user_for_context(quorum_result)
            if user_context:
                decomposed_tasks = enhance_with_user_context(decomposed_tasks, user_context)
                continue

        # Abort workflow
        return {"status": "failed", "reason": "quorum_validation_failed"}
```

#### 4. Langextract Integration

**No new code needed** - reuse existing client:

```python
from sys import path
path.insert(0, "/Volumes/PRO-G40/Code/omniarchon/services/intelligence/src/services/pattern_learning/phase2_matching")

from client_langextract_http import ClientLangextractHttp
```

**Semantic Analysis Usage:**

```python
async with ClientLangextractHttp(base_url="http://localhost:8156") as client:
    result = await client.analyze_semantic(
        content=quorum_reasoning,
        context="AI quorum feedback on task decomposition",
        min_confidence=0.6
    )

    # result.concepts: List[SemanticConcept] with confidence scores
    # result.themes: List[SemanticTheme] with keywords
    # result.domains: List[SemanticDomain] for categorization
    # result.patterns: List[SemanticPattern] for structural analysis
```

---

## Implementation Phases

### Phase 1: Foundation (3 hours)

**Deliverables:**
1. `context_recovery.py` with core classes
2. Enhanced `QuorumResult` model
3. Basic file suggestion mapping
4. Unit tests for context parsing

**Tasks:**
- [ ] Create `ContextRequest` Pydantic model
- [ ] Implement `ContextRecoveryManager.__init__()`
- [ ] Add domain→file mapping dictionary
- [ ] Test langextract client connection
- [ ] Write 5 unit tests for parsing logic

**Success Criteria:**
- Langextract client connects successfully
- Can parse sample quorum feedback into >=3 context requests
- File suggestions map correctly to project structure
- Tests pass with 100% coverage

### Phase 2: Context Gathering (3 hours)

**Deliverables:**
1. File reading integration
2. Concept explanation via Claude Code callback
3. Example search via Grep
4. Token budget enforcement
5. Integration tests

**Tasks:**
- [ ] Implement `gather_missing_context()`
- [ ] Add file existence checks
- [ ] Integrate with Read tool for file loading
- [ ] Add token counting for budget enforcement
- [ ] Write 8 integration tests

**Success Criteria:**
- Can read suggested files automatically
- Token budget prevents context explosion
- Handles missing files gracefully
- Tests cover all context types (file, concept, example)

### Phase 3: Workflow Integration (2 hours)

**Deliverables:**
1. Enhanced `workflow_executor.py` with recovery loop
2. Retry logic with exponential backoff (removed - we don't want delay)
3. User escalation for unrecoverable failures
4. Performance metrics

**Tasks:**
- [ ] Add recovery loop to Phase 2
- [ ] Implement repeat failure detection
- [ ] Add user prompt for unrecoverable cases
- [ ] Track metrics (attempts, success rate, token usage)
- [ ] Write end-to-end test

**Success Criteria:**
- Workflow retries up to 2 times automatically
- User prompt appears only when auto-recovery fails
- Metrics captured for token savings analysis
- End-to-end test passes with real quorum

### Phase 4: Testing & Validation (2 hours)

**Deliverables:**
1. Test suite (15+ tests)
2. Performance benchmarks
3. Documentation
4. Token savings analysis

**Tasks:**
- [ ] Write comprehensive test suite
- [ ] Benchmark langextract parsing speed
- [ ] Document all public APIs
- [ ] Run user's original test case
- [ ] Calculate actual token savings

**Success Criteria:**
- All tests pass (>=95% coverage)
- Langextract parsing <500ms average
- Documentation complete
- Original test case now succeeds automatically
- Token savings measured and documented

---

## File Changes

### New Files

1. **`agents/parallel_execution/context_recovery.py`** (~400 lines)
   - `ContextRecoveryManager` class
   - `ContextRequest` model
   - Domain/file mapping logic
   - Langextract integration

2. **`agents/parallel_execution/test_context_recovery.py`** (~300 lines)
   - Unit tests for parsing
   - Integration tests for gathering
   - Mock langextract responses
   - Edge case coverage

### Modified Files

1. **`agents/parallel_execution/validated_task_architect.py`** (+50 lines)
   - Enhanced `QuorumResult` model
   - Update quorum prompt for structured responses
   - Add `validate_with_quorum_and_recover()` method

2. **`agents/parallel_execution/workflow_executor.py`** (+80 lines)
   - Add recovery loop in Phase 2
   - Import `ContextRecoveryManager`
   - Add retry logic and metrics
   - User escalation handling

3. **`agents/parallel_execution/pyproject.toml`** (+2 lines)
   - Add langextract client dependency path
   - Add any new package requirements

### Configuration Files

1. **`.env`** (+2 lines)
   ```bash
   LANGEXTRACT_SERVICE_URL=http://localhost:8156
   CONTEXT_RECOVERY_MAX_RETRIES=2
   ```

---

## Testing Strategy

### Unit Tests (10 tests)

**File:** `test_context_recovery.py`

```python
class TestContextRecoveryManager:
    async def test_parse_simple_feedback(self):
        """Test parsing straightforward feedback"""

    async def test_parse_complex_feedback(self):
        """Test parsing multi-domain feedback"""

    async def test_file_suggestion_mapping(self):
        """Test domain→file mapping logic"""

    async def test_priority_assignment(self):
        """Test context request prioritization"""

    async def test_token_budget_enforcement(self):
        """Test token budget prevents overload"""

    async def test_repeat_failure_detection(self):
        """Test detection of same issue twice"""

    async def test_context_type_detection(self):
        """Test file vs concept classification"""

    async def test_langextract_connection_failure(self):
        """Test graceful degradation when langextract is down"""

    async def test_empty_context_requests(self):
        """Test when langextract returns no concepts"""

    async def test_max_retries_exceeded(self):
        """Test abort after max recovery attempts"""
```

### Integration Tests (5 tests)

```python
class TestContextRecoveryIntegration:
    async def test_full_recovery_flow(self):
        """Test complete recovery from quorum failure"""

    async def test_file_gathering(self):
        """Test automatic file reading"""

    async def test_concept_explanation(self):
        """Test concept explanation via Claude callback"""

    async def test_workflow_integration(self):
        """Test integration with workflow_executor"""

    async def test_user_escalation(self):
        """Test fallback to user prompt"""
```

### Performance Benchmarks

```python
async def benchmark_langextract_parsing():
    """Target: <500ms average"""

async def benchmark_full_recovery():
    """Target: <2s for complete recovery cycle"""

async def benchmark_token_usage():
    """Measure token overhead of context gathering"""
```

### Real-World Test Case

**The User's Original Test:**

```python
async def test_debug_loop_design_review():
    """
    Original test that failed at 55% confidence.
    Should now pass with automatic context recovery.
    """
    task_request = {
        "action": "coordinate workflow",
        "task_description": "Review 17-section debug loop design document and adapt to ONEX architecture",
        "project_path": "/Volumes/PRO-G40/Code/omniclaude",
        "additional_context": "Focus on database schema, state management, and integration patterns"
    }

    result = await execute_workflow(task_request)

    # Should succeed now with auto-recovery
    assert result["status"] == "completed"
    assert "deliverables" in result

    # Measure token savings
    claude_tokens = result["metrics"]["claude_code_tokens"]
    cheaper_tokens = result["metrics"]["cheaper_model_tokens"]
    savings = calculate_token_savings(claude_tokens, cheaper_tokens)

    print(f"Token Savings: ${savings:.2f}")
```

---

## Success Criteria

### Primary Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Auto-Recovery Rate** | >=80% | % of context failures resolved without user intervention |
| **Parsing Accuracy** | >=90% | % of context requests that are relevant and correct |
| **Performance** | <2s | Time from quorum failure to retry with enhanced context |
| **Token Efficiency** | <5K tokens | Token overhead for context recovery per attempt |
| **Test Coverage** | >=95% | Code coverage for new components |

### Secondary Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Langextract Latency** | <500ms | Average time for semantic analysis |
| **File Suggestion Accuracy** | >=70% | % of suggested files that exist and are relevant |
| **Repeat Failure Detection** | 100% | % of repeat issues caught before retry |
| **User Escalation Rate** | <20% | % of failures requiring user input |

### User's Goal: Token Savings Calculation

**Formula:**
```
Total Workflow Tokens = Phase 1 (Context) + Phase 2 (Quorum) + Phase 3 (Execution)

Without Recovery:
- Phase 2 fails → Entire workflow aborted
- Wasted tokens = Phase 1 + Phase 2
- Manual intervention = Unknown additional tokens

With Recovery:
- Phase 2 fails → Auto-recover → Retry (succeeds)
- Total tokens = Phase 1 + Phase 2 (attempt 1) + Phase 2 (attempt 2) + Phase 3
- Saved tokens = Manual intervention cost - Recovery cost

Savings = (Manual Fix Tokens - Recovery Overhead) / Total Workflow Tokens
```

**Example (User's Test Case):**

| Scenario | Tokens | Cost ($) |
|----------|--------|----------|
| **Phase 1 (Context)** | 5,000 | $0.15 |
| **Phase 2 Attempt 1 (Failed)** | 8,000 | $0.24 |
| **Manual Fix (Claude)** | 15,000 | $0.45 |
| **Phase 2 Attempt 2 (Auto-Recovery)** | 3,000 | $0.09 |
| **Phase 2 Attempt 2 (Retry)** | 8,000 | $0.24 |
| **Phase 3 (Execution)** | 25,000 | $0.75 |
| **TOTAL (Without Recovery)** | 28,000 (aborted) | $0.84 (wasted) |
| **TOTAL (With Recovery)** | 49,000 (completed) | $1.47 |
| **Savings** | Workflow completes! | - |

**Key Insight:** Without recovery, you waste $0.84 and get NO deliverables. With recovery, you spend $1.47 and get COMPLETE deliverables. The real savings is **avoiding complete workflow failure**.

---

## Risk Mitigation

### Risk 1: Langextract Service Unavailable

**Mitigation:**
- Circuit breaker in `ClientLangextractHttp` (already implemented)
- Fallback to simple keyword matching if langextract fails
- Health check before attempting recovery
- User escalation if service is down

**Fallback Logic:**
```python
try:
    result = await langextract_client.analyze_semantic(reasoning)
except LangextractUnavailableError:
    # Fallback to keyword-based parsing
    result = parse_with_keywords(reasoning)
```

### Risk 2: Suggested Files Don't Exist

**Mitigation:**
- File existence check before reading
- Fuzzy matching to find similar files
- Log missing files for analysis
- Don't fail if some files missing

**Implementation:**
```python
for request in context_requests:
    if not os.path.exists(request.suggestion):
        # Try fuzzy match
        similar = find_similar_files(request.suggestion)
        if similar:
            request.suggestion = similar[0]
        else:
            logger.warning(f"File not found: {request.suggestion}")
```

### Risk 3: Token Budget Exceeded

**Mitigation:**
- Track token usage per context request
- Summarize large files instead of including full text
- Priority-based gathering (P1 only if budget tight)
- Hard cap at 50K tokens

**Implementation:**
```python
def gather_with_budget(requests, budget):
    gathered = {}
    used_tokens = 0

    for request in sorted_by_priority(requests):
        content = read_context(request)
        tokens = count_tokens(content)

        if used_tokens + tokens > budget:
            # Summarize instead of full text
            content = summarize(content, max_tokens=budget - used_tokens)
            tokens = count_tokens(content)

        gathered[request.id] = content
        used_tokens += tokens

    return gathered
```

### Risk 4: Repeat Failures (Recovery Doesn't Help)

**Mitigation:**
- Track reasoning text from each attempt
- Detect identical or very similar feedback
- Escalate to user immediately on repeat
- Max 2 automatic retries

**Implementation:**
```python
if is_repeat_failure(current_reasoning, previous_attempts):
    logger.warning("Same context issue repeated - escalating")
    return await escalate_to_user(quorum_result)
```

### Risk 5: Parsing Accuracy Too Low

**Mitigation:**
- Confidence threshold filtering (min 0.6)
- Manual review of suggested files during testing
- Project-specific domain mapping
- Continuous improvement via feedback loop

**Quality Checks:**
```python
# Only use high-confidence concepts
concepts = [c for c in result.concepts if c.confidence > 0.7]

# Validate against known project structure
requests = validate_against_project(context_requests)
```

---

## Token Savings Analysis

### Baseline (Without Recovery)

**User's Test Case:**
1. Phase 1: Context gathering (5K tokens, $0.15)
2. Phase 2: Quorum validation fails (8K tokens, $0.24)
3. **Workflow aborted - no deliverables**
4. Manual fix by Claude (15K tokens, $0.45)
5. Re-run entire workflow (46K tokens, $1.38)

**Total:** 74K tokens, $2.22, ~30 minutes manual intervention

### With Auto-Recovery

**Same Test Case:**
1. Phase 1: Context gathering (5K tokens, $0.15)
2. Phase 2 Attempt 1: Quorum fails (8K tokens, $0.24)
3. **Auto-recovery:** Langextract parsing + file reading (3K tokens, $0.09)
4. Phase 2 Attempt 2: Quorum passes (8K tokens, $0.24)
5. Phase 3: Execution (25K tokens, $0.75)

**Total:** 49K tokens, $1.47, no manual intervention

### Savings Calculation

| Metric | Without Recovery | With Recovery | Savings |
|--------|------------------|---------------|---------|
| **Total Tokens** | 74,000 | 49,000 | 25,000 (34%) |
| **Total Cost** | $2.22 | $1.47 | $0.75 (34%) |
| **Manual Time** | 30 minutes | 0 minutes | 30 minutes |
| **Success Rate** | 0% (aborted) | 100% (completed) | ✓ Workflow completes |

**Key Insight:** The biggest savings is **avoiding workflow failure**. Without recovery, you waste tokens and get nothing. With recovery, the workflow completes successfully with fewer total tokens.

### ROI Analysis

**Investment:**
- 10 hours implementation (~$1,500 at $150/hr)
- Ongoing: ~100ms latency per quorum validation

**Return:**
- Prevents ~$0.75 per failed workflow
- Saves 30 minutes manual intervention per failure
- Enables token metrics capture for cost analysis

**Break-even:**
- 2,000 workflows with context failures
- Or: 50 hours of saved manual intervention

**Expected Usage:**
- ~20% of workflows may have context issues
- ~10 workflows per day
- ~2 context failures per day
- ROI: 3-6 months

---

## Dependencies

### Required Services

1. **Langextract Service**
   - URL: `http://localhost:8156`
   - Health check: `GET /health`
   - Semantic analysis: `POST /analyze/semantic`
   - Must be running before workflow execution

2. **PostgreSQL Database**
   - URL: `localhost:5436`
   - Database: `omninode_bridge`
   - For state persistence and metrics

### Python Packages

```toml
# pyproject.toml additions
[tool.poetry.dependencies]
httpx = "^0.28.1"  # Already exists
pybreaker = "^1.0.0"  # For circuit breaker (via langextract)
pydantic = "^2.0.0"  # Already exists
```

### External Code

```python
# Langextract client from omniarchon
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniarchon/services/intelligence/src/services/pattern_learning/phase2_matching")
from client_langextract_http import ClientLangextractHttp
```

---

## Implementation Checklist

### Phase 1: Foundation ✓
- [ ] Create `context_recovery.py`
- [ ] Define `ContextRequest` model
- [ ] Implement `ContextRecoveryManager.__init__()`
- [ ] Add domain→file mapping
- [ ] Test langextract connection
- [ ] Write 5 unit tests
- [ ] Verify tests pass

### Phase 2: Context Gathering ✓
- [ ] Implement `parse_context_request()`
- [ ] Implement `gather_missing_context()`
- [ ] Add file reading logic
- [ ] Add token budget enforcement
- [ ] Handle missing files gracefully
- [ ] Write 8 integration tests
- [ ] Verify tests pass

### Phase 3: Workflow Integration ✓
- [ ] Enhance `QuorumResult` model
- [ ] Add recovery loop to `workflow_executor.py`
- [ ] Implement repeat failure detection
- [ ] Add user escalation
- [ ] Track metrics
- [ ] Write end-to-end test
- [ ] Verify test passes

### Phase 4: Testing & Validation ✓
- [ ] Run full test suite (15+ tests)
- [ ] Benchmark langextract performance
- [ ] Document all APIs
- [ ] Test user's original case
- [ ] Calculate token savings
- [ ] Write README
- [ ] Update CHANGELOG

---

## Deployment Plan

### Pre-Deployment

1. **Verify langextract service:**
   ```bash
   curl http://localhost:8156/health
   ```

2. **Run test suite:**
   ```bash
   cd agents/parallel_execution
   pytest test_context_recovery.py -v
   ```

3. **Benchmark performance:**
   ```bash
   python benchmark_context_recovery.py
   ```

### Deployment Steps

1. **Deploy code:**
   ```bash
   git checkout -b feature/context-recovery
   # ... implement changes ...
   git add .
   git commit -m "feat: Add context recovery with langextract integration"
   git push origin feature/context-recovery
   ```

2. **Configure environment:**
   ```bash
   echo "LANGEXTRACT_SERVICE_URL=http://localhost:8156" >> .env
   echo "CONTEXT_RECOVERY_MAX_RETRIES=2" >> .env
   ```

3. **Test in production:**
   ```bash
   # Run user's original test case
   python test_debug_loop_workflow.py
   ```

4. **Monitor metrics:**
   ```bash
   # Check recovery success rate
   psql -h localhost -p 5436 -U postgres -d omninode_bridge -c \
     "SELECT COUNT(*), success FROM context_recovery_attempts GROUP BY success;"
   ```

### Post-Deployment

1. **Monitor for 1 week:**
   - Track recovery success rate
   - Monitor langextract service health
   - Check token usage metrics

2. **Tune parameters if needed:**
   - Adjust confidence thresholds
   - Update domain→file mappings
   - Refine file suggestion logic

3. **Gather feedback:**
   - Review failed recovery attempts
   - Identify common patterns
   - Improve parsing logic

---

## Success Validation

### Test Cases

1. **Simple Context Missing:**
   - Feedback: "Needs ONEX architecture info"
   - Expected: Read CLAUDE.md, retry succeeds

2. **Multiple Domains:**
   - Feedback: "Needs database schema and agent patterns"
   - Expected: Read 2+ files, retry succeeds

3. **Vague Feedback:**
   - Feedback: "Task is unclear"
   - Expected: Escalate to user (can't auto-recover)

4. **Repeat Failure:**
   - Attempt 1: Fails with "needs X"
   - Attempt 2: Fails with "needs X" again
   - Expected: Escalate immediately (not helpful)

5. **User's Original Test:**
   - Feedback: "Needs ONEX patterns, database schema, Node types"
   - Expected: Read 3+ files, retry succeeds, full workflow completes

### Metrics Dashboard

```sql
-- Recovery success rate
SELECT
  COUNT(*) as total_attempts,
  SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
  AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) * 100 as success_rate_pct
FROM context_recovery_attempts
WHERE created_at > NOW() - INTERVAL '7 days';

-- Token usage comparison
SELECT
  AVG(tokens_used) as avg_tokens,
  MAX(tokens_used) as max_tokens,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY tokens_used) as p95_tokens
FROM context_recovery_attempts
WHERE success = true;

-- Langextract performance
SELECT
  AVG(langextract_latency_ms) as avg_latency,
  MAX(langextract_latency_ms) as max_latency
FROM context_recovery_attempts;
```

---

## Next Steps

1. **Create this plan on disk** ✓ (This document)
2. **Dispatch workflow coordinator** (Next step)
3. **Execute implementation** (Automated)
4. **Run test suite** (Automated)
5. **Validate with user's test case** (Manual)
6. **Calculate token savings** (Automated)
7. **Deploy to production** (Manual approval)

---

## Appendix A: Example Langextract Response

**Input:**
```
Task decomposition lacks critical context about ONEX architecture patterns,
specifically the Node type conventions (Effect for I/O, Compute for transforms)
and how they integrate with Pydantic models.
```

**Langextract Output:**
```json
{
  "concepts": [
    {"text": "ONEX architecture patterns", "confidence": 0.92, "category": "architecture"},
    {"text": "Node type conventions", "confidence": 0.89, "category": "patterns"},
    {"text": "Effect", "confidence": 0.85, "category": "node_type"},
    {"text": "Compute", "confidence": 0.83, "category": "node_type"},
    {"text": "Pydantic models", "confidence": 0.81, "category": "data_modeling"}
  ],
  "themes": [
    {"name": "architectural_patterns", "confidence": 0.91, "keywords": ["ONEX", "patterns", "conventions"]},
    {"name": "node_types", "confidence": 0.87, "keywords": ["Effect", "Compute", "transforms", "I/O"]}
  ],
  "domains": [
    {"name": "architecture", "confidence": 0.93},
    {"name": "software_design", "confidence": 0.88}
  ],
  "language": "en",
  "processing_time_ms": 342
}
```

**Parsed Context Requests:**
```python
[
    ContextRequest(
        type="file",
        description="ONEX architecture patterns documentation",
        suggestion="CLAUDE.md",
        priority=1
    ),
    ContextRequest(
        type="concept",
        description="Node type conventions (Effect, Compute)",
        suggestion="Explain Node type patterns in this codebase",
        priority=1
    ),
    ContextRequest(
        type="file",
        description="Pydantic model integration examples",
        suggestion="agents/parallel_execution/model_*.py",
        priority=2
    )
]
```

---

## Appendix B: Token Budget Calculation

**Token Counting:**
```python
def count_tokens(text: str, model: str = "gpt-4") -> int:
    """Estimate token count (rough approximation)"""
    # ~4 chars per token for English text
    return len(text) // 4

def enforce_token_budget(
    context_requests: List[ContextRequest],
    budget: int = 50000
) -> Dict[str, str]:
    """Gather context within token budget"""
    gathered = {}
    used_tokens = 0

    for request in sorted(context_requests, key=lambda x: x.priority):
        content = read_context_source(request)
        tokens = count_tokens(content)

        if used_tokens + tokens > budget:
            # Summarize instead of full content
            content = summarize_content(content, max_tokens=budget - used_tokens)
            tokens = count_tokens(content)

            if used_tokens + tokens > budget:
                # Skip if even summary exceeds budget
                logger.warning(f"Skipping {request.description} - exceeds budget")
                continue

        gathered[request.id] = content
        used_tokens += tokens

        logger.info(f"Gathered {request.description} ({tokens} tokens, {used_tokens}/{budget} total)")

    return gathered
```

**Example Budget Allocation:**
- Total budget: 50,000 tokens
- Phase 1 context: 5,000 tokens
- Recovery overhead: 3,000 tokens
- Available for new context: 42,000 tokens
- Per-request average: ~10,000 tokens (4-5 files)

---

## Appendix C: Domain → File Mapping

```python
DOMAIN_FILE_MAP = {
    "architecture": {
        "patterns": ["CLAUDE.md", "README.md", "ARCHITECTURE.md"],
        "onex": ["ONEX_*.md", "agents/AGENT_FRAMEWORK.md"],
        "patterns": ["*_PATTERNS.md", "COMMON_*.md"]
    },
    "database": {
        "schema": ["*_SCHEMA.md", "migrations/*.sql"],
        "models": ["model_*.py", "model_contract_*.py"],
        "integration": ["*_INTEGRATION.md", "database_*.py"]
    },
    "workflow": {
        "coordination": ["workflow_executor.py", "WORKFLOW_*.md"],
        "agents": ["agent_dispatcher.py", "task_architect.py"],
        "patterns": ["COMMON_WORKFLOW.md"]
    },
    "quality": {
        "gates": ["quality-gates-spec.yaml", "QUALITY_*.md"],
        "validation": ["validated_*.py", "test_*.py"],
        "performance": ["performance-thresholds.yaml"]
    },
    "agent": {
        "definitions": ["agent_*.yaml", "configs/agent-*.yaml"],
        "documentation": ["AGENT_*.md", "agents/README.md"],
        "implementation": ["agent_*.py", "agents/parallel_execution/*.py"]
    }
}
```

---

**End of Implementation Plan**

**Total Estimated Effort:** 10 hours
**Expected ROI:** 3-6 months
**Risk Level:** Low (graceful degradation, fallbacks)
**User Impact:** High (enables token savings measurement)

**Ready for Implementation:** ✓
