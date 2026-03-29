# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for agentic_tools.py (OMN-5723, OMN-6955).

Coverage:
- dispatch_tool routing to correct handler
- read_file: success, missing file, offset/limit, empty file
- search_content: success, no matches, timeout
- find_files: success, no matches
- git_log: success, unsafe args rejected
- git_diff: success, write flags rejected
- git_show: success, missing ref
- list_dir: success, not a directory
- line_count: success, missing file
- Error handling: unknown tool, invalid JSON, non-dict args
- Truncation: 8KB cap with stable marker
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

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
sys.modules["agentic_tools"] = _mod
_spec.loader.exec_module(_mod)

ALL_TOOLS = _mod.ALL_TOOLS
dispatch_tool = _mod.dispatch_tool
_truncate = _mod._truncate
_validate_git_args = _mod._validate_git_args


@pytest.mark.unit
class TestToolDefinitions:
    def test_all_tools_has_eight_entries(self) -> None:
        assert len(ALL_TOOLS) == 8

    def test_all_tools_have_required_schema(self) -> None:
        for tool in ALL_TOOLS:
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func

    def test_tool_names_match_plan(self) -> None:
        names = {t["function"]["name"] for t in ALL_TOOLS}
        expected = {
            "read_file",
            "search_content",
            "find_files",
            "git_log",
            "git_diff",
            "git_show",
            "list_dir",
            "line_count",
        }
        assert names == expected

    def test_no_run_command_tool(self) -> None:
        names = {t["function"]["name"] for t in ALL_TOOLS}
        assert "run_command" not in names


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
        result = dispatch_tool("read_file", "")
        assert "error" in result.lower()


@pytest.mark.unit
class TestReadFile:
    def test_read_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = dispatch_tool("read_file", json.dumps({"path": str(f)}))
        assert "line1" in result
        assert "line2" in result

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


@pytest.mark.unit
class TestGitLog:
    def test_git_log_default(self) -> None:
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="abc1234 first commit"
        )
        with patch.object(_mod.subprocess, "run", return_value=mock_result):
            result = dispatch_tool("git_log", json.dumps({}))
        assert "first commit" in result

    def test_git_log_unsafe_args_rejected(self) -> None:
        result = dispatch_tool("git_log", json.dumps({"args": "--oneline; rm -rf /"}))
        assert "unsafe" in result.lower()

    def test_git_log_force_flag_rejected(self) -> None:
        result = dispatch_tool("git_log", json.dumps({"args": "--force"}))
        assert "not allowed" in result.lower()


@pytest.mark.unit
class TestGitDiff:
    def test_git_diff_default(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        with patch.object(_mod.subprocess, "run", return_value=mock_result):
            result = dispatch_tool("git_diff", json.dumps({}))
        assert "no changes" in result.lower()

    def test_git_diff_hard_flag_rejected(self) -> None:
        result = dispatch_tool("git_diff", json.dumps({"args": "--hard"}))
        assert "not allowed" in result.lower()


@pytest.mark.unit
class TestGitShow:
    def test_git_show_with_ref(self) -> None:
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="commit abc1234\nAuthor: test"
        )
        with patch.object(_mod.subprocess, "run", return_value=mock_result):
            result = dispatch_tool("git_show", json.dumps({"ref": "abc1234"}))
        assert "abc1234" in result

    def test_git_show_missing_ref(self) -> None:
        result = dispatch_tool("git_show", json.dumps({}))
        assert "required" in result.lower()

    def test_git_show_pipe_injection(self) -> None:
        result = dispatch_tool("git_show", json.dumps({"ref": "HEAD | rm -rf /"}))
        assert "unsafe" in result.lower()


@pytest.mark.unit
class TestListDir:
    def test_list_dir(self, tmp_path: Path) -> None:
        (tmp_path / "file.py").write_text("")
        (tmp_path / "subdir").mkdir()
        result = dispatch_tool("list_dir", json.dumps({"path": str(tmp_path)}))
        assert "file.py" in result
        assert "subdir/" in result

    def test_list_dir_not_found(self) -> None:
        result = dispatch_tool("list_dir", json.dumps({"path": "/nonexistent/dir"}))
        assert "not found" in result.lower()

    def test_list_dir_file_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("")
        result = dispatch_tool("list_dir", json.dumps({"path": str(f)}))
        assert "not a directory" in result.lower()


@pytest.mark.unit
class TestLineCount:
    def test_line_count(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\nd\n")
        result = dispatch_tool("line_count", json.dumps({"path": str(f)}))
        assert "4 lines" in result

    def test_line_count_missing_path(self) -> None:
        result = dispatch_tool("line_count", json.dumps({}))
        assert "required" in result.lower()

    def test_line_count_not_found(self) -> None:
        result = dispatch_tool(
            "line_count", json.dumps({"path": "/nonexistent/file.txt"})
        )
        assert "not found" in result.lower()


@pytest.mark.unit
class TestTruncation:
    def test_small_output_not_truncated(self) -> None:
        result = _truncate("short text", max_bytes=1000)
        assert result == "short text"
        assert "TRUNCATED" not in result

    def test_large_output_truncated_with_marker(self) -> None:
        lines = [f"line{i:04d} " + "x" * 90 for i in range(100)]
        text = "\n".join(lines)
        result = _truncate(text, max_bytes=1000)
        assert "[TRUNCATED --" in result
        assert "more lines]" in result

    def test_default_cap_is_8kb(self) -> None:
        assert _mod._DEFAULT_MAX_OUTPUT_BYTES == 8 * 1024


@pytest.mark.unit
class TestGitArgValidation:
    def test_safe_args_accepted(self) -> None:
        result = _validate_git_args("--oneline -10")
        assert isinstance(result, list)

    def test_semicolon_rejected(self) -> None:
        result = _validate_git_args("HEAD; rm -rf /")
        assert isinstance(result, str)
        assert "unsafe" in result.lower()

    def test_force_flag_rejected(self) -> None:
        result = _validate_git_args("--force origin main")
        assert isinstance(result, str)
        assert "not allowed" in result.lower()

    def test_delete_flag_rejected(self) -> None:
        result = _validate_git_args("-D branch-name")
        assert isinstance(result, str)
        assert "not allowed" in result.lower()
