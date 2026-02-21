# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Default Ticket Compiler handler.

Compiles a Plan DAG work unit into an executable ModelCompiledTicket with:
- IDL spec (input/output schemas + declared side effects)
- Test contract (verifiable acceptance criteria, no prose-only ACs)
- Policy envelope (validators, permission scope, sandbox constraints)

All validation is enforced at construction time via Pydantic model validators.
"""

from __future__ import annotations

import json
import logging
import uuid

from omniclaude.nodes.node_ticket_compiler.enums.enum_assertion_type import (
    EnumAssertionType,
)
from omniclaude.nodes.node_ticket_compiler.enums.enum_sandbox_level import (
    EnumSandboxLevel,
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

__all__ = ["HandlerTicketCompileDefault"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Work unit type → IDL / policy templates
# ---------------------------------------------------------------------------

_SECURITY_VALIDATORS = ("security_audit", "least_privilege")
_CODE_VALIDATORS = ("code_quality", "style")
_TEST_VALIDATORS = ("test_coverage",)


def _make_schema(properties: dict[str, str]) -> str:
    """Build a minimal JSON Schema string from a property→description map."""
    schema = {
        "type": "object",
        "properties": {
            name: {"type": "string", "description": desc}
            for name, desc in properties.items()
        },
    }
    return json.dumps(schema)


# Maps work unit type → (input_schema, output_schema, side_effects, sandbox, validators, acs)
_UNIT_TYPE_TEMPLATES: dict[
    str,
    tuple[
        str,
        str,
        tuple[str, ...],
        EnumSandboxLevel,
        tuple[str, ...],
        list[tuple[str, str, str]],
    ],
] = {
    "FEATURE_IMPLEMENTATION": (
        _make_schema(
            {"context": "Feature context from intent", "scope": "T-shirt scope"}
        ),
        _make_schema(
            {"files_changed": "Modified/created files", "tests_added": "New test files"}
        ),
        ("modifies_source_code",),
        EnumSandboxLevel.STANDARD,
        _CODE_VALIDATORS,
        [
            ("tests_pass", "All unit tests pass", "uv run pytest tests/ -x"),
            ("lint_clean", "No lint errors", "uv run ruff check src/ tests/"),
            ("types_pass", "No mypy errors", "uv run mypy src/"),
        ],
    ),
    "BUG_FIX": (
        _make_schema(
            {"bug_description": "Description of the bug", "root_cause": "Root cause"}
        ),
        _make_schema(
            {"fix_description": "What was fixed", "regression_test": "Test added"}
        ),
        ("modifies_source_code",),
        EnumSandboxLevel.STANDARD,
        _CODE_VALIDATORS,
        [
            (
                "regression_test",
                "Regression test added and passing",
                "uv run pytest tests/ -k regression",
            ),
            ("tests_pass", "All tests pass", "uv run pytest tests/ -x"),
        ],
    ),
    "REFACTORING": (
        _make_schema(
            {"scope": "Files/modules to refactor", "goals": "Refactoring goals"}
        ),
        _make_schema(
            {"files_changed": "Refactored files", "behavior_preserved": "Verification"}
        ),
        ("modifies_source_code",),
        EnumSandboxLevel.STANDARD,
        _CODE_VALIDATORS,
        [
            (
                "tests_pass",
                "All tests pass after refactoring",
                "uv run pytest tests/ -x",
            ),
            ("lint_clean", "Lint clean after refactoring", "uv run ruff check src/"),
        ],
    ),
    "TEST_SUITE": (
        _make_schema(
            {"target_module": "Module to test", "coverage_target": "Coverage %"}
        ),
        _make_schema(
            {"test_files": "Created test files", "coverage_report": "Coverage report"}
        ),
        ("creates_test_files",),
        EnumSandboxLevel.STANDARD,
        _TEST_VALIDATORS,
        [
            ("tests_pass", "New tests pass", "uv run pytest tests/ -x"),
            ("coverage_met", "Coverage meets target", "uv run pytest --cov"),
        ],
    ),
    "DOCUMENTATION": (
        _make_schema({"topic": "Documentation topic", "audience": "Target audience"}),
        _make_schema({"files_created": "Created documentation files"}),
        ("creates_documentation_files",),
        EnumSandboxLevel.NONE,
        (),
        [
            ("file_exists", "Documentation file created", "test -f docs/"),
        ],
    ),
    "INFRASTRUCTURE": (
        _make_schema(
            {"component": "Infrastructure component", "environment": "Target env"}
        ),
        _make_schema(
            {
                "resources_created": "Created resources",
                "validation_result": "Validation",
            }
        ),
        ("modifies_infrastructure", "may_create_cloud_resources"),
        EnumSandboxLevel.ENFORCED,
        ("infrastructure_validator",),
        [
            ("validation_pass", "Infrastructure validation passes", "make validate"),
        ],
    ),
    "SECURITY_PATCH": (
        _make_schema(
            {
                "vulnerability": "Vulnerability description",
                "cve": "CVE ID if applicable",
            }
        ),
        _make_schema(
            {"patch_applied": "Patch description", "tests_added": "Security tests"}
        ),
        ("modifies_source_code", "may_modify_secrets"),
        EnumSandboxLevel.ENFORCED,
        _SECURITY_VALIDATORS,
        [
            (
                "security_tests",
                "Security regression tests pass",
                "uv run pytest tests/ -k security",
            ),
            (
                "no_new_vulns",
                "No new vulnerabilities introduced",
                "uv run bandit -r src/",
            ),
        ],
    ),
    "CODE_REVIEW": (
        _make_schema({"pr_url": "Pull request URL", "review_scope": "Review scope"}),
        _make_schema(
            {
                "review_result": "Approved/Changes requested",
                "comments": "Review comments",
            }
        ),
        (),
        EnumSandboxLevel.NONE,
        _CODE_VALIDATORS,
        [
            ("pr_approved", "PR approved by reviewer", ""),
        ],
    ),
    "INVESTIGATION": (
        _make_schema(
            {"question": "Question to investigate", "scope": "Investigation scope"}
        ),
        _make_schema(
            {
                "findings": "Investigation findings",
                "recommendation": "Recommended action",
            }
        ),
        (),
        EnumSandboxLevel.STANDARD,
        (),
        [
            ("report_exists", "Investigation report created", "test -f"),
        ],
    ),
    "EPIC_TICKET": (
        _make_schema(
            {"epic_title": "Epic title", "sub_tickets": "Sub-ticket descriptions"}
        ),
        _make_schema({"linear_epic_id": "Created Linear epic ID"}),
        ("creates_linear_epic",),
        EnumSandboxLevel.NONE,
        (),
        [
            ("epic_created", "Linear epic created", ""),
        ],
    ),
    "GENERIC": (
        _make_schema({"description": "Task description"}),
        _make_schema({"result": "Task result"}),
        (),
        EnumSandboxLevel.STANDARD,
        (),
        [
            ("task_done", "Task completed as described", ""),
        ],
    ),
}


class HandlerTicketCompileDefault:
    """Default handler for Plan DAG work unit → Compiled Ticket.

    Produces a ModelCompiledTicket by mapping work unit type to a canonical
    IDL template, test contract, and policy envelope.
    """

    @property
    def handler_key(self) -> str:
        """Registry key for handler lookup."""
        return "default"

    def compile_ticket(
        self,
        request: ModelTicketCompileRequest,
    ) -> ModelCompiledTicket:
        """Compile a work unit into an executable ticket.

        Args:
            request: Compile request containing work unit metadata.

        Returns:
            ModelCompiledTicket with IDL, test contract, and policy envelope.

        Raises:
            ValueError: If compilation produces a ticket with no verifiable ACs.
        """
        ticket_id = str(uuid.uuid4())

        template = _UNIT_TYPE_TEMPLATES.get(
            request.work_unit_type.upper(),
            _UNIT_TYPE_TEMPLATES["GENERIC"],
        )
        (
            input_schema,
            output_schema,
            side_effects,
            sandbox_level,
            validators,
            ac_specs,
        ) = template

        idl_spec = ModelIdlSpec(
            input_schema=input_schema,
            output_schema=output_schema,
            side_effects=side_effects,
        )

        acceptance_criteria = _build_acceptance_criteria(
            work_unit_id=request.work_unit_id,
            ac_specs=ac_specs,
        )

        policy_envelope = ModelPolicyEnvelope(
            required_validators=validators,
            permission_scope=_derive_permissions(sandbox_level, side_effects),
            sandbox_level=sandbox_level,
            allows_network_access=sandbox_level
            not in (EnumSandboxLevel.ENFORCED, EnumSandboxLevel.ISOLATED),
            allows_filesystem_write=True,
        )

        description = _build_description(
            request, idl_spec, acceptance_criteria, policy_envelope
        )

        logger.debug(
            "Compiled ticket %s for work_unit=%s (type=%s, ACs=%d)",
            ticket_id,
            request.work_unit_id,
            request.work_unit_type,
            len(acceptance_criteria),
        )

        return ModelCompiledTicket(
            ticket_id=ticket_id,
            work_unit_id=request.work_unit_id,
            dag_id=request.dag_id,
            intent_id=request.intent_id,
            title=request.work_unit_title,
            description=description,
            idl_spec=idl_spec,
            acceptance_criteria=acceptance_criteria,
            policy_envelope=policy_envelope,
            parent_ticket_id=request.parent_ticket_id,
            team=request.team,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_acceptance_criteria(
    *,
    work_unit_id: str,
    ac_specs: list[tuple[str, str, str]],
) -> tuple[ModelAcceptanceCriterion, ...]:
    """Build acceptance criteria from template specs.

    Args:
        work_unit_id: Source work unit ID (used in criterion IDs).
        ac_specs: List of (suffix, description, verification_command) tuples.

    Returns:
        Tuple of ModelAcceptanceCriterion.
    """
    criteria: list[ModelAcceptanceCriterion] = []

    for suffix, description, command in ac_specs:
        criterion_id = f"{work_unit_id}-{suffix}"

        # Determine assertion type from command pattern
        if command.startswith("uv run pytest"):
            assertion_type = EnumAssertionType.TEST_PASSES
            expected_value = "0"
        elif command.startswith("uv run ruff"):
            assertion_type = EnumAssertionType.LINT_CLEAN
            expected_value = "0"
        elif command.startswith("uv run mypy"):
            assertion_type = EnumAssertionType.TYPE_CHECK_PASSES
            expected_value = "0"
        elif command.startswith("test -f") or command.startswith("ls "):
            assertion_type = EnumAssertionType.FILE_EXISTS
            expected_value = "true"
        elif not command:
            assertion_type = EnumAssertionType.PR_REVIEW_APPROVED
            expected_value = "approved"
        else:
            assertion_type = EnumAssertionType.COMMAND_EXIT_CODE
            expected_value = "0"

        criteria.append(
            ModelAcceptanceCriterion(
                criterion_id=criterion_id,
                description=description,
                assertion_type=assertion_type,
                expected_value=expected_value,
                verification_command=command,
            )
        )

    return tuple(criteria)


def _derive_permissions(
    sandbox_level: EnumSandboxLevel,
    side_effects: tuple[str, ...],
) -> tuple[str, ...]:
    """Derive required permissions from sandbox level and declared side effects.

    Args:
        sandbox_level: Sandbox isolation level.
        side_effects: Declared side effects from the IDL spec.

    Returns:
        Tuple of required permission strings.
    """
    permissions: list[str] = ["read:repository"]

    if "modifies_source_code" in side_effects:
        permissions.append("write:source_code")
    if "creates_test_files" in side_effects:
        permissions.append("write:tests")
    if "creates_documentation_files" in side_effects:
        permissions.append("write:documentation")
    if "modifies_infrastructure" in side_effects:
        permissions.append("write:infrastructure")
    if "may_create_cloud_resources" in side_effects:
        permissions.append("provision:cloud_resources")
    if "may_modify_secrets" in side_effects:
        permissions.append("write:secrets")
    if "creates_linear_epic" in side_effects:
        permissions.append("write:linear_tickets")

    if sandbox_level == EnumSandboxLevel.NONE:
        permissions.append("network:outbound")

    return tuple(permissions)


def _build_description(
    request: ModelTicketCompileRequest,
    idl_spec: ModelIdlSpec,
    acceptance_criteria: tuple[ModelAcceptanceCriterion, ...],
    policy_envelope: ModelPolicyEnvelope,
) -> str:
    """Build a Markdown ticket description from compiled components.

    Args:
        request: Original compile request.
        idl_spec: Compiled IDL specification.
        acceptance_criteria: Verifiable acceptance criteria.
        policy_envelope: Policy constraints.

    Returns:
        Markdown string suitable for a Linear ticket body.
    """
    lines = [
        f"## {request.work_unit_title}",
        "",
        request.work_unit_description or "_No description provided._",
        "",
        "## IDL Specification",
        "",
        "### Inputs",
        f"```json\n{idl_spec.input_schema}\n```",
        "",
        "### Outputs",
        f"```json\n{idl_spec.output_schema}\n```",
        "",
    ]

    if idl_spec.side_effects:
        lines += [
            "### Declared Side Effects",
            "",
            *[f"- `{se}`" for se in idl_spec.side_effects],
            "",
        ]

    lines += [
        "## Acceptance Criteria",
        "",
    ]
    for ac in acceptance_criteria:
        cmd_note = f" (`{ac.verification_command}`)" if ac.verification_command else ""
        lines.append(f"- [ ] **{ac.description}**{cmd_note}")

    lines += [
        "",
        "## Policy Envelope",
        "",
        f"- Sandbox: `{policy_envelope.sandbox_level.value}`",
        f"- Validators: {', '.join(f'`{v}`' for v in policy_envelope.required_validators) or 'none'}",
        f"- Network access: `{policy_envelope.allows_network_access}`",
        "",
        "---",
        f"*Generated from intent `{request.intent_id}` / DAG `{request.dag_id}`*",
    ]

    return "\n".join(lines)
