---
description: Unified platform readiness gate — aggregates 7 verification dimensions into a tri-state (PASS/WARN/FAIL) report with freshness-aware semantics and valid-zero vs broken-zero distinction. Designed for stakeholder go/no-go visibility.
mode: full
version: "1.0.0"
level: advanced
debug: false
category: verification
tags: [readiness, gate, verification, sweep, stakeholder]
author: omninode
composable: true
args:
  - name: --json
    description: "Output raw JSON instead of markdown table (default: false)"
    required: false
  - name: --dimension
    description: "Check a single dimension only (e.g., --dimension contract_completeness)"
    required: false
---

# Platform Readiness Gate

**Skill ID**: `onex:platform_readiness`

## Purpose

Thin skill surface that dispatches to the `node_platform_readiness` node in
omnimarket via `onex run`. The node collects verification results from multiple
subsystems and presents a single go/no-go readiness assessment. The gate is only
as honest as the maturity and freshness of each underlying signal.

## Announce

"I'm running the platform readiness gate to assess overall system health across 7 verification dimensions."

## Usage

/platform_readiness
/platform_readiness --json
/platform_readiness --dimension golden_chain_health

## Tri-State Semantics

Each dimension reports one of:
- **PASS**: Dimension is healthy, data is fresh
- **WARN**: Dimension is degraded or data is stale (>24h)
- **FAIL**: Dimension is broken, data is missing (>72h), or mock data detected

## Freshness Rules

Dimensions backed by sweep results enforce freshness windows:
- Result < 24h old: use actual status
- Result 24h-72h old: automatic WARN (stale data), regardless of actual status
- Result > 72h old or missing: automatic FAIL (data too old to trust)

## Valid-Zero vs Broken-Zero

The gate distinguishes:
- **Valid zero**: No recent activity (acceptable, e.g., no sessions = cost is zero)
- **Broken zero**: Pipeline exists but isn't producing data despite active sessions
- **Null/missing**: Pipeline doesn't exist yet (WARN or FAIL by criticality)
- **Mock**: Hardcoded/fake data detected (always FAIL)

## Readiness Dimensions

| # | Dimension | Source | Critical |
|---|-----------|--------|----------|
| 1 | Contract completeness | `contracts/*.yaml` across repos | Yes |
| 2 | Golden chain health | Last `/golden_chain_sweep` result | Yes |
| 3 | Data flow health | Last `/data_flow_sweep` result | No |
| 4 | Runtime wiring | Last `/runtime_sweep` result | No |
| 5 | Dashboard data | `curl /api/*` endpoints on omnidash | No |
| 6 | Cost measurement | `/api/costs/*` + `/api/savings/*` | No |
| 7 | CI health | `gh workflow` status across repos | Yes |

**Critical dimensions**: FAIL blocks overall PASS even if all other dimensions pass.

## Overall Status

- All PASS: overall **PASS**
- Any WARN, no FAIL: overall **WARN** (with degraded dimensions listed)
- Any FAIL: overall **FAIL** (with blockers listed)

## Output Format

### Markdown (default)

```markdown
# Platform Readiness Report -- YYYY-MM-DD

## Overall: PASS / WARN / FAIL

| Dimension | Status | Freshness | Details |
|-----------|--------|-----------|---------|
| Contract completeness | PASS | current | 7/7 contracts complete |
| Golden chain health | PASS | 2h ago | 5/5 chains verified |
| Data flow health | WARN | 26h ago (stale) | Last sweep passed but data is stale |
| Runtime wiring | PASS | 4h ago | 0 unwired handlers |
| Dashboard data | PASS | current | All endpoints return real data |
| Cost measurement | PASS | current | $0.00 (valid -- no sessions in window) |
| CI health | FAIL | current | omnibase_infra: 2 failing workflows |

## Blockers
- CI health: omnibase_infra has 2 failing workflows (test-unit, lint)

## Degraded
- Data flow health: Last sweep result is 26h old (stale)

## Readiness Decision
FAIL -- 1 critical blocker must be resolved before go/no-go.
```

### JSON (--json)

```json
{
  "timestamp": "2026-04-03T12:00:00Z",
  "overall": "FAIL",
  "dimensions": [
    {
      "name": "contract_completeness",
      "status": "PASS",
      "critical": true,
      "freshness": "current",
      "details": "7/7 contracts complete"
    }
  ],
  "blockers": ["CI health: omnibase_infra has 2 failing workflows"],
  "degraded": ["Data flow health: stale (26h)"]
}
```

## Implementation

1. Run the platform readiness node:
   ```bash
   onex run node_platform_readiness --output-format json
   ```
2. Read the generated artifact:
   ```bash
   cat .onex_state/readiness/latest.yaml
   ```
3. Display dimensions as a structured table with status indicators.
4. If any dimension is FAIL: surface actionable_items for that dimension.
5. If overall status is PASS: confirm platform is ready for overnight autonomy.

## Architecture

```
SKILL.md   -> descriptive documentation (this file)
prompt.md  -> execution instructions (parse args -> onex run dispatch -> render results)
node       -> omnimarket/src/omnimarket/nodes/node_platform_readiness/ (business logic)
contract   -> node_platform_readiness/contract.yaml (inputs/outputs/topics)
```

This skill is a **thin wrapper** — it parses arguments, dispatches to the omnimarket
node via `onex run node_platform_readiness`, and renders results. All verification
logic lives in the node handler.

## Integration Points

- **close-out**: Can be invoked as final gate check in close-out pipeline
- **data_flow_sweep**: Provides data flow health dimension
- **golden_chain_sweep**: Provides golden chain health dimension
- **runtime_sweep**: Provides runtime wiring dimension
- **system_status**: Complementary -- system_status is detailed diagnostics, readiness gate is aggregated go/no-go
