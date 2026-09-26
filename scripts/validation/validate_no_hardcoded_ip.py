#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Validate no hardcoded internal IP addresses in source code.

Scans Python and YAML files for internal network IPs (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
that are not explicitly suppressed. Ensures all endpoint configuration
comes from environment variables.

Exit codes:
    0: No violations found
    1: Violations detected
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_IP_PATTERN = re.compile(
    r"""(?:https?://)?"""
    r"""(?:192\.168\.\d{1,3}\.\d{1,3}"""
    r"""|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"""
    r"""|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})"""
    r"""(?::\d+)?""",
)

_ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        # None — all hardcoded IPs are now forbidden
    }
)

# Inline suppression marker: lines containing this comment are exempt.
_SUPPRESS_MARKER = "onex-allow-internal-ip"


def main(argv: list[str] | None = None) -> int:
    scan_dirs = [Path("src"), Path("tests"), Path("scripts")]
    existing_dirs = [d for d in scan_dirs if d.exists()]
    if not existing_dirs:
        print(
            "No scannable directories found (src/, tests/, scripts/)", file=sys.stderr
        )  # noqa: T201
        return 1

    violations: list[str] = []
    raw_paths = argv if argv is not None else sys.argv[1:]
    selected = [Path(raw) for raw in raw_paths]
    if not selected or any(
        path.resolve() == Path(__file__).resolve()
        or path.name == ".pre-commit-config.yaml"
        for path in selected
    ):
        selected = existing_dirs
    files: set[Path] = set()
    for path in selected:
        if path.is_file() and path.suffix in {".py", ".yaml", ".yml"}:
            files.add(path)
        elif path.is_dir():
            for ext in ("*.py", "*.yaml", "*.yml"):
                files.update(path.rglob(ext))
    for path in sorted(files):
        rel = str(path)
        if rel in _ALLOWED_PATHS:
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if _IP_PATTERN.search(line) and _SUPPRESS_MARKER not in line:
                violations.append(f"  {rel}:{i}: {line.strip()}")

    if violations:
        print(f"ERROR: {len(violations)} hardcoded internal IP(s) found:")  # noqa: T201
        for v in violations:
            print(v)  # noqa: T201
        print(  # noqa: T201
            "\nAll endpoints must be configured via environment variables. "
            "See ~/.omnibase/.env and CLAUDE.md for the endpoint configuration guide."
        )
        return 1

    dirs_str = ", ".join(str(d) + "/" for d in existing_dirs)
    print(f"OK: no hardcoded internal IPs found in {dirs_str}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
