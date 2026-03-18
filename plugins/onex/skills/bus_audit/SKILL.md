---
description: Run OmniClaude bus health audit (Layer 2 domain validation)
version: "1.0.0"
level: advanced
debug: false
category: diagnostics
tags:
  - diagnostics
  - kafka
  - event-bus
author: omninode
args:
  - name: --json
    description: "Output results in JSON format for dashboard integration"
    required: false
  - name: --failures-only
    description: "Show only failed checks"
    required: false
  - name: --verbose
    description: "Include sample payloads for failed checks"
    required: false
  - name: --skip-daemon
    description: "Skip emit daemon health check"
    required: false
  - name: --broker
    description: "Override Kafka broker address (default: reads $KAFKA_BOOTSTRAP_SERVERS)"
    required: false
  - name: --sample-count
    description: "Number of messages to sample per topic (default: 20)"
    required: false
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

When invoked:

1. Execute the bus audit script located at `scripts/bus_audit.py` in the repository root
2. Pass through any user-provided flags to the script:
   - `--json` - Output results in JSON format for dashboard integration
   - `--failures-only` - Show only failed checks
   - `-v` / `--verbose` - Include sample payloads for failed checks
   - `--skip-daemon` - Skip emit daemon health check
   - `--broker <host:port>` - Override Kafka broker address (default: reads `$KAFKA_BOOTSTRAP_SERVERS`, falls back to `<kafka-bootstrap-servers>:9092`)
   - `--sample-count <n>` - Number of messages to sample per topic (default: 20)

3. Display the audit results to the user, including:
   - Topic presence and accessibility
   - Schema validation status for each topic
   - Hook emission status (SessionStart, SessionEnd, UserPromptSubmit, PostToolUse)
   - Misroute detection results
   - Emit daemon health status (unless skipped)
   - Overall verdict with upgrade logic for core lifecycle topics

## Examples

```
/bus-audit                    # Full audit with default settings
/bus-audit --json             # JSON output for dashboards
/bus-audit --failures-only    # Only show problems
/bus-audit -v                 # Verbose: show sample payloads for failures
/bus-audit --skip-daemon      # Skip daemon health check
```
