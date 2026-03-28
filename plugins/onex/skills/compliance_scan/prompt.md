# Compliance Scan Prompt

You are running the compliance scan skill. This skill audits handler contract
compliance across all ONEX repositories.

## Parse arguments

Extract from invocation:
- `--repos <list>`: Comma-separated repos to scan (default: all repos with handlers)
- `--create-tickets`: Create Linear tickets for non-allowlisted violations
- `--dry-run`: Report findings without saving reports or creating tickets

## Phase 1 — Discover repos

1. Scan `$OMNI_HOME/` for repositories containing `src/**/nodes/*/handlers/` directories
2. Default repos: `omnibase_infra`, `omniintelligence`, `omnimemory`, `omnibase_core`
3. If `--repos` is specified, filter to only those repos

```bash
# Find repos with handler directories
for repo in omnibase_infra omniintelligence omnimemory omnibase_core; do
  if [ -d "$OMNI_HOME/$repo/src" ]; then
    handler_dirs=$(find "$OMNI_HOME/$repo/src" -path "*/nodes/*/handlers" -type d 2>/dev/null)
    if [ -n "$handler_dirs" ]; then
      echo "Found handlers in $repo"
    fi
  fi
done
```

## Phase 2 — Scan each repo

For each repo:

1. Find all `src/**/nodes/node_*/` directories that contain a `handlers/` subdirectory
2. For each node directory:
   a. Locate `contract.yaml` (in the node directory)
   b. List all `.py` files in `handlers/` (excluding `__init__.py`)
   c. For each handler file, perform 4 checks:

### Check 1: Topic compliance
- Parse contract.yaml for `event_bus.publish_topics` and `event_bus.subscribe_topics`
- Scan handler source for topic string literals matching `onex.evt.*` or known bare topics
- Use AST parsing to distinguish strings in function calls vs docstrings/comments
- Flag topics used in handler but not declared in contract

### Check 2: Transport compliance
- Parse contract.yaml for declared transport types
- Scan handler imports for transport indicators:
  - `psycopg`, `asyncpg`, `sqlalchemy` -> DATABASE
  - `httpx`, `requests`, `aiohttp` -> HTTP
  - `aiokafka`, `confluent_kafka` -> KAFKA
  - `qdrant_client` -> QDRANT
- Two-tier: import-only = HYBRID (warning), call-site usage = IMPERATIVE (violation)

### Check 3: Handler routing registration
- Check if handler class is listed in contract.yaml `handler_routing.handlers[]`
- Flag handlers on disk but not in contract routing

### Check 4: Logic-in-node detection
- Check node.py for methods beyond `__init__`
- Flag custom methods, properties, or class-level logic

3. Load the repo's allowlist from `arch-handler-contract-compliance-allowlist.yaml`
4. Mark allowlisted handlers and skip them from violation counting

## Phase 3 — Aggregate results

Build a compliance report:
- Total handler count
- Counts by verdict: compliant, imperative, hybrid, allowlisted, missing_contract
- Compliant percentage = (compliant + allowlisted) / total * 100
- Violation histogram (count per violation type)
- Per-repo breakdown with top violations

## Phase 4 — Save and display

1. Unless `--dry-run`, save report JSON to `$OMNI_HOME/docs/registry/compliance-scan-<date>.json`
2. Print summary:
   ```
   === Handler Contract Compliance Scan ===
   Repos scanned: 4
   Total handlers: 269
     Compliant: 52 (19%)
     Imperative: 180 (67%)
     Hybrid: 15 (6%)
     Allowlisted: 20 (7%)
     Missing contract: 2 (1%)

   Top violations:
     1. HARDCODED_TOPIC: 145
     2. MISSING_HANDLER_ROUTING: 89
     3. UNDECLARED_TRANSPORT: 34

   Per-repo breakdown:
     omnibase_infra: 180 handlers, 28% compliant
     omniintelligence: 45 handlers, 11% compliant
     ...
   ```

## Phase 5 — Create tickets (if --create-tickets)

If `--create-tickets` is specified:
1. For each node directory with non-allowlisted violations:
   a. Group all handler violations by node (one ticket per node)
   b. Create Linear ticket:
      - Title: "Fix contract compliance: <node_name> [VIOLATION_TYPES]"
      - Project: Active Sprint
      - Label: contract-compliance
      - Description: handler paths, specific violations with line references, contract.yaml changes needed
   c. Update the repo's allowlist YAML with the new ticket ID
2. Maximum 10 tickets per run to prevent spam
3. Skip nodes that already have a ticket in the allowlist

## Operational constraints

- Use AST parsing for topic/transport detection (not raw regex)
- Exclude comments and docstrings from topic string detection
- Import-only transport findings produce warnings, not CI-blocking violations
- Allowlist supports whole-node entries for MISSING_CONTRACT verdict
