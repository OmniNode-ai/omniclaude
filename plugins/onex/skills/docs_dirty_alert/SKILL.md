---
description: Alert when untracked docs/{handoffs,evidence,plans,deep-dives} files in omni_home exceed a count threshold or are older than 4 hours
mode: full
version: "1.0.0"
level: basic
debug: false
category: observability
tags:
  - docs
  - alerting
  - dirty-canonical
  - friction
author: OmniNode Team
skill_kind: dispatch
---

# docs_dirty_alert

Scans the `omni_home` canonical registry for untracked files under
`docs/handoffs`, `docs/evidence`, `docs/plans`, and `docs/deep-dives`.

Fires an alert when either condition is true:
- **Count threshold exceeded**: total untracked docs files >= `count_threshold` (default 50)
- **Age threshold exceeded**: any untracked file has an mtime older than `age_threshold_seconds` (default 14 400 s = 4 h)

On alert, writes a friction YAML to `$ONEX_STATE_DIR/friction/` and exits 1.
Exits 0 when clean.

## Invocation

```bash
# Run check directly (requires OMNI_HOME and ONEX_STATE_DIR)
onex skill docs_dirty_alert

# Non-zero exit = alert fired
```

## Cron Integration

Added to session crons via `scripts/setup-session-crons.sh`. Runs every 30 min.
The cron prompt runs this check and emits a friction entry via
`Skill(skill="onex:record_friction", ...)` when alert fires.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OMNI_HOME` | Yes | Path to the canonical omni_home registry root |
| `ONEX_STATE_DIR` | Yes | ONEX runtime state directory |

## Outputs

- Friction YAML: `$ONEX_STATE_DIR/friction/docs-dirty-alert-{timestamp}.yaml`
- Exit code: 0 = clean, 1 = alert fired
