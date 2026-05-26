# OMN-11613: manifest_injector Deletion Plan

**Status:** Migration documented — deletion pending caller migration  
**Date:** 2026-05-26  
**Ticket:** OMN-11613 (Wave 4B Step 9)

---

## Current State (as of 2026-05-26)

### What exists

| File | Lines | Status |
|------|-------|--------|
| `src/omniclaude/lib/core/manifest_injector.py` | 5480 | ACTIVE — still the production code path |
| `src/omniclaude/lib/core/models_manifest_injector.py` | ~200 | ACTIVE — models extracted in OMN-11590 (now also in `node_manifest_fetch_effect/models/`) |
| `src/omniclaude/nodes/node_manifest_fetch_effect/` | 24 unit tests | NEW — created in OMN-11597, merged to dev |

### What `manifest_injector.py` actually does

`ManifestInjector` is a Kafka-event-driven subsystem (~5480 lines) that:
1. Publishes intelligence requests to Kafka `intelligence.requests` topic
2. Waits for responses from `onex-intelligence-adapter` (Qdrant, Memgraph, PostgreSQL queries)
3. Formats responses into a structured agent manifest (patterns, infrastructure, models)
4. Falls back to a minimal manifest on timeout (2000ms budget)
5. Exposes both async context-manager and sync-wrapper APIs

### What `node_manifest_fetch_effect` does (OMN-11597)

A narrow HTTP-fetch node that:
1. Calls `{runtime_url}/v1/introspection/manifest` via httpx
2. Returns `ModelManifestFetchResult` with status: OK / TIMEOUT / UNAVAILABLE / ERROR
3. Never raises — graceful degradation only
4. No Kafka, no intelligence queries, no pattern retrieval

**These are NOT equivalent.** The node fetches from a pre-computed runtime endpoint.
`manifest_injector` assembles the manifest dynamically from Kafka + intelligence adapters.
The node is a **first step** — it can replace the HTTP fetch leg of a future refactored pipeline,
not the entire manifest_injector.

---

## Active Callers of manifest_injector (must migrate before deletion)

### 1. `src/omniclaude/lib/core/__init__.py`
```python
from .manifest_injector import ManifestInjector, inject_manifest
# ...
"ManifestInjector",
"inject_manifest",
```
**Action required:** Remove exports once all downstream callers are migrated.

### 2. `src/omniclaude/lib/utils/manifest_loader.py` (lines 74–78)
```python
from manifest_injector import inject_manifest
manifest: str = inject_manifest(correlation_id=correlation_id, agent_name=agent_name)
```
**Note:** This import uses a bare `manifest_injector` (not `omniclaude.lib.core.manifest_injector`).
It loads from `$ONEX_STATE_DIR/agents/lib/` at runtime — this is the deployed copy of
`manifest_injector.py` installed separately from the Python package.

**Action required:** Replace `manifest_loader.py` with a caller of `node_manifest_fetch_effect`
(or a future node that assembles the full manifest from the runtime endpoint).

### 3. `src/omniclaude/config/settings.py` (line 349)
```python
"Enable runtime kill switch for patterns. When True, ManifestInjector "
```
**Action required:** Update docstring after ManifestInjector is replaced.

### 4. `src/omniclaude/lib/core/intelligence_cache.py` (line 26)
```python
# - Used by ManifestInjector for pattern/infrastructure/model queries
```
**Action required:** Update comment. `IntelligenceCache` may also need deletion/migration
depending on whether the new manifest pipeline still uses it.

---

## Why deletion is NOT safe yet

1. **`node_manifest_fetch_effect` is not wired into any caller** — it exists as an isolated node
   with no dispatch table entry and no callers in `src/` or `plugins/`.

2. **The node and the injector are not equivalent** — the injector generates dynamic manifests
   via Kafka + intelligence adapters; the node fetches a pre-computed manifest from an HTTP endpoint.
   A full replacement requires either:
   a. Wiring `node_manifest_fetch_effect` as the manifest source in `manifest_loader.py`, OR
   b. Creating additional nodes to handle the intelligence-query leg of manifest assembly.

3. **Golden fixtures still depend on `manifest_injector.py`** — 61 tests in
   `tests/golden/test_manifest_injector_golden.py` document current behavior and pass against
   the live code. These become the equivalence proof for the replacement.

---

## Equivalence Proof Requirements (before deletion can proceed)

For the deletion to be safe, all of the following must hold:

1. `manifest_loader.py` calls `node_manifest_fetch_effect` (or equivalent) instead of
   importing `inject_manifest` from the deployed `manifest_injector.py`
2. The new code path produces structurally equivalent output (same manifest sections)
3. All 61 golden fixtures in `tests/golden/test_manifest_injector_golden.py` pass against
   the new implementation (or are replaced by equivalent tests of the new node)
4. The 24 unit tests in `tests/unit/nodes/node_manifest_fetch_effect/` continue to pass
5. `pre-commit run --all-files` passes

---

## Migration Steps to Enable Deletion

These are the follow-on tickets needed before deletion can be executed:

### Step A: Wire `node_manifest_fetch_effect` into a caller (new ticket)
Update `src/omniclaude/lib/utils/manifest_loader.py` to call `node_manifest_fetch_effect`
via the ONEX container + DI, replacing the bare `manifest_injector` import.

### Step B: Migrate or deprecate golden fixtures (new ticket)
Either port the 61 golden tests to test the new node's behavior, or add a parallel golden
test for the `node_manifest_fetch_effect` path and mark the old ones as deprecated.

### Step C: Remove `manifest_injector.py` and `models_manifest_injector.py` (this ticket, OMN-11613)
Only executable after Steps A and B are complete and green.

---

## Test Evidence (current state — all green)

```
tests/golden/test_manifest_injector_golden.py  61 passed
tests/unit/nodes/node_manifest_fetch_effect/   24 passed
```

Run to verify:
```bash
uv run pytest tests/golden/test_manifest_injector_golden.py tests/unit/nodes/node_manifest_fetch_effect/ -v
```
