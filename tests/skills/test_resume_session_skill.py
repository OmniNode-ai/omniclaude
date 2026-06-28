# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the resume_session skill live-state re-verification policy (OMN-13042).

C-2: on resume, the skill must read LATEST.md (fallback: newest-mtime handoff in
docs/handoffs/), re-run ``verify:`` probe blocks in live-state sections, treat any
section without a ``verify:`` block as historical, and treat un-reverifiable
live-state alarms (e.g. BUS-IS-DOWN) as stale rather than action-gating.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "resume_session"
)


def _content() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def _body() -> str:
    return _content().split("---", 2)[2]


@pytest.mark.unit
class TestResumeSessionLiveStateReverification:
    """OMN-13042 DoD: live-state re-verification policy is documented in SKILL.md."""

    def test_skill_md_exists(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()

    def test_frontmatter_parses(self) -> None:
        parts = _content().split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have YAML frontmatter delimited by ---"
        yaml.safe_load(parts[1])

    def test_reads_latest_md_with_handoffs_fallback(self) -> None:
        body = _body()
        assert "LATEST.md" in body, "SKILL.md must specify reading LATEST.md on resume"
        assert "docs/handoffs/" in body, (
            "SKILL.md must specify the docs/handoffs/ fallback location"
        )
        # Fallback must be ordered by modification time (newest mtime).
        assert re.search(r"\bmtime\b", body), (
            "SKILL.md must specify the fallback selects the newest-mtime handoff"
        )

    def test_reruns_verify_blocks_in_live_state_sections(self) -> None:
        body = _body()
        assert "verify:" in body, (
            "SKILL.md must reference 'verify:' blocks that gate live-state sections"
        )
        assert "live-state" in body.lower(), (
            "SKILL.md must describe live-state sections"
        )
        # The probe must be re-executed/re-run, not trusted as recorded.
        assert re.search(r"re-?(run|execut|probe)", body, re.IGNORECASE), (
            "SKILL.md must instruct re-running each verify: probe on resume"
        )

    def test_section_without_verify_block_is_historical(self) -> None:
        body = _body().lower()
        assert "historical" in body, (
            "SKILL.md must classify sections without a verify: block as historical"
        )
        assert "not authoritative" in body, (
            "SKILL.md must state historical sections are not authoritative for "
            "current state"
        )

    def test_stale_alarm_does_not_gate_action(self) -> None:
        body = _body()
        assert "BUS-IS-DOWN" in body, (
            "SKILL.md must name a representative stale live-state alarm "
            "(e.g. BUS-IS-DOWN)"
        )
        low = body.lower()
        assert "stale" in low, "SKILL.md must treat un-reverifiable alarms as stale"
        assert "does not" in low and "gate" in low, (
            "SKILL.md must state a stale alarm does not gate/block action"
        )

    def test_no_instructional_routing_violations(self) -> None:
        """resume_session is a Tier-3 instructional skill: no onex-run dispatch
        commands and no rendered_output receipt assertions may be introduced."""
        body = _body()
        assert not re.search(r"\bonex\s+run(-node)?\b", body, re.IGNORECASE), (
            "instructional skill must not contain onex run / onex run-node dispatch"
        )
        assert "rendered_output" not in body, (
            "instructional skill must not contain rendered_output receipt assertions"
        )
