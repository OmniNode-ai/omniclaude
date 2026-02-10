# FK Scan Results — omniclaude

**Ticket**: OMN-2068 (slice of OMN-2054)
**Date**: 2026-02-10
**Repo**: omniclaude
**Verdict**: All REFERENCES are intra-service. Zero cross-service FK violations.

---

## Scope

Scanned all SQL files that define or alter schema:

| Category | Files Scanned | FK Constraints Found |
|----------|--------------|---------------------|
| Active schema (`scripts/init-db.sh`) | 1 | 1 |
| Active migrations (`sql/migrations/`) | 3 (+ 3 down) | 0 |
| Archived migrations (`_archive/`) | 30+ | 30+ (all intra-service) |
| Python ORM models (`src/`) | all `.py` | 0 |

---

## Active FK Constraints

### 1. `agent_manifest_injections.routing_decision_id`

| Field | Value |
|-------|-------|
| Source table | `agent_manifest_injections` |
| Source column | `routing_decision_id` |
| Target table | `agent_routing_decisions` |
| Target column | `id` |
| Defined in | `scripts/init-db.sh:77` |
| Cascade behavior | None (default: NO ACTION) |
| Cross-service? | **No** — both tables defined in same `init-db.sh` |

```sql
routing_decision_id UUID REFERENCES agent_routing_decisions(id),
```

This is the **only active FK constraint** in the omniclaude schema. Both the source and target tables are created in the same `scripts/init-db.sh` script and are fully owned by omniclaude.

---

## Active Migrations — Zero FKs

| Migration | Tables/Columns | FK Constraints |
|-----------|---------------|----------------|
| `sql/migrations/001_add_project_context_to_observability_tables.sql` | ALTER TABLE (5 tables) + view | 0 |
| `sql/migrations/002_create_learned_patterns.sql` | CREATE TABLE `learned_patterns` (includes `updated_at` trigger consolidated from deleted `migrations/001_create_learned_patterns_table.sql`) | 0 |
| `sql/migrations/003_add_evidence_tier.sql` | ALTER TABLE `learned_patterns` | 0 |

All active migrations use only self-contained tables with no foreign key references.

---

## Archived Migrations — All Intra-Service

All FK constraints in `_archive/` reference tables that are also defined within omniclaude's own migration files:

| Archived File | FK Target Table | Owner |
|--------------|-----------------|-------|
| `001_debug_loop_core_schema.sql` | `debug_execution_attempts` | omniclaude |
| `005_debug_state_management.sql` | `debug_state_snapshots`, `debug_error_events`, `debug_success_events`, `debug_workflow_steps`, `agent_transformation_events` | omniclaude |
| `002_create_agent_transformation_events.sql` | `agent_definitions`, `agent_transformation_events` (self-ref) | omniclaude |
| `012_agent_complete_traceability.sql` | `agent_manifest_injections`, `agent_prompts` | omniclaude |
| `008_agent_manifest_traceability.sql` | `agent_routing_decisions` | omniclaude |
| `003_code_generation.sql` | `generation_sessions` | omniclaude |
| `001_core.sql` | `model_price_catalog`, `debug_transform_functions`, `error_events`, `clarification_tickets` | omniclaude |
| `004_pattern_quality_usage.sql` | `pattern_lineage_nodes` | omniclaude |
| `013_rollback_pattern_quality_fk.sql` | `pattern_lineage_nodes` | omniclaude |
| `001_create_claude_code_versions.sql` | `claude_code_versions` | omniclaude |

Every FK target table is created within omniclaude's own migration files. No references to tables owned by other services (omniarchon, omnibase_core, omninode_bridge, etc.).

---

## Logical Joins (No FK Constraint)

The `agent_activity_realtime` view in `sql/migrations/001_add_project_context_to_observability_tables.sql` joins:

```sql
FROM agent_execution_logs e
LEFT JOIN agent_actions a ON e.correlation_id = a.correlation_id
```

This is a logical join on `correlation_id` (not enforced by FK constraint). Both tables are owned by omniclaude.

---

## Cross-Service FK Violations

**None found.**

---

## Resolution Plans

No resolution plans needed — all FK constraints are intra-service.

---

## Tables Owned by omniclaude

For reference, these are the tables defined in the active schema (`scripts/init-db.sh`):

1. `agent_routing_decisions`
2. `agent_manifest_injections`
3. `agent_execution_logs`
4. `agent_transformation_events`
5. `router_performance_metrics`
6. `agent_actions`

Plus from active migrations:

7. `learned_patterns`

And the view:

8. `agent_activity_realtime` (view)
