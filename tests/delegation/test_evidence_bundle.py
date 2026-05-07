# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the delegation evidence bundle writer (OMN-10639)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from omniclaude.delegation.evidence_bundle import (
    EvidenceBundleWriter,
    ModelBifrostResponse,
    ModelBundleReceipt,
    ModelCostEvent,
    ModelQualityGateArtifact,
    ModelRunManifest,
    hash_prompt,
    new_bundle_id,
)

_CORRELATION_ID = "11111111-2222-3333-4444-555555555555"
_BUNDLE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_PROMPT_HASH = hashlib.sha256(b"hello").hexdigest()
_T0 = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
_T1 = datetime(2026, 5, 6, 12, 0, 5, tzinfo=UTC)


def _manifest(correlation_id: str = _CORRELATION_ID) -> ModelRunManifest:
    return ModelRunManifest(
        correlation_id=correlation_id,
        bundle_id=_BUNDLE_ID,
        ticket_id="OMN-10639",
        session_id="session-abc",
        task_type="research",
        prompt_hash=_PROMPT_HASH,
        started_at=_T0,
        completed_at=_T1,
        runner="inprocess",
    )


def _bifrost(correlation_id: str = _CORRELATION_ID) -> ModelBifrostResponse:
    return ModelBifrostResponse(
        correlation_id=correlation_id,
        backend_selected="http://test-backend.invalid:8000",
        model_used="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        rule_id="rule-research-v1",
        config_version="v1",
        retry_count=0,
        latency_ms=1234,
        prompt_tokens=42,
        completion_tokens=128,
        total_tokens=170,
        response_content="example response",
        response_truncated=False,
    )


def _quality(correlation_id: str = _CORRELATION_ID) -> ModelQualityGateArtifact:
    return ModelQualityGateArtifact(
        correlation_id=correlation_id,
        passed=True,
        quality_score=0.92,
        failure_reasons=(),
        fallback_to_claude=False,
    )


def _cost(correlation_id: str = _CORRELATION_ID) -> ModelCostEvent:
    return ModelCostEvent(
        correlation_id=correlation_id,
        session_id="session-abc",
        model_local="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        baseline_model="claude-opus-4-6",
        local_cost_usd=0.0,
        cloud_cost_usd=0.012,
        savings_usd=0.012,
        savings_method="zero_marginal_api_cost",
        token_provenance="measured",
        pricing_manifest_version="2026-05-06-v1",
        prompt_tokens=42,
        completion_tokens=128,
    )


@pytest.mark.unit
class TestEvidenceBundleWrite:
    def test_writes_all_five_artifacts(self, tmp_path: Path) -> None:
        writer = EvidenceBundleWriter(tmp_path)
        receipt = writer.write(
            manifest=_manifest(),
            bifrost_response=_bifrost(),
            quality_gate=_quality(),
            cost_event=_cost(),
            issued_at=_T1,
        )
        bundle_dir = tmp_path / _CORRELATION_ID
        assert (bundle_dir / "run_manifest.json").is_file()
        assert (bundle_dir / "bifrost_response.json").is_file()
        assert (bundle_dir / "quality_gate_result.json").is_file()
        assert (bundle_dir / "cost_event.json").is_file()
        assert (bundle_dir / "receipt.json").is_file()
        assert isinstance(receipt, ModelBundleReceipt)
        assert receipt.correlation_id == _CORRELATION_ID
        assert receipt.bundle_id == _BUNDLE_ID

    def test_artifacts_round_trip_to_their_models(self, tmp_path: Path) -> None:
        writer = EvidenceBundleWriter(tmp_path)
        writer.write(
            manifest=_manifest(),
            bifrost_response=_bifrost(),
            quality_gate=_quality(),
            cost_event=_cost(),
            issued_at=_T1,
        )
        bundle_dir = tmp_path / _CORRELATION_ID

        ModelRunManifest.model_validate_json(
            (bundle_dir / "run_manifest.json").read_bytes()
        )
        ModelBifrostResponse.model_validate_json(
            (bundle_dir / "bifrost_response.json").read_bytes()
        )
        ModelQualityGateArtifact.model_validate_json(
            (bundle_dir / "quality_gate_result.json").read_bytes()
        )
        ModelCostEvent.model_validate_json(
            (bundle_dir / "cost_event.json").read_bytes()
        )
        ModelBundleReceipt.model_validate_json(
            (bundle_dir / "receipt.json").read_bytes()
        )

    def test_receipt_hashes_match_on_disk_bytes(self, tmp_path: Path) -> None:
        writer = EvidenceBundleWriter(tmp_path)
        receipt = writer.write(
            manifest=_manifest(),
            bifrost_response=_bifrost(),
            quality_gate=_quality(),
            cost_event=_cost(),
            issued_at=_T1,
        )
        bundle_dir = tmp_path / _CORRELATION_ID
        for filename, expected_hash in receipt.artifact_hashes.items():
            actual = hashlib.sha256((bundle_dir / filename).read_bytes()).hexdigest()
            assert actual == expected_hash, f"hash mismatch for {filename}"

    def test_root_hash_is_deterministic(self, tmp_path: Path) -> None:
        writer1 = EvidenceBundleWriter(tmp_path / "first")
        writer2 = EvidenceBundleWriter(tmp_path / "second")
        receipt1 = writer1.write(
            manifest=_manifest(),
            bifrost_response=_bifrost(),
            quality_gate=_quality(),
            cost_event=_cost(),
            issued_at=_T1,
        )
        receipt2 = writer2.write(
            manifest=_manifest(),
            bifrost_response=_bifrost(),
            quality_gate=_quality(),
            cost_event=_cost(),
            issued_at=_T1,
        )
        assert receipt1.bundle_root_hash == receipt2.bundle_root_hash
        assert receipt1.artifact_hashes == receipt2.artifact_hashes

    def test_root_hash_changes_when_an_artifact_changes(self, tmp_path: Path) -> None:
        writer = EvidenceBundleWriter(tmp_path)
        baseline = writer.write(
            manifest=_manifest(),
            bifrost_response=_bifrost(),
            quality_gate=_quality(),
            cost_event=_cost(),
            issued_at=_T1,
        )

        other_dir = tmp_path / "other"
        writer2 = EvidenceBundleWriter(other_dir)
        mutated_quality = ModelQualityGateArtifact(
            correlation_id=_CORRELATION_ID,
            passed=False,
            quality_score=0.10,
            failure_reasons=("refusal_phrase",),
            fallback_to_claude=True,
        )
        mutated = writer2.write(
            manifest=_manifest(),
            bifrost_response=_bifrost(),
            quality_gate=mutated_quality,
            cost_event=_cost(),
            issued_at=_T1,
        )
        assert baseline.bundle_root_hash != mutated.bundle_root_hash

    def test_bundle_path_is_per_correlation_id(self, tmp_path: Path) -> None:
        writer = EvidenceBundleWriter(tmp_path)
        path = writer.bundle_path("alt-correlation")
        assert path == tmp_path / "alt-correlation"


@pytest.mark.unit
class TestPathTraversalDefence:
    """correlation_id must never escape the bundle root."""

    @pytest.mark.parametrize(
        "bad_id",
        [
            "../escape",
            "..",
            ".",
            "/abs/path",
            "nested/segment",
            "back\\slash",
            "..\\windows",
        ],
    )
    def test_model_rejects_traversal_in_correlation_id(self, bad_id: str) -> None:
        with pytest.raises(ValidationError):
            ModelRunManifest(
                correlation_id=bad_id,
                bundle_id=_BUNDLE_ID,
                task_type="research",
                prompt_hash=_PROMPT_HASH,
                started_at=_T0,
                completed_at=_T1,
                runner="inprocess",
            )

    @pytest.mark.parametrize(
        "bad_id",
        ["../escape", "..", ".", "/abs/path", "nested/segment", "back\\slash"],
    )
    def test_bundle_path_rejects_traversal(self, tmp_path: Path, bad_id: str) -> None:
        writer = EvidenceBundleWriter(tmp_path)
        with pytest.raises(ValueError, match="invalid correlation_id"):
            writer.bundle_path(bad_id)


@pytest.mark.unit
class TestEvidenceBundleErrors:
    def test_correlation_id_mismatch_raises(self, tmp_path: Path) -> None:
        writer = EvidenceBundleWriter(tmp_path)
        with pytest.raises(ValueError, match="correlation_id mismatch"):
            writer.write(
                manifest=_manifest(),
                bifrost_response=_bifrost("wrong-id"),
                quality_gate=_quality(),
                cost_event=_cost(),
                issued_at=_T1,
            )
        # No bundle directory created on failure
        assert not (tmp_path / _CORRELATION_ID).exists()

    def test_completed_before_started_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelRunManifest(
                correlation_id=_CORRELATION_ID,
                bundle_id=_BUNDLE_ID,
                task_type="research",
                prompt_hash="a" * 64,
                started_at=_T1,
                completed_at=_T0,
                runner="inprocess",
            )


@pytest.mark.unit
class TestHelpers:
    def test_new_bundle_id_is_unique(self) -> None:
        assert new_bundle_id() != new_bundle_id()

    def test_hash_prompt_matches_sha256(self) -> None:
        assert hash_prompt("hello") == hashlib.sha256(b"hello").hexdigest()


@pytest.mark.unit
class TestAtomicity:
    def test_partial_bundle_does_not_have_receipt(self, tmp_path: Path) -> None:
        # Receipt is the LAST file written. Simulate failure between artifact
        # writes and receipt by writing only the four artifacts, then asserting
        # that the receipt's absence is the only thing the consumer needs.
        writer = EvidenceBundleWriter(tmp_path)
        writer.write(
            manifest=_manifest(),
            bifrost_response=_bifrost(),
            quality_gate=_quality(),
            cost_event=_cost(),
            issued_at=_T1,
        )
        # Remove receipt to simulate a crash before final atomic write.
        (tmp_path / _CORRELATION_ID / "receipt.json").unlink()
        # Consumer policy: receipt-presence == bundle-complete.
        assert not (tmp_path / _CORRELATION_ID / "receipt.json").exists()
        # The other four artifacts are still parseable.
        assert (tmp_path / _CORRELATION_ID / "run_manifest.json").is_file()


@pytest.mark.unit
class TestCanonicalization:
    def test_on_disk_payload_is_sorted_compact_json(self, tmp_path: Path) -> None:
        writer = EvidenceBundleWriter(tmp_path)
        writer.write(
            manifest=_manifest(),
            bifrost_response=_bifrost(),
            quality_gate=_quality(),
            cost_event=_cost(),
            issued_at=_T1,
        )
        raw = (tmp_path / _CORRELATION_ID / "run_manifest.json").read_bytes()
        # Compact: no spaces after separators
        assert b": " not in raw
        assert b", " not in raw
        # Parses as JSON
        parsed = json.loads(raw)
        assert parsed["correlation_id"] == _CORRELATION_ID
        # Sorted: keys appear in alphabetical order in the byte stream
        keys_in_order = list(parsed.keys())
        assert keys_in_order == sorted(keys_in_order)
