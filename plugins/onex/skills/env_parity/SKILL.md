---
description: Multi-machine environment conformance checker — validates settings, env files, secrets, and topology against the machine registry
mode: full
version: 2.0.0
level: advanced
debug: false
category: operations
tags: [parity, drift, conformance, registry, multi-machine, settings, env]
author: OmniClaude Team
composable: true
inputs:
  - name: subcommand
    type: str
    description: "Mode: check (audit) or fix (auto-fix conformance issues)"
    required: false
args:
  - name: subcommand
    description: "Mode: check (default) or fix"
    required: false
  - name: --machine-id
    description: "Target a specific machine (default: all machines in registry)"
    required: false
  - name: --fix-remote
    description: "Allow auto-fix on remote machines (requires fix subcommand)"
    required: false
  - name: --dry-run
    description: "Preview fix actions without executing"
    required: false
  - name: --create-tickets
    description: "Create Linear tickets for FAIL findings (opt-in, not default)"
    required: false
---

# Env Parity Checker

## Dispatch Surface

**Target**: Agent Teams

## Overview

Registry-backed multi-machine environment conformance checker. Validates each machine in the
fleet against its expected configuration derived from the machine registry (`machines.yaml`).

Replaces the previous Docker-vs-k8s parity scope with comprehensive multi-machine conformance:

- **Config**: `settings.json` existence, path correctness, no stale hooks blocks
- **Env**: No duplicate keys in `~/.omnibase/.env`
- **Secrets**: Infisical identity authenticates successfully
- **Topology**: Plugin symlink points to canonical clone

Unreachable machines are reported as `UNREACHABLE`, not as check failures.
Output is grouped by machine, then by check category, then by individual check.

## Checks Catalog

| check_id | category | auto_fixable | what it checks |
|----------|----------|-------------|----------------|
| `config.settings_exists` | config | no | `settings.json` exists at expected path per machine |
| `config.settings_paths` | config | yes (sync-settings) | `OMNI_HOME`, `ONEX_STATE_DIR`, statusLine match registry |
| `config.no_hooks_block` | config | yes | No empty `hooks` block in settings.json |
| `env.no_duplicates` | env | yes (last-wins dedup) | No duplicate keys in `~/.omnibase/.env` |
| `secrets.infisical_identity` | secrets | no (run bootstrap) | Infisical client ID authenticates successfully |
| `topology.plugin_symlink` | topology | yes (re-symlink) | Plugin cache is symlink to canonical clone |

## When to Use

- **Post-setup**: After bootstrapping a new machine with `onex env bootstrap`
- **Pre-deploy**: Before promoting a release to verify fleet conformance
- **Routine**: Periodic conformance sweeps across all machines
- **Post-incident**: After any settings-related or env-related failure

## Quick Start

```bash
# Check all machines (default)
/env_parity check

# Check a specific machine
/env_parity check --machine-id infra-server

# Auto-fix local machine
/env_parity fix

# Auto-fix including remote machines
/env_parity fix --fix-remote

# Dry-run fix
/env_parity fix --dry-run

# Create Linear tickets for FAIL findings
/env_parity check --create-tickets
```

## Status Semantics

| Status | Meaning |
|--------|---------|
| **PASS** | Check passed — machine conforms to registry |
| **WARN** | Non-blocking issue detected |
| **FAIL** | Conformance violation — action required |
| **UNREACHABLE** | Machine not reachable via SSH — checks skipped |

## Ticket Creation

Linear ticket creation requires the explicit `--create-tickets` flag. It is NOT the default.
This prevents ticket spam on routine conformance checks.

When `--create-tickets` is set, one ticket is created per FAIL finding using:
- Title: `[env-parity:<check_id>] <machine_id>: <finding detail>`
- Priority: 1 (Urgent)
- Project: Active Sprint
- Deduplication: exact prefix match on `[env-parity:<check_id>]` — skip if any existing ticket matches

## See Also

- `system-status` — overall platform health check
- `gap` — code/contract drift detection
- `onex env check` — the underlying CLI command
- `onex env bootstrap` — one-command machine setup
- `omnibase_infra/config/machines.yaml` — the machine registry
