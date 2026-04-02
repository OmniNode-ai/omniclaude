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

**Before taking any action, check actual service health.**

Never assume any service is running or stopped. The state of the environment is unknown at
skill invocation time. Check it. Then act.

### Health Check Strategy [OMN-7238]

Infrastructure may run **locally in Docker** or on a **remote host** (per `POSTGRES_HOST` in env).
Always source `~/.omnibase/.env` first and use `POSTGRES_HOST` to determine where infra lives.

**Primary checks (always work, local or remote):**
```bash
source ~/.omnibase/.env
INFRA_HOST="${POSTGRES_HOST:-localhost}"
curl -sf "http://${INFRA_HOST}:8085/health"        # runtime API
curl -sf "http://${INFRA_HOST}:8053/health"        # intelligence API
psql -h "${INFRA_HOST}" -p "${POSTGRES_PORT:-5436}" -U postgres -d omnibase_infra -c 'SELECT 1'
kcat -L -b "${KAFKA_BOOTSTRAP_SERVERS}" 2>&1 | head -3
```

**Supplementary checks (only when infra is local Docker):**
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

If `POSTGRES_HOST` points to a remote host, `docker ps` reflects LOCAL Docker only and
will show zero containers — this is expected and NOT a failure signal.

---

## Overview

Brings up the ONEX Docker environment in the correct bundle order, starting only what
is missing or unhealthy. Uses the canonical `infra-*` shell functions — never raw
`docker compose -f <path>` (per CLAUDE.md, direct path usage caused the 2026-03-08 incident).

**NOTE**: The `infra-*` shell functions and `docker compose` commands only work when
infrastructure runs in local Docker. When infra is on a remote host, this skill
operates in **audit-only mode** — it checks health endpoints and reports status but
cannot start/stop remote containers.

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
source ~/.omnibase/.env
INFRA_HOST="${POSTGRES_HOST:-localhost}"
IS_LOCAL=$([[ "${INFRA_HOST}" == "localhost" || "${INFRA_HOST}" == "127.0.0.1" ]] && echo true || echo false)

# Always check health endpoints (works local or remote)
echo "=== Health Endpoint Checks (host: ${INFRA_HOST}) ==="
curl -sf "http://${INFRA_HOST}:8085/health" && echo "runtime: HEALTHY" || echo "runtime: UNHEALTHY"
curl -sf "http://${INFRA_HOST}:8053/health" && echo "intelligence-api: HEALTHY" || echo "intelligence-api: UNHEALTHY"
psql -h "${INFRA_HOST}" -p "${POSTGRES_PORT:-5436}" -U postgres -d omnibase_infra -c 'SELECT 1' >/dev/null 2>&1 && echo "postgres: HEALTHY" || echo "postgres: UNHEALTHY"
kcat -L -b "${KAFKA_BOOTSTRAP_SERVERS}" 2>/dev/null | head -1 | grep -q "broker" && echo "kafka: HEALTHY" || echo "kafka: UNHEALTHY"

# Supplementary: local Docker state (only meaningful when infra is local)
if [[ "${IS_LOCAL}" == "true" ]]; then
  echo "=== Local Docker State ==="
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
fi
```

Build two lists from health endpoint results:
- **Healthy**: services returning 200 / responding to queries
- **Unhealthy**: services unreachable or returning errors

If infra is on a remote host (`POSTGRES_HOST` != localhost), skip Docker container enumeration
and rely entirely on health endpoints.

Expected services:

| Bundle | Health checks |
|--------|--------------|
| core | postgres (`SELECT 1`), kafka (kcat broker metadata) |
| runtime | `http://$INFRA_HOST:8085/health`, `http://$INFRA_HOST:8053/health` |

If `--status` flag: print categorized state table and stop. Do not start anything.

### Phase 1 — Determine What to Start

**Remote host mode**: If `POSTGRES_HOST` points to a non-localhost address, this skill
operates in **audit-only mode**. It reports health status but cannot start/stop containers
on the remote host. If any service is unhealthy, report the failure and stop — do not
attempt `infra-up` against a remote host.

**Local Docker mode**: Based on the audit and the requested mode:

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
