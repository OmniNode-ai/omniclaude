# Compliance Migration Prompt

You are running the compliance migration skill. This skill migrates a single
imperative handler to the declarative contract-driven pattern.

## Parse arguments

Extract from invocation:
- `--handler <path>`: Required. Path to the handler file to migrate.
- `--apply`: Apply generated changes (default: dry-run only)
- `--validate`: Run validation after migration (default: true)

## Step 1 — Analyze handler

1. Read the handler source file at the specified path
2. Locate the parent node directory (the `node_*` directory containing `handlers/`)
3. Find `contract.yaml` in the node directory
4. If no contract.yaml exists, note this — the migration will need to create one
5. Run compliance checks against the handler:
   - Topic compliance: find hardcoded topic strings
   - Transport compliance: find undeclared transport imports
   - Handler routing: check if registered in contract.yaml
   - Logic in node.py: check for business logic in node.py

6. If no violations found:
   ```
   Handler is already compliant. No migration needed.
   ```
   Exit.

## Step 2 — Generate migration spec

For each violation type found, generate specific changes:

### HARDCODED_TOPIC
1. Identify the topic string literal in the handler code
2. Determine if it's a publish or subscribe topic based on context:
   - Used in `producer.send()`, `emit()`, `publish()` -> publish topic
   - Used in `subscribe()`, `consumer()`, topic list -> subscribe topic
3. Generate contract.yaml change:
   ```yaml
   # Add to contract.yaml event_bus section
   event_bus:
     publish_topics:
       - "<topic_string>"  # NEW: was hardcoded in handler
   ```
4. The handler code can keep the topic string — the contract now declares it

### UNDECLARED_TRANSPORT
1. Identify which transport library is imported
2. Map to transport type: httpx->HTTP, asyncpg->DATABASE, etc.
3. Generate contract.yaml change:
   ```yaml
   metadata:
     transport_type: "<TRANSPORT_TYPE>"  # NEW: handler uses this transport
   ```

### MISSING_HANDLER_ROUTING
1. Determine the handler's class name and module path
2. Infer the operation name from the class/method name
3. Generate contract.yaml change:
   ```yaml
   handler_routing:
     handlers:
       - handler_class: "<ClassName>"
         module_path: "<module.path>"
         operation: "<operation_name>"  # NEW: handler was not registered
   ```

### LOGIC_IN_NODE
1. Identify custom methods in node.py (beyond `__init__`)
2. For each method:
   a. Determine if it contains business logic (not just delegation)
   b. Create a new handler file: `handlers/handler_<method_name>.py`
   c. Move the method body into the new handler
   d. Update node.py to only have `__init__` calling `super().__init__(container)`
3. Add the new handler to contract.yaml routing
4. Mark complex extractions as LOW_CONFIDENCE

### DIRECT_DB_ACCESS
1. Find direct database construction (e.g., `asyncpg.connect()`, `create_engine()`)
2. Replace with injected service from `ModelONEXContainer`
3. Add DATABASE transport declaration to contract.yaml

## Step 3 — Output ModelMigrationSpec

Print a structured migration spec:
```
=== Migration Spec ===
Handler: <handler_path>
Node: <node_dir>
Contract: <contract_path>
Violations: [<list>]
Complexity: <1-5>
Status: GENERATED

Contract changes:
  1. Add "<topic>" to event_bus.publish_topics
  2. Add handler routing entry for <ClassName>
  ...

Handler changes:
  1. Topic string is now contract-declared (no code change needed)
  2. New handler file: handlers/handler_<name>.py (extracted from node.py)
  ...
```

## Step 4 — Apply changes (if --apply)

If `--apply` is specified:
1. Write the updated contract.yaml using proper YAML serialization
2. Write modified handler files
3. If LOGIC_IN_NODE, create new handler file and update node.py
4. Stage all changes

## Step 5 — Validate (if --validate)

If `--validate` and changes were applied:
1. Verify the handler module can be imported:
   ```bash
   uv run python -c "import <module_path>"
   ```
2. Run syntax check on modified files:
   ```bash
   uv run python -m py_compile <file>
   ```
3. Run existing unit tests if present:
   ```bash
   uv run pytest tests/unit/ -k "<handler_name>" -x -q --no-header 2>/dev/null
   ```
4. Report pass/fail for each validation step

## Output format

Always output the ModelMigrationSpec JSON for machine consumption, followed by
the human-readable summary above.

## Constraints

- Never change handler output behavior — only move wiring declarations
- Mark low-confidence extractions (complex LOGIC_IN_NODE) clearly
- Preserve all existing imports and type annotations
- Do not modify files outside the target node directory
