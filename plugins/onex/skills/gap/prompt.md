<!-- routing-enforced: dispatches to node_gap_compute (stub). functionally-complete requires real node implementation. -->

# /onex:gap — dispatch-only shim

Dispatch to `node_gap_compute` in omnimarket. Do not reimplement gap analysis inline.

No inline orchestration, no LLM reasoning, no direct Kafka publish, no
`gh` subprocess fallback — the node owns the full pipeline.

## Announce

Say: "I'm using the gap skill to dispatch node_gap_compute."

## Parse `$ARGUMENTS`

First positional argument is the subcommand: `detect`, `fix`, `cycle`, or `reconcile`.

All remaining flags are passed through to the node.

### Arguments

| Argument | Description |
|----------|-------------|
| `subcommand` | Mode: detect (audit), fix (auto-fix loop), cycle (detect->fix->verify), or reconcile |
| `--epic` | Linear epic ID to audit (detect mode) |
| `--report` | Path to gap-analysis report (fix mode) |
| `--max-iterations` | Maximum fix iterations (cycle mode, default: 3) |
| `--dry-run` | Preview without making changes |
| `--repo` | Limit audit to a specific repo name (detect mode) |
| `--since-days` | Look back N days for closed Epics (detect mode, default 30) |
| `--severity-threshold` | Minimum severity to report: WARNING \| CRITICAL (detect mode, default WARNING) |
| `--max-findings` | Maximum total findings to emit (detect mode, default 200) |
| `--max-best-effort` | Maximum BEST_EFFORT findings to emit (detect mode, default 50) |
| `--output` | Output format: json \| md (detect mode, default md) |
| `--ticket` | Single finding via Linear ticket ID containing a gap-analysis marker block (fix mode) |
| `--latest` | Follow $ONEX_STATE_DIR/gap-analysis/latest/ symlink (fix mode) |
| `--mode` | Execution mode: ticket-pipeline \| ticket-work \| implement-only (fix mode) |
| `--choose` | Provide decisions for gated findings e.g. GAP-b7e2d5f8=A (fix mode) |
| `--force-decide` | Re-open previously decided findings in decisions.json (fix mode) |
| `--resume` | Path to a prior gap-cycle summary.json to resume from (cycle mode) |
| `--audit` | Record that pipeline-audit was requested (cycle mode, v0.1 deferred) |
| `--no-fix` | Skip gap-fix phase (cycle mode) |
| `--verify` | Run golden-path-validate after fix (cycle mode) |
| `--auto-only` | Skip GATE findings in fix phase (cycle mode) |
| `--skip-infra-probes` | Skip infrastructure probes that require live services |
| `--include-auth-probes` | Include auth_config probes (disabled by default) |
| `--lag-threshold` | Consumer group lag threshold for projection_lag probe (default: 10000) |

## Dispatch

```bash
onex run node_gap_compute -- $PARSED_ARGS
```

Surface the JSON output from stdout. The node produces a `ModelSkillResult` with `status`, `run_id`, and `message`.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. If dispatch cannot execute, report the error and stop.

Never re-implement gap analysis orchestration inline. If the node is unavailable, stop — do not fall back to inline probing, direct Kafka publish, or prose orchestration.

---

## Probe Reference (node_gap_compute contract)

The node runs 12 probe categories against each repo in scope. This section documents the probe
contract so routing validation and tests can verify shim/node alignment without re-implementing
logic here.

### Probe Catalog

| Probe | boundary_kind | Category | Auto-fix? |
|-------|---------------|----------|-----------|
| 2.1 | kafka_topic | CONTRACT_DRIFT | NO (GATE) |
| 2.2 | model_field | CONTRACT_DRIFT | NO (GATE) |
| 2.3 | fk_reference | CONTRACT_DRIFT | NO (GATE) |
| 2.4 | api_contract | CONTRACT_DRIFT | NO (GATE) |
| 2.5 | db_boundary | ARCHITECTURE_VIOLATION | NO (GATE) |
| 2.6 | topic_registry | CONTRACT_DRIFT | LOCAL-ONLY |
| 2.7 | env_activation | ARCHITECTURE_VIOLATION | NO (GATE) |
| 2.8 | projection_lag | ARCHITECTURE_VIOLATION | NO (GATE) |
| 2.9 | auth_config | CONTRACT_DRIFT | NO (GATE) |
| 2.10 | migration_parity | ARCHITECTURE_VIOLATION | NO (GATE) |
| 2.11 | legacy_config | ARCHITECTURE_VIOLATION | YES (search-replace) |
| 2.12 | branch_protection | INTEGRATION_HEALTH | YES (gh api) |

### Probe 2.12: Branch Protection Drift

**Category**: `INTEGRATION_HEALTH` | **boundary_kind**: `branch_protection`
**rule_name**: `required_check_name_stale`

Queries GitHub branch protection required status checks and compares against actual CI job
names from the most recent PR. Any required check name not present in actual checks is drift.

Evidence method: `gh api` — queries `repos/{ORG}/{repo}/branches/main/protection/required_status_checks`.

**Proof blob schema**:
```json
{
  "repo": "omniweb",
  "branch": "main",
  "required_checks": ["Quality Gate", "Tests Gate"],
  "actual_checks": ["Quality Gate"],
  "stale_checks": ["Tests Gate"],
  "valid_checks": ["Quality Gate"]
}
```

**Auto-fix**: removes stale required check names from `required_status_checks` via:
```bash
gh api -X PATCH repos/{ORG}/{repo}/branches/main/protection/required_status_checks \
  --input - <<< '{"strict": true, "contexts": [<valid_checks>]}'
```

Only removes stale checks; keeps all valid checks intact. Gate if no valid checks remain.

### Auto-Dispatch Table

| `boundary_kind` | `rule_name` | `dispatch_class` |
|-----------------|-------------|-----------------|
| `kafka_topic` | `topic_name_mismatch` | `AUTO` |
| `db_url_drift` | `legacy_db_name_in_tests` | `AUTO` |
| `db_url_drift` | `legacy_env_var` | `AUTO` |
| `legacy_config` | `legacy_denylist_match` | `AUTO` |
| `branch_protection` | `required_check_name_stale` | `AUTO` (gh api; GATE if no valid checks remain) |
| `kafka_topic` | `producer_only_no_consumer` | `GATE` |
| `api_contract` | `missing_openapi` | `GATE` |
| All other cases | — | `GATE` |

The node executes 12 probe categories in Phase 2 of its detect pipeline.
