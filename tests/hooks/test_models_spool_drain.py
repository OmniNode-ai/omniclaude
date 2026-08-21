# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the hook-event spool-drain contract models (OMN-16090)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.hooks.models_spool_drain import (
    ModelCapturedHookEvent,
    ModelDrainBatchResult,
    ModelDrainSummary,
    ModelHookEventCaptureBatch,
    ModelSpoolRecord,
    canonical_sha_input,
)

pytestmark = pytest.mark.unit

VALID_SHA = "a" * 64


class TestModelSpoolRecord:
    def test_minimal_valid_record(self) -> None:
        record = ModelSpoolRecord.model_validate(
            {"event_type": "artifact.captured", "payload": {"x": 1}}
        )
        assert record.event_type == "artifact.captured"
        assert record.payload == {"x": 1}
        assert record.spooled_at_utc is None
        assert record.spool_reason is None

    def test_ignores_extra_fields(self) -> None:
        record = ModelSpoolRecord.model_validate(
            {
                "event_type": "artifact.captured",
                "payload": {},
                "spooled_at_utc": "2026-06-28T17:25:25.517566+00:00",
                "spool_reason": "FileNotFoundError: nope",
                "future_field": "should not raise",
            }
        )
        assert record.spool_reason == "FileNotFoundError: nope"

    def test_missing_event_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            ModelSpoolRecord.model_validate({"payload": {}})


class TestModelCapturedHookEvent:
    def _valid_kwargs(self) -> dict[str, str]:
        return {
            "event_type": "artifact.captured",
            "event_sha": VALID_SHA,
            "occurred_at": "2026-06-28T17:25:25.517566Z",
            "payload_json": '{"a":1}',
        }

    def test_valid_event(self) -> None:
        event = ModelCapturedHookEvent.model_validate(self._valid_kwargs())
        assert event.event_sha == VALID_SHA

    def test_rejects_malformed_sha(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["event_sha"] = "not-a-sha"
        with pytest.raises(ValidationError):
            ModelCapturedHookEvent.model_validate(kwargs)

    def test_rejects_uppercase_sha(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["event_sha"] = "A" * 64
        with pytest.raises(ValidationError):
            ModelCapturedHookEvent.model_validate(kwargs)

    @pytest.mark.parametrize("bad_type", ["", "AB", "Upper.Case", "no spaces allowed"])
    def test_rejects_malformed_event_type(self, bad_type: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs["event_type"] = bad_type
        with pytest.raises(ValidationError):
            ModelCapturedHookEvent.model_validate(kwargs)

    def test_accepts_bare_dotted_and_topic_shaped_types(self) -> None:
        for event_type in ("artifact.captured", "onex.evt.omniclaude.skill-started.v1"):
            kwargs = self._valid_kwargs()
            kwargs["event_type"] = event_type
            ModelCapturedHookEvent.model_validate(kwargs)

    def test_optional_fields_default_none(self) -> None:
        event = ModelCapturedHookEvent.model_validate(self._valid_kwargs())
        assert event.event_id is None
        assert event.spool_reason is None

    def test_rejects_extra_field(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["unexpected"] = "nope"  # type: ignore[assignment]
        with pytest.raises(ValidationError):
            ModelCapturedHookEvent.model_validate(kwargs)


class TestModelHookEventCaptureBatch:
    def _event(self) -> ModelCapturedHookEvent:
        return ModelCapturedHookEvent.model_validate(
            {
                "event_type": "artifact.captured",
                "event_sha": VALID_SHA,
                "occurred_at": "2026-06-28T17:25:25.517566Z",
                "payload_json": '{"a":1}',
            }
        )

    def test_valid_batch(self) -> None:
        batch = ModelHookEventCaptureBatch(
            source="local_macos_claude_hooks",
            batch_sha=VALID_SHA,
            events=[self._event()],
        )
        assert batch.events[0].event_sha == VALID_SHA

    def test_rejects_empty_events(self) -> None:
        with pytest.raises(ValidationError):
            ModelHookEventCaptureBatch(
                source="local_macos_claude_hooks", batch_sha=VALID_SHA, events=[]
            )

    def test_rejects_bad_source(self) -> None:
        with pytest.raises(ValidationError):
            ModelHookEventCaptureBatch(
                source="AB", batch_sha=VALID_SHA, events=[self._event()]
            )

    def test_to_workflow_request_shape(self) -> None:
        batch = ModelHookEventCaptureBatch(
            source="local_macos_claude_hooks",
            batch_sha=VALID_SHA,
            events=[self._event()],
        )
        request = batch.to_workflow_request()
        assert request["workflow_type"] == "hook-event-capture"
        assert request["payload"]["source"] == "local_macos_claude_hooks"
        assert request["payload"]["batch_sha"] == VALID_SHA
        assert len(request["payload"]["events"]) == 1


class TestModelDrainSummaryHadFailures:
    def test_dry_run_never_reports_failures(self) -> None:
        summary = ModelDrainSummary(
            dry_run=True,
            files_present=1,
            files_considered=1,
            unique_events=1,
            duplicate_files_collapsed=0,
            batches=[
                ModelDrainBatchResult(
                    batch_sha="a" * 64, event_count=1, confirmed=False, status="dry_run"
                )
            ],
        )
        assert summary.had_failures is False

    def test_live_run_reports_unconfirmed_batch_as_failure(self) -> None:
        summary = ModelDrainSummary(
            dry_run=False,
            files_present=1,
            files_considered=1,
            unique_events=1,
            duplicate_files_collapsed=0,
            batches=[
                ModelDrainBatchResult(
                    batch_sha="a" * 64,
                    event_count=1,
                    confirmed=False,
                    status="submit_failed",
                )
            ],
        )
        assert summary.had_failures is True

    def test_live_run_all_confirmed_has_no_failures(self) -> None:
        summary = ModelDrainSummary(
            dry_run=False,
            files_present=1,
            files_considered=1,
            unique_events=1,
            duplicate_files_collapsed=0,
            batches=[
                ModelDrainBatchResult(
                    batch_sha="a" * 64,
                    event_count=1,
                    confirmed=True,
                    status="completed",
                )
            ],
        )
        assert summary.had_failures is False


class TestCanonicalShaInput:
    def test_deterministic_regardless_of_dict_key_order(self) -> None:
        a = canonical_sha_input(
            "artifact.captured", {"z": 1, "a": 2}, "2026-01-01T00:00:00Z"
        )
        b = canonical_sha_input(
            "artifact.captured", {"a": 2, "z": 1}, "2026-01-01T00:00:00Z"
        )
        assert a == b

    def test_different_payload_different_output(self) -> None:
        a = canonical_sha_input("artifact.captured", {"a": 1}, "2026-01-01T00:00:00Z")
        b = canonical_sha_input("artifact.captured", {"a": 2}, "2026-01-01T00:00:00Z")
        assert a != b
