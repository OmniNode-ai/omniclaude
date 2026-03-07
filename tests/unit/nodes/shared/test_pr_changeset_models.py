# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for ModelPRChangeSet, ModelPROutcome, and ModelMergeGateResult (OMN-3138).

Tests verify:
- Deterministic changeset_id generation (uuid5 reproducibility)
- Schema validation (frozen, required fields, field constraints)
- ModelContractChange and ModelGateCheckResult sub-models
- Correlation field propagation across all three event models
- build_changeset_id helper

Test markers:
    @pytest.mark.unit
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

import pytest

from omniclaude.nodes.shared.models.model_merge_gate_result import (
    ModelGateCheckResult,
    ModelMergeGateResult,
)
from omniclaude.nodes.shared.models.model_pr_changeset import (
    CHANGESET_UUID_NAMESPACE,
    ModelContractChange,
    ModelPRChangeSet,
    build_changeset_id,
)
from omniclaude.nodes.shared.models.model_pr_outcome import ModelPROutcome

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC)
_RUN_ID = uuid.uuid4()
_CORRELATION_ID = uuid.uuid4()
_RUN_FINGERPRINT = "pipeline-20260307-120000-abc"
_PR_REF = "OmniNode-ai/omniclaude#247"
_REPO = "OmniNode-ai/omniclaude"
_BASE_SHA = "abc1234567890"
_HEAD_SHA = "def5678901234"


def _make_changeset(**overrides: object) -> ModelPRChangeSet:
    """Build a valid ModelPRChangeSet with sensible defaults."""
    defaults: dict[str, object] = {
        "changeset_id": build_changeset_id(_PR_REF, _BASE_SHA, _HEAD_SHA),
        "pr_number": 247,
        "pr_ref": _PR_REF,
        "repo": _REPO,
        "base_sha": _BASE_SHA,
        "head_sha": _HEAD_SHA,
        "run_id": _RUN_ID,
        "correlation_id": _CORRELATION_ID,
        "run_fingerprint": _RUN_FINGERPRINT,
        "emitted_at": _NOW,
    }
    defaults.update(overrides)
    return ModelPRChangeSet(**defaults)  # type: ignore[arg-type]


def _make_outcome(**overrides: object) -> ModelPROutcome:
    """Build a valid ModelPROutcome with sensible defaults."""
    defaults: dict[str, object] = {
        "pr_number": 247,
        "pr_ref": _PR_REF,
        "repo": _REPO,
        "outcome": "merged",
        "run_id": _RUN_ID,
        "correlation_id": _CORRELATION_ID,
        "run_fingerprint": _RUN_FINGERPRINT,
        "emitted_at": _NOW,
    }
    defaults.update(overrides)
    return ModelPROutcome(**defaults)  # type: ignore[arg-type]


def _make_gate_result(**overrides: object) -> ModelMergeGateResult:
    """Build a valid ModelMergeGateResult with sensible defaults."""
    changeset_id = build_changeset_id(_PR_REF, _BASE_SHA, _HEAD_SHA)
    defaults: dict[str, object] = {
        "changeset_id": changeset_id,
        "pr_ref": _PR_REF,
        "repo": _REPO,
        "overall_passed": True,
        "run_id": _RUN_ID,
        "correlation_id": _CORRELATION_ID,
        "run_fingerprint": _RUN_FINGERPRINT,
        "emitted_at": _NOW,
    }
    defaults.update(overrides)
    return ModelMergeGateResult(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Changeset ID determinism tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChangesetIdDeterminism:
    """Changeset ID must be deterministic for the same PR ref + SHA range."""

    def test_same_inputs_produce_same_id(self) -> None:
        """build_changeset_id with identical inputs returns the same UUID."""
        id1 = build_changeset_id(_PR_REF, _BASE_SHA, _HEAD_SHA)
        id2 = build_changeset_id(_PR_REF, _BASE_SHA, _HEAD_SHA)
        assert id1 == id2

    def test_different_head_sha_produces_different_id(self) -> None:
        """Different head_sha must produce a different changeset_id."""
        id1 = build_changeset_id(_PR_REF, _BASE_SHA, _HEAD_SHA)
        id2 = build_changeset_id(_PR_REF, _BASE_SHA, "fff9999999999")
        assert id1 != id2

    def test_different_pr_ref_produces_different_id(self) -> None:
        """Different pr_ref must produce a different changeset_id."""
        id1 = build_changeset_id(_PR_REF, _BASE_SHA, _HEAD_SHA)
        id2 = build_changeset_id("OmniNode-ai/other#99", _BASE_SHA, _HEAD_SHA)
        assert id1 != id2

    def test_uses_uuid5_with_correct_namespace(self) -> None:
        """build_changeset_id must use uuid5 with CHANGESET_UUID_NAMESPACE."""
        expected = uuid.uuid5(
            CHANGESET_UUID_NAMESPACE, f"{_PR_REF}:{_BASE_SHA}:{_HEAD_SHA}"
        )
        actual = build_changeset_id(_PR_REF, _BASE_SHA, _HEAD_SHA)
        assert actual == expected

    def test_changeset_id_is_uuid(self) -> None:
        """build_changeset_id must return a UUID instance."""
        result = build_changeset_id(_PR_REF, _BASE_SHA, _HEAD_SHA)
        assert isinstance(result, UUID)


# ---------------------------------------------------------------------------
# ModelPRChangeSet schema tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelPRChangeSet:
    """Schema and validation tests for ModelPRChangeSet."""

    def test_model_is_frozen(self) -> None:
        """ModelPRChangeSet must be frozen (immutable after creation)."""
        cs = _make_changeset()
        with pytest.raises(Exception):  # noqa: B017
            cs.pr_number = 999  # type: ignore[misc]

    def test_required_fields_present(self) -> None:
        """All required fields must be populated in a valid instance."""
        cs = _make_changeset()
        assert cs.changeset_id is not None
        assert cs.pr_number == 247
        assert cs.pr_ref == _PR_REF
        assert cs.repo == _REPO
        assert cs.base_sha == _BASE_SHA
        assert cs.head_sha == _HEAD_SHA
        assert cs.run_id == _RUN_ID
        assert cs.correlation_id == _CORRELATION_ID
        assert cs.run_fingerprint == _RUN_FINGERPRINT
        assert cs.emitted_at == _NOW

    def test_contract_changes_default_empty(self) -> None:
        """contract_changes defaults to empty list."""
        cs = _make_changeset()
        assert cs.contract_changes == []

    def test_with_contract_changes(self) -> None:
        """ModelPRChangeSet can contain ModelContractChange instances."""
        change = ModelContractChange(
            file_path="src/nodes/node_foo/contract.yaml",
            change_type="modified",
            declared_topics=["onex.evt.omniclaude.foo.v1"],
        )
        cs = _make_changeset(contract_changes=[change])
        assert len(cs.contract_changes) == 1
        assert cs.contract_changes[0].file_path == "src/nodes/node_foo/contract.yaml"
        assert cs.contract_changes[0].declared_topics == ["onex.evt.omniclaude.foo.v1"]

    def test_pr_number_must_be_positive(self) -> None:
        """pr_number must be >= 1."""
        with pytest.raises(Exception):  # noqa: B017
            _make_changeset(pr_number=0)

    def test_session_id_optional(self) -> None:
        """session_id defaults to None."""
        cs = _make_changeset()
        assert cs.session_id is None

    def test_extra_fields_ignored(self) -> None:
        """Extra fields in input data are ignored (extra='ignore')."""
        cs = _make_changeset(unknown_field="should be ignored")
        assert not hasattr(cs, "unknown_field")


# ---------------------------------------------------------------------------
# ModelContractChange tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelContractChange:
    """Schema tests for the ModelContractChange sub-model."""

    def test_valid_change_types(self) -> None:
        """All three change_type literals must be accepted."""
        for ct in ("added", "modified", "deleted"):
            change = ModelContractChange(
                file_path="contract.yaml",
                change_type=ct,  # type: ignore[arg-type]
            )
            assert change.change_type == ct

    def test_declared_topics_default_empty(self) -> None:
        """declared_topics defaults to empty list."""
        change = ModelContractChange(file_path="contract.yaml", change_type="added")
        assert change.declared_topics == []

    def test_frozen(self) -> None:
        """ModelContractChange must be frozen."""
        change = ModelContractChange(file_path="contract.yaml", change_type="added")
        with pytest.raises(Exception):  # noqa: B017
            change.file_path = "other.yaml"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ModelPROutcome tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelPROutcome:
    """Schema and validation tests for ModelPROutcome."""

    def test_model_is_frozen(self) -> None:
        """ModelPROutcome must be frozen."""
        outcome = _make_outcome()
        with pytest.raises(Exception):  # noqa: B017
            outcome.outcome = "failed"  # type: ignore[misc]

    def test_required_fields(self) -> None:
        """All required fields must be present."""
        outcome = _make_outcome()
        assert outcome.pr_number == 247
        assert outcome.outcome == "merged"
        assert outcome.run_id == _RUN_ID
        assert outcome.correlation_id == _CORRELATION_ID

    def test_valid_outcome_literals(self) -> None:
        """All outcome literals must be accepted."""
        for oc in ("merged", "reverted", "failed", "skipped"):
            outcome = _make_outcome(outcome=oc)
            assert outcome.outcome == oc

    def test_merge_sha_optional(self) -> None:
        """merge_sha defaults to None."""
        outcome = _make_outcome()
        assert outcome.merge_sha is None

    def test_with_merge_details(self) -> None:
        """ModelPROutcome can carry merge_sha and merge_method."""
        outcome = _make_outcome(
            merge_sha="abc123def456",
            merge_method="squash",
        )
        assert outcome.merge_sha == "abc123def456"
        assert outcome.merge_method == "squash"

    def test_changeset_id_optional(self) -> None:
        """changeset_id is optional (None if no changeset was emitted)."""
        outcome = _make_outcome()
        assert outcome.changeset_id is None

    def test_with_changeset_id_link(self) -> None:
        """ModelPROutcome can link back to a changeset."""
        csid = build_changeset_id(_PR_REF, _BASE_SHA, _HEAD_SHA)
        outcome = _make_outcome(changeset_id=csid)
        assert outcome.changeset_id == csid

    def test_pipeline_phase_literals(self) -> None:
        """All pipeline_phase literals must be accepted."""
        for phase in ("merge_phase3", "merge_phase4", "fix", "review"):
            outcome = _make_outcome(pipeline_phase=phase)
            assert outcome.pipeline_phase == phase


# ---------------------------------------------------------------------------
# ModelMergeGateResult tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelMergeGateResult:
    """Schema and validation tests for ModelMergeGateResult."""

    def test_model_is_frozen(self) -> None:
        """ModelMergeGateResult must be frozen."""
        gate = _make_gate_result()
        with pytest.raises(Exception):  # noqa: B017
            gate.overall_passed = False  # type: ignore[misc]

    def test_required_fields(self) -> None:
        """All required fields must be present."""
        gate = _make_gate_result()
        assert gate.changeset_id is not None
        assert gate.pr_ref == _PR_REF
        assert gate.overall_passed is True
        assert gate.run_id == _RUN_ID
        assert gate.correlation_id == _CORRELATION_ID

    def test_tier_defaults_to_a(self) -> None:
        """tier defaults to 'A'."""
        gate = _make_gate_result()
        assert gate.tier == "A"

    def test_with_check_results(self) -> None:
        """ModelMergeGateResult can contain ModelGateCheckResult instances."""
        check = ModelGateCheckResult(
            check_name="contract_schema",
            passed=True,
            severity="info",
            message="Contract schema valid",
            file_path="src/nodes/node_foo/contract.yaml",
        )
        gate = _make_gate_result(checks=[check], checks_passed=1, checks_failed=0)
        assert len(gate.checks) == 1
        assert gate.checks[0].check_name == "contract_schema"

    def test_failed_gate_result(self) -> None:
        """A failed gate result carries appropriate counts."""
        fail_check = ModelGateCheckResult(
            check_name="topic_naming",
            passed=False,
            severity="critical",
            message="Topic name does not follow ONEX convention",
        )
        gate = _make_gate_result(
            overall_passed=False,
            checks=[fail_check],
            checks_passed=0,
            checks_failed=1,
        )
        assert gate.overall_passed is False
        assert gate.checks_failed == 1


# ---------------------------------------------------------------------------
# ModelGateCheckResult tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelGateCheckResult:
    """Schema tests for ModelGateCheckResult sub-model."""

    def test_severity_literals(self) -> None:
        """All severity literals must be accepted."""
        for sev in ("critical", "major", "minor", "info"):
            check = ModelGateCheckResult(
                check_name="test",
                passed=True,
                severity=sev,  # type: ignore[arg-type]
            )
            assert check.severity == sev

    def test_frozen(self) -> None:
        """ModelGateCheckResult must be frozen."""
        check = ModelGateCheckResult(check_name="test", passed=True)
        with pytest.raises(Exception):  # noqa: B017
            check.passed = False  # type: ignore[misc]

    def test_file_path_optional(self) -> None:
        """file_path defaults to None."""
        check = ModelGateCheckResult(check_name="test", passed=True)
        assert check.file_path is None


# ---------------------------------------------------------------------------
# Correlation propagation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCorrelationPropagation:
    """All three event models must carry run_id, correlation_id, run_fingerprint."""

    def test_changeset_carries_correlation(self) -> None:
        cs = _make_changeset()
        assert cs.run_id == _RUN_ID
        assert cs.correlation_id == _CORRELATION_ID
        assert cs.run_fingerprint == _RUN_FINGERPRINT

    def test_outcome_carries_correlation(self) -> None:
        outcome = _make_outcome()
        assert outcome.run_id == _RUN_ID
        assert outcome.correlation_id == _CORRELATION_ID
        assert outcome.run_fingerprint == _RUN_FINGERPRINT

    def test_gate_result_carries_correlation(self) -> None:
        gate = _make_gate_result()
        assert gate.run_id == _RUN_ID
        assert gate.correlation_id == _CORRELATION_ID
        assert gate.run_fingerprint == _RUN_FINGERPRINT
