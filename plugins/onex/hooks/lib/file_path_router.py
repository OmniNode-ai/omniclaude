#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""File-path convention router for PreToolUse hooks.

Patterson-style routing: maps file paths to domain-specific convention
snippets that get injected into the model context during Edit/Write
operations. Each invocation is a new process (subprocess model), so
all state is loaded fresh from disk.

Performance budget: <20ms for 1 YAML read + 0-2 markdown reads + fnmatch.
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

import yaml

CONVENTIONS_DIR = Path(__file__).resolve().parent.parent / "conventions"
ROUTES_FILE = CONVENTIONS_DIR / "routes.yaml"
MAX_SNIPPET_LINES = 50


def _find_repo_root(file_path: str) -> Path | None:
    """Walk up from file_path looking for .git to find repo root.

    Handles both regular repos (.git is a directory) and worktrees
    (.git is a file pointing to the main repo's worktree directory).
    """
    p = Path(file_path).resolve()
    for parent in [p] + list(p.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _to_repo_relative(file_path: str) -> str | None:
    """Convert absolute path to repo-relative path for route matching.

    Returns a path like ``reponame/sub/path/file.py`` where ``reponame``
    is the repo root directory name. For worktrees this is the checkout
    directory name (e.g., ``omnidash``), which matches the route table
    patterns.
    """
    repo_root = _find_repo_root(file_path)
    if not repo_root:
        return None
    relative = Path(file_path).resolve().relative_to(repo_root)
    repo_name = repo_root.name
    return f"{repo_name}/{relative}"


def _load_routes() -> list[dict[str, object]]:
    """Load route table from YAML."""
    if not ROUTES_FILE.exists():
        return []
    with open(ROUTES_FILE) as f:
        data = yaml.safe_load(f)
    return data.get("routes", []) if data else []


def _load_snippet(name: str) -> str:
    """Load a convention snippet, truncating if over MAX_SNIPPET_LINES."""
    snippet_file = CONVENTIONS_DIR / f"{name}.md"
    if not snippet_file.exists():
        return ""
    lines = snippet_file.read_text().splitlines()
    if len(lines) > MAX_SNIPPET_LINES:
        print(
            f"[file_path_router] WARNING: snippet {name}.md exceeds "
            f"{MAX_SNIPPET_LINES} lines, truncating",
            file=sys.stderr,
        )
        lines = lines[:MAX_SNIPPET_LINES]
        lines.append(f"[truncated at {MAX_SNIPPET_LINES} lines]")
    return "\n".join(lines)


def get_conventions(file_path: str) -> str:
    """Return concatenated convention snippets for a file path."""
    repo_relative = _to_repo_relative(file_path)
    if not repo_relative:
        return ""

    routes = _load_routes()
    matched = [
        r
        for r in routes
        if isinstance(r.get("pattern"), str)
        and fnmatch.fnmatch(repo_relative, r["pattern"])
    ]
    if not matched:
        return ""

    snippets: list[str] = []
    seen: set[str] = set()
    for route in matched:
        for conv_name in route.get("conventions", []):
            if conv_name not in seen:
                seen.add(conv_name)
                snippet = _load_snippet(conv_name)
                if snippet:
                    snippets.append(snippet)

    return "\n\n".join(snippets)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(0)
    result = get_conventions(sys.argv[1])
    if result:
        print(result)
