# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for the Evidence Bundle generator (OMN-2505).

Test markers:
    @pytest.mark.unit     — pure unit tests
    @pytest.mark.integration — storage round-trip tests

Coverage:
- R1: Generate evidence bundle per executed ticket
  - Bundle is immutable (frozen Pydantic model)
  - Bundle contains ticket ID, outcome, AC records, timestamps
  - Bundle references nl_input_hash for traceability
  - completed_at must not precede started_at
- R2: Bundles are stored and retrievable
  - Bundles are saved to store on generation
  - Bundle is retrievable by bundle_id and ticket_id
  - Storage failure raises RuntimeError (no silent loss)
  - Duplicate bundle ID raises RuntimeError
- R3: Traceability chain
  - Bundle references ticket_id, work_unit_id, dag_id, intent_id, nl_input_hash
  - Chain verifiable end-to-end
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from omniclaude.nodes.node_evidence_bundle.enums.enum_ac_verdict import EnumAcVerdict
from omniclaude.nodes.node_evidence_bundle.enums.enum_execution_outcome import (
    EnumExecutionOutcome,
)
from omniclaude.nodes.node_evidence_bundle.handler_evidence_bundle_default import (
    HandlerEvidenceBundleDefault,
)
from omniclaude.nodes.node_evidence_bundle.models.model_ac_verification_record import (
    ModelAcVerificationRecord,
)
from omniclaude.nodes.node_evidence_bundle.models.model_bundle_generate_request import (
    ModelBundleGenerateRequest,
)
from omniclaude.nodes.node_evidence_bundle.models.model_evidence_bundle import (
    ModelEvidenceBundle,
)
from omniclaude.nodes.node_evidence_bundle.store_bundle_in_memory import (
    StoreBundleInMemory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NL_HASH = hashlib.sha256(b"add oauth2 login endpoint").hexdigest()
_T_START = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
_T_END = datetime(2025, 1, 1, 10, 5, 0, tzinfo=UTC)


def _ac_record(
    criterion_id: str = "wu-001-tests",
    verdict: EnumAcVerdict = EnumAcVerdict.PASS,
) -> ModelAcVerificationRecord:
    return ModelAcVerificationRecord(
        criterion_id=criterion_id,
        verdict=verdict,
        actual_value="0",
        verified_at=_T_END,
    )


def _request(
    outcome: EnumExecutionOutcome = EnumExecutionOutcome.SUCCESS,
    **kwargs: object,
) -> ModelBundleGenerateRequest:
    defaults: dict[str, object] = {
        "ticket_id": f"ticket-{uuid.uuid4()}",
        "work_unit_id": f"wu-{uuid.uuid4()}",
        "dag_id": f"dag-{uuid.uuid4()}",
        "intent_id": f"intent-{uuid.uuid4()}",
        "nl_input_hash": _NL_HASH,
        "outcome": outcome,
        "ac_records": (_ac_record(),),
        "actual_outputs": (("files_changed", "src/auth/oauth2.py"),),
        "started_at": _T_START,
        "completed_at": _T_END,
        "correlation_id": uuid.uuid4(),
    }
    defaults.update(kwargs)
    return ModelBundleGenerateRequest(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# R1: ModelAcVerificationRecord
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelAcVerificationRecord:
    def test_valid_record_accepted(self) -> None:
        rec = _ac_record()
        assert rec.verdict == EnumAcVerdict.PASS

    def test_record_is_frozen(self) -> None:
        rec = _ac_record()
        with pytest.raises(ValidationError):
            rec.verdict = EnumAcVerdict.FAIL  # type: ignore[misc]

    def test_all_verdicts_accepted(self) -> None:
        for verdict in EnumAcVerdict:
            rec = _ac_record(verdict=verdict)
            assert rec.verdict == verdict

    def test_error_message_default_empty(self) -> None:
        rec = _ac_record()
        assert rec.error_message == ""

    def test_actual_value_default_empty(self) -> None:
        rec = ModelAcVerificationRecord(
            criterion_id="wu-001-tests",
            verdict=EnumAcVerdict.SKIPPED,
            verified_at=_T_END,
        )
        assert rec.actual_value == ""


# ---------------------------------------------------------------------------
# R1: ModelEvidenceBundle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelEvidenceBundle:
    def _bundle(self, **kwargs: object) -> ModelEvidenceBundle:
        defaults: dict[str, object] = {
            "bundle_id": str(uuid.uuid4()),
            "ticket_id": f"ticket-{uuid.uuid4()}",
            "work_unit_id": f"wu-{uuid.uuid4()}",
            "dag_id": f"dag-{uuid.uuid4()}",
            "intent_id": f"intent-{uuid.uuid4()}",
            "nl_input_hash": _NL_HASH,
            "outcome": EnumExecutionOutcome.SUCCESS,
            "ac_records": (_ac_record(),),
            "actual_outputs": (),
            "started_at": _T_START,
            "completed_at": _T_END,
        }
        defaults.update(kwargs)
        return ModelEvidenceBundle(**defaults)  # type: ignore[arg-type]

    def test_valid_bundle_accepted(self) -> None:
        bundle = self._bundle()
        assert bundle.outcome == EnumExecutionOutcome.SUCCESS

    def test_bundle_is_frozen(self) -> None:
        bundle = self._bundle()
        with pytest.raises(ValidationError):
            bundle.outcome = EnumExecutionOutcome.FAILURE  # type: ignore[misc]

    def test_completed_before_started_rejected(self) -> None:
        with pytest.raises(ValidationError, match="completed_at"):
            self._bundle(
                started_at=_T_END,
                completed_at=_T_START,
            )

    def test_equal_timestamps_accepted(self) -> None:
        bundle = self._bundle(started_at=_T_START, completed_at=_T_START)
        assert bundle.started_at == bundle.completed_at

    def test_nl_input_hash_must_be_64_chars(self) -> None:
        with pytest.raises(ValidationError):
            self._bundle(nl_input_hash="tooshort")

    def test_nl_input_hash_stored(self) -> None:
        bundle = self._bundle()
        assert bundle.nl_input_hash == _NL_HASH

    def test_bundle_serializable(self) -> None:
        bundle = self._bundle()
        data = bundle.model_dump()
        assert data["outcome"] == "SUCCESS"
        assert len(data["nl_input_hash"]) == 64

    def test_all_outcome_types_accepted(self) -> None:
        for outcome in EnumExecutionOutcome:
            bundle = self._bundle(outcome=outcome)
            assert bundle.outcome == outcome


# ---------------------------------------------------------------------------
# R2: StoreBundleInMemory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreBundleInMemory:
    def setup_method(self) -> None:
        self.store = StoreBundleInMemory()

    def _bundle(self, **kwargs: object) -> ModelEvidenceBundle:
        defaults: dict[str, object] = {
            "bundle_id": str(uuid.uuid4()),
            "ticket_id": f"ticket-{uuid.uuid4()}",
            "work_unit_id": f"wu-{uuid.uuid4()}",
            "dag_id": f"dag-{uuid.uuid4()}",
            "intent_id": f"intent-{uuid.uuid4()}",
            "nl_input_hash": _NL_HASH,
            "outcome": EnumExecutionOutcome.SUCCESS,
            "started_at": _T_START,
            "completed_at": _T_END,
        }
        defaults.update(kwargs)
        return ModelEvidenceBundle(**defaults)  # type: ignore[arg-type]

    def test_save_and_get_by_bundle_id(self) -> None:
        bundle = self._bundle()
        self.store.save(bundle)
        retrieved = self.store.get(bundle.bundle_id)
        assert retrieved.bundle_id == bundle.bundle_id

    def test_save_and_get_by_ticket_id(self) -> None:
        bundle = self._bundle()
        self.store.save(bundle)
        retrieved = self.store.get_by_ticket_id(bundle.ticket_id)
        assert retrieved is not None
        assert retrieved.ticket_id == bundle.ticket_id

    def test_get_unknown_bundle_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            self.store.get("nonexistent-bundle-id")

    def test_get_unknown_ticket_returns_none(self) -> None:
        result = self.store.get_by_ticket_id("nonexistent-ticket-id")
        assert result is None

    def test_duplicate_bundle_id_raises_runtime_error(self) -> None:
        bundle = self._bundle()
        self.store.save(bundle)
        with pytest.raises(RuntimeError, match="already exists"):
            self.store.save(bundle)

    def test_multiple_bundles_stored_independently(self) -> None:
        b1 = self._bundle()
        b2 = self._bundle()
        self.store.save(b1)
        self.store.save(b2)
        assert self.store.get(b1.bundle_id).bundle_id == b1.bundle_id
        assert self.store.get(b2.bundle_id).bundle_id == b2.bundle_id


# ---------------------------------------------------------------------------
# R2: HandlerEvidenceBundleDefault — integration / storage round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerEvidenceBundleDefault:
    def setup_method(self) -> None:
        self.store = StoreBundleInMemory()
        self.handler = HandlerEvidenceBundleDefault(self.store)

    def test_handler_key_is_default(self) -> None:
        assert self.handler.handler_key == "default"

    def test_generate_returns_bundle(self) -> None:
        req = _request()
        bundle = self.handler.generate(req)
        assert isinstance(bundle, ModelEvidenceBundle)

    def test_generated_bundle_matches_request(self) -> None:
        req = _request()
        bundle = self.handler.generate(req)
        assert bundle.ticket_id == req.ticket_id
        assert bundle.work_unit_id == req.work_unit_id
        assert bundle.dag_id == req.dag_id
        assert bundle.intent_id == req.intent_id
        assert bundle.nl_input_hash == req.nl_input_hash
        assert bundle.outcome == req.outcome
        assert bundle.started_at == req.started_at
        assert bundle.completed_at == req.completed_at

    def test_generated_bundle_stored_by_bundle_id(self) -> None:
        req = _request()
        bundle = self.handler.generate(req)
        retrieved = self.store.get(bundle.bundle_id)
        assert retrieved.bundle_id == bundle.bundle_id

    def test_generated_bundle_retrievable_by_ticket_id(self) -> None:
        req = _request()
        bundle = self.handler.generate(req)
        retrieved = self.store.get_by_ticket_id(req.ticket_id)
        assert retrieved is not None
        assert retrieved.ticket_id == req.ticket_id

    def test_generate_with_failure_outcome(self) -> None:
        req = _request(outcome=EnumExecutionOutcome.FAILURE)
        bundle = self.handler.generate(req)
        assert bundle.outcome == EnumExecutionOutcome.FAILURE

    def test_generate_with_partial_outcome(self) -> None:
        req = _request(outcome=EnumExecutionOutcome.PARTIAL)
        bundle = self.handler.generate(req)
        assert bundle.outcome == EnumExecutionOutcome.PARTIAL

    def test_generate_with_ac_records(self) -> None:
        records = (
            _ac_record("wu-001-tests", EnumAcVerdict.PASS),
            _ac_record("wu-001-lint", EnumAcVerdict.FAIL),
        )
        req = _request(ac_records=records)
        bundle = self.handler.generate(req)
        assert len(bundle.ac_records) == 2
        assert bundle.ac_records[0].verdict == EnumAcVerdict.PASS
        assert bundle.ac_records[1].verdict == EnumAcVerdict.FAIL

    def test_generate_with_actual_outputs(self) -> None:
        outputs = (
            ("files_changed", "src/auth/oauth2.py"),
            ("tests_added", "tests/test_oauth2.py"),
        )
        req = _request(actual_outputs=outputs)
        bundle = self.handler.generate(req)
        assert len(bundle.actual_outputs) == 2

    def test_each_call_produces_unique_bundle_id(self) -> None:
        req1 = _request()
        req2 = _request()
        b1 = self.handler.generate(req1)
        b2 = self.handler.generate(req2)
        assert b1.bundle_id != b2.bundle_id


# ---------------------------------------------------------------------------
# R3: Traceability chain
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTraceabilityChain:
    def test_bundle_references_all_chain_ids(self) -> None:
        store = StoreBundleInMemory()
        handler = HandlerEvidenceBundleDefault(store)
        req = _request()
        bundle = handler.generate(req)
        assert bundle.ticket_id == req.ticket_id
        assert bundle.work_unit_id == req.work_unit_id
        assert bundle.dag_id == req.dag_id
        assert bundle.intent_id == req.intent_id
        assert bundle.nl_input_hash == req.nl_input_hash

    def test_nl_input_hash_is_sha256_hex(self) -> None:
        nl_text = "add oauth2 login endpoint to authservice"
        expected_hash = hashlib.sha256(nl_text.encode()).hexdigest()
        assert len(expected_hash) == 64

        store = StoreBundleInMemory()
        handler = HandlerEvidenceBundleDefault(store)
        req = _request(nl_input_hash=expected_hash)
        bundle = handler.generate(req)
        assert bundle.nl_input_hash == expected_hash

    def test_bundle_chain_verifiable_end_to_end(self) -> None:
        nl_text = "implement oauth2 login"
        nl_hash = hashlib.sha256(nl_text.encode()).hexdigest()

        ticket_id = f"ticket-{uuid.uuid4()}"
        wu_id = f"wu-{uuid.uuid4()}"
        dag_id = f"dag-{uuid.uuid4()}"
        intent_id = f"intent-{uuid.uuid4()}"

        store = StoreBundleInMemory()
        handler = HandlerEvidenceBundleDefault(store)
        req = _request(
            ticket_id=ticket_id,
            work_unit_id=wu_id,
            dag_id=dag_id,
            intent_id=intent_id,
            nl_input_hash=nl_hash,
        )
        bundle = handler.generate(req)

        # Chain: NL → Intent → DAG → Work Unit → Ticket → Bundle
        assert bundle.nl_input_hash == nl_hash
        assert bundle.intent_id == intent_id
        assert bundle.dag_id == dag_id
        assert bundle.work_unit_id == wu_id
        assert bundle.ticket_id == ticket_id

        # Retrievable by ticket_id
        retrieved = store.get_by_ticket_id(ticket_id)
        assert retrieved is not None
        assert retrieved.bundle_id == bundle.bundle_id

    def test_bundle_timestamps_are_explicit_not_defaulted(self) -> None:
        custom_start = datetime(2025, 6, 15, 9, 0, 0, tzinfo=UTC)
        custom_end = datetime(2025, 6, 15, 9, 30, 0, tzinfo=UTC)

        store = StoreBundleInMemory()
        handler = HandlerEvidenceBundleDefault(store)
        req = _request(started_at=custom_start, completed_at=custom_end)
        bundle = handler.generate(req)

        assert bundle.started_at == custom_start
        assert bundle.completed_at == custom_end
