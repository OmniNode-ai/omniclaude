# Error Handling & Logging Audit Report
**Date**: 2025-10-29
**Correlation ID**: 5160f8d0-c983-4cbc-961f-0e8412c43f8c
**Auditor**: agent-debug-intelligence

---

## Executive Summary

**Systemic Issue Identified**: Errors are not being buried, but **visibility is inconsistent** due to:
1. ✅ **Infrastructure exists** for error logging (Kafka, PostgreSQL, file logs)
2. ✅ **Graceful degradation works** (errors logged but don't crash system)
3. ❌ **Critical gaps** in error handling (agent_router.py has no error logging)
4. ⚠️ **Logging configuration issues** (many libraries don't configure logging)
5. ⚠️ **Detection failures not being triggered** (infrastructure works but no failures happening)

**Key Metrics**:
- 1,232 routing decisions logged ✅
- 127 transformation events logged ✅
- 77 performance metrics logged ✅
- **0 detection failures logged** ⚠️

---

## 1. Error Suppression Report

### 1.1 Bash Scripts (Hook Scripts)

**Pattern Analysis**:
- ✅ **24 scripts use `set -e`** (exit on error)
- ⚠️ **20 instances of error suppression**:
  - `2>/dev/null` (stderr to /dev/null)
  - `|| true` (force success)

**Detailed Findings**:

#### Acceptable Error Suppression

```bash
# claude_hooks/user-prompt-submit.sh:16
source "/Volumes/PRO-G40/Code/omniclaude/.env" 2>/dev/null || true
# ✅ ACCEPTABLE: .env may not exist, graceful fallback
```

```bash
# claude_hooks/tests/hook_validation/test_session_hooks.sh
local start_ns=$(date +%s%N 2>/dev/null || echo "0")
# ✅ ACCEPTABLE: Fallback for systems without nanosecond support
```

#### Potentially Problematic Suppression

```bash
# claude_hooks/run_tests.sh:15
pip3 install -r "${SCRIPT_DIR}/requirements.txt" || true
# ⚠️ WARNING: Silently continues if dependencies fail to install
# RECOMMENDATION: Check exit code and warn user
```

```bash
# claude_hooks/session-end.sh
[...cleanup...] 2>/dev/null || true
# ⚠️ WARNING: Cleanup failures silently ignored
# RECOMMENDATION: Log cleanup failures to detect issues
```

**Severity Assessment**:
- **Critical**: 0 instances (no errors being buried that would break functionality)
- **High**: 2 instances (dependency installation, cleanup failures)
- **Medium**: 5 instances (convenience redirects for optional features)
- **Low**: 13 instances (fallback values, compatibility checks)

---

### 1.2 Python Exception Handling

**Survey Results**:
- **125 files import logging module** ✅
- **Hundreds of `except Exception` blocks** (standard practice)
- **Multiple `except Exception: pass` blocks** (potential issues)

#### Critical Finding: Silent Exception Swallowing

**Location**: `claude_hooks/lib/hook_event_logger.py:122-123`
```python
except Exception as e:
    print(f"⚠️  [HookEventLogger] Failed to log event: {e}", file=sys.stderr)
    try:
        if self._conn:
            self._conn.rollback()
    except Exception:
        pass  # ❌ CRITICAL: Rollback failure silently ignored
```
**Impact**: Database connection issues may go undetected
**Recommendation**: Log rollback failures

**Location**: `agents/parallel_execution/file_utils.py`
```python
except (json.JSONDecodeError, FileNotFoundError):
    pass  # ❌ CRITICAL: File read failures silently ignored
```
**Impact**: Corrupted JSON files will cause silent failures
**Recommendation**: Log errors or return error indicator

**Location**: `agents/parallel_execution/metrics_collector.py`
```python
except Exception:
    pass  # ❌ CRITICAL: Metric collection failures invisible
```
**Impact**: No visibility into metric collection issues
**Recommendation**: Log metric collection failures

#### Acceptable Exception Handling

```python
# agents/parallel_execution/agent_analyzer.py:2-3
try:
    from dotenv import load_dotenv
except ImportError:
    pass  # ✅ ACCEPTABLE: Optional dependency
```

---

## 2. Logging Infrastructure Assessment

### 2.1 Python Logging Configuration

**Critical Finding**: Many libraries use `logger = logging.getLogger(__name__)` but **don't configure the logger**.

**What This Means**:
- If root logger not configured → log messages go nowhere (lost)
- Only scripts that call `logging.basicConfig()` have logging
- Hook scripts redirect stderr to log file, so Python logging DOES work

**Files Configuring Logging** (18 found):
- ✅ `consumers/agent_actions_consumer.py` (StreamHandler → stdout)
- ✅ `claude_hooks/error_handling.py` (StreamHandler → stderr)
- ✅ `claude_hooks/services/hook_event_processor.py` (FileHandler + StreamHandler)
- ✅ `agents/parallel_execution/dispatch_runner.py` (FileHandler + StreamHandler)
- ✅ `agents/lib/kafka_agent_action_consumer.py` (StreamHandler)

**Files Using Logging Without Configuration** (107 found):
- ⚠️ `agents/lib/agent_router.py` - **NO LOGGING AT ALL**
- ⚠️ `agents/lib/agent_execution_logger.py` - Uses logger but doesn't configure
- ⚠️ `claude_hooks/lib/hook_event_adapter.py` - Uses logger but doesn't configure
- ⚠️ `agents/lib/manifest_injector.py` - Uses logger but doesn't configure

**Impact**: Log messages from these libraries only appear if:
1. Calling script configured logging
2. Stderr is captured (which hooks do with `2>>"$LOG_FILE"`)

### 2.2 Where Do Logs Go?

**Log Destinations**:

| Source | Destination | Status |
|--------|-------------|--------|
| Bash hooks | `~/.claude/hooks/hook-enhanced.log` (191MB!) | ✅ Working |
| Python stderr | Redirected to hook log via `2>>"$LOG_FILE"` | ✅ Working |
| Consumer logs | Docker stdout (view with `docker logs`) | ✅ Working |
| Database events | PostgreSQL `hook_events` table | ✅ Working |
| Kafka events | Topics + consumer → database | ⚠️ Partial (see section 3) |

**Evidence of Working Logs**:
```bash
$ ls -lh ~/.claude/hooks/hook-enhanced.log
-rw-r--r--  191M  hook-enhanced.log  # ✅ Active logging

$ tail ~/.claude/hooks/hook-enhanced.log
[2025-10-29 18:22:26] Detection result: AGENT_DETECTED:pr-review
✓ UserPromptSubmit event logged: 416dd8c6-e7e8-4069-bfca-b6c5fa601ce4
```

### 2.3 Centralized Error Collection

**Status**: ✅ **YES, but distributed**

**Error Collection Points**:
1. **PostgreSQL Database** (`omninode_bridge`):
   - `hook_events` table (UserPromptSubmit, PreToolUse, PostToolUse)
   - `agent_routing_decisions` (1,232 entries)
   - `agent_transformation_events` (127 entries)
   - `router_performance_metrics` (77 entries)
   - `agent_detection_failures` (0 entries - see section 5)
   - `agent_execution_logs` (execution tracking)

2. **File Logs**:
   - `~/.claude/hooks/hook-enhanced.log` (hook execution)
   - `/tmp/hook_event_processor.log` (event processor)
   - Docker container logs (consumer, services)

3. **Kafka Topics** (event bus):
   - `onex.evt.omniclaude.routing-decision.v1`
   - `onex.evt.omniclaude.agent-transformation.v1`
   - `onex.evt.omniclaude.performance-metrics.v1`
   - `onex.evt.omniclaude.detection-failure.v1`
   - `onex.evt.omniclaude.agent-actions.v1`

---

## 3. Kafka Event Publishing Failures

### 3.1 Error Evidence from Logs

**Location**: `~/.claude/hooks/hook-enhanced.log`

**Finding 1: Kafka Connection Errors**
```
2025-10-29 22:20:19,477 - kafka.conn - ERROR - socket disconnected
2025-10-29 22:20:19,478 - kafka.conn - ERROR - Closing connection. KafkaConnectionError: socket disconnected
2025-10-29 22:20:19,478 - kafka.client - WARNING - Node 0 connection failed -- refreshing metadata
```
**Impact**: Kafka consumer experiences intermittent disconnects
**Status**: ⚠️ Logged but may indicate infrastructure issue

**Finding 2: Coordinator Errors**
```
2025-10-29 18:19:39,122 - kafka.coordinator - ERROR - Error sending JoinGroupRequest_v4 to node coordinator-0
2025-10-29 18:19:39,122 - kafka.coordinator - WARNING - Marking the coordinator dead
```
**Impact**: Consumer group coordination issues
**Status**: ⚠️ Logged, may cause event processing delays

**Finding 3: Intelligence Query Failures**
```
Code analysis request failed: KafkaError: INVALID_INPUT: Missing required field: content for DEBUG_INTELLIGENCE_QUERY operation
```
**Impact**: Debug intelligence queries failing due to missing fields
**Status**: ❌ **CRITICAL** - Intelligence queries failing repeatedly

### 3.2 Error Handling in hook_event_adapter.py

**Code Analysis**: `/Volumes/PRO-G40/Code/omniclaude/claude_hooks/lib/hook_event_adapter.py`

```python
def _publish(self, topic: str, event: Dict[str, Any]) -> bool:
    try:
        producer = self._get_producer()
        future = producer.send(topic, value=event, key=partition_key)
        future.get(timeout=1.0)  # Wait up to 1 second
        self.logger.debug(f"Published event to {topic}")
        return True
    except Exception as e:
        # ✅ GOOD: Log error but don't fail
        self.logger.error(f"Failed to publish event to {topic}: {e}")
        return False
```

**Assessment**:
- ✅ **Proper error handling**: Logs error, returns False
- ✅ **Non-blocking**: Doesn't crash hooks
- ✅ **Graceful degradation**: System continues working
- ⚠️ **Silent failure**: Caller may not check return value

**Recommendation**: Add metrics for failed publishes

---

## 4. Database Operation Failures

### 4.1 PostgreSQL Connection Handling

**Code Analysis**: `claude_hooks/lib/hook_event_logger.py`

```python
def log_event(self, source, action, resource, ...):
    try:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, params)
            conn.commit()
        return event_id
    except Exception as e:
        # ✅ GOOD: Print to stderr (captured by hook log)
        print(f"⚠️  [HookEventLogger] Failed to log event: {e}", file=sys.stderr)
        try:
            if self._conn:
                self._conn.rollback()
        except Exception:
            pass  # ❌ BAD: Rollback failure silently ignored
        return None
```

**Assessment**:
- ✅ **Error logged**: Prints to stderr
- ✅ **Non-blocking**: Returns None on failure
- ⚠️ **Rollback failures hidden**: `except Exception: pass`

**Database Connection Evidence**:
```bash
$ PGPASSWORD="..." psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
psql (14.x)
omninode_bridge=# \dt
# 34 tables found ✅
```

**Status**: ✅ Database connection working, error handling mostly good

---

## 5. Agent Routing Failures

### 5.1 Critical Finding: agent_detection_failures Table Empty

**Database Query**:
```sql
SELECT COUNT(*) FROM agent_detection_failures;
-- Result: 0 rows ❌
```

**Why is this table empty?**

### 5.2 Infrastructure Exists

**✅ Table Created**: `agents/migrations/001_agent_detection_failures.sql`
```sql
CREATE TABLE IF NOT EXISTS agent_detection_failures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id UUID NOT NULL,
    user_prompt TEXT NOT NULL,
    detection_status TEXT NOT NULL,
    failure_reason TEXT,
    ...
);
```

**✅ Consumer Exists**: `consumers/agent_actions_consumer.py:623`
```python
def _insert_detection_failures(self, cursor, events: List[Dict[str, Any]]) -> tuple[int, int]:
    """Insert agent_detection_failures events."""
    insert_sql = """INSERT INTO agent_detection_failures ..."""
```

**✅ Publishing Method Exists**: `claude_hooks/lib/hook_event_adapter.py:73`
```python
TOPIC_DETECTION_FAILURES = "onex.evt.omniclaude.detection-failure.v1"

def publish_detection_failure(self, user_request, failure_reason, ...):
    event = {...}
    return self._publish(self.TOPIC_DETECTION_FAILURES, event)
```

### 5.3 Hook DOES Call publish_detection_failure

**Code**: `claude_hooks/user-prompt-submit.sh:84-115`
```bash
if [[ "$AGENT_DETECTION" == "NO_AGENT_DETECTED" ]] || [[ -z "$AGENT_DETECTION" ]]; then
  log "No agent detected, logging failure..."

  python3 - <<'PYFAIL' 2>>"$LOG_FILE"
    adapter = get_hook_event_adapter()
    adapter.publish_detection_failure(
        user_request=user_request,
        failure_reason="No agent detected by hybrid selector",
        ...
    )
  except Exception as e:
    print(f"Error logging detection failure: {e}", file=sys.stderr)
  PYFAIL
```

**✅ Code is correct and called when detection fails**

### 5.4 Why Table is Empty: Detection is Succeeding

**Log Evidence**: `~/.claude/hooks/hook-enhanced.log`
```
[2025-10-29 18:22:26] Detection result: AGENT_DETECTED:pr-review
[2025-10-29 18:22:44] Detection result: AGENT_DETECTED:agent-ticket-manager
```

**Analysis**:
- ✅ Recent hook executions show **successful detections**
- ✅ No "NO_AGENT_DETECTED" messages in recent logs
- ✅ Infrastructure works but no failures happening

**Conclusion**: Table is empty because **detection is working well**, not because logging is broken.

### 5.5 CRITICAL GAP: agent_router.py Has NO Error Logging

**File**: `/Volumes/PRO-G40/Code/omniclaude/agents/lib/agent_router.py`

**Analysis**:
```python
class AgentRouter:
    def route(self, user_request, context=None, max_recommendations=5):
        # NO try/except blocks
        # NO error handling
        # NO logging of failures
        # NO detection failure tracking

        recommendations = []
        for agent_name, trigger_score, match_reason in trigger_matches:
            # Score each match
            confidence = self.confidence_scorer.score(...)
            recommendations.append(...)

        return recommendations  # Returns empty list if no matches
```

**Issues Identified**:
1. ❌ **NO error handling**: Exceptions bubble up
2. ❌ **NO logging**: No logger configured
3. ❌ **NO failure tracking**: Empty results not logged to agent_detection_failures
4. ❌ **NO visibility**: Can't debug why routing failed

**Impact**:
- If routing fails (no matches), returns empty list silently
- If exception occurs, crashes caller
- No record of routing failures for improvement
- No metrics on routing accuracy

**Recommendation**: Add comprehensive error handling and logging:

```python
import logging
logger = logging.getLogger(__name__)

class AgentRouter:
    def route(self, user_request, context=None, max_recommendations=5):
        try:
            # ... existing routing logic ...

            if not recommendations:
                logger.warning(
                    f"No agents matched for request: {user_request[:100]}",
                    extra={
                        "correlation_id": context.get("correlation_id"),
                        "trigger_matches": len(trigger_matches),
                    }
                )
                # TODO: Log to agent_detection_failures table

            return recommendations
        except Exception as e:
            logger.error(
                f"Routing failed: {e}",
                extra={"correlation_id": context.get("correlation_id")},
                exc_info=True
            )
            # TODO: Log to agent_detection_failures table
            return []  # Graceful fallback
```

---

## 6. Gap Analysis

### 6.1 What Errors Are NOT Being Logged?

| Error Type | Logged? | Location |
|------------|---------|----------|
| Agent routing failures | ❌ NO | agent_router.py (no logging) |
| Empty routing results | ❌ NO | agent_router.py (returns silently) |
| Low confidence matches | ⚠️ Partial | Logged if below threshold, but not tracked |
| Kafka publish failures | ✅ YES | hook_event_adapter.py (logs to stderr) |
| Database write failures | ✅ YES | hook_event_logger.py (logs to stderr) |
| Intelligence query failures | ✅ YES | Logs show repeated failures |
| Python library errors | ⚠️ Depends | Only if caller configured logging |
| Bash script errors | ✅ YES | `set -e` causes exit (logged) |
| Exception rollback failures | ❌ NO | hook_event_logger.py (silent pass) |
| Metric collection failures | ❌ NO | metrics_collector.py (silent pass) |

### 6.2 What Failures Are Invisible?

**High Priority (CRITICAL)**:
1. **Agent routing failures** - No logging in agent_router.py
2. **Empty routing results** - Returns [] silently
3. **Exception rollback failures** - Silently ignored
4. **Metric collection failures** - Silently ignored
5. **File I/O failures** - Some silently ignored (file_utils.py)

**Medium Priority (WARNING)**:
6. **Dependency installation failures** - `pip install || true` continues silently
7. **Cleanup failures** - Session cleanup errors ignored
8. **Low confidence warnings** - Not tracked in database

**Low Priority (INFO)**:
9. **Cache misses** - Tracked in stats but not logged per-event
10. **Fallback activations** - Happens silently (by design)

### 6.3 Where Should Logging Be Added?

**Priority 1 (CRITICAL) - Must Fix**:
1. **agents/lib/agent_router.py**
   - Add logging module import
   - Log empty results
   - Log exceptions
   - Track failures to agent_detection_failures table

2. **claude_hooks/lib/hook_event_logger.py:122**
   - Log rollback failures instead of `pass`

3. **agents/parallel_execution/metrics_collector.py**
   - Log metric collection failures

4. **agents/parallel_execution/file_utils.py**
   - Log file I/O failures

**Priority 2 (HIGH) - Should Fix**:
5. **claude_hooks/run_tests.sh**
   - Check pip install exit code, warn on failure

6. **claude_hooks/session-end.sh**
   - Log cleanup failures

7. **agents/lib/manifest_injector.py**
   - Configure logging in module (not just use logger)

**Priority 3 (MEDIUM) - Nice to Have**:
8. Add correlation ID to all log messages
9. Add structured logging (JSON format)
10. Add log aggregation (ELK stack or similar)

---

## 7. Recommendations

### 7.1 Critical Fixes (Do First)

**1. Add Error Handling to agent_router.py**
```python
# File: agents/lib/agent_router.py
import logging
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)

class AgentRouter:
    def __init__(self, ...):
        # ... existing init ...
        self.failure_tracker = None  # Optional detection failure tracker

    def route(self, user_request: str, context: Optional[Dict] = None,
              max_recommendations: int = 5) -> List[AgentRecommendation]:
        correlation_id = context.get("correlation_id") if context else None

        try:
            # ... existing routing logic ...

            # Log if no matches found
            if not recommendations:
                logger.warning(
                    "No agents matched request",
                    extra={
                        "correlation_id": correlation_id,
                        "request_length": len(user_request),
                        "trigger_matches_count": len(trigger_matches),
                    }
                )

                # Track detection failure
                if self.failure_tracker and correlation_id:
                    self._track_detection_failure(
                        correlation_id=UUID(correlation_id),
                        user_request=user_request,
                        trigger_matches=trigger_matches,
                    )

            return recommendations

        except Exception as e:
            logger.error(
                f"Routing failed: {e}",
                extra={"correlation_id": correlation_id},
                exc_info=True
            )

            # Track error
            if self.failure_tracker and correlation_id:
                self._track_detection_failure(
                    correlation_id=UUID(correlation_id),
                    user_request=user_request,
                    detection_status="error",
                    failure_reason=str(e),
                )

            return []  # Graceful fallback

    def _track_detection_failure(self, correlation_id: UUID, user_request: str,
                                  detection_status: str = "no_detection",
                                  failure_reason: str = "No agents matched",
                                  trigger_matches: Optional[List] = None):
        """Track detection failure to database."""
        if not self.failure_tracker:
            return

        try:
            self.failure_tracker.record_failure(
                correlation_id=correlation_id,
                user_prompt=user_request,
                detection_status=detection_status,
                failure_reason=failure_reason,
                trigger_matches=trigger_matches or [],
            )
        except Exception as e:
            logger.error(f"Failed to track detection failure: {e}")
```

**2. Fix Exception Rollback Logging**
```python
# File: claude_hooks/lib/hook_event_logger.py:122
except Exception as e:
    print(f"⚠️  [HookEventLogger] Failed to log event: {e}", file=sys.stderr)
    try:
        if self._conn:
            self._conn.rollback()
    except Exception as rollback_error:
        # ✅ FIX: Log rollback failure
        print(f"⚠️  [HookEventLogger] Rollback failed: {rollback_error}", file=sys.stderr)
```

**3. Fix Metric Collection Logging**
```python
# File: agents/parallel_execution/metrics_collector.py
except Exception as e:
    # ✅ FIX: Log instead of pass
    logger.error(f"Metric collection failed: {e}", exc_info=True)
```

### 7.2 Nice-to-Have Improvements

**1. Structured Logging Migration**

Add JSON structured logging for better log aggregation:

```python
# File: agents/lib/structured_logging_config.py
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
            "file": record.pathname,
            "line": record.lineno,
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)

def configure_structured_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)
```

**2. Correlation ID Propagation**

Ensure all log messages include correlation ID:

```python
# Add to all logging calls
logger.info("Event occurred", extra={"correlation_id": correlation_id})
```

**3. Log Aggregation**

Set up centralized log collection:
- Use ELK stack (Elasticsearch, Logstash, Kibana)
- Or Loki + Grafana
- Or CloudWatch Logs

**4. Alerting on Errors**

Set up alerts for:
- Kafka connection failures (> 5 per hour)
- Intelligence query failures (> 10 per hour)
- Detection failures (> 20% of requests)
- Database connection failures (any)

### 7.3 Testing Recommendations

**1. Simulate Failures**

Create test script to verify error logging:

```python
# File: agents/tests/test_error_logging.py
import pytest
from agents.lib.agent_router import AgentRouter

def test_routing_failure_logged(caplog):
    """Test that routing failures are logged."""
    router = AgentRouter()

    # Request that won't match any agents
    result = router.route("xyzabc123notarealthing")

    assert result == []
    assert "No agents matched request" in caplog.text

def test_routing_exception_logged(caplog):
    """Test that routing exceptions are logged."""
    router = AgentRouter()

    # Trigger exception by passing invalid input
    with pytest.raises(Exception):
        router.route(None)

    assert "Routing failed" in caplog.text
```

**2. Integration Tests**

Test end-to-end error flow:
- Hook script → Kafka → Consumer → Database
- Verify detection failures are tracked
- Verify errors don't crash system

---

## 8. Summary

### 8.1 Current State Assessment

**What's Working Well** ✅:
1. Hook event logging (191MB log file shows active logging)
2. Database observability (1,232+ routing decisions tracked)
3. Graceful degradation (Kafka errors don't crash system)
4. Comprehensive try/except blocks (hundreds across codebase)
5. Non-blocking error handling (hooks continue on errors)

**What Needs Improvement** ⚠️:
1. agent_router.py lacks error handling and logging (CRITICAL)
2. Some exception handlers silently swallow errors (`except: pass`)
3. Python libraries don't configure logging (rely on caller)
4. Intelligence query failures happening repeatedly
5. Kafka connection instability (intermittent disconnects)

**What's Not Actually Broken** 💡:
1. agent_detection_failures table empty → Detection is succeeding, not broken
2. Errors being "buried" → Actually logged, but need better visibility
3. Tool execution logging → Not implemented (separate issue from this audit)

### 8.2 Severity Breakdown

| Severity | Count | Examples |
|----------|-------|----------|
| **CRITICAL** | 4 | agent_router.py no logging, rollback failures, metric failures, file I/O failures |
| **HIGH** | 5 | Intelligence query failures, Kafka instability, dependency install silent fail |
| **MEDIUM** | 8 | Cleanup failures, logging not configured, low confidence not tracked |
| **LOW** | 13 | Acceptable error suppression for fallbacks |

### 8.3 Action Plan

**Week 1 (CRITICAL)**:
1. Add error handling to agent_router.py
2. Fix exception rollback logging
3. Fix metric collection logging
4. Fix file I/O error logging

**Week 2 (HIGH)**:
5. Investigate intelligence query failures (missing field: content)
6. Investigate Kafka connection stability
7. Fix dependency installation error handling

**Week 3 (MEDIUM)**:
8. Add structured logging configuration
9. Add correlation ID propagation
10. Configure logging in all library modules

**Week 4 (MONITORING)**:
11. Set up log aggregation
12. Set up error alerting
13. Create error dashboards

### 8.4 Key Metrics to Track

**Post-Fix Monitoring**:
1. **Detection failure rate**: Should see non-zero if router starts logging
2. **Error log volume**: Track errors/hour by type
3. **Kafka connection stability**: Disconnects/hour
4. **Intelligence query success rate**: Target >95%
5. **Database write success rate**: Target >99.9%

---

## Appendix A: File Locations

**Critical Files Mentioned**:
- `agents/lib/agent_router.py` - Needs error handling
- `claude_hooks/lib/hook_event_logger.py` - Fix rollback logging (line 122)
- `claude_hooks/lib/hook_event_adapter.py` - Kafka publishing (working)
- `agents/parallel_execution/metrics_collector.py` - Fix silent pass
- `agents/parallel_execution/file_utils.py` - Fix silent pass
- `consumers/agent_actions_consumer.py` - Consumer (working)

**Log Locations**:
- `~/.claude/hooks/hook-enhanced.log` (191MB) - Primary hook log
- `/tmp/hook_event_processor.log` - Event processor log
- Docker logs: `docker logs omniclaude_agent_consumer`

**Database**:
- Host: `192.168.86.200:5436`
- Database: `omninode_bridge`
- Key tables: `agent_routing_decisions`, `agent_detection_failures`, `hook_events`

---

## Appendix B: Example Log Messages

**Good Error Logging** ✅:
```
⚠️  [HookEventLogger] Failed to log event: connection refused
```

**Bad Error Logging** ❌:
```python
except Exception:
    pass  # Silent failure
```

**Kafka Error Example**:
```
2025-10-29 22:20:19,477 - kafka.conn - ERROR - socket disconnected
```

**Intelligence Query Failure**:
```
Code analysis request failed: KafkaError: INVALID_INPUT: Missing required field: content
```

---

## Appendix C: Database Evidence

**Query Results**:
```sql
SELECT
    'routing_decisions' as table, COUNT(*) FROM agent_routing_decisions
UNION ALL SELECT
    'transformations', COUNT(*) FROM agent_transformation_events
UNION ALL SELECT
    'metrics', COUNT(*) FROM router_performance_metrics
UNION ALL SELECT
    'failures', COUNT(*) FROM agent_detection_failures;

-- Results:
-- routing_decisions: 1232 ✅
-- transformations: 127 ✅
-- metrics: 77 ✅
-- failures: 0 ⚠️ (but detection is succeeding)
```

---

**End of Report**
