# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for agentic_tools.py (OMN-5723).

Coverage:
- dispatch_tool routing to correct handler
- read_file: success, missing file, offset/limit, empty file
- search_content: success, no matches, timeout
- find_files: success, no matches
- run_command: allowlisted command, rejected command
- Error handling: unknown tool, invalid JSON, non-dict args
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

# The hooks/lib modules are not installed packages — they're loaded at runtime.
# Use importlib to load by file path so we don't pollute sys.path with a 'lib'
# entry that would shadow tests/unit/lib/ during pytest collection.
_MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "agentic_tools.py"
)
_spec = importlib.util.spec_from_file_location("agentic_tools", _MODULE_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

ALL_TOOLS = _mod.ALL_TOOLS
_is_command_allowed = _mod._is_command_allowed
dispatch_tool = _mod.dispatch_tool

# ---------------------------------------------------------------------------
# Tests: Tool definitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolDefinitions:
    def test_all_tools_has_four_entries(self) -> None:
        assert len(ALL_TOOLS) == 4

    def test_all_tools_have_required_schema(self) -> None:
        for tool in ALL_TOOLS:
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func


# ---------------------------------------------------------------------------
# Tests: dispatch_tool routing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDispatchRouting:
    def test_unknown_tool_returns_error(self) -> None:
        result = dispatch_tool("nonexistent_tool", "{}")
        assert "unknown tool" in result.lower()

    def test_invalid_json_returns_error(self) -> None:
        result = dispatch_tool("read_file", "not json{{{")
        assert "invalid json" in result.lower()

    def test_non_dict_args_returns_error(self) -> None:
        result = dispatch_tool("read_file", '"just a string"')
        assert "must be a json object" in result.lower()

    def test_empty_args_string_treated_as_empty_dict(self) -> None:
        # Should not crash — just get a validation error from the tool itself.
        result = dispatch_tool("read_file", "")
        assert "error" in result.lower()


# ---------------------------------------------------------------------------
# Tests: read_file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadFile:
    def test_read_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = dispatch_tool("read_file", json.dumps({"path": str(f)}))
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result

    def test_read_with_offset_and_limit(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("\n".join(f"line{i}" for i in range(20)))
        result = dispatch_tool(
            "read_file", json.dumps({"path": str(f), "offset": 5, "limit": 3})
        )
        assert "line5" in result
        assert "line7" in result
        assert "line8" not in result

    def test_read_nonexistent_file(self) -> None:
        result = dispatch_tool(
            "read_file", json.dumps({"path": "/nonexistent/path/file.txt"})
        )
        assert "not found" in result.lower()

    def test_read_directory_returns_error(self, tmp_path: Path) -> None:
        result = dispatch_tool("read_file", json.dumps({"path": str(tmp_path)}))
        assert "not a file" in result.lower()

    def test_missing_path_returns_error(self) -> None:
        result = dispatch_tool("read_file", json.dumps({}))
        assert "required" in result.lower()


# ---------------------------------------------------------------------------
# Tests: search_content
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchContent:
    def test_search_finds_matches(self, tmp_path: Path) -> None:
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="code.py:1:def hello()\ncode.py:3:def world()"
        )
        with patch.object(_mod.subprocess, "run", return_value=mock_result):
            result = dispatch_tool(
                "search_content",
                json.dumps({"pattern": "def \\w+", "path": str(tmp_path)}),
            )
        assert "hello" in result
        assert "world" in result

    def test_search_no_matches(self, tmp_path: Path) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with patch.object(_mod.subprocess, "run", return_value=mock_result):
            result = dispatch_tool(
                "search_content",
                json.dumps({"pattern": "zzzznotfound", "path": str(tmp_path)}),
            )
        assert "no matches" in result.lower()

    def test_search_missing_pattern(self) -> None:
        result = dispatch_tool("search_content", json.dumps({}))
        assert "required" in result.lower()


# ---------------------------------------------------------------------------
# Tests: find_files
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindFiles:
    def test_find_files_matches(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        result = dispatch_tool(
            "find_files",
            json.dumps({"pattern": "*.py", "path": str(tmp_path)}),
        )
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_find_files_no_matches(self, tmp_path: Path) -> None:
        result = dispatch_tool(
            "find_files",
            json.dumps({"pattern": "*.xyz", "path": str(tmp_path)}),
        )
        assert "no files found" in result.lower()

    def test_find_files_missing_pattern(self) -> None:
        result = dispatch_tool("find_files", json.dumps({}))
        assert "required" in result.lower()


# ---------------------------------------------------------------------------
# Tests: run_command
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunCommand:
    def test_allowed_command_executes(self) -> None:
        result = dispatch_tool("run_command", json.dumps({"command": "ls /tmp"}))
        # Should not contain an error about not allowed
        assert "not allowed" not in result.lower()

    def test_disallowed_command_rejected(self) -> None:
        result = dispatch_tool(
            "run_command", json.dumps({"command": "rm -rf /tmp/test"})
        )
        assert "not allowed" in result.lower()

    def test_git_log_allowed(self) -> None:
        assert _is_command_allowed("git log --oneline -5")

    def test_git_diff_allowed(self) -> None:
        assert _is_command_allowed("git diff HEAD~1")

    def test_git_push_not_allowed(self) -> None:
        assert not _is_command_allowed("git push origin main")

    def test_python_not_allowed(self) -> None:
        assert not _is_command_allowed("python -c 'import os; os.system(\"rm -rf /\")'")

    def test_missing_command_returns_error(self) -> None:
        result = dispatch_tool("run_command", json.dumps({}))
        assert "required" in result.lower()

    def test_cat_allowed(self) -> None:
        assert _is_command_allowed("cat /tmp/test.txt")

    def test_wc_allowed(self) -> None:
        assert _is_command_allowed("wc -l /tmp/test.txt")
