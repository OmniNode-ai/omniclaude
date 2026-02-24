# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for QuirkType, QuirkStage, QuirkSignal, and QuirkFinding.

Tests cover:
- Enum membership and string values
- Model instantiation with required and optional fields
- Field validation (confidence bounds, evidence non-empty, ast_span ordering)
- Immutability (frozen=True enforcement)
- Serialisation round-trips (model_dump / model_validate)
- Top-level package imports (``from omniclaude.quirks import ...``)

All tests are decorated with ``@pytest.mark.unit`` per repo convention.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from omniclaude.quirks import QuirkFinding, QuirkSignal, QuirkStage, QuirkType
from omniclaude.quirks.enums import QuirkStage as _QuirkStageAlias
from omniclaude.quirks.enums import QuirkType as _QuirkTypeAlias

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal(**overrides: object) -> QuirkSignal:
    """Build a minimal valid QuirkSignal, applying any field overrides."""
    defaults: dict[str, object] = {
        "quirk_type": QuirkType.SYCOPHANCY,
        "session_id": "sess-abc123",
        "confidence": 0.85,
        "evidence": ["Agent agreed with incorrect user claim"],
        "stage": QuirkStage.WARN,
        "detected_at": datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC),
        "extraction_method": "heuristic",
    }
    defaults.update(overrides)
    return QuirkSignal(**defaults)  # type: ignore[arg-type]


def _finding(**overrides: object) -> QuirkFinding:
    """Build a minimal valid QuirkFinding, applying any field overrides."""
    defaults: dict[str, object] = {
        "quirk_type": QuirkType.SYCOPHANCY,
        "signal_id": uuid4(),
        "policy_recommendation": "warn",
        "fix_guidance": "Verify user claims before agreeing.",
        "confidence": 0.80,
    }
    defaults.update(overrides)
    return QuirkFinding(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuirkTypeEnum:
    """QuirkType has exactly 7 members with correct string values."""

    def test_all_seven_members_present(self) -> None:
        expected = {
            "SYCOPHANCY",
            "STUB_CODE",
            "NO_TESTS",
            "LOW_EFFORT_PATCH",
            "UNSAFE_ASSUMPTION",
            "IGNORED_INSTRUCTIONS",
            "HALLUCINATED_API",
        }
        actual = {m.value for m in QuirkType}
        assert actual == expected

    def test_str_enum_values_are_uppercase(self) -> None:
        for member in QuirkType:
            assert member.value == member.value.upper()

    def test_package_alias_is_same_class(self) -> None:
        assert QuirkType is _QuirkTypeAlias


@pytest.mark.unit
class TestQuirkStageEnum:
    """QuirkStage has exactly 3 members with correct string values."""

    def test_all_three_members_present(self) -> None:
        expected = {"OBSERVE", "WARN", "BLOCK"}
        actual = {m.value for m in QuirkStage}
        assert actual == expected

    def test_package_alias_is_same_class(self) -> None:
        assert QuirkStage is _QuirkStageAlias


# ---------------------------------------------------------------------------
# QuirkSignal instantiation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuirkSignalInstantiation:
    """QuirkSignal can be created with required and optional fields."""

    def test_minimal_valid_signal(self) -> None:
        sig = _signal()
        assert sig.quirk_type == QuirkType.SYCOPHANCY
        assert sig.session_id == "sess-abc123"
        assert sig.confidence == pytest.approx(0.85)
        assert sig.stage == QuirkStage.WARN
        assert sig.extraction_method == "heuristic"
        assert sig.diff_hunk is None
        assert sig.file_path is None
        assert sig.ast_span is None

    def test_quirk_id_is_uuid(self) -> None:
        sig = _signal()
        assert isinstance(sig.quirk_id, UUID)

    def test_all_extraction_methods_accepted(self) -> None:
        for method in ("regex", "AST", "heuristic", "model"):
            sig = _signal(extraction_method=method)
            assert sig.extraction_method == method

    def test_optional_fields_accepted(self) -> None:
        sig = _signal(
            diff_hunk="@@ -1,3 +1,4 @@\n+stub_fn()\n",
            file_path="src/agent/handler.py",
            ast_span=(10, 20),
        )
        assert sig.diff_hunk is not None
        assert sig.file_path == "src/agent/handler.py"
        assert sig.ast_span == (10, 20)

    def test_all_quirk_types_accepted(self) -> None:
        for qt in QuirkType:
            sig = _signal(quirk_type=qt)
            assert sig.quirk_type == qt

    def test_all_stages_accepted(self) -> None:
        for stage in QuirkStage:
            sig = _signal(stage=stage)
            assert sig.stage == stage


# ---------------------------------------------------------------------------
# QuirkSignal field validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuirkSignalValidation:
    """QuirkSignal enforces confidence bounds, non-empty evidence, ast_span order."""

    def test_confidence_at_zero_accepted(self) -> None:
        sig = _signal(confidence=0.0)
        assert sig.confidence == pytest.approx(0.0)

    def test_confidence_at_one_accepted(self) -> None:
        sig = _signal(confidence=1.0)
        assert sig.confidence == pytest.approx(1.0)

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _signal(confidence=-0.01)

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _signal(confidence=1.001)

    def test_empty_evidence_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _signal(evidence=[])

    def test_multiple_evidence_strings_accepted(self) -> None:
        sig = _signal(evidence=["line 1", "line 2", "line 3"])
        assert len(sig.evidence) == 3

    def test_ast_span_equal_start_end_accepted(self) -> None:
        sig = _signal(ast_span=(5, 5))
        assert sig.ast_span == (5, 5)

    def test_ast_span_inverted_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _signal(ast_span=(20, 5))

    def test_invalid_extraction_method_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _signal(extraction_method="unknown")


# ---------------------------------------------------------------------------
# QuirkSignal immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuirkSignalImmutability:
    """QuirkSignal is frozen — mutation must raise an error."""

    def test_mutation_raises(self) -> None:
        sig = _signal()
        with pytest.raises(Exception):  # ValidationError or TypeError from frozen model
            sig.session_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QuirkSignal serialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuirkSignalSerialisation:
    """QuirkSignal round-trips through model_dump / model_validate."""

    def test_model_dump_and_validate_roundtrip(self) -> None:
        original = _signal(
            diff_hunk="@@\n-old\n+new\n",
            file_path="src/foo.py",
            ast_span=(1, 10),
        )
        dumped = original.model_dump()
        restored = QuirkSignal.model_validate(dumped)
        assert restored == original

    def test_json_roundtrip(self) -> None:
        original = _signal()
        json_str = original.model_dump_json()
        restored = QuirkSignal.model_validate_json(json_str)
        assert restored.quirk_id == original.quirk_id
        assert restored.confidence == pytest.approx(original.confidence)


# ---------------------------------------------------------------------------
# QuirkFinding instantiation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuirkFindingInstantiation:
    """QuirkFinding can be created with required and optional fields."""

    def test_minimal_valid_finding(self) -> None:
        finding = _finding()
        assert finding.quirk_type == QuirkType.SYCOPHANCY
        assert finding.policy_recommendation == "warn"
        assert finding.fix_guidance == "Verify user claims before agreeing."
        assert finding.suggested_exemptions == []
        assert finding.validator_blueprint_id is None

    def test_finding_id_is_uuid(self) -> None:
        finding = _finding()
        assert isinstance(finding.finding_id, UUID)

    def test_all_policy_recommendations_accepted(self) -> None:
        for policy in ("observe", "warn", "block"):
            finding = _finding(policy_recommendation=policy)
            assert finding.policy_recommendation == policy

    def test_invalid_policy_recommendation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _finding(policy_recommendation="escalate")

    def test_optional_fields_accepted(self) -> None:
        finding = _finding(
            validator_blueprint_id="blueprint-v2",
            suggested_exemptions=["tests/**", "scripts/**"],
        )
        assert finding.validator_blueprint_id == "blueprint-v2"
        assert len(finding.suggested_exemptions) == 2


# ---------------------------------------------------------------------------
# QuirkFinding field validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuirkFindingValidation:
    """QuirkFinding enforces confidence bounds."""

    def test_confidence_at_zero_accepted(self) -> None:
        finding = _finding(confidence=0.0)
        assert finding.confidence == pytest.approx(0.0)

    def test_confidence_at_one_accepted(self) -> None:
        finding = _finding(confidence=1.0)
        assert finding.confidence == pytest.approx(1.0)

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _finding(confidence=-0.1)

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _finding(confidence=1.1)


# ---------------------------------------------------------------------------
# QuirkFinding immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuirkFindingImmutability:
    """QuirkFinding is frozen — mutation must raise an error."""

    def test_mutation_raises(self) -> None:
        finding = _finding()
        with pytest.raises(Exception):
            finding.fix_guidance = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QuirkFinding serialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuirkFindingSerialisation:
    """QuirkFinding round-trips through model_dump / model_validate."""

    def test_model_dump_and_validate_roundtrip(self) -> None:
        original = _finding(
            validator_blueprint_id="bp-abc",
            suggested_exemptions=["tests/"],
        )
        dumped = original.model_dump()
        restored = QuirkFinding.model_validate(dumped)
        assert restored == original

    def test_json_roundtrip(self) -> None:
        original = _finding()
        json_str = original.model_dump_json()
        restored = QuirkFinding.model_validate_json(json_str)
        assert restored.finding_id == original.finding_id


# ---------------------------------------------------------------------------
# Package-level import tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPackageImports:
    """All public types are importable from omniclaude.quirks."""

    def test_quirk_type_importable(self) -> None:
        import omniclaude.quirks as _quirks  # noqa: PLC0415

        assert _quirks.QuirkType is QuirkType

    def test_quirk_stage_importable(self) -> None:
        import omniclaude.quirks as _quirks  # noqa: PLC0415

        assert _quirks.QuirkStage is QuirkStage

    def test_quirk_signal_importable(self) -> None:
        import omniclaude.quirks as _quirks  # noqa: PLC0415

        assert _quirks.QuirkSignal is QuirkSignal

    def test_quirk_finding_importable(self) -> None:
        import omniclaude.quirks as _quirks  # noqa: PLC0415

        assert _quirks.QuirkFinding is QuirkFinding
