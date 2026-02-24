# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the deterministic replay engine.

Tests:
- ReplayMode enum values
- ReplayResult model (frozen, fields)
- load_frame_from_jsonl (hit, miss, malformed)
- _clone_repo_to_tempdir (mocked subprocess)
- _checkout_commit (mocked subprocess)
- _apply_patch (mocked subprocess)
- _classify_outcome
- _detect_divergence_reason
- ReplayEngine.replay — FULL, STUBBED, TEST_ONLY modes (mocked workspace)
- ReplayEngine.replay — workspace setup failure path
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

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
    OutcomeStatus,
)
from omniclaude.trace.replay_engine import (
    REASON_ENV_CHANGED,
    REASON_STUBBED_UNKNOWN,
    REASON_UNKNOWN,
    ReplayEngine,
    ReplayMode,
    ReplayResult,
    _apply_patch,
    _checkout_commit,
    _classify_outcome,
    _clone_repo_to_tempdir,
    _detect_divergence_reason,
    load_frame_from_jsonl,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TIMESTAMP = "2026-02-21T12:00:00Z"

DIFF_PATCH = """\
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,1 +1,2 @@
 original_line = True
+new_line = True
"""


def make_check_result(
    exit_code: int = 0,
    command: str = "ruff check src/",
    env_hash: str = "abc123",
) -> ModelCheckResult:
    from omniclaude.trace.frame_assembler import sha256_of

    return ModelCheckResult(
        command=command,
        environment_hash=env_hash,
        exit_code=exit_code,
        output_hash=sha256_of("output"),
        truncated_output="",
    )


def make_change_frame(
    outcome_status: str = "pass",
    check_results: list[ModelCheckResult] | None = None,
) -> ChangeFrame:
    from omniclaude.trace.frame_assembler import sha256_of

    if check_results is None:
        check_results = [make_check_result(exit_code=0)]

    return ChangeFrame(
        frame_id=uuid4(),
        parent_frame_id=None,
        trace_id="trace-001",
        timestamp_utc=TIMESTAMP,
        agent_id="agent-test",
        model_id="claude-sonnet-4-5",
        frame_config=ModelFrameConfig(),
        intent_ref=ModelIntentRef(prompt_hash=sha256_of("test prompt")),
        workspace_ref=ModelWorkspaceRef(
            repo="OmniNode-ai/omniclaude",
            branch="feature/test",
            base_commit="abc" + "0" * 37,
        ),
        delta=ModelDelta(
            diff_patch=DIFF_PATCH,
            files_changed=["src/foo.py"],
            loc_added=1,
            loc_removed=0,
        ),
        tool_events=[
            ModelToolEvent(
                tool_name="Write",
                input_hash=sha256_of("input"),
                output_hash=sha256_of("output"),
                raw_pointer=None,
            )
        ],
        checks=check_results,
        outcome=ModelOutcome(status=outcome_status),  # type: ignore[arg-type]
        evidence=ModelEvidence(),
    )


# ---------------------------------------------------------------------------
# ReplayMode tests
# ---------------------------------------------------------------------------


class TestReplayMode:
    def test_values(self) -> None:
        assert ReplayMode.FULL == "full"
        assert ReplayMode.STUBBED == "stubbed"
        assert ReplayMode.TEST_ONLY == "test_only"

    def test_is_str_enum(self) -> None:
        assert isinstance(ReplayMode.FULL, str)


# ---------------------------------------------------------------------------
# ReplayResult tests
# ---------------------------------------------------------------------------


class TestReplayResult:
    def test_valid_result(self) -> None:
        frame = make_change_frame()
        result = ReplayResult(
            frame_id=frame.frame_id,
            mode=ReplayMode.TEST_ONLY,
            original_outcome=OutcomeStatus.PASS,
            replayed_outcome=OutcomeStatus.PASS,
            diverged=False,
            divergence_reason=None,
            check_results=[make_check_result()],
            duration_seconds=0.5,
        )
        assert result.diverged is False
        assert result.divergence_reason is None

    def test_is_frozen(self) -> None:
        frame = make_change_frame()
        result = ReplayResult(
            frame_id=frame.frame_id,
            mode=ReplayMode.FULL,
            original_outcome=OutcomeStatus.PASS,
            replayed_outcome=OutcomeStatus.FAIL,
            diverged=True,
            divergence_reason=REASON_UNKNOWN,
            check_results=[],
            duration_seconds=1.0,
        )
        with pytest.raises(Exception):
            result.diverged = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# load_frame_from_jsonl tests
# ---------------------------------------------------------------------------


class TestLoadFrameFromJsonl:
    def test_finds_frame_by_id(self) -> None:
        frame = make_change_frame()
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_dir = Path(tmpdir)
            session_id = "test-session-123"
            jsonl_path = trace_dir / f"{session_id}.jsonl"
            jsonl_path.write_text(frame.model_dump_json() + "\n")

            result = load_frame_from_jsonl(session_id, frame.frame_id, trace_dir)
            assert result is not None
            assert result.frame_id == frame.frame_id

    def test_returns_none_when_frame_not_found(self) -> None:
        frame = make_change_frame()
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_dir = Path(tmpdir)
            session_id = "test-session-456"
            jsonl_path = trace_dir / f"{session_id}.jsonl"
            jsonl_path.write_text(frame.model_dump_json() + "\n")

            other_id = uuid4()
            result = load_frame_from_jsonl(session_id, other_id, trace_dir)
            assert result is None

    def test_returns_none_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_dir = Path(tmpdir)
            result = load_frame_from_jsonl("no-such-session", uuid4(), trace_dir)
            assert result is None

    def test_skips_malformed_lines(self) -> None:
        frame = make_change_frame()
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_dir = Path(tmpdir)
            session_id = "test-session-789"
            jsonl_path = trace_dir / f"{session_id}.jsonl"
            # Write a malformed line followed by a valid frame
            jsonl_path.write_text("not valid json\n" + frame.model_dump_json() + "\n")
            result = load_frame_from_jsonl(session_id, frame.frame_id, trace_dir)
            assert result is not None

    def test_multiple_frames_finds_correct_one(self) -> None:
        frame1 = make_change_frame()
        frame2 = make_change_frame()
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_dir = Path(tmpdir)
            session_id = "multi-session"
            jsonl_path = trace_dir / f"{session_id}.jsonl"
            jsonl_path.write_text(
                frame1.model_dump_json() + "\n" + frame2.model_dump_json() + "\n"
            )
            result = load_frame_from_jsonl(session_id, frame2.frame_id, trace_dir)
            assert result is not None
            assert result.frame_id == frame2.frame_id


# ---------------------------------------------------------------------------
# _clone_repo_to_tempdir tests
# ---------------------------------------------------------------------------


class TestCloneRepoToTempdir:
    def test_returns_true_on_success(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = _clone_repo_to_tempdir("/repo", "/tmpdir")
            assert result is True
            mock_run.assert_called_once()

    def test_returns_false_on_failure(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            result = _clone_repo_to_tempdir("/repo", "/tmpdir")
            assert result is False

    def test_returns_false_on_exception(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = _clone_repo_to_tempdir("/repo", "/tmpdir")
            assert result is False


# ---------------------------------------------------------------------------
# _checkout_commit tests
# ---------------------------------------------------------------------------


class TestCheckoutCommit:
    def test_returns_true_on_success(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            result = _checkout_commit("abc123", "/tmpdir")
            assert result is True

    def test_returns_false_on_failure(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 128
        with patch("subprocess.run", return_value=mock_result):
            result = _checkout_commit("invalid", "/tmpdir")
            assert result is False


# ---------------------------------------------------------------------------
# _apply_patch tests
# ---------------------------------------------------------------------------


class TestApplyPatch:
    def test_returns_true_on_success(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("subprocess.run", return_value=mock_result):
                result = _apply_patch(DIFF_PATCH, tmpdir)
                assert result is True

    def test_returns_false_on_failure(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("subprocess.run", return_value=mock_result):
                result = _apply_patch(DIFF_PATCH, tmpdir)
                assert result is False

    def test_cleans_up_patch_file(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("subprocess.run", return_value=mock_result):
                _apply_patch(DIFF_PATCH, tmpdir)
            # Patch file should be deleted
            assert not (Path(tmpdir) / "_replay.patch").exists()


# ---------------------------------------------------------------------------
# _classify_outcome tests
# ---------------------------------------------------------------------------


class TestClassifyOutcome:
    def test_all_pass(self) -> None:
        checks = [make_check_result(0), make_check_result(0)]
        assert _classify_outcome(checks) == OutcomeStatus.PASS

    def test_all_fail(self) -> None:
        checks = [make_check_result(1), make_check_result(1)]
        assert _classify_outcome(checks) == OutcomeStatus.FAIL

    def test_mixed(self) -> None:
        checks = [make_check_result(0), make_check_result(1)]
        assert _classify_outcome(checks) == OutcomeStatus.PARTIAL

    def test_empty_is_fail(self) -> None:
        assert _classify_outcome([]) == OutcomeStatus.FAIL


# ---------------------------------------------------------------------------
# _detect_divergence_reason tests
# ---------------------------------------------------------------------------


class TestDetectDivergenceReason:
    def test_env_changed_when_hash_differs(self) -> None:
        frame = make_change_frame(
            check_results=[make_check_result(env_hash="original-hash")]
        )
        replayed = [make_check_result(env_hash="different-hash")]
        reason = _detect_divergence_reason(frame, replayed, ReplayMode.FULL)
        assert reason == REASON_ENV_CHANGED

    def test_stubbed_unknown_in_stubbed_mode(self) -> None:
        """STUBBED mode with matching env hashes returns REASON_STUBBED_UNKNOWN.

        Tools are not re-run in STUBBED mode so non-determinism cannot be
        confirmed — the reason accurately reflects unknown divergence.
        """
        frame = make_change_frame(
            check_results=[make_check_result(env_hash="same-hash")]
        )
        replayed = [make_check_result(env_hash="same-hash")]
        reason = _detect_divergence_reason(frame, replayed, ReplayMode.STUBBED)
        assert reason == REASON_STUBBED_UNKNOWN

    def test_unknown_in_full_mode(self) -> None:
        frame = make_change_frame(
            check_results=[make_check_result(env_hash="same-hash")]
        )
        replayed = [make_check_result(env_hash="same-hash")]
        reason = _detect_divergence_reason(frame, replayed, ReplayMode.FULL)
        assert reason == REASON_UNKNOWN


# ---------------------------------------------------------------------------
# ReplayEngine tests (with mocked workspace setup)
# ---------------------------------------------------------------------------


def _mock_successful_workspace(mock_run: MagicMock) -> None:
    """Configure mock_run to simulate successful workspace setup."""
    success = MagicMock()
    success.returncode = 0
    success.stdout = ""
    success.stderr = ""
    mock_run.return_value = success


class TestReplayEngine:
    """Tests for ReplayEngine.replay() in all three modes."""

    def _make_engine(self) -> ReplayEngine:
        return ReplayEngine(repo_root="/fake/repo")

    def test_test_only_mode_pass(self) -> None:
        """TEST_ONLY: all checks pass → outcome matches original."""
        engine = self._make_engine()
        frame = make_change_frame(outcome_status="pass")

        # Mock: clone, checkout, apply all succeed; checks return exit_code=0
        def fake_subprocess(*args: object, **kwargs: object) -> MagicMock:
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_subprocess):
            result = engine.replay(frame, mode=ReplayMode.TEST_ONLY)

        assert result.mode == ReplayMode.TEST_ONLY
        assert result.frame_id == frame.frame_id
        assert not result.diverged
        assert result.duration_seconds >= 0.0

    def test_test_only_mode_diverged(self) -> None:
        """TEST_ONLY: all checks fail → diverged from original 'pass'."""
        engine = self._make_engine()
        frame = make_change_frame(outcome_status="pass")

        call_count = 0

        def fake_subprocess(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            # First 3 calls: clone, checkout, apply (succeed)
            # Subsequent calls (checks): fail
            m.returncode = 0 if call_count <= 3 else 1
            m.stdout = "error output" if call_count > 3 else ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_subprocess):
            result = engine.replay(frame, mode=ReplayMode.TEST_ONLY)

        assert result.diverged

    def test_workspace_clone_failure(self) -> None:
        """Workspace clone failure → FAIL outcome with env_changed reason."""
        engine = self._make_engine()
        frame = make_change_frame(outcome_status="pass")

        fail_result = MagicMock()
        fail_result.returncode = 1
        fail_result.stdout = ""
        fail_result.stderr = "clone failed"

        with patch("subprocess.run", return_value=fail_result):
            result = engine.replay(frame, mode=ReplayMode.TEST_ONLY)

        assert result.replayed_outcome == OutcomeStatus.FAIL
        assert result.divergence_reason == REASON_ENV_CHANGED
        assert result.diverged is True

    def test_full_mode_raises_not_implemented(self) -> None:
        """FULL mode raises NotImplementedError until live tool re-execution is built."""
        engine = self._make_engine()
        frame = make_change_frame(outcome_status="pass")

        def fake_subprocess(*args: object, **kwargs: object) -> MagicMock:
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_subprocess):
            with pytest.raises(NotImplementedError, match="FULL replay mode"):
                engine.replay(frame, mode=ReplayMode.FULL)

    def test_stubbed_mode(self) -> None:
        """STUBBED mode: workspace succeeds and checks pass → no divergence."""
        engine = self._make_engine()
        frame = make_change_frame(outcome_status="pass")

        def fake_subprocess(*args: object, **kwargs: object) -> MagicMock:
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_subprocess):
            result = engine.replay(frame, mode=ReplayMode.STUBBED)

        assert result.mode == ReplayMode.STUBBED
        assert not result.diverged

    def test_unknown_commit_skips_checkout(self) -> None:
        """Frame with base_commit='unknown' skips checkout step."""
        from omniclaude.trace.frame_assembler import sha256_of

        frame = ChangeFrame(
            frame_id=uuid4(),
            parent_frame_id=None,
            trace_id="trace-001",
            timestamp_utc=TIMESTAMP,
            agent_id="agent-test",
            model_id="claude-sonnet-4-5",
            frame_config=ModelFrameConfig(),
            intent_ref=ModelIntentRef(prompt_hash=sha256_of("test prompt")),
            workspace_ref=ModelWorkspaceRef(
                repo="OmniNode-ai/omniclaude",
                branch="main",
                base_commit="unknown",  # This skips checkout
            ),
            delta=ModelDelta(
                diff_patch=DIFF_PATCH,
                files_changed=["src/foo.py"],
                loc_added=1,
                loc_removed=0,
            ),
            tool_events=[
                ModelToolEvent(
                    tool_name="Write",
                    input_hash=sha256_of("input"),
                    output_hash=sha256_of("output"),
                    raw_pointer=None,
                )
            ],
            checks=[make_check_result(exit_code=0)],
            outcome=ModelOutcome(status="pass"),
            evidence=ModelEvidence(),
        )

        engine = self._make_engine()

        def fake_subprocess(*args: object, **kwargs: object) -> MagicMock:
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_subprocess):
            result = engine.replay(frame, mode=ReplayMode.TEST_ONLY)

        # Should complete without error even with "unknown" base_commit
        assert result.frame_id == frame.frame_id

    def test_result_has_check_results(self) -> None:
        """Replay result includes check_results from the replay run."""
        engine = self._make_engine()
        frame = make_change_frame(outcome_status="pass")

        def fake_subprocess(*args: object, **kwargs: object) -> MagicMock:
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_subprocess):
            result = engine.replay(frame, mode=ReplayMode.TEST_ONLY)

        # Check results come from the actual run_checks call
        assert isinstance(result.check_results, list)
