# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests: two_strike_arbiter first-strike dispatch-surface trace guardrails (OMN-13048).

Retro D-2 (PROCESS_FAILURE_RETRO.md §3.D) mandates that on first strike against a
dispatch-surface defect the skill must require a full end-to-end static trace
(contract → dispatch callback → handler deps → injected consumers → terminal
correlation) enumerating ALL defects before fixing any.

These tests are tripwires on the SKILL.md text — the document is the authoritative
contract for skill behavior. If the guardrail text is removed the test fails,
preventing the fix-then-rediscover ladder from re-opening.

Pattern follows tests/unit/skills/test_friction_escalation_tooling_guards.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"


def _read(relpath: str) -> str:
    path = _SKILLS_ROOT / relpath
    assert path.exists(), f"Expected skill file at {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestTwoStrikeArbiterFirstStrikeProtocol:
    """Guards the first-strike dispatch-surface trace mandate (Retro D-2, OMN-13048)."""

    @pytest.fixture
    def skill_md(self) -> str:
        return _read("two_strike_arbiter/SKILL.md")

    def test_first_strike_protocol_section_present(self, skill_md: str) -> None:
        """SKILL.md must contain the First-Strike Protocol section."""
        assert "First-Strike Protocol" in skill_md, (
            "two_strike_arbiter/SKILL.md must contain a 'First-Strike Protocol' section "
            "(OMN-13048, Retro D-2). The section defines the mandatory static trace "
            "before any fix is applied on dispatch-surface defects."
        )

    def test_static_trace_chain_documented(self, skill_md: str) -> None:
        """The static trace chain must be documented: contract → dispatch → handler deps → consumers → terminal."""
        assert "contract" in skill_md and "dispatch callback" in skill_md, (
            "two_strike_arbiter/SKILL.md must document the static trace chain: "
            "contract → dispatch callback → handler deps → injected consumers → "
            "terminal correlation (OMN-13048)."
        )

    def test_enumerate_all_defects_before_fixing(self, skill_md: str) -> None:
        """SKILL.md must mandate enumerating ALL defects before fixing any."""
        assert "enumerate" in skill_md.lower() and "before" in skill_md.lower(), (
            "two_strike_arbiter/SKILL.md must explicitly require enumerating ALL "
            "defects before fixing any (OMN-13048, Retro D-2)."
        )

    def test_fix_then_rediscover_disallowed(self, skill_md: str) -> None:
        """SKILL.md must document that fix-then-rediscover is structurally disallowed."""
        assert "fix-then-rediscover" in skill_md, (
            "two_strike_arbiter/SKILL.md must state that fix-then-rediscover is "
            "structurally disallowed (OMN-13048, Retro D-2). Remove this guardrail "
            "only if the four-cycle defect ladder risk has been resolved."
        )

    def test_retro_d2_omn_13048_cited(self, skill_md: str) -> None:
        """SKILL.md must cite Retro D-2 and OMN-13048 as the source of the rule."""
        assert "D-2" in skill_md, (
            "two_strike_arbiter/SKILL.md must cite Retro D-2 (OMN-13048) as the "
            "source of the first-strike dispatch-surface trace mandate."
        )
        assert "OMN-13048" in skill_md, (
            "two_strike_arbiter/SKILL.md must reference OMN-13048 for traceability."
        )

    def test_one_pr_set_per_repo(self, skill_md: str) -> None:
        """SKILL.md must require that fixes ship as ONE PR set per repo."""
        assert "ONE" in skill_md or "one" in skill_md.lower(), (
            "two_strike_arbiter/SKILL.md must require that enumerated follow-up fixes "
            "ship as ONE design-reviewed PR set per repo (OMN-13048, Retro D-2)."
        )

    def test_anti_patterns_section_present(self, skill_md: str) -> None:
        """SKILL.md must contain an Anti-Patterns section."""
        assert "## Anti-Patterns" in skill_md, (
            "two_strike_arbiter/SKILL.md must include an '## Anti-Patterns' section "
            "listing the fix-then-rediscover and separate-PR-per-defect patterns "
            "as forbidden (OMN-13048)."
        )

    def test_dispatch_surface_concept_defined(self, skill_md: str) -> None:
        """SKILL.md must define what counts as a dispatch-surface defect."""
        assert "dispatch surface" in skill_md or "dispatch-surface" in skill_md, (
            "two_strike_arbiter/SKILL.md must define what constitutes a dispatch-surface "
            "defect (contract, dispatch callback, handler deps, consumers, terminal "
            "correlation) so the protocol boundary is unambiguous (OMN-13048)."
        )

    def test_first_strike_output_requires_trace(self, skill_md: str) -> None:
        """SKILL.md must document that action==first_strike requires the static trace."""
        assert "first_strike" in skill_md and "static trace" in skill_md, (
            "two_strike_arbiter/SKILL.md must document that when the node returns "
            "action=='first_strike' the caller must perform the dispatch-surface "
            "static trace before issuing any fix (OMN-13048)."
        )
