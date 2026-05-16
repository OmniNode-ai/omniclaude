#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PostToolUse aislop blocking gate for high-severity write content."""

from __future__ import annotations

import json
import re
import sys

_LOCAL_PATH_RE = re.compile(r"/(?:Users|Volumes|home)/[^\s'\"`),}\]]+")
_TOPIC_LITERAL_RE = re.compile(
    r"""(?P<quote>["'])[^"'\n]*\bonex\.\w+\.\w+\.\w+\.v\d+\b[^"'\n]*(?P=quote)"""
)
_BARE_EXCEPT_RE = re.compile(r"(?m)^[ \t]*except[ \t]*:[ \t]*(?:#.*)?$")
_EMPTY_IMPL_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?:async[ \t]+)?def[ \t]+(?P<name>\w+)"
    r"[ \t]*\([^)]*\)[ \t]*(?:->[ \t]*[^:]+)?[ \t]*:[ \t]*\n"
    r"(?P=indent)[ \t]+pass[ \t]*(?:#.*)?$"
)


def _line_number(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _line_at(content: str, offset: int) -> str:
    start = content.rfind("\n", 0, offset) + 1
    end = content.find("\n", offset)
    if end == -1:
        end = len(content)
    return content[start:end]


def _is_src_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return "/src/" in normalized or normalized.startswith("src/")


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    filename = normalized.rsplit("/", 1)[-1]
    return "/tests/" in normalized or filename.startswith("test_")


def _changed_chunks(payload: object) -> list[tuple[str, str]]:
    if not isinstance(payload, dict):
        return []

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []

    path = str(tool_input.get("file_path") or "")
    if tool_name == "Write":
        content = tool_input.get("content")
        return [(path, content)] if isinstance(content, str) else []

    if tool_name == "Edit":
        new_string = tool_input.get("new_string")
        return [(path, new_string)] if isinstance(new_string, str) else []

    if tool_name == "MultiEdit":
        chunks: list[tuple[str, str]] = []
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            for edit in edits:
                if isinstance(edit, dict) and isinstance(edit.get("new_string"), str):
                    chunks.append((path, edit["new_string"]))
        return chunks

    return []


def _finding(
    check: str,
    path: str,
    line: int,
    match_text: str,
    message: str,
) -> dict[str, object]:
    return {
        "check": check,
        "severity": "ERROR",
        "path": path,
        "line": line,
        "match": match_text[:120],
        "message": message,
    }


def scan_content(path: str, content: str) -> list[dict[str, object]]:
    """Return blocking aislop findings for one changed content chunk."""
    findings: list[dict[str, object]] = []

    for match in _LOCAL_PATH_RE.finditer(content):
        line = _line_at(content, match.start())
        if "# local-path-ok" in line:
            continue
        findings.append(
            _finding(
                "hardcoded-paths",
                path,
                _line_number(content, match.start()),
                match.group(0),
                "hardcoded local filesystem path requires # local-path-ok",
            )
        )

    for match in _TOPIC_LITERAL_RE.finditer(content):
        findings.append(
            _finding(
                "hardcoded-topics",
                path,
                _line_number(content, match.start()),
                match.group(0),
                "hardcoded onex topic string literal",
            )
        )

    for match in _BARE_EXCEPT_RE.finditer(content):
        findings.append(
            _finding(
                "bare-except",
                path,
                _line_number(content, match.start()),
                match.group(0).strip(),
                "bare except blocks hide failure classes",
            )
        )

    if _is_src_path(path) and not _is_test_path(path):
        for match in _EMPTY_IMPL_RE.finditer(content):
            if match.group("name") == "__init__":
                continue
            prefix = content[: match.start()]
            previous_lines = prefix.splitlines()[-3:]
            if any("@abstractmethod" in line for line in previous_lines):
                continue
            findings.append(
                _finding(
                    "empty-impls",
                    path,
                    _line_number(content, match.start()),
                    match.group(0).strip(),
                    "empty implementation in src/",
                )
            )

    return findings


def run_gate(raw_json: str, gate_enabled: bool = True) -> tuple[int, str]:
    """Run the gate over Claude PostToolUse JSON and return (exit_code, output)."""
    if not gate_enabled:
        return 0, raw_json

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return 0, raw_json

    findings: list[dict[str, object]] = []
    for path, content in _changed_chunks(payload):
        findings.extend(scan_content(path, content))

    if not findings:
        return 0, raw_json

    tool_name = (
        payload.get("tool_name", "tool") if isinstance(payload, dict) else "tool"
    )
    output = {
        "decision": "block",
        "reason": (
            f"AISLOP_GATE blocked {tool_name}: "
            f"{len(findings)} high-severity aislop finding(s)"
        ),
        "findings": findings,
    }
    return 2, json.dumps(output, separators=(",", ":"))


def main() -> int:
    raw_json = sys.stdin.read()
    exit_code, output = run_gate(raw_json)
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
