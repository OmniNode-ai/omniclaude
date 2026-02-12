---
name: bus-audit
description: Run OmniClaude bus health audit (Layer 2 domain validation)
tags: [diagnostics, kafka, event-bus]
---

# Bus Audit

**Usage:** `/bus-audit [flags]`

Run the OmniClaude domain-specific bus health audit. This builds on the generic Layer 1 bus audit engine to add schema validation, emission presence checks, misroute detection, and verdict upgrades for core lifecycle topics.

## What This Does

Audits the Kafka event bus for OmniClaude-specific health:
- Validates 14 topic schemas against Pydantic models
- Checks emission presence per hook (SessionStart, SessionEnd, UserPromptSubmit, PostToolUse)
- Detects misrouted events (observability events on restricted cmd topics)
- Upgrades verdicts for core lifecycle topics (session-started, session-ended, prompt-submitted, tool-executed)
- Checks emit daemon health

## Implementation

Run the bus audit CLI script:

```bash
python /Volumes/PRO-G40/Code/omniclaude3/scripts/bus_audit.py
```

Forward any user-provided flags (e.g., `--json`, `--failures-only`, `-v`, `--skip-daemon`, `--broker`, `--sample-count`).

## Examples

```
/bus-audit                    # Full audit with default settings
/bus-audit --json             # JSON output for dashboards
/bus-audit --failures-only    # Only show problems
/bus-audit -v                 # Verbose: show sample payloads for failures
/bus-audit --skip-daemon      # Skip daemon health check
```
