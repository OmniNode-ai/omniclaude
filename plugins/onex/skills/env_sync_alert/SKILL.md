---
description: Alert on env-sync.log and critical log failures — emits friction YAML and Linear ticket
mode: full
version: "1.0.0"
level: basic
debug: false
category: observability
tags:
  - infra
  - alerting
  - env-sync
  - infisical
  - friction
author: OmniNode Team
ticket: OMN-8868
---

# env_sync_alert

Scans `.onex_state/logs/env-sync.log` for seed-infisical failures. If error_count > 0 AND
last success was > 1 hour ago, emits a friction YAML entry and creates a Linear ticket.

Also scans `hooks.log` and `pipeline-trace.log` for ERROR/CRITICAL patterns.

## Invocation

```bash
# Run check directly
onex skill env_sync_alert

# Non-zero exit = alert fired
```

## Cron Integration

Added to overseer tick (*/15 * * * *) prompt. The overseer runs this check on every pulse.

## Outputs

- Friction YAML: `$ONEX_STATE_DIR/friction/env-sync-alert-{timestamp}.yaml`
- Linear ticket: created/updated when alert fires and `create_linear_ticket=True`
- Exit code: 0=clean, 1=alert fired
