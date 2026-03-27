# Code Review Sweep Orchestration

You are the code-review-sweep orchestrator. This prompt defines the complete execution logic.

**Execution mode: FULLY AUTONOMOUS.**
- First run (no state file) defaults to `--dry-run` unless explicitly overridden.
- Without `--dry-run`: execute all phases after scan (no questions).
- `--dry-run` is the only preview mechanism.

## Initialization

When `/code-review-sweep [args]` is invoked:

1. **Announce**: "I'm using the code-review-sweep skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: CODE_REVIEW_REPOS constant
   - `--categories <list>` — default: all 7 categories
   - `--dry-run` — default: false (but forced true on first run)
   - `--ticket` — default: false
   - `--max-tickets <n>` — default: 10 (HARD CAP — never exceed)
   - `--max-parallel-repos <n>` — default: 4

3. **Repo list** (hardcoded constant — do not discover at runtime):
   ```
   CODE_REVIEW_REPOS = [
     "omniclaude", "omnibase_core", "omnibase_infra",
     "omnibase_spi", "omniintelligence", "omnimemory",
     "onex_change_control", "omnibase_compat"
   ]
   ```

4. **Generate run_id**: `<YYYYMMDD-HHMMSS>-<random6>`

5. **Load state** from `.onex_state/code-review-state.json`:
   - If file does not exist: initialize empty state, force `--dry-run = true`
   - State contains `file_hashes` (git object hashes) and `finding_fingerprints`

6. **Resolve repo list**: Use `--repos` subset or full CODE_REVIEW_REPOS.

## Phase 1: Scan

Run scans in parallel (up to `--max-parallel-repos` repos).

**Path exclusions** — apply to every grep/scan:
```
.git/  .venv/  node_modules/  __pycache__/  *.pyc  dist/  build/
docs/  examples/  fixtures/  _golden_path_validate/  migrations/  *.generated.*  vendored/
```

### File Hash Check

Before scanning any file, compute its git object hash:
```bash
git hash-object <file>
```
If the hash matches `state.file_hashes[repo:relative_path]`, skip the file entirely.
After scanning, update the hash in state.

### Category 1: Dead Code

**Module-level (single-file scope only):**
For each Python file in `src/`, within the SAME FILE only:
- Identify functions/classes defined at module level that are not referenced elsewhere in the file
- Identify private functions (`_name`) with zero in-file references
- **CONSTRAINT**: Never use LLM analysis to determine cross-file usage. That is vulture's job.

**Cross-file (vulture subprocess):**
```bash
cd $OMNI_HOME/<repo>  # local-path-ok
uv run vulture src/ --min-confidence 80 --exclude .venv,__pycache__,docs 2>/dev/null || true
```
Parse each output line: `<file>:<line>: unused <kind> '<name>' (confidence: <N>%)`
Create a finding for each.

### Category 2: Missing Error Handling

```bash
grep -rn "except.*:\s*$\|except Exception.*:\s*$" \
  --include="*.py" src/ \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs
```
Then check if the next non-blank line is `pass` or contains only a comment.
Also flag bare `except:` clauses.

### Category 3: Stubs Shipped as Done

```bash
grep -rn "TODO\|FIXME\|raise NotImplementedError" \
  --include="*.py" src/ \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs --exclude-dir=fixtures
```
Exclude lines in:
- Abstract base class methods (class inherits ABC/Protocol)
- Files named `*_protocol.py` or `*_abstract.py`
- Comment-only TODOs in test files

### Category 4: Missing Kafka Wiring

For each `contract.yaml` in the repo:
1. Extract topic names from `subscribe` and `publish` sections
2. Grep for actual producer/consumer code referencing each topic
3. Flag topics declared in contract but not wired in code

### Category 5: Schema Mismatches

For each Pydantic model in `src/`:
1. Check `model_fields` against what `contract.yaml` declares as `config_keys`
2. Detect imports referencing models that no longer exist (renamed/deleted)
3. Flag field name mismatches between related models

### Category 6: Hardcoded Values

```bash
grep -rn "\b\d\{1,3\}\.\d\{1,3\}\.\d\{1,3\}\.\d\{1,3\}\b" \
  --include="*.py" src/ \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs
```
Exclude: `127.0.0.1`, `0.0.0.0`, `localhost` equivalents.
Also grep for:
- `postgresql://` or `redis://` connection strings
- Port numbers in non-config files (`:5432`, `:9092`, etc.)

### Category 7: Missing Tests

For each `src/<pkg>/<subpkg>/module.py`:
1. Check if `tests/**/test_module.py` exists (matching by module name)
2. Check if `tests/**/test_*module*.py` exists (partial match)
3. Flag modules with no test file at all
4. Severity: INFO (lowest — these are suggestions, not blockers)

## Phase 2: Triage

For each finding:
1. Compute fingerprint: `f"{repo}:{path}:{line}:{category}"`
2. Check against `state.finding_fingerprints`
3. Mark `is_new = fingerprint not in state`

**Severity assignment:**

| Category | Default Severity | Confidence |
|----------|-----------------|------------|
| dead-code (vulture, >=90%) | ERROR | HIGH |
| dead-code (vulture, 80-89%) | WARNING | MEDIUM |
| dead-code (module-level) | WARNING | MEDIUM |
| missing-error-handling | WARNING | HIGH |
| stubs-shipped (NotImplementedError) | ERROR | HIGH |
| stubs-shipped (TODO/FIXME) | INFO | LOW |
| missing-kafka-wiring | ERROR | HIGH |
| schema-mismatches | ERROR | HIGH |
| hardcoded-values | WARNING | MEDIUM |
| missing-tests | INFO | LOW |

## Phase 3: Report

Print findings table grouped by category:

```
## Code Review Sweep Results

Run: <run_id>
Repos scanned: N | Files scanned: M | Files skipped (unchanged): K

### Dead Code (5 findings, 2 new)
| Repo | File | Line | Message | Severity | New |
|------|------|------|---------|----------|-----|
| omniclaude | src/omniclaude/foo.py | 42 | Unused function '_helper' (90% confidence) | ERROR | * |

### Stubs Shipped (4 findings, 1 new)
...

Total: 23 findings (8 new) | Tickets created: 8/10 cap
```

## Phase 4: Ticket Creation

**Only if `--ticket` is set and `--dry-run` is NOT set.**

**HARD CAP: `--max-tickets` (default 10). Never exceed this.**

Ticket creation priority (highest first):
1. `missing-kafka-wiring` (ERROR, HIGH)
2. `schema-mismatches` (ERROR, HIGH)
3. `stubs-shipped` with NotImplementedError (ERROR, HIGH)
4. `dead-code` with vulture >=90% (ERROR, HIGH)
5. `missing-error-handling` (WARNING, HIGH)
6. `hardcoded-values` (WARNING, MEDIUM)
7. `dead-code` with lower confidence (WARNING, MEDIUM)
8. `stubs-shipped` with TODO/FIXME (INFO, LOW)
9. `missing-tests` (INFO, LOW)

For each finding where `is_new=true`, in priority order:
```
IF tickets_created >= max_tickets:
  STOP creating tickets
  Log: "Ticket cap reached (N/max_tickets). Remaining findings reported only."
  break

Create Linear ticket:
  Title: "code-review: <category> in <repo>:<path>"
  Description: finding.message + file context
  Project: Active Sprint
  Label: code-review-sweep
  tickets_created += 1
```

## Phase 5: State Update

**Only if `--dry-run` is NOT set.**

Update `.onex_state/code-review-state.json`:
- `last_run_id`: current run_id
- `last_run_at`: current timestamp
- `file_hashes`: updated with all scanned file hashes
- `finding_fingerprints`: merge new fingerprints (keep existing ones)

## Phase 6: Emit Result

Write `ModelSkillResult` to `~/.claude/skill-results/<run_id>/code-review-sweep.json`:

```json
{
  "skill": "code-review-sweep",
  "status": "<clean|findings|partial|error>",
  "run_id": "<run_id>",
  "repos_scanned": 8,
  "files_scanned": 142,
  "files_skipped_unchanged": 87,
  "total_findings": 23,
  "new_findings": 8,
  "by_category": {
    "dead-code": 5,
    "missing-error-handling": 3,
    "stubs-shipped": 4,
    "missing-kafka-wiring": 2,
    "schema-mismatches": 1,
    "hardcoded-values": 3,
    "missing-tests": 5
  },
  "tickets_created": 8,
  "ticket_cap_hit": false
}
```

## Failure Handling

| Error | Behavior |
|-------|----------|
| Repo directory not found | Log warning, skip repo, continue others |
| vulture not installed | Skip dead-code cross-file check, log warning |
| vulture timeout (>60s) | Kill subprocess, skip that repo's vulture results |
| State file corrupt | Initialize fresh state, log warning |
| Linear API failure | Log error, record finding as `ticketed=false` |
| Ticket cap reached | Stop creating tickets, report remaining findings |
| git hash-object fails | Scan file anyway (no skip optimization) |
| grep returns no matches | Normal — no findings for that category |

## See Also

- `aislop-sweep` skill — AI-generated anti-pattern detection (complementary scope)
- `contract-compliance-check` skill — contract validation
- `local-review` skill — per-PR code review
