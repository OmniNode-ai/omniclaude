# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shared staged-file selection for per-file validation scripts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path


def selected_python_files(
    raw_paths: Sequence[str], *, roots: Iterable[Path], rule_file: Path
) -> list[Path]:
    """Return staged Python files, or the full roots when policy inputs changed."""
    selected = [Path(raw).resolve() for raw in raw_paths]
    full = not selected or any(
        path.resolve() == rule_file.resolve() or path.name == ".pre-commit-config.yaml"
        for path in selected
    )
    if full:
        files = {path for root in roots if root.exists() for path in root.rglob("*.py")}
    else:
        files = {path for path in selected if path.is_file() and path.suffix == ".py"}
    return sorted(files)
