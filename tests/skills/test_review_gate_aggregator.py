#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for review gate verdict aggregation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Import aggregator via file path since plugins aren't on sys.path
_AGGREGATOR_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "_lib"
    / "review_gate"
    / "aggregator.py"
)
_spec = importlib.util.spec_from_file_location("aggregator", _AGGREGATOR_PATH)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules["aggregator"] = _mod
_spec.loader.exec_module(_mod)
aggregate_verdicts = _mod.aggregate_verdicts


@pytest.mark.unit
class TestVerdictAggregation:
    """Verify verdict aggregation logic."""

    def test_all_pass_yields_pass(self) -> None:
        """All agents pass -> gate passes."""
        verdicts = [
            {"agent": "scope", "verdict": "pass", "findings": []},
            {"agent": "correctness", "verdict": "pass", "findings": []},
            {"agent": "conventions", "verdict": "pass", "findings": []},
        ]
        result = aggregate_verdicts(verdicts, strict=False)
        assert result["gate_verdict"] == "pass"
        assert result["total_findings"] == 0

    def test_major_finding_blocks_default_mode(self) -> None:
        """A MAJOR finding blocks merge in default mode."""
        verdicts = [
            {
                "agent": "scope",
                "verdict": "fail",
                "findings": [
                    {
                        "severity": "MAJOR",
                        "file": "src/foo.py",
                        "line": 10,
                        "message": "Scope creep",
                    }
                ],
            },
            {"agent": "correctness", "verdict": "pass", "findings": []},
            {"agent": "conventions", "verdict": "pass", "findings": []},
        ]
        result = aggregate_verdicts(verdicts, strict=False)
        assert result["gate_verdict"] == "fail"
        assert result["blocking_count"] == 1

    def test_minor_finding_passes_default_mode(self) -> None:
        """A MINOR finding does not block in default mode."""
        verdicts = [
            {"agent": "scope", "verdict": "pass", "findings": []},
            {
                "agent": "correctness",
                "verdict": "pass",
                "findings": [
                    {
                        "severity": "MINOR",
                        "file": "src/bar.py",
                        "line": 5,
                        "message": "Missing docstring",
                    }
                ],
            },
            {"agent": "conventions", "verdict": "pass", "findings": []},
        ]
        result = aggregate_verdicts(verdicts, strict=False)
        assert result["gate_verdict"] == "pass"

    def test_minor_finding_blocks_strict_mode(self) -> None:
        """A MINOR finding blocks merge in strict mode."""
        verdicts = [
            {"agent": "scope", "verdict": "pass", "findings": []},
            {
                "agent": "correctness",
                "verdict": "pass",
                "findings": [
                    {
                        "severity": "MINOR",
                        "file": "src/bar.py",
                        "line": 5,
                        "message": "Missing docstring",
                    }
                ],
            },
            {"agent": "conventions", "verdict": "pass", "findings": []},
        ]
        result = aggregate_verdicts(verdicts, strict=True)
        assert result["gate_verdict"] == "fail"
        assert result["blocking_count"] == 1

    def test_nit_never_blocks(self) -> None:
        """NIT findings never block, even in strict mode."""
        verdicts = [
            {
                "agent": "conventions",
                "verdict": "pass",
                "findings": [
                    {
                        "severity": "NIT",
                        "file": "src/baz.py",
                        "line": 1,
                        "message": "Trailing whitespace",
                    }
                ],
            },
        ]
        result = aggregate_verdicts(verdicts, strict=True)
        assert result["gate_verdict"] == "pass"
