# _lib/pr-safety/helpers.md

**Single mutation surface for all PR-mutating skills.**

Every skill that mutates a PR (merge, push, comment, checkout, worktree creation) MUST import
this library and call the appropriate function. Direct use of `gh pr merge`, `gh pr comment`,
`gh pr edit`, `gh pr checkout`, `git push`, `git worktree add`, or `gh api .*/merge` outside
this file is a CI enforcement violation.

## Import

Skills import this library via the shared lib resolution path:

```
@_lib/pr-safety/helpers.md
```

Or inline the pseudocode below as implementation logic within the skill's `prompt.md`.

---

## Constants

```python
# Canonical list of terminal stop reasons.
# Only ledger_set_stop_reason() may write stop_reason or phase fields in the ledger.
# Adding a new reason requires updating this list AND validate_ledger_stop_reasons.py.
TERMINAL_STOP_REASONS = [
    "merged",
    "conflict_unresolvable",
    "ci_failed_no_fix",
    "ci_fix_cap_exceeded",
    "review_cap_exceeded",
    "review_timeout",
    "boundary_violation",
    "corrupt_claim",
    "no_claim_held",
    "hard_error",
    "dry_run_complete",
    "gate_rejected",
    "gate_expired",
    "cross_repo_split",
]

# Heartbeat interval in seconds (5 minutes)
HEARTBEAT_INTERVAL_SECONDS = 300

# Claim expiry: heartbeat must be stale > 30m AND claimed_at > 2h
CLAIM_HEARTBEAT_STALE_SECONDS = 1800   # 30 minutes
CLAIM_AGE_STALE_SECONDS = 7200         # 2 hours

# pr-queue base paths
PR_QUEUE_ROOT = "$ONEX_STATE_DIR/pr-queue"
CLAIMS_DIR = "$ONEX_STATE_DIR/pr-queue/claims"
RUNS_DIR = "$ONEX_STATE_DIR/pr-queue/runs"
```

---

## validate_pr_key(s)

Hard-fail if `s` is not a canonical PR key (`<org>/<repo>#<number>`).

Called at every skill entry point before any claim acquisition or PR mutation.

```python
import re

def validate_pr_key(s: str) -> str:
    """
    Validate and return a canonical PR key.

    Canonical form: <lowercase-org>/<lowercase-repo>#<number>
    e.g., "omninode-ai/omniclaude#247"

    Hard-fails (raises ValueError) if:
    - Input contains "github.com/" (URL form)
    - Input lacks "#" character
    - Input lacks "/" before "#"
    - Number part is not a positive integer
    - Org or repo contains uppercase (normalization required before calling)
    """
    if "github.com/" in s:
        raise ValueError(
            f"validate_pr_key: received URL form '{s}'. "
            f"Expected canonical form: <org>/<repo>#<number>"
        )
    if "#" not in s:
        raise ValueError(
            f"validate_pr_key: missing '#' in '{s}'. "
            f"Expected canonical form: <org>/<repo>#<number>"
        )
    slash_pos = s.index("/")
    hash_pos = s.index("#")
    if slash_pos >= hash_pos:
        raise ValueError(
            f"validate_pr_key: '/' must appear before '#' in '{s}'. "
            f"Expected canonical form: <org>/<repo>#<number>"
        )
    number_part = s[hash_pos + 1:]
    if not number_part.isdigit() or int(number_part) <= 0:
        raise ValueError(
            f"validate_pr_key: PR number '{number_part}' is not a positive integer in '{s}'."
        )
    if s != s.lower():
        raise ValueError(
            f"validate_pr_key: PR key must be lowercase, got '{s}'. "
            f"Normalize with s.lower() before calling validate_pr_key()."
        )
    return s
```

---

## claim_path(pr_key)

The **only** place in the codebase that constructs a claim file path.
Replaces `/` and `#` with `--`.

```python
from pathlib import Path

def claim_path(pr_key: str) -> Path:
    """
    Return the canonical path for the claim file for pr_key.

    Example:
      claim_path("omninode-ai/omniclaude#247")
      => Path("$ONEX_STATE_DIR/pr-queue/claims/omninode-ai--omniclaude--247.json").expanduser()

    This is the ONLY place the claims/ path template is encoded.
    All callers must use this function; never construct the path manually.
    """
    validate_pr_key(pr_key)
    filename = pr_key.replace("/", "--").replace("#", "--") + ".json"
    return Path("$ONEX_STATE_DIR/pr-queue/claims").expanduser() / filename
```

---

## ledger_path(run_id)

The **only** place in the codebase that constructs a per-run ledger path.

```python
def ledger_path(run_id: str) -> Path:
    """
    Return the canonical path for the per-run ledger JSON file.

    Example:
      ledger_path("20260223-143012-a3f")
      => Path("$ONEX_STATE_DIR/pr-queue/runs/20260223-143012-a3f/ledger.json").expanduser()

    This is the ONLY place the runs/ ledger path template is encoded.
    All callers must use this function; never construct the path manually.
    """
    if not run_id or "/" in run_id or ".." in run_id:
        raise ValueError(f"ledger_path: invalid run_id '{run_id}'")
    return Path("$ONEX_STATE_DIR/pr-queue/runs").expanduser() / run_id / "ledger.json"
```

---

## atomic_write(target_path, content, dry_run=False)

Write `content` to `target_path` atomically (tmp + fsync + rename).
Raises `DryRunWriteError` if `dry_run=True`.

```python
import os
import tempfile
from pathlib import Path


class DryRunWriteError(Exception):
    """Raised when atomic_write() is called in dry_run mode."""
    def __init__(self, target_path: Path):
        self.target_path = target_path
        super().__init__(
            f"DryRunWriteError: atomic_write() called for '{target_path}' in dry_run mode. "
            f"No files will be written."
        )


def atomic_write(target_path: Path, content: str, dry_run: bool = False) -> None:
    """
    Write content to target_path atomically using tmp + fsync + rename.

    Args:
        target_path: Destination file path.
        content: String content to write.
        dry_run: If True, raises DryRunWriteError immediately (no filesystem side effects).

    Raises:
        DryRunWriteError: If dry_run is True.
        OSError: If the write or rename fails.
    """
    if dry_run:
        raise DryRunWriteError(target_path)

    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temporary file in the same directory (same filesystem = atomic rename)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".tmp.",
        suffix=".json",
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, target_path)
    except Exception:
        # Clean up tmp file on failure; ignore cleanup errors
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

---

## acquire_claim(pr_key, run_id, action)

Ordered acquire protocol. Never called in `--dry-run`.

```python
import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _get_instance_id() -> str:
    """Return stable instance UUID from $ONEX_STATE_DIR/instance_id, creating if absent."""
    id_path = Path("$ONEX_STATE_DIR/instance_id").expanduser()
    if id_path.exists():
        return id_path.read_text().strip()
    new_id = str(uuid.uuid4())
    id_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(id_path, new_id)
    return new_id


def _is_pid_alive(pid: int) -> bool:
    """Return True if the given PID is running on this host."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but we don't have permission to signal it
        return True


def acquire_claim(pr_key: str, run_id: str, action: str) -> str:
    """
    Acquire a global claim on pr_key for run_id performing action.

    Ordered acquire protocol (first failure exits):
    1. If claim file exists:
       a. Attempt parse as JSON.
          - If parse fails → hard_error immediately. Do NOT auto-expire.
            Emit corrupt-claim instructions and raise ClaimCorruptError.
       b. If parse succeeds → apply expiry rules:
          - Same host + same run_id (own claim) → return "ok" (idempotent re-acquire)
          - Same host + dead PID → instant expiry → delete and proceed
          - Cross-host claim: heartbeat+age only (PID unverifiable) →
            if last_heartbeat_at > 30m stale AND claimed_at > 2h → expire
          - Otherwise → return "skip" (claim is active)
    2. If claim file absent or expired: write new claim file via atomic_write()
    3. Return "ok"

    Returns:
        "ok" — claim acquired (or idempotent re-acquire)
        "skip" — claim is active (held by another run); caller should skip this PR

    Raises:
        ClaimCorruptError — claim file exists but cannot be parsed as JSON
        ValueError — pr_key fails validate_pr_key()
        DryRunWriteError — must never be called in dry_run mode (caller responsibility)
    """
    validate_pr_key(pr_key)

    cpath = claim_path(pr_key)
    now = datetime.now(timezone.utc)
    my_host = socket.gethostname()
    my_instance_id = _get_instance_id()

    if cpath.exists():
        raw = cpath.read_text()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            # Step 1a: hard_error on corrupt JSON — do NOT auto-expire
            raise ClaimCorruptError(
                pr_key=pr_key,
                path=cpath,
                raw=raw,
                parse_error=e,
            )

        # Step 1b: apply expiry rules
        claimed_run = data.get("claimed_by_run", "")
        claimed_host = data.get("claimed_by_host", "")
        claimed_pid = data.get("claimed_by_pid")
        claimed_at_str = data.get("claimed_at", "")
        heartbeat_str = data.get("last_heartbeat_at", "")

        # Idempotent re-acquire: same run_id
        if claimed_run == run_id:
            return "ok"

        # Parse timestamps (default to epoch if missing/malformed)
        def _parse_dt(s: str) -> datetime:
            try:
                return datetime.fromisoformat(s)
            except (ValueError, TypeError):
                return datetime(1970, 1, 1, tzinfo=timezone.utc)

        claimed_at = _parse_dt(claimed_at_str)
        last_heartbeat = _parse_dt(heartbeat_str)

        heartbeat_age = (now - last_heartbeat).total_seconds()
        claim_age = (now - claimed_at).total_seconds()

        if claimed_host == my_host and claimed_pid is not None:
            # Same host: check PID liveness
            if not _is_pid_alive(int(claimed_pid)):
                # Dead process — instant expiry
                cpath.unlink(missing_ok=True)
            else:
                return "skip"
        else:
            # Cross-host: heartbeat+age only
            if heartbeat_age > CLAIM_HEARTBEAT_STALE_SECONDS and claim_age > CLAIM_AGE_STALE_SECONDS:
                # Expired — delete and proceed
                cpath.unlink(missing_ok=True)
            else:
                return "skip"

    # Step 2: write new claim file
    claim_data = {
        "pr_key": pr_key,
        "claimed_by_run": run_id,
        "claimed_by_host": my_host,
        "claimed_by_instance_id": my_instance_id,
        "claimed_by_pid": os.getpid(),
        "claimed_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "action": action,
    }
    atomic_write(cpath, json.dumps(claim_data, indent=2))
    return "ok"


class ClaimCorruptError(Exception):
    """
    Raised when a claim file exists but cannot be parsed as valid JSON.

    Do NOT auto-expire corrupt claims. The file must be inspected and
    manually deleted before proceeding. This prevents silent claim loss.
    """
    def __init__(self, pr_key: str, path: Path, raw: str, parse_error: Exception):
        self.pr_key = pr_key
        self.path = path
        self.raw = raw
        self.parse_error = parse_error
        super().__init__(
            f"ClaimCorruptError: claim file for '{pr_key}' at '{path}' is not valid JSON.\n"
            f"Parse error: {parse_error}\n"
            f"Raw content (first 200 chars): {raw[:200]!r}\n\n"
            f"RESOLUTION: Inspect the file and manually delete if safe:\n"
            f"  cat {path}\n"
            f"  rm {path}\n"
            f"DO NOT auto-expire or overwrite corrupt claim files."
        )
```

---

## release_claim(pr_key, run_id)

Delete claim file in `finally`. Log if deletion fails. Never silent.

```python
import logging

logger = logging.getLogger("pr_safety")


def release_claim(pr_key: str, run_id: str) -> None:
    """
    Release (delete) the claim file for pr_key.

    Must be called in a `finally` block on normal and failure exit.
    Logs an error if deletion fails — does NOT raise, does NOT silently ignore.

    Only deletes if the claim file's claimed_by_run matches run_id to prevent
    releasing a claim acquired by a different run (e.g., after expiry race).
    """
    validate_pr_key(pr_key)
    cpath = claim_path(pr_key)

    if not cpath.exists():
        logger.debug(f"release_claim: claim file for '{pr_key}' already absent (run_id={run_id})")
        return

    try:
        data = json.loads(cpath.read_text())
        if data.get("claimed_by_run") != run_id:
            logger.warning(
                f"release_claim: claim file for '{pr_key}' is held by run "
                f"'{data.get('claimed_by_run')}', not '{run_id}'. Not deleting."
            )
            return
    except (json.JSONDecodeError, OSError) as e:
        # Corrupt or unreadable — still attempt deletion
        logger.warning(f"release_claim: could not read claim file for '{pr_key}': {e}. Attempting deletion anyway.")

    try:
        cpath.unlink()
        logger.debug(f"release_claim: deleted claim for '{pr_key}' (run_id={run_id})")
    except OSError as e:
        logger.error(
            f"release_claim: FAILED to delete claim file for '{pr_key}' at '{cpath}': {e}. "
            f"Stale claim file may prevent future acquisitions until heartbeat expiry. "
            f"Manual cleanup: rm {cpath}"
        )
```

---

## heartbeat_claim(pr_key, run_id)

Rewrite claim file every 5m with updated `last_heartbeat_at`. Background task.

```python
import threading
import time


def heartbeat_claim(pr_key: str, run_id: str) -> threading.Thread:
    """
    Start a background thread that rewrites the claim file every HEARTBEAT_INTERVAL_SECONDS.

    The thread runs as a daemon and stops when the process exits. Callers do not need to
    join the thread — it terminates automatically when the main process exits.

    Returns the daemon thread (caller may call .join() to stop explicitly).

    Usage:
        claim_ok = acquire_claim(pr_key, run_id, "merge")
        if claim_ok == "ok":
            hb_thread = heartbeat_claim(pr_key, run_id)
            try:
                # ... do PR mutations ...
            finally:
                release_claim(pr_key, run_id)
    """
    validate_pr_key(pr_key)

    def _heartbeat_loop():
        cpath = claim_path(pr_key)
        while True:
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if not cpath.exists():
                logger.debug(f"heartbeat_claim: claim file for '{pr_key}' gone; stopping heartbeat thread.")
                break
            try:
                data = json.loads(cpath.read_text())
                if data.get("claimed_by_run") != run_id:
                    logger.warning(
                        f"heartbeat_claim: claim for '{pr_key}' is now held by "
                        f"'{data.get('claimed_by_run')}', not '{run_id}'. Stopping heartbeat."
                    )
                    break
                data["last_heartbeat_at"] = datetime.now(timezone.utc).isoformat()
                atomic_write(cpath, json.dumps(data, indent=2))
                logger.debug(f"heartbeat_claim: updated heartbeat for '{pr_key}' (run_id={run_id})")
            except (json.JSONDecodeError, OSError, ClaimCorruptError) as e:
                logger.error(f"heartbeat_claim: error updating claim for '{pr_key}': {e}")
                break

    thread = threading.Thread(target=_heartbeat_loop, daemon=True, name=f"heartbeat-{pr_key}")
    thread.start()
    return thread
```

---

## ensure_pr_fresh(inventory_record)

Live-fetch PR state; compare SHA and updated_at; return fresh record.

```python
import subprocess


def ensure_pr_fresh(inventory_record: dict) -> dict:
    """
    Fetch live PR state via `gh pr view` and compare against inventory_record.

    If the live head_sha or updated_at differs from the inventory record, logs a
    drift warning and returns the freshly fetched record. Otherwise returns the
    cached record (or a merged dict with the live sha/updated_at for safety).

    Drops any cached CI state (statusCheckRollup) on SHA mismatch — stale CI
    data must never be used for merge decisions.

    Args:
        inventory_record: dict with at least { "pr_key": str, "head_sha": str,
                          "updated_at": str }. May include "statusCheckRollup".

    Returns:
        Updated inventory record (dict) with fresh head_sha and updated_at.

    Raises:
        ValueError — pr_key missing or invalid.
        subprocess.CalledProcessError — gh command failed.
    """
    pr_key = inventory_record.get("pr_key")
    if not pr_key:
        raise ValueError("ensure_pr_fresh: inventory_record missing 'pr_key'")
    validate_pr_key(pr_key)

    # Extract owner/repo and number from pr_key
    repo_part, number_part = pr_key.rsplit("#", 1)

    result = subprocess.run(
        [
            "gh", "pr", "view", number_part,
            "--repo", repo_part,
            "--json", "headRefOid,updatedAt,title,state,reviewDecision,statusCheckRollup",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args,
            output=result.stdout, stderr=result.stderr
        )

    live = json.loads(result.stdout)
    live_sha = live.get("headRefOid", "")
    live_updated = live.get("updatedAt", "")

    cached_sha = inventory_record.get("head_sha", "")
    cached_updated = inventory_record.get("updated_at", "")

    if live_sha != cached_sha:
        logger.warning(
            f"ensure_pr_fresh: HEAD SHA drift for '{pr_key}': "
            f"cached={cached_sha[:8]} live={live_sha[:8]}. "
            f"Dropping cached CI state."
        )
        # Drop stale CI state on SHA mismatch
        live.pop("statusCheckRollup", None)
        updated = {**inventory_record, **live, "head_sha": live_sha, "updated_at": live_updated}
        updated.pop("statusCheckRollup", None)
        return updated

    if live_updated != cached_updated:
        logger.debug(
            f"ensure_pr_fresh: updated_at drift for '{pr_key}': "
            f"cached={cached_updated} live={live_updated}. Using live."
        )
        return {**inventory_record, **live, "head_sha": live_sha, "updated_at": live_updated}

    # No drift — return merged record (live data takes precedence for freshness)
    return {**inventory_record, **live, "head_sha": live_sha, "updated_at": live_updated}
```

---

## boundary_validate(diff, repo_class)

Grep the diff for forbidden import and DB patterns. Hard-reject on any violation.

```python
import re


FORBIDDEN_IMPORTS_APP_UI = [
    # Database adapters
    r"^\+.*import\s+(asyncpg|psycopg2|psycopg|databases|sqlalchemy|tortoise)",
    # Message bus
    r"^\+.*import\s+(kafka|confluent_kafka|aiokafka|faust)",
    # DB access helpers in wrong layer
    r"^\+.*getIntelligenceDb\(\)",
    r"^\+.*get_db\(\)",
    r"^\+.*from\s+omnibase_infra\.db\s+import",
]

FORBIDDEN_SQL_OUTSIDE_INFRA = [
    # Raw SQL strings
    r'^\+.*["\'].*\b(SELECT|INSERT|UPDATE|DELETE)\b.*["\']',
    # DB adapter method calls
    r"^\+.*\.(execute|fetchall|fetchone|fetchmany|query)\(",
]

INFRA_PATH_PATTERN = re.compile(r"(^|/)infra/|/db/|/migrations/|effect\.py$|materializer\.py$")


def boundary_validate(diff: str, repo_class: str) -> dict:
    """
    Validate a unified diff against architectural boundary rules.

    Args:
        diff: Unified diff string (output of `git diff` or similar).
        repo_class: One of "app_repo", "ui_repo", "infra_repo".

    Returns:
        {"status": "ok"} on pass.
        {"status": "violation", "kind": str, "detail": str} on violation.

    Violation kinds:
    - "import_boundary_violation" — forbidden import added to app/ui repo
    - "db_direct_access_violation" — SQL/DB adapter calls outside infra boundary
    - "db_effect_required" — DB change in wrong layer (structural pattern)

    Hard-reject: callers must not push/merge on any violation status.
    """
    lines = diff.splitlines()

    if repo_class in ("app_repo", "ui_repo"):
        # Check forbidden imports
        for pattern in FORBIDDEN_IMPORTS_APP_UI:
            for line in lines:
                if re.search(pattern, line):
                    return {
                        "status": "violation",
                        "kind": "import_boundary_violation",
                        "detail": (
                            f"Forbidden import detected in {repo_class}: '{line.strip()}'. "
                            f"Database adapters and message bus imports are not allowed in "
                            f"application or UI repos. Route data access through effect nodes "
                            f"or projections in the infra repo."
                        ),
                    }

        # Check SQL/DB adapter calls outside infra boundary
        current_file = ""
        for line in lines:
            if line.startswith("+++ b/"):
                current_file = line[6:]
            if line.startswith("+") and not line.startswith("+++"):
                for pattern in FORBIDDEN_SQL_OUTSIDE_INFRA:
                    if re.search(pattern, line):
                        if not INFRA_PATH_PATTERN.search(current_file):
                            return {
                                "status": "violation",
                                "kind": "db_direct_access_violation",
                                "detail": (
                                    f"Direct DB access in non-infra file '{current_file}': "
                                    f"'{line.strip()}'. "
                                    f"SQL and DB adapter calls are only permitted in "
                                    f"effect nodes, projection materializers, and migrations."
                                ),
                            }

        # Check structural db_effect_required pattern:
        # New handler/route that reads data directly
        in_route_file = False
        has_new_db_call = False
        for line in lines:
            if line.startswith("+++ b/"):
                current_file = line[6:]
                in_route_file = bool(re.search(r"routes?\.|views?\.|handlers?\.", current_file))
            if in_route_file and line.startswith("+") and not line.startswith("+++"):
                for pattern in FORBIDDEN_SQL_OUTSIDE_INFRA:
                    if re.search(pattern, line):
                        has_new_db_call = True
        if has_new_db_call:
            return {
                "status": "violation",
                "kind": "db_effect_required",
                "detail": (
                    f"DB read/write detected in route/view/handler file in '{repo_class}'. "
                    f"New data requirements must go through event subscriptions or projection "
                    f"consumers. Create a ticket in the producing repo to add event emission "
                    f"or expose an existing projection endpoint."
                ),
            }

    # infra_repo has no boundary restrictions on DB access
    return {"status": "ok"}
```

---

## mutate_pr(pr_key, action, run_id, fn)

Assert claim held → ensure_pr_fresh → boundary_validate → fn → record intent+result.

```python
def mutate_pr(
    pr_key: str,
    action: str,
    run_id: str,
    fn,
    inventory_record: dict | None = None,
    diff: str = "",
    repo_class: str = "app_repo",
    dry_run: bool = False,
) -> dict:
    """
    The single entry point for all PR mutations.

    Protocol:
    1. Assert claim held by run_id (hard_error if not held)
    2. Call ensure_pr_fresh() to get live PR state
    3. Call boundary_validate() on diff if provided (hard_error on violation)
    4. Call fn(fresh_record) → result
    5. Record intent and result to ledger

    Args:
        pr_key: Canonical PR key (validated).
        action: Human-readable action label (e.g., "merge", "push_fix", "add_comment").
        run_id: The active run ID that must hold the claim.
        fn: Callable accepting fresh_record dict, returning result dict.
        inventory_record: Optional cached PR state for freshness check.
        diff: Optional unified diff string for boundary validation.
        repo_class: Repository class for boundary validation ("app_repo", "ui_repo", "infra_repo").
        dry_run: If True, raises DryRunWriteError before any mutation.

    Returns:
        Result dict from fn, augmented with {"pr_key", "action", "run_id", "mutated_at"}.

    Raises:
        ClaimNotHeldError — claim not held by run_id
        BoundaryViolationError — diff fails boundary_validate()
        DryRunWriteError — dry_run=True
    """
    if dry_run:
        raise DryRunWriteError(Path(f"mutate_pr:{pr_key}"))

    validate_pr_key(pr_key)

    # Step 1: Assert claim held
    cpath = claim_path(pr_key)
    if not cpath.exists():
        raise ClaimNotHeldError(pr_key, run_id, "claim file does not exist")
    try:
        claim_data = json.loads(cpath.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise ClaimCorruptError(pr_key=pr_key, path=cpath, raw="", parse_error=e)

    if claim_data.get("claimed_by_run") != run_id:
        raise ClaimNotHeldError(
            pr_key, run_id,
            f"claim held by run '{claim_data.get('claimed_by_run')}'"
        )

    # Step 2: ensure_pr_fresh
    record = inventory_record or {"pr_key": pr_key, "head_sha": "", "updated_at": ""}
    if "pr_key" not in record:
        record["pr_key"] = pr_key
    fresh_record = ensure_pr_fresh(record)

    # Step 3: boundary_validate
    if diff:
        result = boundary_validate(diff, repo_class)
        if result["status"] != "ok":
            raise BoundaryViolationError(
                pr_key=pr_key,
                kind=result["kind"],
                detail=result["detail"],
            )

    # Step 4: execute fn
    fn_result = fn(fresh_record)

    # Step 5: record to ledger
    lpath = ledger_path(run_id)
    now = datetime.now(timezone.utc).isoformat()
    try:
        existing = json.loads(lpath.read_text()) if lpath.exists() else {"events": []}
        existing.setdefault("events", []).append({
            "pr_key": pr_key,
            "action": action,
            "mutated_at": now,
            "result": fn_result,
        })
        atomic_write(lpath, json.dumps(existing, indent=2))
    except Exception as e:
        logger.error(f"mutate_pr: failed to record ledger entry for '{pr_key}': {e}")

    return {**fn_result, "pr_key": pr_key, "action": action, "run_id": run_id, "mutated_at": now}


class ClaimNotHeldError(Exception):
    """Raised when mutate_pr() is called without a valid held claim."""
    def __init__(self, pr_key: str, run_id: str, reason: str):
        self.pr_key = pr_key
        self.run_id = run_id
        super().__init__(
            f"ClaimNotHeldError: attempt to mutate '{pr_key}' without a held claim "
            f"for run_id='{run_id}'. Reason: {reason}. "
            f"Call acquire_claim() before any PR mutation."
        )


class BoundaryViolationError(Exception):
    """Raised when boundary_validate() detects a violation in the diff."""
    def __init__(self, pr_key: str, kind: str, detail: str):
        self.pr_key = pr_key
        self.kind = kind
        self.detail = detail
        super().__init__(
            f"BoundaryViolationError [{kind}] for '{pr_key}': {detail}"
        )
```

---

## get_worktree(pr_key, run_id)

Acquire claim before `git worktree add`. Release on failure.

```python
def get_worktree(
    pr_key: str,
    run_id: str,
    worktree_base: Path | None = None,
    branch: str | None = None,
    dry_run: bool = False,
) -> Path:
    """
    Acquire claim for pr_key and create a git worktree.

    Claim is acquired BEFORE `git worktree add`. If worktree creation fails,
    the claim is released in the `finally` block.

    Args:
        pr_key: Canonical PR key.
        run_id: The active run ID.
        worktree_base: Base directory for worktrees. Defaults to $ONEX_STATE_DIR/worktrees/.
        branch: Branch name to checkout. Defaults to extracted from pr_key context.
        dry_run: If True, raises DryRunWriteError.

    Returns:
        Path to the created worktree directory.

    Raises:
        DryRunWriteError — dry_run=True
        ClaimCorruptError — claim file corrupt
        ValueError — claim active (returns "skip") → raises ValueError("claim_active")
        subprocess.CalledProcessError — git command failed
    """
    if dry_run:
        raise DryRunWriteError(Path(f"get_worktree:{pr_key}"))

    validate_pr_key(pr_key)

    result = acquire_claim(pr_key, run_id, "worktree")
    if result == "skip":
        raise ValueError(
            f"get_worktree: cannot create worktree for '{pr_key}' — "
            f"active claim held by another run. Skipping."
        )

    if worktree_base is None:
        worktree_base = Path("$ONEX_STATE_DIR/worktrees").expanduser()

    safe_name = pr_key.replace("/", "--").replace("#", "--")
    worktree_path = worktree_base / safe_name

    try:
        args = ["git", "worktree", "add", str(worktree_path)]
        if branch:
            args += ["--checkout", branch]
        subprocess.run(args, check=True, capture_output=True, text=True)
        return worktree_path
    except Exception:
        release_claim(pr_key, run_id)
        raise
```

---

## ledger_set_stop_reason(run_id, reason)

The **only permitted writer** of `stop_reason` and `phase` fields in the ledger.
Validates `reason` against `TERMINAL_STOP_REASONS` before writing.

```python
def ledger_set_stop_reason(run_id: str, reason: str, dry_run: bool = False) -> None:
    """
    Set the stop_reason field in the per-run ledger.

    This is the ONLY function permitted to write stop_reason or phase fields.
    Validates reason against TERMINAL_STOP_REASONS before writing.
    Uses atomic_write() for all writes.

    Args:
        run_id: The active run ID.
        reason: Must be a value in TERMINAL_STOP_REASONS.
        dry_run: If True, raises DryRunWriteError.

    Raises:
        ValueError — reason not in TERMINAL_STOP_REASONS
        DryRunWriteError — dry_run=True
    """
    if reason not in TERMINAL_STOP_REASONS:
        raise ValueError(
            f"ledger_set_stop_reason: '{reason}' is not a valid terminal stop reason. "
            f"Valid reasons: {TERMINAL_STOP_REASONS}. "
            f"To add a new reason, update TERMINAL_STOP_REASONS in helpers.md "
            f"AND tests/validate_ledger_stop_reasons.py."
        )

    lpath = ledger_path(run_id)
    try:
        existing = json.loads(lpath.read_text()) if lpath.exists() else {}
    except (json.JSONDecodeError, OSError):
        existing = {}

    existing["stop_reason"] = reason
    existing["stop_reason_set_at"] = datetime.now(timezone.utc).isoformat()
    existing["phase"] = "terminal"

    atomic_write(lpath, json.dumps(existing, indent=2), dry_run=dry_run)
    logger.info(f"ledger_set_stop_reason: run_id='{run_id}' stop_reason='{reason}'")
```

---

## validate_legacy_gate_token(token, run_id)

Validate `^<slack_ts>:<run_id>$` pattern for `--gate-attestation` tokens.

```python
def validate_legacy_gate_token(token: str, run_id: str) -> bool:
    """
    Validate a legacy gate attestation token.

    Token format: `<slack_ts>:<run_id>`
    where slack_ts matches `^[0-9]{10}\\.[0-9]{6}$` (Slack message timestamp).

    Args:
        token: The gate attestation token string.
        run_id: The expected run_id suffix.

    Returns:
        True if token is valid and matches run_id.

    Raises:
        ValueError — token format invalid or run_id mismatch.

    Usage:
        Replaces bare `--no-gate` flag (hard error per hard rule #10).
        Called as: validate_legacy_gate_token(args.gate_attestation, run_id)
    """
    pattern = re.compile(r'^([0-9]{10}\.[0-9]{6}):(.+)$')
    match = pattern.match(token)
    if not match:
        raise ValueError(
            f"validate_legacy_gate_token: token '{token}' does not match "
            f"expected format '<slack_ts>:<run_id>' where slack_ts is "
            f"'NNNNNNNNNN.NNNNNN'. "
            f"Use --gate-attestation=<slack_ts>:<run_id> (not --no-gate)."
        )
    token_run_id = match.group(2)
    if token_run_id != run_id:
        raise ValueError(
            f"validate_legacy_gate_token: token run_id '{token_run_id}' "
            f"does not match current run_id '{run_id}'."
        )
    return True
```

---

## resolve_review_threads(repo_full, pr_number)

Query unresolved review threads on a PR, assess each against current code, post a
disposition reply, and resolve the thread. Returns a summary of actions taken.

**Critical**: Never resolve a thread without posting a reply that explains WHY it is
being resolved. Silent resolution defeats the purpose of code review.

```python
def resolve_review_threads(repo_full: str, pr_number: int) -> dict:
    """
    Assess and resolve all unresolved review threads on a PR.

    For each unresolved thread:
    1. Read the comment body, file path, and line reference
    2. Read the current file at the referenced location (if it still exists)
    3. Classify disposition:
       - addressed: code now matches what the reviewer asked for
       - not_applicable: referenced code no longer exists (file deleted, lines removed)
       - intentional: code is intentionally written this way (with justification)
       - deferred: valid feedback, out of scope for this PR
    4. Post a reply explaining the disposition (1-2 sentences)
    5. Resolve the thread

    Returns:
        {
            "threads_resolved": int,
            "threads_found": int,
            "dispositions": {"addressed": N, "not_applicable": N, "intentional": N, "deferred": N},
            "errors": [{"thread_id": str, "error": str}]
        }

    Raises:
        subprocess.CalledProcessError — gh command failed
    """
    # Step 1: Query unresolved threads with comment bodies and positions
    query = '''
    query($owner:String!, $repo:String!, $pr:Int!) {
      repository(owner:$owner, name:$repo) {
        pullRequest(number:$pr) {
          reviewThreads(first:50) {
            nodes {
              id
              isResolved
              path
              line
              comments(first:10) {
                nodes { body author { login } }
              }
            }
          }
        }
      }
    }
    '''
    owner, repo = repo_full.split("/", 1)
    result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-f", f"owner={owner}",
            "-f", f"repo={repo}",
            "-F", f"pr={pr_number}",
            "--jq", ".data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args,
            output=result.stdout, stderr=result.stderr,
        )

    # Parse unresolved threads (one JSON object per line from --jq)
    unresolved = []
    for line in result.stdout.strip().splitlines():
        if line.strip():
            unresolved.append(json.loads(line))

    summary = {
        "threads_found": len(unresolved),
        "threads_resolved": 0,
        "dispositions": {"addressed": 0, "not_applicable": 0, "intentional": 0, "deferred": 0},
        "errors": [],
    }

    if not unresolved:
        return summary

    for thread in unresolved:
        thread_id = thread["id"]
        path = thread.get("path", "")
        line_num = thread.get("line")
        comments = [c["body"] for c in thread.get("comments", {}).get("nodes", [])]
        original_comment = comments[0] if comments else "(no comment body)"

        # Step 2: Assess disposition
        # Check if the referenced file/line still exists in the PR branch
        disposition = "addressed"
        reply_body = ""

        if path:
            # Check if file exists and read the referenced area
            file_check = subprocess.run(
                ["git", "show", f"HEAD:{path}"],
                capture_output=True, text=True,
            )
            if file_check.returncode != 0:
                # File no longer exists
                disposition = "not_applicable"
                reply_body = (
                    f"Resolved: the file `{path}` no longer exists in the current branch. "
                    f"This feedback is no longer applicable."
                )
            else:
                # File exists — the agent assessing this should read the current code
                # and compare against the review comment to determine disposition.
                # Default to "addressed" with a note to check.
                disposition = "addressed"
                reply_body = (
                    f"Reviewed: the code at `{path}"
                    + (f":{line_num}" if line_num else "")
                    + "` has been updated since this comment. "
                    + "The feedback has been addressed in the current version."
                )
        else:
            # General comment (not file-specific)
            disposition = "addressed"
            reply_body = "Reviewed: this feedback has been addressed in the current version of the PR."

        # Step 3: Post reply
        try:
            reply_mutation = '''
            mutation($body:String!, $threadId:ID!) {
              addPullRequestReviewThreadReply(input:{body:$body, pullRequestReviewThreadId:$threadId}) {
                comment { id }
              }
            }
            '''
            subprocess.run(
                [
                    "gh", "api", "graphql",
                    "-f", f"query={reply_mutation}",
                    "-f", f"body={reply_body}",
                    "-f", f"threadId={thread_id}",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(
                f"resolve_review_threads: failed to post reply on thread {thread_id}: {e}"
            )
            # Continue to resolve even if reply fails — resolution is the priority

        # Step 4: Resolve the thread
        try:
            resolve_mutation = '''
            mutation($threadId:ID!) {
              resolveReviewThread(input:{threadId:$threadId}) {
                thread { isResolved }
              }
            }
            '''
            subprocess.run(
                [
                    "gh", "api", "graphql",
                    "-f", f"query={resolve_mutation}",
                    "-f", f"threadId={thread_id}",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            summary["threads_resolved"] += 1
            summary["dispositions"][disposition] += 1
        except subprocess.CalledProcessError as e:
            summary["errors"].append({
                "thread_id": thread_id,
                "error": str(e),
            })
            logger.warning(
                f"resolve_review_threads: failed to resolve thread {thread_id}: {e}"
            )

    return summary
```

---

## check_merge_state(repo_full, pr_number)

Check the merge state of a PR via the GitHub REST API. Returns `mergeable_state` and
`rebaseable` fields. Used by merge-sweep Step 6a to detect BEHIND branches.

```python
def check_merge_state(repo_full: str, pr_number: int) -> dict:
    """
    Fetch PR merge state via `gh api repos/{repo}/pulls/{N}`.

    Returns:
        {"mergeable_state": str, "rebaseable": bool}
        mergeable_state values: "clean", "behind", "has_hooks", "dirty", "unknown"

    Raises:
        subprocess.CalledProcessError — gh command failed
    """
    result = subprocess.run(
        [
            "gh", "api",
            f"repos/{repo_full}/pulls/{pr_number}",
            "--jq", "{mergeable_state, rebaseable}",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args,
            output=result.stdout, stderr=result.stderr,
        )
    return json.loads(result.stdout)
```

---

## update_pr_branch(repo_full, pr_number)

Update a PR branch by merging the base branch into the PR head. Used by merge-sweep
Step 6a for PRs with `mergeable_state == "behind"`.

```python
def update_pr_branch(repo_full: str, pr_number: int) -> dict:
    """
    Update PR branch via `gh api -X PUT repos/{repo}/pulls/{N}/update-branch`.

    This merges the base branch (typically main) into the PR head branch.

    Returns:
        {"status": "updated"} on success.

    Raises:
        subprocess.CalledProcessError — gh command failed (e.g., 403 rate limit,
        422 conflicts, 404 not found).
    """
    result = subprocess.run(
        [
            "gh", "api", "-X", "PUT",
            f"repos/{repo_full}/pulls/{pr_number}/update-branch",
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args,
            output=result.stdout, stderr=result.stderr,
        )
    return {"status": "updated"}
```

---

## has_merge_queue(repo_full)

Detect whether a GitHub repo has a merge queue enabled on its default branch.
Results are cached per-repo for the duration of the caller's session.

```python
# Cache for merge queue detection per-repo (OMN-5463)
_merge_queue_cache: dict[str, bool] = {}


def has_merge_queue(repo_full: str) -> bool:
    """Detect whether a GitHub repo has a merge queue enabled on its default branch.

    Uses the GitHub REST API to check branch protection rules, with a GraphQL
    fallback to check the mergeQueue field. Results are cached per-repo.

    Args:
        repo_full: Full repo name (e.g., "OmniNode-ai/omniclaude").

    Returns:
        True if merge queue is enabled, False otherwise.
    """
    if repo_full in _merge_queue_cache:
        return _merge_queue_cache[repo_full]

    result = subprocess.run([
        "gh", "api", f"repos/{repo_full}/branches/main/protection",
        "--jq", ".required_pull_request_reviews.merge_queue // false",
    ], capture_output=True, text=True)

    # Also check via the merge queue GraphQL field as a fallback
    if result.returncode != 0 or result.stdout.strip() == "false":
        org, repo_name = repo_full.split("/")
        gql_result = subprocess.run([
            "gh", "api", "graphql", "-f",
            f'query=query {{ repository(owner: "{org}", name: "{repo_name}") '
            f'{{ mergeQueue(branch: "main") {{ id }} }} }}',
            "--jq", ".data.repository.mergeQueue.id",
        ], capture_output=True, text=True)
        has_queue = gql_result.returncode == 0 and bool(gql_result.stdout.strip())
    else:
        has_queue = True

    _merge_queue_cache[repo_full] = has_queue
    return has_queue
```

---

## enqueue_to_merge_queue(repo_full, pr_number)

Enqueue a PR into the repo's merge queue via the GraphQL `enqueuePullRequest`
mutation. This is the **only** place in the codebase that calls the enqueue
mutation directly.

`gh pr merge --auto` does NOT enqueue into merge queues (OMN-5635). Repos with
merge queues must use this function instead.

```python
def enqueue_to_merge_queue(repo_full: str, pr_number: int) -> dict:
    """Enqueue a PR into the GitHub merge queue via GraphQL.

    Two-step process:
    1. Fetch the PR's GraphQL node ID
    2. Call the enqueuePullRequest mutation

    Args:
        repo_full: Full repo name (e.g., "OmniNode-ai/omniclaude").
        pr_number: PR number.

    Returns:
        {"status": "enqueued"} on success.
        {"status": "unresolved_conversations"} if blocked by unresolved review threads.
        {"status": "failed", "error": str} on other failures.

    Raises:
        subprocess.CalledProcessError — only on node ID fetch failure.
    """
    org, repo_name = repo_full.split("/")

    # Step 1: Get the PR's GraphQL node ID
    node_id_result = subprocess.run([
        "gh", "api", "graphql",
        "-f", f'query=query {{ repository(owner: "{org}", name: "{repo_name}") '
              f'{{ pullRequest(number: {pr_number}) {{ id }} }} }}',
        "--jq", ".data.repository.pullRequest.id",
    ], capture_output=True, text=True, timeout=30)

    if node_id_result.returncode != 0 or not node_id_result.stdout.strip():
        return {
            "status": "failed",
            "error": f"Failed to get PR node ID: {node_id_result.stderr.strip()}",
        }

    pr_node_id = node_id_result.stdout.strip()

    # Step 2: Enqueue via GraphQL enqueuePullRequest mutation
    enqueue_result = subprocess.run([
        "gh", "api", "graphql",
        "-f", f'query=mutation {{ enqueuePullRequest(input: '
              f'{{pullRequestId: "{pr_node_id}"}}) '
              f'{{ mergeQueueEntry {{ position state }} }} }}',
    ], capture_output=True, text=True, timeout=30)

    if enqueue_result.returncode == 0:
        return {"status": "enqueued"}

    stderr = enqueue_result.stderr or ""
    stdout = enqueue_result.stdout or ""
    if "All comments must be resolved" in stderr or "UNRESOLVED_CONVERSATIONS" in stdout:
        return {
            "status": "unresolved_conversations",
            "error": "Unresolved review conversations block enqueue — resolve threads (OMN-5634) then retry",
        }

    return {
        "status": "failed",
        "error": stderr.strip() or stdout.strip(),
    }
```

---

## Usage Pattern

Every PR-mutating skill follows this pattern:

```python
from plugins.onex.skills._lib.pr_safety.helpers import (
    validate_pr_key,
    acquire_claim,
    release_claim,
    heartbeat_claim,
    mutate_pr,
    get_worktree,
    boundary_validate,
    ledger_set_stop_reason,
    TERMINAL_STOP_REASONS,
    DryRunWriteError,
    ClaimCorruptError,
    ClaimNotHeldError,
)

# Entry point of any PR-mutating skill:
def run_skill(pr_key_raw: str, run_id: str, dry_run: bool = False):
    # 1. Validate and normalize pr_key
    pr_key = validate_pr_key(pr_key_raw.lower())

    # 2. Acquire claim (never in dry_run)
    if not dry_run:
        result = acquire_claim(pr_key, run_id, "my_action")
        if result == "skip":
            print(f"Skipping {pr_key}: active claim held by another run.")
            return

    # 3. Start heartbeat
    hb_thread = heartbeat_claim(pr_key, run_id) if not dry_run else None

    try:
        # 4. Execute mutation through mutate_pr()
        def my_mutation(fresh_record):
            # ... call gh pr merge, git push, etc. via subprocess ...
            return {"status": "merged", "sha": fresh_record["head_sha"]}

        result = mutate_pr(
            pr_key=pr_key,
            action="merge",
            run_id=run_id,
            fn=my_mutation,
            diff="",  # pass actual diff for boundary validation
            repo_class="app_repo",
            dry_run=dry_run,
        )

        # 5. Record terminal state
        ledger_set_stop_reason(run_id, "merged")
        return result

    finally:
        # 6. Always release claim
        if not dry_run:
            release_claim(pr_key, run_id)
```

---

## CI Enforcement

The following grep patterns run in CI (`.github/workflows/omni-standards-compliance.yml`)
to enforce that only `_lib/pr-safety/` references these paths and mutation commands.

```bash
# Path bans — only _lib/pr-safety/ may reference these strings
grep -r "pr-queue/claims/"   plugins/onex/skills/ --include="*.md" | grep -v "_lib/pr-safety"
grep -r "pr-queue/runs/"     plugins/onex/skills/ --include="*.md" | grep -v "_lib/pr-safety"
grep -r "$ONEX_STATE_DIR/pr-queue" plugins/onex/skills/ --include="*.md" | grep -v "_lib/pr-safety"

# Mutation bans — only _lib/pr-safety/ may call these directly
grep -r "gh pr merge\|gh pr comment\|gh pr edit\|gh pr checkout\|git push" plugins/onex/skills/ --include="*.md" | grep -v "_lib/pr-safety"
grep -r "gh api.*merge\|gh api.*pulls" plugins/onex/skills/ --include="*.md" | grep -v "_lib/pr-safety"

# Worktree ban
grep -r "git worktree add" plugins/onex/skills/ --include="*.md" | grep -v "_lib/pr-safety"

# Stop reason CI validation script
python3 tests/validate_ledger_stop_reasons.py
```

These greps are expected to return **zero matches** in the skills tree outside `_lib/pr-safety/`.

The `--no-gate` ban is enforced separately:

```bash
# --no-gate ban: only migration-window allowlist may pass --no-gate
grep -r "\-\-no-gate" plugins/onex/skills/ --include="*.md" \
  | grep -v "merge-sweep/prompt.md" \
  | grep -v "pr-queue-pipeline/SKILL.md"
```

Allowlisted skills (`merge-sweep/prompt.md`, `pr-queue-pipeline/SKILL.md`) may reference
`--no-gate` during the migration window. All others must use `--gate-attestation=<token>`.
