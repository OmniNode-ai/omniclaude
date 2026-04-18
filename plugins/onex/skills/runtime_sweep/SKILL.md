---
description: Runtime registration and wiring verification — checks node descriptions are real (not compute+hash), all contract-declared handlers are wired in dispatch, all topics have both producer and consumer, container logs are free of repeated errors, omninode-runtime containers have RestartCount <= 5, and orchestrator consumer groups are non-Empty. Auto-creates Linear tickets for unwired handlers, error-heavy containers, crash-looping containers, and stranded consumer groups.
mode: full
version: "1.0.0"
level: advanced
debug: false
category: verification
tags: [runtime, wiring, contracts, sweep, close-out]
author: omninode
composable: true
args:
  - name: --dry-run
    description: "Report findings without creating Linear tickets (default: false)"
    required: false
  - name: --scope
    description: "Check scope: omnidash-only | all-repos (default: all-repos)"
    required: false
---

# Runtime Sweep

**Announce at start:** "I'm using the runtime-sweep skill to verify runtime registration and wiring integrity."

## Usage

```
/runtime-sweep
/runtime-sweep --dry-run
/runtime-sweep --scope omnidash-only
```

## Execution

### Phase 1 — Parse arguments

- `--dry-run` → pass through to node
- `--scope` → `all-repos` (default) or `omnidash-only`

### Phase 2 — Run node

```bash
onex run node_runtime_sweep -- \
  --scope <all-repos|omnidash-only> \
  [--dry-run]
```

Capture stdout (JSON: `RuntimeSweepResult`). Exit 0 = clean, exit 1 = findings.

### Phase 3 — Render report

From the JSON output display four summary tables:

**Node Descriptions** — REAL / PLACEHOLDER / MISSING per contract

**Handler Wiring** — WIRED / UNWIRED / ORPHAN_TOPIC per handler file

**Topic Symmetry** — SYMMETRIC / PRODUCER_ONLY / CONSUMER_ONLY per topic

Report counts by finding type. List each finding with subject and type.

### Phase 3b — Docker Log Analysis

For each running container, call `get_container_logs()` via `docker_helper`:

```python
logs = docker_helper.get_container_logs(container_id, tail=500)
```

Classify container log health:
- **CLEAN**: no errors in last 500 lines
- **NOISY**: repeated non-fatal warnings
- **ERROR_HEAVY**: >10% of lines are errors
- **CRASH_LOOP**: container restarted in last 5 minutes

### Phase 3c — Live Container Crash-Loop Detection [OMN-9122]

For each `omninode-runtime*` container, run:

```bash
docker inspect --format='{{.RestartCount}}' "$CONTAINER_NAME"
```

Threshold: `RestartCount > 5` → `CRASH_LOOP_CRITICAL` finding. Writes friction YAML to
`$ONEX_STATE_DIR/friction/runtime_sweep_<timestamp>.yaml` and exits non-zero.

### Phase 3d — Orchestrator Consumer Group Health [OMN-9122]

Derive consumer groups from `event_bus.subscribe_topics` in contract YAMLs. For each group:

```bash
docker exec omnibase-infra-redpanda rpk group describe "$GROUP_NAME" --brokers localhost:9092
```

`STATE: Empty` → `CONSUMER_GROUP_EMPTY` finding. Writes friction YAML and exits non-zero.

### Phase 4 — Ticket creation (skipped if `--dry-run`)

For each finding with type PLACEHOLDER_DESCRIPTION, MISSING_DESCRIPTION,
UNWIRED_HANDLER, ORPHAN_TOPIC, PRODUCER_ONLY, CONSUMER_ONLY,
CRASH_LOOP_CRITICAL, or CONSUMER_GROUP_EMPTY, create a Linear ticket via
`tracker.save_issue`:

```
Title: fix(wiring): <finding_type> — <subject>
Project: Active Sprint
Labels: wiring, runtime-sweep
```

Skip ticket creation for REAL, WIRED, SYMMETRIC findings (healthy state).

### Phase 5 — Write skill result

Write to `$ONEX_STATE_DIR/skill-results/<run_id>/runtime-sweep.json`:

```json
{
  "skill": "runtime-sweep",
  "status": "clean | findings | error",
  "contracts_checked": 0,
  "total_findings": 0,
  "by_type": {}
}
```

If Phase 3c or Phase 3d found violations, additionally write a friction YAML to
`$ONEX_STATE_DIR/friction/runtime_sweep_<timestamp>.yaml` with crash-loop and
consumer-group findings, then exit non-zero.

## Architecture

```
SKILL.md  → thin shell: parse args → node dispatch → render results
node      → omnimarket/src/omnimarket/nodes/node_runtime_sweep/
contract  → node_runtime_sweep/contract.yaml
```

All wiring verification logic lives in the node handler. This skill does no analysis.
