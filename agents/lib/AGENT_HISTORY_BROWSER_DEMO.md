# Agent History Browser - Demo & Examples

## Overview

The Agent History Browser is an interactive CLI tool for exploring agent execution history with complete manifest injection traceability. It provides a user-friendly interface to browse, search, and analyze what each agent received at execution time.

## Installation

No additional installation required! The tool is included in the `agents/lib/` directory.

**Dependencies**:
- `psycopg2` (required) - `pip install psycopg2-binary`
- `rich` (optional) - `pip install rich` - for enhanced UI with colors and tables

## Quick Start

```bash
# Launch interactive browser
cd /Volumes/PRO-G40/Code/omniclaude
python3 agents/lib/agent_history_browser.py

# Filter by specific agent
python3 agents/lib/agent_history_browser.py --agent test-agent

# Show specific execution details
python3 agents/lib/agent_history_browser.py --correlation-id a2f33abd-34c2-4d63-bfe7-2cb14ded13fd

# Export manifest JSON
python3 agents/lib/agent_history_browser.py --correlation-id <id> --export manifest.json

# Show last 100 runs
python3 agents/lib/agent_history_browser.py --limit 100

# Show runs from last 24 hours
python3 agents/lib/agent_history_browser.py --since-hours 24
```

## Example: Interactive Session

```
$ python3 agents/lib/agent_history_browser.py

Connecting to 192.168.86.200:5436/omninode_bridge...

================================================================================
AGENT EXECUTION HISTORY BROWSER
================================================================================

Recent Agent Runs:

┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ #  ┃ Correlation ID                       ┃ Agent Name              ┃ Time               ┃ Patterns ┃ Query Time ┃ Debug Intel  ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 1  │ a2f33abd-34c2-4d63-bfe7-2cb14ded13fd │ test-agent              │ 2m ago             │      150 │      650ms │    ✓5/✗3     │
│ 2  │ 897cb585-1bcb-4386-a9ec-232a39df002e │ demo-agent              │ 5m ago             │        0 │        0ms │    ✓0/✗0     │
│ 3  │ f8e7d6c5-b4a3-9281-e170-456def789abc │ polymorphic-agent       │ 15m ago            │      182 │     1245ms │    ✓8/✗2     │
│ 4  │ 12345678-1234-1234-1234-123456789abc │ api-architect           │ 1h ago             │       95 │      580ms │    ✓3/✗1     │
│ 5  │ abcdef12-3456-7890-abcd-ef1234567890 │ debug-intelligence      │ 2h ago             │      120 │      720ms │   ✓12/✗5     │
└────┴──────────────────────────────────────┴─────────────────────────┴────────────────────┴──────────┴────────────┴──────────────┘

Total: 5 agent runs

╭─────────────────────────────────────────────────────────────────────────────╮
│ Commands:                                                                   │
│   [number]           View detailed history for agent run                    │
│   search [name]      Filter by agent name                                   │
│   clear              Clear filter                                           │
│   limit [N]          Set list limit (current: 50)                           │
│   export [number]    Export manifest JSON                                   │
│   h, help            Show help                                              │
│   q, quit            Quit browser                                           │
╰─────────────────────────────────────────────────────────────────────────────╯

Command [q]: 1
```

## Example: Detail View

```
================================================================================
AGENT EXECUTION HISTORY BROWSER
================================================================================

╭──────────────────────────── Agent Execution Details ─────────────────────────╮
│                                                                               │
│ Correlation ID: a2f33abd-34c2-4d63-bfe7-2cb14ded13fd                         │
│ Agent: test-agent                                                             │
│ Timestamp: 2025-10-27 13:45:32 UTC                                           │
│ Source: archon-intelligence-adapter (full)                                   │
│                                                                               │
╰───────────────────────────────────────────────────────────────────────────────╯

                            Performance Metrics
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Section                     ┃  Time (ms) ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ Patterns                    │        450 │
│ Infrastructure              │        120 │
│ Models                      │         80 │
│ Database Schemas            │        100 │
│ Debug Intelligence          │         75 │
│ Total                       │        825 │
└─────────────────────────────┴────────────┘

                              Manifest Content
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Category                     ┃  Count ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ Patterns                     │    150 │
│ Infrastructure Services      │      4 │
│ Models                       │      3 │
│ Database Schemas             │     12 │
│ Manifest Size                │ 45,682 │
└──────────────────────────────┴────────┘

╭────────────────────────────── Debug Intelligence ────────────────────────────╮
│                                                                               │
│ ✓ Successful Approaches: 5 examples                                          │
│ ✗ Failed Approaches: 3 examples to avoid                                     │
│                                                                               │
╰───────────────────────────────────────────────────────────────────────────────╯

Successful Approaches (what worked):
  • Edit: Fixed import error in module initialization
  • Write: Created new configuration file with proper format
  • Bash: Successfully ran tests after fixing dependencies
  • Read: Identified issue by reading error logs
  • Grep: Found similar pattern in existing codebase

Failed Approaches (avoid retrying):
  • Write: Syntax error in generated code
  • Edit: Attempted to modify non-existent file
  • Bash: Command failed due to missing environment variable

╭───────────────────────── Formatted Manifest Preview ─────────────────────────╮
│ ======================================================================       │
│ SYSTEM MANIFEST - Dynamic Context via Event Bus                             │
│ ======================================================================       │
│                                                                               │
│ Version: 2.0.0                                                               │
│ Generated: 2025-10-27T13:45:32.123456+00:00                                 │
│ Source: archon-intelligence-adapter                                          │
│                                                                               │
│ AVAILABLE PATTERNS:                                                          │
│   Collections: execution_patterns (50), code_patterns (100)                 │
│                                                                               │
│   • NodeDatabaseWriterEffect (95% confidence)                                │
│     File: node_database_writer_effect.py                                     │
│     Node Types: EFFECT                                                       │
│   • NodeDataTransformerCompute (92% confidence)                              │
│     File: node_data_transformer_compute.py                                   │
│     Node Types: COMPUTE                                                      │
│   ... and 148 more patterns                                                  │
│                                                                               │
│ AI MODELS & DATA MODELS:                                                     │
│   AI Providers:                                                              │
│     • Anthropic: Claude models available                                     │
│     • Google Gemini: Gemini models available                                 │
│                                                                               │
│ ... (135 more lines)                                                         │
│                                                                               │
╰───────────────────────────────────────────────────────────────────────────── (first 20 lines) ╯

Press Enter to return...
```

## Example: Search and Filter

```
Command [q]: search test

Filtering by agent: test

Recent Agent Runs:

┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ #  ┃ Correlation ID                       ┃ Agent Name              ┃ Time               ┃ Patterns ┃ Query Time ┃ Debug Intel  ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 1  │ a2f33abd-34c2-4d63-bfe7-2cb14ded13fd │ test-agent              │ 2m ago             │      150 │      650ms │    ✓5/✗3     │
│ 2  │ b3e4f5a6-7890-1234-5678-90abcdef1234 │ test-agent              │ 10m ago            │      145 │      620ms │    ✓4/✗2     │
│ 3  │ c5d6e7f8-9012-3456-7890-abcdef123456 │ testing-specialist      │ 25m ago            │      132 │      710ms │    ✓6/✗1     │
└────┴──────────────────────────────────────┴─────────────────────────┴────────────────────┴──────────┴────────────┴──────────────┘

Total: 3 agent runs (filtering: test)

Command [q]: clear

Filter cleared
```

## Example: Export Manifest

```
Command [q]: export 1

✓ Manifest exported to: manifest_a2f33abd-34c2-4d63-bfe7-2cb14ded13fd.json

Command [q]: q
```

## Non-Interactive Usage

### Show specific correlation ID

```bash
$ python3 agents/lib/agent_history_browser.py \
    --correlation-id a2f33abd-34c2-4d63-bfe7-2cb14ded13fd

AGENT EXECUTION DETAILS
================================================================================
Correlation ID: a2f33abd-34c2-4d63-bfe7-2cb14ded13fd
Agent: test-agent
Timestamp: 2025-10-27 13:45:32 UTC
Source: archon-intelligence-adapter (full)

PERFORMANCE METRICS:
  Patterns: 450ms
  Infrastructure: 120ms
  Models: 80ms
  Database Schemas: 100ms
  Debug Intelligence: 75ms
  Total Time: 825ms

[... full detail output ...]
```

### Export manifest directly

```bash
$ python3 agents/lib/agent_history_browser.py \
    --correlation-id a2f33abd-34c2-4d63-bfe7-2cb14ded13fd \
    --export manifest.json

✓ Manifest exported to: manifest.json
```

### Filter by agent and limit

```bash
$ python3 agents/lib/agent_history_browser.py \
    --agent polymorphic \
    --limit 10

# Shows last 10 runs from agents matching "polymorphic"
```

## UI Variants

### With Rich Library (Enhanced UI)

When `rich` is installed, you get:
- ✅ Colored output with syntax highlighting
- ✅ Beautiful tables with borders
- ✅ Panels with titles and borders
- ✅ Progress indicators
- ✅ Clear screen between views

Install with: `pip install rich`

### Without Rich Library (Basic UI)

Falls back to basic formatting:
- Plain text tables
- ASCII borders
- No colors (but still fully functional)
- Works in any terminal

## Debug Intelligence Display

The browser shows two types of debug intelligence:

### ✓ Successful Approaches (what worked)
Examples of similar workflows that succeeded. These show proven approaches for similar tasks.

Example:
```
✓ Successful Approaches (what worked):
  • Edit: Fixed import error in module initialization
  • Write: Created new configuration file with proper format
  • Bash: Successfully ran tests after fixing dependencies
```

### ✗ Failed Approaches (avoid retrying)
Examples of similar workflows that failed. These help agents avoid repeating mistakes.

Example:
```
✗ Failed Approaches (avoid retrying):
  • Write: Syntax error in generated code
  • Edit: Attempted to modify non-existent file
  • Bash: Command failed due to missing environment variable
```

## Database Connection

The browser connects to PostgreSQL using these defaults:

| Variable | Default Value | Environment Variable |
|----------|--------------|---------------------|
| Host | 192.168.86.200 | `POSTGRES_HOST` |
| Port | 5436 | `POSTGRES_PORT` |
| Database | omninode_bridge | `POSTGRES_DATABASE` |
| User | postgres | `POSTGRES_USER` |
| Password | omninode-bridge-postgres-dev-2024 | `POSTGRES_PASSWORD` |

Override via environment variables:
```bash
export POSTGRES_HOST=192.168.86.101
export POSTGRES_PORT=5436
export POSTGRES_DATABASE=omninode_bridge
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=your-password

python3 agents/lib/agent_history_browser.py
```

## Understanding the Display

### List View Columns

| Column | Description |
|--------|-------------|
| # | Selection number for interactive mode |
| Correlation ID | Unique ID linking routing → manifest → execution |
| Agent Name | Agent that received the manifest |
| Time | Relative time (e.g., "2m ago", "1h ago") |
| Patterns | Number of code patterns included in manifest |
| Query Time | Total time to generate manifest (ms) |
| Debug Intel | ✓successes/✗failures format |

**Color Coding** (with rich):
- 🟢 Green: Full manifest from intelligence service
- 🔴 Red: Fallback manifest (intelligence unavailable)

### Detail View Sections

1. **Header**: Correlation ID, agent name, timestamp, source
2. **Performance Metrics**: Query time breakdown by section
3. **Manifest Content**: Summary counts (patterns, services, models, schemas)
4. **Debug Intelligence**: Successful/failed approaches from similar workflows
5. **Formatted Manifest Preview**: First 20 lines of actual manifest text

## Use Cases

### 1. Debugging Failed Agent Executions

Find what manifest was provided when execution failed:
```bash
python3 agents/lib/agent_history_browser.py --agent failed-agent
# Select the failed run to see what intelligence was missing
```

### 2. Comparing Successful vs Failed Runs

Compare manifests between successful and failed executions:
- Look for patterns count differences
- Check debug intelligence availability
- Analyze query performance

### 3. Analyzing Performance Issues

Identify slow manifest generation:
```bash
python3 agents/lib/agent_history_browser.py --limit 100
# Sort by Query Time column to find slow generations
```

### 4. Audit Trail

Export complete manifest for compliance/audit:
```bash
python3 agents/lib/agent_history_browser.py \
    --correlation-id <id> \
    --export audit_record.json
```

### 5. Learning from History

Review debug intelligence to see what approaches worked/failed:
- View detail for any run
- Check "Successful Approaches" section
- Avoid "Failed Approaches" patterns

## Tips and Tricks

### Quick Navigation

- Press `1-9` to jump directly to a run
- Type `search <name>` to filter instantly
- Use `limit 10` for quick scans
- Use `clear` to reset filters

### Search Patterns

Search is case-insensitive and supports partial matches:
```
search test       → Matches "test-agent", "testing-specialist"
search poly       → Matches "polymorphic-agent"
search api        → Matches "api-architect"
```

### Export Workflow

1. Launch browser
2. Find interesting run
3. Type `export 1` (or whatever number)
4. JSON saved to `manifest_[correlation-id].json`
5. Analyze with `jq` or your favorite tool

### Time Filters

Show only recent runs:
```bash
# Last hour
python3 agents/lib/agent_history_browser.py --since-hours 1

# Last 24 hours
python3 agents/lib/agent_history_browser.py --since-hours 24

# Last week
python3 agents/lib/agent_history_browser.py --since-hours 168
```

## Troubleshooting

### "Failed to connect to database"

**Causes**:
- Database not running
- Wrong host/port
- Wrong credentials
- Network connectivity issues

**Solutions**:
1. Check database is running
2. Verify environment variables
3. Test connection with `psql`:
   ```bash
   psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge
   ```

### "No agent runs found"

**Causes**:
- Fresh database (no records yet)
- Manifest injection not enabled
- Wrong database

**Solutions**:
1. Run agents with manifest injection enabled
2. Check `ManifestInjector(enable_storage=True)`
3. Verify correct database connection

### "Module not found: psycopg2"

Install psycopg2:
```bash
pip install psycopg2-binary
```

### "Module not found: rich"

Rich is optional. Install for enhanced UI:
```bash
pip install rich
```

Or use without it (basic UI still works).

## Integration with Manifest Traceability

This browser is part of the complete manifest traceability system:

1. **Manifest Injection** → Records created by `ManifestInjector`
2. **Database Storage** → PostgreSQL `agent_manifest_injections` table
3. **Browser Tool** → This tool for interactive exploration
4. **Export/Analysis** → JSON export for deeper analysis

See `MANIFEST_TRACEABILITY_GUIDE.md` for complete system documentation.

## Future Enhancements

Planned features:
- [ ] Correlation with agent_routing_decisions for complete trace
- [ ] Diff view to compare two manifests
- [ ] Statistics dashboard (success rates, performance trends)
- [ ] Web UI version
- [ ] Real-time monitoring mode
- [ ] Search by content (patterns, intelligence)
- [ ] Batch export for multiple runs
- [ ] Integration with EventStore for workflow tracking

## Support

For issues or questions:
1. Check `MANIFEST_TRACEABILITY_GUIDE.md` for database queries
2. Review migration `008_agent_manifest_traceability.sql`
3. Test database connection manually with `psql`
4. Verify manifest injection is enabled in your agents

## License

Part of OmniClaude framework - internal tool for agent observability and traceability.
