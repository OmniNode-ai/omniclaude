# OMN-3990: Investigation — Non-node Dirs under nodes/ (routing_models/, shared/)

**Status**: Investigation complete (read-only)
**Date**: 2026-03-08
**Ticket**: OMN-3990
**Follow-on execute ticket**: OMN-3991

---

## 1. Directory Inventory

Two non-node directories exist under `src/omniclaude/nodes/`:

```
src/omniclaude/nodes/
├── routing_models/          ← re-export shim only
│   └── __init__.py          (2 174 bytes — re-exports from canonical node models)
└── shared/                  ← shared handler + models
    ├── __init__.py          (983 bytes)
    ├── handler_skill_requested.py  (13 213 bytes — THE shared dispatcher)
    └── models/
        ├── __init__.py
        ├── model_merge_gate_result.py
        ├── model_pipeline_events.py
        ├── model_pr_changeset.py
        ├── model_pr_outcome.py
        ├── model_skill_completion_event.py
        ├── model_skill_lifecycle_events.py
        ├── model_skill_node_contract.py
        ├── model_skill_request.py
        └── model_skill_result.py
```

Neither directory contains a `contract.yaml`. Neither is a ONEX node.

---

## 2. Node Count (Before Migration)

| Category | Count |
|---|---|
| `node_skill_*_orchestrator` | 79 |
| Other `node_*` (effects, computes, reducers) | 20 |
| **Total `node_*` dirs** | **99** |
| Non-node dirs (`routing_models/`, `shared/`) | 2 |
| **Total entries in nodes/** | **101** |

The node count of **99** must be preserved exactly after migration. No node directories move.

---

## 3. Current Import Graph

### 3a. routing_models/

`routing_models/__init__.py` is a pure re-export shim. It imports from three canonical node
model sub-packages and re-exports all routing-related models under a convenience path.

**Imports FROM (canonical sources):**
- `omniclaude.nodes.node_agent_routing_compute.models` — 5 models
- `omniclaude.nodes.node_routing_emission_effect.models` — 2 models
- `omniclaude.nodes.node_routing_history_reducer.models` — 2 models

**Imported BY (current path `omniclaude.nodes.routing_models`):**
- `tests/nodes/test_routing_models/test_models.py` — 1 test file, imports 9 models via the
  re-export path (`from omniclaude.nodes.routing_models import ...`)

**No src/ production code imports from `omniclaude.nodes.routing_models`.**

### 3b. shared/

`shared/` contains the shared Kafka event handler plus a models sub-package consumed by
every skill orchestrator node and the runtime.

**Imported BY (src/ production code):**

| Importer | What it imports |
|---|---|
| `src/omniclaude/runtime/wiring_dispatchers.py` | `handle_skill_requested`, `ModelSkillCompletionEvent`, `ModelSkillNodeContract`, `ModelSkillNodeExecution`, `ModelSkillRequest`, `SkillResultStatus` |
| `src/omniclaude/nodes/node_claude_code_session_effect/backends/backend_subprocess.py` | `ModelSkillResult`, `SkillResultStatus` |
| `src/omniclaude/nodes/node_claude_code_session_effect/protocols/protocol_claude_code_session.py` | `ModelSkillResult` |
| `src/omniclaude/nodes/node_local_llm_inference_effect/backends/backend_vllm.py` | `ModelSkillResult`, `SkillResultStatus` |
| `src/omniclaude/nodes/node_local_llm_inference_effect/protocols/protocol_local_llm_inference.py` | `ModelSkillResult` |
| `src/omniclaude/lib/contract_change_detector.py` | `ModelContractChange` |
| `src/omniclaude/nodes/shared/models/model_skill_completion_event.py` | `SkillResultStatus` (internal self-reference) |

**Imported BY (tests):**

| Test file | What it imports |
|---|---|
| `tests/unit/nodes/shared/test_model_skill_request.py` | `ModelSkillRequest` |
| `tests/unit/nodes/shared/test_pr_changeset_models.py` | `ModelGateCheckResult`, `ModelMergeGateResult`, `ModelContractChange`, `ModelPRChangeSet`, `ModelPROutcome` |
| `tests/unit/nodes/shared/test_handler_skill_requested.py` | `handle_skill_requested`, `ModelSkillLifecycleEvent` variants, `ModelSkillRequest`, `SkillResultStatus` |
| `tests/unit/nodes/node_claude_code_session_effect/test_backend_subprocess.py` | `SkillResultStatus` |
| `tests/unit/nodes/node_local_llm_inference_effect/test_backend_vllm.py` | `SkillResultStatus` |
| `tests/unit/runtime/test_wiring_dispatchers.py` | `ModelSkillNodeContract`, `ModelSkillNodeExecution`, `SkillResultStatus` |
| `tests/nodes/test_pipeline_event_models.py` | `model_pipeline_events.*` (17 test functions) |
| `tests/unit/runtime/test_introspection.py` | (indirect — tests the introspection proxy but does not import shared directly) |
| `tests/unit/nodes/node_skill_integration_gate_orchestrator/test_integration_gate_node.py` | asserts `module == "omniclaude.nodes.shared"` in contract YAML |

---

## 4. Loaders and Globs That Scan nodes/

### 4a. Targeted globs (safe — unaffected by non-node dirs)

| File | Pattern | Picks up non-node dirs? |
|---|---|---|
| `src/omniclaude/runtime/introspection.py:241` | `node_skill_*/contract.yaml` | **No** — prefix filter |
| `src/omniclaude/runtime/wiring_dispatchers.py:162` (`load_skill_contracts`) | `node_skill_*/contract.yaml` | **No** — prefix filter |
| `tests/unit/nodes/test_skill_node_coverage.py:55,95` | `iterdir()` + `d.name.startswith("node_skill_")` and `glob("node_skill_*/contract.yaml")` | **No** — prefix filter |
| `scripts/generate_skill_node.py` | builds path `node_skill_{snake}_orchestrator/` explicitly | **No** |

### 4b. Broad glob (wiring.py docstring example)

`wiring.py` line 47 contains a **documentation example** using `**/contract.yaml`. This glob
**would** descend into `routing_models/` and `shared/` if any `contract.yaml` existed there.

**Verdict**: Neither `routing_models/` nor `shared/` contains a `contract.yaml` today, so
the broad glob is currently harmless. However, this is a future-proofing risk if a
`contract.yaml` is ever accidentally added to either directory.

### 4c. ServiceContractPublisher (runtime wiring)

`src/omniclaude/runtime/wiring.py` delegates to `ServiceContractPublisher` from
`omnibase_infra`, which uses `root.glob("**/contract.yaml")`. With
`OMNICLAUDE_CONTRACTS_ROOT=src/omniclaude/nodes`, this glob currently returns only node
contracts because neither non-node directory has a `contract.yaml`. Safe today.

### 4d. `_default_contracts_dir()` in introspection.py

Uses `importlib.resources.files("omniclaude").joinpath("nodes")` — resolves to the installed
package's `nodes/` directory. Points to the same physical location. Targeted glob
(`node_skill_*/contract.yaml`) keeps it safe.

---

## 5. Contract YAML References (81 files)

All 81 `contract.yaml` files under `src/omniclaude/nodes/node_skill_*_orchestrator/` contain:

```yaml
input_model:
  name: ModelSkillRequest
  module: omniclaude.nodes.shared.models        # ← current path

output_model:
  name: ModelSkillResult
  module: omniclaude.nodes.shared.models        # ← current path

dependencies:
  - name: handler_skill_requested
    type: handler
    function: handle_skill_requested
    module: omniclaude.nodes.shared              # ← current path
```

These module paths are also hardcoded in:
- `docs/templates/skill_node_contract.yaml.template` (the generator template for new nodes)
- `tests/unit/nodes/node_skill_integration_gate_orchestrator/test_integration_gate_node.py:272`
  (asserts `handler_dep["module"] == "omniclaude.nodes.shared"`)

---

## 6. Packaging and Distribution Implications

**Build backend**: hatchling with `packages = ["src/omniclaude"]`.

Both `routing_models/` and `shared/` are Python packages (have `__init__.py`) under
`src/omniclaude/`. They are included in the wheel automatically as sub-packages of `omniclaude`.

If either is moved:
- The wheel includes the new location automatically (no `pyproject.toml` change needed for
  hatchling with directory-based discovery)
- Python imports at the old module path (`omniclaude.nodes.routing_models`,
  `omniclaude.nodes.shared.*`) will break at runtime until all callsites are updated
- The wheel will ship both old and new locations during any transition period only if both
  directories exist simultaneously (not desirable — should be atomic)

No `MANIFEST.in` or `setup.cfg` exists. No special inclusion rules needed.

---

## 7. Test Fixtures That Depend on Current Paths

| Test file | Dependency on current path | Nature |
|---|---|---|
| `tests/nodes/test_routing_models/test_models.py` | `from omniclaude.nodes.routing_models import ...` | Import path |
| `tests/unit/nodes/shared/test_model_skill_request.py` | `from omniclaude.nodes.shared.models.model_skill_request import ...` | Import path |
| `tests/unit/nodes/shared/test_pr_changeset_models.py` | `from omniclaude.nodes.shared.models.*` | Import paths |
| `tests/unit/nodes/shared/test_handler_skill_requested.py` | `from omniclaude.nodes.shared.*` | Import paths |
| `tests/unit/nodes/node_claude_code_session_effect/test_backend_subprocess.py` | `from omniclaude.nodes.shared.models.model_skill_result import ...` | Import path |
| `tests/unit/nodes/node_local_llm_inference_effect/test_backend_vllm.py` | `from omniclaude.nodes.shared.models.model_skill_result import ...` | Import path |
| `tests/unit/runtime/test_wiring_dispatchers.py` | `from omniclaude.nodes.shared.models.*` | Import paths |
| `tests/nodes/test_pipeline_event_models.py` | `from omniclaude.nodes.shared.models.model_pipeline_events import ...` | Import paths (17 test methods) |
| `tests/unit/nodes/node_skill_integration_gate_orchestrator/test_integration_gate_node.py` | `assert handler_dep["module"] == "omniclaude.nodes.shared"` | String assertion on YAML module field |

The `test_introspection.py` test does NOT depend on current paths — it uses temp directories.

The `test_skill_node_coverage.py` test does NOT depend on non-node dirs — it filters by
`node_skill_*` prefix during `iterdir()`.

---

## 8. Proposed Target Layout

### 8a. routing_models/ — Proposed target

`routing_models/` is a convenience re-export shim. It does not contain handler logic and
is not imported by any production code. Only one test file imports it.

**Proposed new location**: `src/omniclaude/routing_models/`
(sibling of `nodes/`, not nested inside it)

**Rationale**: It is not a node. It is a cross-node convenience package that collects
routing model re-exports. Living at `omniclaude.routing_models` is semantically correct
and prevents any node-scanning pattern from encountering it.

**New import path**: `omniclaude.routing_models` (instead of `omniclaude.nodes.routing_models`)

### 8b. shared/ — Proposed target

`shared/` contains `handler_skill_requested.py` and 9 model files. It is imported by
the runtime, two effect nodes, the lib layer, and 81 contract YAML files.

**Proposed new location**: `src/omniclaude/shared/`
(sibling of `nodes/`, not nested inside it)

**Rationale**: `shared/` is cross-cutting infrastructure used by the runtime and multiple
nodes. It is not itself a node. At `omniclaude.shared` it is clearly a shared package, not
a node peer.

**New import paths**:
- `omniclaude.shared` (instead of `omniclaude.nodes.shared`)
- `omniclaude.shared.models` (instead of `omniclaude.nodes.shared.models`)
- `omniclaude.shared.models.model_skill_result` etc. (same sub-path structure, new root)

---

## 9. Expected Node Count Before and After

| Metric | Before | After |
|---|---|---|
| `node_*` dirs in nodes/ | 99 | 99 (unchanged) |
| `node_skill_*_orchestrator` dirs | 79 | 79 (unchanged) |
| Non-node dirs in nodes/ | 2 | 0 |
| `routing_models/` at `omniclaude.routing_models` | 0 | 1 |
| `shared/` at `omniclaude.shared` | 0 | 1 |

Node counts are identical. No node directories move.

---

## 10. Blast Radius Summary

| Component | Impact | Notes |
|---|---|---|
| `routing_models/__init__.py` | Move file, update 1 import path | 1 test file affected |
| `shared/` (handler + 9 models) | Move directory, update import paths | 9 src files, 8 test files, 81 contract YAMLs, 1 template |
| `docs/templates/skill_node_contract.yaml.template` | Update 3 `module:` lines | Used by `generate_skill_node.py` for new node generation |
| 81 `contract.yaml` files | Update `module: omniclaude.nodes.shared.*` → `omniclaude.shared.*` in each | Can be done with `sed` or script |
| `test_integration_gate_node.py:272` | Update string assertion | 1 line change |
| `introspection.py` | No change needed | Glob pattern `node_skill_*/contract.yaml` unaffected |
| `wiring_dispatchers.py` | No change needed | Glob `node_skill_*/contract.yaml` unaffected |
| `test_skill_node_coverage.py` | No change needed | Filters by `node_skill_*` prefix |
| `pyproject.toml` | No change needed | Hatchling includes all `src/omniclaude/**` |
| Node count invariants | No change | No nodes move |

---

## 11. Explicit Migration Steps for OMN-3991

The execute ticket (OMN-3991) should perform the following steps in order:

**11.1 — Move routing_models/**

```bash
git mv src/omniclaude/nodes/routing_models src/omniclaude/routing_models
```

**11.2 — Move shared/**

```bash
git mv src/omniclaude/nodes/shared src/omniclaude/shared
```

**11.3 — Update Python import statements in src/**

Files to update (9 files):
- `src/omniclaude/runtime/wiring_dispatchers.py` — 5 import lines
- `src/omniclaude/nodes/node_claude_code_session_effect/backends/backend_subprocess.py` — 1 import line
- `src/omniclaude/nodes/node_claude_code_session_effect/protocols/protocol_claude_code_session.py` — 1 import line
- `src/omniclaude/nodes/node_local_llm_inference_effect/backends/backend_vllm.py` — 1 import line
- `src/omniclaude/nodes/node_local_llm_inference_effect/protocols/protocol_local_llm_inference.py` — 1 import line
- `src/omniclaude/lib/contract_change_detector.py` — 1 import line
- `src/omniclaude/shared/models/model_skill_completion_event.py` — 1 internal import line

Mechanical sed transform (verify output before committing):
```bash
find src/ -name "*.py" -exec sed -i '' \
  's/omniclaude\.nodes\.shared/omniclaude.shared/g;
   s/omniclaude\.nodes\.routing_models/omniclaude.routing_models/g' {} \;
```

**11.4 — Update test import statements (8 test files)**

Same sed transform applied to tests/:
```bash
find tests/ -name "*.py" -exec sed -i '' \
  's/omniclaude\.nodes\.shared/omniclaude.shared/g;
   s/omniclaude\.nodes\.routing_models/omniclaude.routing_models/g' {} \;
```

**11.5 — Update 81 contract.yaml files**

```bash
find src/omniclaude/nodes -name "contract.yaml" -exec sed -i '' \
  's/module: omniclaude\.nodes\.shared/module: omniclaude.shared/g' {} \;
```

**11.6 — Update the contract template**

File: `docs/templates/skill_node_contract.yaml.template`

Lines 44, 48, 94:
- `module: omniclaude.nodes.shared.models` → `module: omniclaude.shared.models`
- `module: omniclaude.nodes.shared` → `module: omniclaude.shared`

**11.7 — Update the string assertion in test_integration_gate_node.py**

File: `tests/unit/nodes/node_skill_integration_gate_orchestrator/test_integration_gate_node.py`

Line 272:
- `assert handler_dep["module"] == "omniclaude.nodes.shared"` →
- `assert handler_dep["module"] == "omniclaude.shared"`

**11.8 — Verify**

```bash
# Confirm no remaining references to old paths
grep -r "omniclaude\.nodes\.shared\|omniclaude\.nodes\.routing_models" src/ tests/ docs/templates/ --include="*.py" --include="*.yaml"

# Confirm node count unchanged
ls src/omniclaude/nodes | grep -c "^node_"      # must be 99
ls src/omniclaude/nodes | grep -v "^node_"       # must be empty (or __pycache__ only)

# Run tests
uv run pytest tests/unit/nodes/shared/ tests/nodes/test_routing_models/ -v
uv run pytest tests/unit/runtime/test_wiring_dispatchers.py -v
uv run pytest tests/unit/nodes/test_skill_node_coverage.py -v
uv run pytest tests/unit/runtime/test_introspection.py -v
```

---

## 12. Rollback Path

If migration must be reverted:
```bash
git revert HEAD  # or git reset --hard HEAD~1
```

All changes are in a single commit (no database migrations, no Kafka schema changes, no
multi-repo dependencies). Rollback is instant and complete.

---

## 13. Key Findings Summary

1. `routing_models/` is a **pure re-export shim** with zero production importers. Only 1 test
   file uses it. Low-risk move.

2. `shared/` is **high-coupling cross-cutting infrastructure** — handler + 9 models. It has
   9 src importers, 8 test importers, and its module path is hardcoded in 81 contract YAML
   files and 1 template. Mechanical but high surface area.

3. **No loaders glob non-node dirs today** — all active globs use `node_skill_*/contract.yaml`
   (prefix-filtered). The broad `**/contract.yaml` in the wiring.py docstring example is
   harmless because neither non-node dir has a `contract.yaml`.

4. **Zero node count change** — no node directories are affected. 99 node dirs remain in
   `nodes/` after both moves.

5. **Packaging**: No `pyproject.toml` changes needed. Hatchling auto-discovers both new
   sibling directories.

6. **Migration is mechanical** — all changes are string substitutions and `git mv`. No
   logic changes, no new files, no schema changes.
