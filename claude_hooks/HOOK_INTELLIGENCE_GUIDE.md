# Claude Code Hook Intelligence Guide

## Available Claude Code Hooks

### Currently Implemented

#### 1. **UserPromptSubmit** ✅
**Trigger**: Every time the user submits a prompt to Claude
**Timing**: Before prompt is processed by Claude
**Use Cases**:
- Agent detection and routing intelligence
- RAG intelligence gathering (background)
- Intent pattern tracking
- Correlation ID generation
- User behavior analytics

**Current Capture**:
- Full prompt text
- Detected agent (if any)
- Agent domain and purpose
- Intelligence queries triggered
- Correlation ID for request tracing

#### 2. **PreToolUse** ✅
**Trigger**: Before any tool is executed
**Timing**: After Claude decides to use a tool, before execution
**Use Cases**:
- Quality enforcement (ONEX standards)
- Input validation
- Security checks
- Resource usage prediction
- Tool invocation analytics

**Current Capture**:
- Tool name
- Tool input parameters
- Correlation ID (linked to UserPromptSubmit)
- Agent context (name, domain, prompt preview)
- Session/Root IDs for hierarchical tracking
- Quality check metadata

**Selective Filtering**: Currently only intercepts Write/Edit/MultiEdit for quality checks

#### 3. **PostToolUse** ✅
**Trigger**: After a tool completes execution
**Timing**: After tool returns results, before results go to Claude
**Use Cases**:
- Auto-fix application (naming conventions)
- Output validation
- Performance tracking
- Success/failure analytics
- Correlation linking

**Current Capture**:
- Tool name and output
- File path (for Write/Edit operations)
- Auto-fix details (if applied)
- Correlation ID (linked to prompt)
- Agent context
- Event linking metadata

---

## Additional Hook Opportunities

### Potential Claude Code Hooks (To Investigate)

#### **ResponseStart**
**Would Trigger**: When Claude starts generating a response
**Intelligence Value**:
- Response latency tracking
- Model selection metadata
- Context window usage
- Thinking token usage (if enabled)

#### **ResponseComplete**
**Would Trigger**: When Claude finishes generating response
**Intelligence Value**:
- Full response text
- Token usage (input/output/thinking)
- Response quality metrics
- Error detection

#### **ToolOutputReceive**
**Would Trigger**: When tool output is received by Claude
**Intelligence Value**:
- Tool execution time
- Output size and format
- Error/success status
- Resource usage

#### **ConversationStart/ConversationEnd**
**Would Trigger**: Conversation lifecycle events
**Intelligence Value**:
- Session analytics
- Conversation flow patterns
- Multi-turn context tracking

#### **ErrorOccurred**
**Would Trigger**: When errors happen during execution
**Intelligence Value**:
- Error classification
- Recovery strategies
- Debugging patterns
- System health monitoring

---

## Enhancement Opportunities

### 1. Enhanced PreToolUse Intelligence

**Additional Data to Capture**:
```json
{
  "code_analysis": {
    "file_type": "python",
    "estimated_complexity": "medium",
    "patterns_detected": ["class_definition", "async_function"],
    "potential_issues": ["missing_type_hints"]
  },
  "context_awareness": {
    "recent_tools": ["Read", "Edit", "Write"],
    "workflow_phase": "implementation",
    "estimated_time_ms": 150
  },
  "security_scan": {
    "contains_secrets": false,
    "path_traversal_risk": "low",
    "injection_risk": "none"
  },
  "performance_prediction": {
    "estimated_cpu_ms": 50,
    "estimated_memory_mb": 2,
    "estimated_io_ops": 1
  }
}
```

### 2. Enhanced PostToolUse Intelligence

**Additional Data to Capture**:
```json
{
  "execution_metrics": {
    "actual_duration_ms": 45,
    "memory_used_mb": 1.8,
    "io_operations": 1,
    "cache_hits": 0
  },
  "quality_metrics": {
    "onex_compliance": 0.95,
    "type_coverage": 0.88,
    "test_coverage": 0.0,
    "documentation_score": 0.65
  },
  "impact_analysis": {
    "files_modified": 1,
    "lines_added": 25,
    "lines_removed": 0,
    "dependencies_affected": []
  },
  "auto_improvements": {
    "fixes_applied": ["renamed_variable", "added_type_hint"],
    "suggestions_pending": ["add_docstring", "extract_method"]
  }
}
```

### 3. Cross-Hook Intelligence

**Correlation Queries** (Now Enabled):
```sql
-- Full request trace: User prompt → Tools executed → Results
SELECT
  u.created_at as prompt_time,
  u.payload->>'agent_detected' as agent,
  u.payload->>'prompt_preview' as prompt,
  pre.created_at as tool_start,
  pre.resource_id as tool_name,
  pre.payload->'tool_input' as inputs,
  post.created_at as tool_end,
  post.payload->'auto_fix_details' as fixes
FROM hook_events u
LEFT JOIN hook_events pre
  ON u.metadata->>'correlation_id' = pre.metadata->>'correlation_id'
  AND pre.source = 'PreToolUse'
LEFT JOIN hook_events post
  ON u.metadata->>'correlation_id' = post.metadata->>'correlation_id'
  AND post.source = 'PostToolUse'
WHERE u.source = 'UserPromptSubmit'
ORDER BY u.created_at DESC;
```

**Agent Performance Analytics**:
```sql
-- Which agents use which tools most often?
SELECT
  u.payload->>'agent_detected' as agent,
  post.resource_id as tool,
  COUNT(*) as usage_count,
  AVG(EXTRACT(EPOCH FROM (post.created_at - pre.created_at)) * 1000) as avg_duration_ms
FROM hook_events u
JOIN hook_events pre ON u.metadata->>'correlation_id' = pre.metadata->>'correlation_id'
JOIN hook_events post ON u.metadata->>'correlation_id' = post.metadata->>'correlation_id'
WHERE u.source = 'UserPromptSubmit'
  AND pre.source = 'PreToolUse'
  AND post.source = 'PostToolUse'
GROUP BY agent, tool
ORDER BY usage_count DESC;
```

---

## Implementation Priorities

### Phase 1: ✅ Complete
- [x] Basic hook event logging
- [x] Correlation ID generation
- [x] Agent detection tracking
- [x] Tool invocation logging

### Phase 2: ✅ Complete
- [x] Correlation ID propagation
- [x] Cross-hook linking
- [x] Enhanced PreToolUse context
- [x] Agent context in all hooks

### Phase 3: Recommended Next
- [ ] Performance metrics capture
- [ ] Code quality scoring
- [ ] Security scanning integration
- [ ] Impact analysis
- [ ] Real-time dashboards

### Phase 4: Advanced
- [ ] ML-based pattern detection
- [ ] Automated optimization suggestions
- [ ] Predictive intelligence
- [ ] Cross-session learning

---

## Hook Performance Guidelines

**Target Latencies**:
- UserPromptSubmit: <100ms (non-blocking RAG queries)
- PreToolUse: <50ms (synchronous quality checks)
- PostToolUse: <50ms (synchronous auto-fixes)
- Database logging: <10ms (async, non-blocking)

**Resource Limits**:
- Memory per hook: <10MB
- Disk I/O: Minimal (state files <1KB)
- Network calls: Async only
- CPU: <5% sustained usage

---

## Configuration Files

- **Hook scripts**: `~/.claude/hooks/*.sh`
- **Python modules**: `~/.claude/hooks/lib/*.py`
- **State files**: `~/.claude/hooks/.state/`
- **Logs**: `~/.claude/hooks/logs/`
- **Settings**: `~/.claude/settings.json`

## Database Schema

**hook_events table**:
```sql
id                UUID PRIMARY KEY
source            VARCHAR (UserPromptSubmit, PreToolUse, PostToolUse, Correlation)
action            VARCHAR (prompt_submitted, tool_invocation, tool_completion, link_events)
resource          VARCHAR (prompt, tool, correlation)
resource_id       VARCHAR (agent name, tool name, correlation ID)
payload           JSONB (event-specific data)
metadata          JSONB (correlation IDs, timestamps, agent context)
processed         BOOLEAN (for async processing)
processing_errors ARRAY (error tracking)
retry_count       INTEGER
created_at        TIMESTAMP WITH TIME ZONE
processed_at      TIMESTAMP WITH TIME ZONE
```

---

## Best Practices

1. **Always use correlation IDs** for request tracing
2. **Keep hooks fast** (<50ms synchronous, async for slow ops)
3. **Graceful degradation** (hooks should never crash the workflow)
4. **Structured logging** (use JSON payloads)
5. **State cleanup** (remove old correlation files after 1 hour)
6. **Security first** (validate all inputs, sanitize outputs)
7. **Monitor performance** (track hook execution times)
8. **Version control** (document hook schema changes)

---

## Testing Hooks

```bash
# Test correlation manager
python3 ~/.claude/hooks/lib/correlation_manager.py

# Test hook event logger
python3 ~/.claude/hooks/lib/hook_event_logger.py

# Query hook events
python /path/to/observability_report.py

# Check correlation propagation
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM hook_events WHERE metadata->>'correlation_id' IS NOT NULL ORDER BY created_at DESC LIMIT 5;"
```

---

## Future Research

1. Investigate additional Claude Code hook events
2. Explore MCP server event hooks
3. Consider agent framework custom hooks
4. Evaluate real-time streaming intelligence
5. Assess ML model integration opportunities
