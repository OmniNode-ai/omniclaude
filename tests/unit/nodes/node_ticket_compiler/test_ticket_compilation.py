# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for the Ticket Compiler (OMN-2503).

Test markers:
    @pytest.mark.unit  — all tests here

Coverage:
- R1: IDL specification (input/output schemas + declared side effects)
  - IDL input and output schemas are valid JSON
  - Side effects are declared strings
  - IDL is serializable (JSON/YAML)
- R2: Test contract (verifiable acceptance criteria, no prose-only ACs)
  - Acceptance criteria include programmatically verifiable ACs
  - Prose-only ACs (MANUAL_VERIFICATION-only) are rejected
  - Tickets with no ACs are rejected
  - ACs contain verification commands where applicable
- R3: Policy envelope (validators, permission scope, sandbox constraints)
  - Policy envelope declares required validators
  - Permission scope is derived from side effects
  - Sandbox level defaults to STANDARD
  - ENFORCED/ISOLATED sandbox cannot allow network access
  - Sandbox validator enforced at construction
"""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from omniclaude.nodes.node_ticket_compiler.enums.enum_assertion_type import (
    EnumAssertionType,
)
from omniclaude.nodes.node_ticket_compiler.enums.enum_sandbox_level import (
    EnumSandboxLevel,
)
from omniclaude.nodes.node_ticket_compiler.handler_ticket_compile_default import (
    HandlerTicketCompileDefault,
    _build_acceptance_criteria,
    _derive_permissions,
)
from omniclaude.nodes.node_ticket_compiler.models.model_acceptance_criterion import (
    ModelAcceptanceCriterion,
)
from omniclaude.nodes.node_ticket_compiler.models.model_compiled_ticket import (
    ModelCompiledTicket,
)
from omniclaude.nodes.node_ticket_compiler.models.model_idl_spec import ModelIdlSpec
from omniclaude.nodes.node_ticket_compiler.models.model_policy_envelope import (
    ModelPolicyEnvelope,
)
from omniclaude.nodes.node_ticket_compiler.models.model_ticket_compile_request import (
    ModelTicketCompileRequest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEMA = json.dumps({"type": "object", "properties": {"foo": {"type": "string"}}})


def _request(
    work_unit_type: str = "FEATURE_IMPLEMENTATION", **kwargs: object
) -> ModelTicketCompileRequest:
    defaults: dict[str, object] = {
        "work_unit_id": f"wu-{uuid.uuid4()}",
        "work_unit_title": f"Test work unit: {work_unit_type}",
        "work_unit_description": "A test work unit for unit testing.",
        "work_unit_type": work_unit_type,
        "dag_id": f"dag-{uuid.uuid4()}",
        "intent_id": f"intent-{uuid.uuid4()}",
        "correlation_id": uuid.uuid4(),
    }
    defaults.update(kwargs)
    return ModelTicketCompileRequest(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# R1: IDL Specification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelIdlSpec:
    def test_valid_idl_spec_accepted(self) -> None:
        spec = ModelIdlSpec(
            input_schema=_SCHEMA,
            output_schema=_SCHEMA,
            side_effects=("modifies_source_code",),
        )
        assert spec.input_schema == _SCHEMA
        assert spec.output_schema == _SCHEMA
        assert "modifies_source_code" in spec.side_effects

    def test_invalid_json_input_schema_rejected(self) -> None:
        with pytest.raises(ValidationError, match="valid JSON"):
            ModelIdlSpec(
                input_schema="{not valid json",
                output_schema=_SCHEMA,
            )

    def test_invalid_json_output_schema_rejected(self) -> None:
        with pytest.raises(ValidationError, match="valid JSON"):
            ModelIdlSpec(
                input_schema=_SCHEMA,
                output_schema="not json at all",
            )

    def test_empty_side_effects_allowed(self) -> None:
        spec = ModelIdlSpec(input_schema=_SCHEMA, output_schema=_SCHEMA)
        assert spec.side_effects == ()

    def test_idl_spec_is_frozen(self) -> None:
        spec = ModelIdlSpec(input_schema=_SCHEMA, output_schema=_SCHEMA)
        with pytest.raises(ValidationError):
            spec.input_schema = "{}"  # type: ignore[misc]

    def test_idl_spec_serializable_to_json(self) -> None:
        spec = ModelIdlSpec(
            input_schema=_SCHEMA,
            output_schema=_SCHEMA,
            side_effects=("creates_test_files",),
        )
        serialized = spec.model_dump()
        assert serialized["input_schema"] == _SCHEMA
        assert serialized["side_effects"] == ("creates_test_files",)


# ---------------------------------------------------------------------------
# R2: Test Contract — Acceptance Criteria
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelAcceptanceCriterion:
    def test_valid_criterion_with_command_accepted(self) -> None:
        ac = ModelAcceptanceCriterion(
            criterion_id="wu-001-tests_pass",
            description="All unit tests pass",
            assertion_type=EnumAssertionType.TEST_PASSES,
            expected_value="0",
            verification_command="uv run pytest tests/ -x",
        )
        assert ac.assertion_type == EnumAssertionType.TEST_PASSES

    def test_valid_criterion_with_expected_value_only(self) -> None:
        ac = ModelAcceptanceCriterion(
            criterion_id="wu-001-lint",
            description="Lint is clean",
            assertion_type=EnumAssertionType.LINT_CLEAN,
            expected_value="0",
        )
        assert ac.expected_value == "0"

    def test_prose_only_criterion_rejected(self) -> None:
        """An AC with no expected_value and no command is rejected unless MANUAL_VERIFICATION."""
        with pytest.raises(ValidationError, match="prose-only"):
            ModelAcceptanceCriterion(
                criterion_id="wu-001-vague",
                description="It works somehow",
                assertion_type=EnumAssertionType.COMMAND_EXIT_CODE,
                expected_value="",
                verification_command="",
            )

    def test_manual_verification_without_command_allowed(self) -> None:
        ac = ModelAcceptanceCriterion(
            criterion_id="wu-001-manual",
            description="Reviewed by security team",
            assertion_type=EnumAssertionType.MANUAL_VERIFICATION,
        )
        assert ac.assertion_type == EnumAssertionType.MANUAL_VERIFICATION

    def test_criterion_is_frozen(self) -> None:
        ac = ModelAcceptanceCriterion(
            criterion_id="wu-001-tests_pass",
            description="Tests pass",
            assertion_type=EnumAssertionType.TEST_PASSES,
            expected_value="0",
        )
        with pytest.raises(ValidationError):
            ac.description = "new desc"  # type: ignore[misc]


@pytest.mark.unit
class TestModelCompiledTicketValidation:
    def _make_ticket(
        self,
        acceptance_criteria: tuple[ModelAcceptanceCriterion, ...],
        ticket_id: str | None = None,
    ) -> ModelCompiledTicket:
        tid = ticket_id or str(uuid.uuid4())
        wu_id = str(uuid.uuid4())
        return ModelCompiledTicket(
            ticket_id=tid,
            work_unit_id=wu_id,
            dag_id=f"dag-{uuid.uuid4()}",
            intent_id=f"intent-{uuid.uuid4()}",
            title="Test ticket",
            idl_spec=ModelIdlSpec(input_schema=_SCHEMA, output_schema=_SCHEMA),
            acceptance_criteria=acceptance_criteria,
            policy_envelope=ModelPolicyEnvelope(),
        )

    def _verifiable_ac(self, suffix: str = "tests") -> ModelAcceptanceCriterion:
        return ModelAcceptanceCriterion(
            criterion_id=f"wu-001-{suffix}",
            description="Tests pass",
            assertion_type=EnumAssertionType.TEST_PASSES,
            expected_value="0",
            verification_command="uv run pytest tests/ -x",
        )

    def test_ticket_with_verifiable_ac_accepted(self) -> None:
        ticket = self._make_ticket((self._verifiable_ac(),))
        assert len(ticket.acceptance_criteria) == 1

    def test_ticket_with_no_acs_rejected(self) -> None:
        with pytest.raises(ValidationError, match="no acceptance criteria"):
            self._make_ticket(())

    def test_ticket_with_only_manual_acs_rejected(self) -> None:
        manual_ac = ModelAcceptanceCriterion(
            criterion_id="wu-001-manual",
            description="Manually reviewed",
            assertion_type=EnumAssertionType.MANUAL_VERIFICATION,
        )
        with pytest.raises(ValidationError, match="MANUAL_VERIFICATION"):
            self._make_ticket((manual_ac,))

    def test_ticket_with_mixed_acs_accepted(self) -> None:
        manual_ac = ModelAcceptanceCriterion(
            criterion_id="wu-001-manual",
            description="Manually reviewed",
            assertion_type=EnumAssertionType.MANUAL_VERIFICATION,
        )
        ticket = self._make_ticket((self._verifiable_ac(), manual_ac))
        assert len(ticket.acceptance_criteria) == 2

    def test_compiled_ticket_is_frozen(self) -> None:
        ticket = self._make_ticket((self._verifiable_ac(),))
        with pytest.raises(ValidationError):
            ticket.title = "new title"  # type: ignore[misc]

    def test_compiled_ticket_serializable(self) -> None:
        ticket = self._make_ticket((self._verifiable_ac(),))
        data = ticket.model_dump()
        assert data["title"] == "Test ticket"
        assert len(data["acceptance_criteria"]) == 1


# ---------------------------------------------------------------------------
# R3: Policy Envelope
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelPolicyEnvelope:
    def test_default_policy_envelope_accepted(self) -> None:
        env = ModelPolicyEnvelope()
        assert env.sandbox_level == EnumSandboxLevel.STANDARD
        assert env.allows_network_access is False
        assert env.allows_filesystem_write is True

    def test_enforced_sandbox_with_network_access_rejected(self) -> None:
        with pytest.raises(ValidationError, match="network access"):
            ModelPolicyEnvelope(
                sandbox_level=EnumSandboxLevel.ENFORCED,
                allows_network_access=True,
            )

    def test_isolated_sandbox_with_network_access_rejected(self) -> None:
        with pytest.raises(ValidationError, match="network access"):
            ModelPolicyEnvelope(
                sandbox_level=EnumSandboxLevel.ISOLATED,
                allows_network_access=True,
            )

    def test_standard_sandbox_with_network_access_allowed(self) -> None:
        env = ModelPolicyEnvelope(
            sandbox_level=EnumSandboxLevel.STANDARD,
            allows_network_access=True,
        )
        assert env.allows_network_access is True

    def test_none_sandbox_with_network_access_allowed(self) -> None:
        env = ModelPolicyEnvelope(
            sandbox_level=EnumSandboxLevel.NONE,
            allows_network_access=True,
        )
        assert env.allows_network_access is True

    def test_policy_envelope_is_frozen(self) -> None:
        env = ModelPolicyEnvelope()
        with pytest.raises(ValidationError):
            env.sandbox_level = EnumSandboxLevel.ISOLATED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildAcceptanceCriteria:
    def test_pytest_command_yields_test_passes(self) -> None:
        criteria = _build_acceptance_criteria(
            work_unit_id="wu-001",
            ac_specs=[("tests", "All tests pass", "uv run pytest tests/ -x")],
        )
        assert len(criteria) == 1
        assert criteria[0].assertion_type == EnumAssertionType.TEST_PASSES
        assert criteria[0].expected_value == "0"

    def test_ruff_command_yields_lint_clean(self) -> None:
        criteria = _build_acceptance_criteria(
            work_unit_id="wu-001",
            ac_specs=[("lint", "No lint errors", "uv run ruff check src/")],
        )
        assert criteria[0].assertion_type == EnumAssertionType.LINT_CLEAN

    def test_mypy_command_yields_type_check_passes(self) -> None:
        criteria = _build_acceptance_criteria(
            work_unit_id="wu-001",
            ac_specs=[("types", "No mypy errors", "uv run mypy src/")],
        )
        assert criteria[0].assertion_type == EnumAssertionType.TYPE_CHECK_PASSES

    def test_test_f_command_yields_file_exists(self) -> None:
        criteria = _build_acceptance_criteria(
            work_unit_id="wu-001",
            ac_specs=[("exists", "File exists", "test -f docs/README.md")],
        )
        assert criteria[0].assertion_type == EnumAssertionType.FILE_EXISTS

    def test_empty_command_yields_pr_review_approved(self) -> None:
        criteria = _build_acceptance_criteria(
            work_unit_id="wu-001",
            ac_specs=[("approved", "PR approved", "")],
        )
        assert criteria[0].assertion_type == EnumAssertionType.PR_REVIEW_APPROVED
        assert criteria[0].expected_value == "approved"

    def test_custom_command_yields_command_exit_code(self) -> None:
        criteria = _build_acceptance_criteria(
            work_unit_id="wu-001",
            ac_specs=[("validate", "Validation passes", "make validate")],
        )
        assert criteria[0].assertion_type == EnumAssertionType.COMMAND_EXIT_CODE

    def test_criterion_id_includes_work_unit_id(self) -> None:
        criteria = _build_acceptance_criteria(
            work_unit_id="wu-abc-123",
            ac_specs=[("tests", "Tests pass", "uv run pytest tests/ -x")],
        )
        assert criteria[0].criterion_id == "wu-abc-123-tests"


@pytest.mark.unit
class TestDerivePermissions:
    def test_base_permission_always_included(self) -> None:
        perms = _derive_permissions(EnumSandboxLevel.STANDARD, ())
        assert "read:repository" in perms

    def test_modifies_source_code_adds_write_permission(self) -> None:
        perms = _derive_permissions(
            EnumSandboxLevel.STANDARD, ("modifies_source_code",)
        )
        assert "write:source_code" in perms

    def test_creates_test_files_adds_write_tests(self) -> None:
        perms = _derive_permissions(EnumSandboxLevel.STANDARD, ("creates_test_files",))
        assert "write:tests" in perms

    def test_creates_documentation_files_adds_write_documentation(self) -> None:
        perms = _derive_permissions(
            EnumSandboxLevel.STANDARD, ("creates_documentation_files",)
        )
        assert "write:documentation" in perms

    def test_modifies_infrastructure_adds_write_infrastructure(self) -> None:
        perms = _derive_permissions(
            EnumSandboxLevel.STANDARD, ("modifies_infrastructure",)
        )
        assert "write:infrastructure" in perms

    def test_may_create_cloud_resources_adds_provision(self) -> None:
        perms = _derive_permissions(
            EnumSandboxLevel.STANDARD, ("may_create_cloud_resources",)
        )
        assert "provision:cloud_resources" in perms

    def test_may_modify_secrets_adds_write_secrets(self) -> None:
        perms = _derive_permissions(EnumSandboxLevel.STANDARD, ("may_modify_secrets",))
        assert "write:secrets" in perms

    def test_creates_linear_epic_adds_write_tickets(self) -> None:
        perms = _derive_permissions(EnumSandboxLevel.STANDARD, ("creates_linear_epic",))
        assert "write:linear_tickets" in perms

    def test_none_sandbox_adds_network_outbound(self) -> None:
        perms = _derive_permissions(EnumSandboxLevel.NONE, ())
        assert "network:outbound" in perms

    def test_standard_sandbox_no_network_outbound(self) -> None:
        perms = _derive_permissions(EnumSandboxLevel.STANDARD, ())
        assert "network:outbound" not in perms


# ---------------------------------------------------------------------------
# HandlerTicketCompileDefault — end-to-end ticket compilation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerTicketCompileDefault:
    def setup_method(self) -> None:
        self.handler = HandlerTicketCompileDefault()

    def test_handler_key_is_default(self) -> None:
        assert self.handler.handler_key == "default"

    @pytest.mark.parametrize(
        "work_unit_type",
        [
            "FEATURE_IMPLEMENTATION",
            "BUG_FIX",
            "REFACTORING",
            "TEST_SUITE",
            "DOCUMENTATION",
            "INFRASTRUCTURE",
            "SECURITY_PATCH",
            "CODE_REVIEW",
            "INVESTIGATION",
            "EPIC_TICKET",
            "GENERIC",
        ],
    )
    def test_compile_ticket_succeeds_for_all_unit_types(
        self, work_unit_type: str
    ) -> None:
        req = _request(work_unit_type)
        ticket = self.handler.compile_ticket(req)
        assert ticket.work_unit_id == req.work_unit_id
        assert ticket.intent_id == req.intent_id
        assert ticket.dag_id == req.dag_id
        assert ticket.title == req.work_unit_title

    def test_compiled_ticket_has_verifiable_ac(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION")
        ticket = self.handler.compile_ticket(req)
        verifiable = [
            ac
            for ac in ticket.acceptance_criteria
            if ac.assertion_type != EnumAssertionType.MANUAL_VERIFICATION
        ]
        assert len(verifiable) >= 1

    def test_feature_implementation_has_idl_spec(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION")
        ticket = self.handler.compile_ticket(req)
        assert ticket.idl_spec.input_schema
        parsed = json.loads(ticket.idl_spec.input_schema)
        assert parsed["type"] == "object"
        assert "context" in parsed["properties"]

    def test_feature_implementation_has_source_code_side_effect(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION")
        ticket = self.handler.compile_ticket(req)
        assert "modifies_source_code" in ticket.idl_spec.side_effects

    def test_security_patch_uses_enforced_sandbox(self) -> None:
        req = _request("SECURITY_PATCH")
        ticket = self.handler.compile_ticket(req)
        assert ticket.policy_envelope.sandbox_level == EnumSandboxLevel.ENFORCED

    def test_documentation_uses_none_sandbox(self) -> None:
        req = _request("DOCUMENTATION")
        ticket = self.handler.compile_ticket(req)
        assert ticket.policy_envelope.sandbox_level == EnumSandboxLevel.NONE

    def test_unknown_type_falls_back_to_generic(self) -> None:
        req = _request("UNKNOWN_TYPE_XYZ")
        ticket = self.handler.compile_ticket(req)
        assert ticket.work_unit_id == req.work_unit_id
        assert len(ticket.acceptance_criteria) >= 1

    def test_ticket_description_contains_ac_section(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION")
        ticket = self.handler.compile_ticket(req)
        assert "## Acceptance Criteria" in ticket.description

    def test_ticket_description_contains_idl_section(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION")
        ticket = self.handler.compile_ticket(req)
        assert "## IDL Specification" in ticket.description

    def test_ticket_description_contains_policy_section(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION")
        ticket = self.handler.compile_ticket(req)
        assert "## Policy Envelope" in ticket.description

    def test_ticket_description_references_intent_and_dag(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION")
        ticket = self.handler.compile_ticket(req)
        assert req.intent_id in ticket.description
        assert req.dag_id in ticket.description

    def test_parent_ticket_id_propagated(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION", parent_ticket_id="PARENT-123")
        ticket = self.handler.compile_ticket(req)
        assert ticket.parent_ticket_id == "PARENT-123"

    def test_team_propagated(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION", team="backend-team")
        ticket = self.handler.compile_ticket(req)
        assert ticket.team == "backend-team"

    def test_security_patch_has_security_validators(self) -> None:
        req = _request("SECURITY_PATCH")
        ticket = self.handler.compile_ticket(req)
        assert "security_audit" in ticket.policy_envelope.required_validators

    def test_feature_implementation_has_code_validators(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION")
        ticket = self.handler.compile_ticket(req)
        assert "code_quality" in ticket.policy_envelope.required_validators

    def test_compiled_ticket_has_stable_unique_id(self) -> None:
        req = _request("FEATURE_IMPLEMENTATION")
        ticket1 = self.handler.compile_ticket(req)
        ticket2 = self.handler.compile_ticket(req)
        # Two compilations of same request should produce different ticket IDs (UUID each time)
        assert ticket1.ticket_id != ticket2.ticket_id

    def test_infrastructure_has_enforced_sandbox(self) -> None:
        req = _request("INFRASTRUCTURE")
        ticket = self.handler.compile_ticket(req)
        assert ticket.policy_envelope.sandbox_level == EnumSandboxLevel.ENFORCED

    def test_bug_fix_has_regression_test_ac(self) -> None:
        req = _request("BUG_FIX")
        ticket = self.handler.compile_ticket(req)
        commands = [ac.verification_command for ac in ticket.acceptance_criteria]
        assert any("regression" in cmd for cmd in commands)

    def test_test_suite_has_coverage_ac(self) -> None:
        req = _request("TEST_SUITE")
        ticket = self.handler.compile_ticket(req)
        commands = [ac.verification_command for ac in ticket.acceptance_criteria]
        assert any("cov" in cmd for cmd in commands)

    def test_work_unit_description_included_in_ticket_description(self) -> None:
        req = _request(
            "FEATURE_IMPLEMENTATION", work_unit_description="Custom description here."
        )
        ticket = self.handler.compile_ticket(req)
        assert "Custom description here." in ticket.description

    def test_empty_description_uses_placeholder(self) -> None:
        req = _request("GENERIC", work_unit_description="")
        ticket = self.handler.compile_ticket(req)
        assert "_No description provided._" in ticket.description
