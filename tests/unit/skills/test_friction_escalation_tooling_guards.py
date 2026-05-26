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
    """Guards `pr_polish:tooling/agents-skip-precommit-before-push`.

    Updated for thin dispatch-only shim (OMN-8768): pre-commit gate logic
    now lives in node_pr_polish; the shim dispatches to it. The SKILL.md
    must document that the node owns the pre-commit gate (OMN-8602).
    """

    @pytest.fixture
    def skill_md(self) -> str:
        return _read("pr_polish/SKILL.md")

    def test_pre_push_precommit_gate_in_node(self, skill_md: str) -> None:
        """SKILL.md must reference the backing node that owns the pre-commit gate."""
        assert "node_pr_polish" in skill_md, (
            "pr_polish/SKILL.md must reference node_pr_polish, which owns "
            "the pre-commit gate (OMN-8602). The gate is enforced in the node, "
            "not inline in the shim prompt."
        )

    def test_dispatch_only_tag(self, skill_md: str) -> None:
        """Thin shim must carry dispatch-only tag to prevent inline logic creep."""
        assert "dispatch-only" in skill_md, (
            "pr_polish/SKILL.md must be tagged dispatch-only (OMN-8768). "
            "Pre-commit gate belongs to node_pr_polish."
        )

    def test_runs_pre_commit_run_all_files(self, skill_md: str) -> None:
        """SKILL.md or prompt must not encourage skipping pre-commit."""
        prompt = _read("pr_polish/prompt.md")
        assert "--no-verify" not in prompt, (
            "pr_polish/prompt.md must not reference --no-verify (OMN-8602)."
        )

    def test_blocks_push_on_failure(self, skill_md: str) -> None:
        """Dispatch-only shim must not implement push inline."""
        prompt = _read("pr_polish/prompt.md")
        assert "git push" not in prompt, (
            "pr_polish/prompt.md must not run git push inline (OMN-8602). "
            "The node_pr_polish node owns the push path."
        )

    def test_forbids_no_verify(self, skill_md: str) -> None:
        """The shim prompt must not use --no-verify."""
        prompt = _read("pr_polish/prompt.md")
        assert "--no-verify" not in prompt

    def test_references_omn_8602(self, skill_md: str) -> None:
        """SKILL.md must preserve OMN-8602 traceability via the node reference."""
        # node_pr_polish is the authoritative location for OMN-8602 guards.
        assert "node_pr_polish" in skill_md


@pytest.mark.unit
class TestAutopilotForegroundDispatchGuard:
    """Retired autopilot must not re-open foreground dispatch."""

    def test_autopilot_skill_remains_retired(self) -> None:
        """OMN-12234 removed autopilot as a user-invocable foreground shim."""
        assert not (_SKILLS_ROOT / "autopilot" / "SKILL.md").exists()

    def test_session_orchestrator_replaces_autopilot(self) -> None:
        """Session orchestrator is the supported close-out control surface."""
        session_skill = _read("session/SKILL.md")
        assert "node_session_orchestrator" in session_skill


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
