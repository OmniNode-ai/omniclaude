# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for delegation quality gate intent-specific markers [OMN-7410]."""

from __future__ import annotations


class TestQualityGateMarkers:
    """Verify quality gate is intent-specific for doc, research, test, subprocess."""

    def test_doc_gate_accepts_prose(self) -> None:
        from plugins.onex.hooks.lib.delegation_orchestrator import _run_quality_gate

        response = (
            "This module provides configuration management for the ONEX platform. "
            "It handles environment variable resolution and transport-specific "
            "configuration discovery."
        )
        passed, reason = _run_quality_gate(response, "document")
        assert passed, f"Document prose should pass gate, but failed: {reason}"

    def test_research_gate_skips_markers(self) -> None:
        from plugins.onex.hooks.lib.delegation_orchestrator import _run_quality_gate

        response = (
            "The registration subsystem uses a 4-node pattern with orchestrator, "
            "reducer, compute, and effect nodes."
        )
        passed, reason = _run_quality_gate(response, "research")
        assert passed, f"Research response should pass gate, but failed: {reason}"

    def test_test_gate_still_requires_code_markers(self) -> None:
        from plugins.onex.hooks.lib.delegation_orchestrator import _run_quality_gate

        response = "Here is some text without any test markers. " * 5
        passed, _reason = _run_quality_gate(response, "test")
        assert not passed, "Test response without markers should fail gate"

    def test_subprocess_skips_gate_entirely(self) -> None:
        from plugins.onex.hooks.lib.delegation_orchestrator import _run_quality_gate

        # Subprocess intents should bypass the gate entirely
        passed, reason = _run_quality_gate("fail", "lint")
        assert passed, f"Subprocess intent 'lint' should bypass gate, but: {reason}"

    def test_doc_gate_rejects_too_short(self) -> None:
        from plugins.onex.hooks.lib.delegation_orchestrator import _run_quality_gate

        passed, _reason = _run_quality_gate("Short.", "document")
        assert not passed, "Very short document response should still fail"

    def test_test_gate_accepts_with_markers(self) -> None:
        from plugins.onex.hooks.lib.delegation_orchestrator import _run_quality_gate

        response = "def test_example():\n    assert True\n" * 5
        passed, reason = _run_quality_gate(response, "test")
        assert passed, f"Test with markers should pass: {reason}"
