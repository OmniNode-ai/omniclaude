# Phase-by-Phase Execution Control Guide

## Overview

The enhanced `dispatch_runner.py` now supports granular phase-level control for debugging, testing, and workflow optimization. This enables you to execute specific phases, stop at checkpoints, and inspect intermediate state.

## Workflow Phases

The dispatch runner implements a 5-phase workflow:

| Phase | Name | Description | Dependencies |
|-------|------|-------------|--------------|
| 0 | Context Gathering | RAG intelligence collection | None |
| 1 | Quorum Validation | AI-powered task breakdown validation | None |
| 2 | Task Planning | Task preparation and planning | None |
| 3 | Context Filtering | Per-task context filtering | Phase 0 (if enabled) |
| 4 | Parallel Execution | Parallel agent task execution | Phase 3 |

## New CLI Flags

### Phase Control

```bash
--only-phase N              # Execute only phase N (0-4)
--stop-after-phase N        # Execute phases 0-N, then stop
--skip-phases N,M,...       # Skip specified phases (comma-separated)
```

### State Management

```bash
--save-phase-state FILE     # Save phase state to JSON file
--load-phase-state FILE     # Load phase state from JSON file
```

### Existing Flags (Backward Compatible)

```bash
--enable-context            # Enable Phase 0 (context gathering)
--enable-quorum             # Enable Phase 1 (quorum validation)
--interactive, -i           # Enable interactive checkpoints
--input-file, -f FILE       # Read input from JSON file
--resume-session FILE       # Resume interactive session
```

## Usage Examples

### 1. Debug Context Gathering Only

Execute only Phase 0 to inspect gathered context without running tasks:

```bash
python dispatch_runner.py \
  --only-phase 0 \
  --enable-context \
  --save-phase-state context_debug.json \
  < tasks.json
```

This outputs:
- Phase 0 timing and results
- Gathered context summary
- Saved state for inspection

### 2. Test Quorum Validation

Execute Phases 0-1 to test context gathering and quorum validation:

```bash
python dispatch_runner.py \
  --stop-after-phase 1 \
  --enable-context \
  --enable-quorum \
  --save-phase-state validation_debug.json \
  < tasks.json
```

This outputs:
- Phase 0: Context gathering results
- Phase 1: Quorum validation results with retry attempts
- Deficiencies and confidence scores
- Saved state including quorum result

### 3. Skip Expensive Phases

Skip context gathering and quorum validation for faster iteration:

```bash
python dispatch_runner.py \
  --skip-phases 0,1 \
  < tasks.json
```

This executes:
- Phase 3: Context filtering (without context)
- Phase 4: Parallel execution

### 4. Resume from Saved State

Load phase state from a previous run:

```bash
python dispatch_runner.py \
  --load-phase-state validation_debug.json \
  --skip-phases 0,1 \
  < tasks.json
```

This resumes execution using previously gathered context and validation results.

### 5. Interactive Debugging with Phase Control

Combine interactive mode with phase control:

```bash
python dispatch_runner.py \
  --interactive \
  --enable-context \
  --enable-quorum \
  --stop-after-phase 1 \
  < tasks.json
```

This enables:
- Human-in-the-loop validation at each phase
- Ability to edit, retry, or skip phases
- Stop after validation for inspection

## Phase Results Output

Each phase execution produces a `PhaseResult` with:

```json
{
  "phase": "CONTEXT_GATHERING",
  "phase_name": "Context Gathering",
  "success": true,
  "duration_ms": 1523.4,
  "started_at": "2025-10-07T16:30:00.000Z",
  "completed_at": "2025-10-07T16:30:01.523Z",
  "output_data": {
    "context_summary": {...},
    "total_items": 42
  },
  "error": null,
  "skipped": false,
  "retry_count": 0
}
```

## Timing Summary

The final output includes a comprehensive timing summary:

```json
{
  "success": true,
  "timing_summary": {
    "total_duration_ms": 5234.7,
    "phases": [
      {
        "phase": "CONTEXT_GATHERING",
        "duration_ms": 1523.4,
        "success": true,
        "skipped": false
      },
      {
        "phase": "QUORUM_VALIDATION",
        "duration_ms": 2341.2,
        "success": true,
        "skipped": false
      },
      {
        "phase": "PARALLEL_EXECUTION",
        "duration_ms": 1370.1,
        "success": true,
        "skipped": false
      }
    ]
  }
}
```

## Quorum Retry Behavior

Phase 1 (Quorum Validation) now properly handles RETRY decisions:

### Previous Behavior
- RETRY decision logged but ignored
- Execution continued with potentially flawed breakdown

### New Behavior
- RETRY decision triggers automatic retry (up to 3 attempts)
- Deficiencies displayed for each retry
- Max retries exceeded: warning logged, execution continues
- FAIL decision: execution aborts immediately
- PASS decision: execution continues normally

Example retry flow:

```
[DispatchRunner] Phase 1: Quorum Validation
[DispatchRunner] Max retries: 3
[DispatchRunner] Validating task breakdown with AI quorum...
[DispatchRunner] Quorum decision: RETRY (confidence: 65.0%)
[DispatchRunner] Deficiencies found: 2
[DispatchRunner]   - Task dependencies may be incomplete
[DispatchRunner]   - Context requirements need clarification

[DispatchRunner] Retry attempt 1/3
[DispatchRunner] Validating task breakdown with AI quorum...
[DispatchRunner] Quorum decision: PASS (confidence: 85.0%)
[DispatchRunner] ✓ Phase 1 completed in 2341.2ms (confidence: 85.0%)
```

## Phase State Persistence

### Saved State Structure

```json
{
  "phases_executed": [
    {
      "phase": "CONTEXT_GATHERING",
      "phase_name": "Context Gathering",
      "success": true,
      "duration_ms": 1523.4,
      "output_data": {...}
    }
  ],
  "current_phase": 0,
  "global_context": {...},
  "quorum_result": {...},
  "tasks_data": [...],
  "user_prompt": "Original user request",
  "saved_at": "2025-10-07T16:30:01.523Z"
}
```

### Use Cases for State Persistence

1. **Debugging**: Inspect phase outputs without re-running expensive operations
2. **Testing**: Verify phase behavior in isolation
3. **Optimization**: Identify slow phases for optimization
4. **Resume**: Continue execution from a checkpoint
5. **Analysis**: Analyze phase timing and success rates

## Enhanced Logging

Each phase now includes comprehensive logging:

```
================================================================================
[DispatchRunner] Phase 0: Context Gathering
[DispatchRunner] Queries: 2
================================================================================

[DispatchRunner] Gathering global context...
[DispatchRunner] ✓ Context gathered: 42 items, ~5000 tokens
[DispatchRunner] Phase 0 completed in 1523ms

================================================================================
[DispatchRunner] Phase 1: Quorum Validation
[DispatchRunner] Max retries: 3
================================================================================

[DispatchRunner] Validating task breakdown with AI quorum...
[DispatchRunner] Quorum decision: PASS (confidence: 85.0%)
[DispatchRunner] ✓ Phase 1 completed in 2341ms (confidence: 85.0%)

================================================================================
[DispatchRunner] Phase 4: Parallel Execution
[DispatchRunner] Tasks: 2
================================================================================

[DispatchRunner] Executing 2 tasks in parallel...
[DispatchRunner] ✓ Phase 4 completed in 1370ms (2 succeeded, 0 failed)
```

## ONEX Compliance

The implementation follows ONEX architectural patterns:

### Naming Conventions
- ✅ Classes: `ExecutionPhase`, `PhaseConfig`, `PhaseResult`, `PhaseState`
- ✅ Functions: `execute_phase_0_context_gathering()`, `execute_phase_1_quorum_validation()`
- ✅ Clear naming indicating purpose and phase number

### Error Handling
- ✅ Structured error messages with phase context
- ✅ Graceful degradation (failed phase logs warning, continues if possible)
- ✅ Critical failures abort execution immediately
- ✅ Retry logic with exponential backoff (quorum validation)

### Performance Tracking
- ✅ Per-phase timing with millisecond precision
- ✅ Timestamp tracking (started_at, completed_at)
- ✅ Success/failure/skip status tracking
- ✅ Retry count tracking

### Structured Logging
- ✅ Consistent logging format with `[DispatchRunner]` prefix
- ✅ Visual separators for phase boundaries
- ✅ Success (✓), warning (⚠), and failure (✗) indicators
- ✅ Detailed output to stderr, JSON results to stdout

## Testing

Run the test suite to verify phase control functionality:

```bash
./test_phase_control.sh
```

This tests:
1. Backward compatibility (no phase control flags)
2. --only-phase 0 (context gathering only)
3. --stop-after-phase 1 (context + quorum)
4. --skip-phases 0,1 (skip context and quorum)
5. --save-phase-state (state persistence)
6. --help (documentation)

## Troubleshooting

### Phase 0 fails but execution continues
- Expected behavior: Phase 0 failure is non-critical
- Context filtering disabled automatically
- Tasks execute without pre-gathered context

### Phase 1 validation takes long time
- Quorum validation queries multiple AI models
- Retry logic adds 2-3 additional validation attempts
- Consider using `--skip-phases 1` for faster iteration

### --only-phase 4 fails with missing context
- Phase 4 depends on Phase 3 (task preparation)
- Use `--stop-after-phase 3` to prepare tasks
- Load state with `--load-phase-state` to resume

### Saved state file is very large
- Contains full context and quorum results
- Consider cleaning up old state files
- Use `jq` to inspect specific fields: `jq '.phases_executed' state.json`

## Best Practices

1. **Development**: Use `--skip-phases 0,1` for fast iteration
2. **Debugging**: Use `--only-phase N` to isolate issues
3. **Production**: Run all phases without restrictions
4. **Optimization**: Use `--save-phase-state` to identify slow phases
5. **Testing**: Use `--stop-after-phase 1` to validate without execution

## Future Enhancements

Planned improvements:
- [ ] Phase 2 extraction (currently merged with Phase 3)
- [ ] Phase dependency validation
- [ ] Phase retry logic for all phases
- [ ] Performance threshold validation per phase
- [ ] Phase execution DAG for complex workflows
- [ ] Phase-level circuit breaker patterns
