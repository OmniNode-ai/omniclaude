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
   - `--checks <list>` — default: all (ruff,mypy,spdx,type-unions,pip-usage,ci-health)
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

6. **Resolve check set**: If `--checks` provided, use that subset; otherwise use all 6.

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
uv run onex spdx fix --check . 2>&1 || true
```
Lines containing "NEEDS FIX:" indicate files needing SPDX headers.
Exit code 1 if any files need fixing; 0 if clean.

**type-unions check** (ruff UP007 — AST-aware, no docstring false positives):
```bash
cd /Volumes/PRO-G40/Code/omni_home/<repo>  # local-path-ok
uv run ruff check src/ --select UP007 --output-format json 2>/dev/null || true
```
Parse JSON output. Each entry: `{path, row, col, code, message}`. code will be `UP007` (use X | Y instead of Union[X, Y]) or `UP006` (use type instead of Type).

**pip-usage check** (grep, excluding tests/):
```bash
cd /Volumes/PRO-G40/Code/omni_home/<repo>  # local-path-ok
grep -r "^pip install\|^python " scripts/ --include="*.sh" --include="*.py" -n \
  --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=tests \
  2>/dev/null || true
```

**ci-health check** (verify blocking mypy + ruff UP007 in CI):
```bash
cd /Volumes/PRO-G40/Code/omni_home/<repo>  # local-path-ok
python3 -c "
import os, glob, re, sys

workflows = glob.glob('.github/workflows/*.yml') + glob.glob('.github/workflows/*.yaml')
findings = []

has_blocking_mypy = False
has_up007_check = False

for wf in workflows:
    content = open(wf).read()
    # Explicit suppression: repo certifies equivalent enforcement
    if 'ci-health-ok' in content:
        has_blocking_mypy = True
        has_up007_check = True
        break
    # Blocking mypy: 'mypy' present and NOT accompanied by '|| true' on same line
    for line in content.splitlines():
        if re.search(r'\bmypy\b', line) and '|| true' not in line and '#' not in line.split('mypy')[0]:
            has_blocking_mypy = True
    # ruff UP007: ruff invoked with UP007 or UP006 in select
    if re.search(r'ruff.*UP007|ruff.*UP006|ruff.*--select.*UP', content):
        has_up007_check = True

if not has_blocking_mypy:
    findings.append('ci-health:mypy-not-blocking: No blocking mypy job found in CI')
if not has_up007_check:
    findings.append('ci-health:no-up007-check: No ruff UP007 check found in CI')

for f in findings:
    print(f)
sys.exit(1 if findings else 0)
" 2>/dev/null || true
```
Each output line is a finding: `ci-health:{code}: {message}`.

**CI-health policy**: This check enforces convergence on ONE explicit standards workflow
posture visible in each repo's `.github/workflows/` directory:

  1. A blocking mypy job — present in a workflow file, not guarded with `|| true`,
     and reachable under `push` or `pull_request` triggers.
  2. A blocking ruff UP007/UP006 check — explicit `--select UP007` or `--select UP006`
     in a workflow step, reachable under `push` or `pull_request` triggers.

This is NOT a theorem about whether equivalent enforcement exists elsewhere.
If your repo achieves equivalent enforcement via a non-standard path (reusable action,
wrapper script, pre-commit CI), it does NOT satisfy ci-health automatically.
You must either:
  a) Add the explicit canonical check shape, OR
  b) Add a suppression comment to the workflow file: `# ci-health-ok: <ticket-or-reason>`

**Suppression discipline**: suppressions are waiver tokens, not permanent amnesty.
Include a ticket reference or expiry intent. Example:
  `# ci-health-ok: OMN-XXXX — using reusable-standards-gate.yml (equivalent enforcement)`

Stale suppressions with no ticket reference should be flagged in future audits.

Collect all findings into `repo_results[repo]`. On scan error, set `repo_results[repo] = None`.

## Phase 2: Triage

For each finding, create a `ModelSweepFinding`:
```python
{
  "repo": str,
  "path": str,       # repo-relative
  "line": int,       # 0 if whole-file
  "check": str,      # ruff | mypy | spdx | type-unions | pip-usage | ci-health
  "message": str,
  "severity": str,   # CRITICAL | ERROR | WARNING | INFO
  "confidence": str, # HIGH | MEDIUM | LOW
  "autofixable": bool,
  "ticketable": bool,
  "fingerprint": str,  # "{repo}:{path}:{check}:{line_bucket}"
  "new": bool,         # true if fingerprint was not in prior run
}
```

**Severity mapping:**
- `ruff`: WARNING (autofixable=true for most codes)
- `mypy`: ERROR (autofixable=false)
- `spdx`: WARNING (autofixable=true)
- `type-unions`: WARNING (autofixable=true — ruff UP007 is auto-fixable via `ruff check --fix --select UP007`)
- `pip-usage`: INFO (autofixable=false)
- `ci-health`: ERROR (autofixable=false — requires CI workflow addition per repo)

**Classification:**
- `TRIVIAL_AUTO_FIX`: autofixable=true (ruff violations, missing SPDX, type-union UP007 violations)
- `REQUIRES_FIX_AGENT`: mypy errors, ci-health violations
- `INFORMATIONAL`: pip-usage, INFO severity

**ticketable**: confidence=HIGH AND severity>=WARNING AND NOT autofixable

**Fingerprint:**
```python
fingerprint = f"{repo}:{path}:{check}:{symbol_or_line_bucket}"
# symbol_or_line_bucket: str(line // 10 * 10)
```

**Dedup + Persist**:

1. Load prior fingerprints with graceful degradation:
   ```python
   import json, os
   latest = os.path.expanduser("~/.claude/standardization-sweep/latest")
   prior_fps = set()
   if os.path.exists(latest):
       try:
           data = json.load(open(latest))
           prior_fps = {f["fingerprint"] for f in data.get("findings", []) if "fingerprint" in f}
       except (json.JSONDecodeError, KeyError, OSError) as e:
           print(f"[sweep] Warning: could not load prior findings ({e}); treating all as new")
   ```
   If the prior file is missing, unreadable, or malformed, `prior_fps` stays empty and all current findings are marked `new=True`. The sweep does not fail.

2. For each assembled `ModelSweepFinding`, set:
   `finding["new"] = finding["fingerprint"] not in prior_fps`

3. Persist current run — stable versioned schema:
   ```python
   import json, os, tempfile
   from datetime import datetime
   run_dir = os.path.expanduser(f"~/.claude/standardization-sweep/{run_id}")
   os.makedirs(run_dir, exist_ok=True)
   out_path = f"{run_dir}/findings.json"

   # all_findings is the list of ModelSweepFinding dicts from Phase 2 (dicts, not objects)
   payload = {
       "schema_version": "1.0.0",
       "run_id": run_id,
       "timestamp": datetime.utcnow().isoformat() + "Z",
       "findings": all_findings,   # each is already a dict with required fields
   }

   # Atomic write: write to temp file then rename to avoid corrupt state on interrupt
   tmp_fd, tmp_path = tempfile.mkstemp(dir=run_dir, suffix=".json.tmp")
   try:
       with os.fdopen(tmp_fd, "w") as f:
           json.dump(payload, f, indent=2)
       os.replace(tmp_path, out_path)   # atomic on POSIX
   except Exception:
       os.unlink(tmp_path)
       raise

   # Update latest symlink (replace existing symlink or stale file)
   latest = os.path.expanduser("~/.claude/standardization-sweep/latest")
   if os.path.lexists(latest):   # handles broken symlinks too
       os.remove(latest)
   os.symlink(out_path, latest)
   ```

The executing agent performs these steps inline after triage, using Python in the same session context. `all_findings` is the list of `ModelSweepFinding` dicts assembled during Phase 2.

**`findings.json` stable artifact contract (`schema_version: "1.0.0"`):**

```
Top-level fields (required):
  schema_version  string   always "1.0.0"
  run_id          string   e.g. "20260318-120000-a1b"
  timestamp       string   UTC ISO-8601 e.g. "2026-03-18T12:00:00Z"
  findings        array    list of finding objects

Finding object (required fields):
  repo            string   repo name e.g. "omniclaude"
  path            string   repo-relative file path
  line            int      0 if whole-file finding
  check           string   ruff | mypy | spdx | type-unions | pip-usage | ci-health
  message         string   human-readable description
  severity        string   CRITICAL | ERROR | WARNING | INFO
  confidence      string   HIGH | MEDIUM | LOW
  autofixable     bool
  ticketable      bool
  fingerprint     string   "{repo}:{path}:{check}:{line_bucket}"
  new             bool     true if fingerprint was not in prior run
```

Sort order: deterministic by `(repo, path, check, line)`. If any required field is missing at
write time, the skill fails with an explicit error rather than writing a partial artifact.

The `new` field is set during Phase 2 triage, BEFORE both display (dry-run table) and
persistence. The persisted artifact always matches exactly what was shown to the operator.

If no findings → emit `ModelSkillResult(status=clean)` and exit.

## Phase 3: Report / Dry-Run Exit

IF `--dry-run`:
  Print per-repo summary table:
  ```
  REPO              ruff  mypy  spdx  type-unions  pip-usage  ci-health  TOTAL
  omniclaude           5     0     2            3          0          0     10
  omnibase_core        0     1     0            0          0          1      2
  ```
  Print: "Dry run complete. 12 violations found across 2 repos. No fixes applied."
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

  **type-union auto-fix (ruff UP007):**
  ```bash
  uv run ruff check --fix --select UP007 src/
  ```

  **spdx auto-fix:**
  ```bash
  uv run onex spdx fix .
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
