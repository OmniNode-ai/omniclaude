"""Tests for worktree_manager module.

All subprocess calls are mocked — no real git operations occur.
Tests cover the four public methods (create, delete, list, get) plus the
internal parser and error paths.

Related Tickets:
    - OMN-2379: WorktreeManager Python class
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the hooks lib is importable without an installed package
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
    ),
)

from worktree_manager import (
    Worktree,
    WorktreeError,
    WorktreeManager,
    _parse_worktree_list,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PORCELAIN_TWO = """\
worktree /repo
HEAD aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111
branch refs/heads/main

worktree /tmp/wt-feat
HEAD bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222
branch refs/heads/feat/my-feature

"""

PORCELAIN_DETACHED = """\
worktree /repo
HEAD aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111
branch refs/heads/main

worktree /tmp/wt-detached
HEAD cccc3333cccc3333cccc3333cccc3333cccc3333
detached

"""


def _make_process(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    """Return a mock CompletedProcess."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


# ---------------------------------------------------------------------------
# Worktree dataclass
# ---------------------------------------------------------------------------


class TestWorktree:
    def test_branch_short_strips_prefix(self) -> None:
        wt = Worktree(path="/repo", branch="refs/heads/feat/foo", head="abc")
        assert wt.branch_short == "feat/foo"

    def test_branch_short_no_prefix(self) -> None:
        wt = Worktree(path="/repo", branch="main", head="abc")
        assert wt.branch_short == "main"

    def test_branch_short_empty(self) -> None:
        wt = Worktree(path="/repo", branch="", head="abc")
        assert wt.branch_short == ""

    def test_is_main_defaults_false(self) -> None:
        wt = Worktree(path="/repo", branch="refs/heads/main", head="abc")
        assert not wt.is_main

    def test_frozen(self) -> None:
        wt = Worktree(path="/repo", branch="refs/heads/main", head="abc")
        with pytest.raises(Exception):
            wt.path = "/other"  # noqa: E501 (FrozenInstanceError raised at runtime; mypy sees no type error)


# ---------------------------------------------------------------------------
# _parse_worktree_list
# ---------------------------------------------------------------------------


class TestParseWorktreeList:
    def test_two_worktrees(self) -> None:
        result = _parse_worktree_list(PORCELAIN_TWO)
        assert len(result) == 2

        main = result[0]
        assert main.path == "/repo"
        assert main.branch == "refs/heads/main"
        assert main.head == "aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111"
        assert main.is_main is True

        feat = result[1]
        assert feat.path == "/tmp/wt-feat"
        assert feat.branch == "refs/heads/feat/my-feature"
        assert feat.is_main is False

    def test_detached_head(self) -> None:
        result = _parse_worktree_list(PORCELAIN_DETACHED)
        assert len(result) == 2
        detached = result[1]
        assert detached.branch == ""

    def test_empty_output(self) -> None:
        result = _parse_worktree_list("")
        assert result == []

    def test_single_worktree_no_trailing_newline(self) -> None:
        single = "worktree /repo\nHEAD abc123\nbranch refs/heads/main"
        result = _parse_worktree_list(single)
        assert len(result) == 1
        assert result[0].path == "/repo"
        assert result[0].is_main is True


# ---------------------------------------------------------------------------
# WorktreeManager.list
# ---------------------------------------------------------------------------


class TestWorktreeManagerList:
    @patch("worktree_manager.subprocess.run")
    def test_list_returns_parsed_worktrees(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process(stdout=PORCELAIN_TWO)

        mgr = WorktreeManager(repo_path="/repo")
        result = mgr.list()

        assert len(result) == 2
        mock_run.assert_called_once_with(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd="/repo",
            timeout=30,
            check=False,
        )

    @patch("worktree_manager.subprocess.run")
    def test_list_raises_on_nonzero(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process(returncode=128, stderr="not a git repo")

        mgr = WorktreeManager()
        with pytest.raises(WorktreeError, match="git worktree list failed"):
            mgr.list()

    @patch("worktree_manager.subprocess.run")
    def test_list_no_repo_path_passes_none_cwd(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process(stdout=PORCELAIN_TWO)
        mgr = WorktreeManager()
        mgr.list()
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] is None


# ---------------------------------------------------------------------------
# WorktreeManager.get
# ---------------------------------------------------------------------------


class TestWorktreeManagerGet:
    @patch("worktree_manager.subprocess.run")
    def test_get_returns_matching_worktree(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process(stdout=PORCELAIN_TWO)

        mgr = WorktreeManager(repo_path="/repo")
        wt = mgr.get(branch="feat/my-feature")

        assert wt is not None
        assert wt.path == "/tmp/wt-feat"

    @patch("worktree_manager.subprocess.run")
    def test_get_with_full_ref_prefix(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process(stdout=PORCELAIN_TWO)

        mgr = WorktreeManager(repo_path="/repo")
        wt = mgr.get(branch="refs/heads/feat/my-feature")

        assert wt is not None
        assert wt.branch_short == "feat/my-feature"

    @patch("worktree_manager.subprocess.run")
    def test_get_returns_none_when_not_found(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process(stdout=PORCELAIN_TWO)

        mgr = WorktreeManager(repo_path="/repo")
        result = mgr.get(branch="nonexistent")

        assert result is None


# ---------------------------------------------------------------------------
# WorktreeManager.delete
# ---------------------------------------------------------------------------


class TestWorktreeManagerDelete:
    @patch("worktree_manager.subprocess.run")
    def test_delete_calls_remove_and_prune(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process()

        mgr = WorktreeManager(repo_path="/repo")
        mgr.delete(path="/tmp/wt-feat")

        assert mock_run.call_count == 2
        first_call_args = mock_run.call_args_list[0][0][0]
        assert first_call_args == ["git", "worktree", "remove", "/tmp/wt-feat"]
        second_call_args = mock_run.call_args_list[1][0][0]
        assert second_call_args == ["git", "worktree", "prune"]

    @patch("worktree_manager.subprocess.run")
    def test_delete_without_prune(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process()

        mgr = WorktreeManager(repo_path="/repo")
        mgr.delete(path="/tmp/wt-feat", prune=False)

        assert mock_run.call_count == 1
        call_args = mock_run.call_args_list[0][0][0]
        assert "prune" not in call_args

    @patch("worktree_manager.subprocess.run")
    def test_delete_raises_on_nonzero_remove(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process(returncode=1, stderr="has changes")

        mgr = WorktreeManager(repo_path="/repo")
        with pytest.raises(WorktreeError, match="git worktree remove failed"):
            mgr.delete(path="/tmp/wt-feat")

    @patch("worktree_manager.subprocess.run")
    def test_delete_prune_failure_is_nonfatal(self, mock_run: MagicMock) -> None:
        # remove succeeds, prune fails — should NOT raise
        mock_run.side_effect = [
            _make_process(returncode=0),  # worktree remove
            _make_process(returncode=1, stderr="prune error"),  # worktree prune
        ]

        mgr = WorktreeManager(repo_path="/repo")
        # Should not raise
        mgr.delete(path="/tmp/wt-feat")


# ---------------------------------------------------------------------------
# WorktreeManager.create
# ---------------------------------------------------------------------------


class TestWorktreeManagerCreate:
    @patch("worktree_manager.subprocess.run")
    def test_create_calls_add_then_get(self, mock_run: MagicMock) -> None:
        # First call: worktree add; second call: worktree list (via get)
        mock_run.side_effect = [
            _make_process(returncode=0),  # worktree add
            _make_process(stdout=PORCELAIN_TWO),  # worktree list (via get)
        ]

        mgr = WorktreeManager(repo_path="/repo")
        wt = mgr.create(branch="feat/my-feature", path="/tmp/wt-feat")

        assert wt.path == "/tmp/wt-feat"
        first_args = mock_run.call_args_list[0][0][0]
        assert first_args == [
            "git",
            "worktree",
            "add",
            "/tmp/wt-feat",
            "feat/my-feature",
        ]

    @patch("worktree_manager.subprocess.run")
    def test_create_raises_on_nonzero_add(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_process(returncode=128, stderr="already exists")

        mgr = WorktreeManager(repo_path="/repo")
        with pytest.raises(WorktreeError, match="git worktree add failed"):
            mgr.create(branch="feat/my-feature", path="/tmp/wt-feat")

    @patch("worktree_manager.subprocess.run")
    def test_create_fallback_when_get_returns_none(self, mock_run: MagicMock) -> None:
        # add succeeds but the branch is not in the list output (edge case)
        porcelain_main_only = (
            "worktree /repo\n"
            "HEAD aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111\n"
            "branch refs/heads/main\n"
        )
        mock_run.side_effect = [
            _make_process(returncode=0),  # worktree add
            _make_process(stdout=porcelain_main_only),  # worktree list
        ]

        mgr = WorktreeManager(repo_path="/repo")
        wt = mgr.create(branch="feat/new", path="/tmp/wt-new")

        # Fallback Worktree constructed from the path argument
        assert "feat/new" in wt.branch


# ---------------------------------------------------------------------------
# Git-not-found error propagation
# ---------------------------------------------------------------------------


class TestGitNotFound:
    @patch("worktree_manager.subprocess.run", side_effect=FileNotFoundError)
    def test_list_raises_worktree_error_when_git_missing(
        self, _mock_run: MagicMock
    ) -> None:
        mgr = WorktreeManager()
        with pytest.raises(WorktreeError, match="git executable not found"):
            mgr.list()

    @patch("worktree_manager.subprocess.run", side_effect=FileNotFoundError)
    def test_create_raises_worktree_error_when_git_missing(
        self, _mock_run: MagicMock
    ) -> None:
        mgr = WorktreeManager()
        with pytest.raises(WorktreeError, match="git executable not found"):
            mgr.create(branch="feat/foo", path="/tmp/wt")

    @patch(
        "worktree_manager.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
    )
    def test_list_raises_worktree_error_on_timeout(self, _mock_run: MagicMock) -> None:
        mgr = WorktreeManager()
        with pytest.raises(WorktreeError, match="timed out"):
            mgr.list()
