# Debug Loop Integration Plan

**Version**: 1.0.0
**Created**: 2025-10-11
**Status**: Ready for Implementation
**Target**: Integrate debug state management with existing agent framework

---

## Executive Summary

This plan integrates the new debug state management system (5 tables + state_manager.py) with our existing agent framework. The integration enables:

- **Error→Success tracking** across debug workflows
- **State snapshots** at critical execution points
- **Quorum decision capture** from validated_task_architect
- **Phase transition logging** from parallel execution
- **LLM metrics correlation** via existing hook_events
- **Verbose/Silent modes** for token optimization

**Key Principle**: Non-invasive integration using ONEX Effect node patterns. No breaking changes to existing code.

---

## 1. Integration Points

### 1.1 Agent Debug Intelligence (`agent-debug-intelligence`)

**File**: `/Volumes/PRO-G40/Code/omniclaude/agents/configs/agent-debug-intelligence.yaml`

**Purpose**: Capture error/success states during multi-dimensional debugging.

**Integration Approach**:
- Add state capture hooks in debug workflow phases (BFROS Framework)
- Capture state at error detection, root cause analysis, and solution validation
- Link error events to success events when fixes are validated

**Required Changes**:
```python
# NEW FILE: /Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution/agent_debug_intelligence.py

from state_manager import get_state_manager, SnapshotType, ErrorCategory, ErrorSeverity
from uuid import UUID, uuid4

class DebugIntelligenceAgent:
    """Enhanced debug intelligence agent with state capture."""

    def __init__(self):
        self.state_manager = get_state_manager()
        self.correlation_id = None
        self.error_snapshot_id = None
        self.error_event_id = None

    async def initialize(self):
        """Initialize state manager."""
        await self.state_manager.initialize()

    async def execute_debug_workflow(self, task_description: str, context: dict):
        """Execute BFROS debug workflow with state capture."""

        # Generate correlation ID for this debug session
        self.correlation_id = uuid4()

        try:
            # Phase 1: Behavior Analysis - Capture initial state
            initial_state = {
                "phase": "behavior_analysis",
                "task_description": task_description,
                "context": context,
                "expected_behavior": context.get("expected_behavior"),
                "actual_behavior": context.get("actual_behavior")
            }

            initial_snapshot_id = await self.state_manager.capture_snapshot(
                agent_state=initial_state,
                correlation_id=self.correlation_id,
                snapshot_type=SnapshotType.CHECKPOINT,
                agent_name="agent-debug-intelligence",
                task_description=f"Debug: {task_description}",
                execution_step=1
            )

            # Phase 2: Fault Localization - Capture error state
            error_state = await self._locate_fault(context)

            if error_state:
                # Capture error snapshot
                self.error_snapshot_id = await self.state_manager.capture_snapshot(
                    agent_state=error_state,
                    correlation_id=self.correlation_id,
                    snapshot_type=SnapshotType.ERROR,
                    agent_name="agent-debug-intelligence",
                    task_description=f"Error detected: {error_state.get('error_type')}",
                    execution_step=2,
                    parent_snapshot_id=initial_snapshot_id
                )

                # Record error event
                self.error_event_id = await self.state_manager.record_error(
                    exception=Exception(error_state.get("error_message", "Unknown error")),
                    snapshot_id=self.error_snapshot_id,
                    correlation_id=self.correlation_id,
                    agent_name="agent-debug-intelligence",
                    error_category=ErrorCategory.AGENT,
                    error_severity=self._determine_severity(error_state),
                    is_recoverable=True,
                    metadata={
                        "fault_location": error_state.get("fault_location"),
                        "affected_components": error_state.get("affected_components"),
                        "error_propagation": error_state.get("error_propagation")
                    }
                )

            # Phase 3: Root Cause Analysis
            root_cause = await self._analyze_root_cause(error_state, context)

            # Phase 4: Solution Development
            solution = await self._develop_solution(root_cause)

            # Phase 5: Solution Validation - Capture success state
            validation_result = await self._validate_solution(solution)

            if validation_result["success"]:
                # Capture success snapshot
                success_state = {
                    "phase": "solution_validated",
                    "solution": solution,
                    "validation_result": validation_result,
                    "quality_improvement": validation_result.get("quality_delta"),
                    "tests_passed": validation_result.get("tests_passed")
                }

                success_snapshot_id = await self.state_manager.capture_snapshot(
                    agent_state=success_state,
                    correlation_id=self.correlation_id,
                    snapshot_type=SnapshotType.SUCCESS,
                    agent_name="agent-debug-intelligence",
                    task_description="Solution validated successfully",
                    execution_step=5,
                    parent_snapshot_id=self.error_snapshot_id
                )

                # Record success event
                success_event_id = await self.state_manager.record_success(
                    snapshot_id=success_snapshot_id,
                    correlation_id=self.correlation_id,
                    agent_name="agent-debug-intelligence",
                    operation_name="debug_workflow_completion",
                    success_type="validation_pass",
                    quality_score=validation_result.get("quality_score"),
                    execution_time_ms=validation_result.get("execution_time_ms"),
                    metadata={
                        "fix_type": solution.get("fix_type"),
                        "anti_patterns_removed": solution.get("anti_patterns_removed", []),
                        "tests_added": solution.get("tests_added", 0)
                    }
                )

                # Link error to success for pattern learning
                if self.error_event_id:
                    await self.state_manager.link_error_to_success(
                        error_id=self.error_event_id,
                        success_id=success_event_id,
                        stf_name=solution.get("stf_name", "debug_fix_applied"),
                        recovery_strategy="systematic_debug_workflow",
                        recovery_duration_ms=validation_result.get("total_duration_ms"),
                        intermediate_steps=5,  # BFROS phases
                        confidence_score=validation_result.get("confidence_score", 1.0)
                    )

            return {
                "success": validation_result["success"],
                "correlation_id": str(self.correlation_id),
                "error_event_id": str(self.error_event_id) if self.error_event_id else None,
                "solution": solution
            }

        except Exception as e:
            # Capture unhandled error
            await self.state_manager.record_error(
                exception=e,
                correlation_id=self.correlation_id,
                agent_name="agent-debug-intelligence",
                error_category=ErrorCategory.FRAMEWORK,
                error_severity=ErrorSeverity.CRITICAL,
                is_recoverable=False
            )
            raise

    def _determine_severity(self, error_state: dict) -> ErrorSeverity:
        """Determine error severity from error state."""
        impact = error_state.get("impact", "medium")
        severity_map = {
            "critical": ErrorSeverity.CRITICAL,
            "high": ErrorSeverity.HIGH,
            "medium": ErrorSeverity.MEDIUM,
            "low": ErrorSeverity.LOW
        }
        return severity_map.get(impact.lower(), ErrorSeverity.MEDIUM)

    async def _locate_fault(self, context: dict) -> dict:
        """Fault localization phase (implement actual logic)."""
        # Placeholder - implement actual fault localization
        return {
            "error_type": "ValidationError",
            "error_message": "Example error",
            "fault_location": "module.function",
            "affected_components": ["component1"],
            "error_propagation": ["step1", "step2"]
        }

    async def _analyze_root_cause(self, error_state: dict, context: dict) -> dict:
        """Root cause analysis phase."""
        # Placeholder - implement actual analysis
        return {"root_cause": "example_root_cause"}

    async def _develop_solution(self, root_cause: dict) -> dict:
        """Solution development phase."""
        # Placeholder - implement actual solution generation
        return {
            "fix_type": "code_modification",
            "stf_name": "apply_validation_fix",
            "anti_patterns_removed": ["pattern1"],
            "tests_added": 3
        }

    async def _validate_solution(self, solution: dict) -> dict:
        """Solution validation phase."""
        # Placeholder - implement actual validation
        return {
            "success": True,
            "quality_score": 0.85,
            "quality_delta": 0.15,
            "tests_passed": True,
            "execution_time_ms": 1500,
            "total_duration_ms": 5000,
            "confidence_score": 0.95
        }
```

---

### 1.2 Parallel Coordinator (`agent_dispatcher.py`)

**File**: `/Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution/agent_dispatcher.py`

**Purpose**: Capture phase transitions during parallel task execution.

**Integration Approach**:
- Capture workflow step snapshots at batch start/end
- Track parallel execution state transitions
- Link to trace_logger for unified observability

**Required Changes**:
```python
# MODIFY: /Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution/agent_dispatcher.py

from state_manager import get_state_manager, SnapshotType
from uuid import uuid4

class ParallelCoordinator:
    def __init__(self, ...):
        # ... existing initialization ...
        self.state_manager = get_state_manager()
        self.workflow_correlation_id = None

    async def initialize(self):
        """Initialize coordinator and state manager."""
        # ... existing initialization ...
        await self.state_manager.initialize()

    async def execute_parallel(
        self,
        tasks: List[AgentTask]
    ) -> Dict[str, AgentResult]:
        """Execute tasks with state capture at phase boundaries."""

        # Generate workflow correlation ID
        self.workflow_correlation_id = uuid4()

        start_time = time.time()

        # Start coordinator trace (existing)
        self._coordinator_trace_id = await self.trace_logger.start_coordinator_trace(...)

        # INTEGRATION: Capture initial workflow state
        initial_workflow_state = {
            "phase": "initialization",
            "total_tasks": len(tasks),
            "dependency_graph": self._build_dependency_graph(tasks),
            "task_descriptions": [t.description for t in tasks],
            "coordinator_trace_id": self._coordinator_trace_id
        }

        await self.state_manager.capture_snapshot(
            agent_state=initial_workflow_state,
            correlation_id=self.workflow_correlation_id,
            snapshot_type=SnapshotType.CHECKPOINT,
            agent_name="parallel-coordinator",
            task_description=f"Parallel workflow: {len(tasks)} tasks",
            execution_step=0
        )

        # ... existing dependency graph building ...

        results = {}
        completed_tasks = set()
        step_number = 1

        while len(completed_tasks) < len(tasks):
            # Find ready tasks (existing logic)
            ready_tasks = [...]

            if not ready_tasks:
                # Deadlock detected
                # INTEGRATION: Capture error state
                deadlock_state = {
                    "phase": "deadlock",
                    "completed_tasks": list(completed_tasks),
                    "pending_tasks": [t.task_id for t in tasks if t.task_id not in completed_tasks],
                    "dependency_graph": dependency_graph
                }

                snapshot_id = await self.state_manager.capture_snapshot(
                    agent_state=deadlock_state,
                    correlation_id=self.workflow_correlation_id,
                    snapshot_type=SnapshotType.ERROR,
                    agent_name="parallel-coordinator",
                    task_description="Dependency deadlock detected",
                    execution_step=step_number
                )

                await self.state_manager.record_error(
                    exception=Exception(f"Dependency deadlock: {deadlock_state['pending_tasks']}"),
                    snapshot_id=snapshot_id,
                    correlation_id=self.workflow_correlation_id,
                    agent_name="parallel-coordinator",
                    error_category=ErrorCategory.FRAMEWORK,
                    error_severity=ErrorSeverity.HIGH,
                    is_recoverable=False
                )
                break

            # INTEGRATION: Capture pre-batch state
            pre_batch_state = {
                "phase": "batch_start",
                "batch_number": step_number,
                "ready_tasks": [t.task_id for t in ready_tasks],
                "completed_so_far": list(completed_tasks),
                "remaining": len(tasks) - len(completed_tasks)
            }

            pre_batch_snapshot_id = await self.state_manager.capture_snapshot(
                agent_state=pre_batch_state,
                correlation_id=self.workflow_correlation_id,
                snapshot_type=SnapshotType.PRE_TRANSFORM,
                agent_name="parallel-coordinator",
                task_description=f"Starting batch {step_number}",
                execution_step=step_number
            )

            # Log batch start (existing)
            await self.trace_logger.log_event(...)

            # Execute ready tasks in parallel (existing)
            batch_results = await self._execute_batch(ready_tasks)

            # Update results (existing)
            results.update(batch_results)
            completed_tasks.update(batch_results.keys())

            # INTEGRATION: Capture post-batch state
            post_batch_state = {
                "phase": "batch_complete",
                "batch_number": step_number,
                "batch_results": {tid: r.success for tid, r in batch_results.items()},
                "success_count": sum(1 for r in batch_results.values() if r.success),
                "failure_count": sum(1 for r in batch_results.values() if not r.success),
                "total_completed": len(completed_tasks),
                "progress_percentage": (len(completed_tasks) / len(tasks)) * 100
            }

            await self.state_manager.capture_snapshot(
                agent_state=post_batch_state,
                correlation_id=self.workflow_correlation_id,
                snapshot_type=SnapshotType.POST_TRANSFORM,
                agent_name="parallel-coordinator",
                task_description=f"Completed batch {step_number}",
                execution_step=step_number,
                parent_snapshot_id=pre_batch_snapshot_id
            )

            # Log batch completion (existing)
            await self.trace_logger.log_event(...)

            step_number += 1

        # Calculate total execution time (existing)
        total_time_ms = (time.time() - start_time) * 1000

        # INTEGRATION: Capture final workflow state
        final_state = {
            "phase": "completion",
            "total_tasks": len(tasks),
            "completed_tasks": len(results),
            "successful_tasks": sum(1 for r in results.values() if r.success),
            "failed_tasks": sum(1 for r in results.values() if not r.success),
            "total_duration_ms": total_time_ms,
            "batches_executed": step_number - 1
        }

        final_snapshot_id = await self.state_manager.capture_snapshot(
            agent_state=final_state,
            correlation_id=self.workflow_correlation_id,
            snapshot_type=SnapshotType.SUCCESS,
            agent_name="parallel-coordinator",
            task_description="Workflow completed",
            execution_step=step_number
        )

        # Record success event
        await self.state_manager.record_success(
            snapshot_id=final_snapshot_id,
            correlation_id=self.workflow_correlation_id,
            agent_name="parallel-coordinator",
            operation_name="parallel_workflow_execution",
            success_type="task_completion",
            execution_time_ms=int(total_time_ms),
            metadata=final_state
        )

        # End coordinator trace (existing)
        await self.trace_logger.end_coordinator_trace(...)

        return results
```

---

### 1.3 Validated Task Architect (`validated_task_architect.py`)

**File**: `/Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution/validated_task_architect.py`

**Purpose**: Capture quorum decisions and retry attempts.

**Integration Approach**:
- Capture state at each quorum validation attempt
- Track validation deficiencies and retry logic
- Link failed validations to eventual successes

**Required Changes**:
```python
# MODIFY: /Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution/validated_task_architect.py

from state_manager import get_state_manager, SnapshotType, ErrorCategory, ErrorSeverity
from uuid import uuid4

class ValidatedTaskArchitect:
    def __init__(self):
        self.quorum = MinimalQuorum()
        self.max_retries = 3
        # INTEGRATION: Add state manager
        self.state_manager = get_state_manager()
        self.validation_correlation_id = None

    async def breakdown_tasks_with_validation(
        self,
        user_prompt: str,
        global_context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Break down tasks with state capture at quorum decisions."""

        # INTEGRATION: Initialize state manager
        await self.state_manager.initialize()

        # Generate correlation ID for this validation session
        self.validation_correlation_id = uuid4()

        augmented_prompt = user_prompt
        attempt_history = []
        error_event_ids = []  # Track error events for each failed attempt

        for attempt in range(self.max_retries):
            print(f"\n{'='*60}")
            print(f"ATTEMPT {attempt + 1}/{self.max_retries}")
            print(f"{'='*60}")

            # INTEGRATION: Capture pre-validation state
            pre_validation_state = {
                "phase": "pre_validation",
                "attempt": attempt + 1,
                "max_retries": self.max_retries,
                "user_prompt": user_prompt,
                "augmented_prompt": augmented_prompt if attempt > 0 else None,
                "previous_deficiencies": attempt_history[-1].get("deficiencies") if attempt_history else None
            }

            pre_validation_snapshot_id = await self.state_manager.capture_snapshot(
                agent_state=pre_validation_state,
                correlation_id=self.validation_correlation_id,
                snapshot_type=SnapshotType.CHECKPOINT,
                agent_name="validated-task-architect",
                task_description=f"Quorum validation attempt {attempt + 1}",
                execution_step=attempt + 1
            )

            # Generate task breakdown (existing)
            task_breakdown = await self._generate_breakdown(
                augmented_prompt, global_context
            )

            # Store attempt (existing)
            attempt_history.append({...})

            # Validate with quorum (existing)
            print(f"\n🔍 Validating with quorum...")
            result = await self.quorum.validate_intent(user_prompt, task_breakdown)

            # INTEGRATION: Capture quorum decision state
            quorum_decision_state = {
                "phase": "quorum_decision",
                "attempt": attempt + 1,
                "decision": result.decision.value,
                "confidence": result.confidence,
                "deficiencies": result.deficiencies,
                "model_responses": result.model_responses,
                "task_breakdown": task_breakdown
            }

            post_validation_snapshot_id = await self.state_manager.capture_snapshot(
                agent_state=quorum_decision_state,
                correlation_id=self.validation_correlation_id,
                snapshot_type=SnapshotType.SUCCESS if result.decision == ValidationDecision.PASS else SnapshotType.ERROR,
                agent_name="validated-task-architect",
                task_description=f"Quorum decision: {result.decision.value}",
                execution_step=attempt + 1,
                parent_snapshot_id=pre_validation_snapshot_id
            )

            if result.decision == ValidationDecision.PASS:
                print(f"\n✅ Validation PASSED on attempt {attempt + 1}")

                # INTEGRATION: Record success event
                success_event_id = await self.state_manager.record_success(
                    snapshot_id=post_validation_snapshot_id,
                    correlation_id=self.validation_correlation_id,
                    agent_name="validated-task-architect",
                    operation_name="quorum_validation",
                    success_type="validation_pass",
                    quality_score=result.confidence,
                    metadata={
                        "attempts_required": attempt + 1,
                        "model_consensus": result.scores,
                        "breakdown_task_count": len(task_breakdown.get("tasks", []))
                    }
                )

                # INTEGRATION: Link any previous errors to this success
                for error_id in error_event_ids:
                    await self.state_manager.link_error_to_success(
                        error_id=error_id,
                        success_id=success_event_id,
                        stf_name="quorum_validation_retry",
                        recovery_strategy="prompt_augmentation",
                        intermediate_steps=attempt + 1,
                        confidence_score=result.confidence
                    )

                # Add final validation task (existing)
                enhanced_breakdown = self._add_final_validation_task(...)

                return {
                    "breakdown": enhanced_breakdown,
                    "validated": True,
                    "attempts": attempt + 1,
                    "quorum_result": {...},
                    "attempt_history": attempt_history,
                    # INTEGRATION: Add correlation info
                    "correlation_id": str(self.validation_correlation_id),
                    "success_event_id": str(success_event_id)
                }

            elif result.decision == ValidationDecision.RETRY:
                print(f"\n⚠️  Validation requires RETRY:")

                # INTEGRATION: Record error event for retry
                error_event_id = await self.state_manager.record_error(
                    exception=Exception(f"Validation retry required: {', '.join(result.deficiencies)}"),
                    snapshot_id=post_validation_snapshot_id,
                    correlation_id=self.validation_correlation_id,
                    agent_name="validated-task-architect",
                    error_category=ErrorCategory.AGENT,
                    error_severity=ErrorSeverity.MEDIUM,
                    is_recoverable=True,
                    metadata={
                        "attempt": attempt + 1,
                        "deficiencies": result.deficiencies,
                        "confidence": result.confidence,
                        "decision": result.decision.value
                    }
                )
                error_event_ids.append(error_event_id)

                if attempt < self.max_retries - 1:
                    print(f"\n🔄 Retrying with feedback...")
                    # Augment prompt with feedback (existing)
                    augmented_prompt = self._augment_prompt(...)
                else:
                    print(f"\n❌ Max retries reached")
                    return {
                        "breakdown": task_breakdown,
                        "validated": False,
                        "attempts": attempt + 1,
                        "quorum_result": {...},
                        "attempt_history": attempt_history,
                        "error": f"Max retries ({self.max_retries}) exceeded",
                        # INTEGRATION: Add correlation info
                        "correlation_id": str(self.validation_correlation_id),
                        "error_event_ids": [str(eid) for eid in error_event_ids]
                    }

            else:  # FAIL
                print(f"\n❌ Validation FAILED critically")

                # INTEGRATION: Record critical error
                error_event_id = await self.state_manager.record_error(
                    exception=Exception(f"Validation failed critically: {', '.join(result.deficiencies)}"),
                    snapshot_id=post_validation_snapshot_id,
                    correlation_id=self.validation_correlation_id,
                    agent_name="validated-task-architect",
                    error_category=ErrorCategory.AGENT,
                    error_severity=ErrorSeverity.CRITICAL,
                    is_recoverable=False,
                    metadata={
                        "attempt": attempt + 1,
                        "deficiencies": result.deficiencies,
                        "confidence": result.confidence,
                        "decision": result.decision.value
                    }
                )

                return {
                    "breakdown": task_breakdown,
                    "validated": False,
                    "attempts": attempt + 1,
                    "quorum_result": {...},
                    "attempt_history": attempt_history,
                    "error": f"Validation failed critically: {result.deficiencies}",
                    # INTEGRATION: Add correlation info
                    "correlation_id": str(self.validation_correlation_id),
                    "error_event_id": str(error_event_id)
                }

        # Should never reach here
        return {...}
```

---

## 2. Verbose/Silent Mode Integration

### 2.1 Mode Toggle Implementation

**Purpose**: Allow token-efficient logging by toggling between verbose and silent modes.

**Design**:
- **VERBOSE mode**: Full logging with detailed messages (default for debugging)
- **SILENT mode**: Minimal logging, database operations only (production/token-sensitive)

**Implementation**:
```python
# USAGE EXAMPLE: Toggle modes based on environment or user preference

from state_manager import get_state_manager, VerboseMode

# Option 1: Set mode globally
state_manager = get_state_manager()
state_manager.set_verbose_mode(VerboseMode.SILENT)  # Production mode

# Option 2: Context manager for temporary silent mode
async with state_manager.silent_mode():
    # Operations here use SILENT mode
    await state_manager.capture_snapshot(...)

# Option 3: Environment variable
import os
verbose_mode = VerboseMode.VERBOSE if os.getenv("DEBUG_STATE_VERBOSE", "false").lower() == "true" else VerboseMode.SILENT
state_manager.set_verbose_mode(verbose_mode)
```

**Token Savings**:
- VERBOSE mode: ~50-100 tokens per operation (logs to console + DB)
- SILENT mode: ~5-10 tokens per operation (DB only, no console output)
- **Estimated savings**: 80-90% token reduction in SILENT mode

### 2.2 Where Silent Mode Matters

| Context | Mode | Rationale |
|---------|------|-----------|
| Development/Debug | VERBOSE | Need detailed visibility into state transitions |
| Production LLM calls | SILENT | Minimize token usage, reduce cost |
| CI/CD automated tests | VERBOSE | Detailed logs for test debugging |
| User-facing operations | SILENT | Fast, token-efficient execution |
| Error investigations | VERBOSE | Maximum detail for troubleshooting |

---

## 3. LLM Metrics Integration

### 3.1 Hook Events Reuse

**Existing Table**: `hook_events` (already captures LLM interactions)

**View**: `debug_llm_call_summary` (created in migration 005)

**Integration Approach**: Query existing hook_events instead of creating new LLM tracking tables.

**Query Examples**:
```sql
-- Get all LLM calls for a correlation_id
SELECT
  hook_event_id,
  tool_name,
  quality_score,
  success_classification,
  call_timestamp
FROM agent_observability.debug_llm_call_summary
WHERE correlation_id = '<correlation_id_here>'
ORDER BY call_timestamp;

-- Aggregate LLM metrics for debug workflow
SELECT
  correlation_id,
  COUNT(*) as total_llm_calls,
  AVG(CAST(quality_score AS FLOAT)) as avg_quality_score,
  COUNT(*) FILTER (WHERE success_classification = 'success') as successful_calls,
  COUNT(*) FILTER (WHERE success_classification = 'failure') as failed_calls
FROM agent_observability.debug_llm_call_summary
WHERE correlation_id IN (
  SELECT DISTINCT correlation_id
  FROM agent_observability.debug_state_snapshots
  WHERE agent_name = 'agent-debug-intelligence'
    AND captured_at >= NOW() - INTERVAL '24 hours'
)
GROUP BY correlation_id;
```

### 3.2 Correlation with Debug Events

**Pattern**: Link hook_events to debug_state_snapshots via correlation_id

**Implementation**:
```python
# UTILITY FUNCTION: Get LLM metrics for debug session

async def get_llm_metrics_for_debug_session(
    db_layer: DatabaseIntegrationLayer,
    correlation_id: UUID
) -> Dict[str, Any]:
    """
    Get LLM call metrics for a debug session.

    Returns:
        - total_calls: Total LLM calls made
        - avg_quality: Average quality score
        - success_rate: Percentage of successful calls
        - call_timeline: List of calls with timestamps
    """
    query = """
        SELECT
            COUNT(*) as total_calls,
            AVG(CAST(quality_score AS FLOAT)) as avg_quality,
            COUNT(*) FILTER (WHERE success_classification = 'success')::FLOAT /
                COUNT(*)::FLOAT as success_rate,
            json_agg(
                json_build_object(
                    'tool_name', tool_name,
                    'quality_score', quality_score,
                    'success', success_classification,
                    'timestamp', call_timestamp
                ) ORDER BY call_timestamp
            ) as call_timeline
        FROM agent_observability.debug_llm_call_summary
        WHERE correlation_id = $1
    """

    result = await db_layer.execute_query(
        query,
        str(correlation_id),
        fetch="one"
    )

    return dict(result) if result else {
        "total_calls": 0,
        "avg_quality": None,
        "success_rate": 0.0,
        "call_timeline": []
    }
```

### 3.3 Accuracy/Latency/Cost Rollup

**Query**: Aggregate LLM performance metrics across debug sessions

```sql
-- Accuracy, latency, and success metrics for debug workflows
CREATE OR REPLACE VIEW agent_observability.debug_llm_performance_summary AS
SELECT
  dss.agent_name,
  dss.snapshot_type,
  COUNT(DISTINCT dss.correlation_id) as debug_sessions,
  COUNT(llm.hook_event_id) as total_llm_calls,
  AVG(CAST(llm.quality_score AS FLOAT)) as avg_quality_score,
  COUNT(llm.hook_event_id) FILTER (WHERE llm.success_classification = 'success')::FLOAT /
    NULLIF(COUNT(llm.hook_event_id), 0)::FLOAT as success_rate,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
    EXTRACT(EPOCH FROM (dss.captured_at - LAG(dss.captured_at) OVER (
      PARTITION BY dss.correlation_id ORDER BY dss.captured_at
    )))
  ) as median_step_latency_seconds
FROM agent_observability.debug_state_snapshots dss
LEFT JOIN agent_observability.debug_llm_call_summary llm
  ON llm.correlation_id = dss.correlation_id
WHERE dss.agent_name IN ('agent-debug-intelligence', 'validated-task-architect')
  AND dss.captured_at >= NOW() - INTERVAL '7 days'
GROUP BY dss.agent_name, dss.snapshot_type;

COMMENT ON VIEW agent_observability.debug_llm_performance_summary IS
  'Aggregates LLM performance metrics (accuracy, latency, success rate) for debug workflows';
```

---

## 4. Deployment Sequence

### Phase 1: Foundation (Week 1)

**Objectives**:
- Deploy database schema
- Initialize state_manager in existing agents
- Verify database connectivity

**Steps**:
1. **Run Migration 005**
   ```bash
   # From agents/parallel_execution/migrations/
   psql -h localhost -p 5436 -U postgres -d omninode_bridge \
     -f 005_debug_state_management.sql
   ```

2. **Verify Migration**
   ```bash
   # Test migration with quickstart
   bash MIGRATION_005_QUICKSTART.md
   ```

3. **Initialize State Manager**
   ```python
   # Test state manager initialization
   python -c "
   import asyncio
   from state_manager import get_state_manager

   async def test():
       sm = get_state_manager()
       success = await sm.initialize()
       print(f'State manager initialized: {success}')

   asyncio.run(test())
   "
   ```

4. **Testing Checkpoint**
   - ✅ Migration applied without errors
   - ✅ All 5 new tables exist
   - ✅ Views and functions created
   - ✅ State manager connects to database

### Phase 2: Agent Integration (Week 2)

**Objectives**:
- Integrate agent-debug-intelligence
- Integrate parallel coordinator
- Test basic state capture

**Steps**:
1. **Create agent_debug_intelligence.py**
   - Implement file from Section 1.1
   - Add BFROS phase state capture
   - Test with sample debug workflow

2. **Modify agent_dispatcher.py**
   - Apply changes from Section 1.2
   - Add state capture at batch boundaries
   - Test with sample parallel execution

3. **Testing Checkpoint**
   - ✅ Debug intelligence captures error/success events
   - ✅ Parallel coordinator captures workflow steps
   - ✅ State snapshots created in database
   - ✅ Error→success links work correctly

### Phase 3: Quorum Integration (Week 2-3)

**Objectives**:
- Integrate validated_task_architect
- Capture quorum decisions
- Test retry workflows

**Steps**:
1. **Modify validated_task_architect.py**
   - Apply changes from Section 1.3
   - Add quorum decision state capture
   - Test with sample validation workflows

2. **Testing Checkpoint**
   - ✅ Quorum decisions captured
   - ✅ Retry attempts tracked
   - ✅ Failed validations linked to eventual successes
   - ✅ Confidence scores stored

### Phase 4: LLM Metrics & Observability (Week 3)

**Objectives**:
- Link hook_events to debug states
- Create performance dashboards
- Test correlation queries

**Steps**:
1. **Create utility functions**
   - Implement `get_llm_metrics_for_debug_session()`
   - Create performance summary queries
   - Test correlation lookups

2. **Create Observability Dashboard**
   ```python
   # Example: Generate observability report
   python agents/parallel_execution/observability_report.py \
     --correlation-id <uuid> \
     --include-llm-metrics \
     --include-state-snapshots
   ```

3. **Testing Checkpoint**
   - ✅ LLM metrics query correctly
   - ✅ Correlation_id links work
   - ✅ Performance summaries generate
   - ✅ Dashboard displays debug workflows

### Phase 5: Production Rollout (Week 4)

**Objectives**:
- Enable silent mode for production
- Monitor performance impact
- Fine-tune thresholds

**Steps**:
1. **Configure Modes**
   ```python
   # Production configuration
   state_manager = get_state_manager()
   state_manager.set_verbose_mode(VerboseMode.SILENT)
   ```

2. **Monitor Metrics**
   - Query performance (<200ms target)
   - Token usage reduction
   - Database load

3. **Optimization**
   - Adjust snapshot frequency if needed
   - Fine-tune error severity thresholds
   - Optimize correlation queries

4. **Final Checkpoint**
   - ✅ Silent mode reduces token usage by 80%+
   - ✅ Query performance meets targets
   - ✅ No performance degradation in agent execution
   - ✅ All integration tests pass

---

## 5. Rollback Procedures

### Emergency Rollback

**If critical issues occur during deployment:**

1. **Rollback Database**
   ```bash
   psql -h localhost -p 5436 -U postgres -d omninode_bridge \
     -f agents/parallel_execution/migrations/005_rollback_debug_state_management.sql
   ```

2. **Revert Code Changes**
   ```bash
   # If using git
   git revert <commit-hash-of-integration>

   # Or manually remove state_manager calls
   # Comment out all state_manager.* calls in:
   # - agent_debug_intelligence.py
   # - agent_dispatcher.py
   # - validated_task_architect.py
   ```

3. **Verify System Recovery**
   ```bash
   # Test basic agent execution
   python agents/parallel_execution/agent_dispatcher.py
   ```

### Partial Rollback

**If only specific integration fails:**

- **Agent Debug Intelligence**: Comment out state capture calls, keep rest
- **Parallel Coordinator**: Remove state capture, keep trace logging
- **Validated Task Architect**: Disable quorum state capture only

---

## 6. Testing Strategy

### Unit Tests

```python
# tests/test_state_manager_integration.py

import pytest
from uuid import uuid4
from state_manager import get_state_manager, SnapshotType

@pytest.mark.asyncio
async def test_state_capture_in_debug_workflow():
    """Test state capture during debug workflow."""
    sm = get_state_manager()
    await sm.initialize()

    correlation_id = uuid4()

    # Capture error snapshot
    error_state = {"phase": "error", "error_type": "ValidationError"}
    error_snapshot_id = await sm.capture_snapshot(
        agent_state=error_state,
        correlation_id=correlation_id,
        snapshot_type=SnapshotType.ERROR,
        agent_name="agent-debug-intelligence",
        task_description="Test error"
    )

    assert error_snapshot_id is not None

    # Record error event
    error_event_id = await sm.record_error(
        exception=Exception("Test error"),
        snapshot_id=error_snapshot_id,
        correlation_id=correlation_id,
        agent_name="agent-debug-intelligence"
    )

    assert error_event_id is not None

@pytest.mark.asyncio
async def test_quorum_validation_state_capture():
    """Test state capture during quorum validation."""
    # Similar test for validated_task_architect integration
    pass
```

### Integration Tests

```bash
# tests/integration/test_full_debug_loop.sh

#!/bin/bash

# Test full debug loop with state capture
echo "Testing full debug loop integration..."

# 1. Run debug workflow
python agents/parallel_execution/agent_debug_intelligence.py \
  --task "Debug validation error" \
  --capture-state

# 2. Verify state snapshots created
python -c "
import asyncio
from database_integration import get_database_layer

async def verify():
    db = get_database_layer()
    await db.initialize()

    result = await db.execute_query(
        'SELECT COUNT(*) FROM agent_observability.debug_state_snapshots WHERE agent_name = %s',
        'agent-debug-intelligence',
        fetch='val'
    )

    print(f'State snapshots created: {result}')
    assert result > 0, 'No snapshots found!'

asyncio.run(verify())
"

echo "✅ Integration test passed"
```

---

## 7. Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| State snapshot capture | <50ms | Database INSERT latency |
| Error event recording | <100ms | Full error capture + snapshot |
| Success event recording | <100ms | Full success capture + snapshot |
| Correlation query | <200ms | JOIN across state/error/success tables |
| LLM metrics query | <150ms | View query for correlation_id |
| Token savings (SILENT mode) | 80%+ | Compare VERBOSE vs SILENT output |
| Agent execution overhead | <5% | Compare execution time with/without state capture |

---

## 8. Monitoring & Alerts

### Key Metrics to Monitor

1. **State Capture Rate**
   ```sql
   -- Snapshots created per hour
   SELECT
     DATE_TRUNC('hour', captured_at) as hour,
     COUNT(*) as snapshots_created,
     snapshot_type
   FROM agent_observability.debug_state_snapshots
   WHERE captured_at >= NOW() - INTERVAL '24 hours'
   GROUP BY hour, snapshot_type
   ORDER BY hour DESC;
   ```

2. **Error→Success Correlation Rate**
   ```sql
   -- Percentage of errors that led to success
   SELECT
     COUNT(DISTINCT esc.error_event_id)::FLOAT /
       NULLIF(COUNT(DISTINCT e.id), 0)::FLOAT as correlation_rate
   FROM agent_observability.debug_error_events e
   LEFT JOIN agent_observability.debug_error_success_correlation esc
     ON esc.error_event_id = e.id
   WHERE e.occurred_at >= NOW() - INTERVAL '24 hours';
   ```

3. **Database Performance**
   ```sql
   -- Query latency monitoring
   SELECT
     query,
     mean_exec_time,
     calls
   FROM pg_stat_statements
   WHERE query LIKE '%debug_state_snapshots%'
   ORDER BY mean_exec_time DESC
   LIMIT 10;
   ```

---

## 9. Success Criteria

| Criterion | Definition | Validation |
|-----------|------------|------------|
| ✅ State capture works | Snapshots created in all 3 agents | Query database, verify counts |
| ✅ Error→Success links | Failed attempts linked to eventual success | Check correlation table |
| ✅ Quorum decisions tracked | All validation attempts captured | Verify snapshot_type diversity |
| ✅ LLM metrics correlated | hook_events linked via correlation_id | Join query returns results |
| ✅ Silent mode effective | 80%+ token reduction | Compare logs VERBOSE vs SILENT |
| ✅ Performance acceptable | <5% execution overhead | Benchmark with/without state capture |
| ✅ No breaking changes | All existing tests pass | Run full test suite |

---

## 10. Documentation Updates

After deployment, update the following documentation:

1. **ONEX Patterns Guide** - Add state management patterns
2. **Agent Development Guide** - Document state capture best practices
3. **Observability Dashboard** - Add debug loop metrics section
4. **API Documentation** - Document state_manager public API

---

## Appendix A: File Change Summary

| File | Change Type | Lines Changed | Risk Level |
|------|-------------|---------------|------------|
| `agent_debug_intelligence.py` | NEW | ~350 | Medium (new file) |
| `agent_dispatcher.py` | MODIFY | ~80 additions | Low (non-breaking) |
| `validated_task_architect.py` | MODIFY | ~120 additions | Low (non-breaking) |
| `005_debug_state_management.sql` | NEW | ~575 | Low (reversible) |
| Database schema | EXTEND | 5 tables + 2 views | Low (additive only) |

---

## Appendix B: Quick Reference Commands

```bash
# Deploy migration
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/005_debug_state_management.sql

# Test state manager
python agents/parallel_execution/state_manager.py

# Run integration tests
pytest tests/test_state_manager_integration.py

# Query debug sessions
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM agent_observability.debug_workflow_context LIMIT 10;"

# Check LLM metrics
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM agent_observability.debug_llm_call_summary WHERE correlation_id = '<uuid>';"

# Rollback if needed
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -f agents/parallel_execution/migrations/005_rollback_debug_state_management.sql
```

---

**End of Integration Plan**

**Next Steps**: Review plan, validate approach, proceed with Phase 1 deployment.
