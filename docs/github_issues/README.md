# GitHub Issues for TODO Audit

This directory contains GitHub issue templates for critical TODOs identified in the codebase audit.

## Audit Summary

- **Total TODOs**: 110
- **Critical Issues**: 4
- **High Priority Issues**: 1
- **Medium Priority Issues**: 13
- **Low Priority (Document Only)**: 92

See [`../TODO_AUDIT.md`](../TODO_AUDIT.md) for complete audit details.

---

## Critical Issues (Create Immediately)

### [Issue #1: Dead Letter Queue for Failed Kafka Messages](ISSUE_01_DEAD_LETTER_QUEUE.md)
**Priority**: CRITICAL | **Effort**: 1-2 days

Failed messages in Kafka consumer are lost permanently. Need to implement DLQ for failed batch processing.

**Impact**: Production data loss, no retry mechanism, debugging impossible

---

### [Issue #2: Kafka Publishing for Validation Requests](ISSUE_02_VALIDATION_KAFKA_PUBLISHING.md)
**Priority**: CRITICAL | **Effort**: 2-3 days

Code validation requests prepared but never published to Kafka. Validation service is non-functional.

**Impact**: Quality gates bypassed, ONEX compliance checks not running

---

### [Issue #3: Kafka Subscription for Validation Responses](ISSUE_03_VALIDATION_RESPONSE_SUBSCRIPTION.md)
**Priority**: CRITICAL | **Effort**: 1-2 days

No consumer for validation responses. All validations fail with `OnexError`.

**Impact**: Validation workflow completely broken

**Dependencies**: Requires Issue #2 to be completed first

---

## High Priority Issues

### [Issue #4: Object Storage Retrieval for State Snapshots](ISSUE_04_OBJECT_STORAGE_RETRIEVAL.md)
**Priority**: HIGH | **Effort**: 2-4 days

Large state snapshots (>1MB) stored in object storage cannot be retrieved.

**Impact**: Debugging and replay capabilities broken for complex workflows

**Backends**: S3, MinIO, local filesystem

---

## Medium Priority Issues

### [Issue #5: Router Cache Hit Tracking](ISSUE_05_ROUTER_CACHE_TRACKING.md)
**Priority**: MEDIUM | **Effort**: 1-2 days

Router hardcodes `cache_hit: False` instead of tracking actual cache statistics.

**Impact**: Cannot measure cache effectiveness, blocks Universal Router planning

---

### [Issues #6-10: Medium Priority Batch](ISSUE_06_TO_10_BATCHED.md)

Contains 5 medium priority issues:

1. **Issue #6**: Track routing strategy in database (2-3 hours)
2. **Issue #7**: Implement true parallel execution with asyncio.gather (3-4 hours)
3. **Issue #8**: Implement import order validation (3-4 hours)
4. **Issue #9**: Integrate Archon MCP client for monitoring (4-6 hours)
5. **Issue #10**: Initialize omnibase_spi validator - BLOCKED by Week 4 (2-3 hours)

**Total Effort (Issues #6-9)**: 2-3 days

---

## Additional Medium Priority

### Issues #11-15: Pattern Learning Improvements Epic

Batch 5 ML-related TODOs into single epic (detailed in batched document):

- Recall tracking for pattern feedback
- ML-based pattern tuning
- Variant-specific feedback tracking
- Version history tracking for rollback
- PatternFeedbackCollector integration

**Effort**: 2-3 weeks (iterative)

---

### Issue #16: Replace Dict[str, Any] with ModelObjectData

**Priority**: MEDIUM | **Effort**: 2-3 hours | **Blocked**: Week 4 milestone

Replace `Dict[str, Any]` with `ModelObjectData` for ONEX type safety compliance.

---

## Low Priority (Document Only)

### Template TODOs (No GitHub Issues)

**92 TODOs** in templates, tests, and generated code placeholders. These are intentional and should NOT be removed:

- **Template helpers** (11 patterns): Connection pooling, circuit breaker, retry, etc.
- **Node templates** (8 TODOs): Business logic placeholders in templates
- **Test TODOs** (60+ TODOs): Test fixtures, assertions, mock implementations
- **Week 4 TODOs** (5 TODOs): Waiting for omnibase_core completion

See [TODO_AUDIT.md](../TODO_AUDIT.md) for complete list.

---

## Recommended Implementation Order

### Sprint 1: Critical Infrastructure (Week 1)
1. **Issue #1**: Dead letter queue (1-2 days) - Prevents data loss
2. **Issue #2**: Validation publishing (2-3 days) - Enables validation
3. **Issue #3**: Validation responses (1-2 days) - Completes validation

**Total**: 4-7 days

### Sprint 2: High Priority + Quick Wins (Week 2)
4. **Issue #4**: Object storage retrieval (2-4 days) - Restores debugging
5. **Issue #5**: Router cache tracking (1-2 days) - Observability
6. **Issue #6**: Routing strategy tracking (2-3 hours) - Analytics

**Total**: 3-6 days

### Sprint 3: Medium Priority (Week 3)
7. **Issue #7**: Parallel execution (3-4 hours) - Performance
8. **Issue #8**: Import order validation (3-4 hours) - Quality
9. **Issue #9**: Archon MCP integration (4-6 hours) - Monitoring

**Total**: 2-3 days

### Future Sprints
- **Issue #10, #16**: After Week 4 milestone (omnibase_core)
- **Issues #11-15**: Pattern learning epic (2-3 weeks, can be done iteratively)

---

## Effort Summary

| Priority | Issues | Estimated Effort |
|----------|--------|-----------------|
| Critical | #1, #2, #3 | 4-7 days |
| High | #4 | 2-4 days |
| Medium | #5, #6, #7, #8, #9 | 4-6 days |
| **Subtotal** | **9 issues** | **10-17 days** |
| Blocked (Week 4) | #10, #16 | 4-6 hours |
| Epic (ML) | #11-15 | 2-3 weeks |
| **Total** | **16 issues** | **12-20 days** |

---

## Creating GitHub Issues

To create issues from these templates:

1. Navigate to GitHub repository: `https://github.com/OmniNode-ai/omniclaude`
2. Go to **Issues** tab
3. Click **New Issue**
4. Copy content from template file
5. Adjust labels as needed
6. Assign to appropriate developer/team
7. Link related issues (e.g., Issue #3 depends on Issue #2)

### Labels to Use

- **Priority**: `priority:critical`, `priority:high`, `priority:medium`, `priority:low`
- **Type**: `type:bug`, `type:feature`, `type:enhancement`, `type:refactor`
- **Component**: `component:kafka`, `component:validation`, `component:router`, `component:storage`, `component:monitoring`
- **Status**: `status:blocked`, `status:in-progress`, `status:ready`
- **Special**: `blocked:week4`, `reliability`, `observability`, `performance`, `onex-compliance`

---

## Notes

- **Template TODOs are intentional**: Don't create issues for template placeholders
- **Test TODOs are infrastructure**: Test-related TODOs are working as designed
- **Week 4 blockers**: Issues #10 and #16 require omnibase_core completion
- **ML improvements**: Issues #11-15 can be done as single epic or separate issues

---

## Related Documentation

- [Complete TODO Audit](../TODO_AUDIT.md) - Detailed analysis of all 110 TODOs
- [Architecture Documentation](../architecture/) - System architecture docs
- [Observability Guide](../observability/) - Observability and tracing docs

---

**Audit Date**: 2025-11-07
**Last Updated**: 2025-11-07
**Audited By**: Claude Code (OmniClaude Polymorphic Agent)
