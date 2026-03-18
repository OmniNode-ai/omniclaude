---
description: Local Docker vs onex-dev k8s environment parity checker — detects credential drift, stale ECR tags, and missing Infisical paths
version: 1.0.0
level: advanced
debug: false
category: operations
tags: [parity, drift, credentials, ecr, infisical, k8s, docker]
author: OmniClaude Team
composable: true
inputs:
  - name: subcommand
    type: str
    description: "Mode: check (audit) or fix (auto-fix Infisical paths only)"
    required: false
args:
  - name: subcommand
    description: "Mode: check (default) or fix"
    required: false
  - name: --checks
    description: "Comma-separated check IDs (default: credential,ecr,infisical)"
    required: false
  - name: --all-checks
    description: "Run all 8 checks including secondary (schema, services, flags, kafka, packages)"
    required: false
  - name: --namespace
    description: "k8s namespace to probe (default: onex-dev)"
    required: false
  - name: --dry-run
    description: "Preview fix actions without executing"
    required: false
  - name: --create-tickets
    description: "Create Linear tickets for CRITICAL findings (opt-in, not default)"
    required: false
mode: full
---

# Env Parity Checker

## Dispatch Requirement

This skill MUST be dispatched through `onex:polymorphic-agent`. Never execute env-parity directly.

```python
Skill(skill="onex:env-parity", args="check --checks credential,ecr,infisical")
```

## Overview

Automated local-Docker vs onex-dev k8s parity checker. Detects:

- **CRITICAL** (default): credential drift, stale ECR tags, missing Infisical paths
- **WARNING** (--all-checks): schema drift, missing deployments, feature flag mismatches, Kafka topic gaps, package version mismatches

**Incident origin (2026-03-10):**
1. `omniintelligence-credentials` had `POSTGRES_USER=postgres` instead of `role_omniintelligence` — DB auth failures after pod restart
2. ECR tags deleted while still referenced in active deployment specs — `ErrImagePull` on rollout
3. Infisical paths never seeded — InfisicalSecret 404 loops for hours

The `onex:gap` skill covers code/contract drift. This skill fills the runtime state gap.

## Checks Catalog

| check_id | severity_tier | incident_class | default | auto_fixable |
|----------|--------------|----------------|---------|-------------|
| `credential` | CRITICAL | DB auth failure on pod restart | yes | no |
| `ecr` | CRITICAL | ErrImagePull on rollout | yes | no |
| `infisical` | CRITICAL | InfisicalSecret 404 loops | yes | yes |
| `schema` | WARNING | Migration state drift | --all-checks | no |
| `services` | WARNING | Missing deployment | --all-checks | no |
| `flags` | WARNING | Feature flag inconsistency | --all-checks | no |
| `kafka` | WARNING | Missing Kafka topics in cloud | --all-checks | no |
| `packages` | WARNING | Package version mismatch | --all-checks | no |

## When to Use

- **Post-incident**: After any DB auth failure, ErrImagePull, or InfisicalSecret error
- **Pre-deploy**: Before promoting a new release to verify cloud state matches local
- **Ad hoc**: When suspecting drift between local and cloud environments

## Quick Start

```bash
# Default: CRITICAL checks only (credential, ECR, Infisical)
/env-parity check

# All 8 checks
/env-parity check --all-checks

# Fix Infisical path gaps (only auto-fixable check)
/env-parity fix --checks infisical

# Dry-run fix
/env-parity fix --checks infisical --dry-run

# Create Linear tickets for CRITICAL findings
/env-parity check --create-tickets
```

## Alert Thresholds

| Severity | Action |
|----------|--------|
| **CRITICAL** | Fix today — active or imminent production impact |
| **WARNING** | Fix this sprint — quality/reliability risk |
| **INFO** | Informational — no action required |

## Ticket Creation

Linear ticket creation requires the explicit `--create-tickets` flag. It is NOT the default.
This prevents ticket spam on routine parity checks.

When `--create-tickets` is set, one ticket is created per CRITICAL finding using:
- Title: `[env-parity:<check_id>] <finding title verbatim>`
- Priority: 1 (Urgent)
- Project: Active Sprint
- Deduplication: exact prefix match on `[env-parity:<check_id>]` — skip if any existing ticket (any state) matches

## See Also

- `system-status` — overall platform health check
- `gap` — code/contract drift detection
- `omnibase_infra/scripts/system_health_check.sh` — infrastructure health
- `omnibase_infra/scripts/compare_environments.py` — the underlying probe script
