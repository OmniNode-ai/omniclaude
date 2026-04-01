---
description: Periodic hook health check with Slack alerting when error rates exceed thresholds
mode: full
version: "1.0.0"
level: advanced
debug: false
category: observability
tags:
  - hooks
  - health
  - alerting
  - slack
args:
  - name: --dry-run
    description: "Report findings without sending Slack alerts"
    required: false
  - name: --window
    description: "Time window in minutes (default: 5)"
    required: false
  - name: --threshold
    description: "Error count threshold for alerting (default: 5)"
    required: false
  - name: --schedule
    description: "Schedule recurring check via CronCreate (e.g., '5m')"
    required: false
---

# Hook Health Alert

## Purpose

Periodic check of hook error rates. Queries the omnidash API for hook health
summary, evaluates against thresholds, and fires Slack alerts when tier 1
(interpreter) or tier 2 (degraded) errors exceed the configured threshold.

Designed as a skill-based interim solution. Will migrate to an ONEX effect node
(consuming `onex.evt.omniclaude.hook-health-error.v1` directly) when the
runtime node system is operational.

## Execution

1. Query `GET /api/hook-health/summary?window={window}m` from omnidash
   (pending: omnidash endpoint not yet implemented; uses local `hook_health_probe` until then)
2. Evaluate:
   - Tier 1 (interpreter) errors > 0: CRITICAL alert (always)
   - Tier 2 (degraded) errors > threshold: WARNING alert
   - Tier 3 (intentional): dashboard only, no alert
3. If alert needed and not --dry-run:
   - Post to Slack via `SLACK_BOT_TOKEN` / `SLACK_CHANNEL_ID`
   - Rate limit: one alert per stable alert identity per 30 minutes
   - Alert identity = `{hook_name}:{error_tier}:{error_category}`
   - Message format matches existing blocked_notifier.py Block Kit style
4. Log result to `.onex_state/hook-health/last-check.json`

## Alert Format

```
:red_circle: Hook Health CRITICAL
Interpreter errors detected (N in last 5m)

Hook: pre_tool_use_authorization_shim
Category: import_error
Message: ImportError: cannot import name 'UTC'...
Python: 3.9.6 (expected 3.12+)

Action: Rebuild plugin venv -- `cd plugins/onex/lib && uv sync`
```

## Scheduling

```
/hook-health-alert --schedule 5m
```

This creates a CronCreate job that runs the check every 5 minutes.
