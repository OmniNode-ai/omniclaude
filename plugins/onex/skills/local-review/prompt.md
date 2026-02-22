# Local Review Orchestration

You are executing the local-review skill. This prompt defines the complete orchestration logic.

---

## Arguments

Parse arguments from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--uncommitted` | false | Only review uncommitted changes (ignore committed) |
| `--since <ref>` | auto-detect | Base ref for diff (branch/commit) |
| `--max-iterations <n>` | 10 | Maximum review-fix cycles |
| `--files <glob>` | all | Glob pattern to limit scope |
| `--no-fix` | false | Report only, don't attempt fixes |
| `--no-commit` | false | Fix but don't commit (stage only) |
| `--checkpoint <ticket:run>` | none | Write checkpoint after each iteration (format: `ticket_id:run_id`) |
| `--required-clean-runs <n>` | 2 | Consecutive clean runs required before passing (min 1) |
| `--flag-false-positive <pattern>` | none | Write a pending_review suppression entry to ~/.claude/review-suppressions.yml (exits immediately after writing) |

**Examples**:
```bash
/local-review                                    # Review all changes since base branch
/local-review --uncommitted                      # Only uncommitted changes
/local-review --since main                       # Explicit base
/local-review --max-iterations 5                 # Limit iterations
/local-review --files "src/**/*.py"              # Specific files only
/local-review --no-fix                           # Report only mode
/local-review --required-clean-runs 1            # Fast iteration (skip confirmation pass)
/local-review --flag-false-positive "asyncio_mode"  # Flag a false positive for suppression
```

---

## Phase 0: Pre-Existing Issue Scan

Phase 0 runs BEFORE the diff review loop. It detects and handles pre-existing lint/mypy
failures so they don't surface as CI surprises after the feature work is merged.

**Key invariant**: Pre-existing fixes are committed separately from the feature work.
NEVER mix pre-existing fixes with the feature branch changes.

### Phase 0 Procedure

```
Phase 0: Pre-existing issue scan
  1. Run pre-commit run --all-files against the current HEAD state (i.e. before any uncommitted
     fixes are applied; do NOT stash or alter the working tree to run this step)
  2. Run mypy src/ --strict (or repo-equivalent detected from pyproject.toml)
  3. Classify each failure:
       - AUTO-FIX if: ≤10 files touched AND same subsystem AND low-risk change
       - DEFER if any criterion fails (>10 files, architectural, unrelated subsystem)
  4. For AUTO-FIX:
       - Apply fixes
       - Commit as: chore(pre-existing): fix pre-existing lint/type errors
       - This commit is separate from all feature commits
  5. For DEFER:
       - Auto-file a follow-up Linear sub-ticket (if Linear MCP available)
       - Note in session: "Pre-existing issues deferred to {ticket_id}: {count} issues"
       - Add deferred issues to PR description note section
  6. Write Phase 0 results to session notes (session notes = the structured context block
     injected into the Claude session via the context-injection subsystem)
  7. Proceed to Phase 1 (Initialize)
```

### Auto-Fix Criteria (ALL must be true)

| Criterion | Value |
|-----------|-------|
| Files touched | ≤ 10 |
| Subsystem | Same as the feature work (determine by inspecting `git diff {base}..HEAD --name-only`; the top-level directory prefix of the majority of changed files identifies the subsystem — e.g. `src/omniclaude/hooks/` or `plugins/onex/skills/`) |
| Risk level | Low (formatting, import ordering, type annotation style) |

### Phase 0 Output in Session Notes

```markdown
## Phase 0 — Pre-existing Issues — {timestamp}

### Auto-Fixed (committed separately)
- src/api.py: missing type annotation on `user_id` param
- src/utils.py: ruff E501 line too long

### Deferred to follow-up
- src/legacy/: 23 issues across 15 files (too broad — created OMN-XXXX)
```

---

## Phase 1: Initialize

**1. Parse arguments** from `$ARGUMENTS`

**2. Detect base reference** (if `--since` not provided):
```bash
# Try to find the merge-base with remote main/master
git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD origin/master 2>/dev/null || {
    if git rev-parse --verify HEAD~10 >/dev/null 2>&1; then
        echo "Warning: Could not find merge-base, using HEAD~10" >&2
        echo "HEAD~10"
    else
        echo "Warning: Could not find merge-base, using initial commit" >&2
        git rev-list --max-parents=0 HEAD 2>/dev/null || echo "HEAD"
    fi
}
```

**3. Initialize tracking state**:
```
iteration = 0
max_iterations = <from args or 10>
commits_made = []
total_issues_fixed = 0
nit_count = 0  # Track deferred nits for final summary
failed_fixes = []  # Track {file, line, description, fingerprint, consecutive_count} of issues that failed to fix (do not retry)
consecutive_clean_runs = 0
required_clean_runs = <from args or 2>
last_clean_signature = None
retry_count = 0  # Transient failure retry counter; resets to 0 on any successful iteration
quality_gate = {"status": "failed", "required_clean_runs": required_clean_runs,
                "consecutive_clean_runs": 0, "final_signature": None,
                "blocking_issue_count": 0, "nit_count": 0}
suppression_registry = []  # Loaded from ~/.claude/review-suppressions.yml on first use
```

**3a. Load suppression registry** (non-blocking, runs after step 3):
```python
import yaml
from pathlib import Path

_registry_path = Path.home() / ".claude" / "review-suppressions.yml"
if _registry_path.exists():
    try:
        _registry_data = yaml.safe_load(_registry_path.read_text()) or {}
        suppression_registry = [
            s for s in _registry_data.get("suppressions", [])
            if s.get("status") == "active"
        ]
    except Exception as _e:
        print(f"Warning: Could not load suppression registry: {_e}")
        suppression_registry = []
```

**4. Display configuration**:
```
## Review Configuration

**Base**: {base_ref}
**Scope**: {all changes | uncommitted only | specific files}
**Max iterations**: {max_iterations}
**Required clean runs**: {required_clean_runs}
**Mode**: {fix & commit | fix only | report only}
```

---

### Helper: compute_run_signature

```python
def compute_run_signature(base_ref, files):
    """Deterministic signature of review inputs."""
    import hashlib
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "--short=7", "HEAD"], text=True
    ).strip()
    content = f"{head_sha}|{base_ref}|{'|'.join(sorted(files))}"
    return hashlib.sha256(content.encode()).hexdigest()[:12]
```

---

## Phase 2: Review Loop

**For each iteration until clean or max reached:**

### Step 2.1: Gather Changes

This step uses a two-step diff approach to capture all relevant changes:
1. Committed changes since base ref (for `--uncommitted=false`)
2. Uncommitted changes in working tree (always checked)

```bash
# Get changed files
if --uncommitted:
    # Capture both unstaged and staged (but uncommitted) changes
    unstaged=$(git diff --name-only)
    staged=$(git diff --cached --name-only)
    files=$(echo -e "$unstaged\n$staged" | sort -u | grep -v '^$')
else:
    # Combine committed and uncommitted changes, then deduplicate
    committed=$(git diff --name-only {base_ref}..HEAD)
    # Capture both unstaged and staged (but uncommitted) changes
    unstaged=$(git diff --name-only)
    staged=$(git diff --cached --name-only)
    uncommitted=$(echo -e "$unstaged\n$staged" | sort -u | grep -v '^$')
    files=$(echo -e "$committed\n$uncommitted" | sort -u | grep -v '^$')
fi

# Apply file filter if --files specified
# Filter to matching glob pattern
```

**If glob matches zero files** (when `--files` specified):
- Report "No files match pattern '{glob}'" and exit.

**If no changes**:
- If `iteration == 0` and `commits_made == []`: Report "No changes to review. Working tree clean." and exit.
- Otherwise: Skip to Phase 3 (show summary of work completed in previous iterations).

### Step 2.2: Run Code Review

Dispatch a `polymorphic-agent` with strict keyword-based classification (matching onex pr-review standards):

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` — with the `onex:` prefix. Using `"polymorphic-agent"` without it immediately fails: `Error: Agent type 'polymorphic-agent' not found`. Do NOT use `feature-dev:code-reviewer` or other specialized review agents.

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Review iteration {iteration+1} changes",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent. Do NOT delegate to feature-dev:code-reviewer.

You are reviewing local code changes for production readiness.

## Changes to Review

**Base ref**: {base_ref}
**Files to review**: {file_list}
**Mode**: {--uncommitted | all changes}

# If --uncommitted mode:
Run: git diff -- {files}  # Unstaged changes
Also run: git diff --cached -- {files}  # Staged but uncommitted changes

# If all changes mode (default):
Run: git diff {base_ref}..HEAD -- {files}  # Committed changes
Also run: git diff -- {files}  # Unstaged changes
Also run: git diff --cached -- {files}  # Staged but uncommitted changes

Read each changed file fully to understand context.

## Priority Classification (Keyword-Based)

Classify issues using these keyword triggers (from onex pr-review):

### CRITICAL (Must Fix - BLOCKING)
Keywords: `security`, `vulnerability`, `injection`, `data loss`, `crash`, `breaking change`, `authentication bypass`, `authorization`, `secrets exposed`
- Security vulnerabilities (SQL injection, XSS, command injection)
- Data loss or corruption risks
- System crashes or unhandled exceptions that halt execution
- Breaking changes to public APIs

### MAJOR (Should Fix - BLOCKING)
Keywords: `bug`, `error`, `incorrect`, `wrong`, `fails`, `broken`, `performance`, `missing validation`, `race condition`, `memory leak`
- Logic errors that produce incorrect results
- Missing error handling for likely failure cases
- Performance problems (N+1 queries, unbounded loops)
- Missing or failing tests for critical paths
- Race conditions or concurrency bugs

### MINOR (Should Fix - BLOCKING)
Keywords: `should`, `missing`, `incomplete`, `edge case`, `documentation`
- Missing edge case handling
- Incomplete error messages
- Missing type hints on public APIs
- Code that works but violates project conventions (check CLAUDE.md)

### NIT (Optional - NOT blocking)
Keywords: `nit`, `consider`, `suggestion`, `optional`, `style`, `formatting`, `nitpick`
- Code style preferences
- Variable naming suggestions
- Minor refactoring opportunities
- Formatting inconsistencies

## Merge Requirements (STRICT)

Ready to merge ONLY when:
- ALL Critical issues resolved
- ALL Major issues resolved
- ALL Minor issues resolved
- Nits are OPTIONAL (nice to have)

NOT ready if ANY Critical/Major/Minor remain

## Output Format

Return issues in this exact JSON format:
```json
{
  \"critical\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}],
  \"major\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}],
  \"minor\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}],
  \"nit\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}]
}
```

**Rules**:
- Be specific: include file:line references
- Explain WHY each issue matters
- Include the keyword that triggered classification
- Do NOT mark nitpicks as Critical/Major/Minor
- Do NOT use confidence scoring - use keyword classification only

If no issues found, return: {\"critical\": [], \"major\": [], \"minor\": [], \"nit\": []}
"
)
```

**JSON Parsing and Validation**:
1. Parse the response as JSON
2. Validate structure: must have `critical`, `major`, `minor`, `nit` keys, each being an array
3. Validate each issue: must have `file` (string), `line` (positive integer), `description` (string), `keyword` (string)
4. **Partial validation**: Skip individual malformed issues but continue processing valid ones. Only fall back to text extraction if ALL issues are malformed or JSON structure is invalid.

**Text Extraction Fallback**: If JSON parsing/validation fails **OR** all parsed issues are malformed/filtered out:
1. Try to extract issues from markdown/text format using these patterns:
   - `**{file}:{line}** - {description}` (markdown bold format)
   - `{file}:{line}: {description}` (compiler-style format)
   - `- {file}:{line} - {description}` (list format)
   - **Validate line numbers**: Extracted `line` must be a positive integer; skip extractions with non-integer or negative values
2. Assign severity and keyword based on description content:
   - "critical/security/crash/injection/vulnerability" -> critical, keyword="extracted:critical"
   - "bug/error/logic/incorrect/fails/broken" -> major, keyword="extracted:major"
   - "should/missing/incomplete/edge case/documentation" -> minor, keyword="extracted:minor"
   - "nit/consider/suggestion/optional/style/formatting" -> nit, keyword="extracted:nit"
   - else -> minor, keyword="extracted:unknown"
3. **If extraction succeeds** (finds at least one issue):
   - Use extracted issues and proceed normally to Step 2.3 (display issues)
4. **If extraction fails** (no recognizable patterns):
   - Log the raw response for debugging
   - Mark iteration as `PARSE_FAILED` (not "clean"); set `last_error = "could not parse review response"`
   - Display: "Warning: Review response could not be parsed. {retry_count < 2 ? f'Retry {retry_count+1}/2...' : 'Retry limit reached — hard exit.'}"
   - Proceed to Step 2.3 where `PARSE_FAILED` triggers retry logic (hard exit after 2 retries)
5. On `PARSE_FAILED` after retry exhaustion, the final status MUST be "Parse failed - manual review needed" (never "Clean")

**Agent Failure Handling**: If the review agent crashes, times out, or returns an error:
1. Log the error with details (timeout duration, error message, etc.)
2. Mark iteration as `AGENT_FAILED` (not "clean" or "parse failed"); set `last_error = {error}`
3. Display: "Warning: Review agent failed: {error}. {retry_count < 2 ? f'Retry {retry_count+1}/2...' : 'Retry limit reached — hard exit.'}"
4. **Continue to Step 2.3** (AGENT_FAILED will be handled there with retry logic; hard exit after 2 retries)

### Step 2.3: Display Issues and Handle Error States

**Guard for error states**: If `PARSE_FAILED` or `AGENT_FAILED` is set, skip directly to the early exit conditions below (do not attempt to display issues, as the `issues` dict may not exist).

**Apply suppression registry** (before displaying findings):
```python
import fnmatch

suppressed = []  # {file, line, description, suppression_id, suppression_reason}

def _is_suppressed(issue, suppression_registry):
    for s in suppression_registry:
        if s.get("status") != "active":
            continue
        pattern = s.get("pattern", "")
        file_glob = s.get("file_glob", "*")
        if pattern and pattern in issue["description"]:
            if fnmatch.fnmatch(issue["file"], file_glob):
                return s
    return None

for severity in ["critical", "major", "minor", "nit"]:
    remaining = []
    for issue in issues[severity]:
        match = _is_suppressed(issue, suppression_registry)
        if match:
            suppressed.append({
                "file": issue["file"],
                "line": issue["line"],
                "description": issue["description"],
                "suppression_id": match.get("id", "?"),
                "suppression_reason": match.get("reason", ""),
            })
        else:
            remaining.append(issue)
    issues[severity] = remaining
```

```markdown
## Review Iteration {iteration+1}

### CRITICAL ({count}) - BLOCKING
- **{file}:{line}** - {description} [`{keyword}`]

### MAJOR ({count}) - BLOCKING
- **{file}:{line}** - {description} [`{keyword}`]

### MINOR ({count}) - BLOCKING
- **{file}:{line}** - {description} [`{keyword}`]

### NIT ({count}) - Optional
- **{file}:{line}** - {description} [`{keyword}`]

### SUPPRESSED ({len(suppressed)}) — Known False Positives
- {file}:{line} - {description} [{suppression_id}: {suppression_reason}]

**Merge Status**: {Ready | Blocked by N issues}
```

(Omit the SUPPRESSED section if `suppressed` is empty.)

**Track nit count**: After successfully parsing the review response (not on PARSE_FAILED or AGENT_FAILED),
record the final nit count: `nit_count = len(issues["nit"])` (replaces previous value, not cumulative).
This represents nits remaining at the end of the review loop.

**Early Exit Conditions** (each increments counter before exiting):

**If no Critical/Major/Minor issues** (clean run detected):
```
current_signature = compute_run_signature(base_ref, changed_files)

if last_clean_signature is not None and current_signature != last_clean_signature:
    print(f"Run signature changed ({last_clean_signature} -> {current_signature}) -> clean run counter reset to 0")
    consecutive_clean_runs = 0

consecutive_clean_runs += 1
last_clean_signature = current_signature
retry_count = 0  # Reset retry counter on any successful iteration
iteration += 1

if consecutive_clean_runs >= required_clean_runs:
    # Quality gate passed
    quality_gate = {
        "status": "passed",
        "required_clean_runs": required_clean_runs,
        "consecutive_clean_runs": consecutive_clean_runs,
        "final_signature": current_signature,
        "blocking_issue_count": 0,
        "nit_count": nit_count,
    }
    goto Phase 3  # Confirmed clean
else:
    print(f"Clean run {consecutive_clean_runs}/{required_clean_runs} -- running confirmation pass")
    goto Step 2.1  # Need another clean run to confirm
```
- Nits alone do NOT block - they are optional

**If `PARSE_FAILED` or `AGENT_FAILED`**:
```
# Retry policy: up to 2 retries before hard exit (declared in SKILL.md frontmatter)
if retry_count < 2:
    retry_count += 1
    error_type = "PARSE_FAILED" if PARSE_FAILED else "AGENT_FAILED"
    print(f"Retry {retry_count}/2 for {error_type} at iteration {iteration+1}. Reason: {last_error}")
    # Re-dispatch the review phase (goto Step 2.1 without incrementing iteration)
    goto Step 2.1
else:
    # Retry exhaustion: hard exit
    iteration += 1  # A review was attempted even though it failed
    error_type = "PARSE_FAILED" if PARSE_FAILED else "AGENT_FAILED"
    goto Phase 3  # exits with status: failed, reason: "{error_type} after 2 retries: {last_error}"
```

Note: `retry_count` resets to 0 on any successful iteration (i.e., whenever the review agent
returns a parseable response, regardless of whether issues were found).

**If `--no-fix`**:
```
iteration += 1  # A review was performed (report-only mode)
goto Phase 3
```

### Step 2.4: Fix Issues

**Reset clean counter** (blocking issues were found):
```
# Blocking issues were found -- reset clean counter
if consecutive_clean_runs > 0:
    print(f"Blocking issues found -> clean run counter reset to 0 (was {consecutive_clean_runs})")
consecutive_clean_runs = 0
last_clean_signature = None
retry_count = 0  # Review succeeded (parseable response) -- reset retry counter
```

**Pre-filter previously failed issues**:
```python
# Snapshot all issues BEFORE filtering so checkpoint fingerprints reflect the full review
_original_issues = {sev: list(lst) for sev, lst in issues.items()}

# Filter out issues that already failed in previous iterations (do not retry)
# Create set once for O(1) lookups instead of O(n*m) list comprehension
failed_fixes_set = {(f["file"], f["line"]) for f in failed_fixes}
for severity in ["critical", "major", "minor"]:
    issues[severity] = [
        issue for issue in issues[severity]
        if (issue["file"], issue["line"]) not in failed_fixes_set
    ]
```

For each severity level (critical first, then major, then minor), dispatch a `polymorphic-agent`:

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` — with the `onex:` prefix. Using `"polymorphic-agent"` without it immediately fails: `Error: Agent type 'polymorphic-agent' not found`.

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Fix {severity} issues from review",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent.

Fix the following {severity} issues:

{issues_list}

**Instructions**:
1. Read each file
2. Apply the fix
3. Verify the fix doesn't break other code
4. Do NOT commit - just make the changes

**Files to modify**: {file_list}
"
)
```

**Fix Agent Failure Handling**: If the fix agent crashes, times out, or fails:
1. Log the error with details
2. Add affected issues to `failed_fixes` list (do not retry in subsequent iterations):
   ```python
   import re as _re
   for issue in affected_issues:
       # Compute fingerprint for auto-flag tracking
       desc_keywords = "_".join(_re.findall(r'\w+', issue["description"].lower())[:5])
       line_approx = (issue["line"] // 10) * 10  # bucket to nearest 10 lines
       fingerprint = f"{issue['file']}:{line_approx}:{desc_keywords}"

       # Check if fingerprint already tracked
       existing = next((f for f in failed_fixes if f.get("fingerprint") == fingerprint), None)
       if existing:
           existing["consecutive_count"] = existing.get("consecutive_count", 1) + 1
       else:
           failed_fixes.append({
               "file": issue["file"],
               "line": issue["line"],
               "description": issue["description"],
               "fingerprint": fingerprint,
               "consecutive_count": 1,
           })
   ```
3. **Auto-flag check**: After updating `failed_fixes`, check if any fingerprint has reached the threshold:
   ```python
   AUTO_FLAG_THRESHOLD = 3
   for ff in failed_fixes:
       if ff.get("consecutive_count", 0) >= AUTO_FLAG_THRESHOLD and not ff.get("auto_flagged"):
           ff["auto_flagged"] = True  # Mark so we don't write duplicate entries on future iterations
           _write_suppression_entry(ff["file"], ff["description"], status="active",
                                    reason="Auto-flagged: 3 consecutive failed fixes")
           print(f"Auto-flagged false positive: {ff['fingerprint']} -> written to ~/.claude/review-suppressions.yml")
           # Reload registry so it's suppressed on next iteration
           suppression_registry = _reload_suppression_registry()
   ```
   (See `_write_suppression_entry` helper in Implementation Notes below.)
4. Continue to next severity level (attempt remaining fixes)
5. If ALL fixes fail:
   ```
   iteration += 1  # A review cycle was attempted but all fixes failed
   goto Phase 3    # Status: "Fix failed - {n} issues need manual attention"
   ```
6. If SOME fixes succeed: proceed to Step 2.5 to commit successful fixes, note failed issues in commit message

### Step 2.5: Stage and Commit Fixes

**Always stage fixes** (regardless of `--no-commit`):

**Note**: For multi-line commit messages, use heredoc format:
```bash
git commit -m "$(cat <<'EOF'
fix(review): [{severity}] {summary}

- Fixed: {file}:{line} - {description}
- Fixed: {file}:{line} - {description}

Review iteration: {iteration+1}/{max_iterations}
EOF
)"
```

```bash
# Stage fixed files and check for errors
git add {fixed_files}
if [ $? -ne 0 ]; then
    # Stage failed - some files may be partially staged
    # Do NOT unstage partial changes (preserve user's ability to inspect)
    # Report which files succeeded/failed for manual intervention
    iteration += 1
    stage_failed = true
    goto Phase 3  # Status: "Stage failed - check file permissions"
fi
```

**Track issues fixed** (regardless of `--no-commit`):
```
total_issues_fixed += count
```

**Commit** (if not `--no-commit`):

```bash
# Commit with descriptive message using heredoc (include failed fixes if any)
git commit -m "$(cat <<'EOF'
fix(review): [{severity}] {summary}

- Fixed: {file}:{line} - {description}
- Fixed: {file}:{line} - {description}
- FAILED: {file}:{line} - {description} (needs manual fix)

Review iteration: {iteration+1}/{max_iterations}
EOF
)"
```

**Track commit** (only count successfully fixed issues, not failed ones):
```
# count = number of successfully fixed issues (excludes items in failed_fixes)
commits_made.append({
  "hash": git rev-parse --short HEAD,
  "severity": severity,
  "summary": summary,
  "issues_fixed": count  # Excludes failed fixes
})
```

Note: `total_issues_fixed` was already incremented in the "Track issues fixed" step above.

**On commit failure**:
1. Log the error with failure reason (hooks, conflicts, permissions)
2. Leave files staged for manual intervention
3. Set `commit_failed = true` with reason
4. Increment iteration counter and exit:
   ```
   iteration += 1  # A review cycle was attempted
   goto Phase 3
   ```
5. Final status: "Commit failed - {reason}. Files staged for manual review."

This prevents re-reviewing the same changes and gives the user clear next steps.

### Step 2.5b: Write Checkpoint (OMN-2144)

After a successful commit (or stage in `--no-commit` mode), write a checkpoint if
`--checkpoint` was provided.  Checkpoint write failure is **non-blocking**.

```python
if checkpoint_arg and checkpoint_ticket_id and checkpoint_run_id:
    try:
        import subprocess as _sp
        import sys
        import os
        import json
        from pathlib import Path as _Path

        _plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
        if not _plugin_root:
            # Hardcoded known location relative to home when CLAUDE_PLUGIN_ROOT is not set
            _plugin_root = str(_Path.home() / ".claude" / "plugins" / "onex")
        _CHECKPOINT_MANAGER = os.path.join(
            _plugin_root,
            "hooks", "lib", "checkpoint_manager.py"
        )
        # Get current HEAD SHA for the checkpoint
        try:
            _head_sha = _sp.check_output(
                ["git", "rev-parse", "--short=7", "HEAD"], text=True
            ).strip()
        except Exception:
            _head_sha = "0000000"

        # Derive next attempt number from existing checkpoints.
        # This prevents collisions if the pipeline resumes after a crash
        # (where iteration + 1 could duplicate an existing attempt number).
        _list_proc = _sp.run(
            [sys.executable, _CHECKPOINT_MANAGER, "list",
             "--ticket-id", checkpoint_ticket_id,
             "--run-id", checkpoint_run_id],
            capture_output=True, text=True
        )
        _all_checkpoints = (
            json.loads(_list_proc.stdout).get("checkpoints", [])
            if _list_proc.returncode == 0 else []
        )
        _existing = [cp for cp in _all_checkpoints if cp.get("phase") == "local_review"]
        _next_attempt = str(len(_existing) + 1)

        _cp_payload = json.dumps({
            "iteration_count": iteration + 1,  # 1-based (iteration hasn't been incremented yet)
            "issue_fingerprints": [
                f"{issue['file']}:{issue['line']}"
                for severity in ["critical", "major", "minor"]
                for issue in _original_issues.get(severity, [])
            ],
            "last_clean_sha": _head_sha,
            "quality_gate": quality_gate,
        })
        # Direct subprocess to checkpoint_manager (not polymorphic-agent dispatch)
        # because checkpoint writes are non-blocking side-effects that don't need
        # agent orchestration overhead.
        _cp_cmd = [
            sys.executable, _CHECKPOINT_MANAGER, "write",
            "--ticket-id", checkpoint_ticket_id,
            "--run-id", checkpoint_run_id,
            "--phase", "local_review",
            "--attempt", _next_attempt,
            # Inline repo detection (self-contained; no cross-skill dependency on get_current_repo)
            "--repo-commit-map", json.dumps({os.path.basename(os.getcwd()): _head_sha}),
            # artifact_paths is a list[str] of file-system paths for generated outputs
            # (reports, saved files). Distinct from repo_commit_map which tracks commit
            # SHAs per repository. local-review modifies existing files via commits,
            # so no artifact paths are produced.
            "--artifact-paths", json.dumps([]),
            "--payload", _cp_payload,
        ]
        _cp_proc = _sp.run(_cp_cmd, capture_output=True, text=True, timeout=30)
        # Parse checkpoint write result from JSON stdout (exit code is always 0)
        _cp_result = json.loads(_cp_proc.stdout) if _cp_proc.stdout.strip() else {}
        if _cp_result.get("success", False):
            print(f"Checkpoint written for local_review attempt {_next_attempt}")
        else:
            _cp_err_msg = _cp_result.get("error", _cp_proc.stderr or "unknown error")
            print(f"Warning: Checkpoint write failed: {_cp_err_msg}")
    except Exception as _cp_err:
        print(f"Warning: Checkpoint write failed: {_cp_err}")
        # Non-blocking: continue pipeline
```

### Step 2.6: Check Loop Condition

**Note**: This step is ONLY reached in the normal flow (issues found -> fixed -> committed successfully).
Early exits (no issues, parse failed, no-fix mode, commit failed) have their own explicit
`iteration += 1` statements in Step 2.3 and Step 2.5 before jumping to Phase 3.

```
iteration += 1

if iteration >= max_iterations:
    # Max iterations reached
    goto Phase 3
else:
    # Continue loop
    goto Step 2.1
```

---

## Phase 3: Final Summary

```markdown
## Review Complete

**Iterations**: {iteration}
**Total issues fixed**: {total_issues_fixed}
**Commits created**: {len(commits_made)}
**Clean runs**: {consecutive_clean_runs}/{required_clean_runs}
**Quality gate**: {quality_gate["status"]}
**Nits deferred**: {nit_count} (optional)

### Commits
{for index, commit in enumerate(commits_made):}
{index + 1}. {commit.hash} - fix(review): [{commit.severity}] {commit.summary}
{end for}

**Status**: {status_indicator}
```

**Status indicators** (choose based on total_issues_fixed and mode):
- `Clean - Confirmed ({N}/{N} clean runs)` (no Critical/Major/Minor, confirmed by N consecutive clean runs)
- `Clean with nits - Confirmed ({N}/{N} clean runs)` (only nits remain, confirmed by N clean runs)
- `Max iterations reached - {n} blocking issues remain` (hit limit with Critical/Major/Minor remaining)
- `Report only - {n} blocking issues found` (--no-fix mode)
- `Changes staged - review before commit` (--no-commit mode, issues were fixed but not committed)
- `Parse failed - manual review needed` (review response couldn't be parsed)
- `Agent failed - {error}. Manual review required.` (review agent crashed/timed out)
- `Fix failed - {n} issues need manual attention` (all fix attempts failed in Step 2.4)
- `Stage failed - check file permissions` (git add failed)
- `Commit failed - {reason}. Files staged for manual review.` (commit step failed)

**Status selection logic**:
```
if parse_failed:
    "Parse failed - manual review needed"
elif agent_failed:
    "Agent failed - {error}. Manual review required."
elif fix_failed:
    "Fix failed - {n} issues need manual attention"
elif stage_failed:
    "Stage failed - check file permissions"
elif commit_failed:
    "Commit failed - {reason}. Files staged for manual review."
elif --no-fix:
    "Report only - {n} blocking issues found"
elif blocking_issues_remain:
    "Max iterations reached - {n} blocking issues remain"
elif total_issues_fixed == 0:
    # No blocking issues found to fix (only nits which are optional)
    if nits_remain:
        f"Clean with nits - Confirmed ({consecutive_clean_runs}/{required_clean_runs} clean runs)"
    else:
        f"Clean - Confirmed ({consecutive_clean_runs}/{required_clean_runs} clean runs)"
elif --no-commit:
    # Issues were fixed but not committed (staged only)
    "Changes staged - review before commit"
elif nits_remain:
    f"Clean with nits - Confirmed ({consecutive_clean_runs}/{required_clean_runs} clean runs)"
else:
    f"Clean - Confirmed ({consecutive_clean_runs}/{required_clean_runs} clean runs)"
```

---

## Implementation Notes

### Suppression Registry Helpers (OMN-2514)

> **Note**: These helpers must be defined before the Argument Parsing section because
> `--flag-false-positive` calls `_write_suppression_entry` at parse time and exits immediately.

```python
import yaml
import re as _re
from pathlib import Path
from datetime import date

_REGISTRY_PATH = Path.home() / ".claude" / "review-suppressions.yml"

def _load_registry():
    """Load raw registry dict from disk, or return empty structure."""
    if _REGISTRY_PATH.exists():
        try:
            return yaml.safe_load(_REGISTRY_PATH.read_text()) or {"version": 1, "suppressions": []}
        except Exception:
            return {"version": 1, "suppressions": []}
    return {"version": 1, "suppressions": []}

def _reload_suppression_registry():
    """Return list of active suppression entries (for use after auto-flag write)."""
    data = _load_registry()
    return [s for s in data.get("suppressions", []) if s.get("status") == "active"]

def _write_suppression_entry(file_context, description, status, reason):
    """Append a new suppression entry to the registry file."""
    data = _load_registry()
    suppressions = data.get("suppressions", [])

    # Generate next ID
    existing_ids = [s.get("id", "") for s in suppressions]
    next_num = len(suppressions) + 1
    new_id = f"fp_{next_num:03d}"
    while new_id in existing_ids:
        next_num += 1
        new_id = f"fp_{next_num:03d}"

    new_entry = {
        "id": new_id,
        "pattern": description,
        "file_glob": file_context if file_context != "*" else "*",
        "reason": reason,
        "added": str(date.today()),
        "status": status,
    }
    suppressions.append(new_entry)
    data["suppressions"] = suppressions

    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return new_id
```

### Argument Parsing

Extract from `$ARGUMENTS` string:
```python
args = "$ARGUMENTS".split()
uncommitted = "--uncommitted" in args
no_fix = "--no-fix" in args
no_commit = "--no-commit" in args

# Extract --since value and validate
if "--since" in args:
    idx = args.index("--since")
    if idx + 1 >= len(args) or args[idx + 1].startswith("--"):
        print("Error: --since requires a ref argument")
        exit(1)
    since_ref = args[idx + 1]
    # Validate the ref exists using bash: git rev-parse --verify {since_ref} >/dev/null 2>&1
    if subprocess.run(["git", "rev-parse", "--verify", since_ref], capture_output=True).returncode != 0:
        print(f"Error: Invalid ref '{since_ref}'. Use branch name or commit SHA.")
        exit(1)

# Extract --max-iterations value
if "--max-iterations" in args:
    idx = args.index("--max-iterations")
    try:
        max_iterations = int(args[idx + 1]) if idx + 1 < len(args) else 10
        if max_iterations < 1:
            print("Warning: --max-iterations must be >= 1. Using default (10).")
            max_iterations = 10
    except (ValueError, IndexError):
        print("Warning: --max-iterations requires a numeric value. Using default (10).")
        max_iterations = 10

# Extract --files value
if "--files" in args:
    idx = args.index("--files")
    if idx + 1 >= len(args) or args[idx + 1].startswith("--"):
        print("Warning: --files requires a glob pattern. Reviewing all files.")
        files_glob = None
    else:
        files_glob = args[idx + 1]

# Extract --required-clean-runs value (OMN-2327)
required_clean_runs = 2  # default
if "--required-clean-runs" in args:
    idx = args.index("--required-clean-runs")
    try:
        required_clean_runs = int(args[idx + 1]) if idx + 1 < len(args) else 2
        if required_clean_runs < 1:
            print("Warning: --required-clean-runs must be >= 1. Using default (2).")
            required_clean_runs = 2
    except (ValueError, IndexError):
        print("Warning: --required-clean-runs requires a numeric value. Using default (2).")
        required_clean_runs = 2

# Extract --checkpoint value (OMN-2144)
checkpoint_arg = None
checkpoint_ticket_id = None
checkpoint_run_id = None
if "--checkpoint" in args:
    idx = args.index("--checkpoint")
    if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
        checkpoint_arg = args[idx + 1]
        parts = checkpoint_arg.split(":", 1)
        if len(parts) == 2:
            checkpoint_ticket_id = parts[0]
            checkpoint_run_id = parts[1]
        else:
            print(f"Warning: --checkpoint requires format 'ticket_id:run_id', got '{checkpoint_arg}'. Ignoring.")
            checkpoint_arg = None

# Extract --flag-false-positive value (OMN-2514)
# This flag causes an immediate write to the registry and exits (does not start the review loop)
flag_false_positive_pattern = None
if "--flag-false-positive" in args:
    idx = args.index("--flag-false-positive")
    if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
        flag_false_positive_pattern = args[idx + 1]
    else:
        print("Error: --flag-false-positive requires a pattern argument")
        exit(1)
    # Write entry to registry immediately and exit
    _write_suppression_entry(
        file_context="*",
        description=flag_false_positive_pattern,
        status="pending_review",
        reason="Manually flagged",
    )
    print(f"Suppression entry written: pattern='{flag_false_positive_pattern}' status=pending_review")
    print(f"Registry: ~/.claude/review-suppressions.yml")
    print("Review the entry and change status to 'active' to suppress it in future runs.")
    exit(0)
```

### Base Branch Detection

```bash
# Detect default branch
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
if [ -z "$DEFAULT_BRANCH" ]; then
    DEFAULT_BRANCH="main"
fi

# Find merge base (with warning fallback for CI environments)
BASE_REF=$(git merge-base HEAD origin/$DEFAULT_BRANCH 2>/dev/null || { echo "Warning: Using HEAD~10 fallback" >&2; echo "HEAD~10"; })
```

### Issue Severity Handling (Strict Mode)

**CRITICAL issues**: MUST be fixed. BLOCKING - cannot merge.

**MAJOR issues**: MUST be fixed. BLOCKING - cannot merge.

**MINOR issues**: MUST be fixed. BLOCKING - cannot merge.

**NIT issues**: Optional. NOT blocking - can merge with nits remaining.

**This matches the onex pr-review merge requirements**: ALL Critical/Major/Minor must be resolved before merge. Only nits are optional.

### Commit Message Format

```
fix(review): [{severity}] {one-line summary}

{bullet list of fixes}

Review iteration: {current}/{max}
```

---

## Error Handling

| Error | Response |
|-------|----------|
| No git repo | "Error: Not in a git repository" |
| No changes | "No changes to review. Working tree clean." |
| Invalid --since ref | "Error: Invalid ref '{ref}'. Use branch name or commit SHA." |
| Review agent failure | Log error, mark iteration as `AGENT_FAILED`; retry up to 2 times (Step 2.3 retry logic); after retry exhaustion exit to Phase 3 with status "Agent failed after 2 retries - {error}. Manual re-invocation required." |
| Fix agent failure | Log error, mark issue as "needs manual fix" |
| Malformed JSON response | Try text extraction; if fails, mark `PARSE_FAILED` and retry up to 2 times; after retry exhaustion exit to Phase 3 with status "Parse failed after 2 retries - manual review needed." |
| Commit failure (general) | Log error, increment counter, files remain staged, exit to Phase 3 |
| Commit failure (hooks) | Report hook output, increment counter, suggest `--no-verify`, exit to Phase 3 |
| Commit failure (conflicts) | Log "Merge conflict detected", increment counter, exit to Phase 3 |
| Commit failure (permissions) | Log "Permission denied", increment counter, exit to Phase 3 |
| Stage failure (git add) | Log error, report which files couldn't be staged, increment counter, exit to Phase 3 with status "Stage failed - check file permissions" |

---

## Example Session

```
> /local-review --max-iterations 3

## Review Configuration

**Base**: abc1234 (origin/main)
**Scope**: All changes since base
**Max iterations**: 3
**Required clean runs**: 2
**Mode**: Fix & commit

---

## Review Iteration 1

### CRITICAL (1) - BLOCKING
- **src/api.py:45** - SQL injection in user query [`injection`]

### MAJOR (2) - BLOCKING
- **src/auth.py:89** - Missing password validation [`missing validation`]
- **src/utils.py:23** - Uncaught exception in parser [`error`]

### MINOR (1) - BLOCKING
- **src/config.py:12** - Magic number should be constant [`should`]

### NIT (2) - Optional
- **src/models.py:56** - Unused import [`style`]
- **tests/test_api.py:78** - Consider adding assertion message [`suggestion`]

**Merge Status**: Blocked by 4 issues (1 critical, 2 major, 1 minor)

Fixing 4 blocking issues (nits deferred)...

Created commit: def5678 - fix(review): [critical] SQL injection vulnerability
Created commit: ghi9012 - fix(review): [major] Password validation and exception handling
Created commit: jkl3456 - fix(review): [minor] Magic number extracted to constant

---

## Review Iteration 2

### CRITICAL (0)
### MAJOR (0)
### MINOR (0)
### NIT (2) - Optional
- **src/models.py:56** - Unused import [`style`]
- **tests/test_api.py:78** - Consider adding assertion message [`suggestion`]

**Merge Status**: Ready (only optional nits remain)

Clean run 1/2 -- running confirmation pass

---

## Review Iteration 3

### CRITICAL (0)
### MAJOR (0)
### MINOR (0)
### NIT (2) - Optional
- **src/models.py:56** - Unused import [`style`]
- **tests/test_api.py:78** - Consider adding assertion message [`suggestion`]

**Merge Status**: Ready (only optional nits remain)

---

## Review Complete

**Iterations**: 3
**Total issues fixed**: 4
**Commits created**: 3
**Clean runs**: 2/2
**Quality gate**: passed
**Nits deferred**: 2 (optional)

### Commits
1. def5678 - fix(review): [critical] SQL injection vulnerability
2. ghi9012 - fix(review): [major] Password validation and exception handling
3. jkl3456 - fix(review): [minor] Magic number extracted to constant

**Status**: Clean with nits - Confirmed (2/2 clean runs)
```
