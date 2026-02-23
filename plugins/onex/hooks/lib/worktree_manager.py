#!/usr/bin/env python3
"""WorktreeManager - Programmatic Python API for git worktree operations.

Thin wrapper around ``subprocess.run(["git", "worktree", ...])``.  All
shell-level worktree logic that previously required shelling out unsafely is
encapsulated here so callers can write testable, type-safe code.

The class mirrors the four operations performed by the session-end.sh worktree
cleanup:

* ``create``  — ``git worktree add``
* ``delete``  — ``git worktree remove`` + optional ``git worktree prune``
* ``list``    — ``git worktree list --porcelain``
* ``get``     — list + filter by branch

Usage::

    from worktree_manager import WorktreeManager, Worktree

    mgr = WorktreeManager(repo_path="/path/to/repo")
    wt  = mgr.create(branch="feat/foo", path="/tmp/wt-foo")
    all_wts = mgr.list()
    wt2 = mgr.get(branch="feat/foo")
    mgr.delete(path="/tmp/wt-foo")

Related Tickets:
    - OMN-2379: WorktreeManager Python class (this module)

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Worktree:
    """Represents a single git worktree entry.

    Attributes:
        path: Absolute path to the worktree directory.
        branch: Checked-out branch name (e.g. ``refs/heads/feat/foo``), or an
            empty string when the worktree is in detached-HEAD state.
        head: The SHA-1 of HEAD in this worktree.
        is_main: ``True`` when this is the main / bare worktree (the one that
            owns ``.git``).
    """

    path: str
    branch: str
    head: str
    is_main: bool = False

    @property
    def branch_short(self) -> str:
        """Return branch name without the ``refs/heads/`` prefix."""
        prefix = "refs/heads/"
        if self.branch.startswith(prefix):
            return self.branch[len(prefix) :]
        return self.branch


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class WorktreeError(RuntimeError):
    """Raised when a git worktree command fails."""


def _run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a ``git`` sub-command and return the completed process.

    Args:
        args: Arguments to pass after ``git`` (e.g. ``["worktree", "list"]``).
        cwd: Working directory; defaults to the current directory.
        timeout: Maximum seconds to wait for the subprocess.

    Returns:
        The ``CompletedProcess`` object.

    Raises:
        WorktreeError: If the subprocess cannot be started (git not found).
    """
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise WorktreeError("git executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(f"git {' '.join(args)} timed out after {timeout}s") from exc


def _parse_worktree_list(output: str) -> list[Worktree]:
    """Parse ``git worktree list --porcelain`` output into :class:`Worktree` objects.

    The porcelain format groups records separated by blank lines::

        worktree /path/to/main
        HEAD abc1234
        branch refs/heads/main

        worktree /path/to/other
        HEAD def5678
        branch refs/heads/feat/foo

    A ``bare`` line indicates a bare worktree; a ``detached`` line indicates
    detached HEAD (no branch line will follow).

    Args:
        output: Raw stdout from ``git worktree list --porcelain``.

    Returns:
        List of :class:`Worktree` instances in the order returned by git.
    """
    worktrees: list[Worktree] = []
    current: dict[str, str] = {}
    is_first = True  # git always lists the main worktree first

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            # Blank line — flush the current record
            if "worktree" in current:
                worktrees.append(
                    Worktree(
                        path=current.get("worktree", ""),
                        branch=current.get("branch", ""),
                        head=current.get("HEAD", ""),
                        is_main=is_first,
                    )
                )
                is_first = False
                current = {}
            continue

        if line == "bare" or line == "detached":
            # Markers with no value — just record the presence
            current[line] = "true"
            continue

        if " " in line:
            key, _, value = line.partition(" ")
            current[key] = value
        else:
            # Unexpected format — skip gracefully
            logger.debug("Unexpected porcelain line: %r", line)

    # Flush the last record (no trailing blank line in older git versions)
    if "worktree" in current:
        worktrees.append(
            Worktree(
                path=current.get("worktree", ""),
                branch=current.get("branch", ""),
                head=current.get("HEAD", ""),
                is_main=is_first,
            )
        )

    return worktrees


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class WorktreeManager:
    """Manage git worktrees via subprocess.

    Args:
        repo_path: Path to the main repository (the one that owns ``.git``).
            Defaults to the current working directory when ``None``.
    """

    def __init__(self, repo_path: str | None = None) -> None:
        self._repo_path: str | None = (
            str(Path(repo_path).resolve()) if repo_path is not None else None
        )

    # ------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------

    def create(self, branch: str, path: str) -> Worktree:
        """Create a new worktree and check out *branch* in it.

        Equivalent to::

            git worktree add <path> <branch>

        If *branch* does not exist locally the command will fail and
        :class:`WorktreeError` will be raised.  To create a new branch at the
        same time pass a ``-b`` prefix via a different helper or run git
        directly — this method is intentionally minimal.

        Args:
            branch: The branch name to check out (must already exist locally).
            path: Absolute or relative path where the new worktree will be
                created.

        Returns:
            A :class:`Worktree` representing the newly-created worktree.

        Raises:
            WorktreeError: If ``git worktree add`` returns a non-zero exit code.
        """
        result = _run_git(
            ["worktree", "add", path, branch],
            cwd=self._repo_path,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise WorktreeError(
                f"git worktree add failed (exit {result.returncode}): {stderr}"
            )

        # Retrieve the newly-created worktree so callers get a typed object
        worktree = self.get(branch=branch)
        if worktree is None:
            # Fallback: construct a minimal object from what we know
            worktree = Worktree(
                path=str(Path(path).resolve()),
                branch=f"refs/heads/{branch}"
                if not branch.startswith("refs/")
                else branch,
                head="",
            )
        return worktree

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------

    def delete(self, path: str, prune: bool = True) -> None:
        """Remove the worktree at *path*.

        Equivalent to::

            git worktree remove <path>
            git worktree prune          # only when prune=True (default)

        The removal is NOT forced — git will refuse to remove a worktree that
        has uncommitted changes (matching the behaviour of session-end.sh which
        guards against dirty worktrees before calling ``git worktree remove``).

        Args:
            path: Path to the worktree directory to remove.
            prune: When ``True`` (default) also runs ``git worktree prune``
                to clean up administrative files for worktrees whose directories
                have already been deleted.

        Raises:
            WorktreeError: If ``git worktree remove`` returns a non-zero exit
                code (e.g. worktree has uncommitted changes or path not found).
        """
        result = _run_git(
            ["worktree", "remove", path],
            cwd=self._repo_path,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise WorktreeError(
                f"git worktree remove failed (exit {result.returncode}): {stderr}"
            )

        if prune:
            prune_result = _run_git(
                ["worktree", "prune"],
                cwd=self._repo_path,
            )
            if prune_result.returncode != 0:
                # Non-fatal — log and continue
                logger.warning(
                    "git worktree prune failed (exit %d): %s",
                    prune_result.returncode,
                    prune_result.stderr.strip(),
                )

    # ------------------------------------------------------------------
    # list
    # ------------------------------------------------------------------

    def list(self) -> list[Worktree]:
        """List all worktrees registered with this repository.

        Equivalent to::

            git worktree list --porcelain

        Returns:
            List of :class:`Worktree` instances, main worktree first.

        Raises:
            WorktreeError: If the git command itself fails (e.g. not a git
                repo, or git not found).
        """
        result = _run_git(
            ["worktree", "list", "--porcelain"],
            cwd=self._repo_path,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise WorktreeError(
                f"git worktree list failed (exit {result.returncode}): {stderr}"
            )

        return _parse_worktree_list(result.stdout)

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------

    def get(self, branch: str) -> Worktree | None:
        """Return the worktree checked out on *branch*, or ``None``.

        Compares *branch* against both the full ``refs/heads/<branch>`` form
        and the short form so callers can pass either.

        Args:
            branch: Branch name to look up (with or without ``refs/heads/``
                prefix).

        Returns:
            The matching :class:`Worktree`, or ``None`` if not found.
        """
        candidates = self.list()
        short = (
            branch[len("refs/heads/") :] if branch.startswith("refs/heads/") else branch
        )
        full = f"refs/heads/{short}"

        for wt in candidates:
            if wt.branch in (short, full):
                return wt
        return None


__all__ = ["Worktree", "WorktreeError", "WorktreeManager"]
