#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lint gate: reject ``mcp__linear-server__`` references in skill prompts.

Hardcoded ``mcp__linear-server__*`` tool names inside skill prompts couple the
skill to a specific Linear MCP server. ``ProtocolProjectTracker`` (and its
``uv run onex run node_*`` dispatch) is the canonical replacement: skills
address ticketing operations through the protocol, not through a vendor-
specific MCP handle.

This gate scans every ``*.md`` file under ``plugins/onex/skills/`` and exits
non-zero on any occurrence of the literal string ``mcp__linear-server__``.

## Exit codes

- 0 — no violations
- 1 — one or more violations

## Usage

- Pre-commit: invoked with staged markdown paths passed as arguments.
- CI: invoked with no arguments; scans the full ``plugins/onex/skills/`` tree.

## Refs

- OMN-8776 (this gate)
- OMN-8774 (existing-violation cleanup that precedes this gate)
- OMN-8771 (epic: remove Linear MCP coupling)
"""

from __future__ import annotations

import sys
from pathlib import Path

FORBIDDEN = "mcp__linear-server__"
SKILLS_ROOT = Path("plugins/onex/skills")


def _scan_file(path: Path) -> tuple[list[tuple[int, str]], str | None]:
    """Scan a file and return ``(hits, read_error)``.

    Fails closed: if the file is unreadable or not valid UTF-8, returns
    ``read_error`` so the caller treats it as a violation. Silently
    skipping would create a bypass path past this blocking gate.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        return [], f"{path}: decode error: {exc}"
    except OSError as exc:
        return [], f"{path}: read error: {exc}"

    hits: list[tuple[int, str]] = []
    for idx, raw in enumerate(lines, start=1):
        if FORBIDDEN in raw:
            hits.append((idx, raw.rstrip()))
    return hits, None


def _iter_skill_markdown(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def _is_skill_markdown(path: Path) -> bool:
    if path.suffix != ".md":
        return False
    try:
        rel = path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return False
    parts = rel.parts
    return len(parts) >= 3 and parts[:3] == ("plugins", "onex", "skills")


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args:
        targets = [Path(a) for a in args if _is_skill_markdown(Path(a))]
    else:
        targets = _iter_skill_markdown(SKILLS_ROOT)

    total_violations = 0
    violating_files: list[Path] = []
    for path in targets:
        if not path.exists():
            continue
        hits, read_error = _scan_file(path)
        if read_error is not None:
            sys.stderr.write(f"{read_error}\n")
            violating_files.append(path)
            total_violations += 1
            continue
        if not hits:
            continue
        violating_files.append(path)
        for line_no, raw in hits:
            sys.stderr.write(f"{path}:{line_no}: {raw}\n")
            total_violations += 1

    if total_violations == 0:
        return 0

    sys.stderr.write(
        "\n"
        f"BLOCKED: {total_violations} hardcoded '{FORBIDDEN}' reference(s) "
        f"in {len(violating_files)} skill file(s).\n"
        "\n"
        "Skill prompts must address ticketing operations through\n"
        "ProtocolProjectTracker (e.g. `uv run onex run node_<operation>`),\n"
        "not hardcoded MCP tool names that couple the skill to a specific\n"
        "Linear MCP server.\n"
        "\n"
        "See OMN-8776 / OMN-8774 for the canonical replacement pattern.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
