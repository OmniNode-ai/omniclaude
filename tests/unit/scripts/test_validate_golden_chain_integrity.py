# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for validate_golden_chain_integrity.py [OMN-7389]."""

from __future__ import annotations

import subprocess
import sys


class TestGoldenChainIntegrityScript:
    """Tests that the validation script runs and passes."""

    def test_script_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/validation/validate_golden_chain_integrity.py"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"Script failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "PASS" in result.stdout


class TestGoldenChainIntegrityValidation:
    """Tests for the validate() function directly."""

    def test_validate_returns_no_errors(self) -> None:
        from scripts.validation.validate_golden_chain_integrity import validate

        errors = validate()
        assert errors == [], f"Unexpected errors: {errors}"

    def test_expected_chains_matches_registry(self) -> None:
        from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
            GOLDEN_CHAIN_DEFINITIONS,
        )
        from scripts.validation.validate_golden_chain_integrity import EXPECTED_CHAINS

        defined = {c.name for c in GOLDEN_CHAIN_DEFINITIONS}
        assert defined == EXPECTED_CHAINS
