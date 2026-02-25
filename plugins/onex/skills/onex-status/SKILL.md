---
name: onex-status
description: Show current OmniClaude integration tier, probe age, and per-service reachability for self-diagnosis
version: 1.0.0
category: debug
tags:
  - debug
  - status
  - tier
  - diagnostics
  - onex
author: OmniClaude Team
---

# /onex-status

Display the current OmniClaude integration tier, probe file age, and per-service reachability.
Useful for self-diagnosing misconfiguration instantly.

## Quick Start

```
/onex-status
```

## What It Shows

```
OmniClaude Status
─────────────────
Tier:          FULL_ONEX
Probe age:     42s (fresh)

Services:
  Kafka        ✓ reachable   (broker-host:29092)
  Intelligence ✓ healthy     (http://localhost:8053/health)

Probe file:    ~/.claude/.onex_capabilities
Last updated:  2026-02-25T16:15:00Z

To refresh: restart Claude Code session or run /onex-status again
```

## Behavior

1. Reads `~/.claude/.onex_capabilities` (written by `capability_probe.py` at each SessionStart)
2. If the file is **missing or older than 5 minutes**, runs a fresh inline probe (2s timeout) and displays the result
3. Displays tier, probe age, and per-service reachability
4. In **standalone mode** (no Kafka configured), shows "not configured" for unchecked services

## Troubleshooting Guide

| Symptom | Likely cause | Action |
|---------|-------------|--------|
| `STANDALONE` (unexpected) | `KAFKA_BOOTSTRAP_SERVERS` not set or unreachable | Set env var and restart Claude Code session |
| `EVENT_BUS` instead of `FULL_ONEX` | Intelligence service not reachable | Check `INTELLIGENCE_SERVICE_URL` and service health |
| `UNKNOWN (re-probing...)` | First session or stale probe file | Run `/onex-status` again in 5s |
| Probe file older than 5 min | SessionStart probe not running | Check session-start.sh logs |

## Implementation

This skill invokes `plugins/onex/skills/onex-status/status.py` which:
- Imports `capability_probe` when available (requires OMN-2782 to be deployed)
- Falls back to inline probe logic when `capability_probe.py` is not yet installed
- Always exits cleanly — never raises exceptions to the user

## Instructions

When this skill is invoked:

1. Run `status.py` to gather current tier and service status
2. Display the formatted output exactly as shown in the "What It Shows" section
3. If the probe was refreshed (stale/missing file), note "Probe refreshed inline" in the output
4. Do not modify any files or configuration — this is a read-only diagnostic

```bash
python3 "$(dirname "$0")/status.py"
```
