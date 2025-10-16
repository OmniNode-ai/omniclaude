# AI-Enhanced Quality Enforcer Orchestrator

Main orchestrator for the AI-Enhanced Quality Enforcement System. Coordinates validation, RAG intelligence, AI consensus, and automatic code corrections.

## Overview

The Quality Enforcer implements a 5-phase pipeline:

1. **Phase 1: Fast Validation** (<100ms) - Local regex/AST-based naming violation detection
2. **Phase 2: RAG Intelligence** (<500ms) - Query Archon MCP for naming conventions
3. **Phase 3: Correction Generation** - Generate intelligent corrections from RAG context
4. **Phase 4: AI Quorum Scoring** (<1000ms) - Multi-model consensus validation
5. **Phase 5: Decision & Substitution** - Apply high-confidence corrections automatically

**Performance Budget**: <2 seconds total

## Installation

```bash
# Make orchestrator executable
chmod +x ~/.claude/hooks/quality_enforcer.py

# Verify installation
echo '{"tool_name":"Write","parameters":{"file_path":"/tmp/test.py","content":"def test(): pass"}}' | \
  python3 ~/.claude/hooks/quality_enforcer.py
```

## Configuration

### Environment Variables

Control which phases are enabled during rollout:

```bash
# Phase 1: Validation (enabled by default)
export ENABLE_PHASE_1_VALIDATION=true

# Phase 2: RAG Intelligence (disabled by default)
export ENABLE_PHASE_2_RAG=false

# Phase 3: Correction Generation (disabled by default)
export ENABLE_PHASE_3_CORRECTION=false

# Phase 4: AI Quorum (disabled by default)
export ENABLE_PHASE_4_AI_QUORUM=false

# Performance budget in seconds
export PERFORMANCE_BUDGET_SECONDS=2.0
```

### Phased Rollout

**Week 1: Phase 1 Only (Validation)**
```bash
export ENABLE_PHASE_1_VALIDATION=true
export ENABLE_PHASE_2_RAG=false
export ENABLE_PHASE_4_AI_QUORUM=false
```

**Week 1-2: Phase 1 + Phase 2 (RAG)**
```bash
export ENABLE_PHASE_1_VALIDATION=true
export ENABLE_PHASE_2_RAG=true
export ENABLE_PHASE_4_AI_QUORUM=false
```

**Week 2-3: Phase 1-3 (Single Model)**
```bash
export ENABLE_PHASE_1_VALIDATION=true
export ENABLE_PHASE_2_RAG=true
export ENABLE_PHASE_4_AI_QUORUM=true
# Configure single model in lib/consensus/quorum.py
```

**Week 4+: All Phases (Auto-Apply)**
```bash
export ENABLE_PHASE_1_VALIDATION=true
export ENABLE_PHASE_2_RAG=true
export ENABLE_PHASE_4_AI_QUORUM=true
# All models enabled, auto-apply threshold = 0.80
```

## Usage

### Command Line

```bash
# Test with sample input
echo '{"tool_name":"Write","parameters":{"file_path":"/tmp/test.py","content":"def calculateTotal(x): return x"}}' | \
  python3 ~/.claude/hooks/quality_enforcer.py

# Process a real tool call
cat tool_call.json | python3 ~/.claude/hooks/quality_enforcer.py > result.json
```

### As Claude Code Hook

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/quality_enforcer.py",
            "timeout": 3000
          }
        ]
      }
    ]
  }
}
```

## Input/Output Format

### Input (stdin)

JSON object with tool call information:

```json
{
  "tool_name": "Write",
  "parameters": {
    "file_path": "/path/to/file.py",
    "content": "def calculateTotal(items):\n    return sum(items)\n"
  }
}
```

Supported tool names:
- `Write` - Creates or overwrites files
- `Edit` - Edits existing files
- `MultiEdit` - Multiple edits in one operation

### Output (stdout)

Modified tool call with corrections applied:

```json
{
  "tool_name": "Write",
  "parameters": {
    "file_path": "/path/to/file.py",
    "content": "def calculate_total(items):\n    return sum(items)\n\n# AI Quality Enforcer: 1 naming correction(s) applied automatically"
  }
}
```

### Logging (stderr)

Performance statistics and decision logs:

```
[Phase 1] Running fast validation...
[Phase 1] Found 1 violations - 0.045s
[Phase 2] Querying RAG intelligence...
[Phase 2] Generated 1 corrections - 0.312s
[Phase 4] Running AI quorum...
[Phase 4] Scored 1 corrections - 0.856s
[Phase 5] Applying decisions...
  ✓ Auto-applied: calculateTotal → calculate_total (score: 0.90)
[Phase 5] Complete: 1 applied, 0 suggested, 0 skipped - 1.234s

============================================================
Quality Enforcer Statistics
============================================================
Total Time: 1.234s (budget: 2.0s)
Phase 1 (Validation): 0.045s
Phase 2 (RAG): 0.267s
Phase 3 (Correction): Included in Phase 2
Phase 4 (AI Quorum): 0.856s
Phase 5 (Decision): 0.066s
------------------------------------------------------------
Violations Found: 1
Corrections Applied: 1
Corrections Suggested: 0
Corrections Skipped: 0
============================================================
```

## Supported Languages

- Python (.py)
- TypeScript (.ts, .tsx)
- JavaScript (.js, .jsx)

## Decision Thresholds

The enforcer uses these thresholds for decision-making:

- **Score ≥ 0.80 + Confidence ≥ 0.70**: Auto-apply correction
- **Score ≥ 0.60**: Suggest to user (log only)
- **Score < 0.60**: Skip correction

## Error Handling

The orchestrator implements graceful degradation:

1. **Missing validators**: Returns original tool call unchanged
2. **RAG unavailable**: Uses simple fallback corrections
3. **AI Quorum fails**: Uses medium-confidence fallback scores
4. **Performance budget exceeded**: Skips remaining phases
5. **Any fatal error**: Always returns original tool call

Exit codes:
- `0`: Success (with or without corrections)
- `1`: Fatal error (original tool call passed through)

## Performance Characteristics

| Phase | Target | Typical | Fallback |
|-------|--------|---------|----------|
| Validation | <100ms | 30-50ms | Skip on syntax error |
| RAG Query | <500ms | 200-400ms | Use built-in rules |
| AI Quorum | <1000ms | 500-800ms | Reduce model count |
| **Total** | **<2000ms** | **800-1500ms** | Pass through on timeout |

## Troubleshooting

### No corrections applied

Check phase flags:
```bash
env | grep ENABLE_PHASE
```

Enable logging:
```bash
export ENABLE_PHASE_1_VALIDATION=true
cat tool_call.json | python3 quality_enforcer.py 2>&1 | tee output.log
```

### Performance too slow

Reduce enabled phases:
```bash
export ENABLE_PHASE_4_AI_QUORUM=false  # Disable expensive AI scoring
export PERFORMANCE_BUDGET_SECONDS=1.0   # Stricter budget
```

### Module import errors

Install missing dependencies:
```bash
# Check what's missing
python3 -c "from validators.naming_validator import NamingValidator"
python3 -c "from intelligence.rag_client import RAGIntelligenceClient"
python3 -c "from consensus.quorum import AIQuorum"

# Install required libraries per design document
```

## Development

### Adding New Language Support

Edit `_detect_language()` method:

```python
mapping = {
    '.py': 'python',
    '.ts': 'typescript',
    '.rs': 'rust',     # Add new language
}
```

### Custom Decision Thresholds

Modify thresholds in `_apply_decisions()`:

```python
if score.consensus_score >= 0.85 and score.confidence >= 0.75:
    # More conservative threshold
    modified_content = self._apply_correction(modified_content, correction)
```

### Performance Monitoring

Add custom timing:

```python
phase_start = time.time()
# ... your code ...
self.stats['custom_phase_time'] = time.time() - phase_start
```

## References

- **Design Document**: External Archon project - `${ARCHON_ROOT}/docs/agent-framework/ai-quality-enforcement-system.md`
- **Validator**: `~/.claude/hooks/lib/validators/naming_validator.py`
- **RAG Client**: `~/.claude/hooks/lib/intelligence/rag_client.py`
- **AI Quorum**: `~/.claude/hooks/lib/consensus/quorum.py`

## License

Part of the Archon Agent Framework. See main repository for license details.

---

**Version**: 1.0.0
**Last Updated**: 2025-09-29
**Status**: Phase 1 Ready (Validation Only)