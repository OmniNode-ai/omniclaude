"""Unit tests for the compliance result subscriber (OMN-2340).

Tests the full pipeline from raw Kafka payload → PatternAdvisory persistence:
- Payload deserialization (_parse_compliance_result)
- Violation filtering and transformation (violations_to_advisories)
- Advisory persistence (_save_advisory / process_compliance_event)
- Merge behavior (accumulate across multiple events)
- Edge cases: violated=False, empty violations, malformed payloads

All tests run without network access, Kafka, or external services.
Kafka consumer integration is not tested here — that path requires a live broker.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# sys.path: hook lib modules live outside the normal package tree
# ---------------------------------------------------------------------------

_HOOKS_LIB = (
    Path(__file__).resolve().parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))


from compliance_result_subscriber import (
    COMPLIANCE_EVALUATED_TOPIC,
    _parse_compliance_result,
    process_compliance_event,
    violations_to_advisories,
)
from pattern_advisory_formatter import (
    load_and_clear_advisories,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION_ID = "test-session-abc123"


def _make_violation(
    *,
    pattern_id: str = "pat-001",
    pattern_signature: str = "Use type hints",
    domain_id: str = "code_quality",
    confidence: float = 0.85,
    violated: bool = True,
    severity: str = "warning",
    message: str = "Type hints are missing.",
) -> dict[str, Any]:
    return {
        "pattern_id": pattern_id,
        "pattern_signature": pattern_signature,
        "domain_id": domain_id,
        "confidence": confidence,
        "violated": violated,
        "severity": severity,
        "message": message,
    }


def _make_payload(
    *,
    session_id: str = _SESSION_ID,
    violations: list[dict[str, Any]] | None = None,
    correlation_id: str = "corr-001",
    source_path: str = "/src/foo.py",
    content_sha256: str = "abc123",
    language: str = "python",
) -> bytes:
    if violations is None:
        violations = [_make_violation()]
    payload = {
        "correlation_id": correlation_id,
        "session_id": session_id,
        "source_path": source_path,
        "content_sha256": content_sha256,
        "language": language,
        "violations": violations,
    }
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Topic constant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTopicConstant:
    def test_topic_is_correct(self) -> None:
        assert (
            COMPLIANCE_EVALUATED_TOPIC
            == "onex.evt.omniintelligence.compliance-evaluated.v1"
        )


# ---------------------------------------------------------------------------
# _parse_compliance_result
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseComplianceResult:
    def test_valid_payload_returns_dict(self) -> None:
        raw = _make_payload()
        result = _parse_compliance_result(raw)
        assert result is not None
        assert isinstance(result, dict)
        assert result["session_id"] == _SESSION_ID

    def test_returns_none_on_invalid_json(self) -> None:
        assert _parse_compliance_result(b"not json {{{{") is None

    def test_returns_none_on_empty_bytes(self) -> None:
        assert _parse_compliance_result(b"") is None

    def test_returns_none_on_json_array(self) -> None:
        assert _parse_compliance_result(b"[1, 2, 3]") is None

    def test_returns_none_on_non_utf8(self) -> None:
        assert _parse_compliance_result(b"\xff\xfe") is None

    def test_violations_list_preserved(self) -> None:
        violations = [_make_violation(), _make_violation(pattern_id="pat-002")]
        raw = _make_payload(violations=violations)
        result = _parse_compliance_result(raw)
        assert result is not None
        assert len(result["violations"]) == 2


# ---------------------------------------------------------------------------
# violations_to_advisories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestViolationsToAdvisories:
    def test_violated_true_produces_advisory(self) -> None:
        violations = [_make_violation(violated=True)]
        advisories = violations_to_advisories(violations)
        assert len(advisories) == 1
        a = advisories[0]
        assert a["pattern_id"] == "pat-001"
        assert a["pattern_signature"] == "Use type hints"
        assert a["domain_id"] == "code_quality"
        assert a["confidence"] == pytest.approx(0.85)
        assert a["status"] == "validated"
        assert a["message"] == "Type hints are missing."

    def test_violated_false_excluded(self) -> None:
        violations = [_make_violation(violated=False)]
        advisories = violations_to_advisories(violations)
        assert advisories == []

    def test_mixed_violations_filters_correctly(self) -> None:
        violations = [
            _make_violation(pattern_id="p1", violated=True),
            _make_violation(pattern_id="p2", violated=False),
            _make_violation(pattern_id="p3", violated=True),
        ]
        advisories = violations_to_advisories(violations)
        assert len(advisories) == 2
        ids = {a["pattern_id"] for a in advisories}
        assert ids == {"p1", "p3"}

    def test_empty_violations_returns_empty(self) -> None:
        assert violations_to_advisories([]) == []

    def test_status_is_always_validated(self) -> None:
        violations = [_make_violation(violated=True)]
        advisories = violations_to_advisories(violations)
        assert advisories[0]["status"] == "validated"

    def test_confidence_clamped_to_range(self) -> None:
        violations = [_make_violation(violated=True, confidence=1.5)]
        advisories = violations_to_advisories(violations)
        assert advisories[0]["confidence"] <= 1.0

    def test_confidence_nan_becomes_zero(self) -> None:
        violations = [_make_violation(violated=True)]
        violations[0]["confidence"] = float("nan")
        advisories = violations_to_advisories(violations)
        assert advisories[0]["confidence"] == 0.0

    def test_confidence_inf_becomes_zero(self) -> None:
        violations = [_make_violation(violated=True)]
        violations[0]["confidence"] = float("inf")
        advisories = violations_to_advisories(violations)
        assert advisories[0]["confidence"] == 0.0

    def test_entry_without_pattern_id_and_signature_skipped(self) -> None:
        violations = [
            {
                "violated": True,
                "pattern_id": "",
                "pattern_signature": "",
                "confidence": 0.8,
            }
        ]
        advisories = violations_to_advisories(violations)
        assert advisories == []

    def test_entry_with_only_pattern_id_included(self) -> None:
        violations = [
            {
                "violated": True,
                "pattern_id": "only-id",
                "pattern_signature": "",
                "domain_id": "",
                "confidence": 0.7,
                "message": "",
            }
        ]
        advisories = violations_to_advisories(violations)
        assert len(advisories) == 1
        assert advisories[0]["pattern_id"] == "only-id"

    def test_entry_with_only_pattern_signature_included(self) -> None:
        violations = [
            {
                "violated": True,
                "pattern_id": "",
                "pattern_signature": "Only-Sig",
                "domain_id": "",
                "confidence": 0.7,
                "message": "",
            }
        ]
        advisories = violations_to_advisories(violations)
        assert len(advisories) == 1
        assert advisories[0]["pattern_signature"] == "Only-Sig"

    def test_non_dict_entry_skipped_silently(self) -> None:
        violations: list[Any] = ["not-a-dict", None, 42, _make_violation(violated=True)]
        advisories = violations_to_advisories(violations)
        assert len(advisories) == 1

    def test_multiple_violated_all_returned(self) -> None:
        violations = [
            _make_violation(pattern_id=f"p-{i}", violated=True) for i in range(5)
        ]
        advisories = violations_to_advisories(violations)
        assert len(advisories) == 5


# ---------------------------------------------------------------------------
# process_compliance_event: valid payload → advisories written
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessComplianceEventValid:
    def test_valid_payload_writes_advisory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        raw = _make_payload(session_id="session-valid")
        result = process_compliance_event(raw)

        assert result is True
        loaded = load_and_clear_advisories("session-valid")
        assert len(loaded) == 1
        assert loaded[0]["pattern_id"] == "pat-001"
        assert loaded[0]["status"] == "validated"

    def test_multiple_violated_all_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        violations = [
            _make_violation(pattern_id="p1", violated=True),
            _make_violation(pattern_id="p2", violated=True),
        ]
        raw = _make_payload(session_id="session-multi", violations=violations)
        process_compliance_event(raw)

        loaded = load_and_clear_advisories("session-multi")
        ids = {a["pattern_id"] for a in loaded}
        assert ids == {"p1", "p2"}


# ---------------------------------------------------------------------------
# process_compliance_event: violated=False → not written
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessComplianceEventViolatedFalse:
    def test_no_violated_entries_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        violations = [
            _make_violation(violated=False),
            _make_violation(violated=False, pattern_id="p2"),
        ]
        raw = _make_payload(session_id="session-clean", violations=violations)
        result = process_compliance_event(raw)

        assert result is False
        loaded = load_and_clear_advisories("session-clean")
        assert loaded == []

    def test_mixed_only_violated_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        violations = [
            _make_violation(pattern_id="p1", violated=False),
            _make_violation(pattern_id="p2", violated=True),
        ]
        raw = _make_payload(session_id="session-mixed", violations=violations)
        process_compliance_event(raw)

        loaded = load_and_clear_advisories("session-mixed")
        assert len(loaded) == 1
        assert loaded[0]["pattern_id"] == "p2"


# ---------------------------------------------------------------------------
# process_compliance_event: merge behavior across multiple events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessComplianceEventMerge:
    def test_second_event_merges_with_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        # First event: file A violations
        raw_a = _make_payload(
            session_id="session-merge",
            violations=[_make_violation(pattern_id="p1")],
        )
        process_compliance_event(raw_a)

        # Second event: file B violations (different file, same session)
        raw_b = _make_payload(
            session_id="session-merge",
            violations=[_make_violation(pattern_id="p2")],
        )
        process_compliance_event(raw_b)

        loaded = load_and_clear_advisories("session-merge")
        ids = {a["pattern_id"] for a in loaded}
        assert ids == {"p1", "p2"}

    def test_duplicate_pattern_ids_deduplicated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        sid = "session-dedup"
        raw = _make_payload(
            session_id=sid, violations=[_make_violation(pattern_id="same")]
        )
        process_compliance_event(raw)
        process_compliance_event(raw)  # Same pattern a second time

        loaded = load_and_clear_advisories(sid)
        assert len(loaded) == 1
        assert loaded[0]["pattern_id"] == "same"

    def test_different_sessions_independent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        raw_a = _make_payload(
            session_id="sess-A",
            violations=[_make_violation(pattern_id="pA")],
        )
        raw_b = _make_payload(
            session_id="sess-B",
            violations=[_make_violation(pattern_id="pB")],
        )
        process_compliance_event(raw_a)
        process_compliance_event(raw_b)

        loaded_a = load_and_clear_advisories("sess-A")
        loaded_b = load_and_clear_advisories("sess-B")

        assert len(loaded_a) == 1
        assert loaded_a[0]["pattern_id"] == "pA"
        assert len(loaded_b) == 1
        assert loaded_b[0]["pattern_id"] == "pB"


# ---------------------------------------------------------------------------
# process_compliance_event: malformed/edge-case payloads
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessComplianceEventEdgeCases:
    def test_malformed_json_returns_false(self) -> None:
        result = process_compliance_event(b"not valid json")
        assert result is False

    def test_empty_bytes_returns_false(self) -> None:
        result = process_compliance_event(b"")
        assert result is False

    def test_missing_session_id_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        payload = json.dumps({"violations": [_make_violation()]}).encode()
        result = process_compliance_event(payload)
        assert result is False

    def test_empty_session_id_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        raw = _make_payload(session_id="")
        result = process_compliance_event(raw)
        assert result is False

    def test_empty_violations_list_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        raw = _make_payload(violations=[])
        result = process_compliance_event(raw)
        assert result is False

    def test_violations_not_list_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        payload = json.dumps({"session_id": "s1", "violations": "not-a-list"}).encode()
        result = process_compliance_event(payload)
        assert result is False

    def test_json_array_payload_returns_false(self) -> None:
        result = process_compliance_event(b"[1, 2, 3]")
        assert result is False


# ---------------------------------------------------------------------------
# get_advisory_context picks up advisories without modification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAdvisoryContextIntegration:
    """Verify that UserPromptSubmit-style get_advisory_context() picks up
    advisories written by the compliance subscriber without any modification
    to the existing advisory formatter (DoD: verify no changes needed)."""

    def test_advisory_context_contains_subscriber_advisories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Advisories written by subscriber are picked up by get_advisory_context."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        # Add lib dir so pattern_advisory_formatter is importable
        lib_dir = str(_HOOKS_LIB)
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)

        from pattern_advisory_formatter import get_advisory_context  # noqa: PLC0415

        raw = _make_payload(
            session_id="session-ctx",
            violations=[
                _make_violation(
                    pattern_id="p-ctx",
                    pattern_signature="Use type hints",
                    violated=True,
                    confidence=0.9,
                    message="Annotate return types.",
                )
            ],
        )
        process_compliance_event(raw)

        context = get_advisory_context("session-ctx")

        assert "## Pattern Advisory" in context
        assert "Use type hints" in context
        assert "90% confidence" in context

    def test_advisory_context_empty_when_no_violations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No violations written → get_advisory_context returns empty string."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        lib_dir = str(_HOOKS_LIB)
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)

        from pattern_advisory_formatter import get_advisory_context  # noqa: PLC0415

        raw = _make_payload(
            session_id="session-empty-ctx",
            violations=[_make_violation(violated=False)],
        )
        process_compliance_event(raw)

        context = get_advisory_context("session-empty-ctx")
        assert context == ""
