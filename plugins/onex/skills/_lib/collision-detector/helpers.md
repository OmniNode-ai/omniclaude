# Collision Detector Helpers

## Purpose

Before an epic dispatches multiple tickets in parallel, detect which tickets are likely
to touch overlapping file paths. Cluster overlapping tickets and serialize them; dispatch
independent clusters in parallel.

## Collision Detection Logic

### Input
- `tickets`: list of ticket IDs (Linear)
- `epic_id`: the parent epic
- For each ticket: predicted surfaces (from TCB if available, otherwise from ticket title/description)

### Predicted Surface Estimation

If TCB is available for a ticket: use `suggested_entrypoints[*].ref` (file paths).

If TCB is NOT available, estimate surfaces from ticket title + description using these rules:
1. Extract explicit file paths if mentioned (e.g., `src/omnibase_core/models/foo.py`)
2. Extract module names (e.g., "routing", "auth", "schema") → map to top-level directories
3. Extract repo names → use as high-level collision boundary (same repo = potential collision)
4. If no signals: assign to "unknown" cluster (serialize with all other unknowns)

### Module → Directory Mapping (omninode platform)
```
routing      → src/*/routing/
auth         → src/*/auth/
schema       → src/*/models/ or src/*/schemas/
migration    → src/*/migrations/  ← HIGH COLLISION RISK: always serialize
contract     → src/*/contracts/ or contract.yaml files
config       → src/*/config/ or contract_config.yaml files
kafka/event  → src/*/producers/ or src/*/consumers/ or topics.yaml
```

### Collision Sets

Two tickets collide if:
- They predict changes to the same file path (exact match)
- They predict changes to the same directory (prefix match at depth ≤ 3)
- Either ticket touches `migrations/` (always collides with any other migration ticket)
- Both tickets are in the same repo with no TCB (unknown-cluster collision)

### Output

```python
CollisionSet = {
    "tickets": ["OMN-001", "OMN-002"],
    "reason": "Both touch src/omnibase_core/models/routing/",
    "severity": "exact_file | directory | migration | unknown"
}

DetectionResult = {
    "collision_sets": [CollisionSet, ...],    # groups that must serialize
    "independent": ["OMN-003", "OMN-004"],    # safe to parallelize
    "serialization_order": [                   # recommended execution order within collision sets
        ["OMN-001", "OMN-002"],               # execute OMN-001, then OMN-002
        ["OMN-003"]                            # independent
    ]
}
```

### `detect_collisions(tickets, epic_id, tcb_dir="$ONEX_STATE_DIR/tcb/")` — Procedure

1. For each ticket, load TCB if it exists at `{tcb_dir}/{ticket_id}/bundle.json`
2. Extract predicted surfaces (entrypoint file refs)
3. If no TCB: estimate surfaces from ticket title/description using rules above
4. Build surface index: `{surface_path: [ticket_ids]}`
5. Find all surfaces with more than 1 ticket ID → these are collisions
6. Build collision sets (union-find: merge overlapping collision groups)
7. Remaining tickets with no collisions → `independent` list
8. Emit `DetectionResult`

Write result to `$ONEX_STATE_DIR/epics/{epic_id}/collision_report.json`.

### Serialization Strategy

Within a collision set:
- If one ticket is a dependency of another (detectable by Linear `blockedBy`): put dependency first
- If both touch migrations: put schema-first ticket first (title contains "schema", "model", "migration")
- Otherwise: sort by priority (urgent first), then by ticket ID (lower = older = likely foundational)

## Usage in epic-team

```markdown
@_lib/collision-detector/helpers.md

Before dispatching tickets:
1. Call detect_collisions(ticket_ids, epic_id)
2. Log DetectionResult to epic state at $ONEX_STATE_DIR/epics/{epic_id}/collision_report.json
3. For each collision set: dispatch tickets sequentially (wait for previous to reach create_pr before starting next)
4. For independent tickets: dispatch all in parallel immediately
```
