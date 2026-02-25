# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for NodeQuirkMemoryBridgeEffect.

Tests cover:
- First-time promotion creates a new ModelPromotedPattern
- Re-promoting same finding_id is idempotent (no duplicate evidence)
- Second distinct finding increments evidence_count and version
- Pattern key derivation is stable and correct
- process_payload with valid / malformed dicts
- get_pattern_for_finding and get_pattern_by_key
- build_pattern_key static helper

Related: OMN-2586
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from omniclaude.nodes.node_omnimemory_promotion.store_pattern_in_memory import (
    StorePatternInMemory,
)
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.memory_bridge import (
    NodeQuirkMemoryBridgeEffect,
    _derive_quirk_pattern_key,
)
from omniclaude.quirks.models import QuirkFinding


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_finding(
    quirk_type: QuirkType = QuirkType.STUB_CODE,
    policy_recommendation: str = "observe",
    confidence: float = 0.8,
    finding_id: object = None,
) -> QuirkFinding:
    """Build a synthetic QuirkFinding for testing."""
    return QuirkFinding(
        finding_id=finding_id if finding_id is not None else uuid4(),
        quirk_type=quirk_type,
        signal_id=uuid4(),
        policy_recommendation=policy_recommendation,  # type: ignore[arg-type]
        fix_guidance="Replace stub with real implementation.",
        confidence=confidence,
    )


def _make_bridge() -> tuple[NodeQuirkMemoryBridgeEffect, StorePatternInMemory]:
    store = StorePatternInMemory()
    bridge = NodeQuirkMemoryBridgeEffect(store=store)
    return bridge, store


# ---------------------------------------------------------------------------
# Pattern key derivation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_derive_quirk_pattern_key_format() -> None:
    """Pattern key must follow QUIRK:{TYPE}:{RECOMMENDATION} format."""
    finding = _make_finding(QuirkType.STUB_CODE, "observe")
    key = _derive_quirk_pattern_key(finding)
    assert key == "QUIRK:STUB_CODE:OBSERVE"


@pytest.mark.unit
def test_derive_quirk_pattern_key_all_types() -> None:
    """Pattern key includes the correct quirk type for every QuirkType."""
    for qt in QuirkType:
        finding = _make_finding(quirk_type=qt, policy_recommendation="warn")
        key = _derive_quirk_pattern_key(finding)
        assert key == f"QUIRK:{qt.value}:WARN"


@pytest.mark.unit
def test_derive_quirk_pattern_key_all_recommendations() -> None:
    """Pattern key includes the correct recommendation suffix."""
    for rec in ("observe", "warn", "block"):
        finding = _make_finding(policy_recommendation=rec)
        key = _derive_quirk_pattern_key(finding)
        assert key.endswith(f":{rec.upper()}")


@pytest.mark.unit
def test_build_pattern_key_static_helper() -> None:
    """build_pattern_key must produce the same key as _derive_quirk_pattern_key."""
    finding = _make_finding(QuirkType.NO_TESTS, "warn")
    expected = _derive_quirk_pattern_key(finding)
    actual = NodeQuirkMemoryBridgeEffect.build_pattern_key("NO_TESTS", "warn")
    assert actual == expected


# ---------------------------------------------------------------------------
# First-time promotion
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_promote_finding_creates_new_pattern() -> None:
    """First call creates a ModelPromotedPattern with evidence_count=1 version=1."""
    bridge, store = _make_bridge()
    finding = _make_finding()
    pattern = bridge.promote_finding(finding)

    assert pattern is not None
    assert pattern.evidence_count == 1
    assert pattern.version == 1
    expected_key = _derive_quirk_pattern_key(finding)
    assert pattern.pattern_key == expected_key
    assert str(finding.finding_id) in pattern.evidence_bundle_ids


@pytest.mark.unit
def test_promote_finding_pattern_stored_in_store() -> None:
    """Promoted pattern is retrievable from the store after promotion."""
    bridge, store = _make_bridge()
    finding = _make_finding()
    pattern = bridge.promote_finding(finding)
    key = _derive_quirk_pattern_key(finding)

    retrieved = store.get_by_key(key)
    assert retrieved is not None
    assert retrieved.pattern_key == pattern.pattern_key
    assert retrieved.evidence_count == 1


# ---------------------------------------------------------------------------
# Idempotency: same finding_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_promote_same_finding_twice_is_idempotent() -> None:
    """Re-promoting the same finding_id must not change evidence_count or version."""
    bridge, store = _make_bridge()
    fid = uuid4()
    finding = _make_finding(finding_id=fid)

    first = bridge.promote_finding(finding)
    second = bridge.promote_finding(finding)

    # Second call should return the same object (no mutation).
    assert second.evidence_count == 1
    assert second.version == 1
    assert len(second.evidence_bundle_ids) == 1


# ---------------------------------------------------------------------------
# Incremental promotion: distinct findings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_promote_two_distinct_findings_increments_evidence() -> None:
    """Two distinct findings for the same (quirk_type, recommendation) bump evidence_count."""
    bridge, store = _make_bridge()
    finding_a = _make_finding()
    finding_b = _make_finding()  # distinct UUID

    bridge.promote_finding(finding_a)
    pattern_b = bridge.promote_finding(finding_b)

    assert pattern_b.evidence_count == 2
    assert pattern_b.version == 2
    assert str(finding_a.finding_id) in pattern_b.evidence_bundle_ids
    assert str(finding_b.finding_id) in pattern_b.evidence_bundle_ids


@pytest.mark.unit
def test_different_quirk_types_stored_separately() -> None:
    """Findings for different quirk types create separate OmniMemory patterns."""
    bridge, store = _make_bridge()
    finding_stub = _make_finding(QuirkType.STUB_CODE, "observe")
    finding_tests = _make_finding(QuirkType.NO_TESTS, "observe")

    bridge.promote_finding(finding_stub)
    bridge.promote_finding(finding_tests)

    stub_key = _derive_quirk_pattern_key(finding_stub)
    tests_key = _derive_quirk_pattern_key(finding_tests)
    assert stub_key != tests_key

    stub_pattern = store.get_by_key(stub_key)
    tests_pattern = store.get_by_key(tests_key)

    assert stub_pattern is not None and stub_pattern.evidence_count == 1
    assert tests_pattern is not None and tests_pattern.evidence_count == 1


@pytest.mark.unit
def test_different_recommendations_stored_separately() -> None:
    """Findings for same quirk type but different recommendations have separate keys."""
    bridge, store = _make_bridge()
    observe_finding = _make_finding(QuirkType.STUB_CODE, "observe")
    warn_finding = _make_finding(QuirkType.STUB_CODE, "warn")

    bridge.promote_finding(observe_finding)
    bridge.promote_finding(warn_finding)

    obs_key = _derive_quirk_pattern_key(observe_finding)
    warn_key = _derive_quirk_pattern_key(warn_finding)
    assert obs_key != warn_key

    assert store.get_by_key(obs_key) is not None
    assert store.get_by_key(warn_key) is not None


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_pattern_for_finding_returns_none_before_promotion() -> None:
    """get_pattern_for_finding returns None when no pattern has been promoted."""
    bridge, _ = _make_bridge()
    finding = _make_finding()
    assert bridge.get_pattern_for_finding(finding) is None


@pytest.mark.unit
def test_get_pattern_for_finding_returns_pattern_after_promotion() -> None:
    """get_pattern_for_finding returns the stored pattern after promotion."""
    bridge, _ = _make_bridge()
    finding = _make_finding()
    bridge.promote_finding(finding)
    result = bridge.get_pattern_for_finding(finding)
    assert result is not None
    assert result.evidence_count == 1


@pytest.mark.unit
def test_get_pattern_by_key_returns_none_for_unknown_key() -> None:
    """get_pattern_by_key returns None for a key not yet in OmniMemory."""
    bridge, _ = _make_bridge()
    assert bridge.get_pattern_by_key("QUIRK:HALLUCINATED_API:BLOCK") is None


@pytest.mark.unit
def test_get_pattern_by_key_returns_pattern_for_known_key() -> None:
    """get_pattern_by_key returns the stored pattern for a known key."""
    bridge, _ = _make_bridge()
    finding = _make_finding(QuirkType.HALLUCINATED_API, "block")
    bridge.promote_finding(finding)
    key = NodeQuirkMemoryBridgeEffect.build_pattern_key("HALLUCINATED_API", "block")
    result = bridge.get_pattern_by_key(key)
    assert result is not None


# ---------------------------------------------------------------------------
# process_payload (Kafka consumer helper)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_process_payload_valid_finding() -> None:
    """process_payload must promote a valid QuirkFinding payload dict."""
    bridge, store = _make_bridge()
    finding = _make_finding(QuirkType.SYCOPHANCY, "warn", confidence=0.85)
    payload = {
        "finding_id": str(finding.finding_id),
        "quirk_type": finding.quirk_type.value,
        "signal_id": str(finding.signal_id),
        "policy_recommendation": finding.policy_recommendation,
        "fix_guidance": finding.fix_guidance,
        "confidence": finding.confidence,
        "suggested_exemptions": finding.suggested_exemptions,
        "validator_blueprint_id": finding.validator_blueprint_id,
    }
    result = bridge.process_payload(payload)
    assert result is not None
    assert result.evidence_count == 1


@pytest.mark.unit
def test_process_payload_malformed_returns_none() -> None:
    """process_payload must return None (not raise) for a malformed payload."""
    bridge, _ = _make_bridge()
    result = bridge.process_payload({"not": "a valid finding"})
    assert result is None


@pytest.mark.unit
def test_process_payload_empty_dict_returns_none() -> None:
    """process_payload must return None for an empty payload dict."""
    bridge, _ = _make_bridge()
    result = bridge.process_payload({})
    assert result is None
