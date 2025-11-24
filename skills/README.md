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

## Dependencies

System status monitoring skills require external command-line tools (Docker, kcat, psql) and Python packages.

**See [system-status/DEPENDENCIES.md](system-status/DEPENDENCIES.md) for**:
- Complete dependency list with installation instructions
- Platform-specific setup (macOS, Ubuntu, CentOS, Arch)
- Troubleshooting common installation issues
- Verification commands to test all dependencies

**Quick Verification**:
```bash
# Test all dependencies are installed
docker --version && kcat -V && psql --version
python3 -c "import psycopg2; print('✓ All dependencies OK')"
```

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

### System Status

Comprehensive system status checking skills for monitoring the entire OmniClaude agent infrastructure.

#### Tier 1: Quick Status Checks (< 5 seconds)

**check-system-health** - Fast overall system health snapshot
Location: `system-status/check-system-health/`
- Checks: Docker services, infrastructure, recent activity
- Output: Overall status (healthy/degraded/critical)
- Usage: Quick health verification before/after deployments

**check-service-status** - Detailed status for specific Docker services
Location: `system-status/check-service-status/`
- Checks: Container health, resource usage, logs, errors
- Output: Service-specific health details
- Usage: Debug specific service issues

**check-infrastructure** - Infrastructure component connectivity
Location: `system-status/check-infrastructure/`
- Checks: Kafka, PostgreSQL, Qdrant, Valkey connectivity
- Output: Component-specific health and stats
- Usage: Verify infrastructure accessibility

#### Tier 2: Performance & Activity Analysis (5-15 seconds)

**check-agent-performance** - Agent routing and execution metrics
Location: `system-status/check-agent-performance/`
- Checks: Routing times, confidence scores, agent frequency
- Output: Performance metrics and threshold violations
- Usage: Analyze routing performance and agent selection

**check-recent-activity** - Recent agent executions and system activity
Location: `system-status/check-recent-activity/`
- Checks: Manifest injections, routing decisions, agent actions
- Output: Activity summary with trends
- Usage: Monitor system activity and identify patterns

**check-pattern-discovery** - Qdrant pattern collections and stats
Location: `system-status/check-pattern-discovery/`
- Checks: Collection sizes, vector counts, retrieval performance
- Output: Pattern discovery metrics
- Usage: Monitor pattern availability and collection health

**check-database-health** - PostgreSQL database health and activity
Location: `system-status/check-database-health/`
- Checks: Table stats, connection pool, recent inserts
- Output: Database health and activity metrics
- Usage: Monitor database performance and capacity

**check-kafka-topics** - Kafka topic health and consumer status
Location: `system-status/check-kafka-topics/`
- Checks: Topics, partitions, consumer groups, throughput
- Output: Topic-specific health and activity
- Usage: Monitor Kafka infrastructure and message flow

#### Tier 3: Diagnostics & Reporting (15-60 seconds)

**diagnose-issues** - Identify and diagnose common problems
Location: `system-status/diagnose-issues/`
- Checks: Services, infrastructure, performance degradation
- Output: Issues list with severity and recommendations
- Usage: Troubleshoot problems and get actionable fixes

**generate-status-report** - Comprehensive system status report
Location: `system-status/generate-status-report/`
- Generates: Complete system report (JSON, Markdown, HTML)
- Output: Multi-section report with trends and analysis
- Usage: Daily reports, audits, stakeholder updates

### Usage Examples

**Quick health check before deployment**:
```bash
python3 ~/.claude/skills/system-status/check-system-health/execute.py
```

**Diagnose performance issues**:
```bash
python3 ~/.claude/skills/system-status/check-agent-performance/execute.py --timeframe 24h
python3 ~/.claude/skills/system-status/diagnose-issues/execute.py
```

**Generate weekly status report**:
```bash
python3 ~/.claude/skills/system-status/generate-status-report/execute.py \
  --format markdown \
  --output weekly-report.md \
  --timeframe 7d
```

## Shared Utilities

`_shared/db_helper.py` - Database connection utilities
- PostgreSQL connection pooling
- Query execution with error handling
- Correlation ID management
- JSON parameter parsing

`_shared/kafka_helper.py` - Kafka operations (NEW)
- Kafka connectivity checking
- Topic listing and stats
- Consumer group status
- Message throughput monitoring

`_shared/docker_helper.py` - Docker operations (NEW)
- Container status checking
- Health check status
- Resource usage monitoring (CPU, memory)
- Log retrieval and error detection

`_shared/qdrant_helper.py` - Qdrant operations (NEW)
- Qdrant connectivity checking
- Collection listing and stats
- Vector count monitoring
- Collection health checking

`_shared/status_formatter.py` - Output formatting (NEW)
- JSON formatting
- Text table generation
- Markdown report generation
- Status indicators (✓, ✗, ⚠)
- Duration/bytes formatting

`_shared/timeframe_helper.py` - Time range parsing
- Parse timeframe strings (1h, 24h, 7d, 30d)
- Convert to SQL WHERE clauses
- Validate timeframe formats

## Skill Documentation Standards

### Required: SKILL.md (Uppercase)

**All skills MUST use `SKILL.md` (uppercase) for documentation.**

✅ **CORRECT**:
- `skills/system-status/check-system-health/SKILL.md`
- `skills/linear/SKILL.md`
- `skills/pr-review/SKILL.md`

❌ **INCORRECT**:
- `skills/my-skill/skill.md` (lowercase - will be rejected)
- `skills/my-skill/prompt.md` (legacy format - deprecated)

**Why Uppercase?**
- Consistent with established skills (system-status, debug-loop, pr-review)
- Better visibility in file listings
- Matches Claude Code convention expectations
- Easier to spot in directory trees

**YAML Frontmatter Required**:
```yaml
---
name: skill-name
description: Brief description of what this skill does
---
```

**Migration from Legacy Formats**:
If you have old `prompt.md` or `skill.md` (lowercase) files:
```bash
# Rename to SKILL.md (preserves git history)
git mv skills/my-skill/prompt.md skills/my-skill/SKILL.md
git mv skills/my-skill/skill.md skills/my-skill/SKILL.md
```

---

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
