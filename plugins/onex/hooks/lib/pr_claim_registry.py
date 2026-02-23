#!/usr/bin/env python3
"""PR Claim Registry — global mutual-exclusion lock for cross-run PR mutations.

Prevents multiple concurrent skill runs from mutating the same PR simultaneously.
The claim file is the shared lock that all runs read and write; the per-run ledger
is the audit log.

Architecture:
    ~/.claude/pr-queue/claims/<filesystem_key>.json

    filesystem_key = canonical_pr_key with '/' and '#' replaced by '--'
    e.g. "omninode-ai/omniclaude#247" → "omninode-ai--omniclaude--247.json"

Canonical PR key format:
    <lowercase-org>/<lowercase-repo>#<number>
    e.g. "omninode-ai/omniclaude#247"

    Never URL forms, never short forms. Writers normalize; readers validate.

Claim file schema:
    {
        "pr_key": "omninode-ai/omniclaude#247",
        "claimed_by_run": "20260223-143012-a3f",
        "claimed_by_host": "jonah-mbp.local",
        "claimed_by_instance_id": "a3f9c1d2-...",
        "claimed_at": "2026-02-23T14:30:00Z",
        "last_heartbeat_at": "2026-02-23T14:45:00Z",
        "action": "fix_ci"
    }

Expiry policy (BOTH conditions must hold):
    - last_heartbeat_at > 30 minutes stale
    - claimed_at > 2 hours ago

Usage:
    registry = ClaimRegistry()

    # Acquire (in try block)
    acquired = registry.acquire(pr_key="omninode-ai/omniclaude#247",
                                run_id="20260223-143012-a3f",
                                action="fix_ci")
    if not acquired:
        print("PR is claimed by another run, skipping")
        continue

    try:
        # Do PR mutation work
        # Start heartbeat thread
        registry.heartbeat(pr_key, run_id)
    finally:
        registry.release(pr_key, run_id)

Dry-run mode:
    All write operations are no-ops when dry_run=True. Zero filesystem writes.
"""

from __future__ import annotations

import json
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAIMS_DIR = Path.home() / ".claude" / "pr-queue" / "claims"
INSTANCE_ID_PATH = Path.home() / ".claude" / "instance_id"

HEARTBEAT_STALE_MINUTES = 30
CLAIMED_AT_STALE_HOURS = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_instance_id() -> str:
    """Return the stable instance UUID, creating it if it doesn't exist."""
    if INSTANCE_ID_PATH.exists():
        return INSTANCE_ID_PATH.read_text().strip()
    instance_id = str(uuid.uuid4())
    INSTANCE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically
    tmp = INSTANCE_ID_PATH.with_suffix(".tmp")
    tmp.write_text(instance_id)
    tmp.rename(INSTANCE_ID_PATH)
    return instance_id


def get_hostname() -> str:
    """Return the current machine hostname."""
    return socket.gethostname()


def canonical_pr_key(org: str, repo: str, number: int | str) -> str:
    """Build canonical PR key: '<lowercase-org>/<lowercase-repo>#<number>'.

    Args:
        org: GitHub org name (e.g. "OmniNode-ai")
        repo: GitHub repo name (e.g. "omniclaude")
        number: PR number (int or str)

    Returns:
        Canonical key, e.g. "omninode-ai/omniclaude#247"
    """
    return f"{org.lower()}/{repo.lower()}#{number}"


def filesystem_key(pr_key: str) -> str:
    """Convert canonical PR key to a safe filesystem filename.

    Replaces '/' and '#' with '--'.

    Args:
        pr_key: Canonical PR key (e.g. "omninode-ai/omniclaude#247")

    Returns:
        Filesystem-safe name without extension (e.g. "omninode-ai--omniclaude--247")
    """
    return pr_key.replace("/", "--").replace("#", "--")


def _claim_path(pr_key: str) -> Path:
    """Return the Path for the claim file for the given PR key."""
    return CLAIMS_DIR / f"{filesystem_key(pr_key)}.json"


def _now_utc() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(ts: str) -> datetime:
    """Parse ISO 8601 UTC string (with or without Z) to aware datetime."""
    ts = ts.rstrip("Z")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _minutes_since(ts: str) -> float:
    """Return minutes elapsed since the given ISO 8601 UTC timestamp."""
    then = _parse_utc(ts)
    now = datetime.now(UTC)
    return (now - then).total_seconds() / 60.0


def _hours_since(ts: str) -> float:
    """Return hours elapsed since the given ISO 8601 UTC timestamp."""
    return _minutes_since(ts) / 60.0


# ---------------------------------------------------------------------------
# Expiry check
# ---------------------------------------------------------------------------


def is_active(claim_data: dict) -> bool:  # type: ignore[type-arg]
    """Return True if the claim is still active (not expired).

    Expiry requires BOTH conditions:
    - last_heartbeat_at > HEARTBEAT_STALE_MINUTES (30m) stale
    - claimed_at > CLAIMED_AT_STALE_HOURS (2h) ago

    If either condition is not met, the claim is active.
    """
    heartbeat_ts = claim_data.get("last_heartbeat_at", claim_data.get("claimed_at", ""))
    claimed_ts = claim_data.get("claimed_at", "")

    if not heartbeat_ts or not claimed_ts:
        # Malformed claim — treat as expired (safe to proceed)
        return False

    heartbeat_stale = _minutes_since(heartbeat_ts) > HEARTBEAT_STALE_MINUTES
    claimed_old = _hours_since(claimed_ts) > CLAIMED_AT_STALE_HOURS

    # Active if EITHER condition is NOT met (both must hold for expiry)
    return not (heartbeat_stale and claimed_old)


# ---------------------------------------------------------------------------
# ClaimRegistry
# ---------------------------------------------------------------------------


class ClaimRegistry:
    """Global claim registry for PR mutation mutual exclusion.

    All public methods accept a ``dry_run`` parameter. When dry_run=True,
    no filesystem writes occur (zero I/O to ~/.claude/).
    """

    def __init__(self, claims_dir: Path | None = None) -> None:
        self._claims_dir = claims_dir or CLAIMS_DIR
        self._instance_id: str | None = None
        self._hostname: str | None = None

    def _ensure_dir(self) -> None:
        """Create the claims directory if it doesn't exist."""
        self._claims_dir.mkdir(parents=True, exist_ok=True)

    def _instance(self) -> str:
        if self._instance_id is None:
            self._instance_id = get_instance_id()
        return self._instance_id

    def _host(self) -> str:
        if self._hostname is None:
            self._hostname = get_hostname()
        return self._hostname

    def _claim_path(self, pr_key: str) -> Path:
        return self._claims_dir / f"{filesystem_key(pr_key)}.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(
        self,
        pr_key: str,
        run_id: str,
        action: str,
        dry_run: bool = False,
    ) -> bool:
        """Attempt to acquire a claim on the given PR.

        Uses atomic write (write to .tmp, then rename) to prevent races.

        Args:
            pr_key: Canonical PR key (e.g. "omninode-ai/omniclaude#247")
            run_id: Current run ID (e.g. "20260223-143012-a3f")
            action: Action description (e.g. "fix_ci", "rebase", "merge")
            dry_run: If True, no filesystem writes. Returns True (as-if acquired).

        Returns:
            True if claim was acquired (or dry_run), False if claimed by another active run.

        Raises:
            ValueError: If claimed_by_host or claimed_by_instance_id cannot be resolved.
        """
        host = self._host()
        instance_id = self._instance()

        if not host:
            raise ValueError("claimed_by_host is required but could not be resolved")
        if not instance_id:
            raise ValueError(
                "claimed_by_instance_id is required but could not be resolved"
            )

        if dry_run:
            return True

        self._ensure_dir()
        claim_file = self._claim_path(pr_key)

        # Check for existing claim
        if claim_file.exists():
            try:
                existing = json.loads(claim_file.read_text())
                if is_active(existing):
                    existing_run = existing.get("claimed_by_run", "unknown")
                    if existing_run == run_id:
                        # We already own this claim — re-acquire (idempotent)
                        return True
                    print(
                        f"[claim-registry] PR {pr_key} is actively claimed by run "
                        f"{existing_run} (action: {existing.get('action', 'unknown')}). "
                        f"Skipping.",
                        flush=True,
                    )
                    return False
                else:
                    # Expired claim — log and proceed to overwrite
                    print(
                        f"[claim-registry] Expired claim for {pr_key} "
                        f"(run: {existing.get('claimed_by_run', 'unknown')}, "
                        f"heartbeat: {existing.get('last_heartbeat_at', 'unknown')}). "
                        f"Proceeding to claim.",
                        flush=True,
                    )
            except (json.JSONDecodeError, OSError) as e:
                # Malformed or unreadable claim — treat as expired
                print(
                    f"[claim-registry] Warning: could not read existing claim for "
                    f"{pr_key}: {e}. Proceeding to overwrite.",
                    flush=True,
                )

        # Write claim atomically
        now = _now_utc()
        claim_data = {
            "pr_key": pr_key,
            "claimed_by_run": run_id,
            "claimed_by_host": host,
            "claimed_by_instance_id": instance_id,
            "claimed_at": now,
            "last_heartbeat_at": now,
            "action": action,
        }

        tmp_path = claim_file.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(claim_data, indent=2))
            tmp_path.rename(claim_file)
        except OSError as e:
            print(
                f"[claim-registry] Warning: could not write claim for {pr_key}: {e}",
                flush=True,
            )
            return False

        return True

    def release(
        self,
        pr_key: str,
        run_id: str,
        dry_run: bool = False,
    ) -> None:
        """Release a claim held by this run.

        Safe to call even if the claim doesn't exist or was already released.
        Intended for use in finally blocks.

        Args:
            pr_key: Canonical PR key
            run_id: The run ID that holds the claim
            dry_run: If True, no filesystem writes.
        """
        if dry_run:
            return

        claim_file = self._claim_path(pr_key)
        if not claim_file.exists():
            return

        try:
            existing = json.loads(claim_file.read_text())
            if existing.get("claimed_by_run") != run_id:
                # Someone else's claim — do NOT delete
                return
            claim_file.unlink(missing_ok=True)
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"[claim-registry] Warning: could not release claim for {pr_key}: {e}. "
                f"Heartbeat expiry will clean it up.",
                flush=True,
            )

    def heartbeat(
        self,
        pr_key: str,
        run_id: str,
        dry_run: bool = False,
    ) -> None:
        """Update last_heartbeat_at on the claim file (atomic rename).

        Call every 5 minutes while the PR mutation is in progress.

        Args:
            pr_key: Canonical PR key
            run_id: The run ID that holds the claim
            dry_run: If True, no filesystem writes.
        """
        if dry_run:
            return

        claim_file = self._claim_path(pr_key)
        if not claim_file.exists():
            return

        try:
            existing = json.loads(claim_file.read_text())
            if existing.get("claimed_by_run") != run_id:
                # Not our claim — do not heartbeat it
                return
            existing["last_heartbeat_at"] = _now_utc()
            tmp_path = claim_file.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(existing, indent=2))
            tmp_path.rename(claim_file)
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"[claim-registry] Warning: heartbeat failed for {pr_key}: {e}",
                flush=True,
            )

    def cleanup_stale_own_claims(
        self,
        run_id: str,
        dry_run: bool = False,
    ) -> list[str]:
        """Delete all expired claim files owned by this run_id.

        Called at startup resume: if this run's claims are stale (e.g. from a
        prior interrupted execution), clean them up before doing any work.

        Args:
            run_id: The run ID whose stale claims to delete
            dry_run: If True, returns list of would-be-deleted files without deleting.

        Returns:
            List of pr_key strings whose claim files were (or would be) deleted.
        """
        if not self._claims_dir.exists():
            return []

        deleted: list[str] = []

        for claim_file in self._claims_dir.glob("*.json"):
            try:
                claim_data = json.loads(claim_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            if claim_data.get("claimed_by_run") != run_id:
                continue

            if is_active(claim_data):
                # Active claim from this run — do not clean up (may be in use)
                continue

            pr_key = claim_data.get("pr_key", claim_file.stem)
            deleted.append(pr_key)

            if not dry_run:
                try:
                    claim_file.unlink(missing_ok=True)
                    print(
                        f"[claim-registry] Cleaned up stale claim for {pr_key} "
                        f"(run: {run_id})",
                        flush=True,
                    )
                except OSError as e:
                    print(
                        f"[claim-registry] Warning: could not clean up stale claim "
                        f"for {pr_key}: {e}",
                        flush=True,
                    )

        return deleted

    def list_active_claims(self) -> list[dict]:  # type: ignore[type-arg]
        """Return all currently active claim files (for diagnostics).

        Returns:
            List of claim data dicts for claims where is_active() is True.
        """
        if not self._claims_dir.exists():
            return []

        active: list[dict] = []  # type: ignore[type-arg]
        for claim_file in self._claims_dir.glob("*.json"):
            try:
                claim_data = json.loads(claim_file.read_text())
                if is_active(claim_data):
                    active.append(claim_data)
            except (json.JSONDecodeError, OSError):
                continue

        return active

    def has_active_claim(self, pr_key: str) -> bool:
        """Check if there is an active claim on the given PR.

        Args:
            pr_key: Canonical PR key

        Returns:
            True if the PR has an active (non-expired) claim from any run.
        """
        claim_file = self._claim_path(pr_key)
        if not claim_file.exists():
            return False

        try:
            claim_data = json.loads(claim_file.read_text())
            return is_active(claim_data)
        except (json.JSONDecodeError, OSError):
            return False

    def get_claim(self, pr_key: str) -> dict | None:  # type: ignore[type-arg]
        """Return the claim data for a PR if the claim file exists and is readable.

        Args:
            pr_key: Canonical PR key

        Returns:
            Claim data dict, or None if no claim file exists or it is unreadable.
        """
        claim_file = self._claim_path(pr_key)
        if not claim_file.exists():
            return None
        try:
            return json.loads(claim_file.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: ClaimRegistry | None = None


def get_registry() -> ClaimRegistry:
    """Return the module-level singleton ClaimRegistry instance."""
    global _registry
    if _registry is None:
        _registry = ClaimRegistry()
    return _registry


# ---------------------------------------------------------------------------
# CLI for diagnostics
# ---------------------------------------------------------------------------


def _cli_main() -> None:
    """Simple CLI for diagnostics: list active claims."""
    import sys

    registry = ClaimRegistry()

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        active = registry.list_active_claims()
        if not active:
            print("No active claims.")
        else:
            print(f"{len(active)} active claim(s):")
            for claim in active:
                print(
                    f"  {claim['pr_key']}"
                    f" | run: {claim['claimed_by_run']}"
                    f" | host: {claim['claimed_by_host']}"
                    f" | action: {claim['action']}"
                    f" | heartbeat: {claim['last_heartbeat_at']}"
                )
    elif len(sys.argv) > 2 and sys.argv[1] == "release":
        pr_key = sys.argv[2]
        run_id = sys.argv[3] if len(sys.argv) > 3 else ""
        registry.release(pr_key, run_id)
        print(f"Released claim for {pr_key}")
    else:
        print("Usage: pr_claim_registry.py list")
        print("       pr_claim_registry.py release <pr_key> [<run_id>]")


if __name__ == "__main__":
    _cli_main()
