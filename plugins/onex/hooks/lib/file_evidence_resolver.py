# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""File-based evidence resolver (OMN-2092).

Reads gate results from ~/.claude/baselines/ via the metrics aggregator.
Lives in the plugin layer because it depends on metrics_aggregator.

Part of OMN-2092: Evidence-Driven Injection Decisions.
"""

from __future__ import annotations

from pathlib import Path

from plugins.onex.hooks.lib.metrics_aggregator import load_latest_gate_result


class FileEvidenceResolver:
    """Reads gate results from ~/.claude/baselines/ via load_latest_gate_result()."""

    def __init__(self, baselines_root: Path | None = None) -> None:
        self._baselines_root = baselines_root

    def resolve(self, pattern_id: str) -> str | None:
        return load_latest_gate_result(pattern_id, baselines_root=self._baselines_root)


__all__ = [
    "FileEvidenceResolver",
]
