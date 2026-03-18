---
description: Trigger artifact reconciliation for a repo — publishes a reconcile command to the event bus and returns the published event payload
version: 1.0.0
level: advanced
debug: false
category: quality
tags:
  - artifacts
  - reconciliation
  - kafka
  - event-bus
author: OmniClaude Team
composable: true
args:
  - name: --repo
    description: "Target repo name (e.g., omnibase_infra)"
    required: true
  - name: --reason
    description: "Human-readable reason for reconciliation (optional)"
    required: false
---

# Reconcile Artifacts Skill

## Overview

Triggers artifact reconciliation for a target repository by dispatching a `ModelManualReconcileCommand`
to the `onex.cmd.artifact.reconcile.v1` Kafka topic via the `omni-infra` CLI. Use this skill
when artifact state has diverged from source of truth — for example, after manual deployments,
failed pipelines, or drift detected during audit. The published event JSON is returned to the
caller for audit traceability.

The `--files` flag (for scoped file-level reconciliation) is intentionally not exposed in v1 of this skill; use the CLI directly if you need per-file scoping.

## Quick Start

```
# Reconcile a repo with default reason
/reconcile-artifacts --repo omnibase_infra

# Reconcile with an explicit reason
/reconcile-artifacts --repo omnibase_core --reason "Post-deploy artifact drift detected"

# Reconcile after a failed CI run
/reconcile-artifacts --repo omniintelligence --reason "Fixing artifact state after OMN-4088 pipeline failure"
```

## Behavior

1. Sources `~/.omnibase/.env` to load `KAFKA_BOOTSTRAP_SERVERS` and related config
2. Verifies that the `omni-infra` CLI is available on `PATH` (falls back to `uv run omni-infra`)
3. Runs `omni-infra artifact-reconcile --repo <repo> --reason "<reason>"`
4. Captures stdout from the CLI invocation
5. Always attempts to publish. Uses `KAFKA_BOOTSTRAP_SERVERS` if set, otherwise defaults to `localhost:19092`.
6. If the broker is unreachable: exits non-zero with an error message.
7. Returns the exit code, stdout, and any errors to the caller

## Output

On successful publish, the CLI prints status lines to stdout:

```
Publishing artifact-reconcile command (id=<uuid>, repo=omnibase_infra, files=0, bus=localhost:19092)
Published to onex.cmd.artifact.reconcile.v1 — command_id=<uuid>
```

The published Kafka message payload is a `ModelManualReconcileCommand` with fields:
`command_id`, `source_repo`, `changed_files`, `actor`, `reason`.

When the Kafka broker is unreachable or `confluent-kafka` raises a delivery error,
the CLI exits non-zero with an error message on stderr.

## Prerequisites

- `KAFKA_BOOTSTRAP_SERVERS` controls which Kafka broker to target. If unset, the CLI defaults to `localhost:19092`. Publishing is always attempted — there is no silent-skip mode.
- `omni-infra` CLI must be installed and accessible:
  - On `PATH` directly, OR
  - Via `uv run omni-infra` from an `omnibase_infra` worktree

## See Also

- CLI implementation: `omnibase_infra/src/omnibase_infra/cli/artifact_reconcile.py`
- Event topic: `onex.cmd.artifact.reconcile.v1`
- Command model: `ModelManualReconcileCommand`
