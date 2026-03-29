# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for agent_healthcheck skill [OMN-6889].

Validates:
1. SKILL.md frontmatter structure and required fields.
2. Stall detection heuristics (inactivity, context overflow, rate limits).
3. Recovery checkpoint writing with completed/remaining work summary.
4. Integration reference in epic-team SKILL.md.

The stall detection logic tested here mirrors the pseudocode in the SKILL.md
and validates the behavioral contracts that the skill promises. Since the
health-check is a skill (LLM-executed), these tests validate the supporting
data structures and checkpoint I/O rather than executing the skill itself.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills"
_HEALTHCHECK_DIR = _SKILLS_DIR / "agent_healthcheck"
_HEALTHCHECK_SKILL_MD = _HEALTHCHECK_DIR / "SKILL.md"
_EPIC_TEAM_SKILL_MD = _SKILLS_DIR / "epic_team" / "SKILL.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and body from a SKILL.md file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path} does not start with frontmatter delimiter '---'")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path} missing closing frontmatter delimiter '---'")
    fm: dict[str, Any] = yaml.safe_load(parts[1])
    body = parts[2]
    return fm, body


# ---------------------------------------------------------------------------
# Stall detection model (mirrors SKILL.md pseudocode)
# ---------------------------------------------------------------------------


class ModelAgentHealthStatus:
    """In-memory model for agent health status used by detection heuristics.

    This is a test-only implementation of the behavioral contract defined in
    the agent_healthcheck SKILL.md. The actual runtime implementation is
    LLM-executed via the skill prompt.
    """

    def __init__(
        self,
        agent_id: str,
        last_tool_call_utc: datetime,
        context_tokens_used: int,
        context_tokens_max: int,
        rate_limit_errors: list[str] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.last_tool_call_utc = last_tool_call_utc
        self.context_tokens_used = context_tokens_used
        self.context_tokens_max = context_tokens_max
        self.rate_limit_errors = rate_limit_errors or []


def check_inactivity(
    status: ModelAgentHealthStatus,
    timeout_minutes: int = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Check if agent has been inactive beyond the timeout threshold."""
    current = now or datetime.now(UTC)
    idle_minutes = (current - status.last_tool_call_utc).total_seconds() / 60
    return {
        "stalled": idle_minutes > timeout_minutes,
        "idle_minutes": idle_minutes,
        "last_tool_call": status.last_tool_call_utc.isoformat(),
    }


def check_context_usage(
    status: ModelAgentHealthStatus,
    threshold_pct: int = 80,
) -> dict[str, Any]:
    """Check if agent's context window is approaching capacity."""
    pct = (status.context_tokens_used / status.context_tokens_max) * 100
    return {
        "stalled": pct > threshold_pct,
        "usage_pct": pct,
        "tokens_used": status.context_tokens_used,
        "tokens_max": status.context_tokens_max,
    }


def check_rate_limits(status: ModelAgentHealthStatus) -> dict[str, Any]:
    """Check if agent has encountered rate-limit errors."""
    rate_limits = [
        e for e in status.rate_limit_errors if "rate" in e.lower() or "429" in e
    ]
    return {
        "stalled": len(rate_limits) > 0,
        "rate_limit_count": len(rate_limits),
        "last_error": rate_limits[-1] if rate_limits else "",
    }


def check_agent_health(
    status: ModelAgentHealthStatus,
    timeout_minutes: int = 10,
    context_threshold_pct: int = 80,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Combined health check across all three heuristics.

    Returns the first stall reason found, or healthy status.
    """
    inactivity = check_inactivity(status, timeout_minutes, now)
    if inactivity["stalled"]:
        return {
            "status": "stalled",
            "stall_reason": "inactivity",
            "details": inactivity,
        }

    context = check_context_usage(status, context_threshold_pct)
    if context["stalled"]:
        return {
            "status": "stalled",
            "stall_reason": "context_overflow",
            "details": context,
        }

    rate = check_rate_limits(status)
    if rate["stalled"]:
        return {
            "status": "stalled",
            "stall_reason": "rate_limit",
            "details": rate,
        }

    return {
        "status": "healthy",
        "stall_reason": "",
        "details": {
            "idle_minutes": inactivity["idle_minutes"],
            "context_usage_pct": context["usage_pct"],
            "rate_limit_count": rate["rate_limit_count"],
        },
    }


# ---------------------------------------------------------------------------
# Recovery checkpoint writing
# ---------------------------------------------------------------------------


def write_recovery_checkpoint(
    checkpoint_dir: Path,
    ticket_id: str,
    completed_work: list[str],
    remaining_work: list[str],
    stall_reason: str,
    timestamp: datetime | None = None,
) -> dict[str, str]:
    """Write a recovery checkpoint for a stalled agent.

    Writes to: {checkpoint_dir}/{ticket_id}/recovery-{timestamp}.yaml
    """
    ts = timestamp or datetime.now(UTC)
    checkpoint = {
        "schema_version": "1.0.0",
        "ticket_id": ticket_id,
        "timestamp_utc": ts.isoformat(),
        "stall_reason": stall_reason,
        "completed_work": completed_work,
        "remaining_work": remaining_work,
        "recovery_action": "relaunch_fresh_agent",
    }

    ticket_dir = checkpoint_dir / ticket_id
    ticket_dir.mkdir(parents=True, exist_ok=True)
    filename = f"recovery-{ts.strftime('%Y%m%dT%H%M%S')}.yaml"
    path = ticket_dir / filename

    with open(path, "w") as f:
        yaml.dump(checkpoint, f, default_flow_style=False, sort_keys=False)

    return {"path": str(path), "timestamp": ts.isoformat()}


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.unit
class TestAgentHealthcheckSkillStructure:
    """Validate SKILL.md frontmatter and body structure."""

    def test_skill_md_exists(self) -> None:
        """agent_healthcheck SKILL.md must exist."""
        assert _HEALTHCHECK_SKILL_MD.exists(), f"Missing: {_HEALTHCHECK_SKILL_MD}"

    def test_frontmatter_required_fields(self) -> None:
        """Frontmatter must have description, mode, version, category, args."""
        fm, _ = _parse_frontmatter(_HEALTHCHECK_SKILL_MD)
        required = {"description", "mode", "version", "category", "args"}
        missing = required - set(fm.keys())
        assert not missing, f"Missing frontmatter fields: {missing}"

    def test_frontmatter_mode_is_full(self) -> None:
        """Health-check skill must be full mode (not lite)."""
        fm, _ = _parse_frontmatter(_HEALTHCHECK_SKILL_MD)
        assert fm["mode"] == "full"

    def test_frontmatter_category_is_infrastructure(self) -> None:
        """Health-check skill category must be infrastructure."""
        fm, _ = _parse_frontmatter(_HEALTHCHECK_SKILL_MD)
        assert fm["category"] == "infrastructure"

    def test_frontmatter_has_composable_flag(self) -> None:
        """Health-check skill must be marked composable for epic-team integration."""
        fm, _ = _parse_frontmatter(_HEALTHCHECK_SKILL_MD)
        assert fm.get("composable") is True

    def test_body_documents_three_heuristics(self) -> None:
        """SKILL.md body must document all three stall detection heuristics."""
        _, body = _parse_frontmatter(_HEALTHCHECK_SKILL_MD)
        assert "Inactivity" in body or "inactivity" in body
        assert "Context overflow" in body or "context overflow" in body.lower()
        assert "Rate limit" in body or "rate limit" in body.lower()

    def test_body_documents_recovery_protocol(self) -> None:
        """SKILL.md body must document the recovery protocol."""
        _, body = _parse_frontmatter(_HEALTHCHECK_SKILL_MD)
        assert "checkpoint" in body.lower()
        assert "relaunch" in body.lower()

    def test_body_references_checkpoint_protocol(self) -> None:
        """SKILL.md must reference the checkpoint protocol from OMN-6887."""
        _, body = _parse_frontmatter(_HEALTHCHECK_SKILL_MD)
        assert "OMN-6887" in body

    def test_outputs_include_status_and_checkpoint_path(self) -> None:
        """Frontmatter outputs must include status or checkpoint_path."""
        fm, _ = _parse_frontmatter(_HEALTHCHECK_SKILL_MD)
        output_names = {o["name"] for o in fm.get("outputs", [])}
        assert "status" in output_names
        assert "checkpoint_path" in output_names

    def test_topics_yaml_exists(self) -> None:
        """topics.yaml must exist alongside SKILL.md."""
        topics_file = _HEALTHCHECK_DIR / "topics.yaml"
        assert topics_file.exists(), f"Missing: {topics_file}"


@pytest.mark.unit
class TestEpicTeamHealthCheckReference:
    """Validate that epic-team SKILL.md references agent_healthcheck."""

    def test_epic_team_references_healthcheck(self) -> None:
        """epic-team SKILL.md must reference agent_healthcheck for stall detection."""
        text = _EPIC_TEAM_SKILL_MD.read_text(encoding="utf-8")
        assert "agent_healthcheck" in text or "agent-healthcheck" in text

    def test_epic_team_references_omn_6889(self) -> None:
        """epic-team SKILL.md must reference OMN-6889."""
        text = _EPIC_TEAM_SKILL_MD.read_text(encoding="utf-8")
        assert "OMN-6889" in text

    def test_epic_team_documents_three_heuristics(self) -> None:
        """epic-team SKILL.md must mention all three detection heuristics."""
        text = _EPIC_TEAM_SKILL_MD.read_text(encoding="utf-8")
        lower = text.lower()
        assert "inactivity" in lower
        assert "context" in lower
        assert "rate limit" in lower or "rate-limit" in lower


@pytest.mark.unit
class TestStallDetectionInactivity:
    """Test inactivity-based stall detection heuristic."""

    def test_no_tool_calls_for_15_minutes_triggers_stall(self) -> None:
        """Agent with no tool calls for 15 minutes should be detected as stalled.

        This is the primary acceptance criteria test: mock agent status API
        reporting 'no tool calls for 15 minutes' and verify detection.
        """
        now = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)
        last_call = now - timedelta(minutes=15)
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=last_call,
            context_tokens_used=50_000,
            context_tokens_max=200_000,
        )

        result = check_inactivity(status, timeout_minutes=10, now=now)

        assert result["stalled"] is True
        assert result["idle_minutes"] == 15.0

    def test_recent_tool_call_is_healthy(self) -> None:
        """Agent with recent tool call should not be stalled."""
        now = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)
        last_call = now - timedelta(minutes=3)
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=last_call,
            context_tokens_used=50_000,
            context_tokens_max=200_000,
        )

        result = check_inactivity(status, timeout_minutes=10, now=now)

        assert result["stalled"] is False
        assert result["idle_minutes"] == 3.0

    def test_exactly_at_threshold_is_not_stalled(self) -> None:
        """Agent at exactly the timeout threshold should not be stalled (> not >=)."""
        now = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)
        last_call = now - timedelta(minutes=10)
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=last_call,
            context_tokens_used=50_000,
            context_tokens_max=200_000,
        )

        result = check_inactivity(status, timeout_minutes=10, now=now)

        assert result["stalled"] is False

    def test_custom_timeout_threshold(self) -> None:
        """Custom timeout threshold is respected."""
        now = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)
        last_call = now - timedelta(minutes=8)
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=last_call,
            context_tokens_used=50_000,
            context_tokens_max=200_000,
        )

        # 5-minute threshold: stalled
        result = check_inactivity(status, timeout_minutes=5, now=now)
        assert result["stalled"] is True

        # 10-minute threshold: not stalled
        result = check_inactivity(status, timeout_minutes=10, now=now)
        assert result["stalled"] is False


@pytest.mark.unit
class TestStallDetectionContextOverflow:
    """Test context-window-based stall detection heuristic."""

    def test_context_above_threshold_triggers_stall(self) -> None:
        """Agent with context window >80% should trigger stall."""
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=datetime.now(UTC),
            context_tokens_used=170_000,
            context_tokens_max=200_000,
        )

        result = check_context_usage(status, threshold_pct=80)

        assert result["stalled"] is True
        assert result["usage_pct"] == 85.0

    def test_context_below_threshold_is_healthy(self) -> None:
        """Agent with low context usage should not be stalled."""
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=datetime.now(UTC),
            context_tokens_used=100_000,
            context_tokens_max=200_000,
        )

        result = check_context_usage(status, threshold_pct=80)

        assert result["stalled"] is False
        assert result["usage_pct"] == 50.0

    def test_context_exactly_at_threshold_is_not_stalled(self) -> None:
        """Agent at exactly 80% should not be stalled (> not >=)."""
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=datetime.now(UTC),
            context_tokens_used=160_000,
            context_tokens_max=200_000,
        )

        result = check_context_usage(status, threshold_pct=80)

        assert result["stalled"] is False


@pytest.mark.unit
class TestStallDetectionRateLimits:
    """Test rate-limit-based stall detection heuristic."""

    def test_rate_limit_error_triggers_stall(self) -> None:
        """Agent with rate-limit errors should trigger stall."""
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=datetime.now(UTC),
            context_tokens_used=50_000,
            context_tokens_max=200_000,
            rate_limit_errors=["429 Too Many Requests"],
        )

        result = check_rate_limits(status)

        assert result["stalled"] is True
        assert result["rate_limit_count"] == 1
        assert result["last_error"] == "429 Too Many Requests"

    def test_no_errors_is_healthy(self) -> None:
        """Agent with no errors should not be stalled."""
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=datetime.now(UTC),
            context_tokens_used=50_000,
            context_tokens_max=200_000,
            rate_limit_errors=[],
        )

        result = check_rate_limits(status)

        assert result["stalled"] is False
        assert result["rate_limit_count"] == 0

    def test_non_rate_limit_errors_ignored(self) -> None:
        """Non-rate-limit errors should not trigger stall."""
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=datetime.now(UTC),
            context_tokens_used=50_000,
            context_tokens_max=200_000,
            rate_limit_errors=["ConnectionError: timeout"],
        )

        result = check_rate_limits(status)

        assert result["stalled"] is False

    def test_multiple_rate_limit_errors(self) -> None:
        """Multiple rate-limit errors are counted correctly."""
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=datetime.now(UTC),
            context_tokens_used=50_000,
            context_tokens_max=200_000,
            rate_limit_errors=[
                "rate limit exceeded",
                "429 Too Many Requests",
                "ConnectionError: timeout",  # not a rate limit
            ],
        )

        result = check_rate_limits(status)

        assert result["stalled"] is True
        assert result["rate_limit_count"] == 2
        assert result["last_error"] == "429 Too Many Requests"


@pytest.mark.unit
class TestCombinedHealthCheck:
    """Test the combined health check across all three heuristics."""

    def test_inactivity_stall_detected_first(self) -> None:
        """Inactivity is checked first in priority order."""
        now = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=now - timedelta(minutes=15),
            context_tokens_used=190_000,
            context_tokens_max=200_000,
            rate_limit_errors=["429 Too Many Requests"],
        )

        result = check_agent_health(status, now=now)

        assert result["status"] == "stalled"
        assert result["stall_reason"] == "inactivity"

    def test_context_overflow_when_active(self) -> None:
        """Context overflow detected when agent is recently active."""
        now = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=now - timedelta(minutes=2),
            context_tokens_used=190_000,
            context_tokens_max=200_000,
        )

        result = check_agent_health(status, now=now)

        assert result["status"] == "stalled"
        assert result["stall_reason"] == "context_overflow"

    def test_healthy_agent(self) -> None:
        """Agent passing all checks is healthy."""
        now = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)
        status = ModelAgentHealthStatus(
            agent_id="task-abc123",
            last_tool_call_utc=now - timedelta(minutes=2),
            context_tokens_used=50_000,
            context_tokens_max=200_000,
        )

        result = check_agent_health(status, now=now)

        assert result["status"] == "healthy"
        assert result["stall_reason"] == ""


@pytest.mark.unit
class TestRecoveryCheckpointWriting:
    """Test recovery checkpoint writing with completed/remaining work summary."""

    def test_writes_checkpoint_file(self) -> None:
        """Recovery checkpoint writes a YAML file with correct structure."""
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            ts = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)

            result = write_recovery_checkpoint(
                checkpoint_dir=checkpoint_dir,
                ticket_id="OMN-1234",
                completed_work=["Created worktree", "Implemented feature"],
                remaining_work=["Run tests", "Create PR"],
                stall_reason="inactivity",
                timestamp=ts,
            )

            assert "OMN-1234" in result["path"]
            checkpoint_path = Path(result["path"])
            assert checkpoint_path.exists()

            data = yaml.safe_load(checkpoint_path.read_text())
            assert data["schema_version"] == "1.0.0"
            assert data["ticket_id"] == "OMN-1234"
            assert data["stall_reason"] == "inactivity"
            assert data["completed_work"] == [
                "Created worktree",
                "Implemented feature",
            ]
            assert data["remaining_work"] == ["Run tests", "Create PR"]
            assert data["recovery_action"] == "relaunch_fresh_agent"

    def test_checkpoint_filename_includes_timestamp(self) -> None:
        """Checkpoint filename includes ISO timestamp for ordering."""
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            ts = datetime(2026, 3, 28, 22, 15, 30, tzinfo=UTC)

            result = write_recovery_checkpoint(
                checkpoint_dir=checkpoint_dir,
                ticket_id="OMN-5678",
                completed_work=[],
                remaining_work=["All work remaining"],
                stall_reason="context_overflow",
                timestamp=ts,
            )

            assert "recovery-20260328T221530.yaml" in result["path"]

    def test_checkpoint_with_empty_completed_work(self) -> None:
        """Checkpoint handles case where no work was completed."""
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            ts = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)

            result = write_recovery_checkpoint(
                checkpoint_dir=checkpoint_dir,
                ticket_id="OMN-9999",
                completed_work=[],
                remaining_work=["Everything"],
                stall_reason="rate_limit",
                timestamp=ts,
            )

            data = yaml.safe_load(Path(result["path"]).read_text())
            assert data["completed_work"] == []
            assert data["remaining_work"] == ["Everything"]

    def test_multiple_checkpoints_for_same_ticket(self) -> None:
        """Multiple recovery checkpoints can exist for the same ticket."""
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)

            ts1 = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)
            ts2 = datetime(2026, 3, 28, 23, 0, 0, tzinfo=UTC)

            write_recovery_checkpoint(
                checkpoint_dir=checkpoint_dir,
                ticket_id="OMN-1234",
                completed_work=["Step 1"],
                remaining_work=["Step 2", "Step 3"],
                stall_reason="inactivity",
                timestamp=ts1,
            )

            write_recovery_checkpoint(
                checkpoint_dir=checkpoint_dir,
                ticket_id="OMN-1234",
                completed_work=["Step 1", "Step 2"],
                remaining_work=["Step 3"],
                stall_reason="context_overflow",
                timestamp=ts2,
            )

            ticket_dir = checkpoint_dir / "OMN-1234"
            checkpoints = list(ticket_dir.glob("recovery-*.yaml"))
            assert len(checkpoints) == 2


@pytest.mark.unit
class TestStallSimulationEndToEnd:
    """End-to-end test: simulate stall detection triggering recovery flow.

    This is the primary acceptance criteria test from OMN-6889:
    'Create a test fixture that mocks the agent status API to report
    no tool calls for 15 minutes; health-check module detects and
    triggers recovery flow.'
    """

    def test_stall_detection_triggers_checkpoint_recovery(self) -> None:
        """Full flow: detect 15-min stall -> write checkpoint -> verify recovery data."""
        now = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)

        # 1. Mock agent status: no tool calls for 15 minutes
        agent_status = ModelAgentHealthStatus(
            agent_id="task-epic-worker-42",
            last_tool_call_utc=now - timedelta(minutes=15),
            context_tokens_used=120_000,
            context_tokens_max=200_000,
            rate_limit_errors=[],
        )

        # 2. Run health check - should detect inactivity stall
        health_result = check_agent_health(agent_status, now=now)
        assert health_result["status"] == "stalled"
        assert health_result["stall_reason"] == "inactivity"

        # 3. On stall detection, write recovery checkpoint
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)

            checkpoint_result = write_recovery_checkpoint(
                checkpoint_dir=checkpoint_dir,
                ticket_id="OMN-6889",
                completed_work=[
                    "Created worktree at /Volumes/PRO-G40/Code/omni_worktrees/OMN-6889/omniclaude",
                    "Implemented SKILL.md for agent_healthcheck",
                    "Updated epic-team SKILL.md with health-check reference",
                ],
                remaining_work=[
                    "Write unit tests for stall detection",
                    "Create PR",
                    "Run CI and fix failures",
                ],
                stall_reason=health_result["stall_reason"],
                timestamp=now,
            )

            # 4. Verify checkpoint was written
            checkpoint_path = Path(checkpoint_result["path"])
            assert checkpoint_path.exists()

            # 5. Verify checkpoint contains recovery data for fresh agent
            data = yaml.safe_load(checkpoint_path.read_text())
            assert data["ticket_id"] == "OMN-6889"
            assert data["stall_reason"] == "inactivity"
            assert len(data["completed_work"]) == 3
            assert len(data["remaining_work"]) == 3
            assert data["recovery_action"] == "relaunch_fresh_agent"

            # 6. Verify the remaining work can be used to construct
            #    a fresh agent prompt (relaunch contract)
            assert all(isinstance(task, str) for task in data["remaining_work"])
            assert all(isinstance(task, str) for task in data["completed_work"])

    def test_context_overflow_triggers_preemptive_recovery(self) -> None:
        """Context overflow should trigger preemptive recovery before hard limit."""
        now = datetime(2026, 3, 28, 22, 0, 0, tzinfo=UTC)

        agent_status = ModelAgentHealthStatus(
            agent_id="task-epic-worker-99",
            last_tool_call_utc=now - timedelta(minutes=1),  # recently active
            context_tokens_used=170_000,  # 85% of 200K
            context_tokens_max=200_000,
        )

        health_result = check_agent_health(agent_status, now=now)
        assert health_result["status"] == "stalled"
        assert health_result["stall_reason"] == "context_overflow"

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_result = write_recovery_checkpoint(
                checkpoint_dir=Path(tmp),
                ticket_id="OMN-9999",
                completed_work=["Lots of work done over many iterations"],
                remaining_work=["Final cleanup"],
                stall_reason=health_result["stall_reason"],
                timestamp=now,
            )

            data = yaml.safe_load(Path(checkpoint_result["path"]).read_text())
            assert data["stall_reason"] == "context_overflow"
