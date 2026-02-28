# Release Orchestration

You are the release orchestrator. This prompt defines the complete execution logic for
coordinated multi-repo releases across the OmniNode package ecosystem.

**Authoritative behavior is defined here; SKILL.md is descriptive. When docs conflict,
prompt.md wins.**

## Initialization

When `/release [args]` is invoked:

1. **Announce**: "I'm using the release skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `repos` (positional) — default: all repos in tier graph
   - `--all` — explicit flag for all repos (equivalent to omitting repos)
   - `--bump <level>` — default: inferred from conventional commits
   - `--dry-run` — default: false
   - `--resume <run_id>` — default: none
   - `--skip-pypi-wait` — default: false
   - `--pypi-timeout-minutes <n>` — default: 10
   - `--run-id <id>` — default: auto-generated
   - `--gate-attestation <token>` — default: none

3. **Generate or restore run_id**:
   - If `--resume <run_id>` provided: use that run_id, load state file
   - If `--run-id <id>` provided: use that id
   - Otherwise: generate `release-<YYYYMMDD>-<short_hash>` where
     `short_hash = sha256(sorted_repo_names + date)[:6]`

---

## Constants

### Dependency Tier Graph

```python
TIER_GRAPH: dict[int, list[str]] = {
    1: ["omnibase_spi"],
    2: ["omnibase_core"],
    3: ["omnibase_infra", "omniintelligence", "omnimemory"],
    4: ["omniclaude"],
}

# All repos in release order (flattened tiers)
ALL_REPOS: list[str] = [
    "omnibase_spi",
    "omnibase_core",
    "omnibase_infra",
    "omniintelligence",
    "omnimemory",
    "omniclaude",
]

# Known inter-repo dependencies (downstream -> upstream)
DEPENDENCY_MAP: dict[str, list[str]] = {
    "omnibase_spi": [],
    "omnibase_core": ["omnibase_spi"],
    "omnibase_infra": ["omnibase_core", "omnibase_spi"],
    "omniintelligence": ["omnibase_core", "omnibase_spi"],
    "omnimemory": ["omnibase_core", "omnibase_spi"],
    "omniclaude": ["omnibase_core", "omnibase_infra", "omniintelligence"],
}

# GitHub org
GITHUB_ORG = "OmniNode-ai"
```

### Paths

```python
import os

OMNI_HOME = "/Volumes/PRO-G40/Code/omni_home"  # local-path-ok
WORKTREE_ROOT = "/Volumes/PRO-G40/Code/omni_worktrees/release"  # local-path-ok
STATE_DIR = os.path.expanduser("~/.claude/state/release")
ARCHIVE_DIR = os.path.join(STATE_DIR, "archive")
```

### Phase State Machine

```python
PHASES = [
    "PLANNED",
    "WORKTREE",
    "BUMPED",
    "PINNED",
    "CHANGELOG",
    "LOCKED",
    "LINT",
    "COMMITTED",
    "PUSHED",
    "PR_CREATED",
    "MERGED",
    "TAGGED",
    "PUBLISHED",
    "DONE",
]
```

---

## Phase 0: Scan + Validate

### Step 0.1: Pre-flight Validation

```
IF --gate-attestation is set:
  → Validate format: must match <slack_ts>:<run_id> pattern
  → IF invalid: FAIL immediately with INVALID_GATE_TOKEN
  → Do NOT proceed to scan

IF --resume is set:
  → Load state file from ~/.claude/state/release/<run_id>.json
  → IF file not found: FAIL with STATE_NOT_FOUND
  → IF file unparseable: FAIL with STATE_CORRUPT
  → Validate run_id in file matches --resume value
  → Jump to Phase 0.3 (resume plan reconstruction)
```

### Step 0.2: Scan Repos

For each repo in the selected set (all repos or the positional `repos` list):

```bash
# Find the canonical clone path
REPO_PATH="${OMNI_HOME}/${repo}"

# Pull latest main
git -C "${REPO_PATH}" pull --ff-only

# Find last tag — primary: git describe (handles merges well), fallback: sort by semver
LAST_TAG=$(git -C "${REPO_PATH}" describe --tags --abbrev=0 --match "v*" 2>/dev/null || \
           git -C "${REPO_PATH}" tag -l "v*" --sort=-v:refname | head -1)

# If no tag exists, use the initial commit
if [ -z "$LAST_TAG" ]; then
  LAST_TAG=$(git -C "${REPO_PATH}" rev-list --max-parents=0 HEAD | head -1)
  CURRENT_VERSION="0.0.0"
else
  # Extract version from tag: v1.5.0 -> 1.5.0
  CURRENT_VERSION=$(echo "$LAST_TAG" | sed 's|^v||')
fi

# Count commits since last tag
COMMIT_COUNT=$(git -C "${REPO_PATH}" rev-list --count "${LAST_TAG}..HEAD")

# Get conventional commit prefixes for bump inference
COMMIT_LOG=$(git -C "${REPO_PATH}" log --format="%s" "${LAST_TAG}..HEAD")
```

### Step 0.3: Infer Bump Level

For each repo, analyze conventional commit prefixes:

```python
def infer_bump(commit_messages: list[str], override: str | None) -> str:
    """Infer bump level from conventional commits.

    Args:
        commit_messages: List of commit message subjects.
        override: --bump override value (major|minor|patch) or None.

    Returns:
        "major", "minor", or "patch"
    """
    if override:
        return override

    has_breaking = False
    has_feat = False

    for msg in commit_messages:
        # BREAKING CHANGE in footer or ! after type
        if "BREAKING CHANGE" in msg or "!" in msg.split(":")[0]:
            has_breaking = True
        if msg.startswith("feat"):
            has_feat = True

    if has_breaking:
        return "major"
    if has_feat:
        return "minor"
    return "patch"


def compute_new_version(current: str, bump: str) -> str:
    """Compute new version from current version and bump level.

    Args:
        current: Current version string (e.g., "1.5.0").
        bump: Bump level ("major", "minor", "patch").

    Returns:
        New version string.
    """
    parts = [int(x) for x in current.split(".")]
    major, minor, patch = parts[0], parts[1], parts[2]

    if bump == "major":
        return f"{major + 1}.0.0"
    elif bump == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"
```

If a repo has 0 commits since last tag, mark it as `NOTHING_TO_RELEASE` and exclude
from the plan. This is not an error -- just skip it.

### Step 0.4: Drift Guard

```python
def drift_guard(scanned_repos: list[str]) -> None:
    """Verify scanned repo set matches the hardcoded tier graph.

    Raises GRAPH_DRIFT if repos exist in omni_home with pyproject.toml
    that are not in the tier graph, or vice versa.
    """
    graph_repos = set()
    for tier_repos in TIER_GRAPH.values():
        graph_repos.update(tier_repos)

    scanned_set = set(scanned_repos)

    missing_from_graph = scanned_set - graph_repos
    missing_from_scan = graph_repos - scanned_set

    if missing_from_graph:
        raise ReleaseError(
            code="GRAPH_DRIFT",
            message=f"Repos found in omni_home but not in tier graph: {missing_from_graph}. "
                    f"Update TIER_GRAPH in prompt.md and SKILL.md."
        )
    # missing_from_scan is OK -- repos with no pyproject.toml are excluded
```

**IMPORTANT**: Only scan repos that have a `pyproject.toml` with OmniNode dependencies.
Repos like `omnidash` (Node.js) or `omniweb` (PHP) are excluded from the Python release
pipeline. The drift guard only checks repos that appear in `TIER_GRAPH`.

### Step 0.5: Resume Plan Reconstruction (--resume only)

When resuming, reconstruct the plan from the state file:

```
FOR each repo in state file:
  IF phase == "DONE": mark as completed in plan
  ELSE: mark as pending, will restart from current phase

Display plan table with completion status
```

---

## Phase 1: Plan Display

Render the release plan as a table:

```
Release Plan (run: release-20260225-a3f7b2)
---
  Repo               Tier  Current  New      Bump   Commits
  ─────────────────  ────  ───────  ───────  ─────  ───────
  omnibase_spi       1     1.2.0    1.2.1    patch  3
  omnibase_core      2     1.4.0    1.5.0    minor  8
  omnibase_infra     3     2.0.0    2.1.0    minor  12
  omniintelligence   3     0.9.0    0.9.1    patch  2
  omnimemory         3     0.3.0    0.3.1    patch  1
  omniclaude         4     0.3.0    0.4.0    minor  15

  Skipped (no unreleased commits):
    (none)

  Total: 6 repos, 41 commits
```

### Dry-Run Exit

```
IF --dry-run:
  → Print plan table
  → Emit ModelSkillResult(status="DRY_RUN", details=[...per-repo plan...])
  → Write result to ~/.claude/skill-results/<context_id>/release.json
  → EXIT (no state file created, no side effects)
```

---

## Phase 2: Slack Gate

### Step 2.1: Compute Plan Hash

```python
import hashlib
import json

def compute_plan_hash(plan: list[dict]) -> str:
    """Compute SHA256 hash of the release plan for audit trail.

    Args:
        plan: List of per-repo plan dicts (repo, tier, current, new, bump, commits).

    Returns:
        Hash string prefixed with "sha256:".
    """
    plan_json = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(plan_json.encode()).hexdigest()[:12]
```

### Step 2.2: Post HIGH_RISK Gate

```
IF --gate-attestation=<token>:
  → Token already validated in Step 0.1
  → Use token for audit trail
  → Skip Slack gate posting
  → Proceed directly to Phase 3

ELSE:
  → Post HIGH_RISK gate to Slack with plan table + plan_hash
  → Use slack-gate skill for implementation
```

**Slack gate message format**:

```
[HIGH_RISK] release — coordinated release of N repos

Run: <run_id>
Plan Hash: <plan_hash>

RELEASE PLAN:
  Tier 1:
    omnibase_spi       1.2.0 → 1.2.1  (patch, 3 commits)
  Tier 2:
    omnibase_core      1.4.0 → 1.5.0  (minor, 8 commits)
  Tier 3:
    omnibase_infra     2.0.0 → 2.1.0  (minor, 12 commits)
    omniintelligence   0.9.0 → 0.9.1  (patch, 2 commits)
    omnimemory         0.3.0 → 0.3.1  (patch, 1 commit)
  Tier 4:
    omniclaude         0.3.0 → 0.4.0  (minor, 15 commits)

Commands:
  approve            — execute full release plan
  reject             — cancel entire release

This is HIGH_RISK — silence will NOT auto-advance.
```

**Credential resolution**: `~/.omnibase/.env` (SLACK_BOT_TOKEN, SLACK_CHANNEL_ID).

**Gate polling**: Invoke `slack_gate_poll.py` from the `slack-gate` skill:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack-gate/slack_gate_poll.py \
  --channel "$SLACK_CHANNEL_ID" \
  --thread-ts "$THREAD_TS" \
  --bot-token "$SLACK_BOT_TOKEN" \
  --timeout-minutes "1440" \
  --accept-keywords '["approve", "release", "yes", "proceed"]' \
  --reject-keywords '["reject", "cancel", "no", "hold", "deny"]'
```

**Poll exit codes**:
- 0 (ACCEPTED): proceed to Phase 3
- 1 (REJECTED): emit ModelSkillResult(status="FAILED", error="GATE_REJECTED"), exit
- 2 (TIMEOUT): emit ModelSkillResult(status="FAILED", error="GATE_TIMEOUT"), exit

### Step 2.3: Initialize State File

After gate approval (or --gate-attestation), create the state file:

```python
import json
import os
import tempfile
from datetime import datetime, timezone

def init_state_file(run_id: str, plan: list[dict], gate_token: str, plan_hash: str) -> str:
    """Create initial state file for the release run.

    Returns:
        Path to the state file.
    """
    state = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan_hash,
        "gate_token": gate_token,
        "status": "in_progress",
        "repos": {},
    }

    for entry in plan:
        state["repos"][entry["repo"]] = {
            "tier": entry["tier"],
            "old_version": entry["current"],
            "new_version": entry["new"],
            "bump": entry["bump"],
            "phase": "PLANNED",
            "phase_history": [
                {"phase": "PLANNED", "at": datetime.now(timezone.utc).isoformat()}
            ],
            "worktree_path": None,
            "branch": f"release/{run_id}/{entry['repo']}",
            "pr_url": None,
            "pr_number": None,
            "tag": f"{entry['repo']}/v{entry['new']}",
            "error": None,
        }

    state_path = os.path.join(STATE_DIR, f"{run_id}.json")
    os.makedirs(STATE_DIR, exist_ok=True)
    atomic_write_state(state, state_path)
    return state_path


def atomic_write_state(state: dict, path: str) -> None:
    """Write state file atomically to prevent corruption on crash."""
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.rename(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise
```

---

## Phase 3: Execute (Sequential Tiers)

**CRITICAL EXECUTION ORDER**: Tiers execute sequentially (1 then 2 then 3 then 4).
Within each tier, repos execute sequentially. No parallelism.

### Tier Execution Loop

```
FOR tier_num in [1, 2, 3, 4]:
  repos_in_tier = [r for r in plan if r["tier"] == tier_num]
  IF not repos_in_tier: CONTINUE

  FOR repo_entry in repos_in_tier:
    IF repo_entry["phase"] == "DONE": CONTINUE (already completed, resume case)

    result = execute_repo_release(repo_entry, run_id, state, state_path)

    IF result == "FAILED":
      → Mark all remaining repos in this tier as BLOCKED
      → Mark all repos in later tiers as BLOCKED
      → Update state: status = "partial" (if any repos completed) or "failed"
      → BREAK out of tier loop
```

### Per-Repo Release: 12 Sub-Steps

Each sub-step updates the state file atomically after completion.

#### Sub-Step 1: WORKTREE

```bash
REPO_PATH="${OMNI_HOME}/${repo}"
WORKTREE_PATH="${WORKTREE_ROOT}/${run_id}/${repo}"
BRANCH="release/${run_id}/${repo}"

# Idempotency: if worktree exists and branch matches, reuse
if [ -d "$WORKTREE_PATH" ]; then
  CURRENT_BRANCH=$(git -C "$WORKTREE_PATH" branch --show-current)
  if [ "$CURRENT_BRANCH" = "$BRANCH" ]; then
    echo "Reusing existing worktree at ${WORKTREE_PATH}"
  else
    echo "ERROR: Worktree exists but on wrong branch: ${CURRENT_BRANCH}"
    # FAIL with WORKTREE_CONFLICT
    exit 1
  fi
else
  # Pull latest main first
  git -C "$REPO_PATH" pull --ff-only

  # Create worktree
  mkdir -p "$(dirname "$WORKTREE_PATH")"
  git -C "$REPO_PATH" worktree add "$WORKTREE_PATH" -b "$BRANCH"
fi

# Verify worktree is clean
if [ -n "$(git -C "$WORKTREE_PATH" status --porcelain)" ]; then
  echo "ERROR: Worktree is dirty"
  # FAIL with WORKTREE_DIRTY
  exit 1
fi
```

**State update**: Set phase to `WORKTREE`, record `worktree_path`.

#### Sub-Step 2: BUMP

Update the `version` field in `pyproject.toml`:

```python
import re

def bump_version(worktree_path: str, new_version: str) -> None:
    """Update version in pyproject.toml.

    Idempotency: if version already matches, skip.
    """
    pyproject_path = os.path.join(worktree_path, "pyproject.toml")
    with open(pyproject_path) as f:
        content = f.read()

    # Match: version = "X.Y.Z"
    pattern = r'^(version\s*=\s*")([^"]+)(")'
    match = re.search(pattern, content, re.MULTILINE)
    if not match:
        raise ReleaseError(code="BUMP_FAILED", message="No version field found in pyproject.toml")

    current = match.group(2)
    if current == new_version:
        print(f"  Version already {new_version}, skipping bump")
        return

    content = re.sub(pattern, f'\\g<1>{new_version}\\3', content, count=1, flags=re.MULTILINE)
    with open(pyproject_path, "w") as f:
        f.write(content)
    print(f"  Bumped version: {current} → {new_version}")
```

**State update**: Set phase to `BUMPED`.

#### Sub-Step 3: PIN

Update dependency pins in `pyproject.toml` for any same-run dependencies that have
already completed (are in DONE state in the current run).

```python
def pin_dependencies(worktree_path: str, state: dict, repo: str) -> None:
    """Pin same-run dependencies to exact ==X.Y.Z versions.

    MVP: Exact pins only. Only pins deps that were released in this same run.
    Idempotency: if pin already matches, skip.

    Cross-reference: pr-safety helpers for safe file mutation patterns.
    """
    pyproject_path = os.path.join(worktree_path, "pyproject.toml")
    with open(pyproject_path) as f:
        content = f.read()

    deps_to_pin = DEPENDENCY_MAP.get(repo, [])
    modified = False

    for dep_repo in deps_to_pin:
        dep_state = state["repos"].get(dep_repo)
        if not dep_state or dep_state["phase"] != "DONE":
            continue  # Dep not in this run or not yet completed

        new_version = dep_state["new_version"]
        # Convert repo name to package name (underscores to hyphens for PyPI)
        pkg_name = dep_repo.replace("_", "-")

        # Match various dependency specifier patterns:
        #   "omnibase-core>=1.0.0"
        #   "omnibase-core~=1.0"
        #   "omnibase-core==1.4.0"
        #   "omnibase-core"
        pattern = rf'("{pkg_name})((?:>=|~=|==|<=|!=|>|<)[^"]*)?(")'
        replacement = rf'\1=={new_version}\3'

        new_content = re.sub(pattern, replacement, content)
        if new_content != content:
            content = new_content
            modified = True
            print(f"  Pinned {pkg_name}=={new_version}")

    if modified:
        with open(pyproject_path, "w") as f:
            f.write(content)
    else:
        print("  No dependencies to pin (or already pinned)")
```

**Pin Policy (MVP)**: Exact pins only (`==X.Y.Z`). Future versions may support
compatible release (`~=X.Y`) or range specifiers.

**State update**: Set phase to `PINNED`.

#### Sub-Step 4: CHANGELOG

Generate a CHANGELOG entry from conventional commits since the last tag:

```bash
LAST_TAG=$(git -C "${REPO_PATH}" describe --tags --abbrev=0 --match "v*" 2>/dev/null || \
           git -C "${REPO_PATH}" tag -l "v*" --sort=-v:refname | head -1)

# Get categorized commits
FEATS=$(git -C "${WORKTREE_PATH}" log --format="- %s" "${LAST_TAG}..HEAD" --grep="^feat")
FIXES=$(git -C "${WORKTREE_PATH}" log --format="- %s" "${LAST_TAG}..HEAD" --grep="^fix")
OTHERS=$(git -C "${WORKTREE_PATH}" log --format="- %s" "${LAST_TAG}..HEAD" \
  --invert-grep --grep="^feat" --grep="^fix")
```

Format the CHANGELOG entry:

```markdown
## vX.Y.Z (YYYY-MM-DD)

### Features
- feat: add new capability

### Bug Fixes
- fix: resolve edge case

### Other Changes
- chore: update dependencies
- refactor: simplify logic
```

**Idempotency**: If a CHANGELOG entry for the target version already exists, skip.

Prepend to `CHANGELOG.md` (or create if absent). If `CHANGELOG.md` does not exist,
create it with a standard header.

**State update**: Set phase to `CHANGELOG`.

#### Sub-Step 5: LOCK

```bash
cd "${WORKTREE_PATH}"
uv lock
```

**IMPORTANT**: This must run after bump + pin steps so the lockfile reflects the new
version and pinned dependencies.

If `uv lock` fails, mark repo as `LOCK_FAILED` and stop.

**State update**: Set phase to `LOCKED`.

#### Sub-Step 6: LINT

```bash
cd "${WORKTREE_PATH}"
pre-commit run --all-files
```

If pre-commit fails, mark repo as `LINT_FAILED` and stop. Do NOT auto-fix -- lint
failures in a release context indicate a real problem that needs human attention.

**State update**: Set phase to `LINT`.

#### Sub-Step 7: COMMIT

```bash
cd "${WORKTREE_PATH}"

# Idempotency: check if HEAD commit already matches
HEAD_MSG=$(git log -1 --format="%s")
EXPECTED_MSG="release: ${repo} v${new_version}"

if [ "$HEAD_MSG" = "$EXPECTED_MSG" ]; then
  echo "  Commit already exists, skipping"
else
  git add -A
  git commit -m "release: ${repo} v${new_version}"
fi
```

**State update**: Set phase to `COMMITTED`.

#### Sub-Step 8: PUSH

```bash
cd "${WORKTREE_PATH}"
BRANCH="release/${run_id}/${repo}"

# Idempotency: check if remote branch exists and matches
REMOTE_SHA=$(git ls-remote origin "${BRANCH}" | cut -f1)
LOCAL_SHA=$(git rev-parse HEAD)

if [ "$REMOTE_SHA" = "$LOCAL_SHA" ]; then
  echo "  Remote branch up to date, skipping push"
else
  git push -u origin "${BRANCH}"
fi
```

**State update**: Set phase to `PUSHED`.

#### Sub-Step 9: PR

```bash
cd "${WORKTREE_PATH}"
BRANCH="release/${run_id}/${repo}"
GITHUB_REPO="${GITHUB_ORG}/${repo}"

# Idempotency: check for existing PR on this branch
EXISTING_PR=$(gh pr list --repo "${GITHUB_REPO}" --head "${BRANCH}" --json number,url --jq '.[0]')

if [ -n "$EXISTING_PR" ]; then
  PR_NUMBER=$(echo "$EXISTING_PR" | jq -r '.number')
  PR_URL=$(echo "$EXISTING_PR" | jq -r '.url')
  echo "  PR already exists: #${PR_NUMBER} (${PR_URL})"
else
  # Create PR
  # Cross-reference: pr-safety helpers for PR creation guards
  PR_URL=$(gh pr create \
    --repo "${GITHUB_REPO}" \
    --title "release: ${repo} v${new_version}" \
    --body "## Release: ${repo} v${new_version}

Coordinated release run: \`${run_id}\`

### Changes
$(git log --format="- %s" "${LAST_TAG}..HEAD")

### Release metadata
- Bump: ${bump}
- Previous: v${current_version}
- Plan hash: ${plan_hash}
" \
    --base main \
    --head "${BRANCH}")

  PR_NUMBER=$(echo "$PR_URL" | grep -oE '[0-9]+$')
  echo "  Created PR: #${PR_NUMBER} (${PR_URL})"
fi
```

**State update**: Set phase to `PR_CREATED`, record `pr_url` and `pr_number`.

#### Sub-Step 10: MERGE

```bash
cd "${WORKTREE_PATH}"
GITHUB_REPO="${GITHUB_ORG}/${repo}"

# Idempotency: check if PR is already merged
PR_STATE=$(gh pr view "${PR_NUMBER}" --repo "${GITHUB_REPO}" --json state --jq '.state')

if [ "$PR_STATE" = "MERGED" ]; then
  echo "  PR already merged, skipping"
else
  # Wait for CI to pass before merging
  # Cross-reference: merge-sweep SKILL.md for merge readiness predicate
  echo "  Waiting for CI checks to pass..."
  gh pr checks "${PR_NUMBER}" --repo "${GITHUB_REPO}" --watch --fail-fast

  # Merge using squash strategy
  gh pr merge "${PR_NUMBER}" --repo "${GITHUB_REPO}" --squash --delete-branch
  echo "  Merged PR #${PR_NUMBER}"
fi
```

**IMPORTANT**: The merge step waits for CI. This is intentional -- we cannot tag a
release commit that hasn't passed CI. The `--watch` flag on `gh pr checks` blocks
until checks complete.

**Cross-reference**: `merge-sweep` SKILL.md for the merge readiness predicate.
The release skill uses `gh pr merge --squash` directly rather than dispatching to
`auto-merge`, since the human already approved the entire release plan at the gate.

**State update**: Set phase to `MERGED`.

#### Sub-Step 11: TAG

```bash
GITHUB_REPO="${GITHUB_ORG}/${repo}"
TAG_NAME="${repo}/v${new_version}"

# Idempotency: check if tag already exists
EXISTING_TAG=$(git -C "${REPO_PATH}" tag -l "${TAG_NAME}")

if [ -n "$EXISTING_TAG" ]; then
  # Verify it points to the right commit
  TAG_SHA=$(git -C "${REPO_PATH}" rev-parse "${TAG_NAME}")
  MAIN_SHA=$(git -C "${REPO_PATH}" rev-parse main)

  if [ "$TAG_SHA" = "$MAIN_SHA" ]; then
    echo "  Tag ${TAG_NAME} already exists at correct commit, skipping"
  else
    echo "  ERROR: Tag ${TAG_NAME} exists but points to wrong commit"
    # FAIL with TAG_CONFLICT
    exit 1
  fi
else
  # Pull latest main (includes the merged PR)
  git -C "${REPO_PATH}" pull --ff-only

  # Create and push tag
  git -C "${REPO_PATH}" tag "${TAG_NAME}"
  git -C "${REPO_PATH}" push origin "${TAG_NAME}"
  echo "  Created and pushed tag: ${TAG_NAME}"
fi
```

**State update**: Set phase to `TAGGED`.

#### Sub-Step 12: PUBLISH

Trigger the release GitHub Action and optionally wait for PyPI availability:

```bash
GITHUB_REPO="${GITHUB_ORG}/${repo}"
TAG_NAME="${repo}/v${new_version}"

# Trigger release workflow
# Cross-reference: .github/workflows/release.yml in each repo
# Cross-reference: .github/workflows/auto-tag-reusable.yml for tag-based triggers
#
# The tag push in Sub-Step 11 should trigger release.yml automatically if it has:
#   on:
#     push:
#       tags: ['<repo>/v*']
#
# If the repo uses auto-tag-reusable.yml, the tag push is sufficient.
echo "  Tag ${TAG_NAME} pushed — release workflow should trigger automatically"

# Optionally wait for PyPI availability
if [ "${skip_pypi_wait}" != "true" ]; then
  PKG_NAME=$(echo "${repo}" | tr '_' '-')
  echo "  Waiting for ${PKG_NAME}==${new_version} on PyPI (timeout: ${pypi_timeout_minutes}m)..."

  ELAPSED=0
  INTERVAL=30  # Check every 30 seconds

  while [ "$ELAPSED" -lt "$((pypi_timeout_minutes * 60))" ]; do
    # Check PyPI JSON API
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
      "https://pypi.org/pypi/${PKG_NAME}/${new_version}/json")

    if [ "$HTTP_STATUS" = "200" ]; then
      echo "  ${PKG_NAME}==${new_version} is available on PyPI"
      break
    fi

    sleep "$INTERVAL"
    ELAPSED=$((ELAPSED + INTERVAL))
    echo "  Still waiting... (${ELAPSED}s / $((pypi_timeout_minutes * 60))s)"
  done

  if [ "$ELAPSED" -ge "$((pypi_timeout_minutes * 60))" ]; then
    echo "  WARNING: PyPI timeout — ${PKG_NAME}==${new_version} not yet available"
    # Mark as PYPI_TIMEOUT but don't fail the repo
    # The tag and merge are already done; PyPI will catch up
  fi
fi
```

**State update**: Set phase to `PUBLISHED` (then immediately to `DONE`).

---

## Phase 4: Cleanup + Summary

### Step 4.1: Remove Worktrees

```bash
FOR each repo in plan:
  WORKTREE_PATH="${WORKTREE_ROOT}/${run_id}/${repo}"
  if [ -d "$WORKTREE_PATH" ]; then
    REPO_PATH="${OMNI_HOME}/${repo}"
    git -C "$REPO_PATH" worktree remove "$WORKTREE_PATH" --force
    echo "Removed worktree: ${WORKTREE_PATH}"
  fi

# Remove the run directory if empty
rmdir "${WORKTREE_ROOT}/${run_id}" 2>/dev/null || true
```

### Step 4.2: Archive State File

```bash
mkdir -p "${ARCHIVE_DIR}"
mv "${STATE_DIR}/${run_id}.json" "${ARCHIVE_DIR}/${run_id}.json"
echo "Archived state file to ${ARCHIVE_DIR}/${run_id}.json"
```

### Step 4.3: Print Summary

```
Release Summary (run: release-20260225-a3f7b2)
---
  Repo               Old    New      PR                Tag                    PyPI
  ─────────────────  ─────  ───────  ────────────────  ─────────────────────  ─────────
  omnibase_spi       1.2.0  1.2.1    #42 (merged)      omnibase_spi/v1.2.1   available
  omnibase_core      1.4.0  1.5.0    #88 (merged)      omnibase_core/v1.5.0  available
  omnibase_infra     2.0.0  2.1.0    #120 (merged)     omnibase_infra/v2.1.0 available
  omniintelligence   0.9.0  0.9.1    #55 (merged)      omniintelligence/v0.9.1 pending
  omnimemory         0.3.0  0.3.1    #12 (merged)      omnimemory/v0.3.1     available
  omniclaude         0.3.0  0.4.0    #350 (merged)     omniclaude/v0.4.0     available

  Status: SUCCESS (6/6 repos released)
```

### Step 4.4: Post Slack Summary

Post a LOW_RISK informational summary to Slack (no polling needed):

```
[release] run release-20260225-a3f7b2 complete

Results:
  Released:  6 repos
  Failed:    0 repos
  Skipped:   0 repos (no unreleased commits)

Details:
  omnibase_spi       1.2.0 → 1.2.1  (patch)
  omnibase_core      1.4.0 → 1.5.0  (minor)
  omnibase_infra     2.0.0 → 2.1.0  (minor)
  omniintelligence   0.9.0 → 0.9.1  (patch)
  omnimemory         0.3.0 → 0.3.1  (patch)
  omniclaude         0.3.0 → 0.4.0  (minor)

Status: SUCCESS
Plan Hash: sha256:abc123...
Gate: <gate_token>
```

Post via `chat.postMessage`. If posting fails, log warning but do NOT fail the skill
result -- summary is best-effort.

### Step 4.5: Emit ModelSkillResult

```python
def build_skill_result(state: dict, plan_hash: str) -> dict:
    """Build the final ModelSkillResult from state.

    Written to: ~/.claude/skill-results/<context_id>/release.json
    """
    repos = state["repos"]

    succeeded = [r for r, s in repos.items() if s["phase"] == "DONE"]
    failed = [r for r, s in repos.items() if s.get("error")]
    skipped = [r for r, s in repos.items() if s["phase"] == "PLANNED" and not s.get("error")]

    if len(failed) == 0 and len(succeeded) > 0:
        status = "SUCCESS"
    elif len(succeeded) > 0 and len(failed) > 0:
        status = "PARTIAL"
    else:
        status = "FAILED"

    return {
        "skill": "release",
        "status": status,
        "run_id": state["run_id"],
        "gate_token": state.get("gate_token"),
        "plan_hash": plan_hash,
        "repos_attempted": len(succeeded) + len(failed),
        "repos_succeeded": len(succeeded),
        "repos_failed": len(failed),
        "repos_skipped": len(skipped),
        "details": [
            {
                "repo": repo,
                "tier": info["tier"],
                "old_version": info["old_version"],
                "new_version": info["new_version"],
                "bump": info["bump"],
                "pr_url": info.get("pr_url"),
                "pr_number": info.get("pr_number"),
                "tag": info.get("tag"),
                "pypi_status": "available" if info["phase"] == "DONE" else "pending",
                "phase": info["phase"],
                "error": info.get("error"),
            }
            for repo, info in repos.items()
        ],
    }
```

---

## Error Handling

### Mid-Chain Failure

When a repo fails during Phase 3 execution:

```
1. Record error on the failing repo (phase + error message)
2. Mark all remaining repos in the SAME tier as BLOCKED
3. Mark ALL repos in LATER tiers as BLOCKED
4. Do NOT roll back completed repos (they are already tagged + published)
5. Set overall status to PARTIAL (if any completed) or FAILED (if none)
6. Emit ModelSkillResult with per-repo details
7. State file is preserved (not archived) for --resume
```

### Failure Recovery via --resume

```
/release --resume release-20260225-a3f7b2
```

The resume flow:
1. Loads state file
2. Shows plan with completed repos marked
3. Posts new Slack gate (or accepts --gate-attestation)
4. Skips all DONE repos
5. Restarts failed repos from their current phase
6. Continues with BLOCKED repos in tier order

### ReleaseError Class

```python
class ReleaseError(Exception):
    """Structured error for release pipeline failures."""

    def __init__(self, code: str, message: str, repo: str | None = None) -> None:
        self.code = code
        self.message = message
        self.repo = repo
        super().__init__(f"[{code}] {message}")
```

---

## Dispatch Contracts

**This section governs how the release skill orchestrator executes.**

The release skill runs INLINE -- it does not dispatch to sub-agents for the core
release logic. This is intentional:

1. Release operations are sequential and must maintain strict ordering
2. State must be updated atomically after each sub-step
3. The human already approved the entire plan at the Slack gate
4. Individual operations (git, gh, uv) are lightweight CLI calls

**Rule**: The release orchestrator runs all 12 sub-steps inline using Bash commands.
It does NOT dispatch to polymorphic agents for individual steps.

**Exception**: The Slack gate (Phase 2) may invoke the `slack-gate` skill's poll script.

---

## Cross-references

| Reference | Where Used | Purpose |
|-----------|-----------|---------|
| `skills/merge-sweep/SKILL.md` | Sub-Step 10 (MERGE) | Merge readiness predicate, merge method |
| `skills/_lib/pr-safety/helpers.md` | Sub-Step 9 (PR) | PR creation guards, claim checks |
| `.github/workflows/release.yml` | Sub-Step 12 (PUBLISH) | PyPI publish trigger (per-repo) |
| `.github/workflows/auto-tag-reusable.yml` | Sub-Step 12 (PUBLISH) | Tag-based release flow |
| `skills/slack-gate/` | Phase 2 | HIGH_RISK gate posting and polling |
| `skills/slack-gate/slack_gate_poll.py` | Phase 2 | Reply polling helper |

---

## Full Execution Sequence (Quick Reference)

```
/release [repos] [flags]
  │
  ├─ Phase 0: Scan + Validate
  │   ├─ 0.1: Pre-flight (--gate-attestation validation, --resume load)
  │   ├─ 0.2: Scan repos (tags, commits, versions)
  │   ├─ 0.3: Infer bumps (conventional commits)
  │   ├─ 0.4: Drift guard (tier graph vs actual repos)
  │   └─ 0.5: Resume plan reconstruction (if --resume)
  │
  ├─ Phase 1: Plan Display
  │   └─ If --dry-run: print plan, emit DRY_RUN result, EXIT
  │
  ├─ Phase 2: Slack Gate
  │   ├─ 2.1: Compute plan hash
  │   ├─ 2.2: Post HIGH_RISK gate (or validate --gate-attestation)
  │   └─ 2.3: Initialize state file
  │
  ├─ Phase 3: Execute (per tier, per repo)
  │   ├─ Sub-Step 1:  WORKTREE
  │   ├─ Sub-Step 2:  BUMP
  │   ├─ Sub-Step 3:  PIN (==X.Y.Z for same-run deps)
  │   ├─ Sub-Step 4:  CHANGELOG
  │   ├─ Sub-Step 5:  LOCK (uv lock)
  │   ├─ Sub-Step 6:  LINT (pre-commit)
  │   ├─ Sub-Step 7:  COMMIT
  │   ├─ Sub-Step 8:  PUSH
  │   ├─ Sub-Step 9:  PR (dedupe check, pr-safety guards)
  │   ├─ Sub-Step 10: MERGE (wait for CI, squash merge)
  │   ├─ Sub-Step 11: TAG (dedupe check)
  │   └─ Sub-Step 12: PUBLISH (trigger release.yml, optional PyPI wait)
  │
  └─ Phase 4: Cleanup + Summary
      ├─ 4.1: Remove worktrees
      ├─ 4.2: Archive state file
      ├─ 4.3: Print summary table
      ├─ 4.4: Post Slack summary (LOW_RISK, informational)
      └─ 4.5: Emit ModelSkillResult
```
