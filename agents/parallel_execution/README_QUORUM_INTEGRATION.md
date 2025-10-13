# Quorum Validation Integration

## Overview

This integration adds AI-powered validation to the parallel dispatch workflow, preventing agent failures caused by task breakdowns that don't match user intent.

## The Problem We Solved

**Real-world failure case**: User requested "Build a postgres adapter effect node" but the task breakdown generated:
- Wrong node type: Compute instead of Effect
- Wrong name: UserAuthentication instead of PostgreSQLAdapter
- Wrong domain: Authentication instead of database operations

**Result**: 5-10 minutes of wasted parallel execution generating incorrect code.

**Solution**: Quorum validation with 5 AI models validates the breakdown before execution, catching misalignments with 2-3 seconds of overhead.

## Architecture

### Enhanced 5-Phase Workflow

```
Phase 0: Global Context Gathering (optional --enable-context)
  └─> Gather workspace context and RAG intelligence

Phase 1: Intent Validation (optional --enable-quorum) ⭐ NEW
  └─> Validate task breakdown with AI quorum
      ├─> Query 5 models in parallel
      ├─> Decision: PASS/RETRY/FAIL
      └─> Abort if FAIL, warn if RETRY

Phase 2: Task Planning
  └─> Analyze dependencies and execution order

Phase 3: Context Filtering (optional --enable-context)
  └─> Filter global context per task

Phase 4: Parallel Execution
  └─> Execute tasks across specialized agents
```

### Quorum Consensus Model

**5 AI Models** (Total Weight: 7.5):
1. **Gemini Flash** (1.0) - Cloud baseline with broad knowledge
2. **Codestral** (1.5) - Code specialist on Mac Studio
3. **Mixtral 8x7B** (2.0) - Advanced reasoning model
4. **Llama 3.2** (1.2) - General-purpose validation
5. **Yi 34B** (1.8) - High-quality decision making

**Decision Thresholds**:
- **PASS**: ≥60% weighted consensus → Proceed with confidence
- **RETRY**: 40-60% consensus → Continue with warnings
- **FAIL**: <40% consensus → Abort execution

**Performance**: ~2-3 seconds for full consensus (parallel queries)

## Usage

### Prerequisites

```bash
# Set Gemini API key
export GEMINI_API_KEY='your-key-here'

# Verify Ollama models are running (if using local models)
curl http://192.168.86.200:11434/api/tags
```

### Basic Usage

```bash
# No validation (fast, for trusted tasks)
echo '{"tasks": [...]}' | python dispatch_runner.py

# With quorum validation (recommended)
echo '{"tasks": [...]}' | python dispatch_runner.py --enable-quorum

# Full stack (context + quorum)
python dispatch_runner.py --enable-context --enable-quorum < tasks.json
```

### Upstream Validation (Recommended)

For complex tasks, use `validated_task_architect.py` to validate AND retry automatically:

```bash
# Validates and retries up to 3 times with feedback
python validated_task_architect.py "Build a postgres adapter effect node"
```

This approach:
- Calls task_architect.py to generate breakdown
- Validates with quorum
- If RETRY: Augments prompt with deficiencies and regenerates
- If FAIL: Returns error immediately
- If PASS: Returns validated breakdown

### Input Format

```json
{
  "tasks": [
    {
      "task_id": "task1",
      "agent": "coder",
      "description": "Implement PostgreSQL adapter",
      "dependencies": [],
      "context_requirements": ["rag:postgres-patterns"]
    }
  ],
  "user_prompt": "Build a postgres adapter effect node",
  "workspace_path": "/path/to/workspace",
  "rag_queries": ["postgres adapters", "kafka integration"]
}
```

### Output Format (with validation)

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

## What Gets Validated

### 1. Intent Alignment
- Does the breakdown match the user's request?
- Example: "PostgreSQL adapter" → UserAuthentication ❌

### 2. Node Type Selection
- Is the correct ONEX node type chosen?
- Effect: External I/O, APIs, databases
- Compute: Pure transformations
- Reducer: Aggregation, state
- Orchestrator: Workflow coordination

### 3. Requirement Completeness
- Are all user requirements captured?
- Missing functionality?
- Incorrect domain mapping?
- Wrong component names?

## Files in This Integration

### Core Components

- **dispatch_runner.py** - Enhanced with Phase 1 validation checkpoint
- **quorum_minimal.py** - Core quorum validation logic (5 AI models)
- **validated_task_architect.py** - Upstream validation with retry logic

### Documentation

- **agent-parallel-dispatcher.md** - Complete workflow documentation
- **README_QUORUM_INTEGRATION.md** - This file
- **demo_quorum_integration.py** - Demonstration script

### Testing

- **test_quorum_integration.py** - Full integration test suite
  - Backward compatibility test
  - Quorum flag activation test
  - PostgreSQL adapter failure detection test
  - Valid breakdown pass test
  - Graceful degradation test

## Performance

### Overhead Budget

- **Quorum validation**: ~2-3 seconds
- **Context gathering**: ~1-2 seconds
- **Context filtering**: ~100ms per task
- **Total**: 3-5 seconds for validated, context-aware dispatch

### Optimization Tips

1. **Use `--enable-quorum` only** (skip context) for fastest validation
2. **Pre-gather context** in Phase 0, reuse across multiple dispatches
3. **Upstream validation** with `validated_task_architect.py` for automatic retry

## Error Handling

### Quorum Unavailable

If quorum_minimal.py is missing or models are unreachable:

```
[DispatchRunner] Warning: Quorum validation unavailable
```

Execution continues normally (graceful degradation).

### Validation Failure (FAIL Decision)

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

### Validation Retry (RETRY Decision)

```
[DispatchRunner] Warning: Quorum suggests retry, but continuing
[DispatchRunner] Deficiencies detected:
  - Node type may be incorrect
  - Consider adding Kafka integration
```

Execution continues with warnings logged.

## Testing

### Quick Integration Test

```bash
# Verify integration structure
python -c "
import sys
sys.path.insert(0, '.')
from quorum_minimal import MinimalQuorum, ValidationDecision
import dispatch_runner
print('✓ Integration verified!')
"
```

### Full Integration Test

```bash
# Requires GEMINI_API_KEY and Ollama models
python test_quorum_integration.py
```

### Demonstration

```bash
# No API key required - shows architecture and use cases
python demo_quorum_integration.py
```

## Integration with Workflow Coordinator

The workflow coordinator can leverage this for:

1. **Multi-agent task distribution**
   - Break complex workflows into parallel tasks
   - Validate each breakdown with quorum
   - Execute tasks across specialized agents

2. **Context inheritance**
   - Share global context across all dispatched tasks
   - Filter to relevant portions per agent

3. **Quality gates**
   - Quorum validation = Phase 1 quality gate
   - Context filtering = Phase 3 optimization gate
   - Parallel execution = Phase 4 efficiency gate

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

**Upstream** (Recommended): `validated_task_architect.py`
- Validates before dispatch
- Automatically retries with feedback
- Returns validated breakdown

**Downstream**: `dispatch_runner.py --enable-quorum`
- Validates after breakdown received
- Useful when breakdown comes from external source
- Cannot retry (would need external coordination)

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

## Future Enhancements

1. **Caching Layer**: Cache quorum results for similar prompts (15-minute TTL)
2. **Learning System**: Track validation accuracy over time, adjust model weights
3. **Streaming Validation**: Start execution before full consensus
4. **Multi-checkpoint Validation**: Validate at pre-execution, mid-execution, post-execution

## References

- [Agent Parallel Dispatcher Documentation](agent-parallel-dispatcher.md)
- [ONEX Architecture Patterns](/Volumes/PRO-G40/Code/Archon/docs/ONEX_ARCHITECTURE_PATTERNS_COMPLETE.md)
- [Quality Gates Specification](../quality-gates-spec.yaml)
- [Performance Thresholds](../performance-thresholds.yaml)

## Support

For issues or questions:
1. Check troubleshooting section above
2. Run `python demo_quorum_integration.py` to verify setup
3. Review `agent-parallel-dispatcher.md` for detailed workflow information
4. Run `python test_quorum_integration.py` to verify full integration
