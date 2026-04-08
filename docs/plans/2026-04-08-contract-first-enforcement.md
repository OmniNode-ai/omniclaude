# Projection-First Contract Enforcement

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan phase-by-phase.

**Goal:** Eliminate all hardcoded topic strings, table names, and endpoints from handler code. Every runtime dependency must be declared in contract.yaml and read from the contract at runtime. The auto-wiring infrastructure already exists — the contracts are incomplete.

**Architecture:** Add `db_tables` to the contract schema (omnibase_core). Update all 6 projection handler contracts to declare their tables and topics. Refactor handlers to read from contract instead of module-level constants. Fix the latency-breakdown schema mismatch. Add a CI lint that rejects hardcoded `onex.*` strings outside contract.yaml.
 here's the full plan
**Tech Stack:** Python 3.12, Pydantic v2, omnibase_core contracts, omnibase_infra auto-wiring, omnimarket projection handlers, omnidash TypeScript

---

## Enforcement Boundary for This Phase

- This phase enforces contract-first declaration of event topics and database tables for projection nodes.
- Runtime validation is warning-based in this phase and does not yet block wiring for missing tables.
- `db_tables` declarations describe required tables; handlers resolve them by semantic role rather than list order.
- CI lint prevents most direct `onex.*` topic literals in production Python, but is a guardrail rather than complete semantic enforcement.
- Endpoint declaration and broader runtime dependency modeling are out of scope for this phase.
- Phase 2 (future) will add strict blocking enforcement once all contracts are complete and validated in production.

---

## Known Types Inventory

> Types discovered in the repository relevant to this plan.

- `ModelEventBusSubcontract` — `omnibase_core/src/omnibase_core/models/contracts/subcontracts/model_event_bus_subcontract.py:38` — publish/subscribe topic declarations with field_validator
- `ModelTopicMeta` — `omnibase_core/src/omnibase_core/models/contracts/subcontracts/model_event_bus_subcontract.py` — per-topic metadata (retention_ms, partition_count)
- `ModelDbOwnershipMetadata` — `omnibase_core/src/omnibase_core/models/contracts/model_db_ownership_metadata.py:21` — owner_service + schema_version assertion
- `ModelDbIoConfig` — `omnibase_core/src/omnibase_core/models/contracts/subcontracts/model_db_io_config.py` — DB I/O config subcontract
- `TopicProvisioner` — `omnibase_infra/src/omnibase_infra/event_bus/service_topic_manager.py:47` — contract-driven topic auto-creation
- `wire_from_manifest` — `omnibase_infra/src/omnibase_infra/runtime/auto_wiring/handler_wiring.py:197` — reads subscribe_topics from contracts and wires consumers
- `ModelDiscoveredContract` — `omnibase_infra/src/omnibase_infra/runtime/auto_wiring/models/` — parsed contract for wiring
- `ModelAutoWiringManifest` — `omnibase_infra/src/omnibase_infra/runtime/auto_wiring/models/` — collection of discovered contracts

## Runtime State Inventory

### Projection Tables (omnidash_analytics)

**Source:** `omnidash/migrations/`

| Table | Migration | Status |
|-------|-----------|--------|
| `delegation_events` | `0007_delegation_events.sql` | 649 rows, latest 2026-04-08 |
| `delegation_shadow_comparisons` | (within 0007 or later) | populated |
| `llm_cost_aggregates` | `0003_llm_cost_aggregates.sql` | 52 rows |
| `baselines_snapshots` | `0001_omnidash_analytics_read_model.sql` | 5,412 rows |
| `node_service_registry` | `0001_omnidash_analytics_read_model.sql` | 67 rows, STALE (2026-04-03) |
| `savings_estimates` | `0034_savings_estimates.sql` | populated |
| `session_outcomes` | `0021_session_outcomes.sql` | 69 rows |
| `injection_effectiveness` | (within 0001 or later) | 2,070 rows |
| `baselines_comparisons` | (within baselines migration set) | populated — confirmed in handler_baselines.py:34 |
| `baselines_trend` | (within baselines migration set) | populated — confirmed in handler_baselines.py:34 |
| `baselines_breakdown` | (within baselines migration set) | populated (38+ rows) — confirmed in handler_baselines.py:34, data-flow-sweep-20260330.md |

### Hardcoded Topic Constants in Projection Handlers

**Source:** grep of omnimarket/src/ handler files

| Handler | Constant | Value | Line |
|---------|----------|-------|------|
| handler_delegation.py | TOPIC_TASK_DELEGATED | `onex.evt.omniclaude.task-delegated.v1` | 18 |
| handler_delegation.py | TOPIC_SHADOW_COMPARISON | `onex.evt.omniclaude.delegation-shadow-comparison.v1` | 19 |
| handler_llm_cost.py | TOPIC | `onex.evt.omniintelligence.llm-call-completed.v1` | 18 |
| handler_registration.py | TOPIC_INTROSPECTION | `onex.evt.platform.node-introspection.v1` | 17 |
| handler_registration.py | TOPIC_HEARTBEAT | `onex.evt.platform.node-heartbeat.v1` | 18 |
| handler_registration.py | TOPIC_STATE_CHANGE | `onex.evt.platform.node-state-change.v1` | 19 |
| handler_session_outcome.py | TOPIC | `onex.evt.omniclaude.session-outcome.v1` | 17 |
| handler_savings.py | TOPIC | `onex.evt.omnibase-infra.savings-estimated.v1` | 19 |
| handler_baselines.py | (inline) | `onex.evt.omnibase-infra.baselines-computed.v1` | (handler code) |
| handler_build_loop_orchestrator.py | TOPIC_PHASE_TRANSITION | `onex.evt.omnimarket.build-loop-orchestrator-phase-transition.v1` | 73 |
| handler_build_loop_orchestrator.py | TOPIC_COMPLETED | `onex.evt.omnimarket.build-loop-orchestrator-completed.v1` | 75 |

### Latency Breakdown Schema Chain

| Layer | Field | Source |
|-------|-------|--------|
| Python emitter | `correlation_id` (no `prompt_id`) | `omniclaude/plugins/onex/hooks/lib/extraction_event_emitter.py:203` |
| TS interface | `prompt_id` (required) | `omnidash/shared/extraction-types.ts:158` |
| TS guard | `prompt_id \|\| promptId` | `omnidash/shared/extraction-types.ts:237-241` |
| Drizzle column | `prompt_id UUID NOT NULL` | `omnidash/shared/intelligence-schema.ts:571` |

---

## Task 1: Add `db_tables` field to contract subcontract schema

> **R4 FIX**: `model_db_io_config.py` is `ModelDbIOConfig` — a SQL query-templating model for EFFECT nodes with required fields (`operation`, `connection_name`, `query_template`) and `extra="forbid"`. Adding `db_tables` there would break it. The correct target is a **new** subcontract file: `model_db_ownership_subcontract.py`.

**Files:**
- Create: `omnibase_core/src/omnibase_core/models/contracts/subcontracts/model_db_ownership_subcontract.py`
- Modify: `omnibase_core/src/omnibase_core/models/contracts/subcontracts/__init__.py` (export new types)
- Modify: `omnibase_core/src/omnibase_core/models/contracts/__init__.py` (export new types)

**Not reusing `ModelDbOwnershipMetadata` because:** it tracks service-level ownership assertions (one row per service), not per-node table declarations. We need a per-node list of tables the handler reads/writes.

**Not reusing `ModelDbIOConfig` because:** that model handles SQL query execution config for EFFECT nodes (operation, query_template, connection_name) — a different concern entirely.

**Step 1: Write failing test**

```python
# tests/test_db_ownership_subcontract.py
def test_db_tables_field_exists():
    """Contract db_ownership_subcontract must support declaring owned tables with role."""
    from omnibase_core.models.contracts.subcontracts.model_db_ownership_subcontract import (
        ModelDbOwnershipSubcontract, ModelDbTableDeclaration
    )
    config = ModelDbOwnershipSubcontract(
        db_tables=[
            {"name": "delegation_events", "migration": "0007_delegation_events.sql", "access": "write", "role": "events"},
        ]
    )
    assert len(config.db_tables) == 1
    assert config.db_tables[0].name == "delegation_events"
    assert config.db_tables[0].role == "events"

def test_db_tables_role_lookup():
    """Handlers must be able to resolve tables by semantic role."""
    from omnibase_core.models.contracts.subcontracts.model_db_ownership_subcontract import (
        ModelDbOwnershipSubcontract
    )
    config = ModelDbOwnershipSubcontract(
        db_tables=[
            {"name": "delegation_events", "migration": "0007_delegation_events.sql", "access": "write", "role": "events"},
            {"name": "delegation_shadow_comparisons", "migration": "0007_delegation_events.sql", "access": "write", "role": "shadow_comparisons"},
        ]
    )
    by_role = {t.role: t for t in config.db_tables}
    assert by_role["events"].name == "delegation_events"
    assert by_role["shadow_comparisons"].name == "delegation_shadow_comparisons"

def test_db_tables_default_empty():
    from omnibase_core.models.contracts.subcontracts.model_db_ownership_subcontract import (
        ModelDbOwnershipSubcontract
    )
    config = ModelDbOwnershipSubcontract()
    assert config.db_tables == []
```

**Step 2: Run test to verify it fails**

```bash
cd omnibase_core && uv run pytest tests/test_db_ownership_subcontract.py -v
```

**Step 3: Create `model_db_ownership_subcontract.py`**

```python
# omnibase_core/src/omnibase_core/models/contracts/subcontracts/model_db_ownership_subcontract.py
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ModelDbTableDeclaration", "ModelDbOwnershipSubcontract"]

class ModelDbTableDeclaration(BaseModel):
    """Declaration of a DB table owned by this node."""
    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    name: str  # table name in the target database
    migration: str  # migration file that creates this table
    access: Literal["read", "write", "read_write"] = "write"
    database: str = "omnidash_analytics"  # target database name
    role: str  # semantic role for handler lookup (e.g. "events", "shadow_comparisons", "snapshot", "breakdown")

class ModelDbOwnershipSubcontract(BaseModel):
    """Per-node declaration of DB tables owned/accessed by this node."""
    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    db_tables: list[ModelDbTableDeclaration] = Field(default_factory=list)
```

**Step 4: Export from `__init__.py` files**

In `subcontracts/__init__.py`, add:
```python
from .model_db_ownership_subcontract import ModelDbTableDeclaration, ModelDbOwnershipSubcontract
```

In `contracts/__init__.py`, add to `__all__`:
```python
"ModelDbTableDeclaration",
"ModelDbOwnershipSubcontract",
```

**Step 5: Run test to verify pass**

**Step 6: Commit**

```bash
git commit -m "feat(contracts): add ModelDbOwnershipSubcontract with db_tables field"
```

**Acceptance criteria:**
- `ModelDbOwnershipSubcontract` exists at `omnibase_core.models.contracts.subcontracts.model_db_ownership_subcontract`
- `db_tables` field accepts `list[ModelDbTableDeclaration]`, default empty list (backwards compatible)
- `access` field is `Literal["read", "write", "read_write"]` — not bare `str`
- `role` field is `str` — handlers use `{t.role: t for t in db_tables}` to resolve tables by semantic role, never by list index
- `ModelDbIOConfig` is NOT modified (it is a SQL query execution model, not a table declaration model)
- Existing contracts continue to validate

---

## Task 2: Update 6 projection node contracts with `db_tables` and fix hardcoded topics

**Files:**
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_delegation/contract.yaml`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_llm_cost/contract.yaml`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_registration/contract.yaml`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_baselines/contract.yaml`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_savings/contract.yaml`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_session_outcome/contract.yaml`

**Step 1: Read each contract.yaml and add db_tables + verify subscribe_topics**

For each projection node, add a `db_io` section with `db_tables` and ensure `event_bus.subscribe_topics` lists all consumed topics (currently hardcoded in handler code).

Example for `node_projection_delegation/contract.yaml`:
```yaml
db_io:
  db_tables:
    - name: delegation_events
      migration: "0007_delegation_events.sql"
      access: write
      database: omnidash_analytics
      role: events
    - name: delegation_shadow_comparisons
      migration: "0007_delegation_events.sql"
      access: write
      database: omnidash_analytics
      role: shadow_comparisons

event_bus:
  subscribe_topics:
    - onex.evt.omniclaude.task-delegated.v1
    - onex.evt.omniclaude.delegation-shadow-comparison.v1
  publish_topics:
    - onex.evt.omnimarket.projection-delegation-applied.v1
```

**Step 2: Repeat for all 6 nodes with correct table/topic/role mappings**

| Node | Table | Role | Subscribe Topics |
|------|-------|------|-----------------|
| projection_delegation | delegation_events | events | task-delegated.v1, delegation-shadow-comparison.v1 |
| projection_delegation | delegation_shadow_comparisons | shadow_comparisons | (same subscription) |
| projection_llm_cost | llm_cost_aggregates | aggregates | llm-call-completed.v1 |
| projection_registration | node_service_registry | registry | node-introspection.v1, node-heartbeat.v1, node-state-change.v1 |
| projection_baselines | baselines_snapshots | snapshots | baselines-computed.v1 |
| projection_baselines | baselines_comparisons | comparisons | (same subscription) |
| projection_baselines | baselines_trend | trend | (same subscription) |
| projection_baselines | baselines_breakdown | breakdown | (same subscription) |
| projection_savings | savings_estimates | estimates | savings-estimated.v1 |
| projection_session_outcome | session_outcomes | outcomes | session-outcome.v1 |

**Step 3: Run contract validation**

```bash
cd omnimarket && uv run python -c "
from omnibase_core.contracts.contract_loader import load_contract
import pathlib
for node in pathlib.Path('src/omnimarket/nodes').glob('node_projection_*/contract.yaml'):
    c = load_contract(node)
    print(f'{node.parent.name}: {len(c.get(\"db_io\", {}).get(\"db_tables\", []))} tables, {len(c.get(\"event_bus\", {}).get(\"subscribe_topics\", []))} subs')
"
```

> **R4 NOTE**: `load_contract` returns a dict (YAML parsed), not a typed Pydantic object. Access fields via dict notation until a typed contract loader is available for omnimarket nodes.

**Step 4: Commit**

```bash
git commit -m "feat(contracts): declare db_tables and subscribe_topics on all projection nodes"
```

**Acceptance criteria:**
- All 6 projection contracts declare their DB tables with migration references
- All 6 projection contracts declare their subscribe_topics (matching what's currently hardcoded)
- Contract validation passes for all 6

---

## Task 3: Refactor projection handlers to read topics from contract

**Files:**
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_delegation/handlers/handler_delegation.py`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_llm_cost/handlers/handler_llm_cost.py`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_registration/handlers/handler_registration.py`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_session_outcome/handlers/handler_session_outcome.py`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_savings/handlers/handler_savings.py`
- Modify: `omnimarket/src/omnimarket/nodes/node_projection_baselines/handlers/handler_baselines.py`

**Step 1: Write failing test**

```python
def test_handler_reads_topic_from_contract():
    """Handler must not hardcode topic strings."""
    import ast, pathlib
    handler = pathlib.Path("src/omnimarket/nodes/node_projection_delegation/handlers/handler_delegation.py")
    source = handler.read_text()
    # No module-level TOPIC_* = "onex.*" constants allowed
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("TOPIC"):
                    assert False, f"Hardcoded topic constant {target.id} found — must read from contract"
```

**Step 2: Remove hardcoded TOPIC constants from each handler**

Replace:
```python
TOPIC_TASK_DELEGATED = "onex.evt.omniclaude.task-delegated.v1"
```

With contract loading in `__init__` or `handle()`:
```python
from omnibase_core.contracts.contract_loader import load_contract

def __init__(self, contract_path: Path | None = None):
    _path = contract_path or Path(__file__).parent.parent / "contract.yaml"
    self._contract: dict = load_contract(_path)

@property
def subscribe_topics(self) -> list[str]:
    # load_contract returns a dict — access via dict notation
    return self._contract.get("event_bus", {}).get("subscribe_topics", [])
```

**Step 3: Remove hardcoded table names**

Replace:
```python
INSERT INTO delegation_events (...)
```

With contract-sourced table names resolved by semantic role at construction time:
```python
_tables = self._contract.get("db_io", {}).get("db_tables", [])
_by_role = {t["role"]: t["name"] for t in _tables}
self._table_delegation = _by_role["events"]
self._table_shadow = _by_role["shadow_comparisons"]
```

Handlers must resolve tables by `role`, not by list index or by matching against a hardcoded name string.

> **Security note**: Table names sourced from contract YAML are NOT user input, but the name must still be validated against a known-safe allowlist before interpolation into SQL. Use: `assert self._table_delegation in KNOWN_PROJECTION_TABLES` at construction time.

**Step 4: Run ruff + tests**

```bash
cd omnimarket && uv run ruff check src/ && uv run pytest tests/ -x -q
```

**Step 5: Commit**

```bash
git commit -m "refactor(projections): read topics and table names from contract, remove hardcoded constants"
```

**Acceptance criteria:**
- Zero `TOPIC_*` or `TOPIC =` module-level constants in any projection handler
- Zero hardcoded `INSERT INTO <table>` strings — table names come from contract
- All existing tests pass
- `grep -rn 'TOPIC.*=.*"onex\.' src/omnimarket/nodes/node_projection_*` returns zero results
- Handler construction fails with `ValueError` if a declared table `role` is not in `KNOWN_PROJECTION_TABLES` allowlist — the constructor must validate every role returned from `_by_role` against the allowlist before storing the table name; if any role is absent, raise `ValueError(f"Unknown table role {role!r} not in KNOWN_PROJECTION_TABLES")` immediately
- `KNOWN_PROJECTION_TABLES` is defined as a `frozenset` of all valid table names from the Runtime State Inventory above; any table name not in the set causes a `ValueError` at construction, not at query time
- There is NO `next()` fallback or default table name — if the contract does not declare a required role, the handler must fail loudly at construction rather than silently falling back to a hardcoded string

---

## Task 4: Fix latency-breakdown prompt_id schema mismatch

**Approach: Make `prompt_id` optional in the consumer (Approach B)**

The Python emitter at `extraction_event_emitter.py:203` emits `correlation_id` but has no `prompt_id` concept. The emitter cannot produce a `prompt_id` without a schema-breaking change on the Python side. The correct fix is to relax the consumer so it accepts events that lack `prompt_id`, rather than forcing a field into the emitter that doesn't belong there.

**Files:**
- Modify: `omnidash/shared/extraction-types.ts`
- Modify: `omnidash/shared/intelligence-schema.ts`

**Step 1: Make `prompt_id` optional in the TypeScript interface**

In `omnidash/shared/extraction-types.ts:158`, change the `LatencyBreakdownEvent` interface field from:
```typescript
prompt_id: string;
```
to:
```typescript
prompt_id?: string | null;
```

**Step 2: Update the `isLatencyBreakdownEvent` guard**

In `omnidash/shared/extraction-types.ts:237-241`, remove any check that requires `prompt_id` to be present. The guard must pass for events that carry only `correlation_id`. Do not add a `prompt_id || promptId` fallback — simply drop the `prompt_id` requirement from the guard entirely.

**Step 3: Make the DB column nullable**

In `omnidash/shared/intelligence-schema.ts:571`, change the `prompt_id` Drizzle column from:
```typescript
prompt_id: uuid("prompt_id").notNull(),
```
to:
```typescript
prompt_id: uuid("prompt_id"),
```

Generate and apply the migration so the column becomes `UUID NULL`.

**Step 4: Verify events now pass the guard**

After the fix, emit a test latency event and confirm `injection_effectiveness` row count increases within 30 seconds:
```bash
ssh 192.168.86.201 "docker exec omnibase-infra-postgres psql -U postgres -d omnidash_analytics \
  -c \"SELECT COUNT(*) FROM injection_effectiveness WHERE created_at > now() - interval '1 hour'\""
```

**Step 5: Commit**

```bash
git commit -m "fix(latency): make prompt_id optional in consumer — emitter has no prompt_id concept, only correlation_id"
```

**Acceptance criteria:**
- `prompt_id` field in `LatencyBreakdownEvent` interface is `string | null | undefined` (optional)
- `isLatencyBreakdownEvent` guard does NOT check for `prompt_id` presence — events without `prompt_id` pass the guard
- `intelligence-schema.ts` Drizzle column `prompt_id` is nullable (`UUID NULL` — no `notNull()`)
- A migration exists making the DB column nullable; existing rows with `NULL` prompt_id are valid
- New events emitted by the Python emitter (which has no `prompt_id`) pass the guard and are written to `injection_effectiveness`
- `grep "prompt_id" omnidash/shared/extraction-types.ts` shows `prompt_id` as optional in both interface and guard
- `grep "notNull" omnidash/shared/intelligence-schema.ts` does NOT match the `prompt_id` column line

---

## Task 5: Add omnimarket completion topics to omnidash subscription manifest

> **R1 NOTE**: The "31 topics" claim has no verified source. Run Step 1 first to get the actual count before writing acceptance criteria with a specific number.

**Files:**
- Modify: `omnidash/shared/topics.ts` (or create `topics.yaml` if that's the correct pattern)

**Step 1: Enumerate all omnimarket completion events from contracts**

```bash
grep -rn "publish_topics" omnimarket/src/omnimarket/nodes/*/contract.yaml | grep "onex.evt.omnimarket"
```

**Step 2: Add each topic to omnidash's subscription manifest**

For each `onex.evt.omnimarket.*` topic, only subscribe if it meets one of:
- A defined projection handler exists that consumes it
- An explicit observability purpose is documented (e.g. audit trail, debug replay)

Do NOT add topics to a catch-all raw ingestion handler. If a topic has no handler and no documented purpose, leave it out of this phase and note it as a gap.

**Step 3: Map topics to projection handlers**

For each topic added in Step 2:
- Identify the existing projection handler or create a named handler (not a generic pass-through)
- Register the handler in the read-model-consumer's subscription list

**Step 4: Commit**

```bash
git commit -m "feat(omnidash): subscribe to omnimarket completion events with projection handlers"
```

**Acceptance criteria:**
- Run Step 1 grep first; record actual count N
- `grep "omnimarket" omnidash/shared/topics.ts` returns entries only for topics with a defined projection handler or explicit observability purpose
- No catch-all raw ingestion handler subscribes to omnimarket topics unless it is explicitly designated for audit or debug
- Read-model-consumer subscribes to all qualifying omnimarket completion topics
- Events published by omnimarket reach omnidash consumer

---

## Task 6: Add CI lint to reject hardcoded topic strings

**Files:**
- Create: `omnimarket/scripts/lint_no_hardcoded_topics.py`
- Modify: `.github/workflows/ci.yml` (or equivalent CI config)

**Step 1: Write the topic-literal guardrail script**

This script is a line-grep guardrail against `onex.*` topic literals in production Python. Note: AST-based string analysis (e.g. checking only `ast.Constant` nodes in assignments) would be stronger — it could distinguish imports from assignments and skip multiline strings — but line grep is sufficient for the current codebase and avoids false negatives from obfuscated string construction. AST analysis is a recommended future iteration.

```python
#!/usr/bin/env python3
"""Topic-literal guardrail: reject hardcoded onex.* strings in production Python.

Scans *.py files only. contract.yaml is not scanned (not a Python file).
Allowed locations: test files (test_*, conftest), topics.py constants module.
Forbidden: handler_*.py, adapter_*.py, and any other production Python.
"""
import pathlib, sys

ALLOWED_FILES = {"topics.py"}
ALLOWED_PREFIXES = {"test_", "conftest"}

violations = []
for py_file in pathlib.Path("src").rglob("*.py"):
    if any(py_file.name.startswith(p) for p in ALLOWED_PREFIXES):
        continue
    if py_file.name in ALLOWED_FILES:
        continue
    source = py_file.read_text()
    for i, line in enumerate(source.splitlines(), 1):
        if '"onex.' in line or "'onex." in line:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            violations.append(f"{py_file}:{i}: {stripped}")

if violations:
    print(f"ERROR: {len(violations)} hardcoded topic literal(s) found:")
    for v in violations:
        print(f"  {v}")
    sys.exit(1)
print("OK: No hardcoded topic literals found.")
```

**Step 2: Add to CI**

```yaml
- name: Topic-literal guardrail
  run: uv run python scripts/lint_no_hardcoded_topics.py
```

**Step 3: Commit**

```bash
git commit -m "feat(ci): add topic-literal guardrail to reject hardcoded onex.* strings in handler code"
```

**Acceptance criteria:**
- CI fails if any production `*.py` file (except `topics.py`, `test_*`, `conftest*`) contains a hardcoded `"onex.*"` string
- `contract.yaml` files are not scanned (script only scans `*.py`)
- Test files are exempt
- Existing code passes after Task 3 refactor
- A future iteration should replace line grep with AST-based `ast.Constant` node inspection for stronger guarantees

> **Ordering note:** Task 7 must complete before the CI lint step (Step 2 above) is added to the CI workflow. The `build_loop_orchestrator` and `nightly_loop_controller` handlers still contain hardcoded `onex.*` topic strings until Task 7 migrates them to contract-declared topics. Adding the CI lint before Task 7 is complete will cause CI to fail on those files. Add the CI lint step only after Task 7's commit is merged.

---

## Task 7: Fix legacy contract patterns (build_loop_orchestrator, nightly_loop_controller)

**Files:**
- Modify: `omnimarket/src/omnimarket/nodes/node_build_loop_orchestrator/contract.yaml`
- Modify: `omnimarket/src/omnimarket/nodes/node_nightly_loop_controller/contract.yaml`

**Step 1: Read both contracts**

Both use `handler:` top-level key + `handler_routing.default_handler` instead of the standard `handler_routing.handlers[]` array pattern.

**Step 2: Migrate to standard pattern**

Replace:
```yaml
handler:
  module: omnimarket.nodes.node_build_loop_orchestrator.handlers.handler_build_loop_orchestrator
  class: HandlerBuildLoopOrchestrator

handler_routing:
  default_handler: HandlerBuildLoopOrchestrator
```

With:
```yaml
handler_routing:
  routing_strategy: operation_match
  handlers:
    - handler:
        name: HandlerBuildLoopOrchestrator
        module: omnimarket.nodes.node_build_loop_orchestrator.handlers.handler_build_loop_orchestrator
      event_model:
        name: ModelLoopStartCommand
        module: omnimarket.nodes.node_build_loop_orchestrator.models.model_loop_start_command
```

**Step 3: Add undeclared lifecycle topics to publish_topics**

The 6 build-loop lifecycle topics published in code but not declared:
- `onex.evt.omnimarket.build-loop-started.v1`
- `onex.evt.omnimarket.build-loop-fill-completed.v1`
- `onex.evt.omnimarket.build-loop-classify-completed.v1`
- `onex.evt.omnimarket.build-loop-closeout-completed.v1`
- `onex.evt.omnimarket.build-loop-build-completed.v1`
- `onex.evt.omnimarket.build-loop-failed.v1`

Add all to `event_bus.publish_topics`.

**Step 4: Run contract validation + tests**

**Step 5: Commit**

```bash
git commit -m "fix(contracts): migrate legacy handler pattern, declare lifecycle topics"
```

**Acceptance criteria:**
- Both contracts use `handler_routing.handlers[]` array pattern
- All published lifecycle topics declared in `event_bus.publish_topics`
- No `handler:` top-level key (legacy pattern removed)
- Contract validation passes

---

## Task 8: Add warning-based preflight validation — verify declared tables exist before wiring

**Files:**
- Modify: `omnibase_infra/src/omnibase_infra/runtime/auto_wiring/handler_wiring.py`

**Step 1: Write failing test**

> **R4 FIX**: Actual `wire_from_manifest` signature is `async def wire_from_manifest(manifest, dispatch_engine, event_bus=None, environment="dev")`. There is no `db_connection` parameter. The table-existence check cannot use the auto-wiring function directly — it must be a pre-wiring validation step that runs before `wire_from_manifest` is called.

```python
from unittest.mock import AsyncMock

async def test_table_validator_warns_on_missing_table():
    """Pre-wiring preflight must emit a warning when a declared table doesn't exist."""
    from omnibase_infra.runtime.auto_wiring.db_table_validator import validate_db_tables

    # Mock asyncpg connection: fetchval returns None (table not found in pg_tables)
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=None)

    contracts_raw = [
        {"name": "node_projection_test", "db_io": {"db_tables": [
            {"name": "nonexistent_table", "migration": "0099.sql", "database": "omnidash_analytics", "role": "events"}
        ]}}
    ]
    warnings = await validate_db_tables(contracts_raw, db_conn=mock_conn)
    assert len(warnings) == 1
    assert warnings[0]["reason"] == "missing_db_table"
    assert warnings[0]["details"]["table"] == "nonexistent_table"
    assert warnings[0]["details"]["database"] == "omnidash_analytics"
    assert warnings[0]["details"]["node"] == "node_projection_test"
```

**Step 2: Create `db_table_validator.py` as a pre-wiring step**

```python
# omnibase_infra/src/omnibase_infra/runtime/auto_wiring/db_table_validator.py
async def validate_db_tables(contracts: list[dict], db_conn) -> list[dict]:
    """Preflight check: warn when declared db_tables don't exist. Does not block wiring.

    This is a warning-based preflight. Strict blocking is deferred to Phase 2
    once all contracts are complete and validated in production.
    """
    warnings = []
    for contract in contracts:
        db_io = contract.get("db_io", {})
        for table_decl in db_io.get("db_tables", []):
            if not await _table_exists(db_conn, table_decl["name"], table_decl.get("database", "omnidash_analytics")):
                warnings.append({
                    "reason": "missing_db_table",
                    "severity": "warning",
                    "details": {
                        "table": table_decl["name"],
                        "database": table_decl.get("database", "omnidash_analytics"),
                        "node": contract.get("name"),
                    },
                })
                logger.warning(
                    "Node %s declares table %s but it does not exist in %s. "
                    "Run migrations before starting this node.",
                    contract.get("name"), table_decl["name"], table_decl.get("database"),
                )
    return warnings
```

**Step 3: Call validator before `wire_from_manifest` in startup**

In the runtime startup sequence, call `validate_db_tables` before `wire_from_manifest`. This is a preflight warning phase — the validator logs warnings but does NOT block wiring. Degraded operation is preferable to a hard startup failure for missing tables.

Strict blocking is a later switch, deferred to Phase 2 once all contracts are complete and validated in production.

> **R6 FIX**: The old test asserted `report.rejected_contracts[0].reason == "missing_db_table"` which contradicted the "warn, don't block" decision. The new test correctly validates the separate validator function returns warnings without blocking.

**Step 4: Run tests**

**Step 5: Commit**

```bash
git commit -m "feat(runtime): add warning-based preflight validation for declared db_tables"
```

**Acceptance criteria:**
- `validate_db_tables()` exists at `omnibase_infra.runtime.auto_wiring.db_table_validator`
- Missing tables produce a WARNING log entry with table name, database, and node name
- Warning dicts use structured fields: `reason="missing_db_table"`, `details={"table": ..., "database": ..., "node": ...}`
- `validate_db_tables` returns warning dicts but does NOT raise — wiring continues (warn, don't block)
- `wire_from_manifest` signature is NOT modified (still `manifest, dispatch_engine, event_bus, environment`)
- Nodes with no `db_io.db_tables` produce zero warnings (backwards compatible)
- Strict blocking is explicitly NOT implemented in this phase — it is a Phase 2 concern

---

## Task 9: Proof of Life — End-to-End Verification

**Files:**
- Output: `.onex_state/contract-enforcement-proof-of-life-2026-04-08.md`

**Step 1: Verify contract completeness**

For each projection node, verify:
```bash
cd omnimarket
for node in node_projection_delegation node_projection_llm_cost node_projection_registration \
            node_projection_baselines node_projection_savings node_projection_session_outcome; do
    echo "=== $node ==="
    uv run python3 -c "
from omnibase_core.contracts.contract_loader import load_contract
from pathlib import Path
c = load_contract(Path('src/omnimarket/nodes/$node/contract.yaml'))
print(f'  db_tables: {[t[\"name\"] for t in c.get(\"db_io\", {}).get(\"db_tables\", [])]}')
print(f'  subscribe: {c.get(\"event_bus\", {}).get(\"subscribe_topics\", [])}')
print(f'  publish: {c.get(\"event_bus\", {}).get(\"publish_topics\", [])}')
"
done
```

**Step 2: Verify no hardcoded topics remain**

```bash
uv run python scripts/lint_no_hardcoded_topics.py
```

Expected: `OK: No hardcoded topic strings found.`

**Step 3: Verify latency events pass guard**

Emit a test latency event and verify it appears in the DB:
```bash
# After emitter fix, check that new events have prompt_id
ssh 192.168.86.201 "docker exec omnibase-infra-postgres psql -U postgres -d omnidash_analytics \
  -c \"SELECT COUNT(*) FROM injection_effectiveness WHERE prompt_id IS NOT NULL AND created_at > now() - interval '1 hour'\""
```

**Step 4: Verify omnimarket events reach omnidash**

Publish a test event to an omnimarket completion topic and verify omnidash consumes it:
```bash
# Check consumer group includes omnimarket topics
ssh 192.168.86.201 "docker exec omnibase-infra-redpanda rpk group describe omnidash-read-model-v1 \
  | grep omnimarket | head -5"
```

**Step 5: Write proof report**

Document:
- Contract completeness: all 6 nodes have db_tables + subscribe_topics declared
- Hardcoded topic lint: passes CI
- Latency events: flowing end-to-end
- Omnimarket subscription: omnidash consuming completion events
- Runtime warnings: auto-wiring logs for missing tables (if any)

**Acceptance criteria:**
- All 6 projection contracts declare db_tables and subscribe_topics
- Zero hardcoded topic constants in projection handler code
- CI lint rejects future hardcoded topics
- Latency events no longer silently dropped
- Omnimarket completion events visible in omnidash
- Runtime warns on missing tables during auto-wiring
