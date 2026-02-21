"""Unit tests for omniclaude.trace.models.

Tests cover:
- Happy path construction for each model
- Invalid inputs raise ValueError / ValidationError
- All three ChangeFrame invariant violations raise ValueError with correct messages
- Model serialization round-trip (model_dump() -> model_validate())
- Frozen model enforcement (mutation raises ValidationError / TypeError)
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from omniclaude.trace.change_frame import (
    AssociationMethod,
    ChangeFrame,
    FailureType,
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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_frame_config(**overrides: object) -> ModelFrameConfig:
    defaults: dict[str, object] = {"temperature": 0.0, "seed": 42, "max_tokens": 4096}
    defaults.update(overrides)
    return ModelFrameConfig(**defaults)  # type: ignore[arg-type]


def make_intent_ref(**overrides: object) -> ModelIntentRef:
    defaults: dict[str, object] = {
        "prompt_hash": "abc123def456" * 4,
        "ticket_id": "OMN-9999",
        "contract_hash": "deadbeef" * 8,
    }
    defaults.update(overrides)
    return ModelIntentRef(**defaults)  # type: ignore[arg-type]


def make_workspace_ref(**overrides: object) -> ModelWorkspaceRef:
    defaults: dict[str, object] = {
        "repo": "omninode/omniclaude",
        "branch": "main",
        "base_commit": "abc1234567890abcdef",
    }
    defaults.update(overrides)
    return ModelWorkspaceRef(**defaults)  # type: ignore[arg-type]


def make_delta(**overrides: object) -> ModelDelta:
    defaults: dict[str, object] = {
        "diff_patch": "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n",
        "files_changed": ["foo.py"],
        "loc_added": 1,
        "loc_removed": 1,
    }
    defaults.update(overrides)
    return ModelDelta(**defaults)  # type: ignore[arg-type]


def make_check_result(**overrides: object) -> ModelCheckResult:
    defaults: dict[str, object] = {
        "command": "pytest tests/ -v",
        "environment_hash": "envhash123",
        "exit_code": 0,
        "output_hash": "outhash456",
    }
    defaults.update(overrides)
    return ModelCheckResult(**defaults)  # type: ignore[arg-type]


def make_outcome(**overrides: object) -> ModelOutcome:
    defaults: dict[str, object] = {"status": "pass"}
    defaults.update(overrides)
    return ModelOutcome(**defaults)  # type: ignore[arg-type]


def make_change_frame(**overrides: object) -> ChangeFrame:
    defaults: dict[str, object] = {
        "frame_id": uuid.uuid4(),
        "parent_frame_id": None,
        "trace_id": "session-abc123",
        "timestamp_utc": "2026-02-19T14:22:31Z",
        "agent_id": "polymorphic-agent",
        "model_id": "claude-opus-4-6",
        "frame_config": make_frame_config(),
        "intent_ref": make_intent_ref(),
        "workspace_ref": make_workspace_ref(),
        "delta": make_delta(),
        "checks": [make_check_result()],
        "outcome": make_outcome(),
    }
    defaults.update(overrides)
    return ChangeFrame(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ModelFrameConfig tests
# ---------------------------------------------------------------------------


class TestModelFrameConfig:
    def test_happy_path(self) -> None:
        cfg = ModelFrameConfig(temperature=0.7, seed=42, max_tokens=2048)
        assert cfg.temperature == 0.7
        assert cfg.seed == 42
        assert cfg.max_tokens == 2048

    def test_all_optional_fields(self) -> None:
        cfg = ModelFrameConfig()
        assert cfg.temperature is None
        assert cfg.seed is None
        assert cfg.max_tokens is None

    def test_frozen_mutation_raises(self) -> None:
        cfg = ModelFrameConfig(temperature=0.5)
        with pytest.raises((ValidationError, TypeError)):
            cfg.temperature = 0.9  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        cfg = ModelFrameConfig(temperature=0.3, seed=7, max_tokens=1024)
        data = cfg.model_dump()
        cfg2 = ModelFrameConfig.model_validate(data)
        assert cfg == cfg2


# ---------------------------------------------------------------------------
# ModelIntentRef tests
# ---------------------------------------------------------------------------


class TestModelIntentRef:
    def test_happy_path(self) -> None:
        ref = ModelIntentRef(
            prompt_hash="abc123",
            ticket_id="OMN-1234",
            contract_hash="deadbeef",
        )
        assert ref.prompt_hash == "abc123"
        assert ref.ticket_id == "OMN-1234"

    def test_empty_prompt_hash_raises(self) -> None:
        with pytest.raises(ValidationError, match="prompt_hash must not be empty"):
            ModelIntentRef(prompt_hash="   ")

    def test_optional_fields(self) -> None:
        ref = ModelIntentRef(prompt_hash="xyz")
        assert ref.ticket_id is None
        assert ref.contract_hash is None

    def test_frozen_mutation_raises(self) -> None:
        ref = ModelIntentRef(prompt_hash="abc")
        with pytest.raises((ValidationError, TypeError)):
            ref.prompt_hash = "def"  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        ref = ModelIntentRef(prompt_hash="abc", ticket_id="OMN-1")
        data = ref.model_dump()
        ref2 = ModelIntentRef.model_validate(data)
        assert ref == ref2


# ---------------------------------------------------------------------------
# ModelWorkspaceRef tests
# ---------------------------------------------------------------------------


class TestModelWorkspaceRef:
    def test_happy_path(self) -> None:
        ref = ModelWorkspaceRef(repo="org/repo", branch="main", base_commit="abc123")
        assert ref.repo == "org/repo"
        assert ref.branch == "main"
        assert ref.base_commit == "abc123"

    def test_empty_base_commit_raises(self) -> None:
        with pytest.raises(ValidationError, match="base_commit must not be empty"):
            ModelWorkspaceRef(repo="org/repo", branch="main", base_commit="  ")

    def test_frozen_mutation_raises(self) -> None:
        ref = ModelWorkspaceRef(repo="org/repo", branch="main", base_commit="abc")
        with pytest.raises((ValidationError, TypeError)):
            ref.branch = "feature"  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        ref = ModelWorkspaceRef(repo="org/repo", branch="feat", base_commit="def456")
        data = ref.model_dump()
        ref2 = ModelWorkspaceRef.model_validate(data)
        assert ref == ref2


# ---------------------------------------------------------------------------
# ModelDelta tests
# ---------------------------------------------------------------------------


class TestModelDelta:
    def test_happy_path(self) -> None:
        delta = make_delta()
        assert "diff_patch" in delta.diff_patch or delta.diff_patch
        assert delta.loc_added == 1

    def test_negative_loc_raises(self) -> None:
        with pytest.raises(ValidationError, match="loc values must be non-negative"):
            ModelDelta(
                diff_patch="some patch",
                files_changed=[],
                loc_added=-1,
                loc_removed=0,
            )

    def test_frozen_mutation_raises(self) -> None:
        delta = make_delta()
        with pytest.raises((ValidationError, TypeError)):
            delta.loc_added = 99  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        delta = make_delta()
        data = delta.model_dump()
        delta2 = ModelDelta.model_validate(data)
        assert delta == delta2


# ---------------------------------------------------------------------------
# ModelToolEvent tests
# ---------------------------------------------------------------------------


class TestModelToolEvent:
    def test_happy_path(self) -> None:
        ev = ModelToolEvent(
            tool_name="Write",
            input_hash="ihash",
            output_hash="ohash",
            raw_pointer=None,
        )
        assert ev.tool_name == "Write"
        assert ev.raw_pointer is None

    def test_frozen_mutation_raises(self) -> None:
        ev = ModelToolEvent(tool_name="Read", input_hash="a", output_hash="b")
        with pytest.raises((ValidationError, TypeError)):
            ev.tool_name = "Edit"  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        ev = ModelToolEvent(
            tool_name="Bash",
            input_hash="x",
            output_hash="y",
            raw_pointer="s3://bucket/key",
        )
        data = ev.model_dump()
        ev2 = ModelToolEvent.model_validate(data)
        assert ev == ev2


# ---------------------------------------------------------------------------
# ModelCheckResult tests
# ---------------------------------------------------------------------------


class TestModelCheckResult:
    def test_happy_path(self) -> None:
        check = make_check_result()
        assert check.exit_code == 0
        assert check.command == "pytest tests/ -v"

    def test_failing_check(self) -> None:
        check = make_check_result(exit_code=1)
        assert check.exit_code == 1

    def test_frozen_mutation_raises(self) -> None:
        check = make_check_result()
        with pytest.raises((ValidationError, TypeError)):
            check.exit_code = 1  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        check = make_check_result(exit_code=1, truncated_output="FAILED")
        data = check.model_dump()
        check2 = ModelCheckResult.model_validate(data)
        assert check == check2


# ---------------------------------------------------------------------------
# ModelOutcome tests
# ---------------------------------------------------------------------------


class TestModelOutcome:
    def test_pass_outcome(self) -> None:
        outcome = ModelOutcome(status="pass")
        assert outcome.status == "pass"

    def test_fail_outcome(self) -> None:
        outcome = ModelOutcome(status="fail", failure_signature_id="sig123")
        assert outcome.status == "fail"
        assert outcome.failure_signature_id == "sig123"

    def test_partial_outcome(self) -> None:
        outcome = ModelOutcome(status="partial")
        assert outcome.status == "partial"

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelOutcome(status="unknown")  # type: ignore[arg-type]

    def test_frozen_mutation_raises(self) -> None:
        outcome = ModelOutcome(status="pass")
        with pytest.raises((ValidationError, TypeError)):
            outcome.status = "fail"  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        outcome = ModelOutcome(status="fail", failure_signature_id="sig999")
        data = outcome.model_dump()
        outcome2 = ModelOutcome.model_validate(data)
        assert outcome == outcome2


# ---------------------------------------------------------------------------
# ModelEvidence tests
# ---------------------------------------------------------------------------


class TestModelEvidence:
    def test_defaults(self) -> None:
        ev = ModelEvidence()
        assert ev.truncated_logs == ""
        assert ev.full_log_pointer is None

    def test_with_logs(self) -> None:
        ev = ModelEvidence(
            truncated_logs="FAILED: test_foo", full_log_pointer="s3://bucket/logs/abc"
        )
        assert ev.truncated_logs == "FAILED: test_foo"
        assert ev.full_log_pointer == "s3://bucket/logs/abc"

    def test_frozen_mutation_raises(self) -> None:
        ev = ModelEvidence(truncated_logs="log")
        with pytest.raises((ValidationError, TypeError)):
            ev.truncated_logs = "other"  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        ev = ModelEvidence(truncated_logs="abc", full_log_pointer="s3://x")
        data = ev.model_dump()
        ev2 = ModelEvidence.model_validate(data)
        assert ev == ev2


# ---------------------------------------------------------------------------
# ChangeFrame tests — happy path
# ---------------------------------------------------------------------------


class TestChangeFrameHappyPath:
    def test_minimal_valid_frame(self) -> None:
        frame = make_change_frame()
        assert frame.outcome.status == "pass"
        assert len(frame.checks) == 1

    def test_frame_with_parent(self) -> None:
        parent_id = uuid.uuid4()
        frame = make_change_frame(parent_frame_id=parent_id)
        assert frame.parent_frame_id == parent_id

    def test_frame_with_tool_events(self) -> None:
        ev = ModelToolEvent(tool_name="Write", input_hash="a", output_hash="b")
        frame = make_change_frame(tool_events=[ev])
        assert len(frame.tool_events) == 1

    def test_frame_with_fail_outcome(self) -> None:
        outcome = ModelOutcome(status="fail", failure_signature_id="sig001")
        frame = make_change_frame(
            outcome=outcome,
            checks=[make_check_result(exit_code=1)],
        )
        assert frame.outcome.status == "fail"
        assert frame.outcome.failure_signature_id == "sig001"

    def test_frame_with_multiple_checks(self) -> None:
        checks = [
            make_check_result(command="pytest"),
            make_check_result(command="ruff check"),
            make_check_result(command="mypy"),
        ]
        frame = make_change_frame(checks=checks)
        assert len(frame.checks) == 3

    def test_frozen_mutation_raises(self) -> None:
        frame = make_change_frame()
        with pytest.raises((ValidationError, TypeError)):
            frame.agent_id = "other-agent"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ChangeFrame tests — invariant violations
# ---------------------------------------------------------------------------


class TestChangeFrameInvariants:
    def test_invariant_1_empty_diff_patch_raises(self) -> None:
        """Invariant 1: delta.diff_patch must be non-empty."""
        empty_delta = make_delta(diff_patch="")
        with pytest.raises(ValidationError) as exc_info:
            make_change_frame(delta=empty_delta)
        assert "diff_patch must be non-empty" in str(exc_info.value)

    def test_invariant_1_whitespace_diff_patch_raises(self) -> None:
        """Invariant 1: whitespace-only diff_patch is also invalid."""
        whitespace_delta = make_delta(diff_patch="   \n  ")
        with pytest.raises(ValidationError) as exc_info:
            make_change_frame(delta=whitespace_delta)
        assert "diff_patch must be non-empty" in str(exc_info.value)

    def test_invariant_2_no_checks_raises(self) -> None:
        """Invariant 2: at least one check must be present."""
        with pytest.raises(ValidationError) as exc_info:
            make_change_frame(checks=[])
        assert "at least one check must be present" in str(exc_info.value)

    def test_invariant_3_invalid_outcome_status_raises(self) -> None:
        """Invariant 3: outcome.status must be a valid Literal value."""
        with pytest.raises(ValidationError):
            # ModelOutcome itself rejects invalid status via Literal type
            make_change_frame(outcome=ModelOutcome(status="unknown"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ChangeFrame serialization round-trip
# ---------------------------------------------------------------------------


class TestChangeFrameSerializationRoundTrip:
    def test_model_dump_and_validate(self) -> None:
        frame = make_change_frame()
        data = frame.model_dump()
        frame2 = ChangeFrame.model_validate(data)
        assert frame2.frame_id == frame.frame_id
        assert frame2.outcome.status == frame.outcome.status
        assert frame2.delta.diff_patch == frame.delta.diff_patch

    def test_round_trip_preserves_all_fields(self) -> None:
        frame = make_change_frame(
            tool_events=[
                ModelToolEvent(tool_name="Write", input_hash="a", output_hash="b")
            ],
            evidence=ModelEvidence(truncated_logs="log data"),
        )
        data = frame.model_dump()
        frame2 = ChangeFrame.model_validate(data)
        assert len(frame2.tool_events) == 1
        assert frame2.tool_events[0].tool_name == "Write"
        assert frame2.evidence.truncated_logs == "log data"

    def test_round_trip_with_fail_outcome(self) -> None:
        frame = make_change_frame(
            outcome=ModelOutcome(status="fail", failure_signature_id="sig-abc"),
            checks=[make_check_result(exit_code=1)],
        )
        data = frame.model_dump()
        frame2 = ChangeFrame.model_validate(data)
        assert frame2.outcome.status == "fail"
        assert frame2.outcome.failure_signature_id == "sig-abc"


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_failure_type_values(self) -> None:
        assert FailureType.TEST_FAIL.value == "test_fail"
        assert FailureType.TYPE_FAIL.value == "type_fail"
        assert FailureType.LINT_FAIL.value == "lint_fail"
        assert FailureType.BUILD_FAIL.value == "build_fail"
        assert FailureType.RUNTIME_FAIL.value == "runtime_fail"

    def test_outcome_status_values(self) -> None:
        assert OutcomeStatus.PASS.value == "pass"
        assert OutcomeStatus.FAIL.value == "fail"
        assert OutcomeStatus.PARTIAL.value == "partial"

    def test_association_method_values(self) -> None:
        assert AssociationMethod.COMMIT_ANCESTRY.value == "commit_ancestry"
        assert AssociationMethod.BRANCH_NAME.value == "branch_name"
        assert AssociationMethod.DIFF_OVERLAP.value == "diff_overlap"
        assert AssociationMethod.PATCH_HASH.value == "patch_hash"
