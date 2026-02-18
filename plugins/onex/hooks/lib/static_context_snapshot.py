#!/usr/bin/env python3
"""Static Context Snapshot Service.

Tracks changes to static context files between Claude Code sessions.
Supports two categories of files:

  - **Versioned files** (repo CLAUDE.md): Change detection via git diff.
  - **Non-versioned files** (~/.claude/CLAUDE.md, memory files, .local.md):
      Change detection via SHA-256 content hash comparison. Content snapshots
      are stored only when the hash differs from the previous session.

On detected changes, emits ``static.context.edit.detected`` events via the
emit daemon.

Storage Layout::

    ~/.claude/snapshots/
        static_context.json    # Index: {file_path: {hash, session_id, path}}

Design Decisions:
  - Fail-open: any file I/O or git error is logged and skipped.
  - Hooks must never block; this module exits 0 on all infrastructure failures.
  - Snapshot directory is ``~/.claude/snapshots/`` (persistent, not /tmp/).
  - Content stored only when hash changes to minimise storage.
  - Git diff uses ``--stat`` (summary only) to avoid capturing secrets.

CLI Usage::

    python static_context_snapshot.py scan \\
        --session-id <uuid> \\
        --project-path /path/to/project

Related Tickets:
  - OMN-2237: E1-T8 Static context snapshot service

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Default snapshot directory (persistent across reboots, not /tmp/)
DEFAULT_SNAPSHOT_DIR = Path.home() / ".claude" / "snapshots"
SNAPSHOT_INDEX_FILE = "static_context.json"

# Default non-versioned paths to scan (expanded at runtime)
# These are files not tracked by git that need hash-based snapshotting.
_DEFAULT_NON_VERSIONED_PATHS: list[str] = [
    "~/.claude/CLAUDE.md",
    "~/.claude/settings.json",
]

# Glob patterns within a project root that identify non-versioned local files.
_LOCAL_GLOB_PATTERNS: list[str] = [
    "**/.local.md",
    "**/CLAUDE.local.md",
]

# CLAUDE.md names that are considered versioned (in git repos)
_VERSIONED_FILENAMES: frozenset[str] = frozenset(
    [
        "CLAUDE.md",
    ]
)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class FileSnapshot:
    """Snapshot record for a single static context file.

    Attributes:
        file_path: Absolute path to the file.
        content_hash: SHA-256 hex digest of the file content.
        session_id: Session ID when this snapshot was captured.
        is_versioned: Whether the file is tracked by git.
        git_diff_stat: Brief ``git diff --stat`` output for versioned files, if changed.
        changed: Whether this file changed compared to the previous snapshot.
    """

    file_path: str
    content_hash: str
    session_id: str
    is_versioned: bool
    git_diff_stat: str | None = None
    changed: bool = False


@dataclass
class SnapshotResult:
    """Result from a full snapshot scan.

    Attributes:
        session_id: The session this scan ran for.
        files_scanned: Total number of files scanned.
        files_changed: Number of files with detected changes.
        changed_files: List of changed FileSnapshot records.
        event_emitted: Whether a change detection event was emitted.
    """

    session_id: str
    files_scanned: int
    files_changed: int
    changed_files: list[FileSnapshot]
    event_emitted: bool = False


# =============================================================================
# Snapshot Storage
# =============================================================================


def _load_snapshot_index(snapshot_dir: Path) -> dict[str, Any]:
    """Load the snapshot index from disk.

    Returns an empty dict if the file does not exist or is malformed.

    Args:
        snapshot_dir: Directory containing the snapshot index.

    Returns:
        Parsed snapshot index dictionary.
    """
    index_path = snapshot_dir / SNAPSHOT_INDEX_FILE
    if not index_path.exists():
        return {}
    try:
        return cast(
            "dict[str, Any]", json.loads(index_path.read_text(encoding="utf-8"))
        )
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Failed to load snapshot index: %s", exc)
        return {}


def _save_snapshot_index(snapshot_dir: Path, index: dict[str, Any]) -> bool:
    """Persist the snapshot index to disk atomically.

    Args:
        snapshot_dir: Directory for the snapshot index.
        index: The updated index to write.

    Returns:
        True on success, False on failure.
    """
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        index_path = snapshot_dir / SNAPSHOT_INDEX_FILE
        tmp_path = index_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        tmp_path.replace(index_path)
        return True
    except OSError as exc:
        logger.debug("Failed to save snapshot index: %s", exc)
        return False


# =============================================================================
# Hash Computation
# =============================================================================


def _sha256_file(path: Path) -> str | None:
    """Compute the SHA-256 hex digest of a file's content.

    Args:
        path: Path to the file.

    Returns:
        Hex digest string, or None if the file cannot be read.
    """
    try:
        hasher = hashlib.sha256()
        hasher.update(path.read_bytes())
        return hasher.hexdigest()
    except OSError as exc:
        logger.debug("Cannot hash file %s: %s", path, exc)
        return None


# =============================================================================
# Git Utilities
# =============================================================================


def _is_git_tracked(file_path: Path) -> bool:
    """Return True if the file is tracked in a git repository.

    Args:
        file_path: Path to the file to check.

    Returns:
        True if git tracks the file, False otherwise.
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "ls-files", "--error-unmatch", str(file_path)],
            capture_output=True,
            check=False,
            cwd=str(file_path.parent),
            timeout=2,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False


def _git_diff_stat(file_path: Path, since_commit: str | None = None) -> str | None:
    """Get a brief git diff summary for a file.

    Uses ``--stat`` to produce a summary line without exposing file content.
    If ``since_commit`` is not provided, diffs against HEAD.

    Args:
        file_path: The file to diff.
        since_commit: Optional commit SHA to diff from.

    Returns:
        Single-line summary string, or None on error / no changes.
    """
    try:
        base = since_commit or "HEAD"
        result = subprocess.run(  # noqa: S603
            ["git", "diff", "--stat", base, "--", str(file_path)],
            capture_output=True,
            check=False,
            text=True,
            cwd=str(file_path.parent),
            timeout=3,
        )
        output = result.stdout.strip()
        if result.returncode == 0 and output:
            # Return only the summary line (last non-empty line), stripped
            lines = [line.strip() for line in output.splitlines() if line.strip()]
            return lines[-1] if lines else None
        return None
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return None


def _git_commit_for_file(file_path: Path) -> str | None:
    """Get the latest git commit SHA that touched a file.

    Args:
        file_path: Path to the file.

    Returns:
        Short commit SHA string, or None on error.
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "log", "--oneline", "-1", "--", str(file_path)],
            capture_output=True,
            check=False,
            text=True,
            cwd=str(file_path.parent),
            timeout=3,
        )
        output = result.stdout.strip()
        if result.returncode == 0 and output:
            # First token is the short commit SHA
            return output.split()[0]
        return None
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return None


# =============================================================================
# File Discovery
# =============================================================================


def _collect_versioned_files(project_path: Path) -> list[Path]:
    """Collect versioned CLAUDE.md files within a project directory.

    Looks for CLAUDE.md files in the project root and immediate subdirectories
    that are tracked by git.

    Args:
        project_path: Root of the project to scan.

    Returns:
        List of absolute paths to versioned markdown files.
    """
    candidates: list[Path] = []
    if not project_path.is_dir():
        return candidates

    # Project-root CLAUDE.md
    root_claude = project_path / "CLAUDE.md"
    if root_claude.exists():
        candidates.append(root_claude)

    # Immediate subdirectory CLAUDE.md files (e.g., package sub-repos)
    try:
        for child in project_path.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                sub_claude = child / "CLAUDE.md"
                if sub_claude.exists():
                    candidates.append(sub_claude)
    except OSError as exc:
        logger.debug("Cannot list project directory %s: %s", project_path, exc)

    # Filter to git-tracked files only
    return [p for p in candidates if _is_git_tracked(p)]


def _collect_non_versioned_files(project_path: Path | None = None) -> list[Path]:
    """Collect non-versioned static context files.

    Scans global Claude config files (~/.claude/) and project-local .local.md
    files that are NOT tracked by git.

    Args:
        project_path: Optional project root for local glob patterns.

    Returns:
        List of existing, non-versioned file paths.
    """
    paths: list[Path] = []

    # Global non-versioned files
    for raw_path in _DEFAULT_NON_VERSIONED_PATHS:
        expanded = Path(os.path.expanduser(raw_path))
        if expanded.exists() and not _is_git_tracked(expanded):
            paths.append(expanded)

    # Memory files: ~/.claude/memory/*.md
    memory_dir = Path.home() / ".claude" / "memory"
    if memory_dir.is_dir():
        try:
            for mem_file in memory_dir.glob("*.md"):
                if mem_file.is_file() and not _is_git_tracked(mem_file):
                    paths.append(mem_file)
        except OSError as exc:
            logger.debug("Cannot scan memory dir %s: %s", memory_dir, exc)

    # Project-local .local.md files
    if project_path and project_path.is_dir():
        for pattern in _LOCAL_GLOB_PATTERNS:
            try:
                for local_file in project_path.glob(pattern):
                    if local_file.is_file() and not _is_git_tracked(local_file):
                        paths.append(local_file)
            except OSError as exc:
                logger.debug("Cannot glob %s in %s: %s", pattern, project_path, exc)

    return paths


# =============================================================================
# Change Detection
# =============================================================================


def _detect_versioned_change(
    file_path: Path,
    index: dict[str, Any],
    session_id: str,
) -> FileSnapshot:
    """Detect changes to a git-versioned file.

    Compares the current file's git commit against the stored commit to detect
    changes. Falls back to hash comparison if git is unavailable.

    Args:
        file_path: Absolute path to the versioned file.
        index: Current snapshot index loaded from disk.
        session_id: Current session ID.

    Returns:
        FileSnapshot with ``changed`` set appropriately.
    """
    key = str(file_path)
    previous = index.get(key, {})

    current_hash = _sha256_file(file_path)
    if current_hash is None:
        # Cannot read the file; treat as unchanged to be safe
        return FileSnapshot(
            file_path=key,
            content_hash="",
            session_id=session_id,
            is_versioned=True,
            changed=False,
        )

    previous_hash = previous.get("hash")
    changed = current_hash != previous_hash

    diff_stat: str | None = None
    if changed and previous_hash:
        # Attempt git diff between current HEAD and last-seen commit
        previous_commit = previous.get("git_commit")
        diff_stat = _git_diff_stat(file_path, since_commit=previous_commit)

    current_commit = _git_commit_for_file(file_path)

    return FileSnapshot(
        file_path=key,
        content_hash=current_hash,
        session_id=session_id,
        is_versioned=True,
        git_diff_stat=diff_stat,
        changed=changed,
    )


def _detect_non_versioned_change(
    file_path: Path,
    index: dict[str, Any],
    session_id: str,
) -> FileSnapshot:
    """Detect changes to a non-versioned file via SHA-256 hash comparison.

    Args:
        file_path: Absolute path to the non-versioned file.
        index: Current snapshot index loaded from disk.
        session_id: Current session ID.

    Returns:
        FileSnapshot with ``changed`` set appropriately.
    """
    key = str(file_path)
    previous = index.get(key, {})

    current_hash = _sha256_file(file_path)
    if current_hash is None:
        return FileSnapshot(
            file_path=key,
            content_hash="",
            session_id=session_id,
            is_versioned=False,
            changed=False,
        )

    previous_hash = previous.get("hash")
    changed = current_hash != previous_hash

    return FileSnapshot(
        file_path=key,
        content_hash=current_hash,
        session_id=session_id,
        is_versioned=False,
        changed=changed,
    )


# =============================================================================
# Index Update
# =============================================================================


def _update_index_entry(
    index: dict[str, Any],
    snapshot: FileSnapshot,
) -> None:
    """Update the snapshot index entry for a file.

    Only stores full content for non-versioned files when the hash has changed,
    to minimise storage. For versioned files we rely on git for content history.

    Args:
        index: Mutable snapshot index to update in place.
        snapshot: The new snapshot to record.
    """
    entry: dict[str, Any] = {
        "hash": snapshot.content_hash,
        "session_id": snapshot.session_id,
        "is_versioned": snapshot.is_versioned,
    }

    if not snapshot.is_versioned and snapshot.changed and snapshot.content_hash:
        # Store content snapshot for non-versioned files when they change.
        try:
            content = Path(snapshot.file_path).read_text(encoding="utf-8")
            entry["content_snapshot"] = content
        except OSError as exc:
            logger.debug(
                "Cannot read content for snapshot of %s: %s",
                snapshot.file_path,
                exc,
            )

    if snapshot.is_versioned:
        current_commit = _git_commit_for_file(Path(snapshot.file_path))
        if current_commit:
            entry["git_commit"] = current_commit

    index[snapshot.file_path] = entry


# =============================================================================
# Event Emission
# =============================================================================


def _emit_change_event(
    changed_files: list[FileSnapshot],
    session_id: str,
) -> bool:
    """Emit a static.context.edit.detected event via the emit daemon.

    Tries to import ``emit_client_wrapper`` from the hooks lib. Falls back
    gracefully if the module is unavailable (e.g., running standalone).

    Args:
        changed_files: List of FileSnapshot records that changed.
        session_id: Current session ID.

    Returns:
        True if the event was successfully queued, False otherwise.
    """
    if not changed_files:
        return False

    payload: dict[str, object] = {
        "session_id": session_id,
        "changed_file_count": len(changed_files),
        "changed_files": [
            {
                "file_path": s.file_path,
                "is_versioned": s.is_versioned,
                "git_diff_stat": s.git_diff_stat,
            }
            for s in changed_files
        ],
    }

    try:
        # Attempt to import from the hooks lib (present in deployed environment)
        from emit_client_wrapper import emit_event  # type: ignore[import-not-found]

        return bool(emit_event("static.context.edit.detected", payload))
    except ImportError:
        # In tests or standalone usage, import from the package path
        try:
            import importlib.util as ilu
            import os

            hooks_lib = os.environ.get("HOOKS_LIB_PATH", "")
            if hooks_lib:
                spec = ilu.spec_from_file_location(
                    "emit_client_wrapper",
                    os.path.join(hooks_lib, "emit_client_wrapper.py"),
                )
                if spec and spec.loader:
                    mod = ilu.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    return bool(mod.emit_event("static.context.edit.detected", payload))
        except Exception as exc:
            logger.debug("emit_client_wrapper not available: %s", exc)
        return False
    except Exception as exc:
        logger.debug("Event emission failed: %s", exc)
        return False


# =============================================================================
# Public API
# =============================================================================


def scan_and_snapshot(
    session_id: str,
    project_path: str | None = None,
    snapshot_dir: Path | None = None,
    emit: bool = True,
) -> SnapshotResult:
    """Scan static context files, detect changes, update snapshots.

    This is the primary entry point called by the SessionStart hook.
    All errors are caught and logged; the function always returns a
    SnapshotResult and never raises.

    Args:
        session_id: The current session ID.
        project_path: Optional project root directory. Used to discover
            versioned CLAUDE.md files and project-local .local.md files.
        snapshot_dir: Override for the snapshot storage directory.
            Defaults to ~/.claude/snapshots/.
        emit: Whether to emit a Kafka event when changes are detected.
            Set to False in tests.

    Returns:
        SnapshotResult describing what was scanned and what changed.
    """
    if snapshot_dir is None:
        snapshot_dir = DEFAULT_SNAPSHOT_DIR

    project = Path(project_path).resolve() if project_path else None

    # Load existing index (fail-open: return empty dict on any error)
    try:
        index = _load_snapshot_index(snapshot_dir)
    except Exception as exc:
        logger.debug("Failed to load snapshot index, starting fresh: %s", exc)
        index = {}

    # Collect files to scan
    versioned: list[Path] = []
    non_versioned: list[Path] = []

    if project:
        try:
            versioned = _collect_versioned_files(project)
        except Exception as exc:
            logger.debug("Error collecting versioned files: %s", exc)

    try:
        non_versioned = _collect_non_versioned_files(project)
    except Exception as exc:
        logger.debug("Error collecting non-versioned files: %s", exc)

    # Detect changes
    snapshots: list[FileSnapshot] = []

    for file_path in versioned:
        try:
            snap = _detect_versioned_change(file_path, index, session_id)
            snapshots.append(snap)
        except Exception as exc:
            logger.debug("Error detecting versioned change for %s: %s", file_path, exc)

    for file_path in non_versioned:
        try:
            snap = _detect_non_versioned_change(file_path, index, session_id)
            snapshots.append(snap)
        except Exception as exc:
            logger.debug(
                "Error detecting non-versioned change for %s: %s", file_path, exc
            )

    changed = [s for s in snapshots if s.changed]

    # Update index for all scanned files
    for snap in snapshots:
        if snap.content_hash:  # Only update index for successfully hashed files
            _update_index_entry(index, snap)

    # Persist updated index
    _save_snapshot_index(snapshot_dir, index)

    # Emit event if changes detected
    event_emitted = False
    if emit and changed:
        event_emitted = _emit_change_event(changed, session_id)

    return SnapshotResult(
        session_id=session_id,
        files_scanned=len(snapshots),
        files_changed=len(changed),
        changed_files=changed,
        event_emitted=event_emitted,
    )


# =============================================================================
# CLI Entry Point
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the static context snapshot service.

    Outputs JSON to stdout for shell script consumption.

    Returns:
        0 on success, 1 on unrecoverable error.
    """
    parser = argparse.ArgumentParser(
        description="Static context snapshot service for OmniClaude hooks.",
        prog="static_context_snapshot",
    )
    parser.add_argument(
        "command",
        choices=["scan"],
        help="Command to execute.",
    )
    parser.add_argument(
        "--session-id",
        required=True,
        help="Current session ID.",
    )
    parser.add_argument(
        "--project-path",
        default=None,
        help="Project root directory (optional).",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        help="Snapshot storage directory override.",
    )
    parser.add_argument(
        "--no-emit",
        action="store_true",
        help="Suppress event emission (for testing).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    snapshot_dir = Path(args.snapshot_dir) if args.snapshot_dir else None

    try:
        result = scan_and_snapshot(
            session_id=args.session_id,
            project_path=args.project_path,
            snapshot_dir=snapshot_dir,
            emit=not args.no_emit,
        )
    except Exception as exc:
        # Fail-open: never block the hook
        logger.error("scan_and_snapshot failed: %s", exc)
        print(
            json.dumps(
                {
                    "session_id": args.session_id,
                    "files_scanned": 0,
                    "files_changed": 0,
                    "changed_files": [],
                    "event_emitted": False,
                    "error": str(exc),
                }
            )
        )
        return 0

    # Serialize and output
    output = {
        "session_id": result.session_id,
        "files_scanned": result.files_scanned,
        "files_changed": result.files_changed,
        "changed_files": [
            {
                "file_path": s.file_path,
                "content_hash": s.content_hash,
                "is_versioned": s.is_versioned,
                "git_diff_stat": s.git_diff_stat,
                "changed": s.changed,
            }
            for s in result.changed_files
        ],
        "event_emitted": result.event_emitted,
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "FileSnapshot",
    "SnapshotResult",
    "scan_and_snapshot",
    "DEFAULT_SNAPSHOT_DIR",
    "SNAPSHOT_INDEX_FILE",
]
