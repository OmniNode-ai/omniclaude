---
description: Migrate imperative handlers to declarative contract-driven pattern — reads handler source and contract.yaml, generates contract.yaml updates and handler modifications for each violation type, validates changes via contract-dispatch equivalence. Does not change handler behavior, only moves wiring declarations into contracts.
mode: full
version: "1.0.0"
level: advanced
debug: false
category: governance
tags: [compliance, migration, contracts, handlers, declarative]
author: omninode
composable: true
args:
  - name: --handler
    description: "Path to specific handler to migrate (required)"
    required: true
  - name: --apply
    description: "Apply generated changes (default: dry-run only)"
    required: false
  - name: --validate
    description: "Run contract-dispatch equivalence validation after migration (default: true)"
    required: false
---

# Compliance Migration

**Skill ID**: `onex:compliance-migration`

## Purpose

Migrate a single imperative handler to the declarative contract-driven pattern. For each
violation type found by the compliance scan, this skill generates the specific contract.yaml
changes and handler code modifications needed.

The migration does NOT change handler behavior — it only moves wiring declarations from
Python code into contract.yaml and replaces hardcoded values with contract-declared ones.

## Announce

"I'm using the compliance-migration skill to migrate this handler to the declarative contract pattern."

## Usage

/compliance-migration --handler src/omnibase_infra/nodes/node_foo/handlers/handler_bar.py
/compliance-migration --handler src/omnibase_infra/nodes/node_foo/handlers/handler_bar.py --apply

## Workflow

### Analyze handler

1. Read the handler source and its contract.yaml
2. Run `cross_reference()` to identify all violations
3. If no violations, report "handler is already compliant" and exit

### Generate migration spec

For each violation type, generate specific changes:

**HARDCODED_TOPIC**:
- Add the topic to contract.yaml `event_bus.publish_topics` or `subscribe_topics`
- Note: handler code referencing the topic string can remain — the contract now declares it

**UNDECLARED_TRANSPORT**:
- Add transport capability to contract.yaml `metadata.transport_type` or handler routing
- If handler imports `httpx`/`asyncpg`/etc., add corresponding transport declaration

**MISSING_HANDLER_ROUTING**:
- Add handler entry to contract.yaml `handler_routing.handlers[]`
- Infer operation name from handler class/method name
- Infer module path from handler file location

**LOGIC_IN_NODE**:
- Extract custom methods from node.py into a new handler file
- Add the new handler to contract.yaml routing
- Reduce node.py to declarative shell (only `__init__` calling `super().__init__`)
- Mark as low-confidence if logic is complex

**DIRECT_DB_ACCESS**:
- Replace direct DB construction with injected service from `ModelONEXContainer`
- Add DATABASE transport declaration to contract.yaml

### Output ModelMigrationSpec

Produce a `ModelMigrationSpec` JSON with:
- All violations found
- Specific contract.yaml changes needed (as human-readable strings)
- Specific handler changes needed
- Estimated complexity (1-5 based on violation count and types)
- Migration status (GENERATED)

### Apply changes (if --apply)

If `--apply` is specified:
1. Write the updated contract.yaml
2. Write the modified handler file(s)
3. If LOGIC_IN_NODE, create new handler file and update node.py

### Validate (if --validate)

If `--validate` is specified (default: true) and changes were applied:
1. Verify the handler can be loaded via contract's `handler_routing`
2. Run syntax check on modified files
3. Run existing unit tests if present
4. Report pass/fail

## Output

- `ModelMigrationSpec` JSON printed to stdout
- Updated contract.yaml and handler files (if --apply)
- Validation results (if --validate)

## Dependencies

- `onex_change_control` package (for scanner module and models)
- Target repository source code
