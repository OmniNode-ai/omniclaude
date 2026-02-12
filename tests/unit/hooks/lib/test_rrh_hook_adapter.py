"""Tests for the RRH hook adapter (rrh_hook_adapter.py).

Validates phase-to-profile mapping, seam-ticket override, skip-to resume
logic, governance derivation from ModelTicketContract, verdict evaluation,
and idempotency key generation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# Insert hooks/lib so bare-name imports resolve (mirrors test_cross_repo_detector.py).
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
    ),
)

from omnibase_core.enums.ticket import (
    EnumDefinitionFormat,
    EnumInterfaceKind,
    EnumInterfaceSurface,
    EnumMockStrategy,
    EnumVerificationKind,
)
from omnibase_core.models.ticket.model_interface_consumed import ModelInterfaceConsumed
from omnibase_core.models.ticket.model_interface_provided import (
    ModelInterfaceProvided,
)
from omnibase_core.models.ticket.model_ticket_contract import ModelTicketContract
from omnibase_core.models.ticket.model_verification_step import ModelVerificationStep
from omnibase_spi.contracts.pipeline.contract_rrh_result import ContractRRHResult
from omnibase_spi.contracts.shared.contract_check_result import ContractCheckResult
from omnibase_spi.contracts.shared.contract_verdict import ContractVerdict
from rrh_hook_adapter import (
    PipelinePhase,
    RRHHookAdapter,
)

if TYPE_CHECKING:
    from rrh_adapter import RRHRunConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_contract(
    *,
    ticket_id: str = "OMN-2138",
    is_seam: bool = False,
    deployment_targets: list[str] | None = None,
    branch_pattern: str = "",
    with_interfaces: bool = False,
    with_verification: bool = False,
) -> ModelTicketContract:
    """Build a minimal ModelTicketContract for testing."""
    interfaces_provided: list[ModelInterfaceProvided] = []
    interfaces_consumed: list[ModelInterfaceConsumed] = []
    verification_steps: list[ModelVerificationStep] = []

    if with_interfaces:
        interfaces_provided = [
            ModelInterfaceProvided(
                id="ip-1",
                name="ProtocolFoo",
                kind=EnumInterfaceKind.PROTOCOL,
                surface=EnumInterfaceSurface.PUBLIC_API,
                definition_format=EnumDefinitionFormat.PYTHON,
                definition="class ProtocolFoo: ...",
            ),
        ]
        interfaces_consumed = [
            ModelInterfaceConsumed(
                id="ic-1",
                name="ProtocolBar",
                kind=EnumInterfaceKind.PROTOCOL,
                mock_strategy=EnumMockStrategy.PROTOCOL_STUB,
            ),
        ]

    if with_verification:
        verification_steps = [
            ModelVerificationStep(id="vs-1", kind=EnumVerificationKind.UNIT_TESTS),
            ModelVerificationStep(id="vs-2", kind=EnumVerificationKind.LINT),
        ]

    return ModelTicketContract(
        ticket_id=ticket_id,
        title="Test ticket",
        interfaces_provided=interfaces_provided,
        interfaces_consumed=interfaces_consumed,
        verification_steps=verification_steps,
        context={
            "is_seam_ticket": is_seam,
            "deployment_targets": deployment_targets or [],
            "expected_branch_pattern": branch_pattern,
        },
    )


def _make_rrh_result(
    status: str = "PASS",
    human_summary: str = "All checks passed.",
) -> ContractRRHResult:
    return ContractRRHResult(
        run_id="mock-run-001",
        checks=[
            ContractCheckResult(
                check_id="RRH-1001",
                domain="rrh",
                status="pass" if status == "PASS" else "fail",
                severity="minor",
                message="ok",
            ),
        ],
        verdict=ContractVerdict(
            status=status,
            score=100 if status == "PASS" else 0,
            block_reasons=([] if status == "PASS" else ["something failed"]),
            human_summary=human_summary,
        ),
        duration_ms=10.0,
    )


class StubRRHAdapter:
    """Adapter stub that records calls and returns a canned result."""

    def __init__(self, result: ContractRRHResult | None = None) -> None:
        self.result = result or _make_rrh_result()
        self.run_calls: list[RRHRunConfig] = []

    def run(self, config: RRHRunConfig) -> ContractRRHResult:
        self.run_calls.append(config)
        return self.result


# ---------------------------------------------------------------------------
# Tests: Phase -> profile mapping
# ---------------------------------------------------------------------------


class TestPhaseProfileMapping:
    """Test that each phase maps to the expected profile."""

    @pytest.mark.parametrize(
        ("phase", "expected_profile"),
        [
            (PipelinePhase.BEFORE_FIRST_SIDE_EFFECT, "ticket-pipeline"),
            (PipelinePhase.BEFORE_PR_CREATION, "ticket-pipeline"),
            (PipelinePhase.BEFORE_DEPLOY, "ticket-pipeline"),
            (PipelinePhase.ON_SKIP_TO_RESUME, "ticket-pipeline"),
        ],
    )
    def test_default_profile_for_phase(
        self,
        phase: PipelinePhase,
        expected_profile: str,
        tmp_path: Path,
    ) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract()

        hook.run_preflight(
            phase=phase,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        assert len(stub.run_calls) == 1
        # ON_SKIP_TO_RESUME with no original_phase falls back to map
        assert stub.run_calls[0].profile_name == expected_profile


class TestSeamTicketOverride:
    """Test that seam tickets get the seam-ticket profile at BEFORE_DEPLOY."""

    def test_seam_ticket_at_deploy_phase(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract(is_seam=True)

        hook.run_preflight(
            phase=PipelinePhase.BEFORE_DEPLOY,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        assert stub.run_calls[0].profile_name == "seam-ticket"

    def test_seam_ticket_at_non_deploy_phase(self, tmp_path: Path) -> None:
        """Seam tickets still use ticket-pipeline at non-deploy phases."""
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract(is_seam=True)

        hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        assert stub.run_calls[0].profile_name == "ticket-pipeline"

    def test_non_seam_ticket_at_deploy_phase(self, tmp_path: Path) -> None:
        """Non-seam tickets use ticket-pipeline even at deploy phase."""
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract(is_seam=False)

        hook.run_preflight(
            phase=PipelinePhase.BEFORE_DEPLOY,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        assert stub.run_calls[0].profile_name == "ticket-pipeline"


class TestSkipToResume:
    """Test that ON_SKIP_TO_RESUME uses the original phase's profile."""

    def test_resume_uses_original_phase_profile(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract()

        hook.run_preflight(
            phase=PipelinePhase.ON_SKIP_TO_RESUME,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            original_phase=PipelinePhase.BEFORE_PR_CREATION,
        )

        assert stub.run_calls[0].profile_name == "ticket-pipeline"

    def test_resume_seam_at_deploy(self, tmp_path: Path) -> None:
        """ON_SKIP_TO_RESUME with original_phase=BEFORE_DEPLOY + seam -> seam-ticket."""
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract(is_seam=True)

        hook.run_preflight(
            phase=PipelinePhase.ON_SKIP_TO_RESUME,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            original_phase=PipelinePhase.BEFORE_DEPLOY,
        )

        assert stub.run_calls[0].profile_name == "seam-ticket"


# ---------------------------------------------------------------------------
# Tests: Governance derivation
# ---------------------------------------------------------------------------


class TestGovernanceDerivation:
    """Test governance fields are derived correctly from ModelTicketContract."""

    def test_interfaces_collected(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract(with_interfaces=True)

        hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        gov = stub.run_calls[0].governance
        assert "ProtocolBar" in gov.interfaces_touched
        assert "ProtocolFoo" in gov.interfaces_touched
        # Sorted and deduplicated
        assert gov.interfaces_touched == ("ProtocolBar", "ProtocolFoo")

    def test_evidence_from_verification_steps(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract(with_verification=True)

        hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        gov = stub.run_calls[0].governance
        # unit_tests -> "tests", lint -> not mapped
        assert gov.evidence_requirements == ("tests",)

    def test_deployment_targets_from_context(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract(deployment_targets=["staging", "prod"])

        hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        gov = stub.run_calls[0].governance
        assert gov.deployment_targets == ("staging", "prod")

    def test_seam_flag_from_context(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract(is_seam=True)

        hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        gov = stub.run_calls[0].governance
        assert gov.is_seam_ticket is True

    def test_branch_pattern_from_context(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract(branch_pattern="feature/OMN-*")

        hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        gov = stub.run_calls[0].governance
        assert gov.expected_branch_pattern == "feature/OMN-*"

    def test_empty_contract_produces_empty_governance(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract()

        hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        gov = stub.run_calls[0].governance
        assert gov.ticket_id == "OMN-2138"
        assert gov.evidence_requirements == ()
        assert gov.interfaces_touched == ()
        assert gov.deployment_targets == ()
        assert gov.is_seam_ticket is False
        assert gov.expected_branch_pattern == ""


# ---------------------------------------------------------------------------
# Tests: Verdict evaluation
# ---------------------------------------------------------------------------


class TestEvaluateVerdict:
    """Test _evaluate: verdict -> should_block mapping."""

    @pytest.mark.parametrize(
        ("status", "expected_block"),
        [
            ("PASS", False),
            ("FAIL", True),
            ("QUARANTINE", False),
        ],
    )
    def test_should_block(
        self,
        status: str,
        expected_block: bool,
        tmp_path: Path,
    ) -> None:
        stub = StubRRHAdapter(result=_make_rrh_result(status=status))
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract()

        decision = hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        assert decision.should_block is expected_block
        assert decision.verdict == status

    def test_human_summary_propagated(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter(
            result=_make_rrh_result(
                status="FAIL", human_summary="Branch naming violation"
            )
        )
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract()

        decision = hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

        assert decision.human_summary == "Branch naming violation"


# ---------------------------------------------------------------------------
# Tests: Idempotency key
# ---------------------------------------------------------------------------


class TestIdempotencyKey:
    """Test that the idempotency key is deterministic and changes with inputs."""

    def test_deterministic(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract()

        d1 = hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            head_sha="abc123",
        )
        d2 = hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            head_sha="abc123",
        )

        assert d1.idempotency_key == d2.idempotency_key

    def test_changes_with_phase(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract()

        d1 = hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            head_sha="abc123",
        )
        d2 = hook.run_preflight(
            phase=PipelinePhase.BEFORE_PR_CREATION,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            head_sha="abc123",
        )

        assert d1.idempotency_key != d2.idempotency_key

    def test_changes_with_sha(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract()

        d1 = hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            head_sha="abc123",
        )
        d2 = hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            head_sha="def456",
        )

        assert d1.idempotency_key != d2.idempotency_key

    def test_key_is_16_hex_chars(self, tmp_path: Path) -> None:
        stub = StubRRHAdapter()
        hook = RRHHookAdapter(adapter=stub)  # type: ignore[arg-type]
        contract = _make_contract()

        decision = hook.run_preflight(
            phase=PipelinePhase.BEFORE_FIRST_SIDE_EFFECT,
            contract=contract,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            head_sha="abc",
        )

        assert len(decision.idempotency_key) == 16
        # Verify it is valid hex
        int(decision.idempotency_key, 16)
