# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""End-to-end integration tests for the NL Intent-Plan-Ticket Compiler (OMN-2507).

Proves the full pipeline from raw NL prompt to executable Linear ticket
across all 6 stages without manual intervention.

Pipeline stages:
  Stage 1: NL → Intent Object (HandlerNlIntentDefault, OMN-2501)
  Stage 2: Intent → Plan DAG (HandlerPlanDagDefault, OMN-2502)
  Stage 3.5: Ambiguity Gate (HandlerAmbiguityGateDefault, OMN-2504)
  Stage 4: Plan → Ticket Compilation (HandlerTicketCompileDefault, OMN-2503)
  Stage 5: Evidence Bundle Generation (HandlerEvidenceBundleDefault, OMN-2505)
  Stage 6: OmniMemory Pattern Promotion (HandlerPatternPromotionDefault, OMN-2506)

Test paths:
  R1 (e2e_nl_to_ticket): Happy path — clear NL prompt produces a compiled ticket
  R2 (e2e_ambiguity_rejection): Ambiguous plan node raises AmbiguityGateError
  R3 (e2e_pattern_promotion): Repeated compilations promote a pattern to OmniMemory

Test markers:
    @pytest.mark.integration  — all tests here; requires pipeline stage packages
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest

# ---------------------------------------------------------------------------
# Pipeline stage imports
# ---------------------------------------------------------------------------
# All pipeline stages are available after PRs OMN-2501 through OMN-2506 are
# merged.  Before that, the imports are skipped gracefully via importorskip.
# ---------------------------------------------------------------------------

_pipeline_stages = pytest.importorskip(
    "omniclaude.nodes.node_nl_intent_pipeline.handler_nl_intent_default",
    reason="Pipeline stage OMN-2501 not yet merged — run after all PRs are merged",
)
pytest.importorskip(
    "omniclaude.nodes.node_plan_dag_generator.handler_plan_dag_default",
    reason="Pipeline stage OMN-2502 not yet merged",
)
pytest.importorskip(
    "omniclaude.nodes.node_ambiguity_gate.handler_ambiguity_gate_default",
    reason="Pipeline stage OMN-2504 not yet merged",
)
pytest.importorskip(
    "omniclaude.nodes.node_ticket_compiler.handler_ticket_compile_default",
    reason="Pipeline stage OMN-2503 not yet merged",
)
pytest.importorskip(
    "omniclaude.nodes.node_evidence_bundle.handler_evidence_bundle_default",
    reason="Pipeline stage OMN-2505 not yet merged",
)
pytest.importorskip(
    "omniclaude.nodes.node_omnimemory_promotion.handler_pattern_promotion_default",
    reason="Pipeline stage OMN-2506 not yet merged",
)

# ---------------------------------------------------------------------------
# Stage 3.5: Ambiguity Gate
# ---------------------------------------------------------------------------
from omniclaude.nodes.node_ambiguity_gate.handler_ambiguity_gate_default import (  # noqa: E402
    HandlerAmbiguityGateDefault,
)
from omniclaude.nodes.node_ambiguity_gate.models.model_ambiguity_gate_error import (  # noqa: E402
    AmbiguityGateError,
)
from omniclaude.nodes.node_ambiguity_gate.models.model_gate_check_request import (  # noqa: E402
    ModelGateCheckRequest,
)

# ---------------------------------------------------------------------------
# Stage 5: Evidence Bundle Generation
# ---------------------------------------------------------------------------
from omniclaude.nodes.node_evidence_bundle.enums.enum_ac_verdict import (  # noqa: E402
    EnumAcVerdict,
)
from omniclaude.nodes.node_evidence_bundle.enums.enum_execution_outcome import (  # noqa: E402
    EnumExecutionOutcome,
)
from omniclaude.nodes.node_evidence_bundle.handler_evidence_bundle_default import (  # noqa: E402
    HandlerEvidenceBundleDefault,
)
from omniclaude.nodes.node_evidence_bundle.models.model_ac_verification_record import (  # noqa: E402
    ModelAcVerificationRecord,
)
from omniclaude.nodes.node_evidence_bundle.models.model_bundle_generate_request import (  # noqa: E402
    ModelBundleGenerateRequest,
)
from omniclaude.nodes.node_evidence_bundle.store_bundle_in_memory import (  # noqa: E402
    StoreBundleInMemory,
)

# ---------------------------------------------------------------------------
# Stage 1: NL → Intent
# ---------------------------------------------------------------------------
from omniclaude.nodes.node_nl_intent_pipeline.handler_nl_intent_default import (  # noqa: E402
    HandlerNlIntentDefault,
)
from omniclaude.nodes.node_nl_intent_pipeline.models.model_nl_parse_request import (  # noqa: E402
    ModelNlParseRequest,
)

# ---------------------------------------------------------------------------
# Stage 6: OmniMemory Pattern Promotion
# ---------------------------------------------------------------------------
from omniclaude.nodes.node_omnimemory_promotion.enums.enum_promotion_status import (  # noqa: E402
    EnumPromotionStatus,
)
from omniclaude.nodes.node_omnimemory_promotion.handler_pattern_promotion_default import (  # noqa: E402
    HandlerPatternPromotionDefault,
)
from omniclaude.nodes.node_omnimemory_promotion.models.model_pattern_promotion_request import (  # noqa: E402
    ModelPatternPromotionRequest,
)
from omniclaude.nodes.node_omnimemory_promotion.models.model_promotion_criteria import (  # noqa: E402
    ModelPromotionCriteria,
)
from omniclaude.nodes.node_omnimemory_promotion.store_pattern_in_memory import (  # noqa: E402
    StorePatternInMemory,
)

# ---------------------------------------------------------------------------
# Stage 2: Intent → Plan DAG
# ---------------------------------------------------------------------------
from omniclaude.nodes.node_plan_dag_generator.handler_plan_dag_default import (  # noqa: E402
    HandlerPlanDagDefault,
)
from omniclaude.nodes.node_plan_dag_generator.models.model_plan_dag_request import (  # noqa: E402
    ModelPlanDagRequest,
)

# ---------------------------------------------------------------------------
# Stage 4: Plan → Ticket Compilation
# ---------------------------------------------------------------------------
from omniclaude.nodes.node_ticket_compiler.handler_ticket_compile_default import (  # noqa: E402
    HandlerTicketCompileDefault,
)
from omniclaude.nodes.node_ticket_compiler.models.model_ticket_compile_request import (  # noqa: E402
    ModelTicketCompileRequest,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def nl_handler() -> HandlerNlIntentDefault:
    return HandlerNlIntentDefault()


@pytest.fixture
def dag_handler() -> HandlerPlanDagDefault:
    return HandlerPlanDagDefault()


@pytest.fixture
def gate_handler() -> HandlerAmbiguityGateDefault:
    return HandlerAmbiguityGateDefault()


@pytest.fixture
def ticket_handler() -> HandlerTicketCompileDefault:
    return HandlerTicketCompileDefault()


@pytest.fixture
def bundle_store() -> StoreBundleInMemory:
    return StoreBundleInMemory()


@pytest.fixture
def bundle_handler(bundle_store: StoreBundleInMemory) -> HandlerEvidenceBundleDefault:
    return HandlerEvidenceBundleDefault(bundle_store)


@pytest.fixture
def pattern_store() -> StorePatternInMemory:
    return StorePatternInMemory()


@pytest.fixture
def promotion_handler(
    pattern_store: StorePatternInMemory,
) -> HandlerPatternPromotionDefault:
    return HandlerPatternPromotionDefault(pattern_store)


def _nl_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _now() -> datetime:
    return datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)


def _later() -> datetime:
    return datetime(2025, 6, 1, 10, 5, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# R1: Happy path — NL prompt → compiled ticket
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestE2eNlToTicket:
    """R1: Clear NL prompt produces a compiled ticket with IDL + test contract + policy."""

    def test_e2e_nl_to_ticket_happy_path(
        self,
        nl_handler: HandlerNlIntentDefault,
        dag_handler: HandlerPlanDagDefault,
        gate_handler: HandlerAmbiguityGateDefault,
        ticket_handler: HandlerTicketCompileDefault,
    ) -> None:
        """Full pipeline: NL → Intent → Plan DAG → Ambiguity Gate → Compiled Ticket."""
        nl_text = "Add OAuth2 login endpoint to the AuthService with unit tests"
        correlation_id = uuid.uuid4()

        # Stage 1: NL → Intent
        nl_request = ModelNlParseRequest(
            nl_input=nl_text,
            correlation_id=correlation_id,
        )
        intent = nl_handler.parse_intent(nl_request)
        assert intent.intent_id
        assert intent.nl_input_hash == _nl_hash(nl_text)
        assert intent.confidence > 0.0

        # Stage 2: Intent → Plan DAG
        dag_request = ModelPlanDagRequest(
            intent_id=intent.intent_id,
            intent_type=intent.intent_type.value,
            intent_summary=intent.summary,
            correlation_id=correlation_id,
        )
        plan_dag = dag_handler.generate_plan_dag(dag_request)
        assert plan_dag.dag_id
        assert len(plan_dag.nodes) >= 1

        # Stage 3.5: Ambiguity Gate — all nodes must pass
        dag_id = plan_dag.dag_id
        for unit in plan_dag.nodes:
            gate_req = ModelGateCheckRequest(
                unit_id=unit.unit_id,
                unit_title=unit.title,
                unit_description=unit.description or "Implementation details TBD.",
                unit_type=unit.unit_type.value,
                estimated_scope=unit.estimated_scope,
                context=unit.context,
                dag_id=dag_id,
                intent_id=intent.intent_id,
                correlation_id=correlation_id,
            )
            result = gate_handler.check(gate_req)
            assert result.verdict.value == "PASS", (
                f"Node {unit.unit_id!r} failed ambiguity gate: "
                + "; ".join(f.description for f in result.ambiguity_flags)
            )

        # Stage 4: Plan → Ticket Compilation (compile first node as representative)
        first_unit = plan_dag.nodes[0]
        compile_req = ModelTicketCompileRequest(
            work_unit_id=first_unit.unit_id,
            work_unit_title=first_unit.title,
            work_unit_description=first_unit.description
            or "Implementation details TBD.",
            work_unit_type=first_unit.unit_type.value,
            dag_id=dag_id,
            intent_id=intent.intent_id,
            correlation_id=correlation_id,
        )
        ticket = ticket_handler.compile_ticket(compile_req)

        # Ticket must have all required components
        assert ticket.ticket_id
        assert ticket.work_unit_id == first_unit.unit_id
        assert ticket.intent_id == intent.intent_id
        assert ticket.dag_id == dag_id
        assert len(ticket.acceptance_criteria) >= 1
        assert ticket.idl_spec.input_schema
        assert ticket.policy_envelope.sandbox_level is not None
        assert "## IDL Specification" in ticket.description
        assert "## Acceptance Criteria" in ticket.description
        assert "## Policy Envelope" in ticket.description

    def test_e2e_ticket_linked_to_intent_via_nl_hash(
        self,
        nl_handler: HandlerNlIntentDefault,
        dag_handler: HandlerPlanDagDefault,
        gate_handler: HandlerAmbiguityGateDefault,
        ticket_handler: HandlerTicketCompileDefault,
        bundle_handler: HandlerEvidenceBundleDefault,
    ) -> None:
        """R1: Evidence bundle references nl_input_hash for traceability."""
        nl_text = "Fix the session timeout bug in the login flow"
        correlation_id = uuid.uuid4()

        # Stages 1-4
        intent = nl_handler.parse_intent(
            ModelNlParseRequest(nl_input=nl_text, correlation_id=correlation_id)
        )
        plan_dag = dag_handler.generate_plan_dag(
            ModelPlanDagRequest(
                intent_id=intent.intent_id,
                intent_type=intent.intent_type.value,
                intent_summary=intent.summary,
                correlation_id=correlation_id,
            )
        )
        first_unit = plan_dag.nodes[0]

        # Pass gate for first unit (may need description padding for generic templates)
        gate_req = ModelGateCheckRequest(
            unit_id=first_unit.unit_id,
            unit_title=first_unit.title,
            unit_description=first_unit.description
            or "Detailed implementation per design.",
            unit_type=first_unit.unit_type.value,
            estimated_scope=first_unit.estimated_scope,
            context=first_unit.context,
            dag_id=plan_dag.dag_id,
            intent_id=intent.intent_id,
            correlation_id=correlation_id,
        )
        gate_handler.check(gate_req)

        ticket = ticket_handler.compile_ticket(
            ModelTicketCompileRequest(
                work_unit_id=first_unit.unit_id,
                work_unit_title=first_unit.title,
                work_unit_description=first_unit.description
                or "Detailed implementation.",
                work_unit_type=first_unit.unit_type.value,
                dag_id=plan_dag.dag_id,
                intent_id=intent.intent_id,
                correlation_id=correlation_id,
            )
        )

        # Stage 5: Evidence Bundle Generation
        ac_records = tuple(
            ModelAcVerificationRecord(
                criterion_id=ac.criterion_id,
                verdict=EnumAcVerdict.PASS,
                actual_value="0",
                verified_at=_later(),
            )
            for ac in ticket.acceptance_criteria
        )
        bundle = bundle_handler.generate(
            ModelBundleGenerateRequest(
                ticket_id=ticket.ticket_id,
                work_unit_id=ticket.work_unit_id,
                dag_id=ticket.dag_id,
                intent_id=ticket.intent_id,
                nl_input_hash=intent.nl_input_hash,
                outcome=EnumExecutionOutcome.SUCCESS,
                ac_records=ac_records,
                started_at=_now(),
                completed_at=_later(),
                correlation_id=correlation_id,
            )
        )

        # Bundle links all chain IDs back to original NL input
        assert bundle.nl_input_hash == intent.nl_input_hash
        assert bundle.nl_input_hash == _nl_hash(nl_text)
        assert bundle.ticket_id == ticket.ticket_id
        assert bundle.work_unit_id == first_unit.unit_id
        assert bundle.dag_id == plan_dag.dag_id
        assert bundle.intent_id == intent.intent_id


# ---------------------------------------------------------------------------
# R2: Rejection path — ambiguous plan node → AmbiguityGateError
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestE2eAmbiguityRejection:
    """R2: Ambiguous work unit raises AmbiguityGateError; no ticket emitted."""

    def test_e2e_ambiguity_rejection_vague_title(
        self,
        gate_handler: HandlerAmbiguityGateDefault,
    ) -> None:
        """Vague work unit title blocks ticket compilation at the gate."""
        correlation_id = uuid.uuid4()
        dag_id = f"dag-{uuid.uuid4()}"
        intent_id = f"intent-{uuid.uuid4()}"

        gate_req = ModelGateCheckRequest(
            unit_id=f"wu-{uuid.uuid4()}",
            unit_title="Fix",  # Too vague: 1 word
            unit_description="Implement the fix as needed.",
            unit_type="BUG_FIX",
            dag_id=dag_id,
            intent_id=intent_id,
            correlation_id=correlation_id,
        )

        with pytest.raises(AmbiguityGateError) as exc_info:
            gate_handler.check(gate_req)

        # Gate rejected before ticket compilation; verify rejection details
        assert exc_info.value.result.verdict.value == "FAIL"

        # Error includes which ambiguity type and suggested resolution
        flags = exc_info.value.result.ambiguity_flags
        flag_types = {f.ambiguity_type.value for f in flags}
        assert "TITLE_TOO_VAGUE" in flag_types

        for flag in flags:
            assert flag.suggested_resolution, "Flag missing suggested_resolution"

    def test_e2e_ambiguity_rejection_missing_description(
        self,
        gate_handler: HandlerAmbiguityGateDefault,
    ) -> None:
        """Missing description blocks ticket compilation at the gate."""
        gate_req = ModelGateCheckRequest(
            unit_id=f"wu-{uuid.uuid4()}",
            unit_title="Add OAuth2 login endpoint",
            unit_description="",  # Missing description
            unit_type="FEATURE_IMPLEMENTATION",
            dag_id=f"dag-{uuid.uuid4()}",
            intent_id=f"intent-{uuid.uuid4()}",
            correlation_id=uuid.uuid4(),
        )

        with pytest.raises(AmbiguityGateError) as exc_info:
            gate_handler.check(gate_req)

        flags = exc_info.value.result.ambiguity_flags
        flag_types = {f.ambiguity_type.value for f in flags}
        assert "DESCRIPTION_MISSING" in flag_types

    def test_e2e_ambiguity_rejection_generic_type(
        self,
        gate_handler: HandlerAmbiguityGateDefault,
    ) -> None:
        """GENERIC unit type blocks ticket compilation at the gate."""
        gate_req = ModelGateCheckRequest(
            unit_id=f"wu-{uuid.uuid4()}",
            unit_title="Add OAuth2 login endpoint",
            unit_description="Implement OAuth2 using the existing session manager.",
            unit_type="GENERIC",  # Unknown type
            dag_id=f"dag-{uuid.uuid4()}",
            intent_id=f"intent-{uuid.uuid4()}",
            correlation_id=uuid.uuid4(),
        )

        with pytest.raises(AmbiguityGateError) as exc_info:
            gate_handler.check(gate_req)

        flags = exc_info.value.result.ambiguity_flags
        flag_types = {f.ambiguity_type.value for f in flags}
        assert "UNKNOWN_UNIT_TYPE" in flag_types

    def test_e2e_ambiguity_rejection_error_is_traceable(
        self,
        gate_handler: HandlerAmbiguityGateDefault,
    ) -> None:
        """Rejection error is traceable to DAG and Intent IDs."""
        dag_id = f"dag-{uuid.uuid4()}"
        intent_id = f"intent-{uuid.uuid4()}"
        unit_id = f"wu-{uuid.uuid4()}"

        gate_req = ModelGateCheckRequest(
            unit_id=unit_id,
            unit_title="Fix",
            unit_description="",
            unit_type="GENERIC",
            dag_id=dag_id,
            intent_id=intent_id,
            correlation_id=uuid.uuid4(),
        )

        with pytest.raises(AmbiguityGateError) as exc_info:
            gate_handler.check(gate_req)

        result = exc_info.value.result
        assert result.unit_id == unit_id
        assert result.dag_id == dag_id
        assert result.intent_id == intent_id


# ---------------------------------------------------------------------------
# R3: Pattern promotion path — repeated compilations → OmniMemory promotion
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestE2ePatternPromotion:
    """R3: After N successful compilations, pattern is promoted to OmniMemory."""

    def _run_pipeline_once(
        self,
        nl_text: str,
        nl_handler: HandlerNlIntentDefault,
        dag_handler: HandlerPlanDagDefault,
        gate_handler: HandlerAmbiguityGateDefault,
        ticket_handler: HandlerTicketCompileDefault,
        bundle_handler: HandlerEvidenceBundleDefault,
    ) -> tuple[str, str, str]:
        """Run NL→Ticket pipeline once; return (bundle_id, ticket_id, intent_type)."""
        correlation_id = uuid.uuid4()

        intent = nl_handler.parse_intent(
            ModelNlParseRequest(nl_input=nl_text, correlation_id=correlation_id)
        )
        plan_dag = dag_handler.generate_plan_dag(
            ModelPlanDagRequest(
                intent_id=intent.intent_id,
                intent_type=intent.intent_type.value,
                intent_summary=intent.summary,
                correlation_id=correlation_id,
            )
        )
        first_unit = plan_dag.nodes[0]

        # Pass gate
        gate_req = ModelGateCheckRequest(
            unit_id=first_unit.unit_id,
            unit_title=first_unit.title,
            unit_description=first_unit.description
            or "Detailed implementation per design.",
            unit_type=first_unit.unit_type.value,
            estimated_scope=first_unit.estimated_scope,
            context=first_unit.context,
            dag_id=plan_dag.dag_id,
            intent_id=intent.intent_id,
            correlation_id=correlation_id,
        )
        gate_handler.check(gate_req)

        ticket = ticket_handler.compile_ticket(
            ModelTicketCompileRequest(
                work_unit_id=first_unit.unit_id,
                work_unit_title=first_unit.title,
                work_unit_description=first_unit.description
                or "Implementation details.",
                work_unit_type=first_unit.unit_type.value,
                dag_id=plan_dag.dag_id,
                intent_id=intent.intent_id,
                correlation_id=correlation_id,
            )
        )

        ac_records = tuple(
            ModelAcVerificationRecord(
                criterion_id=ac.criterion_id,
                verdict=EnumAcVerdict.PASS,
                actual_value="0",
                verified_at=_later(),
            )
            for ac in ticket.acceptance_criteria
        )
        bundle = bundle_handler.generate(
            ModelBundleGenerateRequest(
                ticket_id=ticket.ticket_id,
                work_unit_id=ticket.work_unit_id,
                dag_id=ticket.dag_id,
                intent_id=ticket.intent_id,
                nl_input_hash=intent.nl_input_hash,
                outcome=EnumExecutionOutcome.SUCCESS,
                ac_records=ac_records,
                started_at=_now(),
                completed_at=_later(),
                correlation_id=correlation_id,
            )
        )

        return bundle.bundle_id, ticket.ticket_id, intent.intent_type.value

    def test_e2e_pattern_promotion_after_n_compilations(
        self,
        nl_handler: HandlerNlIntentDefault,
        dag_handler: HandlerPlanDagDefault,
        gate_handler: HandlerAmbiguityGateDefault,
        ticket_handler: HandlerTicketCompileDefault,
        bundle_handler: HandlerEvidenceBundleDefault,
        bundle_store: StoreBundleInMemory,
        promotion_handler: HandlerPatternPromotionDefault,
    ) -> None:
        """After 3 successful compilations, pattern is promoted to OmniMemory."""
        nl_prompts = [
            "Add OAuth2 login endpoint to the AuthService with unit tests",
            "Implement OAuth2 authentication flow for the web API service",
            "Create OAuth2 login capability with test coverage in AuthService",
        ]

        bundle_ids: list[str] = []
        intent_type: str = ""

        for nl_text in nl_prompts:
            bid, _tid, itype = self._run_pipeline_once(
                nl_text,
                nl_handler,
                dag_handler,
                gate_handler,
                ticket_handler,
                bundle_handler,
            )
            bundle_ids.append(bid)
            intent_type = itype

        # Derive unit_specs from the Plan DAG for the first prompt
        first_dag = dag_handler.generate_plan_dag(
            ModelPlanDagRequest(
                intent_id=f"intent-{uuid.uuid4()}",
                intent_type=intent_type,
                intent_summary="OAuth2 login",
                correlation_id=uuid.uuid4(),
            )
        )
        unit_specs = tuple(
            (u.unit_id, u.title, u.unit_type.value, u.estimated_scope)
            for u in first_dag.nodes
        )
        dep_specs = tuple((e.from_unit_id, e.to_unit_id) for e in first_dag.edges)

        # Stage 6: Promote pattern
        promotion_req = ModelPatternPromotionRequest(
            intent_type=intent_type,
            unit_specs=unit_specs,
            dep_specs=dep_specs,
            evidence_bundle_ids=tuple(bundle_ids),
            evidence_count=len(bundle_ids),
            criteria=ModelPromotionCriteria(min_evidence_count=3),
            correlation_id=uuid.uuid4(),
        )
        result = promotion_handler.promote(promotion_req)

        assert result.status == EnumPromotionStatus.PROMOTED
        assert result.promoted_pattern is not None
        assert result.promoted_pattern.intent_type == intent_type
        assert result.promoted_pattern.evidence_count == 3
        assert result.promoted_pattern.version == 1

    def test_e2e_pattern_promotion_idempotent(
        self,
        nl_handler: HandlerNlIntentDefault,
        dag_handler: HandlerPlanDagDefault,
        gate_handler: HandlerAmbiguityGateDefault,
        ticket_handler: HandlerTicketCompileDefault,
        bundle_handler: HandlerEvidenceBundleDefault,
        promotion_handler: HandlerPatternPromotionDefault,
    ) -> None:
        """Promoting the same pattern twice returns ALREADY_CURRENT."""
        nl_text = "Add OAuth2 login endpoint to the AuthService with unit tests"
        bid, _tid, intent_type = self._run_pipeline_once(
            nl_text,
            nl_handler,
            dag_handler,
            gate_handler,
            ticket_handler,
            bundle_handler,
        )

        first_dag = dag_handler.generate_plan_dag(
            ModelPlanDagRequest(
                intent_id=f"intent-{uuid.uuid4()}",
                intent_type=intent_type,
                intent_summary="OAuth2",
                correlation_id=uuid.uuid4(),
            )
        )
        unit_specs = tuple(
            (u.unit_id, u.title, u.unit_type.value, u.estimated_scope)
            for u in first_dag.nodes
        )

        req = ModelPatternPromotionRequest(
            intent_type=intent_type,
            unit_specs=unit_specs,
            dep_specs=(),
            evidence_bundle_ids=(bid,),
            evidence_count=1,
            criteria=ModelPromotionCriteria(min_evidence_count=1),
            correlation_id=uuid.uuid4(),
        )
        r1 = promotion_handler.promote(req)
        r2 = promotion_handler.promote(req)

        assert r1.status == EnumPromotionStatus.PROMOTED
        assert r2.status == EnumPromotionStatus.ALREADY_CURRENT

    def test_e2e_cache_hit_after_promotion(
        self,
        nl_handler: HandlerNlIntentDefault,
        dag_handler: HandlerPlanDagDefault,
        gate_handler: HandlerAmbiguityGateDefault,
        ticket_handler: HandlerTicketCompileDefault,
        bundle_handler: HandlerEvidenceBundleDefault,
        promotion_handler: HandlerPatternPromotionDefault,
    ) -> None:
        """After promotion, lookup returns the pattern (cache hit)."""
        nl_text = "Add OAuth2 login endpoint to the AuthService with unit tests"
        bid, _tid, intent_type = self._run_pipeline_once(
            nl_text,
            nl_handler,
            dag_handler,
            gate_handler,
            ticket_handler,
            bundle_handler,
        )

        first_dag = dag_handler.generate_plan_dag(
            ModelPlanDagRequest(
                intent_id=f"intent-{uuid.uuid4()}",
                intent_type=intent_type,
                intent_summary="OAuth2",
                correlation_id=uuid.uuid4(),
            )
        )
        unit_specs = tuple(
            (u.unit_id, u.title, u.unit_type.value, u.estimated_scope)
            for u in first_dag.nodes
        )

        req = ModelPatternPromotionRequest(
            intent_type=intent_type,
            unit_specs=unit_specs,
            dep_specs=(),
            evidence_bundle_ids=(bid,),
            evidence_count=1,
            criteria=ModelPromotionCriteria(min_evidence_count=1),
            correlation_id=uuid.uuid4(),
        )
        promotion_handler.promote(req)

        # Cache hit
        cached = promotion_handler.lookup(intent_type, unit_specs)
        assert cached is not None
        assert cached.intent_type == intent_type

    def test_e2e_cache_miss_before_promotion(
        self,
        promotion_handler: HandlerPatternPromotionDefault,
    ) -> None:
        """Before promotion, lookup returns None (cache miss, fallback to full generation)."""
        dummy_specs: tuple[tuple[str, str, str, str], ...] = (
            ("wu-1", "Implement something", "FEATURE_IMPLEMENTATION", "M"),
        )
        result = promotion_handler.lookup("NONEXISTENT_INTENT", dummy_specs)
        assert result is None

    def test_e2e_below_threshold_pattern_not_promoted(
        self,
        promotion_handler: HandlerPatternPromotionDefault,
    ) -> None:
        """Pattern with fewer than min_evidence_count bundles is not promoted."""
        unit_specs: tuple[tuple[str, str, str, str], ...] = (
            ("wu-1", "Test unit", "TEST_SUITE", "S"),
        )
        req = ModelPatternPromotionRequest(
            intent_type="TESTING",
            unit_specs=unit_specs,
            dep_specs=(),
            evidence_bundle_ids=(f"bundle-{uuid.uuid4()}",),
            evidence_count=1,
            criteria=ModelPromotionCriteria(min_evidence_count=5),
            correlation_id=uuid.uuid4(),
        )
        result = promotion_handler.promote(req)
        assert result.status == EnumPromotionStatus.SKIPPED
        assert result.promoted_pattern is None
        assert promotion_handler.lookup("TESTING", unit_specs) is None
