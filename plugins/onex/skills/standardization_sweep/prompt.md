# Standardization Sweep Orchestration

You are the standardization-sweep orchestrator. This prompt defines the complete execution logic.

**Execution mode: FULLY AUTONOMOUS.**
- Without `--dry-run`: execute all phases immediately after triage (no questions).
- `--dry-run` is the only preview mechanism.

## Initialization

When `/standardization-sweep [args]` is invoked:

1. **Announce**: "I'm using the standardization-sweep skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: all Python repos (see constant below)
   - `--checks <list>` — default: all (ruff,mypy,spdx,type-unions,pip-usage)
   - `--dry-run` — default: false
   - `--auto-fix` — default: false
   - `--severity-threshold <level>` — default: WARNING
   - `--max-parallel-repos <n>` — default: 3
   - `--max-parallel-fix <n>` — default: 2

3. **Python repo list** (hardcoded constant — do not discover at runtime):
   ```
   PYTHON_REPOS = [
     "omniclaude", "omnibase_core", "omnibase_infra", "omnibase_spi",
     "omniintelligence", "omnimemory", "omninode_infra",
     "onex_change_control", "omnibase_compat"
   ]
   ```

4. **Generate run_id**: `<YYYYMMDD-HHMMSS>-<random6>` (e.g., `20260317-120000-a1b`)

5. **Resolve repo list**: If `--repos` provided, use that subset; otherwise use full PYTHON_REPOS.

6. **Resolve check set**: If `--checks` provided, use that subset; otherwise use all 5.

## Phase 1: Scan

Run checks in parallel (up to `--max-parallel-repos` repos at a time).

**Path exclusions** — apply to every grep and scan:
```
.git/  .venv/  node_modules/  __pycache__/  *.pyc  dist/  build/
docs/  examples/  fixtures/  _golden_path_validate/  migrations/  *.generated.*  vendored/
```

For each repo, in the omni_home bare clone at `/Volumes/PRO-G40/Code/omni_home/<repo>/`: <!-- local-path-ok -->

**ruff check:**
```bash
cd /Volumes/PRO-G40/Code/omni_home/<repo>  # local-path-ok
uv run ruff check src/ --output-format json 2>/dev/null || true
```
Parse JSON output. Each entry: `{path, row, col, code, message}`.

**mypy check:**
```bash
cd /Volumes/PRO-G40/Code/omni_home/<repo>  # local-path-ok
uv run mypy src/ --strict --output json 2>/dev/null || true
```
Parse output. Each error line: `{file}:{line}: error: {message}`.

**spdx check:**
```bash
cd /Volumes/PRO-G40/Code/omni_home/<repo>  # local-path-ok
onex spdx fix --check src tests scripts examples 2>&1 || true
```
Lines containing "missing" indicate files needing SPDX headers.

**type-unions check** (grep, excluding scripts/):
```bash
cd /Volumes/PRO-G40/Code/omni_home/<repo>  # local-path-ok
grep -r "Optional\[|Union\[" src/ --include="*.py" -n \
  --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=scripts \
  2>/dev/null || true
```
Each match: `{file}:{line}:{content}`.

**pip-usage check** (grep, excluding tests/):
```bash
cd /Volumes/PRO-G40/Code/omni_home/<repo>  # local-path-ok
grep -r "^pip install\|^python " scripts/ --include="*.sh" --include="*.py" -n \
  --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=tests \
  2>/dev/null || true
```

Collect all findings into `repo_results[repo]`. On scan error, set `repo_results[repo] = None`.

## Phase 2: Triage

For each finding, create a `ModelSweepFinding`:
```python
{
  "repo": str,
  "path": str,       # repo-relative
  "line": int,       # 0 if whole-file
  "check": str,      # ruff | mypy | spdx | type-unions | pip-usage
  "message": str,
  "severity": str,   # CRITICAL | ERROR | WARNING | INFO
  "confidence": str, # HIGH | MEDIUM | LOW
  "autofixable": bool,
  "ticketable": bool,
}
```

**Severity mapping:**
- `ruff`: WARNING (autofixable=true for most codes)
- `mypy`: ERROR (autofixable=false)
- `spdx`: WARNING (autofixable=true)
- `type-unions`: WARNING (autofixable=false — requires judgment)
- `pip-usage`: INFO (autofixable=false)

**Classification:**
- `TRIVIAL_AUTO_FIX`: autofixable=true (ruff violations, missing SPDX)
- `REQUIRES_FIX_AGENT`: mypy errors, type-union violations
- `INFORMATIONAL`: pip-usage, INFO severity

**ticketable**: confidence=HIGH AND severity>=WARNING AND NOT autofixable

**Fingerprint:**
```python
fingerprint = f"{repo}:{path}:{check}:{symbol_or_line_bucket}"
# symbol_or_line_bucket: str(line // 10 * 10)
```

**Dedup**: Load `~/.claude/standardization-sweep/latest/findings.json` if it exists.
Mark `finding.new = fingerprint not in prior_fingerprints`.
Save all findings to `~/.claude/standardization-sweep/<run_id>/findings.json`.

If no findings → emit `ModelSkillResult(status=clean)` and exit.

## Phase 3: Report / Dry-Run Exit

IF `--dry-run`:
  Print per-repo summary table:
  ```
  REPO              ruff  mypy  spdx  type-unions  pip-usage  TOTAL
  omniclaude           5     0     2            3          0     10
  omnibase_core        0     1     0            0          0      1
  ```
  Print: "Dry run complete. 11 violations found across 2 repos. No fixes applied."
  Exit (do not proceed to Phase 4 or 5).

## Phase 4: Auto-Fix

IF `--auto-fix`:
  For each repo with TRIVIAL findings:

  **ruff auto-fix:**
  ```bash
  cd /Volumes/PRO-G40/Code/omni_worktrees/std-sweep-<run_id>/<repo>  # local-path-ok
  uv run ruff check --fix src/
  uv run ruff format src/
  ```

  **spdx auto-fix:**
  ```bash
  onex spdx fix src tests scripts examples
  ```

  Re-scan after fix to verify TRIVIAL findings are RESOLVED.
  Commit fixed files: `chore: auto-fix ruff + spdx violations [std-sweep-<run_id>]`

## Phase 5: Fix Agent Dispatch (DISPATCH)

For each repo with REQUIRES_FIX_AGENT findings (parallel, up to `--max-parallel-fix`):

  1. Create worktree:
     ```bash
     git -C /Volumes/PRO-G40/Code/omni_home/<repo> worktree add \  # local-path-ok
       /Volumes/PRO-G40/Code/omni_worktrees/std-sweep-<run_id>/<repo> \  # local-path-ok
       -b std-sweep-<run_id>-<repo>
     ```

  2. Dispatch polymorphic-agent:
     "In the worktree at `/Volumes/PRO-G40/Code/omni_worktrees/std-sweep-<run_id>/<repo>/`, <!-- local-path-ok -->
      resolve these findings: [findings list]. Commit, create PR, enable auto-merge."

  3. After agent completes, remove worktree:
     ```bash
     git -C /Volumes/PRO-G40/Code/omni_home/<repo> worktree remove \  # local-path-ok
       /Volumes/PRO-G40/Code/omni_worktrees/std-sweep-<run_id>/<repo>  # local-path-ok
     ```

## Phase 6: Summary

Post to Slack (best-effort):
```
standardization-sweep complete. Run: <run_id>
Repos: 9 scanned, <N> with violations
Total violations: <N> | Auto-fixed: <N> | Fix agents dispatched: <N>
PRs: [list of PR links]
```

Emit ModelSkillResult:
```json
{
  "skill": "standardization-sweep",
  "status": "clean | violations_found | partial | error",
  "run_id": "<run_id>",
  "repos_scanned": 9,
  "repos_failed": 0,
  "total_violations": <N>,
  "trivial_auto_fixed": <N>,
  "fix_agents_dispatched": <N>,
  "prs_created": <N>,
  "by_repo": {}
}
```
