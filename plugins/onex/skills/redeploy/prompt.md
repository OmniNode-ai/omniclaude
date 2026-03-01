# Redeploy Orchestration

You are the redeploy orchestrator. This prompt defines the complete execution logic
for a post-release runtime redeploy.

**Authoritative behavior is defined here; SKILL.md is descriptive. When docs conflict,
prompt.md wins.**

## Initialization

When `/redeploy [args]` is invoked:

1. **Announce**: "I'm using the redeploy skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--versions` (required) — comma-separated `pkg=version` pairs
   - `--skip-sync` — skip SYNC phase (default: false)
   - `--skip-dockerfile-update` — skip PIN_UPDATE phase (default: false)
   - `--skip-infisical` — skip INFISICAL phase unconditionally (default: false)
   - `--worktree-ticket` — worktree name prefix (default: `redeploy-<run_id>`)
   - `--verify-only` — skip to VERIFY phase only (default: false)
   - `--dry-run` — print commands, no execution (default: false)
   - `--resume <run_id>` — resume from state file

3. **Generate or restore run_id**:
   - If `--resume <run_id>`: load `~/.claude/state/redeploy/<run_id>.json`, fail if missing
   - Otherwise: generate `redeploy-<YYYYMMDD>-<6-char-hash>` where hash is sha256 of timestamp

4. **Source environment**:
   ```bash
   source ~/.omnibase/.env
   ```

---

## Constants

```python
import os

OMNI_HOME = os.environ.get("OMNI_HOME", "/Volumes/PRO-G40/Code/omni_home")  # local-path-ok
WORKTREE_ROOT = "/Volumes/PRO-G40/Code/omni_worktrees"  # local-path-ok
STATE_DIR = os.path.expanduser("~/.claude/state/redeploy")

PHASES = ["SYNC", "ENV_CHECK", "WORKTREE", "PIN_UPDATE", "DEPLOY", "INFISICAL", "VERIFY", "NOTIFY"]

HEALTH_ENDPOINTS: dict[str, str] = {
    "omninode-runtime": "http://localhost:8085/health",
    "intelligence-api": "http://localhost:8053/health",
    "omninode-contract-resolver": "http://localhost:8091/health",
}

CONTAINER_FOR_VERSION_CHECK = "omninode-runtime"
```

---

## State Management

```python
import json
import os
import tempfile
from datetime import datetime, timezone


def init_state(run_id: str, worktree_ticket: str, versions: dict[str, str]) -> dict:
    return {
        "run_id": run_id,
        "worktree_ticket": worktree_ticket,
        "worktree_path": None,
        "worktree_ref": "main",
        "versions_requested": versions,
        "started_at": datetime.now(timezone.utc).isoformat(),
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
    """Update phase status and write state atomically."""
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
  -> Print each phase with its command sequence (no execution)
  -> Write ModelSkillResult(status="dry_run") -- no state file
  -> EXIT
```

Output format:
```
[DRY RUN] redeploy run_id=redeploy-20260301-abc123
  SYNC:       bash /Volumes/PRO-G40/Code/omni_home/docs/tools/pull-all.sh  # local-path-ok
  ENV_CHECK:  verify POSTGRES_PASSWORD, KAFKA_BOOTSTRAP_SERVERS
  WORKTREE:   git worktree add .../omni_worktrees/redeploy-20260301-abc123/omnibase_infra -b redeploy-20260301-abc123
  PIN_UPDATE: uv run python scripts/update-plugin-pins.py --versions "omniintelligence=0.8.0,..."
  DEPLOY:     ./scripts/deploy-runtime.sh --execute --restart
  INFISICAL:  [conditional] uv run python scripts/seed-infisical.py --execute
  VERIFY:     curl http://localhost:8085/health + docker exec omninode-runtime uv pip show omniintelligence
  NOTIFY:     [FULL_ONEX only] node_slack_alerter_effect
```

---

## Verify-Only Mode

```
IF --verify-only:
  -> Skip SYNC, ENV_CHECK, WORKTREE, PIN_UPDATE, DEPLOY, INFISICAL, NOTIFY
  -> --versions is still required (used to check running container versions)
  -> Execute VERIFY phase inline
  -> Write ModelSkillResult with VERIFY phase status
  -> EXIT
```

---

## Phase Execution

### Phase 1: SYNC <!-- ai-slop-ok: genuine phase heading in skill orchestration, not LLM boilerplate -->

```
IF --skip-sync:
  mark_phase(state, "SYNC", "skipped_by_flag"); CONTINUE

bash "${OMNI_HOME}/docs/tools/pull-all.sh"
```

Expected output pattern:
```
Already up to date.        <- each repo fast-forwards or is already current
Fetching omniclaude...
Fetching omnibase_core...
```

```
  -> success (exit 0): mark_phase(state, "SYNC", "completed")
  -> failure (exit non-zero): mark_phase(state, "SYNC", "failed"); print resume hint; EXIT 1
```

### Phase 2: ENV_CHECK <!-- ai-slop-ok: genuine phase heading in skill orchestration, not LLM boilerplate -->

```python
import os

# Always source ~/.omnibase/.env first
# (already done in Initialization)

# Gate for DEPLOY:
for var in ["POSTGRES_PASSWORD", "KAFKA_BOOTSTRAP_SERVERS"]:
    if not os.environ.get(var):
        print(f"ERROR: {var} not set. Source ~/.omnibase/.env before deploying.")
        mark_phase(state, "ENV_CHECK", "failed", missing=var)
        EXIT 1

# Gate for INFISICAL (only if INFISICAL_ADDR is set and --skip-infisical is false):
if not skip_infisical and os.environ.get("INFISICAL_ADDR"):
    for var in ["INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET"]:
        if not os.environ.get(var):
            print(f"ERROR: INFISICAL_ADDR is set but {var} is missing.")
            mark_phase(state, "ENV_CHECK", "failed", missing=var)
            EXIT 1

mark_phase(state, "ENV_CHECK", "completed")
```

Expected output pattern:
```
ENV_CHECK: POSTGRES_PASSWORD OK
ENV_CHECK: KAFKA_BOOTSTRAP_SERVERS OK
ENV_CHECK: completed
```

### Phase 3: WORKTREE <!-- ai-slop-ok: genuine phase heading in skill orchestration, not LLM boilerplate -->

```python
worktree_ticket = args.worktree_ticket or run_id
worktree_path = f"{WORKTREE_ROOT}/{worktree_ticket}/omnibase_infra"
branch = worktree_ticket

# Idempotency: reuse existing worktree if branch matches
if os.path.isdir(worktree_path):
    current_branch = run(f"git -C {worktree_path} branch --show-current").strip()
    if current_branch == branch:
        print(f"Reusing existing worktree at {worktree_path}")
        state["worktree_path"] = worktree_path
        mark_phase(state, "WORKTREE", "completed", path=worktree_path, reused=True)
        # CONTINUE to next phase
    else:
        print(f"ERROR: Worktree at {worktree_path} is on branch '{current_branch}', expected '{branch}'")
        mark_phase(state, "WORKTREE", "failed"); EXIT 1
else:
    # Pull latest main, then create worktree
    run(f"git -C {OMNI_HOME}/omnibase_infra pull --ff-only")
    os.makedirs(os.path.dirname(worktree_path), exist_ok=True)
    run(f"git -C {OMNI_HOME}/omnibase_infra worktree add {worktree_path} -b {branch}")
    state["worktree_path"] = worktree_path
    mark_phase(state, "WORKTREE", "completed", path=worktree_path, reused=False)
```

Expected output pattern:
```
Preparing worktree (new branch 'redeploy-20260301-abc123')
HEAD is now at <sha> <commit message>
```

### Phase 4: PIN_UPDATE <!-- ai-slop-ok: genuine phase heading in skill orchestration, not LLM boilerplate -->

```
IF --skip-dockerfile-update:
  mark_phase(state, "PIN_UPDATE", "skipped_by_flag"); CONTINUE

worktree_path = state["worktree_path"]
dockerfile = f"{worktree_path}/docker/Dockerfile.runtime"
versions_str = ",".join(f"{k}={v}" for k, v in parsed_versions.items())

result = run:
  uv run python {worktree_path}/scripts/update-plugin-pins.py \
    --versions "{versions_str}" \
    --dockerfile "{dockerfile}"

Parse JSON from last non-empty stdout line -> pins_applied dict
```

Expected output pattern (stderr):
```
  omniintelligence: 0.7.0 -> 0.8.0
  omninode-claude: 0.3.0 -> 0.4.0
  omninode-memory: 0.5.0 -> 0.6.1
```

Expected stdout (last line JSON):
```json
{"omniintelligence": {"from": "0.7.0", "to": "0.8.0", "matched": true}, ...}
```

```
  -> success (returncode 0): mark_phase(state, "PIN_UPDATE", "completed", pins_applied=pins_applied)
  -> failure: mark_phase(state, "PIN_UPDATE", "failed", error=stderr); print resume hint; EXIT 1
```

### Phase 5: DEPLOY <!-- ai-slop-ok: genuine phase heading in skill orchestration, not LLM boilerplate -->

```
worktree_path = state["worktree_path"]

Run (from worktree_path):
  ./scripts/deploy-runtime.sh --execute --restart
```

Expected output pattern:
```
[deploy-runtime] Building omninode-runtime ...
[deploy-runtime] docker compose build: SUCCESS
[deploy-runtime] Stopping omninode-runtime ...
[deploy-runtime] Starting omninode-runtime ...
[deploy-runtime] DONE
```

```
  -> success (exit 0): mark_phase(state, "DEPLOY", "completed")
  -> failure (exit non-zero): mark_phase(state, "DEPLOY", "failed", error=stderr); print resume hint; EXIT 1
```

### Phase 6: INFISICAL <!-- ai-slop-ok: genuine phase heading in skill orchestration, not LLM boilerplate -->

```
IF --skip-infisical:
  mark_phase(state, "INFISICAL", "skipped_by_flag"); CONTINUE

IF NOT os.environ.get("INFISICAL_ADDR"):
  mark_phase(state, "INFISICAL", "skipped_no_infisical"); CONTINUE

# Credentials already validated in ENV_CHECK
worktree_path = state["worktree_path"]
sync_script = f"{worktree_path}/scripts/sync-omnibase-env.sh"

IF os.path.isfile(sync_script):
  Run: bash {sync_script}                           # dapper-soaring-falcon wrapper (preferred)
ELSE:
  Run: uv run python {worktree_path}/scripts/seed-infisical.py \
         --contracts-dir {worktree_path}/src/omnibase_infra/nodes --execute
```

Expected output pattern:
```
Seeding Infisical from contracts...
  /shared/db/POSTGRES_DSN: OK (unchanged)
  /services/omninode-runtime/...: OK (updated)
seed-infisical.py: complete
```

```
  -> success (exit 0): mark_phase(state, "INFISICAL", "completed")
  -> failure (exit non-zero): mark_phase(state, "INFISICAL", "failed", error=stderr); print resume hint; EXIT 1
```

### Phase 7: VERIFY <!-- ai-slop-ok: genuine phase heading in skill orchestration, not LLM boilerplate -->

```python
versions_requested: dict[str, str] = state["versions_requested"]

# 1. Health endpoint checks
failed_health: list[str] = []
for service, url in HEALTH_ENDPOINTS.items():
    result = run(f"curl -sf {url}", capture=True)
    if result.returncode != 0:
        failed_health.append(service)
```

Expected output pattern per endpoint:
```
VERIFY: omninode-runtime http://localhost:8085/health -> 200 OK
VERIFY: intelligence-api http://localhost:8053/health -> 200 OK
VERIFY: omninode-contract-resolver http://localhost:8091/health -> 200 OK
```

```python
if failed_health:
    print(f"VERIFY FAILED: Health checks failed for: {failed_health}")
    mark_phase(state, "VERIFY", "failed", failed_health=failed_health)
    EXIT 1

# 2. In-container package version checks
failed_versions: list[str] = []
for pkg, expected_ver in versions_requested.items():
    result = run(
        f"docker exec {CONTAINER_FOR_VERSION_CHECK} uv pip show {pkg} | grep Version",
        capture=True,
    )
    if result.returncode != 0:
        failed_versions.append(f"{pkg}: container check failed")
        continue
    actual_ver = result.stdout.strip().replace("Version: ", "")
    if actual_ver != expected_ver:
        failed_versions.append(f"{pkg}: expected {expected_ver}, got {actual_ver}")
```

Expected output pattern per package:
```
VERIFY: omniintelligence Version: 0.8.0 (expected 0.8.0) -> OK
VERIFY: omninode-claude   Version: 0.4.0 (expected 0.4.0) -> OK
VERIFY: omninode-memory   Version: 0.6.1 (expected 0.6.1) -> OK
```

```python
if failed_versions:
    print(f"VERIFY FAILED: Version mismatches: {failed_versions}")
    mark_phase(state, "VERIFY", "failed", failed_versions=failed_versions)
    EXIT 1

mark_phase(state, "VERIFY", "completed")
```

### Phase 8: NOTIFY <!-- ai-slop-ok: genuine phase heading in skill orchestration, not LLM boilerplate -->

```python
from omniclaude.nodes._lib.tier_routing import detect_onex_tier

tier = detect_onex_tier()  # see @_lib/tier-routing/helpers.md

if tier == "FULL_ONEX":
    # Use node_slack_alerter_effect
    from omniclaude.nodes.node_slack_alerter_effect.models import ModelSlackAlertRequest

    pins_summary = ", ".join(f"{k}=={v}" for k, v in state["versions_requested"].items())
    phase_summary = {p: d["status"] for p, d in state["phases"].items()}

    request = ModelSlackAlertRequest(
        run_id=state["run_id"],
        message=(
            f"[redeploy] {state['run_id']} complete\n"
            f"Pins: {pins_summary}\n"
            f"Phases: {phase_summary}"
        ),
        risk_tier="LOW_RISK",
    )
    await handler.alert(request)
else:
    # EVENT_BUS or STANDALONE: stdout only
    pins_summary = ", ".join(f"{k}=={v}" for k, v in state["versions_requested"].items())
    print(f"[redeploy] {state['run_id']} complete")
    print(f"  Pins: {pins_summary}")
    print(f"  Phases: all completed")

mark_phase(state, "NOTIFY", "completed")
```

Expected output pattern:
```
[redeploy] redeploy-20260301-abc123 complete
  Pins: omniintelligence==0.8.0, omninode-claude==0.4.0, omninode-memory==0.6.1
  Phases: all completed
```

---

## Resume Logic

```
IF --resume <run_id>:
  path = ~/.claude/state/redeploy/<run_id>.json
  IF not os.path.exists(path):
    EXIT 1 with "State file not found: {path}"

  state = json.load(open(path))
  completed = [p for p, d in state["phases"].items() if d["status"] == "completed"]
  print(f"Resuming {run_id}: skipping completed phases {completed}")

  FOR each phase in PHASES:
    IF state["phases"][phase]["status"] == "completed":
      CONTINUE  # Already done
    ELSE:
      Execute phase (status is pending or failed)
```

---

## Error Handling

On any phase failure:
1. Call `mark_phase(state, phase, "failed", error=...)` — writes state atomically
2. Print: `ERROR in {phase}: {error_message}`
3. Print: `Resume with: /redeploy --resume {run_id} --versions "{versions_str}" [other flags]`
4. Exit 1

---

## Skill Result

Write `ModelSkillResult` to `~/.claude/skill-results/{context_id}/redeploy.json`:

```json
{
  "skill": "redeploy",
  "status": "success | failed | dry_run",
  "run_id": "redeploy-20260301-abc123",
  "phases": {
    "SYNC": "completed",
    "ENV_CHECK": "completed",
    "WORKTREE": "completed",
    "PIN_UPDATE": "completed",
    "DEPLOY": "completed",
    "INFISICAL": "skipped_no_infisical",
    "VERIFY": "completed",
    "NOTIFY": "completed"
  },
  "pins_applied": {
    "omniintelligence": "0.8.0",
    "omninode-claude": "0.4.0",
    "omninode-memory": "0.6.1"
  }
}
```

---

## Full Execution Sequence (Quick Reference)

```
/redeploy --versions "omniintelligence=0.8.0,omninode-claude=0.4.0,omninode-memory=0.6.1"
  |
  +- Initialize: parse args, generate run_id, source ~/.omnibase/.env
  |
  +- Phase 1: SYNC       bash pull-all.sh (ff-only)
  +- Phase 2: ENV_CHECK  verify POSTGRES_PASSWORD, KAFKA_BOOTSTRAP_SERVERS, optional INFISICAL creds
  +- Phase 3: WORKTREE   create or reuse omni_worktrees/<ticket>/omnibase_infra
  +- Phase 4: PIN_UPDATE update-plugin-pins.py -> Dockerfile.runtime version pins
  +- Phase 5: DEPLOY     deploy-runtime.sh --execute --restart
  +- Phase 6: INFISICAL  seed-infisical.py or sync-omnibase-env.sh (if INFISICAL_ADDR set)
  +- Phase 7: VERIFY     curl health endpoints + docker exec uv pip show per-package
  +- Phase 8: NOTIFY     Slack if FULL_ONEX; stdout if EVENT_BUS or STANDALONE
```

---

## Cross-References

| Reference | Used For |
|-----------|---------|
| `@_lib/tier-routing/helpers.md` | `detect_onex_tier()` in NOTIFY phase |
| `@_lib/slack-gate/helpers.md` | Slack credential resolution |
| `omnibase_infra/scripts/deploy-runtime.sh` | DEPLOY phase — core deploy script |
| `omnibase_infra/scripts/update-plugin-pins.py` | PIN_UPDATE phase — Dockerfile pin updater |
| `omnibase_infra/scripts/seed-infisical.py` | INFISICAL phase — direct fallback |
| `release` skill | Run before redeploy to coordinate version bumps |
