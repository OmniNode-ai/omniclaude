# AI Slop Sweep Orchestration

You are the aislop-sweep orchestrator. This prompt defines the complete execution logic.

**Execution mode: FULLY AUTONOMOUS.**
- Without `--dry-run`: execute all phases after triage (no questions).
- `--dry-run` is the only preview mechanism.

## Initialization

When `/aislop-sweep [args]` is invoked:

1. **Announce**: "I'm using the aislop-sweep skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: AISLOP_REPOS constant
   - `--checks <list>` — default: all 6 check categories
   - `--dry-run` — default: false
   - `--ticket` — default: false
   - `--auto-fix` — default: false
   - `--severity-threshold <level>` — default: WARNING
   - `--max-parallel-repos <n>` — default: 4

3. **Repo list** (hardcoded constant — do not discover at runtime):
   ```
   AISLOP_REPOS = [
     "omniclaude", "omnibase_core", "omnibase_infra",
     "omnibase_spi", "omniintelligence", "omnimemory",
     "onex_change_control", "omnibase_compat"
   ]
   ```

4. **Generate run_id**: `<YYYYMMDD-HHMMSS>-<random6>`

5. **Resolve repo list**: Use `--repos` subset or full AISLOP_REPOS.

## Phase 1: Scan

Run grep patterns in parallel (up to `--max-parallel-repos` repos).

**Path exclusions** — apply to every grep:
```
.git/  .venv/  node_modules/  __pycache__/  *.pyc  dist/  build/
docs/  examples/  fixtures/  _golden_path_validate/  migrations/  *.generated.*  vendored/
```

**prohibited-patterns** (CRITICAL):
```bash
grep -r "ONEX_EVENT_BUS_TYPE=inmemory\|OLLAMA_BASE_URL" \
  --include="*.py" --include="*.sh" \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=docs --exclude-dir=fixtures \
  src/ 2>/dev/null || true
```

**hardcoded-topics** (ERROR in src/, WARNING in tests/):
```bash
grep -r '"onex\.' \
  --include="*.py" \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=docs --exclude-dir=fixtures \
  src/ tests/ 2>/dev/null || true
```
Exclude lines that import from contract.yaml or are inside enum definitions.

**phantom-callables** (ERROR — requires multi-location verification):
Grep for lines in SKILL.md / prompt.md files matching `\w+\(\)` or `call \w+` in imperative context (not in code blocks, not in prose descriptions, not in example sections).
For each candidate identifier, verify presence in:
1. `plugins/onex/skills/_lib/`
2. `plugins/onex/skills/_bin/`
3. Any `.py` file under `plugins/`
If absent from all 3: HIGH confidence phantom-callable.
If found in 1+: skip (not a phantom).

**compat-shims** (WARNING — src/ only):
```bash
grep -r "# removed\|# backwards.compat\|_unused_" \
  --include="*.py" \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs --exclude-dir=fixtures \
  src/ 2>/dev/null || true
```

**empty-impls** (WARNING — src/ only, skip Abstract/Protocol/stub/__init__):
```bash
grep -rn "^\s*pass$" \
  --include="*.py" \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs \
  src/ 2>/dev/null || true
```
Post-filter: skip files matching `*Abstract*`, `*Protocol*`, `*stub*`, `*__init__*`.

**todo-fixme** (INFO — src/ only):
```bash
grep -rn "TODO\|FIXME\|HACK" \
  --include="*.py" \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs \
  src/ 2>/dev/null || true
```

## Phase 2: Triage

For each finding, create a `ModelSweepFinding`:
```python
{
  "repo": str,
  "path": str,
  "line": int,
  "check": str,
  "message": str,
  "severity": str,   # CRITICAL | ERROR | WARNING | INFO
  "confidence": str, # HIGH | MEDIUM | LOW
  "autofixable": bool,
  "ticketable": bool,
}
```

Apply triage rules:
- `prohibited-patterns`: CRITICAL, HIGH, autofixable=false, ticketable=true
- `hardcoded-topics` in src/: ERROR, HIGH, ticketable=true
- `hardcoded-topics` in tests/: WARNING, MEDIUM, ticketable=false
- `phantom-callables` confirmed missing (3 locations checked): ERROR, HIGH, ticketable=true
- `phantom-callables` ambiguous (1 location checked): ERROR, MEDIUM, ticketable=false
- `compat-shims`: WARNING, MEDIUM, ticketable=false
- `empty-impls`: WARNING, MEDIUM, ticketable=false
- `todo-fixme`: INFO, LOW, ticketable=false

**Fingerprint**: `f"{repo}:{path}:{check}:{str(line // 10 * 10)}"`

**Dedup**: Load `~/.claude/aislop-sweep/latest/findings.json` if exists.
Mark `finding.new = fingerprint not in prior_fingerprints`.
Save to `~/.claude/aislop-sweep/<run_id>/findings.json`.

If no findings → emit `ModelSkillResult(status=clean)` and exit.

## Phase 3: Ticket Creation

IF `--dry-run`:
  Print findings table grouped by check category and confidence tier:
  ```
  CHECK                REPO              PATH                 SEVERITY   CONFIDENCE
  prohibited-patterns  omniclaude        src/foo.py           CRITICAL   HIGH
  hardcoded-topics     omnibase_core     src/bar.py           ERROR      HIGH
  ...
  ```
  Print: "Dry run complete. <N> findings across <M> repos. No tickets created."
  **EXIT** — do not proceed to ticket creation or auto-fix.

IF `--ticket`:
  For each finding group where `ticketable=true AND new=true AND severity>=threshold`:
    Create Linear ticket:
    - Title: `aislop: <check_family> in <repo>:<path>`
    - Description: list all findings in the group
    - Label: `aislop-sweep`
    - Project: Active Sprint
    At most 1 ticket per group key `(repo, check_family, path)`.
    CRITICAL findings always get their own ticket.

## Phase 4: Auto-Fix

IF `--auto-fix`:
  Narrow allowlist only:
  - Missing SPDX headers → `onex spdx fix src tests scripts examples`
  - `# removed` on blank line → safe to remove

  NOT auto-fixed:
  - compat-shims with non-trivial content
  - `_unused_` variables (may be interface placeholders)
  - Empty `pass` statements (may be abstract stubs)

  After fix: re-grep to confirm removal. Commit + PR per repo.

## Phase 5: Summary

Post to Slack (best-effort):
```
aislop-sweep complete. Run: <run_id>
Repos: <N> scanned
Total findings: <N> | CRITICAL: <N> | ERROR: <N> | WARNING: <N> | INFO: <N>
Tickets created: <N> | Auto-fixed: <N>
```

Emit ModelSkillResult:
```json
{
  "skill": "aislop-sweep",
  "status": "clean | findings | partial | error",
  "run_id": "<run_id>",
  "repos_scanned": <N>,
  "total_findings": <N>,
  "by_severity": {"CRITICAL": 0, "ERROR": 0, "WARNING": 0, "INFO": 0},
  "by_check": {
    "phantom-callables": 0,
    "compat-shims": 0,
    "prohibited-patterns": 0,
    "hardcoded-topics": 0,
    "todo-fixme": 0,
    "empty-impls": 0
  },
  "tickets_created": <N>,
  "auto_fixed": <N>
}
```
