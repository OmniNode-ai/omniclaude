# FK Scan Results — omniclaude

**Ticket**: OMN-2068 (slice of OMN-2054)
**Date**: 2026-02-26
**Repo**: omniclaude
**Verdict**: All REFERENCES are intra-service. Zero cross-service FK violations.

---

## Scope

Scanned all SQL and Python files that define or alter schema:

| Category | Files Scanned | FK Constraints Found |
|----------|--------------|---------------------|
| Active migrations (`sql/migrations/`) | 1 (+ 1 down) | 2 |
| Active schema (`sql/schema/`) | 1 | 0 |
| Reference DDL — pending freeze lift (`docs/db/`) | 2 (+ 1 down) | 1 |
| Python trace schema — pending freeze lift (`src/omniclaude/trace/db_schema.py`) | 1 | 7 |
| Python ORM models (`src/`) | all `.py` | 0 |

**Total FK constraints**: 10
**Cross-service FKs**: 0

---

## Active FK Constraints

### `sql/migrations/001_create_claude_session_tables.sql`

Two FK constraints, both intra-service:

#### 1. `claude_session_prompts.snapshot_id`

| Field | Value |
|-------|-------|
| Source table | `claude_session_prompts` |
| Source column | `snapshot_id` |
| Target table | `claude_session_snapshots` |
| Target column | `snapshot_id` |
| Defined in | `sql/migrations/001_create_claude_session_tables.sql:75` |
| Cascade behavior | `ON DELETE CASCADE` |
| Cross-service? | **No** — both tables defined in the same migration file |

```sql
snapshot_id UUID NOT NULL REFERENCES claude_session_snapshots(snapshot_id) ON DELETE CASCADE,
```

#### 2. `claude_session_tools.snapshot_id`

| Field | Value |
|-------|-------|
| Source table | `claude_session_tools` |
| Source column | `snapshot_id` |
| Target table | `claude_session_snapshots` |
| Target column | `snapshot_id` |
| Defined in | `sql/migrations/001_create_claude_session_tables.sql:95` |
| Cascade behavior | `ON DELETE CASCADE` |
| Cross-service? | **No** — both tables defined in the same migration file |

```sql
snapshot_id UUID NOT NULL REFERENCES claude_session_snapshots(snapshot_id) ON DELETE CASCADE,
```

---

## Active Schema — Zero FKs

### `sql/schema/quirk_stage_tables.sql`

| Table | FK Constraints |
|-------|---------------|
| `quirk_stage_config` | 0 |
| `quirk_stage_audit` | 0 |

No FK constraints. `quirk_type` is referenced as a plain TEXT column; no enforced join between the two tables.

---

## Pending DDL — Blocked by Migration Freeze (OMN-2055)

These files contain FK constraints that will become active once the migration freeze lifts.
They are in reference paths (`docs/db/` and `src/`) — not yet applied to the database.

### `docs/db/002_create_quirk_tables.sql`

#### 3. `quirk_findings.signal_id`

| Field | Value |
|-------|-------|
| Source table | `quirk_findings` |
| Source column | `signal_id` |
| Target table | `quirk_signals` |
| Target column | `id` |
| Defined in | `docs/db/002_create_quirk_tables.sql:80–81` |
| Cascade behavior | `ON DELETE CASCADE` |
| Cross-service? | **No** — both tables defined in the same file |

```sql
signal_id UUID NOT NULL
    REFERENCES quirk_signals (id) ON DELETE CASCADE,
```

### `src/omniclaude/trace/db_schema.py`

Seven FK constraints, all intra-service:

#### 4. `change_frames.parent_frame_id` (self-reference)

| Field | Value |
|-------|-------|
| Source table | `change_frames` |
| Source column | `parent_frame_id` |
| Target table | `change_frames` |
| Target column | `frame_id` |
| Defined in | `src/omniclaude/trace/db_schema.py:45` |
| Cascade behavior | Default (NO ACTION) |
| Cross-service? | **No** — self-reference; forms parent-child DAG within one table |

```sql
parent_frame_id UUID REFERENCES change_frames(frame_id),
```

#### 5. `change_frames.failure_signature_id`

| Field | Value |
|-------|-------|
| Source table | `change_frames` |
| Source column | `failure_signature_id` |
| Target table | `failure_signatures` |
| Target column | `signature_id` |
| Defined in | `src/omniclaude/trace/db_schema.py:53` |
| Cascade behavior | Default (NO ACTION) |
| Cross-service? | **No** — both tables defined in the same file |

```sql
failure_signature_id TEXT REFERENCES failure_signatures(signature_id),
```

#### 6. `frame_pr_association.frame_id`

| Field | Value |
|-------|-------|
| Source table | `frame_pr_association` |
| Source column | `frame_id` |
| Target table | `change_frames` |
| Target column | `frame_id` |
| Defined in | `src/omniclaude/trace/db_schema.py:77` |
| Cascade behavior | Default (NO ACTION) |
| Cross-service? | **No** — both tables defined in the same file |

```sql
frame_id UUID REFERENCES change_frames(frame_id),
```

#### 7. `frame_pr_association.pr_id`

| Field | Value |
|-------|-------|
| Source table | `frame_pr_association` |
| Source column | `pr_id` |
| Target table | `pr_envelopes` |
| Target column | `pr_id` |
| Defined in | `src/omniclaude/trace/db_schema.py:78` |
| Cascade behavior | Default (NO ACTION) |
| Cross-service? | **No** — both tables defined in the same file |

```sql
pr_id UUID REFERENCES pr_envelopes(pr_id),
```

#### 8. `fix_transitions.failure_signature_id`

| Field | Value |
|-------|-------|
| Source table | `fix_transitions` |
| Source column | `failure_signature_id` |
| Target table | `failure_signatures` |
| Target column | `signature_id` |
| Defined in | `src/omniclaude/trace/db_schema.py:89` |
| Cascade behavior | Default (NO ACTION) |
| Cross-service? | **No** — both tables defined in the same file |

```sql
failure_signature_id TEXT REFERENCES failure_signatures(signature_id),
```

#### 9. `fix_transitions.initial_frame_id`

| Field | Value |
|-------|-------|
| Source table | `fix_transitions` |
| Source column | `initial_frame_id` |
| Target table | `change_frames` |
| Target column | `frame_id` |
| Defined in | `src/omniclaude/trace/db_schema.py:90` |
| Cascade behavior | Default (NO ACTION) |
| Cross-service? | **No** — both tables defined in the same file |

```sql
initial_frame_id UUID NOT NULL REFERENCES change_frames(frame_id),
```

#### 10. `fix_transitions.success_frame_id`

| Field | Value |
|-------|-------|
| Source table | `fix_transitions` |
| Source column | `success_frame_id` |
| Target table | `change_frames` |
| Target column | `frame_id` |
| Defined in | `src/omniclaude/trace/db_schema.py:91` |
| Cascade behavior | Default (NO ACTION) |
| Cross-service? | **No** — both tables defined in the same file |

```sql
success_frame_id UUID NOT NULL REFERENCES change_frames(frame_id),
```

---

## Cross-Service FK Violations

**None found.**

---

## Logical Joins (No FK Constraint — Intentional)

The following columns reference data from other services by **value** (TEXT/UUID identifiers)
rather than an enforced FK constraint. This is the correct pattern for cross-service references
— FK constraints would couple schemas across service boundaries.

| Table | Column | Logically References | Service | Intentional? |
|-------|--------|---------------------|---------|--------------|
| `quirk_signals` | `session_id` TEXT | Claude session ID | omniclaude (session lifecycle) | Yes — no FK needed across lifecycle layers |
| `skill_execution_logs` | `session_id` TEXT | Claude session ID | omniclaude (session lifecycle) | Yes — nullable, Kafka-delivered |
| `change_frames` | `agent_id` TEXT | Agent identifier | N/A (free text) | Yes — immutable event field |
| `change_frames` | `repo` TEXT | Repository name | N/A (free text) | Yes — immutable event field |
| `pr_envelopes` | `repo` TEXT | Repository name | N/A (free text) | Yes — immutable event field |

No FK constraints are needed or appropriate for these cross-service value references.

---

## Resolution Plans

No resolution plans needed — all FK constraints are intra-service.

---

## Tables Owned by omniclaude

### Active (applied to `omniclaude` database)

| Table | Defined In |
|-------|-----------|
| `claude_session_snapshots` | `sql/migrations/001_create_claude_session_tables.sql` |
| `claude_session_prompts` | `sql/migrations/001_create_claude_session_tables.sql` |
| `claude_session_tools` | `sql/migrations/001_create_claude_session_tables.sql` |
| `claude_session_event_idempotency` | `sql/migrations/001_create_claude_session_tables.sql` |
| `quirk_stage_config` | `sql/schema/quirk_stage_tables.sql` |
| `quirk_stage_audit` | `sql/schema/quirk_stage_tables.sql` |

### Pending (blocked by migration freeze OMN-2055)

| Table | Defined In | Unblocked By |
|-------|-----------|--------------|
| `quirk_signals` | `docs/db/002_create_quirk_tables.sql` | OMN-2055 freeze lift |
| `quirk_findings` | `docs/db/002_create_quirk_tables.sql` | OMN-2055 freeze lift |
| `skill_execution_logs` | `docs/db/003_create_skill_execution_logs.sql` | OMN-2055 freeze lift |
| `failure_signatures` | `src/omniclaude/trace/db_schema.py` | OMN-2055 freeze lift |
| `change_frames` | `src/omniclaude/trace/db_schema.py` | OMN-2055 freeze lift |
| `pr_envelopes` | `src/omniclaude/trace/db_schema.py` | OMN-2055 freeze lift |
| `frame_pr_association` | `src/omniclaude/trace/db_schema.py` | OMN-2055 freeze lift |
| `fix_transitions` | `src/omniclaude/trace/db_schema.py` | OMN-2055 freeze lift |

---

## Scan History

| Date | Scope | FK Count | Verdict |
|------|-------|----------|---------|
| 2026-02-10 | `scripts/init-db.sh` + `sql/migrations/` (pre-session-table era) | 1 | Clean |
| 2026-02-26 | All schema files: `sql/migrations/`, `sql/schema/`, `docs/db/`, `src/omniclaude/trace/` | 10 | Clean |
