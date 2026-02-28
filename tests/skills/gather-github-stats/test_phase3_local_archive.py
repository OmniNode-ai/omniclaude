# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for gather_stats.py Phase 3 — local archive discovery and deduplication.

Tests cover:
- normalize_url(): SSH <-> HTTPS round-trips, .git suffix stripping, case folding
- extract_best_remote(): priority selection, non-GitHub detection
- _is_bare_clone(): bare vs regular repo detection
- discover_git_repos(): recursion, depth limiting, SKIP_DIRS exclusion, bare detection
- parse_numstat(): binary line skipping, normal lines, empty input
- get_local_repo_stats(): commit count, dates (via subprocess mocks)
- scan_local_archive(): deduplication against seen_remotes, non-GitHub surfacing
- main() / _generate_local_only_report(): integration via --local-only flag

Related: OMN-2870
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: add the skill directory to sys.path so we can import gather_stats
# ---------------------------------------------------------------------------

SKILL_DIR = (
    Path(__file__).parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "gather-github-stats"
)
sys.path.insert(0, str(SKILL_DIR))

import gather_stats  # noqa: E402

# ===========================================================================
# normalize_url tests
# ===========================================================================


class TestNormalizeUrl:
    @pytest.mark.unit
    def test_https_passthrough(self) -> None:
        url = "https://github.com/OmniNode-ai/omniclaude"
        assert (
            gather_stats.normalize_url(url)
            == "https://github.com/omninode-ai/omniclaude"
        )

    @pytest.mark.unit
    def test_strip_git_suffix(self) -> None:
        url = "https://github.com/OmniNode-ai/omniclaude.git"
        assert (
            gather_stats.normalize_url(url)
            == "https://github.com/omninode-ai/omniclaude"
        )

    @pytest.mark.unit
    def test_ssh_to_https_colon(self) -> None:
        """git@github.com:owner/repo -> https://github.com/owner/repo"""
        url = "git@github.com:OmniNode-ai/omniclaude.git"
        result = gather_stats.normalize_url(url)
        assert result == "https://github.com/omninode-ai/omniclaude"

    @pytest.mark.unit
    def test_ssh_to_https_slash(self) -> None:
        """git@github.com/owner/repo (slash variant) is normalised."""
        url = "git@github.com/OmniNode-ai/omniclaude"
        result = gather_stats.normalize_url(url)
        assert result == "https://github.com/omninode-ai/omniclaude"

    @pytest.mark.unit
    def test_round_trip_ssh_https(self) -> None:
        """SSH and HTTPS forms of the same repo normalise to the same string."""
        ssh = "git@github.com:OmniNode-ai/omnibase_core.git"
        https = "https://github.com/OmniNode-ai/omnibase_core.git"
        assert gather_stats.normalize_url(ssh) == gather_stats.normalize_url(https)

    @pytest.mark.unit
    def test_lowercase_applied(self) -> None:
        url = "https://GitHub.COM/MyOrg/MyRepo"
        assert gather_stats.normalize_url(url) == "https://github.com/myorg/myrepo"

    @pytest.mark.unit
    def test_non_github_url_lowercased(self) -> None:
        url = "https://gitlab.com/MyOrg/MyRepo.git"
        assert gather_stats.normalize_url(url) == "https://gitlab.com/myorg/myrepo"

    @pytest.mark.unit
    def test_whitespace_stripped(self) -> None:
        url = "  https://github.com/OmniNode-ai/omniclaude.git  "
        assert (
            gather_stats.normalize_url(url)
            == "https://github.com/omninode-ai/omniclaude"
        )

    @pytest.mark.unit
    def test_git_suffix_case_insensitive(self) -> None:
        url = "https://github.com/OmniNode-ai/omniclaude.GIT"
        assert (
            gather_stats.normalize_url(url)
            == "https://github.com/omninode-ai/omniclaude"
        )


# ===========================================================================
# extract_best_remote tests
# ===========================================================================


def _make_remote_output(*remotes: tuple[str, str]) -> str:
    """Build a fake `git remote -v` stdout from (name, url) pairs."""
    lines = []
    for name, url in remotes:
        lines.append(f"{name}\t{url} (fetch)")
        lines.append(f"{name}\t{url} (push)")
    return "\n".join(lines)


class TestExtractBestRemote:
    @pytest.mark.unit
    def test_prefers_omninode_ai_remote(self, tmp_path: Path) -> None:
        output = _make_remote_output(
            ("origin", "https://github.com/someuser/omniclaude.git"),
            ("upstream", "https://github.com/OmniNode-ai/omniclaude.git"),
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output, stderr="")
            url, is_non_github = gather_stats.extract_best_remote(tmp_path)
        assert url == "https://github.com/OmniNode-ai/omniclaude.git"
        assert not is_non_github

    @pytest.mark.unit
    def test_falls_back_to_github_remote(self, tmp_path: Path) -> None:
        output = _make_remote_output(
            ("origin", "https://github.com/someuser/omniclaude.git"),
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output, stderr="")
            url, is_non_github = gather_stats.extract_best_remote(tmp_path)
        assert url == "https://github.com/someuser/omniclaude.git"
        assert not is_non_github

    @pytest.mark.unit
    def test_falls_back_to_origin(self, tmp_path: Path) -> None:
        output = _make_remote_output(
            ("origin", "https://bitbucket.org/myorg/repo.git"),
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output, stderr="")
            url, is_non_github = gather_stats.extract_best_remote(tmp_path)
        assert url == "https://bitbucket.org/myorg/repo.git"
        assert is_non_github

    @pytest.mark.unit
    def test_falls_back_to_first_remote_when_no_origin(self, tmp_path: Path) -> None:
        output = _make_remote_output(
            ("upstream", "https://gitlab.com/myorg/repo"),
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output, stderr="")
            url, is_non_github = gather_stats.extract_best_remote(tmp_path)
        assert url == "https://gitlab.com/myorg/repo"
        assert is_non_github

    @pytest.mark.unit
    def test_no_remotes_returns_none(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            url, is_non_github = gather_stats.extract_best_remote(tmp_path)
        assert url is None
        assert not is_non_github

    @pytest.mark.unit
    def test_git_failure_returns_none(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="not a git repo"
            )
            url, is_non_github = gather_stats.extract_best_remote(tmp_path)
        assert url is None
        assert not is_non_github


# ===========================================================================
# _is_bare_clone tests
# ===========================================================================


class TestIsBareClone:
    @pytest.mark.unit
    def test_regular_repo_not_bare(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "HEAD").write_text("ref: refs/heads/main\n")
        (tmp_path / "config").write_text("[core]\n")
        assert not gather_stats._is_bare_clone(tmp_path)

    @pytest.mark.unit
    def test_bare_repo_detected(self, tmp_path: Path) -> None:
        # Bare clone: HEAD + config at root, no .git dir
        (tmp_path / "HEAD").write_text("ref: refs/heads/main\n")
        (tmp_path / "config").write_text("[core]\n\tbare = true\n")
        assert gather_stats._is_bare_clone(tmp_path)

    @pytest.mark.unit
    def test_empty_dir_not_bare(self, tmp_path: Path) -> None:
        assert not gather_stats._is_bare_clone(tmp_path)

    @pytest.mark.unit
    def test_only_head_not_bare(self, tmp_path: Path) -> None:
        (tmp_path / "HEAD").write_text("ref: refs/heads/main\n")
        assert not gather_stats._is_bare_clone(tmp_path)


# ===========================================================================
# discover_git_repos tests
# ===========================================================================


class TestDiscoverGitRepos:
    @pytest.mark.unit
    def test_finds_regular_repo(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / ".git").mkdir()
        result = gather_stats.discover_git_repos(tmp_path, max_depth=3)
        assert repo in result

    @pytest.mark.unit
    def test_finds_bare_clone(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare.git"
        bare.mkdir()
        (bare / "HEAD").write_text("ref: refs/heads/main\n")
        (bare / "config").write_text("[core]\n\tbare = true\n")
        result = gather_stats.discover_git_repos(tmp_path, max_depth=3)
        assert bare in result

    @pytest.mark.unit
    def test_respects_max_depth(self, tmp_path: Path) -> None:
        # Repo at depth 2 (from root) — should be found at max_depth=2
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        (deep / ".git").mkdir()

        found_at_2 = gather_stats.discover_git_repos(tmp_path, max_depth=2)
        assert deep in found_at_2

        # At max_depth=1 the scan should not reach depth 2
        found_at_1 = gather_stats.discover_git_repos(tmp_path, max_depth=1)
        assert deep not in found_at_1

    @pytest.mark.unit
    def test_skips_skip_dirs(self, tmp_path: Path) -> None:
        for skip_dir in ["node_modules", "__pycache__", "venv", ".venv"]:
            skip = tmp_path / skip_dir
            skip.mkdir()
            (skip / ".git").mkdir()

        result = gather_stats.discover_git_repos(tmp_path, max_depth=3)
        # None of the repos inside SKIP_DIRS should appear
        result_names = {p.name for p in result}
        assert not result_names.intersection(gather_stats.SKIP_DIRS)

    @pytest.mark.unit
    def test_does_not_descend_into_repo(self, tmp_path: Path) -> None:
        """discover_git_repos must not recurse into a found repo's subtree."""
        outer = tmp_path / "outer"
        outer.mkdir()
        (outer / ".git").mkdir()
        inner = outer / "submodule"
        inner.mkdir()
        (inner / ".git").mkdir()

        result = gather_stats.discover_git_repos(tmp_path, max_depth=5)
        assert outer in result
        assert inner not in result

    @pytest.mark.unit
    def test_empty_directory(self, tmp_path: Path) -> None:
        result = gather_stats.discover_git_repos(tmp_path, max_depth=3)
        assert result == []


# ===========================================================================
# parse_numstat tests
# ===========================================================================


class TestParseNumstat:
    @pytest.mark.unit
    def test_basic_lines(self) -> None:
        output = "10\t5\tsomefile.py\n20\t3\tanother.py\n"
        add, del_ = gather_stats.parse_numstat(output)
        assert add == 30
        assert del_ == 8

    @pytest.mark.unit
    def test_binary_lines_skipped(self) -> None:
        output = "-\t-\tsome_binary.png\n10\t2\treal_file.py\n"
        add, del_ = gather_stats.parse_numstat(output)
        assert add == 10
        assert del_ == 2

    @pytest.mark.unit
    def test_empty_output(self) -> None:
        add, del_ = gather_stats.parse_numstat("")
        assert add == 0
        assert del_ == 0

    @pytest.mark.unit
    def test_only_binary_lines(self) -> None:
        output = "-\t-\timage.png\n-\t-\tvideo.mp4\n"
        add, del_ = gather_stats.parse_numstat(output)
        assert add == 0
        assert del_ == 0

    @pytest.mark.unit
    def test_blank_lines_ignored(self) -> None:
        output = "\n5\t3\tfile.py\n\n"
        add, del_ = gather_stats.parse_numstat(output)
        assert add == 5
        assert del_ == 3

    @pytest.mark.unit
    def test_mixed_binary_and_text(self) -> None:
        output = (
            "100\t50\tsrc/main.py\n"
            "-\t-\tassets/logo.png\n"
            "200\t100\tsrc/utils.py\n"
            "-\t-\tdocs/diagram.pdf\n"
        )
        add, del_ = gather_stats.parse_numstat(output)
        assert add == 300
        assert del_ == 150

    @pytest.mark.unit
    def test_zero_additions_deletions(self) -> None:
        output = "0\t0\tempty_file.txt\n"
        add, del_ = gather_stats.parse_numstat(output)
        assert add == 0
        assert del_ == 0


# ===========================================================================
# get_local_repo_stats tests
# ===========================================================================


def _make_subprocess_run_mock(
    commit_count: str = "42",
    first_date: str = "2024-01-01 10:00:00 +0000",
    last_date: str = "2024-12-31 23:59:59 +0000",
    numstat_output: str = "",
) -> Any:
    """Return a side_effect function for subprocess.run mocks.

    Matches git subcommand by looking at the flat list of cmd args,
    not a joined string, to avoid path-based false matches.
    """

    def side_effect(cmd: list[str], **kwargs: Any) -> MagicMock:
        mock = MagicMock()
        mock.returncode = 0
        # Identify the git subcommand: skip any leading "git" and "-C <dir>" flags
        subcmd_parts = [a for a in cmd if not a.startswith("-") and a != "git"]
        # Drop path entries (anything that looks like an absolute path)
        subcmd_parts = [a for a in subcmd_parts if not a.startswith("/")]
        if "rev-list" in cmd:
            mock.stdout = commit_count
        elif "log" in cmd and "--reverse" in cmd:
            mock.stdout = first_date
        elif "log" in cmd and "-1" in cmd:
            mock.stdout = last_date
        elif "log" in cmd and "--numstat" in cmd:
            mock.stdout = numstat_output
        else:
            mock.stdout = ""
        return mock

    return side_effect


class TestGetLocalRepoStats:
    @pytest.mark.unit
    def test_commit_count_parsed(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=_make_subprocess_run_mock("99")):
            stats = gather_stats.get_local_repo_stats(tmp_path, include_loc=False)
        assert stats["commit_count"] == 99

    @pytest.mark.unit
    def test_dates_parsed(self, tmp_path: Path) -> None:
        with patch(
            "subprocess.run",
            side_effect=_make_subprocess_run_mock(
                first_date="2024-01-15 08:00:00 +0000",
                last_date="2024-11-30 18:00:00 +0000",
            ),
        ):
            stats = gather_stats.get_local_repo_stats(tmp_path, include_loc=False)
        assert stats["first_commit_date"] == "2024-01-15 08:00:00 +0000"
        assert stats["last_commit_date"] == "2024-11-30 18:00:00 +0000"

    @pytest.mark.unit
    def test_loc_not_collected_when_disabled(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=_make_subprocess_run_mock()):
            stats = gather_stats.get_local_repo_stats(tmp_path, include_loc=False)
        assert stats["loc_additions"] is None
        assert stats["loc_deletions"] is None

    @pytest.mark.unit
    def test_loc_collected_when_enabled(self, tmp_path: Path) -> None:
        numstat = "50\t10\tfile.py\n-\t-\tbinary.bin\n"
        with patch(
            "subprocess.run",
            side_effect=_make_subprocess_run_mock(numstat_output=numstat),
        ):
            stats = gather_stats.get_local_repo_stats(tmp_path, include_loc=True)
        assert stats["loc_additions"] == 50
        assert stats["loc_deletions"] == 10

    @pytest.mark.unit
    def test_loc_timeout_handled_gracefully(self, tmp_path: Path) -> None:
        call_count = 0

        def side_effect(cmd: list[str], **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            joined = " ".join(cmd)
            mock = MagicMock()
            mock.returncode = 0
            if "--numstat" in joined:
                raise subprocess.TimeoutExpired(cmd, 120)
            mock.stdout = "5"
            return mock

        with patch("subprocess.run", side_effect=side_effect):
            stats = gather_stats.get_local_repo_stats(tmp_path, include_loc=True)

        # loc values remain None on timeout — no crash
        assert stats["loc_additions"] is None
        assert stats["loc_deletions"] is None

    @pytest.mark.unit
    def test_git_failure_returns_zero_commit_count(self, tmp_path: Path) -> None:
        def side_effect(cmd: list[str], **kwargs: Any) -> MagicMock:
            mock = MagicMock()
            mock.returncode = 128
            mock.stdout = ""
            return mock

        with patch("subprocess.run", side_effect=side_effect):
            stats = gather_stats.get_local_repo_stats(tmp_path, include_loc=False)
        assert stats["commit_count"] == 0


# ===========================================================================
# scan_local_archive deduplication tests
# ===========================================================================


class TestScanLocalArchiveDeduplication:
    @pytest.mark.unit
    def test_github_repos_deduplicated(self, tmp_path: Path) -> None:
        """A local repo whose normalised URL is in seen_remotes is a duplicate."""
        repo_path = tmp_path / "omniclaude"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()

        seen_remotes = {
            gather_stats.normalize_url("https://github.com/OmniNode-ai/omniclaude.git")
        }

        def mock_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            mock = MagicMock()
            mock.returncode = 0
            if "remote" in cmd:
                mock.stdout = (
                    "origin\thttps://github.com/OmniNode-ai/omniclaude.git (fetch)\n"
                    "origin\thttps://github.com/OmniNode-ai/omniclaude.git (push)\n"
                )
            elif "rev-list" in cmd:
                mock.stdout = "100"
            else:
                mock.stdout = "2024-01-01 00:00:00 +0000"
            return mock

        with patch("subprocess.run", side_effect=mock_run):
            result = gather_stats.scan_local_archive(
                local_path=tmp_path,
                max_depth=2,
                include_loc=False,
                seen_remotes=seen_remotes,
            )

        assert result.duplicate_count == 1
        assert len(result.repos) == 1
        assert result.repos[0].is_duplicate
        # Duplicate must NOT count towards total_local_commits
        assert result.total_local_commits == 0

    @pytest.mark.unit
    def test_unique_local_repo_counted(self, tmp_path: Path) -> None:
        """A local repo not in seen_remotes is unique and counted in totals."""
        repo_path = tmp_path / "local_only_tool"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()

        seen_remotes: set[str] = set()

        def mock_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            mock = MagicMock()
            mock.returncode = 0
            if "remote" in cmd:
                mock.stdout = ""  # No remotes
            elif "rev-list" in cmd:
                mock.stdout = "77"
            else:
                mock.stdout = "2024-06-01 00:00:00 +0000"
            return mock

        with patch("subprocess.run", side_effect=mock_run):
            result = gather_stats.scan_local_archive(
                local_path=tmp_path,
                max_depth=2,
                include_loc=False,
                seen_remotes=seen_remotes,
            )

        assert result.duplicate_count == 0
        assert len(result.repos) == 1
        assert not result.repos[0].is_duplicate
        assert result.total_local_commits == 77

    @pytest.mark.unit
    def test_non_github_remote_surfaced(self, tmp_path: Path) -> None:
        """A repo with a non-GitHub remote is flagged and included in totals."""
        repo_path = tmp_path / "gitlab_project"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()

        seen_remotes: set[str] = set()

        def mock_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            mock = MagicMock()
            mock.returncode = 0
            if "remote" in cmd:
                mock.stdout = (
                    "origin\thttps://gitlab.com/myorg/myrepo (fetch)\n"
                    "origin\thttps://gitlab.com/myorg/myrepo (push)\n"
                )
            elif "rev-list" in cmd:
                mock.stdout = "30"
            else:
                mock.stdout = "2024-03-01 00:00:00 +0000"
            return mock

        with patch("subprocess.run", side_effect=mock_run):
            result = gather_stats.scan_local_archive(
                local_path=tmp_path,
                max_depth=2,
                include_loc=False,
                seen_remotes=seen_remotes,
            )

        assert result.non_github_count == 1
        assert result.repos[0].non_github_remote
        assert not result.repos[0].is_duplicate
        assert result.total_local_commits == 30

    @pytest.mark.unit
    def test_multiple_repos_mixed_deduplication(self, tmp_path: Path) -> None:
        """Mix of duplicate and unique repos — counts are correct."""
        for name in ["repo_a", "repo_b", "repo_c"]:
            p = tmp_path / name
            p.mkdir()
            (p / ".git").mkdir()

        seen_remotes = {
            gather_stats.normalize_url("https://github.com/OmniNode-ai/repo_a.git")
        }

        remote_map = {
            "repo_a": "https://github.com/OmniNode-ai/repo_a.git",
            "repo_b": "https://github.com/OmniNode-ai/repo_b.git",
            "repo_c": "",  # no remote
        }

        def mock_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            mock = MagicMock()
            mock.returncode = 0
            if "remote" in cmd:
                # identify which repo path is being queried from the -C argument
                c_idx = cmd.index("-C") if "-C" in cmd else -1
                repo_path_arg = (
                    cmd[c_idx + 1] if c_idx >= 0 and c_idx + 1 < len(cmd) else ""
                )
                for name, url in remote_map.items():
                    if name in repo_path_arg:
                        if url:
                            mock.stdout = (
                                f"origin\t{url} (fetch)\norigin\t{url} (push)\n"
                            )
                        else:
                            mock.stdout = ""
                        return mock
                mock.stdout = ""
            elif "rev-list" in cmd:
                mock.stdout = "10"
            else:
                mock.stdout = "2024-01-01 00:00:00 +0000"
            return mock

        with patch("subprocess.run", side_effect=mock_run):
            result = gather_stats.scan_local_archive(
                local_path=tmp_path,
                max_depth=2,
                include_loc=False,
                seen_remotes=seen_remotes,
            )

        assert len(result.repos) == 3
        assert result.duplicate_count == 1
        # Two unique repos * 10 commits each
        assert result.total_local_commits == 20


# ===========================================================================
# generate_report (local section) tests
# ===========================================================================


class TestGenerateReportLocalSection:
    @pytest.mark.unit
    def test_local_section_absent_when_github_only(self, tmp_path: Path) -> None:
        """When local_result=None the Local Archive section must not appear."""
        report = gather_stats.generate_report(
            org="TestOrg",
            repos=[],
            cache_dir=tmp_path,
            bypass_ttl=False,
            local_result=None,
        )
        assert "## Local Archive" not in report

    @pytest.mark.unit
    def test_local_section_present_when_local_result_provided(
        self, tmp_path: Path
    ) -> None:
        from gather_stats import LocalRepoStats, LocalScanResult

        r = LocalRepoStats(
            path=Path("/some/repo"),
            is_bare=False,
            commit_count=42,
            first_commit_date="2024-01-01",
            last_commit_date="2024-12-31",
            remote_url="https://github.com/OmniNode-ai/omniclaude",
            normalized_url="https://github.com/omninode-ai/omniclaude",
            is_duplicate=False,
            loc_additions=None,
            loc_deletions=None,
            non_github_remote=False,
        )
        local_result = LocalScanResult(
            repos=[r],
            duplicate_count=0,
            non_github_count=0,
            total_local_commits=42,
        )
        report = gather_stats.generate_report(
            org="TestOrg",
            repos=[],
            cache_dir=tmp_path,
            bypass_ttl=False,
            local_result=local_result,
        )
        assert "## Local Archive" in report
        assert "/some/repo" in report

    @pytest.mark.unit
    def test_deduplication_report_present_when_duplicates_exist(
        self, tmp_path: Path
    ) -> None:
        from gather_stats import LocalRepoStats, LocalScanResult

        dup = LocalRepoStats(
            path=Path("/dup/repo"),
            is_bare=False,
            commit_count=10,
            first_commit_date=None,
            last_commit_date=None,
            remote_url="https://github.com/OmniNode-ai/omniclaude",
            normalized_url="https://github.com/omninode-ai/omniclaude",
            is_duplicate=True,
            loc_additions=None,
            loc_deletions=None,
            non_github_remote=False,
        )
        local_result = LocalScanResult(
            repos=[dup],
            duplicate_count=1,
            non_github_count=0,
            total_local_commits=0,
        )
        report = gather_stats.generate_report(
            org="TestOrg",
            repos=[],
            cache_dir=tmp_path,
            bypass_ttl=False,
            local_result=local_result,
        )
        assert "Deduplication Report" in report
        assert "/dup/repo" in report


# ===========================================================================
# _generate_local_only_report tests
# ===========================================================================


class TestGenerateLocalOnlyReport:
    @pytest.mark.unit
    def test_empty_result(self) -> None:
        from gather_stats import LocalScanResult

        result = LocalScanResult()
        report = gather_stats._generate_local_only_report("TestOrg", result)
        assert "No local git repositories found" in report

    @pytest.mark.unit
    def test_none_result(self) -> None:
        report = gather_stats._generate_local_only_report("TestOrg", None)
        assert "No local git repositories found" in report

    @pytest.mark.unit
    def test_report_contains_repo_paths(self) -> None:
        from gather_stats import LocalRepoStats, LocalScanResult

        r = LocalRepoStats(
            path=Path("/my/local/project"),
            is_bare=True,
            commit_count=5,
            first_commit_date="2023-01-01",
            last_commit_date="2023-12-31",
            remote_url=None,
            normalized_url=None,
            is_duplicate=False,
            loc_additions=None,
            loc_deletions=None,
            non_github_remote=False,
        )
        result = LocalScanResult(repos=[r], total_local_commits=5)
        report = gather_stats._generate_local_only_report("TestOrg", result)
        assert "/my/local/project" in report
        assert "## 2. Archived/Local Repos Summary" in report

    @pytest.mark.unit
    def test_report_header_contains_org(self) -> None:
        from gather_stats import LocalScanResult

        result = LocalScanResult()
        report = gather_stats._generate_local_only_report("MySpecialOrg", result)
        assert "MySpecialOrg" in report
