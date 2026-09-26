# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Reject unsuppressed internal IP literals in selected files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(r"(?:192\.168\.|10\.(?:0|1|2)\.|172\.(?:1[6-9]|2[0-9]|3[0-1])\.)")
SUFFIXES = {".py", ".sh", ".yml", ".yaml", ".toml", ".md"}
ROOTS = ("src", "tests", "docs", ".github", "plugins")


def paths(raw: list[str]) -> list[Path]:
    selected = [Path(item) for item in raw]
    if not selected or any(
        item.name in {Path(__file__).name, ".pre-commit-config.yaml"}
        for item in selected
    ):
        return sorted(
            path
            for root in ROOTS
            if Path(root).is_dir()
            for path in Path(root).rglob("*")
            if path.is_file() and path.suffix in SUFFIXES
        )
    return sorted(
        {item for item in selected if item.is_file() and item.suffix in SUFFIXES}
    )


def main(argv: list[str] | None = None) -> int:
    findings: list[str] = []
    for path in paths(argv or []):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if PATTERN.search(line) and "onex-allow-internal-ip" not in line:
                findings.append(f"{path}:{number}:{line.strip()}")
    if findings:
        print("ERROR: hardcoded internal IP found:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
