#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""File-path convention router for PreToolUse hooks.

Matches file paths against a route table (YAML config) and returns the
matching convention snippet content. Uses stdlib only -- no PyYAML.

Route table format (simple YAML subset):
    routes:
      - pattern: "some/glob/**"
        convention: "convention-name"

Convention files live in ``conventions/<name>.md`` and contain a
``## Inject`` section whose content is returned to the caller.

Usage (CLI):
    python3 file_path_router.py /abs/path/to/file.py

Returns the matched convention content on stdout (empty if no match).
Exit code is always 0 -- never blocks a tool call.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class Route(NamedTuple):
    pattern: str
    convention: str


# ---------------------------------------------------------------------------
# Simple YAML parser for the route table subset
# ---------------------------------------------------------------------------

_PATTERN_RE = re.compile(r'^\s*-\s*pattern:\s*"([^"]+)"\s*$')
_CONVENTION_RE = re.compile(r'^\s*convention:\s*"([^"]+)"\s*$')


def _parse_routes(text: str) -> list[Route]:
    """Parse the simple YAML route table into Route objects.

    Only supports the specific subset used by file_path_routes.yaml:
    a ``routes:`` key containing a list of ``- pattern: / convention:`` pairs.
    """
    routes: list[Route] = []
    current_pattern: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "routes:":
            continue

        pat_match = _PATTERN_RE.match(line)
        if pat_match:
            current_pattern = pat_match.group(1)
            continue

        conv_match = _CONVENTION_RE.match(line)
        if conv_match and current_pattern is not None:
            routes.append(
                Route(pattern=current_pattern, convention=conv_match.group(1))
            )
            current_pattern = None

    return routes


# ---------------------------------------------------------------------------
# Route table loading with mtime-based cache
# ---------------------------------------------------------------------------

_cached_routes: list[Route] | None = None
_cached_mtime: float = 0.0
_cached_path: str = ""


def _get_routes_file() -> str:
    """Return the absolute path to the route table YAML."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "config", "file_path_routes.yaml")


def load_routes(config_path: str | None = None) -> list[Route]:
    """Load routes from the YAML config, caching by file mtime.

    If the file is missing or unparseable, returns an empty list (never raises).
    """
    global _cached_routes, _cached_mtime, _cached_path  # noqa: PLW0603

    path = config_path or _get_routes_file()
    path = os.path.abspath(path)

    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return []

    if _cached_routes is not None and _cached_path == path and _cached_mtime == mtime:
        return _cached_routes

    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        routes = _parse_routes(text)
    except Exception:
        return []

    _cached_routes = routes
    _cached_mtime = mtime
    _cached_path = path
    return routes


# ---------------------------------------------------------------------------
# Convention file loading
# ---------------------------------------------------------------------------


def _get_conventions_dir() -> str:
    """Return the absolute path to the conventions directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "conventions")


def _extract_inject_section(text: str) -> str:
    """Extract content under the ``## Inject`` heading.

    Returns everything from the line after ``## Inject`` until the next
    ``##`` heading or end of file. Returns the full text if no ``## Inject``
    heading is found.
    """
    lines = text.splitlines()
    in_inject = False
    result: list[str] = []

    for line in lines:
        if line.strip() == "## Inject":
            in_inject = True
            continue
        if in_inject:
            if line.startswith("## "):
                break
            result.append(line)

    if result:
        return "\n".join(result).strip()
    # Fallback: return entire content (minus the title line) if no ## Inject found
    return text.strip()


def load_convention(name: str, conventions_dir: str | None = None) -> str:
    """Load and return the inject section of a convention file.

    Returns empty string on any error (file missing, read error, etc.).
    """
    base_dir = conventions_dir or _get_conventions_dir()
    path = os.path.join(base_dir, f"{name}.md")

    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        return _extract_inject_section(text)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def match_file_path(
    file_path: str,
    config_path: str | None = None,
    conventions_dir: str | None = None,
) -> tuple[str, str]:
    """Match a file path against the route table.

    Returns ``(convention_name, convention_content)`` for the first matching
    route, or ``("", "")`` if no route matches.

    The file path is normalised to use forward slashes and matched against
    each route pattern using ``fnmatch``. Both the full path and each
    suffix of the path are tested so that absolute paths match patterns
    written relative to a repo root.
    """
    routes = load_routes(config_path)
    if not routes:
        return ("", "")

    normalised = file_path.replace("\\", "/")

    # Build candidate suffixes so "/abs/path/omnidash/server/consumers/foo.py"
    # matches a pattern like "omnidash/server/consumers/**".
    parts = normalised.split("/")
    candidates = [normalised]
    for i in range(1, len(parts)):
        candidates.append("/".join(parts[i:]))

    for route in routes:
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, route.pattern):
                content = load_convention(route.convention, conventions_dir)
                return (route.convention, content)

    return ("", "")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI: ``python3 file_path_router.py <file_path>``."""
    if len(sys.argv) < 2:
        sys.exit(0)

    file_path = sys.argv[1]
    _convention_name, content = match_file_path(file_path)
    if content:
        print(content)


if __name__ == "__main__":
    main()
