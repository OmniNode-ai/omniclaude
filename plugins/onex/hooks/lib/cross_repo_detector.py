#!/usr/bin/env python3
"""Cross-Repo Change Detector - Detects changes spanning multiple repository roots.

Used by the ticket-pipeline to enforce the stop_on_cross_repo policy switch.
Blocks the pipeline if changes touch files outside the current repo root,
preventing accidental cross-repo commits.

Detection Strategy:
    1. Resolve the current repo root via `git rev-parse --show-toplevel`
    2. Collect all changed/untracked files (committed, staged, and untracked)
    3. Resolve each file path with realpath to handle symlinks
    4. Flag any file that resolves outside the repo root

Usage:
    from cross_repo_detector import detect_cross_repo_changes

    result = detect_cross_repo_changes()
    if result["violation"]:
        print(f"Cross-repo change: {result['violating_file']}")

Related Tickets:
    - OMN-1970: Cross-repo detection for ticket-pipeline
    - OMN-1967: Pipeline created with placeholder cross-repo check

.. versionadded:: 0.2.2
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrossRepoResult:
    """Result of cross-repo change detection.

    Attributes:
        violation: True if changes were detected outside the repo root.
        violating_files: List of file paths that resolve outside the repo root.
        repo_root: The resolved repository root path.
        files_checked: Total number of files checked.
        error: Error message if detection itself failed (not a violation).
    """

    violation: bool = False
    violating_files: list[str] = field(default_factory=list)
    repo_root: str = ""
    files_checked: int = 0
    error: str | None = None

    @property
    def violating_file(self) -> str | None:
        """First violating file, for backward-compatible single-file access."""
        return self.violating_files[0] if self.violating_files else None


def _run_git(args: list[str], cwd: str | None = None) -> tuple[str, int]:
    """Run a git command and return (stdout, returncode).

    Args:
        args: Git command arguments (without 'git' prefix).
        cwd: Working directory for git command.

    Returns:
        Tuple of (stdout_text, return_code).
    """
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
            check=False,
        )
        return result.stdout.strip(), result.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"Git command failed: git {' '.join(args)}: {e}")
        return "", 1


def detect_cross_repo_changes(
    cwd: str | None = None,
    base_ref: str = "origin/main",
) -> CrossRepoResult:
    """Detect if any changed/untracked files resolve outside the current repo root.

    Checks three categories of files:
    1. Committed changes vs base_ref (git diff --name-only base_ref...HEAD)
    2. Uncommitted changes (git diff --name-only HEAD)
    3. Untracked files (git ls-files --others --exclude-standard)

    All file paths are resolved with realpath to handle symlinks.

    Args:
        cwd: Working directory (defaults to current directory).
        base_ref: Base reference for committed changes (default: origin/main).

    Returns:
        CrossRepoResult with violation status and details.
    """
    work_dir = cwd or os.getcwd()

    # Get repo root
    repo_root, rc = _run_git(["rev-parse", "--show-toplevel"], cwd=work_dir)
    if rc != 0 or not repo_root:
        return CrossRepoResult(
            error="Not a git repository or git not available",
        )

    # Resolve repo root with realpath (handles symlinks)
    try:
        repo_root_resolved = str(Path(repo_root).resolve())
    except (OSError, ValueError) as e:
        return CrossRepoResult(error=f"Failed to resolve repo root: {e}")

    # Collect all changed files from three sources
    all_files: set[str] = set()

    # 1. Committed changes vs base_ref
    committed_out, rc = _run_git(
        ["diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=work_dir,
    )
    if rc == 0 and committed_out:
        all_files.update(committed_out.splitlines())

    # 2. Uncommitted changes (staged + unstaged vs HEAD)
    uncommitted_out, rc = _run_git(
        ["diff", "--name-only", "HEAD"],
        cwd=work_dir,
    )
    if rc == 0 and uncommitted_out:
        all_files.update(uncommitted_out.splitlines())

    # 3. Untracked files
    untracked_out, rc = _run_git(
        ["ls-files", "--others", "--exclude-standard"],
        cwd=work_dir,
    )
    if rc == 0 and untracked_out:
        all_files.update(untracked_out.splitlines())

    # Check each file's resolved path
    violating: list[str] = []
    for rel_path in sorted(all_files):
        if not rel_path:
            continue
        abs_path = Path(repo_root_resolved) / rel_path
        try:
            resolved = str(abs_path.resolve())
        except (OSError, ValueError):
            # If we can't resolve, skip (don't block on filesystem errors)
            continue

        if (
            not resolved.startswith(repo_root_resolved + os.sep)
            and resolved != repo_root_resolved
        ):
            violating.append(rel_path)
            logger.info(
                f"Cross-repo violation: {rel_path} resolves to {resolved} "
                f"(outside {repo_root_resolved})"
            )

    return CrossRepoResult(
        violation=len(violating) > 0,
        violating_files=violating,
        repo_root=repo_root_resolved,
        files_checked=len(all_files),
    )


# CLI entry point for shell script usage
if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Detect cross-repo changes")
    parser.add_argument("--base-ref", default="origin/main", help="Base reference")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = detect_cross_repo_changes(base_ref=args.base_ref)

    if args.json:
        print(
            json.dumps(
                {
                    "violation": result.violation,
                    "violating_files": result.violating_files,
                    "repo_root": result.repo_root,
                    "files_checked": result.files_checked,
                    "error": result.error,
                }
            )
        )
    else:
        if result.error:
            print(f"Error: {result.error}", file=sys.stderr)
            sys.exit(2)
        elif result.violation:
            print(f"CROSS_REPO_VIOLATION: {result.violating_files}")
            sys.exit(1)
        else:
            print(
                f"OK: {result.files_checked} files checked, all within {result.repo_root}"
            )
            sys.exit(0)


__all__ = ["CrossRepoResult", "detect_cross_repo_changes"]
