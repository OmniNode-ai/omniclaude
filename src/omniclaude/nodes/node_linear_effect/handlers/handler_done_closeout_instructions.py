#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Reject the retired tick-box/comment closeout instruction (OMN-20368 AC6).

Pass the source skill and workflow roots explicitly when auditing another
release. Missing roots are errors, so an absent checkout cannot look clean.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_RETIRED = re.compile(r"dod_evidence\s+comment", re.IGNORECASE)
_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json", ".py"}
_EXCLUDED = {".git", ".venv", "__pycache__", "node_modules", "tests", "fixtures"}


def findings(roots: list[Path]) -> list[str]:
    out: list[str] = []
    for root in roots:
        if not root.is_dir():
            out.append(f"{root}: instruction root is missing or not a directory")
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in _SUFFIXES or any(
                part in _EXCLUDED for part in path.relative_to(root).parts
            ):
                continue
            if not path.is_file() or path.name.startswith("test_"):
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if _RETIRED.search(line):
                    out.append(
                        f"{path}:{number}: retired closeout instruction; require a fresh bound PASS receipt"
                    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    args = parser.parse_args()
    roots = args.roots or [Path(__file__).resolve().parents[5] / "plugins/onex/skills"]
    problems = findings(roots)
    if problems:
        sys.stdout.write("\n".join(problems) + "\n")
        return 1
    sys.stdout.write(
        f"PASS: no retired closeout instruction in {len(roots)} source root(s)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
