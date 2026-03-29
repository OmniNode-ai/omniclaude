# compliance_sweep prompt

You are executing the **compliance-sweep** skill. This skill scans all repos for
handler contract compliance violations using the `arch-handler-contract-compliance`
scanner from `onex_change_control`.

## Announce

Say: "I'm using the compliance-sweep skill to audit handler contract compliance across all repos."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--repos <comma-list>` -- Repos to scan (default: all Python repos)
- `--dry-run` -- Report only, no ticket creation
- `--create-tickets` -- Create Linear tickets for untracked violations
- `--max-tickets <N>` -- Max tickets per run (default: 10)
- `--json` -- Output ModelComplianceSweepReport JSON
- `--allowlist-dir <path>` -- Override allowlist directory

**Default repo list** (scan all unless `--repos` overrides):
```
omnibase_infra, omniintelligence, omnimemory, omnibase_core,
omniclaude, onex_change_control, omnibase_spi
```

**Bare clone root**: `/Volumes/PRO-G40/Code/omni_home`  <!-- local-path-ok -->

**Change control repo**: `/Volumes/PRO-G40/Code/omni_home/onex_change_control`  <!-- local-path-ok -->

## Preamble: Pull bare clones

Before scanning, pull all bare clones to ensure findings reflect latest `main`:

```bash
bash /Volumes/PRO-G40/Code/omni_home/omnibase_infra/scripts/pull-all.sh  # local-path-ok
```

If `pull-all.sh` exits non-zero, **warn but continue** -- stale clones may produce
slightly outdated findings but this is not a blocking failure.

## Phase 1: Discovery

For each repo in the scan list, find all node directories from the `main` branch.
A node directory is a directory under `src/**/nodes/` that starts with `node_` and
contains a `handlers/` subdirectory.

```bash
# For bare clones, use git ls-tree to find node directories
git -C /Volumes/PRO-G40/Code/omni_home/<repo> ls-tree -r -d main --name-only \  # local-path-ok
  | grep -E 'nodes/node_[^/]+/handlers$' \
  | sed 's|/handlers$||' \
  | sort -u
```

For each node directory found, record:
- `repo`: repository name
- `node_dir`: relative path to node directory
- `has_contract`: whether `contract.yaml` exists in the node directory
- `handler_count`: number of `.py` files in `handlers/` (excluding `__init__.py`)

Record the total handler count across all repos.

## Phase 2: Run compliance scanner

For each repo, run the `arch-handler-contract-compliance` validator from
`onex_change_control`. This requires checking out the repo content to a temporary
location since the scanner needs filesystem access.

**Option A (preferred)**: If the repo has a worktree or working copy available, use it directly:

```bash
# Check if a working copy exists (e.g., in a worktree)
REPO_PATH="/Volumes/PRO-G40/Code/omni_home/<repo>"  # local-path-ok

# For bare clones, we need to extract files to a temp dir
TEMP_DIR=$(mktemp -d)
git -C "$REPO_PATH" --work-tree="$TEMP_DIR" checkout main -- src/ 2>/dev/null

# Run the validator
cd /Volumes/PRO-G40/Code/omni_home/onex_change_control  # local-path-ok
uv run python -m onex_change_control.validators.arch_handler_contract_compliance \
  --repo-root "$TEMP_DIR" \
  --json 2>/dev/null

# Clean up
rm -rf "$TEMP_DIR"
```

**Option B**: If the validator is not available (e.g., `onex_change_control` not installed),
fall back to manual scanning:

1. For each node directory, read `contract.yaml` via `git show main:<path>/contract.yaml`
2. For each handler `.py` file, read via `git show main:<path>`
3. Manually check for:
   - Topic string literals matching `onex.evt.*` or known bare topic names
   - Transport imports (`psycopg`, `httpx`, `aiokafka`, etc.)
   - Whether handler is listed in contract.yaml `handler_routing`
   - Custom methods in `node.py` beyond `__init__`

Parse the JSON output from the validator into `ModelHandlerComplianceResult` objects.

## Phase 3: Aggregate results

Build a `ModelComplianceSweepReport` from the per-handler results:

1. **Count by verdict**: COMPLIANT, IMPERATIVE, HYBRID, ALLOWLISTED, MISSING_CONTRACT
2. **Compute compliant_pct**: `(compliant_count / total_handlers) * 100`, clamped 0-100
3. **Build violation histogram**: count occurrences of each `EnumComplianceViolation`
4. **Build per-repo breakdown**: for each repo, compute counts and top violations
5. **Detect new violations**: compare against previous report if it exists at
   `docs/registry/compliance-scan-*.json`

## Phase 4: Save report

Save the `ModelComplianceSweepReport` as JSON to:

```
/Volumes/PRO-G40/Code/omni_home/docs/registry/compliance-scan-<YYYY-MM-DD>.json  <!-- local-path-ok -->
```

If `--json` flag is set, also print the full JSON to stdout.

## Phase 5: Print summary

Print a human-readable summary:

```
Handler Contract Compliance Sweep
===================================
Repos scanned: <N>
Total handlers: <N>
Compliant: <N> (<pct>%)
Imperative: <N> (<pct>%)
Hybrid: <N> (<pct>%)
Allowlisted: <N> (<pct>%)
Missing contract: <N> (<pct>%)

Per-repo breakdown:
  <repo>: <total> handlers (<compliant> compliant, <imperative> imperative, <hybrid> hybrid)
  ...

Top violations:
  <violation_type>: <count>
  ...

Overall compliance: <pct>%
Report: docs/registry/compliance-scan-<date>.json
```

## Phase 6: Ticket creation (--create-tickets)

**Skip entirely** if `--dry-run` is set or `--create-tickets` is NOT set.
Print: "Use --create-tickets to create Linear tickets for violations."

Otherwise:

### Group by node

Group all violation results by `node_dir`. One ticket per node directory, not per handler.
A node's ticket covers all handlers within that node.

### Dedup against existing tickets

For each node with violations:

1. Check if the node's handlers appear in the repo's allowlist YAML with a `ticket:` field
2. Search Linear for an open ticket containing the node name and "compliance" in the title
3. If either check finds an existing ticket: **skip** (idempotent)

### Create tickets

For each node NOT already tracked (up to `--max-tickets`, default 10):

**Title**: `fix(compliance): migrate <node_name> to declarative pattern`

**Description** (markdown):

```markdown
## Contract Compliance Violation

**Node**: `<repo>/src/<package>/nodes/<node_name>/`
**Handlers**: <count> handlers with violations
**Detected by**: compliance-sweep skill run <date>

### Violations

| Handler | Violations | Details |
|---------|-----------|---------|
| handler_foo.py | HARDCODED_TOPIC, UNDECLARED_TRANSPORT | hardcoded topic 'agent-actions' at line 47; imports httpx not declared in contract |
| handler_bar.py | MISSING_HANDLER_ROUTING | handler not registered in contract.yaml handler_routing |

### Required Changes

**contract.yaml updates needed**:
- Add missing topics to `event_bus.publish_topics` / `event_bus.subscribe_topics`
- Add missing transport declarations to capabilities
- Register all handlers in `handler_routing`

**Handler updates needed**:
- Replace hardcoded topic strings with contract-declared references
- Remove direct DB/HTTP construction; use injected services

### Context

This is part of the imperative-to-declarative migration. See:
- Plan: docs/plans/2026-03-27-imperative-to-declarative-scan.md
- Parent ticket: OMN-6842
```

**Settings**:
- Project: Active Sprint
- Label: `contract-compliance`
- Priority: 3 (Normal)

### Report ticket creation

After creating tickets, print:

```
Tickets created: <N>
  OMN-XXXX: fix(compliance): migrate node_foo to declarative pattern
  OMN-YYYY: fix(compliance): migrate node_bar to declarative pattern
  ...

Remaining untracked nodes: <N> (use --max-tickets to increase limit)
```

## Phase 7: Emit event

Emit a `compliance.sweep.completed` event with:

```json
{
  "event_type": "compliance.sweep.completed",
  "timestamp": "<ISO-8601>",
  "repos_scanned": <N>,
  "total_handlers": <N>,
  "compliant_count": <N>,
  "compliant_pct": <float>,
  "imperative_count": <N>,
  "tickets_created": <N>,
  "report_path": "docs/registry/compliance-scan-<date>.json"
}
```

Use the standard event emission pattern (emit daemon or Kafka direct).
If emission fails, log a warning but do not fail the skill.

## Error handling

- If `onex_change_control` is not found: abort with error
- If a repo is not found at `$OMNI_HOME/<repo>`: skip, record in report
- If validator fails for a repo: record as error, continue with remaining repos
- If Linear API fails during ticket creation: log error, continue with remaining tickets
- If `uv` is not available: fall back to `python3` directly

## Examples

### Dry run (default)

```
/compliance-sweep

Handler Contract Compliance Sweep
===================================
Repos scanned: 7
Total handlers: 269
Compliant: 52 (19.3%)
Imperative: 180 (66.9%)
Hybrid: 25 (9.3%)
Allowlisted: 12 (4.5%)
Missing contract: 0 (0.0%)
...
Use --create-tickets to create Linear tickets for violations.
```

### With ticket creation

```
/compliance-sweep --create-tickets --max-tickets 5

Handler Contract Compliance Sweep
===================================
...
Tickets created: 5
  OMN-6900: fix(compliance): migrate node_baselines_effect to declarative pattern
  OMN-6901: fix(compliance): migrate node_agent_actions_consumer to declarative pattern
  ...
Remaining untracked nodes: 23 (use --max-tickets to increase limit)
```
