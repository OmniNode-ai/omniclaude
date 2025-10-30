# PR #18 Critical Issues Tracker

**PR**: https://github.com/OmniNode-ai/omniclaude/pull/18
**Status**: ⚠️ MUST FIX BEFORE MERGE
**Created**: 2025-10-25
**Last Fix Commit**: 5552d2d (addressed CodeRabbit feedback only)

---

## 🔴 CRITICAL - Must Fix Before Merge

### 1. Hardcoded /tmp Directory - Platform Compatibility Issue
**File**: `agents/lib/agent_execution_logger.py:31-32`
**Severity**: 🔴 Critical

**Problem**:
```python
FALLBACK_LOG_DIR = Path("/tmp/omniclaude_logs")
FALLBACK_LOG_DIR.mkdir(exist_ok=True)  # Module-level execution!
```

**Issues**:
- ❌ Module-level directory creation fails in restricted environments
- ❌ `/tmp` doesn't exist on Windows (uses `%TEMP%` instead)
- ❌ Race condition if multiple processes import simultaneously
- ❌ Fails in Docker containers with read-only `/tmp`
- ❌ No error handling - import fails catastrophically

**Impact**: Agent execution logger completely broken on Windows and restricted environments

**Fix Required**:
```python
import tempfile
from pathlib import Path

def _get_fallback_log_dir() -> Path:
    """Get platform-appropriate fallback log directory with lazy initialization."""
    # Use platform-appropriate temp directory
    base_dir = Path(tempfile.gettempdir()) / "omniclaude_logs"

    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        # Verify writable
        test_file = base_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        return base_dir
    except (PermissionError, OSError) as e:
        # Fallback to current directory
        fallback = Path.cwd() / ".omniclaude_logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

# Lazy initialization - no module-level side effects
_FALLBACK_LOG_DIR = None

def get_fallback_log_dir() -> Path:
    global _FALLBACK_LOG_DIR
    if _FALLBACK_LOG_DIR is None:
        _FALLBACK_LOG_DIR = _get_fallback_log_dir()
    return _FALLBACK_LOG_DIR
```

**Changes Required**:
- Replace `FALLBACK_LOG_DIR` constant with `get_fallback_log_dir()` function call
- Update `_write_fallback_log()` to call function instead of using constant
- Add error handling for directory creation
- Use `tempfile.gettempdir()` for platform compatibility

**Test Plan**:
```bash
# Test on Windows
python -c "from agents.lib.agent_execution_logger import get_fallback_log_dir; print(get_fallback_log_dir())"

# Test with read-only /tmp
chmod 000 /tmp && python -c "from agents.lib.agent_execution_logger import get_fallback_log_dir; print(get_fallback_log_dir())"

# Test concurrent imports
parallel python -c "from agents.lib.agent_execution_logger import AgentExecutionLogger" ::: {1..10}
```

---

### 2. Consumer Batch Processing - Infinite Retry Loop Risk
**File**: `consumers/agent_actions_consumer.py:666-673`
**Severity**: 🔴 Critical

**Problem**:
```python
except Exception as e:
    logger.error("Batch processing failed: %s", e, exc_info=True)
    # Send entire batch to DLQ
    all_events = []
    for events in events_by_topic.values():
        all_events.extend(events)
    self.send_to_dlq(all_events, str(e))
    failed = sum(len(events) for events in events_by_topic.values())
    # ❌ NO OFFSET COMMIT - messages will be reprocessed infinitely!
```

**Issues**:
- ❌ Kafka offsets NOT committed on failure → messages reprocessed forever
- ❌ No exponential backoff → tight infinite loop consuming CPU
- ❌ No circuit breaker → one poison message blocks entire consumer
- ❌ No retry limit → can never escape bad message
- ❌ Entire batch fails if one event is malformed

**Impact**:
- One malformed message causes infinite retry loop
- Consumer becomes stuck, stops processing new events
- Database/DLQ can be flooded with duplicate failures
- System degradation under error conditions

**Fix Required**:

```python
class AgentActionsConsumer:
    def __init__(self, ...):
        self.retry_counts = {}  # Track retries per message
        self.max_retries = 3
        self.backoff_base_ms = 100

    def process_batch(self, messages):
        """Process batch with partial failure handling and backoff."""
        try:
            # ... existing code ...

        except Exception as e:
            logger.error("Batch processing failed: %s", e, exc_info=True)

            # Handle with exponential backoff and retry limits
            failed_events = []
            committable_offsets = []

            for msg in messages:
                msg_key = f"{msg.topic}:{msg.partition}:{msg.offset}"
                retry_count = self.retry_counts.get(msg_key, 0)

                if retry_count >= self.max_retries:
                    # Exceeded retries - send to DLQ and commit offset
                    logger.error(f"Message {msg_key} exceeded {self.max_retries} retries, sending to DLQ")
                    failed_events.append(msg.value)
                    committable_offsets.append(msg)
                    del self.retry_counts[msg_key]  # Clean up
                else:
                    # Increment retry count and backoff
                    self.retry_counts[msg_key] = retry_count + 1
                    backoff_ms = self.backoff_base_ms * (2 ** retry_count)
                    logger.warning(f"Message {msg_key} retry {retry_count + 1}/{self.max_retries}, backoff {backoff_ms}ms")
                    time.sleep(backoff_ms / 1000)

            # Send poison messages to DLQ
            if failed_events:
                self.send_to_dlq(failed_events, str(e))

            # CRITICAL: Commit offsets for messages that exceeded retries
            if committable_offsets:
                for msg in committable_offsets:
                    self.consumer.commit({
                        TopicPartition(msg.topic, msg.partition): OffsetAndMetadata(msg.offset + 1, None)
                    })

            failed = len(failed_events)
```

**Alternative: Partial Batch Processing**
Process events individually to isolate poison messages:

```python
def process_batch_safe(self, messages):
    """Process events individually to isolate failures."""
    inserted = 0
    failed = 0

    for msg in messages:
        try:
            # Process single event
            event = self._deserialize_event(msg.value)
            self._process_single_event(event)
            inserted += 1

            # Commit offset for this message
            self.consumer.commit({
                TopicPartition(msg.topic, msg.partition): OffsetAndMetadata(msg.offset + 1, None)
            })

        except Exception as e:
            logger.error(f"Failed to process message {msg.offset}: {e}")
            failed += 1

            # Check retry limit
            msg_key = f"{msg.topic}:{msg.partition}:{msg.offset}"
            retry_count = self.retry_counts.get(msg_key, 0)

            if retry_count >= self.max_retries:
                # Send to DLQ and commit offset to move past poison message
                self.send_to_dlq([msg.value], str(e))
                self.consumer.commit({
                    TopicPartition(msg.topic, msg.partition): OffsetAndMetadata(msg.offset + 1, None)
                })
                del self.retry_counts[msg_key]
            else:
                self.retry_counts[msg_key] = retry_count + 1
                # Don't commit - will retry on next poll
```

**Test Plan**:
```python
# Test poison message handling
def test_poison_message_handling():
    # Send malformed JSON
    producer.send("agent-routing-decisions", b"not-json")

    # Verify consumer doesn't hang
    time.sleep(10)
    assert consumer.is_running()

    # Verify message in DLQ after max retries
    dlq_messages = consume_dlq()
    assert len(dlq_messages) == 1

    # Verify offset was committed (consumer moved past it)
    assert consumer.position() > initial_offset
```

---

### 3. SQL Migration Missing Rollback
**File**: `sql/migrations/001_add_project_context_to_observability_tables.sql`
**Severity**: 🟡 High Priority

**Problem**:
- No DOWN migration script for rollback
- Cannot safely revert if migration causes issues in production
- Violates database migration best practices

**Fix Required**:

Create `sql/migrations/001_add_project_context_to_observability_tables_down.sql`:

```sql
-- Rollback migration 001: Remove project context from observability tables
-- Safe to run multiple times (idempotent)

BEGIN;

-- Drop indexes first (dependencies)
DROP INDEX IF EXISTS idx_agent_actions_project_name;
DROP INDEX IF EXISTS idx_agent_routing_decisions_project_name;
DROP INDEX IF EXISTS idx_agent_detection_failures_project_name;
DROP INDEX IF EXISTS idx_agent_transformation_events_project_name;
DROP INDEX IF EXISTS idx_agent_execution_logs_project_name;

-- Drop view (depends on columns)
DROP VIEW IF EXISTS agent_activity_realtime;

-- Drop function
DROP FUNCTION IF EXISTS extract_project_name(VARCHAR);

-- Remove columns from tables
ALTER TABLE agent_actions
    DROP COLUMN IF EXISTS project_path,
    DROP COLUMN IF EXISTS project_name,
    DROP COLUMN IF EXISTS working_directory;

ALTER TABLE agent_routing_decisions
    DROP COLUMN IF EXISTS project_name;

ALTER TABLE agent_detection_failures
    DROP COLUMN IF EXISTS project_path,
    DROP COLUMN IF EXISTS project_name,
    DROP COLUMN IF EXISTS claude_session_id;

ALTER TABLE agent_transformation_events
    DROP COLUMN IF EXISTS project_path,
    DROP COLUMN IF EXISTS project_name,
    DROP COLUMN IF EXISTS claude_session_id;

ALTER TABLE agent_execution_logs
    DROP COLUMN IF EXISTS project_path,
    DROP COLUMN IF EXISTS project_name,
    DROP COLUMN IF EXISTS claude_session_id,
    DROP COLUMN IF EXISTS terminal_id;

COMMIT;
```

**Test Plan**:
```bash
# Test up migration
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f sql/migrations/001_add_project_context_to_observability_tables.sql

# Test down migration
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f sql/migrations/001_add_project_context_to_observability_tables_down.sql

# Test idempotency (run down twice)
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f sql/migrations/001_add_project_context_to_observability_tables_down.sql

# Test up again (should work after rollback)
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f sql/migrations/001_add_project_context_to_observability_tables.sql
```

---

### 4. Consumer Health Check Race Condition (TOCTOU)
**File**: `consumers/agent_actions_consumer.py:131-135`
**Severity**: 🟡 High Priority

**Problem**:
```python
if (
    self.consumer_instance          # Check 1
    and self.consumer_instance.running  # Check 2
    and not self.consumer_instance.shutdown_event.is_set()  # Check 3
):
    # ⚠️ State could change between checks!
```

**Issues**:
- Time-of-check to time-of-use (TOCTOU) vulnerability
- Consumer could shutdown between checks
- Thread-unsafe access to mutable state
- Could return 200 when consumer is actually dead

**Fix Required**:

```python
import threading

class AgentActionsConsumer:
    def __init__(self, ...):
        self._health_lock = threading.Lock()
        # ... existing init ...

class HealthCheckHandler(BaseHTTPRequestHandler):
    def send_health_response(self):
        """Thread-safe health check response."""
        with self.consumer_instance._health_lock:
            is_healthy = (
                self.consumer_instance is not None
                and self.consumer_instance.running
                and not self.consumer_instance.shutdown_event.is_set()
            )

        if is_healthy:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"status": "healthy", "consumer": "running"}
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"status": "unhealthy", "consumer": "stopped"}
            self.wfile.write(json.dumps(response).encode())
```

**Alternative: Atomic Property**
```python
class AgentActionsConsumer:
    @property
    def is_healthy(self) -> bool:
        """Atomic health check with proper locking."""
        with self._health_lock:
            return (
                self.running
                and not self.shutdown_event.is_set()
                and self.consumer is not None
            )
```

**Test Plan**:
```bash
# Test concurrent health checks during shutdown
parallel curl http://localhost:8080/health ::: {1..100} &
kill -SIGTERM $CONSUMER_PID
wait
# Verify no crashes or inconsistent responses
```

---

## 🟢 Lower Priority (Post-Merge OK)

### 5. Missing Type Hints in Skills
**Files**: `skills/log-execution/execute.py`, `skills/agent-tracking/*/execute*.py`
**Severity**: 🟢 Low

**Issue**: Function signatures lack type annotations
**Fix**: Add type hints for better IDE support and type checking

```python
import argparse

def log_start(args: argparse.Namespace) -> int:
    """Log execution start with type safety."""
    # ...
    return 0

def log_progress(args: argparse.Namespace) -> int:
    """Log execution progress with type safety."""
    # ...
    return 0

def log_complete(args: argparse.Namespace) -> int:
    """Log execution completion with type safety."""
    # ...
    return 0
```

### 6. Magic Numbers and Constants
**Files**: Various
**Severity**: 🟢 Low

**Issue**: Hardcoded values should be class-level constants
**Examples**:
- `execute_batch` page size hardcoded
- Retry counts hardcoded
- Timeout values scattered

**Fix**: Extract to configuration class

```python
class ConsumerConfig:
    BATCH_SIZE = 100
    MAX_RETRIES = 3
    BACKOFF_BASE_MS = 100
    HEALTH_CHECK_PORT = 8080
    REQUEST_TIMEOUT_MS = 30000
```

### 7. Documentation for Archived Docs
**File**: `docs/archive/README.md` (missing)
**Severity**: 🟢 Low

**Fix**: Create README explaining why docs were archived

```markdown
# Archived Documentation

This directory contains documentation that was relevant during development
but is no longer actively maintained. These docs are kept for historical
reference and understanding of design decisions.

## Archived Files
- POC_*.md - Proof of concept documentation from initial development
- MVP_*.md - MVP planning docs, superseded by current implementation
- POLLY_*.md - Polymorphic agent early design docs

## Current Documentation
See the root `/docs` directory for up-to-date documentation.
```

---

## Summary

### Critical Fixes Required Before Merge
1. ✅ Fix /tmp hardcoding → Use `tempfile.gettempdir()`
2. ✅ Fix Kafka offset handling → Add retry limits and commit logic
3. ✅ Create rollback migration → Database safety
4. ✅ Fix health check race condition → Add threading lock

### Can Be Deferred to Follow-Up PR
- Type hints for skills
- Magic number extraction
- Archive documentation README

### Recommendation
**DO NOT MERGE** until critical issues #1-4 are addressed. The current code has production-breaking bugs:
- Won't work on Windows (60%+ of developers)
- Will hang on malformed Kafka messages
- Cannot rollback database migration safely
- Health check has race conditions

**Estimated Fix Time**: 4-6 hours
**Risk Level**: High - these are fundamental platform compatibility and reliability issues

---

## Action Items

- [ ] Fix `agent_execution_logger.py` /tmp hardcoding
- [ ] Fix consumer batch processing with retry logic
- [ ] Create SQL rollback migration
- [ ] Fix health check race condition
- [ ] Run full test suite on Windows
- [ ] Test poison message handling
- [ ] Test migration rollback
- [ ] Create follow-up issues for low-priority items
