# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Reject hardcoded Kafka environment fallbacks in selected Python files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

FALLBACK = re.compile(r"os\.getenv\(\s*['\"]KAFKA_[^'\"]+['\"]\s*,\s*['\"][^'\"]+['\"]")
PRIVATE_BROKER = re.compile(r"192\.168\.[0-9]+\.[0-9]+:[0-9]{4,5}")
EXCLUDED_PARTS = {".venv", "__pycache__", ".claude"}


def paths(raw: list[str]) -> list[Path]:
    selected = [Path(item) for item in raw]
    if not selected or any(
        item.name in {Path(__file__).name, ".pre-commit-config.yaml"}
        for item in selected
    ):
        return sorted(
            path
            for path in Path().rglob("*.py")
            if not EXCLUDED_PARTS.intersection(path.parts)
        )
    return sorted(
        {item for item in selected if item.is_file() and item.suffix == ".py"}
    )


def main(argv: list[str] | None = None) -> int:
    findings: list[str] = []
    for path in paths(argv or []):
        under_scripts = "scripts" in path.parts
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            suppressed = "kafka-fallback-ok" in line or "noqa" in line
            if not under_scripts and FALLBACK.search(line) and not suppressed:
                findings.append(f"{path}:{number}: hardcoded Kafka fallback")
            if (
                PRIVATE_BROKER.search(line)
                and not suppressed
                and "onex-allow-internal-ip" not in line
            ):
                findings.append(f"{path}:{number}: hardcoded private-IP Kafka broker")
    if findings:
        print("ERROR: hardcoded Kafka broker fallback detected:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
