# Debug Loop MVP Roadmap

**Version**: 1.0.0
**Created**: 2025-10-11
**Status**: Ready for Implementation

---

## Executive Summary

Phased rollout of the debug loop system prioritizing immediate value delivery. MVP focuses on core state capture and error→success tracking, deferring advanced features until proven value is established.

**What's Complete**: Database schema (5 tables), state_manager.py (902 lines), integration plan (4 weeks)
**What's Next**: Deploy MVP, measure impact, iterate based on metrics

---

## Feature Prioritization

### Phase 1: MVP (Weeks 1-4) - Core Value

| Priority | Feature | Value | Effort | Risk |
|----------|---------|-------|--------|------|
| P0 | State capture at critical points | High | Medium | Low |
| P0 | Error/success event recording | High | Low | Low |
| P0 | Basic error→success correlation | High | Medium | Low |
| P0 | Verbose/silent mode toggle | Medium | Low | Low |
| P1 | Simple task signature matching | Medium | Low | Low |
| P1 | LLM metrics correlation | Medium | Low | Low |
| P1 | Debug workflow integration | High | Medium | Medium |

**Scope**: State snapshots, basic recall, agent-debug-intelligence integration
**Deliverable**: Working debug loop with state replay capability
**Success Metric**: Capture 100+ error→success pairs in first 2 weeks

### Phase 2: Enhancement (Weeks 5-12) - Advanced Capabilities

| Priority | Feature | Value | Effort | Risk |
|----------|---------|-------|--------|------|
| P2 | Embedding-based similarity search | High | High | Medium |
| P2 | STF code pointer tracking | Medium | Medium | Low |
| P2 | Advanced state diff visualization | Medium | High | Low |
| P2 | Performance optimization (batch writes) | Medium | Medium | Low |
| P3 | Graph-based dependency tracking | Low | High | Medium |
| P3 | Compressed state storage | Low | Medium | Low |

**Scope**: Semantic search, code pointers, performance tuning
**Deliverable**: Intelligent STF recommendations based on historical data
**Success Metric**: >70% similarity accuracy for error matching

### Phase 3: Scale (Weeks 13-24) - Enterprise Features

| Priority | Feature | Value | Effort | Risk |
|----------|---------|-------|--------|------|
| P3 | ML-based recovery prediction | High | Very High | High |
| P3 | Archon MCP intelligence integration | High | High | Medium |
| P3 | Automated A/B testing framework | Medium | Very High | High |
| P4 | Multi-tenant isolation | Low | Medium | Medium |
| P4 | Real-time dashboard | Low | High | Low |

**Scope**: ML automation, Archon integration, production hardening
**Deliverable**: Self-healing debug system with <80% automated recovery
**Success Metric**: 50% reduction in manual debugging time

---

## Phase 1 MVP: Must-Haves

### Week 1: Foundation

**Goal**: Deploy schema, validate state_manager, establish baseline

| Task | Owner | Duration | Dependencies |
|------|-------|----------|--------------|
| Run migration 005 | DevOps | 1h | Database access |
| Test state_manager initialization | Dev | 2h | Migration complete |
| Create mock integration tests | Dev | 4h | state_manager ready |
| Verify query performance (<200ms) | DevOps | 2h | Migration complete |

**Milestone**: All tables created, state_manager connects to DB

### Week 2: Agent Integration

**Goal**: Integrate agent-debug-intelligence with state capture

| Task | Owner | Duration | Dependencies |
|------|-------|----------|--------------|
| Implement BFROS phase state capture | Dev | 8h | state_manager API |
| Add error state capture at fault localization | Dev | 4h | BFROS integration |
| Add success capture at validation | Dev | 4h | BFROS integration |
| Test full debug workflow | QA | 4h | All integrations done |

**Milestone**: Debug workflows create error→success links automatically

### Week 3: Parallel & Quorum Integration

**Goal**: Capture parallel execution and quorum decision states

| Task | Owner | Duration | Dependencies |
|------|-------|----------|--------------|
| Add batch state capture to agent_dispatcher | Dev | 6h | state_manager API |
| Add quorum decision capture to validated_task_architect | Dev | 8h | state_manager API |
| Implement retry attempt tracking | Dev | 4h | Quorum integration |
| Integration testing across all 3 agents | QA | 6h | All integrations done |

**Milestone**: Parallel workflows and quorum decisions fully tracked

### Week 4: LLM Metrics & Polish

**Goal**: Correlate LLM calls, optimize performance, prepare for production

| Task | Owner | Duration | Dependencies |
|------|-------|----------|--------------|
| Query hook_events for LLM metrics | Dev | 4h | Debug sessions exist |
| Create observability report script | Dev | 6h | LLM metrics ready |
| Implement silent mode for production | Dev | 2h | state_manager API |
| Performance tuning (target <5% overhead) | DevOps | 8h | Full integration |
| Documentation updates | Tech Writer | 4h | All features complete |

**Milestone**: Production-ready MVP with <5% overhead, 80% token savings in silent mode

---

## Phase 1 Defers

**Explicitly NOT in MVP** (move to Phase 2+):

| Feature | Rationale | Phase |
|---------|-----------|-------|
| STF code pointer tracking | Nice-to-have, not critical for MVP | Phase 2 |
| Embedding-based similarity | Token-based matching sufficient for MVP | Phase 2 |
| State diff visualization | Query-based analysis works for MVP | Phase 2 |
| Graph-based dependency tracking | Workflow steps table provides basic deps | Phase 2 |
| ML-based recovery prediction | Need data collection first (MVP focus) | Phase 3 |
| Archon MCP integration | External dependency, defer until proven | Phase 3 |
| A/B testing framework | Requires mature system first | Phase 3 |
| Real-time dashboard | Batch queries acceptable for MVP | Phase 3 |

**Key Principle**: Ship fast, learn fast, iterate based on actual usage patterns

---

## Implementation Roadmap (Week-by-Week)

### Week 1: Database Foundation

**Mon-Tue**: Run migration 005, verify schema
**Wed-Thu**: Test state_manager initialization, fix connection issues
**Fri**: Validate query performance benchmarks

**Blockers**: Database access, connection pool configuration

### Week 2: Debug Intelligence Integration

**Mon-Tue**: BFROS phase state capture
**Wed**: Error state capture at fault localization
**Thu**: Success state capture at validation
**Fri**: End-to-end debug workflow testing

**Blockers**: agent-debug-intelligence refactoring needs

### Week 3: Parallel & Quorum

**Mon-Tue**: agent_dispatcher batch state capture
**Wed-Thu**: validated_task_architect quorum tracking
**Fri**: Cross-agent integration testing

**Blockers**: Parallel execution stability, quorum API changes

### Week 4: Production Ready

**Mon**: LLM metrics correlation from hook_events
**Tue-Wed**: Observability report generation
**Thu**: Silent mode implementation and testing
**Fri**: Performance optimization and documentation

**Blockers**: Performance bottlenecks in batch operations

---

## Success Metrics

### Phase 1 MVP Targets (Week 4 Exit Criteria)

| Metric | Target | Measurement | Decision Point |
|--------|--------|-------------|----------------|
| **State Capture Rate** | >90% of debug workflows | Query debug_state_snapshots | GO/NO-GO for Phase 2 |
| **Error→Success Links** | >50 pairs captured | Query debug_error_success_correlation | Validate pattern learning value |
| **Query Performance** | <200ms for all queries | pg_stat_statements | Performance acceptable |
| **Token Savings** | >80% reduction in silent mode | Compare VERBOSE vs SILENT logs | Production deployment approved |
| **Agent Overhead** | <5% execution time increase | Benchmark with/without state capture | Integration sustainable |
| **Quorum Tracking** | 100% of validation attempts | Query debug_state_snapshots WHERE agent_name='validated-task-architect' | Feature completeness |

### Phase 2 Triggers

**Proceed to Phase 2 if**:
- ✅ All MVP metrics met
- ✅ >80% query performance targets achieved
- ✅ No critical production issues in first 2 weeks
- ✅ Positive developer feedback on state replay utility

**Defer Phase 2 if**:
- ❌ <70% state capture rate (investigate missing integration points)
- ❌ >10% agent overhead (optimize before adding features)
- ❌ Critical database performance issues (address before proceeding)

### Phase 3 Triggers

**Proceed to Phase 3 if**:
- ✅ Phase 2 embedding-based similarity achieves >70% accuracy
- ✅ STF recommendations used in >50% of debug sessions
- ✅ Clear ROI demonstrated (>30% debug time reduction)

---

## Go-Live Checklist

### Pre-Production (Week 3)

- [ ] All integration tests passing
- [ ] Performance benchmarks meet targets
- [ ] Database migration tested on staging
- [ ] Rollback procedure documented and tested
- [ ] Silent mode reduces token usage >80%
- [ ] State capture overhead <5%

### Production (Week 4)

- [ ] Migration applied to production database
- [ ] State manager deployed with verbose mode
- [ ] Monitoring dashboard configured
- [ ] Alert thresholds set (query latency, error rate)
- [ ] Team trained on observability reports
- [ ] Incident response procedure documented

### Post-Launch (Week 5)

- [ ] Monitor for 1 week in production
- [ ] Analyze state capture patterns
- [ ] Gather developer feedback
- [ ] Measure actual vs. target metrics
- [ ] Switch to silent mode if stable
- [ ] Plan Phase 2 features based on learnings

---

## Risk Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Database performance degradation | High | Medium | Rollback via 005_rollback_debug_state_management.sql |
| Agent execution overhead >10% | High | Low | Remove state capture from hot paths, batch writes |
| Incomplete state capture | Medium | Medium | Add debug logging, fix integration gaps iteratively |
| Token usage too high in verbose mode | Low | Low | Default to silent mode in production |
| Developer resistance to new API | Medium | Low | Provide clear examples, automate common patterns |

---

## Dependencies & Assumptions

**Dependencies**:
- PostgreSQL 16+ running on localhost:5436
- Database `omninode_bridge` with schema `agent_observability`
- Existing `hook_events` and `agent_transformation_events` tables
- `state_manager.py` (902 lines, already implemented)

**Assumptions**:
- Developers will add state capture to new agents
- Query performance remains acceptable with increased load
- Database has sufficient storage (estimate: 1GB/month for MVP)
- Token costs justify verbose mode for debugging

---

## Quick Reference: Key Decisions

| Decision | Rationale | Review Date |
|----------|-----------|-------------|
| Defer embedding-based search | Token overlap sufficient for MVP | Week 8 (Phase 2 planning) |
| Defer STF code pointers | Error messages provide enough context | Week 8 (Phase 2 planning) |
| Default to verbose mode initially | Need visibility during stabilization | Week 5 (post-launch) |
| No ML predictions in MVP | Requires data collection first | Week 12 (Phase 3 planning) |
| Manual A/B testing only | Automated framework premature | Week 12 (Phase 3 planning) |

---

## Appendix: Command Reference

```bash
# Deploy migration
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/005_debug_state_management.sql

# Rollback if needed
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/005_rollback_debug_state_management.sql

# Test state manager
python agents/parallel_execution/test_state_manager.py

# Check state capture rate
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT agent_name, COUNT(*) FROM agent_observability.debug_state_snapshots GROUP BY agent_name;"

# Check error→success links
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*) as total_links FROM agent_observability.debug_error_success_correlation;"

# Performance check
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT query, mean_exec_time FROM pg_stat_statements WHERE query LIKE '%debug_state_snapshots%' ORDER BY mean_exec_time DESC LIMIT 5;"
```

---

**Next Steps**: Review roadmap with team, validate priorities, execute Week 1 foundation tasks.
