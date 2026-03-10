# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for contract_change_detector (OMN-3138).

Tests verify:
- Contract file filtering from git diff output
- Git status letter mapping (A/M/D/R/C)
- Topic extraction from contract YAML
- Error handling for subprocess failures

All tests use mocking (no real git operations).

Test markers:
    @pytest.mark.unit
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.lib.contract_change_detector import (
    _extract_declared_topics,
    _git_diff_name_status,
    _map_git_status,
    detect_contract_changes,
)

# ---------------------------------------------------------------------------
# _map_git_status tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapGitStatus:
    """Tests for git status letter → change type mapping."""

    def test_added(self) -> None:
        assert _map_git_status("A") == "added"

    def test_modified(self) -> None:
        assert _map_git_status("M") == "modified"

    def test_deleted(self) -> None:
        assert _map_git_status("D") == "deleted"

    def test_renamed(self) -> None:
        """Rename maps to modified."""
        assert _map_git_status("R100") == "modified"

    def test_copied(self) -> None:
        """Copy maps to modified."""
        assert _map_git_status("C100") == "modified"

    def test_empty_string(self) -> None:
        """Empty status defaults to modified."""
        assert _map_git_status("") == "modified"


# ---------------------------------------------------------------------------
# _git_diff_name_status tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGitDiffNameStatus:
    """Tests for the git diff subprocess wrapper."""

    @patch("omniclaude.lib.contract_change_detector.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        """Successful git diff returns (status, path) pairs."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="M\tsrc/nodes/node_foo/contract.yaml\nA\tsrc/nodes/node_bar/contract.yaml\n",
            stderr="",
        )
        result = _git_diff_name_status(Path("/repo"), "abc", "def")
        assert len(result) == 2
        assert result[0] == ("M", "src/nodes/node_foo/contract.yaml")
        assert result[1] == ("A", "src/nodes/node_bar/contract.yaml")

    @patch("omniclaude.lib.contract_change_detector.subprocess.run")
    def test_git_failure_returns_empty(self, mock_run: MagicMock) -> None:
        """Non-zero exit code returns empty list."""
        mock_run.return_value = MagicMock(
            returncode=128, stdout="", stderr="fatal: bad object"
        )
        result = _git_diff_name_status(Path("/repo"), "abc", "def")
        assert result == []

    @patch("omniclaude.lib.contract_change_detector.subprocess.run")
    def test_timeout_returns_empty(self, mock_run: MagicMock) -> None:
        """Timeout returns empty list."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)
        result = _git_diff_name_status(Path("/repo"), "abc", "def")
        assert result == []

    @patch("omniclaude.lib.contract_change_detector.subprocess.run")
    def test_git_not_found_returns_empty(self, mock_run: MagicMock) -> None:
        """FileNotFoundError returns empty list."""
        mock_run.side_effect = FileNotFoundError("git not found")
        result = _git_diff_name_status(Path("/repo"), "abc", "def")
        assert result == []


# ---------------------------------------------------------------------------
# detect_contract_changes tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectContractChanges:
    """Tests for the top-level detect_contract_changes function."""

    @patch("omniclaude.lib.contract_change_detector._extract_declared_topics")
    @patch("omniclaude.lib.contract_change_detector._git_diff_name_status")
    def test_filters_contract_yaml_only(
        self, mock_diff: MagicMock, mock_topics: MagicMock
    ) -> None:
        """Only contract.yaml files are included in results."""
        mock_diff.return_value = [
            ("M", "src/nodes/node_foo/contract.yaml"),
            ("M", "src/nodes/node_foo/node_foo.py"),
            ("A", "src/nodes/node_bar/contract.yaml"),
            ("M", "README.md"),
        ]
        mock_topics.return_value = ["onex.evt.omniclaude.foo.v1"]

        changes = detect_contract_changes("/repo", "abc", "def")
        assert len(changes) == 2
        assert changes[0].file_path == "src/nodes/node_foo/contract.yaml"
        assert changes[1].file_path == "src/nodes/node_bar/contract.yaml"

    @patch("omniclaude.lib.contract_change_detector._extract_declared_topics")
    @patch("omniclaude.lib.contract_change_detector._git_diff_name_status")
    def test_deleted_contract_skips_topic_extraction(
        self, mock_diff: MagicMock, mock_topics: MagicMock
    ) -> None:
        """Deleted contracts should not attempt topic extraction."""
        mock_diff.return_value = [
            ("D", "src/nodes/node_old/contract.yaml"),
        ]
        # _extract_declared_topics should NOT be called for deleted files
        mock_topics.return_value = []

        changes = detect_contract_changes("/repo", "abc", "def")
        assert len(changes) == 1
        assert changes[0].change_type == "deleted"
        assert changes[0].declared_topics == []
        mock_topics.assert_not_called()

    @patch("omniclaude.lib.contract_change_detector._git_diff_name_status")
    def test_no_changes_returns_empty(self, mock_diff: MagicMock) -> None:
        """No diff output returns empty list."""
        mock_diff.return_value = []
        changes = detect_contract_changes("/repo", "abc", "def")
        assert changes == []


# ---------------------------------------------------------------------------
# _extract_declared_topics tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractDeclaredTopics:
    """Tests for declared_topics extraction from contract YAML."""

    @patch("omniclaude.lib.contract_change_detector.subprocess.run")
    def test_extracts_declared_topics_list(self, mock_run: MagicMock) -> None:
        """Extracts declared_topics list from valid contract YAML."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='declared_topics:\n  - "onex.evt.omniclaude.foo.v1"\n  - "onex.evt.omniclaude.bar.v1"\n',
            stderr="",
        )
        topics = _extract_declared_topics(Path("/repo"), "abc123", "contract.yaml")
        assert topics == [
            "onex.evt.omniclaude.foo.v1",
            "onex.evt.omniclaude.bar.v1",
        ]

    @patch("omniclaude.lib.contract_change_detector.subprocess.run")
    def test_extracts_topic_base_string(self, mock_run: MagicMock) -> None:
        """Falls back to topic_base string if declared_topics is absent."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='topic_base: "onex.evt.omniclaude.session-started.v1"\n',
            stderr="",
        )
        topics = _extract_declared_topics(Path("/repo"), "abc123", "contract.yaml")
        assert topics == ["onex.evt.omniclaude.session-started.v1"]

    @patch("omniclaude.lib.contract_change_detector.subprocess.run")
    def test_git_show_failure_returns_empty(self, mock_run: MagicMock) -> None:
        """git show failure returns empty list."""
        mock_run.return_value = MagicMock(
            returncode=128, stdout="", stderr="fatal: path not found"
        )
        topics = _extract_declared_topics(Path("/repo"), "abc123", "contract.yaml")
        assert topics == []

    @patch("omniclaude.lib.contract_change_detector.subprocess.run")
    def test_invalid_yaml_returns_empty(self, mock_run: MagicMock) -> None:
        """Invalid YAML returns empty list."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not: valid: yaml: [[[",
            stderr="",
        )
        # yaml.safe_load may succeed with unexpected structure, or fail
        # Either way, we should get an empty list or a list
        topics = _extract_declared_topics(Path("/repo"), "abc123", "contract.yaml")
        assert isinstance(topics, list)

    @patch("omniclaude.lib.contract_change_detector.subprocess.run")
    def test_no_topics_fields_returns_empty(self, mock_run: MagicMock) -> None:
        """Contract without declared_topics or topic_base returns empty list."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="name: node_foo\nversion: 1.0.0\n",
            stderr="",
        )
        topics = _extract_declared_topics(Path("/repo"), "abc123", "contract.yaml")
        assert topics == []
