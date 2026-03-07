# Post-Release Redeploy Orchestration

You are the post-release redeploy orchestrator. This prompt defines the complete
execution logic for the end-to-end post-PR-merge redeployment pipeline.

**Authoritative behavior is defined here; SKILL.md is descriptive. When docs conflict,
prompt.md wins.**

## Initialization

When `/post-release-redeploy [args]` is invoked:

1. **Announce**: "I'm using the post-release-redeploy skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--batch-label` -- GitHub label for batch PR gate (required unless `--skip-merge-gate`)
   - `--repos` -- comma-separated repo list (default: all repos in tier graph)
   - `--skip-merge-gate` -- skip Phase 1 merge gate (default: false)
   - `--skip-release` -- skip Phase 3 release (default: false)
   - `--skip-rebuild` -- skip Phase 5 Docker rebuild (default: false)
   - `--smoke-prompt` -- custom Kafka smoke test prompt (default: auto-generated)
   - `--dry-run` -- print plan, no execution (default: false)
   - `--resume <run_id>` -- resume from state file

3. **Validate arguments**:
   ```
   IF NOT --skip-merge-gate AND NOT --batch-label:
     FAIL with "MISSING_BATCH_LABEL: --batch-label is required unless --skip-merge-gate is set"
   ```

4. **Generate or restore run_id**:
   - If `--resume <run_id>`: load `~/.claude/state/post-release-redeploy/<run_id>.json`
   - Otherwise: generate `prd-<YYYYMMDD>-<6-char-hash>`

5. **Source environment**:
   ```bash
   source ~/.omnibase/.env
   ```

---

## Constants

```python
import os

OMNI_HOME = "/Volumes/PRO-G40/Code/omni_home"  # local-path-ok
STATE_DIR = os.path.expanduser("~/.claude/state/post-release-redeploy")

GITHUB_ORG = "OmniNode-ai"

ALL_REPOS: list[str] = [
    "omnibase_spi",
    "omnibase_core",
    "omnibase_infra",
    "omniintelligence",
    "omnimemory",
    "omniclaude",
]

# Repos with pyproject.toml (excluded: omninode_infra which is infra-only)
PYTHON_REPOS: list[str] = [
    "omnibase_spi",
    "omnibase_core",
    "omnibase_infra",
    "omniintelligence",
    "omnimemory",
    "omniclaude",
]

PHASES = [
    "PRE_FLIGHT",
    "MERGE_GATE",
    "RELEASE_STATE",
    "RELEASE",
    "INSTALLABILITY",
    "REBUILD",
    "HEALTH",
    "KAFKA_SMOKE",
    "CLOSE_OUT",
]

HEALTH_ENDPOINTS: dict[str, str] = {
    "postgres": "psql -h localhost -p 5436 -U postgres -d omnibase_infra -c 'SELECT 1;'",
    "runtime": "http://localhost:8085/health",
    "intelligence-api": "http://localhost:8053/health",
    "contract-resolver": "http://localhost:8091/health",
}
```

---

## State Management

```python
import json
import os
import tempfile
from datetime import datetime, timezone


def init_state(run_id: str, batch_label: str | None, repos: list[str]) -> dict:
    return {
        "run_id": run_id,
        "batch_label": batch_label,
        "repos": repos,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "release_run_id": None,
        "redeploy_run_id": None,
        "released_versions": {},
        "phases": {phase: {"status": "pending"} for phase in PHASES},
    }


def atomic_write_state(state: dict, run_id: str) -> None:
    path = os.path.join(STATE_DIR, f"{run_id}.json")
    os.makedirs(STATE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.rename(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def mark_phase(state: dict, phase: str, status: str, **kwargs: object) -> None:
    state["phases"][phase] = {
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    atomic_write_state(state, state["run_id"])
```

---

## Dry-Run Mode

```
IF --dry-run:
  -> Print each phase with expected actions
  -> No state file created
  -> EXIT with status "dry_run"
```

Output format:
```
[DRY RUN] post-release-redeploy run_id=prd-20260307-abc123
  PRE_FLIGHT:     verify tag discovery fix, repos on main, pull --ff-only
  MERGE_GATE:     gh pr list --label "<batch-label>" --state open (expect zero)
  RELEASE_STATE:  git describe + rev-list --count for each repo
  RELEASE:        /release (delegates to release skill with Slack gate)
  INSTALLABILITY: docker run python:3.12-slim pip install <released packages>
  REBUILD:        /redeploy --versions "<released versions>"
  HEALTH:         curl health endpoints + docker exec version checks
  KAFKA_SMOKE:    nonce emission + consumer lag check
  CLOSE_OUT:      version gap verification + mixed tag check
```

---

## Phase Execution

### Phase 0: PRE_FLIGHT

**Purpose**: Verify the tag discovery fix is deployed and all repos are on main.

#### Step 0.1: Tag Discovery Fix Verification

```bash
# Verify release skill uses v* pattern (not ${repo}/v*)
RELEASE_PROMPT="${OMNI_HOME}/omniclaude/plugins/onex/skills/release/prompt.md"

if grep -q '\${repo}/v\*' "$RELEASE_PROMPT"; then
  echo "HARD STOP: release prompt.md still uses \${repo}/v* pattern"
  echo "Fix ALL occurrences to use v* before proceeding"
  mark_phase(state, "PRE_FLIGHT", "failed", error="tag_discovery_not_fixed")
  EXIT 1
fi

# Verify git describe --match "v*" is the primary tag discovery method
if ! grep -q 'describe --tags --abbrev=0 --match "v\*"' "$RELEASE_PROMPT"; then
  echo "HARD STOP: release prompt.md does not use git describe --match v*"
  mark_phase(state, "PRE_FLIGHT", "failed", error="tag_discovery_missing")
  EXIT 1
fi

echo "PRE_FLIGHT: tag discovery fix verified"
```

#### Step 0.2: Repos on Main + Pull

```bash
for repo in ${PYTHON_REPOS[@]}; do
  REPO_PATH="${OMNI_HOME}/${repo}"
  BR=$(git -C "$REPO_PATH" rev-parse --abbrev-ref HEAD)
  if [ "$BR" != "main" ]; then
    echo "HARD STOP: $repo is on branch '$BR', not main"
    mark_phase(state, "PRE_FLIGHT", "failed", error="repo_not_on_main", repo="$repo")
    EXIT 1
  fi
  git -C "$REPO_PATH" pull --ff-only origin main || {
    echo "HARD STOP: $repo pull --ff-only failed"
    mark_phase(state, "PRE_FLIGHT", "failed", error="pull_failed", repo="$repo")
    EXIT 1
  }
done

echo "PRE_FLIGHT: all repos on main and pulled"
```

#### Step 0.3: Tag Reachability

```bash
for repo in ${PYTHON_REPOS[@]}; do
  REPO_PATH="${OMNI_HOME}/${repo}"
  LAST_TAG=$(git -C "$REPO_PATH" describe --tags --abbrev=0 --match "v*" 2>/dev/null)
  if [ -z "$LAST_TAG" ]; then
    LAST_TAG=$(git -C "$REPO_PATH" tag -l "v*" --sort=-v:refname | head -1)
  fi
  if [ -z "$LAST_TAG" ]; then
    echo "HARD STOP: $repo has no reachable v* tag"
    mark_phase(state, "PRE_FLIGHT", "failed", error="no_reachable_tag", repo="$repo")
    EXIT 1
  fi
  echo "PRE_FLIGHT: $repo last_tag=$LAST_TAG"
done
```

```
mark_phase(state, "PRE_FLIGHT", "completed")
```

---

### Phase 1: MERGE_GATE

**Purpose**: Verify all batch-labeled PRs are merged before proceeding to release.

```
IF --skip-merge-gate:
  mark_phase(state, "MERGE_GATE", "skipped_by_flag")
  CONTINUE
```

```bash
BATCH_LABEL="${batch_label}"
REPOS_TO_CHECK=(omnibase_infra omnibase_spi omniintelligence omnimemory omnibase_core omniclaude)
STILL_OPEN=""

for repo in "${REPOS_TO_CHECK[@]}"; do
  OPEN=$(gh pr list --repo "${GITHUB_ORG}/${repo}" \
    --label "${BATCH_LABEL}" --state open \
    --json number,headRefName \
    --jq '.[] | "\(.number) \(.headRefName)"')

  if [ -n "$OPEN" ]; then
    echo "STILL OPEN in $repo: $OPEN"
    STILL_OPEN="${STILL_OPEN}${repo}: ${OPEN}\n"
  else
    echo "MERGE_GATE: $repo -- all batch PRs merged"
  fi
done

if [ -n "$STILL_OPEN" ]; then
  echo "HARD STOP: Open batch-labeled PRs remain"
  echo -e "$STILL_OPEN"
  mark_phase(state, "MERGE_GATE", "failed", error="open_prs_remain", open_prs="$STILL_OPEN")
  EXIT 1
fi
```

```
mark_phase(state, "MERGE_GATE", "completed")
```

---

### Phase 2: RELEASE_STATE

**Purpose**: Scan repos for unreleased commits and compute release state. This is
informational -- `/release --dry-run` is the authoritative decision mechanism. This
phase detects broken state before handing off to the release skill.

```bash
echo "=== Release State ==="
for repo in ${PYTHON_REPOS[@]}; do
  REPO_PATH="${OMNI_HOME}/${repo}"

  LAST_TAG=$(git -C "$REPO_PATH" describe --tags --abbrev=0 --match "v*" 2>/dev/null)
  if [ -z "$LAST_TAG" ]; then
    LAST_TAG=$(git -C "$REPO_PATH" tag -l "v*" --sort=-v:refname | head -1)
  fi

  # Already verified in PRE_FLIGHT that tag exists
  COUNT=$(git -C "$REPO_PATH" rev-list --count "${LAST_TAG}..HEAD")
  VER=$(grep '^version' "$REPO_PATH/pyproject.toml" | head -1)

  echo "$repo | last_tag=$LAST_TAG | commits_since=$COUNT | $VER"
done
```

Record the output in state for audit trail:

```
mark_phase(state, "RELEASE_STATE", "completed", scan_output="<captured output>")
```

---

### Phase 3: RELEASE

**Purpose**: Execute the coordinated release pipeline via the `/release` skill.

```
IF --skip-release:
  mark_phase(state, "RELEASE", "skipped_by_flag")
  CONTINUE

# The release skill handles:
# - Tier-ordered version bumps
# - Slack HIGH_RISK gate
# - PR creation, CI wait, merge
# - Tag creation, PyPI publish
# - PyPI availability wait
#
# Invoke it:
/release --all
```

**After `/release` completes**:

```python
# Extract released versions from /release output
# The release skill emits a summary with per-repo versions
# Capture these into state:
state["release_run_id"] = "<run_id from /release>"
state["released_versions"] = {
    # repo: version (from /release completion summary)
}
```

**If `/release` reports NOTHING_TO_RELEASE for all repos**:

```
echo "No repos need release -- skipping INSTALLABILITY and REBUILD"
mark_phase(state, "RELEASE", "completed", result="nothing_to_release")
mark_phase(state, "INSTALLABILITY", "skipped_no_release")
mark_phase(state, "REBUILD", "skipped_no_release")
JUMP to Phase 6 (HEALTH)
```

```
mark_phase(state, "RELEASE", "completed")
```

---

### Phase 4: INSTALLABILITY

**Purpose**: Verify released packages are installable from PyPI before rebuilding images.

```
IF state["released_versions"] is empty:
  mark_phase(state, "INSTALLABILITY", "skipped_no_release")
  CONTINUE
```

```bash
# Build pip install args from released versions
# e.g., omnibase-spi==1.2.1 omnibase-core==1.5.0 ...
INSTALL_ARGS=""
for repo in ${PYTHON_REPOS[@]}; do
  VERSION="${released_versions[$repo]}"
  if [ -n "$VERSION" ]; then
    PKG_NAME=$(echo "$repo" | tr '_' '-')
    INSTALL_ARGS="$INSTALL_ARGS ${PKG_NAME}==${VERSION}"
  fi
done

docker run --rm python:3.12-slim pip install -q --no-cache-dir $INSTALL_ARGS \
  && echo "PyPI install check: OK" \
  || {
    echo "HARD STOP: PyPI install check failed"
    mark_phase(state, "INSTALLABILITY", "failed", error="pip_install_failed")
    EXIT 1
  }
```

```
mark_phase(state, "INSTALLABILITY", "completed")
```

---

### Phase 5: REBUILD

**Purpose**: Update Dockerfile.runtime pins, rebuild and restart Docker runtime.

```
IF --skip-rebuild:
  mark_phase(state, "REBUILD", "skipped_by_flag")
  CONTINUE

IF state["released_versions"] is empty:
  mark_phase(state, "REBUILD", "skipped_no_release")
  CONTINUE
```

**Build version pins for /redeploy**:

The `/redeploy` skill expects `--versions` in `pkg=version` format for the *plugin*
packages installed in `Dockerfile.runtime`. These are typically `omniintelligence`,
`omninode-claude` (maps to `omniclaude`), and `omninode-memory` (maps to `omnimemory`).

```python
# Map repo names to Dockerfile package names
REPO_TO_DOCKERFILE_PKG = {
    "omniintelligence": "omniintelligence",
    "omniclaude": "omninode-claude",
    "omnimemory": "omninode-memory",
}

redeploy_versions = {}
for repo, pkg_name in REPO_TO_DOCKERFILE_PKG.items():
    version = state["released_versions"].get(repo)
    if version:
        redeploy_versions[pkg_name] = version

if not redeploy_versions:
    echo "No Dockerfile plugin packages were released -- skipping rebuild"
    mark_phase(state, "REBUILD", "skipped_no_plugin_release")
    CONTINUE
```

```bash
# Build versions string for /redeploy
VERSIONS_STR=$(python3 -c "
versions = ${redeploy_versions}
print(','.join(f'{k}={v}' for k, v in versions.items()))
")

/redeploy --versions "$VERSIONS_STR"
```

**After `/redeploy` completes**:

```python
state["redeploy_run_id"] = "<run_id from /redeploy>"
```

```
mark_phase(state, "REBUILD", "completed")
```

---

### Phase 6: HEALTH

**Purpose**: Verify infrastructure health and package versions inside containers.

#### Step 6.1: Infrastructure Health

```bash
source ~/.omnibase/.env

# PostgreSQL
psql -h localhost -p 5436 -U postgres -d omnibase_infra -c "SELECT 1;" \
  && echo "HEALTH: postgres OK" || echo "HEALTH: postgres FAIL"

# HTTP health endpoints
for endpoint in "runtime:http://localhost:8085/health" \
                "intelligence-api:http://localhost:8053/health" \
                "contract-resolver:http://localhost:8091/health"; do
  NAME="${endpoint%%:*}"
  # Remove the name: prefix to get the URL
  URL="${endpoint#*:}"
  curl -sf "$URL" && echo "HEALTH: $NAME OK" || echo "HEALTH: $NAME FAIL"
done
```

#### Step 6.2: Container Version Verification

**Discover the primary runtime service dynamically** -- do not hardcode container names:

```bash
cd "${OMNI_HOME}/omnibase_infra"

# Discover runtime services from compose
RUNTIME_SERVICES=$(docker compose -f docker/docker-compose.infra.yml \
  --profile runtime config --services)

# Find the primary runtime service
PRIMARY_RUNTIME=$(echo "$RUNTIME_SERVICES" | grep -i "runtime" | grep -v "worker" | head -1)

if [ -z "$PRIMARY_RUNTIME" ]; then
  echo "WARNING: Could not discover primary runtime service"
  echo "Available services: $RUNTIME_SERVICES"
  echo "Falling back to 'omninode-runtime'"
  PRIMARY_RUNTIME="omninode-runtime"
fi

# Get container ID
RUNTIME_CID=$(docker compose -f docker/docker-compose.infra.yml \
  ps -q "$PRIMARY_RUNTIME" | head -1)

if [ -z "$RUNTIME_CID" ]; then
  echo "HEALTH: container version check SKIPPED (service not running)"
else
  echo "HEALTH: checking versions in container $RUNTIME_CID (service: $PRIMARY_RUNTIME)"
  docker exec "$RUNTIME_CID" python -c "
import omnibase_infra, omniintelligence, omniclaude
print('omnibase_infra:', getattr(omnibase_infra, '__version__', 'UNKNOWN'))
print('omniintelligence:', getattr(omniintelligence, '__version__', 'UNKNOWN'))
print('omniclaude:', getattr(omniclaude, '__version__', 'UNKNOWN'))
"
fi
```

Cross-check printed versions against `state["released_versions"]`. Log mismatches
as warnings but do not fail -- the `/redeploy` VERIFY phase already does strict checks.

```
mark_phase(state, "HEALTH", "completed")
```

---

### Phase 7: KAFKA_SMOKE

**Purpose**: Verify Kafka event emission is healthy using a nonce-based test.

#### Step 7.1: Extract Topic Name from Source

```bash
# Extract the ROUTING_COMPLETED topic from source -- never hardcode
TOPIC=$(grep -n "^    ROUTING_COMPLETED" \
  "${OMNI_HOME}/omniclaude/src/omniclaude/hooks/topics.py" \
  | grep -oP '"[^"]+"' | head -1 | tr -d '"')

if [ -z "$TOPIC" ]; then
  echo "WARNING: Could not extract ROUTING_COMPLETED topic from source"
  echo "KAFKA_SMOKE: skipped (topic not found)"
  mark_phase(state, "KAFKA_SMOKE", "skipped_topic_not_found")
  CONTINUE
fi

echo "KAFKA_SMOKE: using topic $TOPIC"
```

#### Step 7.2: Emit Daemon Health Check

```bash
# Check if the emit daemon PID file exists
PID_FILE_PATH=$(grep -oP "Path\(tempfile\.gettempdir\(\)\)\s*/\s*\"[^\"]+\"" \
  "${OMNI_HOME}/omniclaude/src/omniclaude/publisher/__main__.py" 2>/dev/null \
  | head -1)

# If we cannot parse the PID file path, just check the process
if pgrep -f "omniclaude.publisher" > /dev/null 2>&1; then
  echo "KAFKA_SMOKE: emit daemon is running"
else
  echo "WARNING: emit daemon does not appear to be running"
  echo "Start a new Claude Code session to restart it"
fi
```

#### Step 7.3: Nonce Emission Test

```bash
NONCE="smoke-$(date +%s)"

# Determine which broker to use based on bus status
# Default to local bus
BROKER="${KAFKA_BOOTSTRAP_SERVERS:-localhost:19092}"

echo "KAFKA_SMOKE: nonce=$NONCE on broker=$BROKER topic=$TOPIC"

# Capture baseline (last message before test)
BASELINE=$(kcat -C -b "$BROKER" -t "$TOPIC" -o -1 -e -q 2>/dev/null | cat -v)
echo "KAFKA_SMOKE: baseline captured"

echo ""
echo "ACTION REQUIRED: Send this prompt in a NEW Claude Code session:"
echo "  'ROUTING_SMOKE_TEST nonce=$NONCE'"
echo ""
echo "After sending, the skill will check for the nonce in topic messages."
echo "Press Enter when the test prompt has been sent..."
read

# Check for nonce in recent messages
POST=$(kcat -C -b "$BROKER" -t "$TOPIC" -o -3 -e -q 2>/dev/null | cat -v)
echo "KAFKA_SMOKE: post-test messages captured"

if echo "$POST" | grep -q "$NONCE"; then
  echo "KAFKA_SMOKE: PASS (nonce found in messages)"
else
  echo "KAFKA_SMOKE: WARN -- nonce not found; payload may be enveloped/opaque"
  echo "Manual verification may be needed"
fi
```

#### Step 7.4: Consumer Lag Check

```bash
# Check if we can find the routing consumer group
echo "KAFKA_SMOKE: checking consumer groups..."
docker exec omnibase-infra-redpanda rpk group list 2>/dev/null | head -20 || true

echo ""
echo "If a routing/intelligence consumer group exists above, verify its lag:"
echo "  docker exec omnibase-infra-redpanda rpk group describe <GROUP_NAME>"
echo "Lag should be zero or decreasing."
```

```
mark_phase(state, "KAFKA_SMOKE", "completed")
```

---

### Phase 8: CLOSE_OUT

**Purpose**: Final verification and cleanup.

#### Step 8.1: Repos on Main Confirmation

```bash
for repo in ${PYTHON_REPOS[@]}; do
  REPO_PATH="${OMNI_HOME}/${repo}"
  BR=$(git -C "$REPO_PATH" rev-parse --abbrev-ref HEAD)
  [ "$BR" != "main" ] && echo "WARN: $repo on $BR (not main)" || echo "CLOSE_OUT: $repo on main"
done
```

#### Step 8.2: Tag Discovery Still Working

```bash
grep "LAST_TAG=" "${OMNI_HOME}/omniclaude/plugins/onex/skills/release/prompt.md" | head -3
# Must show git describe -- if ${repo}/v* appears, flag it
```

#### Step 8.3: Version Gap Verification

```bash
for repo in ${PYTHON_REPOS[@]}; do
  REPO_PATH="${OMNI_HOME}/${repo}"
  git -C "$REPO_PATH" pull --ff-only origin main 2>/dev/null || true
  MAIN_VER=$(grep '^version' "$REPO_PATH/pyproject.toml" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
  LAST_TAG=$(git -C "$REPO_PATH" describe --tags --abbrev=0 --match "v*" 2>/dev/null || echo "NONE")

  if [ "v$MAIN_VER" = "$LAST_TAG" ]; then
    echo "CLOSE_OUT: $repo pyproject=$MAIN_VER last_tag=$LAST_TAG"
  else
    echo "CLOSE_OUT: MISMATCH $repo pyproject=$MAIN_VER last_tag=$LAST_TAG"
  fi
done
```

#### Step 8.4: Mixed Tag Scheme Check

```bash
for repo in ${PYTHON_REPOS[@]}; do
  PREFIXED=$(git -C "${OMNI_HOME}/${repo}" tag -l "${repo}/v*" | head -3)
  if [ -n "$PREFIXED" ]; then
    echo "WARN: $repo has repo-prefixed tags (legacy): $PREFIXED"
    echo "Consider deleting or documenting these in a follow-up ticket"
  fi
done
```

```
mark_phase(state, "CLOSE_OUT", "completed")
```

---

## Resume Logic

```
IF --resume <run_id>:
  path = ~/.claude/state/post-release-redeploy/<run_id>.json
  IF not os.path.exists(path):
    EXIT 1 with "State file not found: {path}"

  state = json.load(open(path))
  completed = [p for p, d in state["phases"].items() if d["status"] in ("completed", "skipped_by_flag", "skipped_no_release", "skipped_no_plugin_release", "skipped_topic_not_found")]
  print(f"Resuming {run_id}: skipping completed phases {completed}")

  FOR each phase in PHASES:
    IF state["phases"][phase]["status"] in completed_statuses:
      CONTINUE
    ELSE:
      Execute phase
```

---

## Error Handling

On any phase failure:
1. Call `mark_phase(state, phase, "failed", error=...)` -- writes state atomically
2. Print: `ERROR in {phase}: {error_message}`
3. Print: `Resume with: /post-release-redeploy --resume {run_id} [other flags]`
4. Exit 1

---

## Skill Result

Written to `~/.claude/skill-results/{context_id}/post-release-redeploy.json`:

```json
{
  "skill": "post-release-redeploy",
  "status": "success | failed | partial | dry_run",
  "run_id": "prd-20260307-abc123",
  "release_run_id": "release-20260307-def456",
  "redeploy_run_id": "redeploy-20260307-ghi789",
  "released_versions": {
    "omnibase_spi": "1.2.1",
    "omnibase_core": "1.5.0",
    "omnibase_infra": "2.1.0",
    "omniintelligence": "0.9.1",
    "omnimemory": "0.3.1",
    "omniclaude": "0.4.0"
  },
  "phases": {
    "PRE_FLIGHT": "completed",
    "MERGE_GATE": "completed",
    "RELEASE_STATE": "completed",
    "RELEASE": "completed",
    "INSTALLABILITY": "completed",
    "REBUILD": "completed",
    "HEALTH": "completed",
    "KAFKA_SMOKE": "completed",
    "CLOSE_OUT": "completed"
  }
}
```

---

## Full Execution Sequence (Quick Reference)

```
/post-release-redeploy --batch-label "omni-batch:2068"
  |
  +- Initialize: parse args, generate run_id, source ~/.omnibase/.env
  |
  +- Phase 0: PRE_FLIGHT
  |   +- 0.1: Verify tag discovery fix (no ${repo}/v* in release prompt.md)
  |   +- 0.2: Assert all repos on main, pull --ff-only
  |   +- 0.3: Verify v* tag reachability for all repos
  |
  +- Phase 1: MERGE_GATE
  |   +- gh pr list --label <batch-label> --state open (must be zero)
  |
  +- Phase 2: RELEASE_STATE
  |   +- git describe + rev-list --count for each repo (informational)
  |
  +- Phase 3: RELEASE
  |   +- Delegates to /release skill (full pipeline with Slack gate)
  |
  +- Phase 4: INSTALLABILITY
  |   +- docker run python:3.12-slim pip install <released packages>
  |
  +- Phase 5: REBUILD
  |   +- Delegates to /redeploy skill (Dockerfile pins + Docker rebuild)
  |
  +- Phase 6: HEALTH
  |   +- 6.1: psql + curl health endpoints
  |   +- 6.2: Container version verification via PRIMARY_RUNTIME
  |
  +- Phase 7: KAFKA_SMOKE
  |   +- 7.1: Extract topic name from source (never hardcode)
  |   +- 7.2: Emit daemon health check
  |   +- 7.3: Nonce emission test (requires manual step)
  |   +- 7.4: Consumer lag check
  |
  +- Phase 8: CLOSE_OUT
  |   +- 8.1: Repos on main confirmation
  |   +- 8.2: Tag discovery still working
  |   +- 8.3: Version gap verification
  |   +- 8.4: Mixed tag scheme check
```

---

## Cross-References

| Reference | Used For |
|-----------|---------|
| `release` skill | Phase 3 -- full coordinated release pipeline |
| `redeploy` skill | Phase 5 -- Docker rebuild and restart |
| `release/prompt.md` | Phase 0 -- tag discovery fix verification |
| `omniclaude/src/omniclaude/hooks/topics.py` | Phase 7 -- Kafka topic name extraction |
| `omniclaude/src/omniclaude/publisher/__main__.py` | Phase 7 -- emit daemon PID file |
| `omnibase_infra/docker/docker-compose.infra.yml` | Phase 6 -- runtime service discovery |
| `~/.claude/plans/agile-purring-ullman.md` | Source runbook this skill codifies |
