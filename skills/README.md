# OmniClaude Skills

Claude Code skills for agent observability, tracking, and system management.

## Skills Architecture

Our skills use a **hybrid approach**:
- **SKILL.md** - Instructions for Claude Code (YAML frontmatter + markdown)
- **execute.py** - Python CLI script for actual execution

This gives us:
- ✅ Claude-friendly documentation (SKILL.md)
- ✅ Reusable CLI scripts (can be called from hooks, agents, or manually)
- ✅ Type-safe execution with argument validation
- ✅ Consistent error handling and output formatting

## Skills Location

**Claude Code**: `~/.claude/skills/` (symlink)
**Repository**: `skills/`

The skills directory is **symlinked** from `~/.claude/skills/` to the repository, so:
- Claude Code can discover and use skills
- Skills are version-controlled in git
- Changes to repo automatically reflect in Claude Code

## How Skills Work

### 1. Claude reads SKILL.md

When an agent needs to log a routing decision:

```markdown
---
name: log-routing-decision
description: Log agent routing decisions to PostgreSQL
---

# Log Routing Decision

Use the Bash tool to execute:

```bash
python3 ~/.claude/skills/agent-tracking/log-routing-decision/execute.py \
  --agent "${SELECTED_AGENT}" \
  --confidence ${CONFIDENCE_SCORE} \
  ...
```
```

### 2. Claude executes via Bash tool

Claude substitutes variables and runs:

```bash
python3 ~/.claude/skills/agent-tracking/log-routing-decision/execute.py \
  --agent "agent-performance" \
  --confidence 0.92 \
  --strategy "enhanced_fuzzy_matching" \
  --latency-ms 45 \
  --user-request "optimize my code" \
  --reasoning "High confidence match" \
  --correlation-id "uuid-here"
```

### 3. Python script executes

The `execute.py` script:
- Validates arguments (argparse)
- Connects to database (via `_shared/db_helper.py`)
- Executes the operation
- Returns JSON result

## Available Skills

### Agent Tracking

**log-routing-decision** - Log agent routing decisions
Location: `agent-tracking/log-routing-decision/`

**log-transformation** - Log agent transformations
Location: `agent-tracking/log-transformation/`

**log-performance-metrics** - Log performance metrics
Location: `agent-tracking/log-performance-metrics/`

**log-agent-action** - Log individual agent actions (debug mode)
Location: `agent-tracking/log-agent-action/`

**log-detection-failure** - Log agent detection failures
Location: `agent-tracking/log-detection-failure/`

### Agent Observability

**check-health** - Quick agent system health check
Location: `agent-observability/check-health/`

**diagnose-errors** - Diagnose elevated error rates
Location: `agent-observability/diagnose-errors/`

**generate-report** - Comprehensive observability report
Location: `agent-observability/generate-report/`

**check-agent** - Deep dive into specific agent
Location: `agent-observability/check-agent/`

## Shared Utilities

`_shared/db_helper.py` - Database connection utilities
- PostgreSQL connection pooling
- Query execution with error handling
- Correlation ID management
- JSON parameter parsing

## Creating New Skills

### 1. Create directory structure

```bash
mkdir -p skills/my-skill-category/my-skill-name
```

### 2. Create SKILL.md

```yaml
---
name: my-skill-name
description: What this skill does and when to use it
---

# My Skill Name

## When to Use
- Situation 1
- Situation 2

## How to Use

```bash
python3 ~/.claude/skills/my-skill-category/my-skill-name/execute.py \
  --param1 "${VALUE1}" \
  --param2 "${VALUE2}"
```

## Example

```bash
python3 ~/.claude/skills/my-skill-category/my-skill-name/execute.py \
  --param1 "example-value" \
  --param2 "another-value"
```
```

### 3. Create execute.py

```python
#!/usr/bin/env python3
"""
My Skill Name - Brief description

Usage:
  python3 execute.py --param1 VALUE1 --param2 VALUE2
"""

import argparse
import sys
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import execute_query, get_correlation_id

def main():
    parser = argparse.ArgumentParser(description="My skill description")
    parser.add_argument("--param1", required=True, help="Description")
    parser.add_argument("--param2", required=True, help="Description")
    args = parser.parse_args()

    # Your logic here
    print(json.dumps({"success": True, "result": "..."}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### 4. Make executable

```bash
chmod +x skills/my-skill-category/my-skill-name/execute.py
```

### 5. Test

```bash
python3 skills/my-skill-category/my-skill-name/execute.py --param1 test --param2 test
```

## Testing Skills

### Unit Testing

```bash
cd skills/my-skill-category/my-skill-name
python3 execute.py --help  # Check usage
python3 execute.py --param1 "test" --param2 "test"  # Test execution
```

### Integration Testing

From Claude Code, activate the skill:
1. Ensure `~/.claude/skills/` symlink exists
2. Reference skill in agent instructions
3. Claude will discover and execute via SKILL.md

## Best Practices

### DO:
- ✅ Use CLI arguments, not hardcoded values
- ✅ Return JSON for structured output
- ✅ Handle errors gracefully (don't crash)
- ✅ Document all parameters in SKILL.md
- ✅ Provide example usage with actual values
- ✅ Use `_shared/db_helper.py` for database operations

### DON'T:
- ❌ Hardcode values in SKILL.md examples (use variables)
- ❌ Write SQL directly in SKILL.md (use execute.py)
- ❌ Forget to make execute.py executable
- ❌ Skip error handling
- ❌ Return unstructured output (use JSON)

## Troubleshooting

**Skill not found by Claude**:
- Check `~/.claude/skills/` symlink exists
- Verify SKILL.md has proper YAML frontmatter
- Ensure skill name matches directory name

**Execute script fails**:
- Check file is executable (`chmod +x`)
- Verify Python path in shebang (`#!/usr/bin/env python3`)
- Test script directly: `python3 execute.py --help`

**Database connection fails**:
- Check PostgreSQL is running (localhost:5436)
- Verify credentials in `_shared/db_helper.py`
- Test connection: `python3 _shared/db_helper.py`

## Migration Notes

**Old Format** (deprecated):
- Skills used `prompt.md` instead of `SKILL.md`
- Some skills had inline Python in instructions
- Inconsistent between direct execution vs CLI scripts

**New Format** (current):
- All skills have `SKILL.md` with YAML frontmatter
- All use CLI script approach (`execute.py`)
- Consistent structure across all skills

## Version Control

All skills are tracked in git at `skills/`.

When you modify a skill:
1. Edit in repository: `skills/`
2. Changes automatically available via symlink: `~/.claude/skills/`
3. Commit to git for version control
4. No need to manually sync - symlink handles it

## Performance

Skills execute in **<100ms** typically:
- Database connection: ~10-20ms (pooled)
- Query execution: ~10-50ms
- JSON serialization: ~1-5ms

For async/non-blocking logging, consider Kafka integration (see `log-agent-action` Kafka version).
