"""Tests for cross_repo_detector module.

Tests the cross-repo change detection logic used by ticket-pipeline's
stop_on_cross_repo policy switch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

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

from cross_repo_detector import CrossRepoResult, detect_cross_repo_changes


class TestCrossRepoResult:
    """Test the CrossRepoResult dataclass."""

    def test_no_violation(self) -> None:
        result = CrossRepoResult(
            violation=False,
            repo_root="/repo",
            files_checked=5,
        )
        assert not result.violation
        assert result.violating_file is None
        assert result.violating_files == []

    def test_with_violation(self) -> None:
        result = CrossRepoResult(
            violation=True,
            violating_files=["../other_repo/file.py", "../other_repo/other.py"],
            repo_root="/repo",
            files_checked=10,
        )
        assert result.violation
        assert result.violating_file == "../other_repo/file.py"
        assert len(result.violating_files) == 2

    def test_with_error(self) -> None:
        result = CrossRepoResult(error="Not a git repository")
        assert not result.violation
        assert result.error == "Not a git repository"

    def test_frozen(self) -> None:
        result = CrossRepoResult(violation=False)
        with pytest.raises(AttributeError):
            result.violation = True  # type: ignore[misc]


class TestDetectCrossRepoChanges:
    """Test detect_cross_repo_changes function."""

    def _mock_run(
        self,
        responses: dict[str, tuple[str, int]],
    ):
        """Create a mock for subprocess.run that responds based on git args."""

        def side_effect(cmd, **kwargs):
            # Try progressively shorter keys from the git args
            for k in [
                " ".join(cmd[1:]),
                " ".join(cmd[1:3]),
                cmd[1] if len(cmd) > 1 else "",
            ]:
                if k in responses:
                    stdout, rc = responses[k]
                    return subprocess.CompletedProcess(
                        cmd, rc, stdout=stdout, stderr=""
                    )

            # Default: empty success
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        return side_effect

    @patch("cross_repo_detector.subprocess.run")
    def test_no_changes(self, mock_run) -> None:
        """No changed files -> no violation."""
        mock_run.side_effect = self._mock_run(
            {
                "rev-parse --show-toplevel": ("/repo", 0),
                "diff --name-only origin/main...HEAD": ("", 0),
                "diff --name-only HEAD": ("", 0),
                "ls-files --others --exclude-standard": ("", 0),
            }
        )

        result = detect_cross_repo_changes(cwd="/repo")
        assert not result.violation
        assert result.files_checked == 0

    @patch("cross_repo_detector.subprocess.run")
    def test_all_files_in_repo(self, mock_run) -> None:
        """All changed files within repo root -> no violation.

        Uses a real tmp directory to avoid Path.resolve() mocking issues.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = str(Path(tmp).resolve())

            mock_run.side_effect = self._mock_run(
                {
                    "rev-parse --show-toplevel": (repo_root, 0),
                    "diff --name-only origin/main...HEAD": (
                        "src/main.py\nsrc/utils.py",
                        0,
                    ),
                    "diff --name-only HEAD": ("", 0),
                    "ls-files --others --exclude-standard": ("tests/new_test.py", 0),
                }
            )

            result = detect_cross_repo_changes(cwd=repo_root)

        assert not result.violation
        assert result.files_checked == 3

    @patch("cross_repo_detector.subprocess.run")
    def test_not_a_git_repo(self, mock_run) -> None:
        """Not a git repo -> error result."""
        mock_run.side_effect = self._mock_run({"rev-parse --show-toplevel": ("", 128)})

        result = detect_cross_repo_changes(cwd="/not-a-repo")
        assert not result.violation
        assert result.error is not None
        assert "git" in result.error.lower()

    @patch("cross_repo_detector.subprocess.run")
    def test_deduplicates_files(self, mock_run) -> None:
        """Same file in multiple sources -> counted once."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = str(Path(tmp).resolve())

            mock_run.side_effect = self._mock_run(
                {
                    "rev-parse --show-toplevel": (repo_root, 0),
                    "diff --name-only origin/main...HEAD": ("src/main.py", 0),
                    "diff --name-only HEAD": ("src/main.py", 0),  # Same file
                    "ls-files --others --exclude-standard": ("", 0),
                }
            )

            result = detect_cross_repo_changes(cwd=repo_root)

        assert result.files_checked == 1  # Deduplicated

    @patch("cross_repo_detector.subprocess.run")
    def test_custom_base_ref(self, mock_run) -> None:
        """Custom base ref passed to git diff."""
        calls: list[list[str]] = []

        def capture_calls(cmd, **kwargs):
            calls.append(cmd)
            if "rev-parse" in cmd and "--show-toplevel" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="/repo", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        mock_run.side_effect = capture_calls

        detect_cross_repo_changes(cwd="/repo", base_ref="origin/develop")

        # Verify the base ref was used
        diff_calls = [
            c for c in calls if "diff" in c and "origin/develop" in " ".join(c)
        ]
        assert len(diff_calls) == 1

    @patch("cross_repo_detector.subprocess.run")
    def test_absolute_path_from_git(self, mock_run) -> None:
        """Absolute path from git diff output is flagged as a violation.

        If git returns an absolute path (e.g., from submodules or worktrees),
        Path.__truediv__ would silently discard the repo root. The guard
        must catch this and flag it as a violation.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = str(Path(tmp).resolve())

            mock_run.side_effect = self._mock_run(
                {
                    "rev-parse --show-toplevel": (repo_root, 0),
                    "diff --name-only origin/main...HEAD": (
                        "/etc/passwd\nsrc/safe.py",
                        0,
                    ),
                    "diff --name-only HEAD": ("", 0),
                    "ls-files --others --exclude-standard": ("", 0),
                }
            )

            result = detect_cross_repo_changes(cwd=repo_root)

        assert result.violation
        assert "/etc/passwd" in result.violating_files
        assert result.files_checked == 2

    def test_base_ref_flag_injection_rejected(self) -> None:
        """base_ref starting with '-' is rejected to prevent git flag injection.

        While subprocess.run with a list prevents shell injection, git itself
        interprets arguments starting with '--' as flags (e.g., '--output=/tmp/evil').
        """
        result = detect_cross_repo_changes(cwd="/repo", base_ref="--output=/tmp/evil")

        assert result.error is not None
        assert "Invalid base_ref" in result.error
        assert "--output=/tmp/evil" in result.error
        assert not result.violation

    @patch("cross_repo_detector.subprocess.run")
    def test_git_timeout_handling(self, mock_run) -> None:
        """subprocess.TimeoutExpired is handled gracefully.

        When git times out, _run_git returns ('', 1). If this happens on
        rev-parse, detect_cross_repo_changes returns an error result.
        """
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["git", "rev-parse", "--show-toplevel"], timeout=30
        )

        result = detect_cross_repo_changes(cwd="/repo")

        assert not result.violation
        assert result.error is not None
        assert "git" in result.error.lower()
