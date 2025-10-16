# Interactive Mode Implementation

## Overview

This implementation adds human-in-the-loop validation to the parallel dispatch runner, enabling interactive checkpoints at major workflow steps where users can review, edit, retry, or skip any step.

## Quick Start

### Basic Usage

```bash
# Enable interactive mode with quorum validation
echo '{"tasks": [...], "user_prompt": "Build postgres adapter"}' | \
  python dispatch_runner.py --interactive --enable-quorum
```

### With Context Filtering

```bash
# Full validation: interactive + quorum + context
echo '{"tasks": [...], "user_prompt": "Build postgres adapter"}' | \
  python dispatch_runner.py --interactive --enable-quorum --enable-context
```

### Resume Interrupted Session

```bash
# Resume from saved session
echo '{"tasks": [...]}' | \
  python dispatch_runner.py --interactive --resume-session /tmp/session.json
```

## Implementation Components

### 1. interactive_validator.py

**Purpose**: Core interactive validation system

**Key Classes**:
- `InteractiveValidator`: Main interactive checkpoint system
- `QuietValidator`: Non-interactive fallback (auto-approves all)
- `SessionState`: Session state management for save/resume
- `CheckpointResult`: Result of user interaction at checkpoint
- `Colors`: ANSI color codes for terminal output

**Key Features**:
- Colored terminal UI with progress indicators
- Editor integration for output modification
- Multi-line feedback input for retries
- Session state persistence (save/resume)
- Batch approval mode
- Graceful handling of invalid input

**User Options at Each Checkpoint**:
- **[A]pprove**: Accept output and continue
- **[E]dit**: Open output in editor (uses $EDITOR or nano)
- **[R]etry**: Request retry with custom feedback
- **[S]kip**: Skip validation and proceed
- **[B]atch approve**: Auto-approve all remaining steps
- **[Q]uit**: Save session state and exit

### 2. dispatch_runner.py (Enhanced)

**Purpose**: Integrate interactive checkpoints into workflow

**Key Changes**:
- Added `--interactive` / `-i` flag
- Added `--resume-session <file>` flag
- Created validator instance (Interactive or Quiet)
- Added checkpoint after quorum validation (Phase 1)
- Added checkpoint after agent execution (Phase 4)
- Added checkpoint before final output (Phase 5)
- Updated `validate_with_quorum()` to accept validator
- Handle user choices (approve/edit/retry/skip/quit)

**Checkpoint Locations**:
1. **Task Breakdown Validation** (after quorum)
   - Shows: Task breakdown, quorum result, deficiencies
   - Edit: Modify breakdown before execution
   - Retry: Request re-generation with feedback

2. **Agent Execution Results** (after parallel execution)
   - Shows: Success/failure summary, execution times
   - Edit: Modify result metadata
   - Retry: Re-execute failed tasks (future)

3. **Final Result Compilation** (before output)
   - Shows: Complete output JSON
   - Edit: Modify final output
   - Approve: Print and exit

### 3. agent-parallel-dispatcher.md (Documentation)

**Purpose**: Comprehensive documentation for interactive mode

**Key Sections**:
- Architecture overview with interactive checkpoints
- When to use interactive mode
- Detailed explanation of each checkpoint
- Session management (save/resume)
- Batch approval mode
- Editor integration
- Retry mode with feedback
- Command-line flags
- Usage examples
- Troubleshooting

### 4. test_interactive_mode.py

**Purpose**: Comprehensive test suite

**Test Coverage**:
- SessionState serialization/deserialization
- QuietValidator auto-approval
- InteractiveValidator checkpoints
- User choice handling (approve/edit/retry/skip/batch/quit)
- Session state persistence
- Editor integration (mocked)
- Invalid input handling
- Color disabling for non-TTY
- Command-line flag parsing

**Run Tests**:
```bash
cd ${PROJECT_ROOT}/agents/parallel_execution
python test_interactive_mode.py
# or
pytest test_interactive_mode.py -v
```

### 5. example_interactive_workflow.sh

**Purpose**: Interactive demonstration of all features

**Examples Included**:
1. Basic interactive mode with quorum
2. Interactive + context filtering
3. Edit mode demonstration
4. Retry with feedback
5. Session save and resume
6. Batch approve mode
7. Editor configuration
8. Complete session output

**Run Examples**:
```bash
cd ${PROJECT_ROOT}/agents/parallel_execution
./example_interactive_workflow.sh
```

## Architecture

### Checkpoint Flow

```
┌─────────────────────────────────────────────────────────┐
│                  INTERACTIVE CHECKPOINT                  │
└─────────────────────────────────────────────────────────┘

1. Display Checkpoint Header
   ├─ Step number and total steps
   ├─ Step name
   └─ Progress indicator

2. Display Context Information
   ├─ Quorum result (if available)
   ├─ Deficiencies (if any)
   └─ Output data (formatted JSON)

3. Prompt User for Choice
   ├─ [A]pprove: Continue with current output
   ├─ [E]dit: Open in editor, validate, continue
   ├─ [R]etry: Collect feedback, trigger retry
   ├─ [S]kip: Skip validation, continue
   ├─ [B]atch approve: Auto-approve remaining
   └─ [Q]uit: Save session, exit

4. Handle User Choice
   ├─ Save checkpoint result to session
   ├─ Update session state
   └─ Return result to caller

5. Caller Processes Result
   ├─ Approve/Skip: Continue workflow
   ├─ Edit: Use modified output
   ├─ Retry: Trigger retry with feedback
   └─ Quit: Exit (session saved)
```

### Session State Management

```
┌─────────────────────────────────────────────────────────┐
│                    SESSION STATE                         │
└─────────────────────────────────────────────────────────┘

SessionState {
  session_id: "20250107_143022"
  workflow_name: "postgres_adapter_workflow"
  checkpoints_completed: ["quorum_validation", "execution_results"]
  checkpoints_pending: ["final_compilation"]
  checkpoint_results: {
    "quorum_validation": {
      choice: APPROVE,
      timestamp: "2025-01-07T14:30:22"
    },
    "execution_results": {
      choice: EDIT,
      modified_output: {...},
      timestamp: "2025-01-07T14:31:45"
    }
  },
  batch_approve_remaining: false
}

Saved to: /tmp/interactive_session_20250107_143022.json

Resume:
  python dispatch_runner.py --interactive \
    --resume-session /tmp/interactive_session_20250107_143022.json
```

## Integration Points

### With Quorum Validation

Interactive mode enhances quorum validation by allowing human review:

```python
# In dispatch_runner.py
quorum_result = await validate_with_quorum(
    user_prompt,
    task_breakdown,
    validator=validator  # Interactive or Quiet
)

# validate_with_quorum presents checkpoint if validator provided
# User can:
#   - Approve quorum decision
#   - Edit breakdown if quorum suggests changes
#   - Retry with feedback to improve breakdown
#   - Skip validation despite quorum concerns
```

### With Context Filtering

Interactive mode works seamlessly with context filtering:

```python
# Phase 0: Gather context (automatic)
global_context = await context_manager.gather_global_context(...)

# Phase 1: Validate with quorum + interactive checkpoint
quorum_result = await validate_with_quorum(..., validator=validator)

# Phase 3: Filter context per task (automatic)
filtered_context = context_manager.filter_context(...)

# Phase 4: Execute + interactive checkpoint
results = await coordinator.execute_parallel(tasks)
checkpoint_result = validator.checkpoint(...)  # Review results

# Phase 5: Compile + interactive checkpoint
output = compile_output(results)
checkpoint_result = validator.checkpoint(...)  # Review final output
```

### With Task Architect

For upstream integration with `validated_task_architect.py`:

```python
# In validated_task_architect.py (future enhancement)
for retry_count in range(max_retries):
    # Generate breakdown
    breakdown = await task_architect.generate_breakdown(prompt)

    # Validate with interactive quorum
    quorum_result = await validate_with_quorum(
        prompt,
        breakdown,
        validator=validator
    )

    if quorum_result.get("user_feedback"):
        # User provided retry feedback
        prompt = augment_prompt_with_feedback(
            prompt,
            quorum_result["user_feedback"]
        )
        continue  # Retry with feedback

    if quorum_result.get("user_edited"):
        # User edited breakdown directly
        breakdown = quorum_result["modified_breakdown"]
        break  # Use edited version

    if quorum_result.get("validated"):
        break  # Approved or skipped

# Continue with validated/edited breakdown
```

## Performance Impact

### Overhead

| Mode | Overhead | Notes |
|------|----------|-------|
| No flags | 0ms | Standard execution |
| `--interactive` only | 0ms + user time | Minimal overhead, waits for user |
| `--interactive --enable-quorum` | 2-3s + user time | Quorum validation + user review |
| Batch approve | ~100ms/checkpoint | Auto-approve, minimal overhead |

### User Interaction Time

Depends entirely on user review speed:
- Quick approval: 1-2 seconds per checkpoint
- Edit mode: 30-120 seconds (editor time)
- Retry with feedback: 30-60 seconds (feedback input)
- Batch approve: Instant after first checkpoint

### Session State I/O

- Save: ~10ms (JSON write to /tmp)
- Load: ~10ms (JSON read from /tmp)
- File size: ~1-5KB per session

## Best Practices

### When to Use Interactive Mode

✅ **Use interactive mode when:**
- Working on critical production code
- Task breakdown is complex or ambiguous
- You want to verify AI decisions before proceeding
- Learning how the system decomposes tasks
- Iterating on workflow improvements
- Need to inject domain expertise mid-workflow
- Debugging workflow issues

❌ **Skip interactive mode when:**
- Running automated CI/CD pipelines
- Task breakdown is well-tested and reliable
- Time-sensitive operations
- Batch processing many similar tasks
- Running tests or non-critical experiments

### Workflow Patterns

#### Pattern 1: Trust but Verify
```bash
# Review initial breakdown, batch approve rest
python dispatch_runner.py --interactive --enable-quorum < tasks.json
# At Checkpoint 1: Review breakdown
# If good: [B]atch approve
# Remaining checkpoints auto-approve
```

#### Pattern 2: Full Human Oversight
```bash
# Review every step carefully
python dispatch_runner.py --interactive --enable-quorum < tasks.json
# At each checkpoint: Carefully review
# Edit or retry as needed
# Approve only when satisfied
```

#### Pattern 3: Edit and Continue
```bash
# Interactive edit mode for quick fixes
python dispatch_runner.py --interactive --enable-quorum < tasks.json
# At Checkpoint 1: [E]dit breakdown
# Fix node type or add requirements
# Save and continue
# Batch approve remaining steps
```

#### Pattern 4: Iterative Refinement
```bash
# Retry with feedback until perfect
python dispatch_runner.py --interactive --enable-quorum < tasks.json
# At Checkpoint 1: Review breakdown
# If not perfect: [R]etry with feedback
# System regenerates with your guidance
# Review new breakdown
# Approve when satisfied
```

#### Pattern 5: Interrupt and Resume
```bash
# Start workflow
python dispatch_runner.py --interactive --enable-quorum < tasks.json
# At Checkpoint 1: Review breakdown
# [Q]uit to think about it
# Session saved to /tmp/session_XXXXXX.json

# Later, resume
python dispatch_runner.py --interactive \
  --resume-session /tmp/session_XXXXXX.json < tasks.json
# Continues from next checkpoint
```

## Troubleshooting

### Interactive Mode Not Working

**Problem**: `--interactive` flag doesn't show checkpoints

**Solutions**:
1. Check that `interactive_validator.py` exists
2. Verify import succeeded (no warning in stderr)
3. Ensure running on TTY (not redirected output)
4. Check for Python import errors

### Editor Not Opening

**Problem**: Edit mode fails or opens wrong editor

**Solutions**:
1. Set `EDITOR` environment variable: `export EDITOR=vim`
2. Use full path for VS Code: `export EDITOR="/usr/local/bin/code --wait"`
3. Ensure editor is installed and in PATH
4. Check editor requires `--wait` flag (VS Code, Sublime)

### Session File Not Found

**Problem**: Resume fails with "file not found"

**Solutions**:
1. Check session file path is correct
2. Verify file wasn't deleted (check /tmp)
3. Use absolute path: `--resume-session /tmp/session.json`
4. Session files are temporary (may be cleaned up)

### Colors Not Displaying

**Problem**: ANSI codes shown instead of colors

**Solutions**:
1. Colors auto-disabled for non-TTY
2. Check terminal supports ANSI colors
3. Colors are disabled in pipes/redirects (expected)

### Retry Not Working

**Problem**: Retry feedback doesn't regenerate breakdown

**Solutions**:
1. Retry only works at Task Breakdown checkpoint
2. For agent execution, retry not yet implemented
3. Check caller (e.g., validated_task_architect.py) handles retry
4. Use [E]dit mode as workaround for direct changes

## Future Enhancements

### Planned Features

1. **Per-Agent Checkpoints**
   - Checkpoint after each individual agent execution
   - Review agent output before continuing
   - Edit agent output if needed

2. **Retry Implementation for Agent Execution**
   - Re-execute failed agents with feedback
   - Modify agent parameters and retry
   - Parallel retry of multiple failed agents

3. **Timeout with Auto-Approval**
   - Set timeout: `--auto-approve-timeout 30`
   - Auto-approve after N seconds if no input
   - Useful for semi-automated workflows

4. **Checkpoint Filtering**
   - Skip specific checkpoints: `--skip-checkpoint execution_results`
   - Only show critical checkpoints
   - Configurable checkpoint granularity

5. **History and Replay**
   - Save all checkpoint decisions to history
   - Replay session with same decisions
   - Learn from past interactions

6. **Web UI**
   - Browser-based interactive mode
   - Rich formatting of outputs
   - Side-by-side diffs for edits
   - Real-time collaboration

## Related Documentation

- **agent-parallel-dispatcher.md**: Complete parallel dispatcher documentation
- **quorum_minimal.py**: AI quorum validation implementation
- **context_manager.py**: Context gathering and filtering
- **ONEX_ARCHITECTURE_PATTERNS_COMPLETE.md**: ONEX architecture patterns

## Support

For issues or questions:
1. Check documentation: `agent-parallel-dispatcher.md`
2. Run examples: `./example_interactive_workflow.sh`
3. Run tests: `python test_interactive_mode.py`
4. Review session file: Check /tmp/interactive_session_*.json

## License

Part of the OmniClaude Agent Framework.
