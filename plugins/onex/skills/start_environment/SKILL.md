---
description: Audit-first Docker environment startup — inspects actual running state then starts missing bundles in dependency order
mode: full
version: 1.0.0
level: intermediate
debug: false
category: operations
tags: [docker, infra, startup, environment, postgres, redpanda, runtime]
author: OmniClaude Team
composable: true
args:
  - name: mode
    description: "What to start: core | runtime | memory | all | status (default: auto)"
    required: false
  - name: --status
    description: "Show current container state without starting anything"
    required: false
  - name: --wait-timeout
    description: "Seconds to wait for health before giving up (default: 120)"
    required: false
---

# Start Environment

## CRITICAL RULE — AUDIT FIRST, ALWAYS

**Before taking any action, run `docker ps` and read the output.**

Never assume any container is running. Never assume any container is stopped. The state of
the environment is unknown at skill invocation time. Read it. Then act.

This skill exists because repeated incidents were caused by agents assuming postgres or
redpanda were running when they were not. The fix is mandatory state inspection before every
startup sequence.

---

## Overview

Brings up the local ONEX Docker environment in the correct bundle order, starting only what
is missing or unhealthy. Uses the canonical `infra-*` shell functions — never raw
`docker compose -f <path>` (per CLAUDE.md, direct path usage caused the 2026-03-08 incident).

## Bundle Hierarchy

```
core     → postgres + redpanda + valkey        (always required)
runtime  → omninode-runtime + consumers + intelligence-api + workers
memory   → runtime + memgraph                  (superset of runtime)
```

**Dependency order**: core must be healthy before starting runtime. Runtime must be healthy
before starting memory. Never skip levels.

## When to Use

- Session start — ensure all required services are up before beginning work
- After a `docker restart` or machine sleep/wake
- After `infra-down` when returning to work
- When services report DNS failures (`[Errno -2] Name or service not known`) — this means
  core is down and runtime containers can't resolve `postgres` or `redpanda`

---

## Execution Protocol

### Phase 0 — State Audit (MANDATORY, NO EXCEPTIONS)

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Read and categorize every running container. Build two lists:
- **Running and healthy**: containers with `(healthy)` status
- **Missing or unhealthy**: containers expected but absent, or showing `(unhealthy)` / `(health: starting)`

Expected containers by bundle:

| Bundle | Container names (substring match) |
|--------|----------------------------------|
| core | `omnibase-infra-postgres`, `omnibase-infra-redpanda`, `omnibase-infra-valkey` |
| runtime | `omninode-runtime`, `omninode-runtime-effects`, `omnibase-intelligence-api`, `omninode-agent-actions-consumer`, `omninode-skill-lifecycle-consumer`, `omninode-contract-resolver`, `runtime-worker` |
| memory | `omnibase-infra-memgraph` |

If `--status` flag: print categorized state table and stop. Do not start anything.

### Phase 1 — Determine What to Start

Based on the audit and the requested mode:

| Mode | What gets started |
|------|------------------|
| `auto` (default) | Start any missing bundle. If runtime containers are unhealthy but core is missing → start core first. |
| `core` | Only start core bundle |
| `runtime` | Start core (if missing) then runtime |
| `memory` | Start core (if missing) then runtime (if missing) then memory |
| `all` | Start all bundles in order |
| `status` | Print state only, exit |

### Phase 2 — Start Core (if needed)

If postgres, redpanda, or valkey are missing/unhealthy:

```bash
infra-up
```

Then poll until core containers are healthy (or `--wait-timeout` exceeded):
```bash
# Poll every 5s — check postgres and redpanda specifically
docker ps --format "{{.Names}}\t{{.Status}}" | grep -E "(postgres|redpanda|valkey)"
```

Do not proceed to Phase 3 until core is healthy. If core fails to become healthy within
the timeout, report the failure and stop. Do not attempt to start runtime against a broken core.

### Phase 3 — Start Runtime (if needed)

Only if mode is `runtime`, `memory`, `all`, or `auto` with runtime containers missing or unhealthy.
Only after core is verified healthy.

```bash
infra-up-runtime
```

Poll until runtime containers are healthy:
```bash
docker ps --format "{{.Names}}\t{{.Status}}" | grep -E "(omninode-runtime|intelligence-api|consumer|worker)"
```

### Phase 4 — Start Memory (if needed)

Only if mode is `memory`, `all`, or `auto` with memory containers missing or unhealthy. Only after runtime is verified healthy.

```bash
infra-up-memory
```

### Phase 5 — Final State Report

Run `docker ps` again. Print a clean summary:

```
Environment Status
──────────────────
BUNDLE   CONTAINER                        STATUS
core     omnibase-infra-postgres          ✓ healthy
core     omnibase-infra-redpanda          ✓ healthy
core     omnibase-infra-valkey            ✓ healthy
runtime  omninode-runtime                 ✓ healthy
runtime  omnibase-intelligence-api        ✓ healthy
runtime  omninode-runtime-effects         ✓ healthy
...

Known persistent issues (pre-existing, not actionable):
  - omnibase-infra-memgraph: unhealthy (pre-existing)
  - omnibase-infra-phoenix: unhealthy (pre-existing)
```

Note any containers that are persistently unhealthy but are known pre-existing issues
(memgraph, phoenix) so the user isn't alarmed by them.

---

## Known Persistent Issues (Do Not Alarm the User)

These containers have been unhealthy for extended periods and are not blocking:

| Container | Issue | Impact |
|-----------|-------|--------|
| `omnibase-infra-memgraph` | Unhealthy health check | Non-blocking — memgraph is functional |
| `omnibase-infra-phoenix` | Unhealthy health check | Non-blocking — LLM observability only |

---

## Common Failure Patterns

### `[Errno -2] Name or service not known` in runtime logs

**Cause**: Runtime containers started before core (postgres/redpanda) was running. DNS names
`postgres` and `redpanda` don't resolve because those containers don't exist on the network.

**Fix**: `infra-up` to start core, then runtime containers will recover (autoheal or manual restart).

### `infra-up` hangs or fails

**Cause**: Stale compose state, orphaned containers, or port conflict.

**Diagnose**:
```bash
docker ps -a | grep -E "(postgres|redpanda)"   # Check for stopped containers
docker network inspect omnibase-infra-network  # Check network state
```

### Runtime containers healthy but services returning 503

**Cause**: Core started but migrations haven't run, or Infisical not seeded.

**Check**: `docker logs omnibase-infra-migration-gate` for migration status.

---

## Usage Examples

```bash
# Inspect state only — no changes
/start-environment --status

# Start whatever is missing (auto-detect)
/start-environment

# Ensure full runtime stack is up
/start-environment runtime

# Start everything including memory/memgraph
/start-environment all

# Start with extended health wait
/start-environment runtime --wait-timeout 180
```

## See Also

- `system-status` — comprehensive platform health (post-startup verification)
- `env-parity` — local Docker vs k8s drift detection
- CLAUDE.md → "Docker Operations" — shell function reference (`infra-up`, `infra-up-runtime`, etc.)
