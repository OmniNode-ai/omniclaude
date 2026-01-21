# Agent Parallel Dispatcher

## Overview

The Parallel Dispatcher implements intelligent multi-agent coordination with AI-powered validation to ensure task breakdowns accurately match user intent before execution.

## Architecture

### 5-Phase Enhanced Workflow with Interactive Mode

```
┌─────────────────────────────────────────────────────────────────────┐
│                      PARALLEL DISPATCH WORKFLOW                     │
└─────────────────────────────────────────────────────────────────────┘

Phase 0: Global Context Gathering (Optional, --enable-context)
├─ Gather workspace context
├─ Execute RAG queries for implementation patterns
├─ Collect global intelligence (~5000 tokens max)
└─ Cache for reuse across all tasks

Phase 1: Intent Validation (Optional, --enable-quorum) ⭐ NEW
├─ Validate task breakdown against user prompt
├─ Consult 5 AI models for consensus (Gemini + 4 Ollama)
├─ Decision: PASS (≥60% confidence) | RETRY (40-60%) | FAIL (<40%)
├─ If FAIL: Abort execution with clear error
├─ If RETRY: Continue with warning + deficiency log
├─ If PASS: Proceed to execution (confidence logged)
└─ 🔍 INTERACTIVE CHECKPOINT: Review & approve breakdown (if --interactive)

Phase 2: Task Planning
├─ Tasks received from task_architect.py
├─ Dependencies analyzed
└─ Execution order determined

Phase 3: Context Filtering (Optional, --enable-context)
├─ Filter global context per task
├─ Match context_requirements to gathered intelligence
├─ Attach filtered context to each task
└─ Keep context lean (<5000 tokens per task)

Phase 4: Parallel Execution
├─ Dispatch tasks to specialized agents
├─ Monitor progress with traces
├─ Collect results with metadata
├─ Return aggregated output
└─ 🔍 INTERACTIVE CHECKPOINT: Review execution results (if --interactive)

Phase 5: Final Compilation
├─ Aggregate all results
├─ Format output JSON
└─ 🔍 INTERACTIVE CHECKPOINT: Review final output (if --interactive)
```

## Phase 1: Intent Validation Details

### What It Validates

The quorum validation system checks:

1. **Intent Alignment**: Does the task breakdown correctly understand the user's request?
   - Example: User asks for "PostgreSQL adapter" but breakdown generates "UserAuthentication" ❌

2. **Node Type Selection**: Is the correct ONEX node type chosen?
   - Effect: External I/O, APIs, databases
   - Compute: Pure transformations, algorithms
   - Reducer: Aggregation, state management
   - Orchestrator: Workflow coordination

3. **Requirement Completeness**: Are all user requirements captured?
   - Missing functionality
   - Incorrect domain mapping
   - Wrong component names

### Quorum Consensus Model

**5 AI Models** (Total Weight: 7.5):
- **Gemini Flash** (1.0): Cloud baseline with broad knowledge
- **Codestral** (1.5): Code specialist on Mac Studio
- **Mixtral 8x7B** (2.0): Advanced reasoning model
- **Llama 3.2** (1.2): General-purpose validation
- **Yi 34B** (1.8): High-quality decision making

**Decision Thresholds**:
- **PASS**: ≥60% weighted consensus → Proceed with confidence
- **RETRY**: 40-60% consensus → Continue with warnings
- **FAIL**: <40% consensus → Abort execution

**Performance**: ~2-3 seconds for full consensus (parallel queries)

### When Quorum Catches Issues

**Real-world Example**: PostgreSQL Adapter Failure

```
User Request: "Build a postgres adapter effect node"

Bad Breakdown:
{
  "node_type": "Compute",           ❌ Should be "Effect"
  "name": "UserAuthentication",     ❌ Should be "PostgreSQLAdapter"
  "description": "user auth ops"    ❌ Wrong domain entirely
}

Quorum Result:
- Decision: RETRY
- Confidence: 45%
- Deficiencies:
  1. "Wrong node type: Compute → Effect (database I/O)"
  2. "Name mismatch: UserAuthentication vs PostgreSQLAdapter"
  3. "Missing requirement: Kafka event bus integration"
```

### Integration with validated_task_architect.py

For upstream validation (before dispatch), use `validated_task_architect.py`:

```bash
# Validates AND retries automatically (up to 3 times)
python validated_task_architect.py "Build postgres adapter"
```

This wrapper:
1. Calls task_architect.py to generate breakdown
2. Validates with quorum
3. If RETRY: Augments prompt with deficiencies and regenerates
4. If FAIL: Returns error immediately
5. If PASS: Returns validated breakdown

## Interactive Mode (Human-in-the-Loop) 🔍

### Overview

Interactive mode adds human validation checkpoints at major workflow steps, allowing you to:
- **Approve** outputs and continue execution
- **Edit** outputs before continuing (opens in $EDITOR)
- **Retry** with custom feedback to improve results
- **Skip** validation and proceed anyway
- **Batch approve** all remaining steps
- **Quit** and save session state for later resumption

### When to Use Interactive Mode

✅ **Use interactive mode when:**
- Working on critical production code
- Task breakdown is complex or ambiguous
- You want to verify AI decisions before proceeding
- Learning how the system decomposes tasks
- Iterating on workflow improvements
- Need to inject domain expertise mid-workflow

❌ **Skip interactive mode when:**
- Running automated CI/CD pipelines
- Task breakdown is well-tested and reliable
- Time-sensitive operations
- Batch processing many similar tasks

### Interactive Checkpoints

#### Checkpoint 1: Task Breakdown Validation
**When**: After Phase 1 (quorum validation)
**Shows**:
- Task breakdown JSON
- Quorum decision (PASS/RETRY/FAIL)
- Deficiencies found by AI models
- Confidence scores

**Actions**:
- **Approve**: Accept breakdown, proceed to execution
- **Edit**: Modify breakdown in editor (e.g., fix node types, add missing requirements)
- **Retry**: Request re-generation with custom feedback
- **Skip**: Skip validation, proceed with current breakdown
- **Quit**: Save session and exit

**Example Output**:
```
┌────────────────────────────────────────────────────┐
│ Step 1/3: Task Breakdown Validation               │
└────────────────────────────────────────────────────┘

Quorum Decision: ✓ PASS (87% confidence)

Output Data:
{
  "tasks": [
    {
      "task_id": "task1",
      "agent": "coder",
      "description": "Implement PostgreSQL adapter Effect node",
      "node_type": "Effect"
    }
  ]
}

Options:
  [A]pprove  [E]dit  [R]etry  [S]kip  [B]atch approve  [Q]uit
Your choice: a
```

#### Checkpoint 2: Agent Execution Results
**When**: After Phase 4 (parallel execution)
**Shows**:
- Summary of successful/failed tasks
- Agent names and execution times
- Error messages for failures

**Actions**:
- **Approve**: Accept results, proceed to final compilation
- **Retry**: Re-execute failed tasks (future enhancement)
- **Skip**: Proceed despite failures
- **Quit**: Save session and exit

**Example Output**:
```
┌────────────────────────────────────────────────────┐
│ Step 2/3: Agent Execution Results (2 succeeded, 0 failed) │
└────────────────────────────────────────────────────┘

Output Data:
{
  "summary": {
    "total_tasks": 2,
    "successful": 2,
    "failed": 0
  },
  "results": {
    "task1": {
      "agent": "agent-contract-driven-generator",
      "success": true,
      "execution_time_ms": 2340
    },
    "task2": {
      "agent": "agent-debug-intelligence",
      "success": true,
      "execution_time_ms": 1890
    }
  }
}

Options:
  [A]pprove  [E]dit  [R]etry  [S]kip  [B]atch approve  [Q]uit
Your choice: a
```

#### Checkpoint 3: Final Result Compilation
**When**: Before final JSON output
**Shows**:
- Complete output JSON with all results
- Context summaries
- Quorum validation metadata

**Actions**:
- **Approve**: Output results and exit
- **Edit**: Modify final output in editor
- **Quit**: Save session and exit

### Session Management

#### Saving Sessions
When you quit at any checkpoint with `[Q]uit`, the session state is automatically saved to:
```
/tmp/interactive_session_<timestamp>.json
```

The session includes:
- All completed checkpoints
- User choices and feedback
- Modified outputs (if any)
- Remaining workflow steps

#### Resuming Sessions
To resume an interrupted workflow:

```bash
echo '{"tasks": [...]}' | \
  python dispatch_runner.py --interactive --resume-session /tmp/interactive_session_20250107_143022.json
```

The workflow will:
1. Skip already-completed checkpoints
2. Resume from the next pending checkpoint
3. Preserve all previous decisions and modifications

### Batch Approval Mode

If you trust the workflow after reviewing initial steps, enable batch approval:

**At any checkpoint**, select `[B]atch approve` to:
- Auto-approve all remaining checkpoints
- Continue execution without further prompts
- Still save session state for tracing

This is useful when:
- Initial breakdown looks good
- Quorum validation passed with high confidence
- You want to speed through remaining steps

### Editor Integration

#### Edit Mode Details

When you select `[E]dit`, the system:
1. Exports current output to temporary JSON file
2. Opens file in your configured editor (`$EDITOR` or default `nano`)
3. Waits for you to save and close editor
4. Validates modified JSON
5. Uses modified output for remaining workflow

**Supported Editors**:
- `nano` (default)
- `vim`
- `emacs`
- `code` (VS Code)
- Any editor in `$EDITOR` environment variable

**Set your preferred editor**:
```bash
export EDITOR=vim
# or
export EDITOR="code --wait"
```

#### Common Edit Scenarios

**Fix Node Type**:
```json
{
  "node_type": "Compute",  // Change to "Effect"
  ...
}
```

**Add Missing Requirement**:
```json
{
  "tasks": [...],
  "additional_requirements": [
    "Must support PostgreSQL connection pooling"
  ]
}
```

**Adjust Agent Assignment**:
```json
{
  "task_id": "task2",
  "agent": "coder",  // Change to "debug"
  ...
}
```

### Retry Mode with Feedback

#### How Retry Works

When you select `[R]etry`:
1. System prompts for feedback (multi-line input)
2. Press Enter twice to finish feedback
3. Feedback is attached to retry request
4. Upstream system receives retry signal with your notes

**Example Retry Feedback**:
```
Enter feedback for retry:
(Press Enter twice to finish)

> This should be an Effect node, not Compute
> The domain is database operations, not authentication
> Missing: Kafka event bus integration
> Missing: PostgreSQL connection pooling
>
✓ Feedback captured (142 characters)
```

#### Retry Behavior

**At Task Breakdown Checkpoint**:
- Returns `RETRY` decision to upstream (e.g., `validated_task_architect.py`)
- Upstream re-generates breakdown with your feedback
- New breakdown goes through validation again

**At Execution Results Checkpoint**:
- Currently logs retry request
- Future enhancement: Re-execute failed tasks with feedback

**At Final Compilation Checkpoint**:
- Not applicable (no upstream to retry)
- Use `[E]dit` instead to modify output directly

### Command-Line Flags

| Flag | Description | Example |
|------|-------------|---------|
| `--interactive` or `-i` | Enable interactive mode | `--interactive` |
| `--enable-quorum` | Enable AI quorum validation | `--enable-quorum` |
| `--enable-context` | Enable context gathering | `--enable-context` |
| `--resume-session <file>` | Resume from saved session | `--resume-session /tmp/session.json` |

**Flag Combinations**:
```bash
# Interactive + quorum (recommended)
python dispatch_runner.py --interactive --enable-quorum < tasks.json

# Interactive + context + quorum (full validation)
python dispatch_runner.py --interactive --enable-context --enable-quorum < tasks.json

# Resume previous session
python dispatch_runner.py --interactive --resume-session /tmp/session.json < tasks.json
```

## Usage

### Basic Dispatch (No Validation)

```bash
echo '{
  "tasks": [
    {
      "task_id": "task1",
      "agent": "coder",
      "description": "Implement PostgreSQL adapter",
      "dependencies": []
    }
  ],
  "user_prompt": "Build postgres adapter effect node"
}' | python dispatch_runner.py
```

### With Quorum Validation

```bash
echo '{
  "tasks": [...],
  "user_prompt": "Build postgres adapter effect node"
}' | python dispatch_runner.py --enable-quorum
```

### With Interactive Mode

```bash
echo '{
  "tasks": [
    {
      "task_id": "task1",
      "agent": "coder",
      "description": "Implement PostgreSQL adapter Effect node",
      "dependencies": []
    }
  ],
  "user_prompt": "Build postgres adapter effect node"
}' | python dispatch_runner.py --interactive --enable-quorum
```

**Expected workflow**:
1. Quorum validates task breakdown
2. Checkpoint 1: Review breakdown, approve/edit/retry/skip
3. Tasks execute in parallel
4. Checkpoint 2: Review execution results
5. Final output compiled
6. Checkpoint 3: Review final output before printing

**Sample interaction**:
```
[DispatchRunner] Interactive mode enabled
[DispatchRunner] Quorum validation enabled
[DispatchRunner] Phase 1: Validating task breakdown with AI quorum...
[DispatchRunner] Quorum decision: PASS (confidence: 87.0%)

┌────────────────────────────────────────────────────┐
│ Step 1/3: Task Breakdown Validation               │
└────────────────────────────────────────────────────┘

Quorum Decision: ✓ PASS (87% confidence)

Output Data:
{
  "tasks": [
    {
      "task_id": "task1",
      "agent": "coder",
      "description": "Implement PostgreSQL adapter Effect node",
      "node_type": "Effect"
    }
  ]
}

Options:
  [A]pprove  [E]dit  [R]etry  [S]kip  [B]atch approve  [Q]uit
Your choice: a

[DispatchRunner] Phase 4: Executing 1 tasks in parallel...
[Agent execution proceeds...]

┌────────────────────────────────────────────────────┐
│ Step 2/3: Agent Execution Results (1 succeeded, 0 failed) │
└────────────────────────────────────────────────────┘

Output Data:
{
  "summary": {
    "total_tasks": 1,
    "successful": 1,
    "failed": 0
  },
  ...
}

Options:
  [A]pprove  [E]dit  [R]etry  [S]kip  [B]atch approve  [Q]uit
Your choice: a

[Final output compilation and checkpoint...]
```

Output includes validation metadata:

```json
{
  "success": true,
  "quorum_validation_enabled": true,
  "quorum_validation": {
    "validated": true,
    "decision": "PASS",
    "confidence": 0.82,
    "deficiencies": [],
    "scores": {
      "alignment": 87.4,
      "pass_pct": 0.82,
      "retry_pct": 0.18,
      "fail_pct": 0.0
    },
    "model_count": 5
  },
  "results": [...]
}
```

### With Context Filtering + Quorum

```bash
echo '{
  "tasks": [...],
  "user_prompt": "Build postgres adapter",
  "rag_queries": ["postgres adapters", "kafka event bus"]
}' | python dispatch_runner.py --enable-context --enable-quorum
```

This combines:
- Phase 0: Gather implementation patterns from RAG
- Phase 1: Validate breakdown with quorum
- Phase 3: Filter relevant context per task
- Phase 4: Execute with filtered intelligence

## Command-Line Flags

| Flag | Description | Default | Performance Impact |
|------|-------------|---------|-------------------|
| `--enable-context` | Enable context gathering & filtering | Off | +1-2s overhead |
| `--enable-quorum` | Enable AI quorum validation | Off | +2-3s overhead |
| (none) | Basic parallel dispatch | Default | ~0ms overhead |

**Recommended Combinations**:
- **Production**: Both flags for maximum reliability
- **Development**: `--enable-quorum` only for fast validation
- **Testing**: No flags for speed

## Error Handling

### Quorum Unavailable

If `quorum_minimal.py` is missing or models are unreachable:

```
[DispatchRunner] Warning: Quorum validation unavailable
```

Execution continues normally (graceful degradation).

### Validation Failure

If quorum returns FAIL decision:

```json
{
  "success": false,
  "error": "Task breakdown validation failed critically",
  "quorum_result": {
    "decision": "FAIL",
    "confidence": 0.35,
    "deficiencies": [
      "Wrong node type selected",
      "Missing critical requirements"
    ]
  }
}
```

Execution is aborted to prevent wasted parallel execution.

### Validation Retry

If quorum returns RETRY decision:

```
[DispatchRunner] Warning: Quorum suggests retry, but continuing
[DispatchRunner] Deficiencies detected:
  - Node type may be incorrect
  - Consider adding Kafka integration
```

Execution continues with warnings logged.

## Best Practices

### When to Enable Quorum

✅ **Use quorum validation when:**
- User request is complex or ambiguous
- High stakes (production code, critical features)
- Past failures suggest intent misalignment
- Task breakdown comes from untested/new architect agents

❌ **Skip quorum validation when:**
- Simple, well-understood tasks
- Time-sensitive operations
- Task breakdown is pre-validated
- Testing infrastructure only

### Upstream vs Downstream Validation

**Upstream** (Recommended): Use `validated_task_architect.py`
- Validates before dispatch
- Automatically retries with feedback
- Returns validated breakdown

**Downstream**: Use `dispatch_runner.py --enable-quorum`
- Validates after breakdown received
- Useful when breakdown comes from external source
- Cannot retry (would need external coordination)

### Performance Optimization

**Parallel Quorum Queries**: All 5 models queried simultaneously
- Gemini: ~800ms average
- Ollama models: ~1.5s average (local GPU)
- Total: ~2-3s (not 5x sequential)

**Overhead Budget**:
- Quorum validation: ~2-3s
- Context gathering: ~1-2s
- Context filtering: ~100ms per task
- **Total**: 3-5s for validated, context-aware dispatch

**Optimization Tips**:
- Use `--enable-quorum` only, skip context for faster validation
- Pre-gather context in Phase 0, reuse across multiple dispatches
- Cache quorum results for similar prompts (future enhancement)

## Integration with Workflow Coordinator

The workflow coordinator can leverage parallel dispatch for:

1. **Multi-agent task distribution**
   - Break complex workflows into parallel tasks
   - Validate each breakdown with quorum
   - Execute tasks across specialized agents

2. **Context inheritance**
   - Share global context across all dispatched tasks
   - Filter to relevant portions per agent
   - Maintain consistency throughout workflow

3. **Quality gates**
   - Quorum validation = Phase 1 quality gate
   - Context filtering = Phase 3 optimization gate
   - Parallel execution = Phase 4 efficiency gate

## Troubleshooting

### Models Not Responding

Check Ollama server:
```bash
curl http://192.168.86.200:11434/api/generate -d '{
  "model": "codestral:22b-v0.1-q4_K_M",
  "prompt": "test",
  "stream": false
}'
```

Check Gemini API key:
```bash
echo $GEMINI_API_KEY
```

### Low Confidence Scores

If quorum consistently returns low confidence:
- Review task_architect.py prompt engineering
- Check if user prompts are too ambiguous
- Verify ONEX node type mappings are correct
- Consider adjusting consensus thresholds

### False Positives

If quorum incorrectly rejects valid breakdowns:
- Adjust weighted model contributions
- Increase PASS threshold from 60% to 70%
- Review model prompt instructions
- Check for systematic biases in specific models

## Future Enhancements

### Planned Features

1. **Caching Layer**: Cache quorum results for similar prompts
   - 15-minute TTL
   - Hash-based lookup (user_prompt + task_breakdown)
   - Target: 60% cache hit rate

2. **Learning System**: Track validation accuracy over time
   - Record quorum decisions vs actual outcomes
   - Adjust model weights based on accuracy
   - Identify patterns in successful validations

3. **Streaming Validation**: Start execution before full consensus
   - Execute high-confidence tasks immediately
   - Hold low-confidence tasks for full validation
   - Balance speed vs safety

4. **Multi-checkpoint Validation**: Validate at multiple stages
   - Pre-execution (current)
   - Mid-execution (after first agent completes)
   - Post-execution (validate outputs)

## API Reference

### validate_with_quorum()

```python
async def validate_with_quorum(
    user_prompt: str,
    task_breakdown: Dict[str, Any],
    max_retries: int = 3
) -> Dict[str, Any]:
    """Validate task breakdown against user intent

    Args:
        user_prompt: Original user request
        task_breakdown: Generated task breakdown to validate
        max_retries: Maximum validation retries (default: 3)

    Returns:
        Dict with validation results:
        {
            "validated": bool,        # True if PASS
            "decision": str,          # PASS/RETRY/FAIL
            "confidence": float,      # 0.0-1.0
            "deficiencies": List[str],# Issues found
            "scores": Dict,           # Detailed scores
            "model_count": int        # Models that responded
        }
    """
```

### Input Schema

```json
{
  "tasks": [
    {
      "task_id": "string",
      "agent": "coder|debug",
      "description": "string",
      "dependencies": ["task_id1", "task_id2"],
      "context_requirements": ["rag:query", "workspace:path"],
      "input_data": {}
    }
  ],
  "user_prompt": "string",
  "workspace_path": "optional/path",
  "rag_queries": ["optional", "queries"]
}
```

### Output Schema

```json
{
  "success": true,
  "quorum_validation_enabled": true,
  "context_filtering_enabled": true,
  "quorum_validation": {
    "validated": true,
    "decision": "PASS",
    "confidence": 0.82,
    "deficiencies": [],
    "scores": {
      "alignment": 87.4,
      "pass_pct": 0.82,
      "retry_pct": 0.18,
      "fail_pct": 0.0
    },
    "model_count": 5
  },
  "context_summary": {
    "total_items": 12,
    "total_tokens_estimate": 3420
  },
  "results": [
    {
      "task_id": "task1",
      "agent_name": "agent-contract-driven-generator",
      "success": true,
      "output_data": {},
      "execution_time_ms": 2340,
      "trace_id": "uuid"
    }
  ]
}
```

## Related Components

- **quorum_minimal.py**: Core quorum validation logic
- **validated_task_architect.py**: Upstream validation with retry
- **context_manager.py**: Context gathering and filtering
- **agent_dispatcher.py**: Parallel task coordination
- **task_architect.py**: Task breakdown generation

## References

- [ONEX Architecture Patterns](External Archon project - ${ARCHON_ROOT}/docs/ONEX_ARCHITECTURE_PATTERNS_COMPLETE.md)
- [Agent Framework Documentation](../ARCHITECTURE.md)
- [Quality Gates Specification](../quality-gates-spec.yaml)
- [Performance Thresholds](../performance-thresholds.yaml)
