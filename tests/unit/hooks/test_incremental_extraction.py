# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for incremental extraction hook (OMN-5684)."""

from __future__ import annotations

import pytest

from omniclaude.hooks.handler_incremental_extraction import IncrementalExtractionHandler

# Use generic paths for testing (no local-path violations)
_TEST_PREFIX = "/tmp/test_worktrees/"  # local-path-ok

DEFAULT_CONFIG = {
    "enabled": True,
    "trigger_tools": ["Edit", "Write"],
    "debounce_seconds": 30,
    "watched_extensions": [".py", ".ts", ".js"],
    "watched_repos": [
        {"name": "omniintelligence", "path_prefix": _TEST_PREFIX},
        {"name": "omniclaude", "path_prefix": _TEST_PREFIX},
    ],
    "excluded_paths": ["tests/**", "__pycache__/**", "node_modules/**"],
}


@pytest.mark.unit
class TestIncrementalExtraction:
    """Tests for IncrementalExtractionHandler."""

    def test_edit_triggers_extraction(self) -> None:
        """PostToolUse event for Edit on .py file triggers extraction."""
        handler = IncrementalExtractionHandler(DEFAULT_CONFIG)
        file_path = f"{_TEST_PREFIX}OMN-123/omniintelligence/src/foo/bar.py"

        assert handler.should_trigger("Edit", file_path) is True

    def test_debounce_prevents_duplicate(self) -> None:
        """Two edits to same file within 30s — only first triggers."""
        handler = IncrementalExtractionHandler(DEFAULT_CONFIG)
        file_path = f"{_TEST_PREFIX}OMN-123/omniintelligence/src/foo/bar.py"

        # First trigger
        assert handler.should_trigger("Edit", file_path) is True
        # Second trigger within debounce window — should be skipped
        assert handler.should_trigger("Edit", file_path) is False

    def test_different_files_not_debounced(self) -> None:
        """Different files within debounce window both trigger."""
        handler = IncrementalExtractionHandler(DEFAULT_CONFIG)
        file_a = f"{_TEST_PREFIX}OMN-123/omniintelligence/src/a.py"
        file_b = f"{_TEST_PREFIX}OMN-123/omniintelligence/src/b.py"

        assert handler.should_trigger("Edit", file_a) is True
        assert handler.should_trigger("Edit", file_b) is True

    def test_wrong_tool_does_not_trigger(self) -> None:
        """Read tool should not trigger extraction."""
        handler = IncrementalExtractionHandler(DEFAULT_CONFIG)
        file_path = f"{_TEST_PREFIX}OMN-123/omniintelligence/src/foo.py"

        assert handler.should_trigger("Read", file_path) is False

    def test_wrong_extension_does_not_trigger(self) -> None:
        """.md file should not trigger extraction."""
        handler = IncrementalExtractionHandler(DEFAULT_CONFIG)
        file_path = f"{_TEST_PREFIX}OMN-123/omniintelligence/README.md"

        assert handler.should_trigger("Edit", file_path) is False

    def test_excluded_path_does_not_trigger(self) -> None:
        """Test files should be excluded."""
        handler = IncrementalExtractionHandler(DEFAULT_CONFIG)
        file_path = f"{_TEST_PREFIX}OMN-123/omniintelligence/tests/unit/test_foo.py"

        assert handler.should_trigger("Edit", file_path) is False

    def test_disabled_handler_does_not_trigger(self) -> None:
        """Disabled handler should not trigger."""
        config = {**DEFAULT_CONFIG, "enabled": False}
        handler = IncrementalExtractionHandler(config)
        file_path = f"{_TEST_PREFIX}OMN-123/omniintelligence/src/foo.py"

        assert handler.should_trigger("Edit", file_path) is False

    def test_build_crawl_command(self) -> None:
        """Build crawl command from file path."""
        handler = IncrementalExtractionHandler(DEFAULT_CONFIG)
        file_path = f"{_TEST_PREFIX}OMN-123/omniintelligence/src/foo/bar.py"

        cmd = handler.build_crawl_command(file_path)
        assert cmd is not None
        assert cmd["repo_name"] == "omniintelligence"
        assert cmd["trigger"] == "incremental"
        assert cmd["source"] == "claude_code_hook"
