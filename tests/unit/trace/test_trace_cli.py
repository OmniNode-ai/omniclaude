# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the ``omn trace`` CLI command group.

Tests:
- make_trace_group() returns a Click group
- trace last: no frames / with frames / session filter forwarded
- trace show: frame not found / found / invalid UUID
- trace diff: frame not found / found / invalid UUIDs
- trace replay: no engine / engine injected / frame not found / mode mapping
- trace pr show: not found / found
- trace pr frames: not found / found
- trace pr failure-path: no failure / fail only / fail+pass
- trace pr timeline: empty frames / with frames and CI artifacts

All tests use in-memory fixture data — no DB, no filesystem, no Kafka.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

from click.testing import CliRunner

from omniclaude.cli.trace import make_trace_group
from omniclaude.trace.change_frame import (
    ChangeFrame,
    ModelCheckResult,
    ModelDelta,
    ModelEvidence,
    ModelFrameConfig,
    ModelIntentRef,
    ModelOutcome,
    ModelToolEvent,
    ModelWorkspaceRef,
)
from omniclaude.trace.pr_envelope import (
    ModelCIArtifact,
    ModelPRBodyVersion,
    ModelPRText,
    ModelPRTimeline,
    PREnvelope,
)
from omniclaude.trace.replay_engine import ReplayMode, ReplayResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TIMESTAMP = "2026-02-21T12:00:00Z"
TRACE_ID = "trace-abc-123"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def make_check_result(exit_code: int = 0, command: str = "pytest") -> ModelCheckResult:
    return ModelCheckResult(
        command=command,
        environment_hash=_sha("env"),
        exit_code=exit_code,
        output_hash=_sha("output"),
        truncated_output="some output",
    )


def make_frame(
    outcome_status: str = "pass",
    files_changed: list[str] | None = None,
    failure_sig: str | None = None,
    timestamp: str = TIMESTAMP,
    frame_id: UUID | None = None,
) -> ChangeFrame:
    if files_changed is None:
        files_changed = ["src/router.py"]
    if frame_id is None:
        frame_id = uuid4()
    check_exit = 0 if outcome_status == "pass" else 1
    sig = failure_sig if outcome_status != "pass" else None

    return ChangeFrame(
        frame_id=frame_id,
        parent_frame_id=None,
        trace_id=TRACE_ID,
        timestamp_utc=timestamp,
        agent_id="agent-test",
        model_id="claude-sonnet-4-5",
        frame_config=ModelFrameConfig(),
        intent_ref=ModelIntentRef(prompt_hash=_sha("prompt")),
        workspace_ref=ModelWorkspaceRef(
            repo="OmniNode-ai/omniclaude",
            branch="feature/test",
            base_commit="abc" + "0" * 37,
        ),
        delta=ModelDelta(
            diff_patch="--- a/src/router.py\n+++ b/src/router.py\n@@ -1 +1 @@\n-old\n+new\n",
            files_changed=files_changed,
            loc_added=1,
            loc_removed=0,
        ),
        tool_events=[
            ModelToolEvent(
                tool_name="Edit",
                input_hash=_sha("in"),
                output_hash=_sha("out"),
                raw_pointer=None,
            )
        ],
        checks=[make_check_result(check_exit)],
        outcome=ModelOutcome(
            status=outcome_status,  # type: ignore[arg-type]
            failure_signature_id=sig,
        ),
        evidence=ModelEvidence(),
    )


def make_pr_envelope(pr_number: int = 42) -> PREnvelope:
    body = "## Summary\nFixed the bug."
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    return PREnvelope(
        pr_id=uuid4(),
        provider="github",
        repo="OmniNode-ai/omniclaude",
        pr_number=pr_number,
        head_sha="a" * 40,
        base_sha="b" * 40,
        branch_name="feature/fix-router",
        pr_text=ModelPRText(
            title="Fix router bug",
            body_versions=[
                ModelPRBodyVersion(
                    version=1,
                    body=body,
                    body_hash=body_hash,
                    timestamp=TIMESTAMP,
                )
            ],
        ),
        labels=["bug"],
        reviewers=["alice"],
        timeline=ModelPRTimeline(created_at=TIMESTAMP, merged_at=None),
        ci_artifacts=[
            ModelCIArtifact(
                check_name="CI / tests",
                status="success",
                logs_pointer="https://example.com/logs/1",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Helper: build CLI group with in-memory sources
# ---------------------------------------------------------------------------


def _build_group(
    frames: list[ChangeFrame] | None = None,
    single_frames: dict[UUID, ChangeFrame] | None = None,
    pr: PREnvelope | None = None,
    pr_frames: list[ChangeFrame] | None = None,
    mock_replay_result: ReplayResult | None = None,
) -> Any:
    stored_frames: list[ChangeFrame] = frames or []
    stored_single: dict[UUID, ChangeFrame] = single_frames or {}
    stored_pr: PREnvelope | None = pr
    stored_pr_frames: list[ChangeFrame] = pr_frames or []

    def frame_source(session_id: str | None, limit: int) -> list[ChangeFrame]:
        return stored_frames[:limit]

    def single_frame_source(frame_id: UUID) -> ChangeFrame | None:
        return stored_single.get(frame_id)

    def pr_source(pr_number: int) -> PREnvelope | None:
        if stored_pr is not None and stored_pr.pr_number == pr_number:
            return stored_pr
        return None

    def pr_frame_source(pr_number: int) -> list[ChangeFrame]:
        if stored_pr is not None and stored_pr.pr_number == pr_number:
            return stored_pr_frames
        return []

    # Build a minimal mock ReplayEngine if result provided
    replay_engine = None
    if mock_replay_result is not None:
        from unittest.mock import MagicMock

        replay_engine = MagicMock()
        replay_engine.replay.return_value = mock_replay_result

    return make_trace_group(
        frame_source=frame_source,
        single_frame_source=single_frame_source,
        pr_source=pr_source,
        pr_frame_source=pr_frame_source,
        replay_engine=replay_engine,
    )


# ---------------------------------------------------------------------------
# TestMakeTraceGroup
# ---------------------------------------------------------------------------


class TestMakeTraceGroup:
    def test_returns_click_group(self) -> None:
        import click

        group = make_trace_group()
        assert isinstance(group, click.Group)

    def test_has_expected_commands(self) -> None:
        group = make_trace_group()
        assert "last" in group.commands
        assert "show" in group.commands
        assert "diff" in group.commands
        assert "replay" in group.commands
        assert "pr" in group.commands

    def test_pr_subgroup_has_expected_commands(self) -> None:
        group = make_trace_group()
        pr_group = group.commands["pr"]
        assert "show" in pr_group.commands
        assert "frames" in pr_group.commands
        assert "failure-path" in pr_group.commands
        assert "timeline" in pr_group.commands


# ---------------------------------------------------------------------------
# TestTraceLast
# ---------------------------------------------------------------------------


class TestTraceLast:
    def test_no_frames_prints_message(self) -> None:
        runner = CliRunner()
        group = _build_group(frames=[])
        result = runner.invoke(group, ["last"])
        assert result.exit_code == 0
        assert "No frames found" in result.output

    def test_single_frame_shown(self) -> None:
        frame = make_frame(outcome_status="pass")
        runner = CliRunner()
        group = _build_group(frames=[frame])
        result = runner.invoke(group, ["last"])
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert str(frame.frame_id)[:8] in result.output

    def test_fail_frame_shown(self) -> None:
        frame = make_frame(
            outcome_status="fail", failure_sig="TYPE_FAIL:AssertionError"
        )
        runner = CliRunner()
        group = _build_group(frames=[frame])
        result = runner.invoke(group, ["last"])
        assert result.exit_code == 0
        assert "FAIL" in result.output
        assert "TYPE_FAIL:AssertionError" in result.output

    def test_limit_respected(self) -> None:
        frames = [make_frame() for _ in range(5)]
        runner = CliRunner()

        # Capture what the frame_source sees via side-effects
        seen_limit: list[int] = []

        def frame_source(session_id: str | None, limit: int) -> list[ChangeFrame]:
            seen_limit.append(limit)
            return frames[:limit]

        group = make_trace_group(frame_source=frame_source)
        result = runner.invoke(group, ["last", "--n", "3"])
        assert result.exit_code == 0
        assert seen_limit == [3]

    def test_session_filter_forwarded(self) -> None:
        seen_session: list[str | None] = []

        def frame_source(session_id: str | None, limit: int) -> list[ChangeFrame]:
            seen_session.append(session_id)
            return []

        group = make_trace_group(frame_source=frame_source)
        runner = CliRunner()
        runner.invoke(group, ["last", "--session", "ses-999"])
        assert seen_session == ["ses-999"]

    def test_session_label_in_output(self) -> None:
        frame = make_frame()
        runner = CliRunner()
        group = _build_group(frames=[frame])
        result = runner.invoke(group, ["last", "--session", "my-session"])
        assert "my-session" in result.output

    def test_files_shown(self) -> None:
        frame = make_frame(files_changed=["src/alpha.py", "src/beta.py"])
        runner = CliRunner()
        group = _build_group(frames=[frame])
        result = runner.invoke(group, ["last"])
        assert "src/alpha.py" in result.output
        assert "src/beta.py" in result.output


# ---------------------------------------------------------------------------
# TestTraceShow
# ---------------------------------------------------------------------------


class TestTraceShow:
    def test_invalid_uuid_returns_error(self) -> None:
        group = _build_group()
        runner = CliRunner()
        result = runner.invoke(group, ["show", "not-a-uuid"])
        assert result.exit_code != 0
        assert "Invalid frame_id" in result.output

    def test_frame_not_found_returns_error(self) -> None:
        group = _build_group()
        runner = CliRunner()
        result = runner.invoke(group, ["show", str(uuid4())])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_shows_frame_detail(self) -> None:
        frame = make_frame(outcome_status="pass")
        group = _build_group(single_frames={frame.frame_id: frame})
        runner = CliRunner()
        result = runner.invoke(group, ["show", str(frame.frame_id)])
        assert result.exit_code == 0
        assert str(frame.frame_id) in result.output
        assert "PASS" in result.output

    def test_shows_diff_patch_truncated(self) -> None:
        frame = make_frame()
        group = _build_group(single_frames={frame.frame_id: frame})
        runner = CliRunner()
        result = runner.invoke(group, ["show", str(frame.frame_id)])
        assert result.exit_code == 0
        # diff patch is short so it appears verbatim
        assert "src/router.py" in result.output

    def test_full_flag_disables_truncation(self) -> None:
        frame = make_frame()
        group = _build_group(single_frames={frame.frame_id: frame})
        runner = CliRunner()
        result = runner.invoke(group, ["show", "--full", str(frame.frame_id)])
        assert result.exit_code == 0
        # No truncation marker present
        assert "chars omitted" not in result.output

    def test_shows_failure_sig_when_failed(self) -> None:
        frame = make_frame(outcome_status="fail", failure_sig="LINT_FAIL:E501")
        group = _build_group(single_frames={frame.frame_id: frame})
        runner = CliRunner()
        result = runner.invoke(group, ["show", str(frame.frame_id)])
        assert result.exit_code == 0
        assert "LINT_FAIL:E501" in result.output


# ---------------------------------------------------------------------------
# TestTraceDiff
# ---------------------------------------------------------------------------


class TestTraceDiff:
    def test_invalid_frame_id_a(self) -> None:
        group = _build_group()
        runner = CliRunner()
        result = runner.invoke(group, ["diff", "bad-uuid", str(uuid4())])
        assert result.exit_code != 0
        assert "frame_id_a" in result.output

    def test_invalid_frame_id_b(self) -> None:
        group = _build_group()
        runner = CliRunner()
        result = runner.invoke(group, ["diff", str(uuid4()), "bad-uuid"])
        assert result.exit_code != 0
        assert "frame_id_b" in result.output

    def test_frame_a_not_found(self) -> None:
        frame_b = make_frame()
        group = _build_group(single_frames={frame_b.frame_id: frame_b})
        runner = CliRunner()
        result = runner.invoke(group, ["diff", str(uuid4()), str(frame_b.frame_id)])
        assert result.exit_code != 0
        assert "Frame A" in result.output
        assert "not found" in result.output

    def test_frame_b_not_found(self) -> None:
        frame_a = make_frame()
        group = _build_group(single_frames={frame_a.frame_id: frame_a})
        runner = CliRunner()
        result = runner.invoke(group, ["diff", str(frame_a.frame_id), str(uuid4())])
        assert result.exit_code != 0
        assert "Frame B" in result.output
        assert "not found" in result.output

    def test_shows_diff_between_frames(self) -> None:
        frame_a = make_frame(outcome_status="fail", files_changed=["src/a.py"])
        frame_b = make_frame(outcome_status="pass", files_changed=["src/b.py"])
        group = _build_group(
            single_frames={frame_a.frame_id: frame_a, frame_b.frame_id: frame_b}
        )
        runner = CliRunner()
        result = runner.invoke(
            group, ["diff", str(frame_a.frame_id), str(frame_b.frame_id)]
        )
        assert result.exit_code == 0
        assert "src/a.py" in result.output
        assert "src/b.py" in result.output
        assert "FAIL" in result.output
        assert "PASS" in result.output

    def test_shared_files_shown(self) -> None:
        frame_a = make_frame(files_changed=["shared.py", "a.py"])
        frame_b = make_frame(files_changed=["shared.py", "b.py"])
        group = _build_group(
            single_frames={frame_a.frame_id: frame_a, frame_b.frame_id: frame_b}
        )
        runner = CliRunner()
        result = runner.invoke(
            group, ["diff", str(frame_a.frame_id), str(frame_b.frame_id)]
        )
        assert result.exit_code == 0
        assert "shared.py" in result.output

    def test_check_comparison_shown(self) -> None:
        frame_a = make_frame(outcome_status="fail")
        frame_b = make_frame(outcome_status="pass")
        group = _build_group(
            single_frames={frame_a.frame_id: frame_a, frame_b.frame_id: frame_b}
        )
        runner = CliRunner()
        result = runner.invoke(
            group, ["diff", str(frame_a.frame_id), str(frame_b.frame_id)]
        )
        assert result.exit_code == 0
        assert "pytest" in result.output

    def test_failure_sig_shown_in_diff(self) -> None:
        frame_a = make_frame(outcome_status="fail", failure_sig="TYPE_FAIL:X")
        frame_b = make_frame(outcome_status="pass")
        group = _build_group(
            single_frames={frame_a.frame_id: frame_a, frame_b.frame_id: frame_b}
        )
        runner = CliRunner()
        result = runner.invoke(
            group, ["diff", str(frame_a.frame_id), str(frame_b.frame_id)]
        )
        assert result.exit_code == 0
        assert "TYPE_FAIL:X" in result.output


# ---------------------------------------------------------------------------
# TestTraceReplay
# ---------------------------------------------------------------------------


class TestTraceReplay:
    def _make_replay_result(self, mode: ReplayMode, diverged: bool) -> ReplayResult:
        frame_id = uuid4()
        return ReplayResult(
            frame_id=frame_id,
            mode=mode,
            original_outcome="fail",  # type: ignore[arg-type]
            replayed_outcome="pass" if not diverged else "fail",  # type: ignore[arg-type]
            diverged=diverged,
            divergence_reason="env_changed" if diverged else None,
            check_results=[make_check_result(0)],
            duration_seconds=0.5,
        )

    def test_no_engine_returns_error(self) -> None:
        frame = make_frame()
        group = _build_group(single_frames={frame.frame_id: frame})
        runner = CliRunner()
        result = runner.invoke(group, ["replay", str(frame.frame_id)])
        assert result.exit_code != 0
        assert "ReplayEngine not configured" in result.output

    def test_invalid_uuid_returns_error(self) -> None:
        result_obj = self._make_replay_result(ReplayMode.FULL, False)
        group = _build_group(mock_replay_result=result_obj)
        runner = CliRunner()
        result = runner.invoke(group, ["replay", "not-a-uuid"])
        assert result.exit_code != 0
        assert "Invalid frame_id" in result.output

    def test_frame_not_found_returns_error(self) -> None:
        result_obj = self._make_replay_result(ReplayMode.FULL, False)
        group = _build_group(mock_replay_result=result_obj)
        runner = CliRunner()
        result = runner.invoke(group, ["replay", str(uuid4())])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_replay_full_mode(self) -> None:
        frame = make_frame()
        result_obj = self._make_replay_result(ReplayMode.FULL, False)
        group = _build_group(
            single_frames={frame.frame_id: frame},
            mock_replay_result=result_obj,
        )
        runner = CliRunner()
        result = runner.invoke(group, ["replay", str(frame.frame_id), "--mode", "full"])
        assert result.exit_code == 0
        assert "full" in result.output
        assert "CONSISTENT" in result.output

    def test_replay_diverged_shows_reason(self) -> None:
        frame = make_frame()
        result_obj = self._make_replay_result(ReplayMode.STUBBED, True)
        group = _build_group(
            single_frames={frame.frame_id: frame},
            mock_replay_result=result_obj,
        )
        runner = CliRunner()
        result = runner.invoke(
            group, ["replay", str(frame.frame_id), "--mode", "stubbed"]
        )
        assert result.exit_code == 0
        assert "DIVERGED" in result.output
        assert "env_changed" in result.output

    def test_replay_test_only_mode(self) -> None:
        frame = make_frame()
        result_obj = self._make_replay_result(ReplayMode.TEST_ONLY, False)
        group = _build_group(
            single_frames={frame.frame_id: frame},
            mock_replay_result=result_obj,
        )
        runner = CliRunner()
        result = runner.invoke(
            group, ["replay", str(frame.frame_id), "--mode", "test-only"]
        )
        assert result.exit_code == 0
        assert "test_only" in result.output

    def test_duration_shown(self) -> None:
        frame = make_frame()
        result_obj = self._make_replay_result(ReplayMode.FULL, False)
        group = _build_group(
            single_frames={frame.frame_id: frame},
            mock_replay_result=result_obj,
        )
        runner = CliRunner()
        result = runner.invoke(group, ["replay", str(frame.frame_id)])
        assert result.exit_code == 0
        assert "0.50s" in result.output


# ---------------------------------------------------------------------------
# TestTracePrShow
# ---------------------------------------------------------------------------


class TestTracePrShow:
    def test_pr_not_found(self) -> None:
        group = _build_group()
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "show", "99"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_shows_pr_metadata(self) -> None:
        pr = make_pr_envelope(42)
        group = _build_group(pr=pr)
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "show", "42"])
        assert result.exit_code == 0
        assert "PR #42" in result.output
        assert "Fix router bug" in result.output
        assert "OmniNode-ai/omniclaude" in result.output

    def test_shows_labels(self) -> None:
        pr = make_pr_envelope(42)
        group = _build_group(pr=pr)
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "show", "42"])
        assert result.exit_code == 0
        assert "bug" in result.output

    def test_shows_reviewers(self) -> None:
        pr = make_pr_envelope(42)
        group = _build_group(pr=pr)
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "show", "42"])
        assert result.exit_code == 0
        assert "alice" in result.output

    def test_shows_ci_artifacts(self) -> None:
        pr = make_pr_envelope(42)
        group = _build_group(pr=pr)
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "show", "42"])
        assert result.exit_code == 0
        assert "CI / tests" in result.output

    def test_shows_description_versions(self) -> None:
        pr = make_pr_envelope(42)
        group = _build_group(pr=pr)
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "show", "42"])
        assert result.exit_code == 0
        assert "v1" in result.output


# ---------------------------------------------------------------------------
# TestTracePrFrames
# ---------------------------------------------------------------------------


class TestTracePrFrames:
    def test_pr_not_found(self) -> None:
        group = _build_group()
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "frames", "99"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_no_frames_prints_message(self) -> None:
        pr = make_pr_envelope(42)
        group = _build_group(pr=pr, pr_frames=[])
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "frames", "42"])
        assert result.exit_code == 0
        assert "No frames found" in result.output

    def test_shows_frames(self) -> None:
        pr = make_pr_envelope(42)
        frame = make_frame(outcome_status="fail")
        group = _build_group(pr=pr, pr_frames=[frame])
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "frames", "42"])
        assert result.exit_code == 0
        assert str(frame.frame_id)[:8] in result.output
        assert "FAIL" in result.output

    def test_frame_count_shown(self) -> None:
        pr = make_pr_envelope(42)
        frames = [make_frame() for _ in range(3)]
        group = _build_group(pr=pr, pr_frames=frames)
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "frames", "42"])
        assert result.exit_code == 0
        assert "3 frames" in result.output


# ---------------------------------------------------------------------------
# TestTracePrFailurePath
# ---------------------------------------------------------------------------


class TestTracePrFailurePath:
    def test_pr_not_found(self) -> None:
        group = _build_group()
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "failure-path", "99"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_no_failing_frames(self) -> None:
        pr = make_pr_envelope(42)
        frames = [make_frame(outcome_status="pass")]
        group = _build_group(pr=pr, pr_frames=frames)
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "failure-path", "42"])
        assert result.exit_code == 0
        assert "No failing frames" in result.output

    def test_fail_only_no_pass(self) -> None:
        pr = make_pr_envelope(42)
        fail_frame = make_frame(outcome_status="fail", failure_sig="TYPE_FAIL:X")
        group = _build_group(pr=pr, pr_frames=[fail_frame])
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "failure-path", "42"])
        assert result.exit_code == 0
        assert "FIRST FAILURE" in result.output
        assert "Failing frame found but no passing frame" in result.output

    def test_fail_then_pass(self) -> None:
        pr = make_pr_envelope(42)
        fail_frame = make_frame(
            outcome_status="fail",
            failure_sig="TYPE_FAIL:X",
            timestamp="2026-02-21T10:00:00Z",
            files_changed=["src/a.py"],
        )
        pass_frame = make_frame(
            outcome_status="pass",
            timestamp="2026-02-21T11:00:00Z",
            files_changed=["src/b.py"],
        )
        group = _build_group(pr=pr, pr_frames=[fail_frame, pass_frame])
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "failure-path", "42"])
        assert result.exit_code == 0
        assert "FIRST FAILURE" in result.output
        assert "FIRST PASS" in result.output
        assert "DELTA BETWEEN THEM" in result.output
        assert "src/a.py" in result.output
        assert "src/b.py" in result.output

    def test_failure_sig_shown(self) -> None:
        pr = make_pr_envelope(42)
        fail_frame = make_frame(outcome_status="fail", failure_sig="LINT_FAIL:E501")
        group = _build_group(pr=pr, pr_frames=[fail_frame])
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "failure-path", "42"])
        assert result.exit_code == 0
        assert "LINT_FAIL:E501" in result.output

    def test_diff_command_hint_shown(self) -> None:
        pr = make_pr_envelope(42)
        fail_frame = make_frame(outcome_status="fail", timestamp="2026-02-21T10:00:00Z")
        pass_frame = make_frame(outcome_status="pass", timestamp="2026-02-21T11:00:00Z")
        group = _build_group(pr=pr, pr_frames=[fail_frame, pass_frame])
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "failure-path", "42"])
        assert result.exit_code == 0
        assert "trace diff" in result.output


# ---------------------------------------------------------------------------
# TestTracePrTimeline
# ---------------------------------------------------------------------------


class TestTracePrTimeline:
    def test_pr_not_found(self) -> None:
        group = _build_group()
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "timeline", "99"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_empty_frames_shows_created(self) -> None:
        pr = make_pr_envelope(42)
        group = _build_group(pr=pr, pr_frames=[])
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "timeline", "42"])
        assert result.exit_code == 0
        assert TIMESTAMP in result.output

    def test_frames_appear_in_order(self) -> None:
        pr = make_pr_envelope(42)
        frame1 = make_frame(outcome_status="fail", timestamp="2026-02-21T10:00:00Z")
        frame2 = make_frame(outcome_status="pass", timestamp="2026-02-21T11:00:00Z")
        group = _build_group(pr=pr, pr_frames=[frame2, frame1])  # unsorted input
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "timeline", "42"])
        assert result.exit_code == 0
        idx_fail = result.output.find("2026-02-21T10:00:00Z")
        idx_pass = result.output.find("2026-02-21T11:00:00Z")
        assert idx_fail < idx_pass

    def test_ci_artifacts_shown(self) -> None:
        pr = make_pr_envelope(42)
        group = _build_group(pr=pr, pr_frames=[])
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "timeline", "42"])
        assert result.exit_code == 0
        assert "CI / tests" in result.output

    def test_merged_timestamp_shown_when_present(self) -> None:
        body = "Final"
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        pr = PREnvelope(
            pr_id=uuid4(),
            provider="github",
            repo="OmniNode-ai/omniclaude",
            pr_number=42,
            head_sha="a" * 40,
            base_sha="b" * 40,
            branch_name="feature/x",
            pr_text=ModelPRText(
                title="Merged PR",
                body_versions=[
                    ModelPRBodyVersion(
                        version=1,
                        body=body,
                        body_hash=body_hash,
                        timestamp=TIMESTAMP,
                    )
                ],
            ),
            timeline=ModelPRTimeline(
                created_at=TIMESTAMP,
                merged_at="2026-02-21T18:00:00Z",
            ),
        )
        group = _build_group(pr=pr, pr_frames=[])
        runner = CliRunner()
        result = runner.invoke(group, ["pr", "timeline", "42"])
        assert result.exit_code == 0
        assert "MERGED" in result.output
        assert "2026-02-21T18:00:00Z" in result.output
