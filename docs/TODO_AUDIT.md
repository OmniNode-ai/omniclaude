# TODO Audit - Critical Items Requiring GitHub Issues

**Audit Date**: 2025-11-07
**Total TODOs Found**: 110
**Critical Items**: 10
**Medium Priority**: 13
**Low Priority**: 87 (template/test related)

---

## High Priority (Production Impact) - Requires GitHub Issues

### 1. ❌ CRITICAL: Dead Letter Queue for Failed Messages
**File**: `agents/lib/kafka_agent_action_consumer.py:256`
**Context**: Exception handler for batch processing failures
**Issue**: Failed messages are raised but not sent to DLQ, causing message loss

```python
except Exception as e:
    logger.error(f"Batch processing failed: {e}", exc_info=True)
    # TODO: Send to dead letter queue
    raise
```

**Impact**:
- Failed messages are lost permanently
- No retry mechanism for transient failures
- Debugging production issues becomes difficult

**Suggested Implementation**:
- Create Kafka topic: `agent-actions-dlq`
- Publish failed messages with error metadata
- Add retry counter and max retry configuration
- Include original timestamp and correlation_id

**Priority**: CRITICAL - Production data loss risk

---

### 2. ❌ CRITICAL: Kafka Publishing for Validation Requests
**File**: `agents/lib/quality_validator.py:1014`
**Context**: Request validation event publishing
**Issue**: Validation requests are prepared but never published to Kafka

```python
async def request_validation(
    self, code: str, contract: Dict[str, Any], ...
) -> CodegenValidationRequest:
    # TODO: Implement Kafka publishing
    request = CodegenValidationRequest(
        correlation_id=correlation_id,
        payload={...},
    )
```

**Impact**:
- Validation service is non-functional
- Code quality gates are bypassed
- ONEX compliance validation not happening

**Suggested Implementation**:
- Create Kafka topic: `codegen.validation.requested.v1`
- Publish request with correlation_id
- Add timeout configuration (default 30s)
- Return request object for correlation tracking

**Priority**: CRITICAL - Quality validation broken

---

### 3. ❌ CRITICAL: Kafka Subscription for Validation Responses
**File**: `agents/lib/quality_validator.py:1048`
**Context**: Waiting for validation response
**Issue**: No consumer for validation responses, always raises OnexError

```python
async def wait_for_validation_response(
    self, correlation_id: str, timeout_seconds: int = 30
) -> CodegenValidationResponse:
    # TODO: Implement Kafka subscription and response matching
    raise OnexError("Validation response handling not implemented")
```

**Impact**:
- Validation workflow is incomplete
- All validations fail with error
- Blocks ONEX compliance checking

**Suggested Implementation**:
- Subscribe to topic: `codegen.validation.completed.v1`
- Use correlation_id to match responses
- Implement timeout with asyncio.wait_for()
- Handle validation.failed.v1 topic for errors

**Priority**: CRITICAL - Validation workflow broken

---

### 4. ⚠️ HIGH: Object Storage Retrieval for State Snapshots
**File**: `agents/lib/state_snapshots.py:112`
**Context**: Retrieving large state snapshots from object storage
**Issue**: Large snapshots stored in object storage cannot be retrieved

```python
if row["storage_uri"]:
    # TODO: Implement object storage retrieval
    return None
else:
    return row["snapshot"]
```

**Impact**:
- Large state snapshots (>1MB) are lost
- Debugging complex workflows impossible
- State replay functionality broken

**Suggested Implementation**:
- Support S3/MinIO/local filesystem backends
- Parse storage_uri (s3://bucket/key or file:///path)
- Add streaming support for large snapshots
- Implement signed URL generation for secure access
- Add caching layer (Valkey) for frequently accessed snapshots

**Priority**: HIGH - Debugging capability loss

---

## Medium Priority (Reliability & Performance) - Consider GitHub Issues

### 5. 📊 Cache Hit Tracking in Router
**File**: `agents/services/agent_router_event_service.py:866`
**Context**: Router metadata in response
**Issue**: Cache hit/miss metrics not tracked

```python
"routing_metadata": {
    "routing_time_ms": routing_time_ms,
    "cache_hit": False,  # TODO: Get from router cache stats
}
```

**Impact**:
- Cannot measure cache effectiveness
- No visibility into routing performance optimization
- Missing data for Universal Router planning

**Suggested Implementation**:
- Add cache hit tracking to EnhancedAgentRouter
- Return cache_hit boolean from route() method
- Track hit rate in Prometheus metrics
- Add cache statistics endpoint

**Priority**: MEDIUM - Performance observability

---

### 6. 📊 Routing Strategy Tracking
**File**: `agents/services/agent_router_event_service.py:884`
**Context**: Database logging of routing decisions
**Issue**: Hardcoded routing_strategy instead of actual value

```python
await self._postgres_logger.log_routing_decision(
    routing_strategy="enhanced_fuzzy_matching",  # TODO: Get from router
    ...
)
```

**Impact**:
- Cannot compare routing strategy effectiveness
- Misleading analytics if strategy changes
- Blocks A/B testing of routing algorithms

**Suggested Implementation**:
- Add strategy field to EnhancedAgentRouter
- Return strategy name from route() method
- Support multiple strategies (fuzzy, semantic, hybrid)
- Track strategy distribution in analytics

**Priority**: MEDIUM - Analytics accuracy

---

### 7. ⚡ True Parallel Execution with asyncio.gather
**File**: `agents/parallel_execution/agent_code_generator.py:422`
**Context**: Agent parallel execution
**Issue**: Sequential execution instead of parallel

```python
# Simple sequential execution for now
# TODO: Implement true parallel execution with asyncio.gather
results = []
for task in tasks:
    result = await self.agent.execute(task)
    results.append(result)
return results
```

**Impact**:
- 3-5x slower than parallel execution
- Wastes computational resources
- Defeats purpose of parallel_execution module

**Suggested Implementation**:
- Use asyncio.gather(*tasks) for concurrent execution
- Add error handling with return_exceptions=True
- Implement task timeout per task
- Add max concurrency limit (default 10)
- Preserve task execution order in results

**Priority**: MEDIUM - Performance optimization

---

### 8. 🔍 Import Order Validation
**File**: `agents/lib/quality_validator.py:638`
**Context**: ONEX compliance checking
**Issue**: Import order not validated, just returns True

```python
def _check_import_order(self, imports: List[str], node_type: str) -> bool:
    """Check if imports are in correct order"""
    # For simplicity, just check they are present in the right categories
    # Full implementation would check line numbers
    return True  # TODO: Implement line number checking
```

**Impact**:
- ONEX style guide violations not caught
- Inconsistent import ordering across codebase
- Quality gate is ineffective

**Suggested Implementation**:
- Parse imports with ast module
- Extract line numbers for each import
- Validate order: stdlib → third-party → local
- Check alphabetical ordering within groups
- Return violations list with line numbers

**Priority**: MEDIUM - Code quality

---

### 9. 🔌 Archon MCP Client Integration for Monitoring
**File**: `agents/tests/monitor_dependencies.py:44`
**Context**: Dependency monitoring
**Issue**: Mock status instead of real Archon MCP integration

```python
async def check_dependencies(self) -> Dict[str, Any]:
    # TODO: Integrate with Archon MCP client
    # For now, return mock status for testing
    status = {
        "check_count": self.check_count,
        ...
    }
```

**Impact**:
- Cannot monitor real dependency health
- Missing alerts for service degradation
- Test monitoring is insufficient for production

**Suggested Implementation**:
- Use archon-intelligence MCP client
- Query health endpoints for all services
- Add circuit breaker for failing services
- Implement health check caching (60s TTL)
- Support graceful degradation mode

**Priority**: MEDIUM - Production monitoring

---

### 10. 🔧 omnibase_spi Validator Initialization
**File**: `agents/lib/omninode_template_engine.py:187-188`
**Context**: Template engine initialization
**Issue**: ToolMetadataValidator not initialized

```python
def __init__(self, ...):
    # TODO: Initialize validator when omnibase_spi is available
    # self.metadata_validator = ToolMetadataValidator()
```

**Related**: Line 38-39 has import TODO
**Impact**:
- Tool metadata validation skipped
- ONEX tool specifications not enforced
- Quality regression risk

**Suggested Implementation**:
- Wait for omnibase_core Week 4 completion
- Uncomment imports and validator initialization
- Add feature flag: ENABLE_TOOL_METADATA_VALIDATION
- Gracefully degrade if omnibase_spi unavailable
- Log warning when validator is disabled

**Priority**: MEDIUM - Blocked by Week 4 milestone

---

## Medium Priority (ML/Pattern Improvements)

### 11. 📈 Recall Tracking for Pattern Feedback
**File**: `agents/lib/pattern_feedback.py:208`
**Context**: Pattern quality metrics
**Issue**: Only precision tracked, no recall or F1 score

```python
# Recall: correct / (correct + false_negatives)
# This requires tracking what patterns were missed
recall = None  # TODO: Implement recall tracking in future iteration
```

**Impact**:
- Incomplete pattern effectiveness metrics
- Cannot measure false negatives
- F1 score unavailable for balanced evaluation

**Suggested Implementation**:
- Track expected patterns in database
- Compare discovered vs expected patterns
- Calculate recall = true_positives / (true_positives + false_negatives)
- Store recall alongside precision
- Compute F1 = 2 * (precision * recall) / (precision + recall)

**Priority**: MEDIUM - ML metrics improvement

---

### 12. 🤖 ML-Based Pattern Tuning
**File**: `agents/lib/pattern_feedback.py:332`
**Context**: Pattern threshold tuning
**Issue**: Simple threshold logic instead of ML-based tuning

```python
# Simple threshold tuning logic
# TODO: Implement more sophisticated ML-based tuning
if current_precision >= 0.95:
    recommended = 0.65
```

**Impact**:
- Suboptimal threshold selection
- Manual tuning required
- Cannot adapt to changing patterns

**Suggested Implementation**:
- Train regression model (precision/recall vs threshold)
- Use historical feedback data for training
- Implement Bayesian optimization for threshold search
- Support per-pattern threshold tuning
- Add A/B testing framework for threshold variants

**Priority**: MEDIUM - ML enhancement

---

### 13. 🔀 Variant-Specific Feedback Tracking
**File**: `agents/lib/pattern_tuner.py:335`
**Context**: A/B testing pattern variants
**Issue**: Simplified evaluation, no per-variant tracking

```python
# Get feedback for both variants
# TODO: Implement variant-specific feedback tracking
# For now, use simplified evaluation based on current analysis
```

**Impact**:
- Cannot compare variant effectiveness
- A/B test results unreliable
- Cannot make data-driven variant selection

**Suggested Implementation**:
- Add variant_id field to feedback records
- Track metrics per variant (precision, recall, usage)
- Implement statistical significance testing
- Support multi-armed bandit for variant selection
- Auto-promote winning variants

**Priority**: MEDIUM - A/B testing enhancement

---

### 14. 📜 Version History Tracking for Rollback
**File**: `agents/lib/pattern_tuner.py:409`
**Context**: Pattern rollback functionality
**Issue**: No version history, rollback to default only

```python
async def rollback_pattern(self, pattern_name: str) -> bool:
    # TODO: Implement version history tracking
    # For now, rollback to default threshold
    default_threshold = 0.70
```

**Impact**:
- Cannot rollback to specific previous version
- Lost history of threshold changes
- Cannot audit pattern evolution

**Suggested Implementation**:
- Create pattern_version_history table
- Store: version_id, pattern_name, threshold, timestamp, reason
- Support rollback to specific version
- Add version comparison tool
- Implement automatic rollback on quality regression

**Priority**: MEDIUM - Pattern management

---

### 15. 🔗 PatternFeedbackCollector Integration
**File**: `agents/lib/business_logic_generator.py:834`
**Context**: Capability detection feedback
**Issue**: Pattern detection not integrated with feedback system

```python
def _record_capability_detection(self, ...):
    # TODO: Integrate with PatternFeedbackCollector
    # For now, just log the detection
    self.logger.debug(f"Pattern detection: {capability_name}...")
```

**Impact**:
- Pattern detection feedback lost
- Cannot improve detection accuracy
- Missing closed-loop learning

**Suggested Implementation**:
- Initialize PatternFeedbackCollector in __init__
- Call collector.record_pattern_usage() on detection
- Add feedback collection on generation success/failure
- Track detection confidence vs actual usefulness
- Auto-tune detection thresholds

**Priority**: MEDIUM - Feedback loop completion

---

## Medium Priority (Type Safety & ONEX Compliance)

### 16. 🏗️ Replace Dict[str, Any] with ModelObjectData
**Files**:
- `agents/lib/generation/type_mapper.py:182`
- `agents/lib/generation/type_mapper.py:196`

**Context**: ONEX type safety compliance
**Issue**: Using Dict[str, Any] violates ONEX standards

```python
# ONEX COMPLIANCE: Never use Dict[str, Any]
# Use generic structured data model instead
return "Dict[str, Any]"  # TODO: Replace with ModelObjectData when available
```

**Impact**:
- ONEX compliance violation
- Type safety loss
- Runtime errors not caught by type checker

**Suggested Implementation**:
- Wait for ModelObjectData in omnibase_core (Week 4)
- Import from omnibase_core.models
- Update type_mapper to use ModelObjectData
- Add migration guide for existing code
- Update tests to verify ModelObjectData usage

**Priority**: MEDIUM - Blocked by Week 4 milestone

---

## Low Priority (Code Generation Templates) - Document Only

### 17. 🎨 Template Helper Pattern TODOs (11 patterns)
**File**: `agents/lib/template_helpers.py:139-181`
**Context**: Generated code pattern placeholders
**Issue**: Template TODOs are intentional placeholders for generated code

**Patterns**:
1. Connection pooling (line 139)
2. Circuit breaker (line 145)
3. Exponential backoff retry (line 149)
4. Transaction context (line 153)
5. Computation result caching (line 157)
6. Batch parallel processing (line 161)
7. State machine transitions (line 165)
8. Event store integration (line 169)
9. Lease acquisition and renewal (line 173)
10. Compensating transactions (line 177)
11. Operation timeout (line 181)

**Impact**: None - these are intentional placeholders for user implementation
**Action**: Document only, no GitHub issue needed
**Priority**: LOW - Working as designed

---

### 18. 🎨 Node Template TODOs
**Files**:
- `agents/templates/effect_node_template.py:166,194`
- `agents/templates/compute_node_template.py:144,174`
- `agents/templates/reducer_node_template.py:153,201`
- `agents/templates/orchestrator_node_template.py:192,260`

**Context**: Skeleton templates for node generation
**Issue**: Template placeholders for business logic and metrics

**Impact**: None - these are template placeholders
**Action**: Document only, no GitHub issue needed
**Priority**: LOW - Working as designed

---

### 19. 📡 Introspection Event Publishing
**File**: `agents/templates/effect_node_template.py:270`
**Context**: Node introspection events
**Issue**: Introspection events not published

```python
# TODO: Implement introspection event publishing
```

**Impact**: Missing observability events for node introspection
**Suggested Implementation**: Publish to `node.introspection.v1` Kafka topic
**Priority**: LOW - Nice to have feature

---

## Low Priority (Test/Development) - Document Only

### 20. 📦 Week 4 omnibase_core Installation
**Files** (5 occurrences):
- `agents/tests/test_pipeline_integration.py:36`
- `agents/tests/test_casing_preservation.py:30`
- `agents/tests/test_generation_all_node_types.py:41`
- `agents/tests/test_interactive_pipeline.py:49`
- `agents/tests/test_template_intelligence.py:39`

**Context**: Test files with omnibase_core imports disabled
**Issue**: Tests skip omnibase_core imports until Week 4 milestone

```python
# TODO(Week 4): Install omnibase_core package and remove --ignore from pyproject.toml
```

**Impact**: Some tests skipped pending omnibase_core completion
**Action**: Complete Week 4 milestone, then remove --ignore flag
**Priority**: LOW - Milestone tracked elsewhere

---

### 21. 🧪 Test-Related TODOs (60+ occurrences)
**Files**: Various test files
**Context**: Test assertions, mock implementations, test data
**Examples**:
- Test checking for TODO placeholders in generated code
- Mock implementation TODOs in test fixtures
- Test pattern implementations

**Impact**: None - these are test utilities and fixtures
**Action**: Document only, no GitHub issue needed
**Priority**: LOW - Test infrastructure

---

## Summary Statistics

| Priority | Count | Action Required |
|----------|-------|----------------|
| **Critical** | 4 | Create GitHub issues immediately |
| **High** | 1 | Create GitHub issue this week |
| **Medium** | 13 | Create GitHub issues (prioritize 5-10) |
| **Low (Document Only)** | 92 | No action (working as designed) |
| **TOTAL** | 110 | 5-15 GitHub issues recommended |

---

## Recommended GitHub Issues (Top 10)

**Create immediately**:
1. ❌ Dead letter queue for failed messages (CRITICAL)
2. ❌ Kafka publishing for validation requests (CRITICAL)
3. ❌ Kafka subscription for validation responses (CRITICAL)
4. ⚠️ Object storage retrieval for state snapshots (HIGH)
5. 📊 Cache hit tracking in router (MEDIUM)

**Create this sprint**:
6. 📊 Routing strategy tracking (MEDIUM)
7. ⚡ True parallel execution with asyncio.gather (MEDIUM)
8. 🔍 Import order validation (MEDIUM)
9. 🔌 Archon MCP client integration for monitoring (MEDIUM)
10. 📈 Recall tracking for pattern feedback (MEDIUM)

**Defer to Week 4 milestone**:
- 🔧 omnibase_spi validator initialization (blocked by omnibase_core)
- 🏗️ Replace Dict[str, Any] with ModelObjectData (blocked by omnibase_core)

---

## Notes

- **Template TODOs are intentional**: Pattern helpers and node templates contain TODO comments that are placeholders for user-implemented business logic. These should NOT be removed.
- **Test TODOs are infrastructure**: Test files contain TODO comments for test assertions and mock implementations. These are working as designed.
- **Week 4 blockers**: Several TODOs are blocked by omnibase_core completion. Track via Week 4 milestone, not individual issues.
- **ML improvements**: Pattern tuning TODOs (items 11-15) can be batched into single "Pattern Learning Improvements" epic.

---

**Audit Completed**: 2025-11-07
**Audited By**: Claude Code (OmniClaude Polymorphic Agent)
**Next Review**: After PR #22 merge
