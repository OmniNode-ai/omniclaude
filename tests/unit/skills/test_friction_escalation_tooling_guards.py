# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for friction-escalation tooling guardrails [OMN-8602].

The friction registry surfaced four high-severity tooling friction events:

  - ``pr_polish:tooling/agents-skip-precommit-before-push``
  - ``close_out:tooling/foreground-agent-dispatch``
  - ``redeploy:tooling/manual-deploy-execution``
  - ``redeploy:tooling/deploy-targets-local-not-201``

Each was repaired by adding a guardrail directive to the skill's prompt or
SKILL.md. These tests are tripwires: if the guardrail text is removed (which
would re-open the friction surface), the corresponding test fails.

The tests are intentionally string-level assertions on the markdown — the
documents themselves are the contract for skill behavior. Tests live in
``tests/unit/skills/`` next to ``test_autopilot_closeout.py`` (the closest
existing pattern).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Repo root: this file lives at tests/unit/skills/test_*.py — three .parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"


def _read(relpath: str) -> str:
    """Read a skill file relative to plugins/onex/skills/."""
    path = _SKILLS_ROOT / relpath
    assert path.exists(), f"Expected guardrailed skill file at {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestPrPolishPrecommitGuard:
    """Guards `pr_polish:tooling/agents-skip-precommit-before-push`."""

    @pytest.fixture
    def prompt(self) -> str:
        return _read("pr_polish/prompt.md")

    def test_pre_push_precommit_section_present(self, prompt: str) -> None:
        """Finalize must contain a Pre-Push pre-commit Gate section."""
        assert "Pre-Push pre-commit Gate" in prompt, (
            "pr_polish/prompt.md is missing the mandatory pre-push pre-commit "
            "gate section. This guards the friction surface "
            "'pr_polish:tooling/agents-skip-precommit-before-push' (OMN-8602)."
        )

    def test_runs_pre_commit_run_all_files(self, prompt: str) -> None:
        """The gate must invoke `pre-commit run --all-files`."""
        assert "pre-commit run --all-files" in prompt, (
            "pr_polish/prompt.md must invoke `pre-commit run --all-files` "
            "before push (OMN-8602)."
        )

    def test_blocks_push_on_failure(self, prompt: str) -> None:
        """A pre-commit failure must explicitly block the push."""
        # The gate sets precommit_status = "FAILED" and goto Final Report —
        # both phrases must appear in the same gate block.
        assert 'precommit_status = "FAILED"' in prompt, (
            "pr_polish/prompt.md must mark precommit_status = 'FAILED' on "
            "pre-commit failure to block the push (OMN-8602)."
        )
        idx = prompt.find('precommit_status = "FAILED"')
        assert idx >= 0
        gate_block = prompt[max(0, idx - 500) : idx + 500]
        assert "goto Final Report" in gate_block, (
            "pr_polish/prompt.md must route to 'Final Report' after "
            "pre-commit failure so push is skipped (OMN-8602)."
        )

    def test_forbids_no_verify(self, prompt: str) -> None:
        """The gate must forbid `--no-verify` as a workaround."""
        assert "DO NOT push with --no-verify" in prompt, (
            "pr_polish/prompt.md must explicitly forbid `--no-verify` as a "
            "way to bypass the pre-commit gate (OMN-8602)."
        )

    def test_references_omn_8602(self, prompt: str) -> None:
        """The gate must cite OMN-8602 for traceability."""
        assert "OMN-8602" in prompt, (
            "pr_polish/prompt.md pre-commit gate must cite OMN-8602."
        )


@pytest.mark.unit
class TestAutopilotForegroundDispatchGuard:
    """Guards `close_out:tooling/foreground-agent-dispatch`."""

    @pytest.fixture
    def skill_md(self) -> str:
        return _read("autopilot/SKILL.md")

    def test_no_foreground_agent_dispatch_callout(self, skill_md: str) -> None:
        """SKILL.md must call out that foreground Agent() dispatch is forbidden."""
        assert "No foreground `Agent()` dispatch" in skill_md, (
            "autopilot/SKILL.md is missing the explicit anti-pattern callout "
            "for foreground Agent() dispatch. This guards the friction "
            "surface 'close_out:tooling/foreground-agent-dispatch' (OMN-8602)."
        )

    def test_callout_cites_omn_8602(self, skill_md: str) -> None:
        """The callout must cite OMN-8602."""
        # Look at the specific callout, not just any OMN-8602 mention.
        idx = skill_md.find("No foreground `Agent()` dispatch")
        assert idx >= 0
        nearby = skill_md[idx : idx + 1200]
        assert "OMN-8602" in nearby, (
            "autopilot/SKILL.md foreground-Agent() callout must cite OMN-8602."
        )

    def test_callout_names_friction_surface(self, skill_md: str) -> None:
        """The callout must name the originating friction surface for traceability."""
        assert "close_out:tooling/foreground-agent-dispatch" in skill_md, (
            "autopilot/SKILL.md must reference the friction surface key "
            "'close_out:tooling/foreground-agent-dispatch' (OMN-8602)."
        )


@pytest.mark.unit
class TestRedeployManualDeployGuard:
    """Guards `redeploy:tooling/manual-deploy-execution`."""

    @pytest.fixture
    def skill_md(self) -> str:
        return _read("redeploy/SKILL.md")

    def test_anti_patterns_section_present(self, skill_md: str) -> None:
        """SKILL.md must contain an Anti-Patterns section citing OMN-8602."""
        assert "Anti-Patterns (OMN-8602)" in skill_md, (
            "redeploy/SKILL.md must include the Anti-Patterns (OMN-8602) "
            "section guarding the manual-deploy-execution and "
            "deploy-targets-local-not-201 friction surfaces."
        )

    def test_forbids_deploy_runtime_sh(self, skill_md: str) -> None:
        """SKILL.md must explicitly forbid running deploy-runtime.sh."""
        assert "deploy-runtime.sh" in skill_md, (
            "redeploy/SKILL.md must name `deploy-runtime.sh` as a forbidden "
            "manual fallback (OMN-8602)."
        )

    def test_names_manual_deploy_friction_surface(self, skill_md: str) -> None:
        """SKILL.md must reference the originating friction surface key."""
        assert "redeploy:tooling/manual-deploy-execution" in skill_md, (
            "redeploy/SKILL.md must name the friction surface key "
            "'redeploy:tooling/manual-deploy-execution' (OMN-8602)."
        )


@pytest.mark.unit
class TestRedeployLocalTargetGuard:
    """Guards `redeploy:tooling/deploy-targets-local-not-201`."""

    @pytest.fixture
    def skill_md(self) -> str:
        return _read("redeploy/SKILL.md")

    def test_names_local_target_friction_surface(self, skill_md: str) -> None:
        """SKILL.md must reference the local-target friction surface."""
        assert "redeploy:tooling/deploy-targets-local-not-201" in skill_md, (
            "redeploy/SKILL.md must name the friction surface key "
            "'redeploy:tooling/deploy-targets-local-not-201' (OMN-8602)."
        )

    def test_documents_infra_host_target(self, skill_md: str) -> None:
        """SKILL.md must document that the deploy target is INFRA_HOST."""
        assert "INFRA_HOST" in skill_md, (
            "redeploy/SKILL.md must document that the deploy target is "
            "${INFRA_HOST}, not localhost (OMN-8602)."
        )

    def test_warns_against_localhost(self, skill_md: str) -> None:
        """SKILL.md must explicitly warn against targeting local Docker."""
        # Find the anti-pattern section and verify it warns about localhost.
        idx = skill_md.find("Anti-Patterns (OMN-8602)")
        assert idx >= 0
        section = skill_md[idx:]
        assert "localhost" in section or "local Docker" in section, (
            "redeploy/SKILL.md Anti-Patterns section must warn against "
            "targeting localhost / local Docker (OMN-8602)."
        )
