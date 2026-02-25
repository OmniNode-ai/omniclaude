---
name: rrh
description: Opt-in preflight validation via Release Readiness Handshake (RRH) -- runs A1 (collect) -> A2 (validate) -> A3 (store) pipeline before side-effecting phases
version: 1.0.0
category: validation
tags:
  - rrh
  - preflight
  - validation
  - pipeline
  - governance
author: OmniClaude Team
---

# Release Readiness Handshake (RRH) Skill

## Overview

RRH is an **opt-in preflight validation** step that proves the working environment
is correct before a pipeline phase commits side effects (pushes, PRs, deploys).

The pipeline runs three stages in sequence:

| Stage | Node Role | Purpose |
|-------|-----------|---------|
| **A1** | Collect (Effect) | Gather git state, runtime target, toolchain versions |
| **A2** | Validate (Compute) | Pure validation of environment against profile rules |
| **A3** | Store (Effect) | Write JSON artifact + symlinks for audit trail |

The result is a `ContractRRHResult` containing individual check results and an
aggregated verdict: **PASS**, **FAIL**, or **QUARANTINE**.

## Profiles

RRH supports four validation profiles, each with different strictness levels:

| Profile | Strictness | Use Case |
|---------|-----------|----------|
| `default` | Baseline | General-purpose sanity checks |
| `ticket-pipeline` | Standard | Used by ticket-pipeline at most invocation points |
| `ci-repair` | Moderate | CI failure repair workflows |
| `seam-ticket` | Strictest | Seam tickets at deploy phase (cross-boundary changes) |

## When to Call RRH

RRH is invoked at four points during pipeline execution:

| Phase | Profile | Purpose |
|-------|---------|---------|
| Before first side effect | `ticket-pipeline` | Prove environment correct before any mutations |
| Before PR creation | `ticket-pipeline` | Prove repo is clean and branch is valid |
| Before deploy-like step | `seam-ticket` (if seam) | Strictest check for cross-boundary changes |
| On `--skip-to` resume | Same as original phase | Re-validate after potential drift from skipped phases |

### Decision Logic

- **PASS** -- Pipeline continues to the next phase.
- **FAIL** -- Pipeline blocks. The `should_block` flag is `True` and the human summary
  explains what failed.
- **QUARANTINE** -- Pipeline continues with a warning. This is used when RRH nodes
  are not installed (fallback mode) or when checks are inconclusive.

## Governance Fields

Governance is derived from `ModelTicketContract` at invocation time:

| Field | Source | Purpose |
|-------|--------|---------|
| `ticket_id` | `contract.ticket_id` | Correlation key for the pipeline run |
| `evidence_requirements` | `contract.verification_steps` | Which evidence types are needed (e.g., "tests") |
| `interfaces_touched` | `contract.interfaces_provided` + `contract.interfaces_consumed` | Interfaces affected by this change |
| `deployment_targets` | `contract.context["deployment_targets"]` | Where the artifact will be deployed |
| `is_seam_ticket` | `contract.context["is_seam_ticket"]` | Whether this is a cross-boundary seam ticket |
| `expected_branch_pattern` | `contract.context["expected_branch_pattern"]` | Branch naming convention to validate |

## Idempotency

Each RRH invocation produces a deterministic idempotency key derived from
`sha256(ticket_id:phase:head_sha)[:16]`. This allows callers to detect duplicate
runs and skip re-validation when the environment has not changed.

## Fallback Mode

When the ONEX runtime nodes from `omnibase_infra >= 0.7.0` are not installed,
the adapter uses a `FallbackNodeClient` that returns a **QUARANTINE** verdict
with a clear message. This ensures pipelines degrade gracefully without hard failures.

## Usage

### From Python (Skill Adapter)

```python
from rrh_adapter import RRHAdapter, RRHGovernance, RRHRunConfig

adapter = RRHAdapter()
result = adapter.run(
    RRHRunConfig(
        repo_path=Path("/path/to/repo"),
        profile_name="ticket-pipeline",
        governance=RRHGovernance(
            ticket_id="OMN-2138",
            evidence_requirements=("tests",),
            interfaces_touched=("ProtocolFoo", "ProtocolBar"),
            deployment_targets=("local",),
        ),
        output_dir=Path("/tmp/rrh-artifacts"),
    )
)
print(result.verdict.status)  # PASS, FAIL, or QUARANTINE
```

### From Hook Adapter (Pipeline Integration)

```python
from rrh_hook_adapter import RRHHookAdapter, PipelinePhase

hook = RRHHookAdapter()
decision = hook.run_preflight(
    phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
    contract=ticket_contract,
    repo_path=Path("/path/to/repo"),
    output_dir=Path("/tmp/rrh-artifacts"),
    head_sha="abc123",
)

if decision.should_block:
    print(f"BLOCKED: {decision.human_summary}")
```

## Architecture

```
Hook Adapter (WHEN)          Skill Adapter (HOW)          ONEX Nodes
rrh_hook_adapter.py          rrh_adapter.py               omnibase_infra
                                                          (or FallbackNodeClient)
+-------------------+        +------------------+
| PipelinePhase     | -----> | RRHAdapter.run() | ------> A1: collect_environment()
| ModelTicketContract|        |   config:        |         A2: validate()
| -> profile        |        |   RRHRunConfig   |         A3: store_result()
| -> governance     |        +------------------+
+-------------------+               |
       |                            v
       v                    ContractRRHResult
  RRHDecision                  (verdict, checks, duration)
  (verdict, should_block,
   human_summary, idem_key)
```

## Headless Usage

RRH runs without an interactive Claude Code session when invoked from CLI automation,
Slack bots, or webhook handlers. The skill itself is invoked by `ticket-pipeline`; you
rarely need to call it directly, but the headless setup requirements are the same.

### Required environment variables

| Variable | Purpose | Notes |
|----------|---------|-------|
| `ONEX_RUN_ID` | Unique run identifier for correlation | **Mandatory** — written to every RRH artifact for audit trail |
| `ONEX_UNSAFE_ALLOW_EDITS` | Permit file writes for artifact output | Set to `1` when RRH must write JSON artifacts |
| `ANTHROPIC_API_KEY` | Claude API key | Required for `claude -p` |

```bash
export ONEX_RUN_ID="rrh-$(date +%s)-OMN-1234"
export ONEX_UNSAFE_ALLOW_EDITS=1

claude -p "Invoke the rrh skill for OMN-1234" \
  --allowedTools "Bash,Read,Write,mcp__linear-server__get_issue"
```

### Authentication in headless mode

`ONEX_RUN_ID` is mandatory and written into every RRH artifact (`ContractRRHResult.run_id`).
This is the primary correlation key for the audit trail stored under
`~/.claude/rrh-artifacts/{ticket_id}/`.

The RRH nodes run locally (no network auth required beyond what `omnibase_infra` nodes need).
When the ONEX runtime nodes are not installed, the adapter falls back to QUARANTINE mode and
emits a clear message — no credentials are needed for fallback mode.

### Resume after interruption

RRH uses idempotency keys derived from `sha256(ticket_id:phase:head_sha)[:16]`. If the same
environment is detected on a subsequent run, RRH skips re-validation and returns the cached
result. This means interrupted `claude -p` sessions that re-invoke RRH will not duplicate
audit artifacts.

## See Also

- `ticket-pipeline` skill (primary consumer of RRH)
- `ContractRRHResult` in `omnibase_spi.contracts.pipeline`
- `ContractVerdict` in `omnibase_spi.contracts.shared`
- `ModelTicketContract` in `omnibase_core.models.ticket`
