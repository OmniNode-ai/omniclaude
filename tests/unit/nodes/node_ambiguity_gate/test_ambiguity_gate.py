# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for the Ambiguity Gate (OMN-2504).

Test markers:
    @pytest.mark.unit  — all tests here

Coverage:
- R1: Detect ambiguity in Plan DAG nodes before ticket generation
  - Each DAG node is evaluated for ambiguity
  - Ambiguity types are enumerated and typed
  - Nodes with unresolved ambiguity are quarantined (AmbiguityGateError raised)
- R2: Reject tickets with unresolved ambiguity
  - Compilation raises AmbiguityGateError for ambiguous nodes
  - Error includes: which node, which ambiguity type, suggested resolution
  - No ticket is emitted for a node that fails the ambiguity gate
- R3: Ambiguity resolution paths are auditable
  - AmbiguityGateError.result carries full flag detail traceable to source
  - Flags include field_name and suggested_resolution
"""

from __future__ import annotations

import uuid

import pytest

from omniclaude.nodes.node_ambiguity_gate.enums.enum_ambiguity_type import (
    EnumAmbiguityType,
)
from omniclaude.nodes.node_ambiguity_gate.enums.enum_gate_verdict import EnumGateVerdict
from omniclaude.nodes.node_ambiguity_gate.handler_ambiguity_gate_default import (
    HandlerAmbiguityGateDefault,
    _check_description,
    _check_required_context,
    _check_title,
    _check_unit_type,
    _detect_ambiguities,
)
from omniclaude.nodes.node_ambiguity_gate.models.model_ambiguity_flag import (
    ModelAmbiguityFlag,
)
from omniclaude.nodes.node_ambiguity_gate.models.model_ambiguity_gate_error import (
    AmbiguityGateError,
)
from omniclaude.nodes.node_ambiguity_gate.models.model_gate_check_request import (
    ModelGateCheckRequest,
)
from omniclaude.nodes.node_ambiguity_gate.models.model_gate_check_result import (
    ModelGateCheckResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(
    unit_title: str = "Add OAuth2 login endpoint to AuthService",
    unit_type: str = "FEATURE_IMPLEMENTATION",
    unit_description: str = "Implement OAuth2 login using the existing session manager.",
    estimated_scope: str = "M",
    context: tuple[tuple[str, str], ...] = (),
    **kwargs: object,
) -> ModelGateCheckRequest:
    defaults: dict[str, object] = {
        "unit_id": f"wu-{uuid.uuid4()}",
        "unit_title": unit_title,
        "unit_type": unit_type,
        "unit_description": unit_description,
        "estimated_scope": estimated_scope,
        "context": context,
        "dag_id": f"dag-{uuid.uuid4()}",
        "intent_id": f"intent-{uuid.uuid4()}",
        "correlation_id": uuid.uuid4(),
    }
    defaults.update(kwargs)
    return ModelGateCheckRequest(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# R1: Ambiguity detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAmbiguityFlagModel:
    def test_valid_flag_accepted(self) -> None:
        flag = ModelAmbiguityFlag(
            ambiguity_type=EnumAmbiguityType.TITLE_TOO_VAGUE,
            description="Title is too short",
            suggested_resolution="Expand the title",
            field_name="unit_title",
        )
        assert flag.ambiguity_type == EnumAmbiguityType.TITLE_TOO_VAGUE

    def test_flag_is_frozen(self) -> None:
        flag = ModelAmbiguityFlag(
            ambiguity_type=EnumAmbiguityType.DESCRIPTION_MISSING,
            description="No description",
        )
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            flag.description = "new"  # type: ignore[misc]

    def test_flag_optional_fields_default(self) -> None:
        flag = ModelAmbiguityFlag(
            ambiguity_type=EnumAmbiguityType.SCOPE_UNDEFINED,
            description="Scope missing",
        )
        assert flag.suggested_resolution == ""
        assert flag.field_name == ""


@pytest.mark.unit
class TestGateCheckResultModel:
    def test_pass_result_has_no_flags(self) -> None:
        result = ModelGateCheckResult(
            unit_id="wu-001",
            verdict=EnumGateVerdict.PASS,
            ambiguity_flags=(),
            dag_id="dag-001",
            intent_id="intent-001",
        )
        assert result.verdict == EnumGateVerdict.PASS
        assert len(result.ambiguity_flags) == 0

    def test_fail_result_has_flags(self) -> None:
        flag = ModelAmbiguityFlag(
            ambiguity_type=EnumAmbiguityType.TITLE_TOO_VAGUE,
            description="Too vague",
        )
        result = ModelGateCheckResult(
            unit_id="wu-001",
            verdict=EnumGateVerdict.FAIL,
            ambiguity_flags=(flag,),
            dag_id="dag-001",
            intent_id="intent-001",
        )
        assert result.verdict == EnumGateVerdict.FAIL
        assert len(result.ambiguity_flags) == 1

    def test_result_is_frozen(self) -> None:
        result = ModelGateCheckResult(
            unit_id="wu-001",
            verdict=EnumGateVerdict.PASS,
            dag_id="dag-001",
            intent_id="intent-001",
        )
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            result.verdict = EnumGateVerdict.FAIL  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Title ambiguity detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckTitle:
    def test_clear_title_no_flag(self) -> None:
        req = _request(unit_title="Add OAuth2 login endpoint to AuthService")
        flags: list[ModelAmbiguityFlag] = []
        _check_title(req, flags)
        assert len(flags) == 0

    def test_one_word_title_flagged(self) -> None:
        req = _request(unit_title="Fix")
        flags: list[ModelAmbiguityFlag] = []
        _check_title(req, flags)
        assert len(flags) == 1
        assert flags[0].ambiguity_type == EnumAmbiguityType.TITLE_TOO_VAGUE

    def test_two_word_title_flagged(self) -> None:
        req = _request(unit_title="Fix bug")
        flags: list[ModelAmbiguityFlag] = []
        _check_title(req, flags)
        assert len(flags) == 1

    def test_three_word_title_passes(self) -> None:
        req = _request(unit_title="Fix login bug")
        flags: list[ModelAmbiguityFlag] = []
        _check_title(req, flags)
        assert len(flags) == 0

    def test_flag_contains_suggested_resolution(self) -> None:
        req = _request(unit_title="Do something")
        flags: list[ModelAmbiguityFlag] = []
        _check_title(req, flags)
        # Two words, not flagged; confirm no spurious flag
        assert len(flags) == 1
        assert flags[0].suggested_resolution

    def test_flag_references_field_name(self) -> None:
        req = _request(unit_title="Fix")
        flags: list[ModelAmbiguityFlag] = []
        _check_title(req, flags)
        assert flags[0].field_name == "unit_title"


# ---------------------------------------------------------------------------
# Description ambiguity detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckDescription:
    def test_adequate_description_no_flag(self) -> None:
        req = _request(
            unit_description="Implement OAuth2 login using the existing session manager."
        )
        flags: list[ModelAmbiguityFlag] = []
        _check_description(req, flags)
        assert len(flags) == 0

    def test_empty_description_flagged(self) -> None:
        req = _request(unit_description="")
        flags: list[ModelAmbiguityFlag] = []
        _check_description(req, flags)
        assert len(flags) == 1
        assert flags[0].ambiguity_type == EnumAmbiguityType.DESCRIPTION_MISSING

    def test_whitespace_only_description_flagged(self) -> None:
        req = _request(unit_description="   \n  ")
        flags: list[ModelAmbiguityFlag] = []
        _check_description(req, flags)
        assert len(flags) == 1

    def test_very_short_description_flagged(self) -> None:
        req = _request(unit_description="do it")
        flags: list[ModelAmbiguityFlag] = []
        _check_description(req, flags)
        assert len(flags) == 1

    def test_flag_references_field_name(self) -> None:
        req = _request(unit_description="")
        flags: list[ModelAmbiguityFlag] = []
        _check_description(req, flags)
        assert flags[0].field_name == "unit_description"


# ---------------------------------------------------------------------------
# Unit type ambiguity detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckUnitType:
    def test_known_type_no_flag(self) -> None:
        req = _request(unit_type="FEATURE_IMPLEMENTATION")
        flags: list[ModelAmbiguityFlag] = []
        _check_unit_type(req, flags)
        assert len(flags) == 0

    def test_generic_type_flagged(self) -> None:
        req = _request(unit_type="GENERIC")
        flags: list[ModelAmbiguityFlag] = []
        _check_unit_type(req, flags)
        assert len(flags) == 1
        assert flags[0].ambiguity_type == EnumAmbiguityType.UNKNOWN_UNIT_TYPE

    def test_unknown_type_flagged(self) -> None:
        req = _request(unit_type="UNKNOWN")
        flags: list[ModelAmbiguityFlag] = []
        _check_unit_type(req, flags)
        assert len(flags) == 1

    def test_case_insensitive_generic_flagged(self) -> None:
        req = _request(unit_type="generic")
        flags: list[ModelAmbiguityFlag] = []
        _check_unit_type(req, flags)
        assert len(flags) == 1

    def test_bug_fix_not_flagged(self) -> None:
        req = _request(unit_type="BUG_FIX")
        flags: list[ModelAmbiguityFlag] = []
        _check_unit_type(req, flags)
        assert len(flags) == 0

    def test_flag_references_field_name(self) -> None:
        req = _request(unit_type="GENERIC")
        flags: list[ModelAmbiguityFlag] = []
        _check_unit_type(req, flags)
        assert flags[0].field_name == "unit_type"


# ---------------------------------------------------------------------------
# Required context ambiguity detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckRequiredContext:
    def test_non_contextual_type_no_flag(self) -> None:
        req = _request(unit_type="FEATURE_IMPLEMENTATION", context=())
        flags: list[ModelAmbiguityFlag] = []
        _check_required_context(req, flags)
        assert len(flags) == 0

    def test_security_patch_missing_vulnerability_flagged(self) -> None:
        req = _request(unit_type="SECURITY_PATCH", context=())
        flags: list[ModelAmbiguityFlag] = []
        _check_required_context(req, flags)
        assert len(flags) == 1
        assert flags[0].ambiguity_type == EnumAmbiguityType.MISSING_REQUIRED_CONTEXT
        assert "vulnerability" in flags[0].description

    def test_security_patch_with_vulnerability_key_passes(self) -> None:
        req = _request(
            unit_type="SECURITY_PATCH",
            context=(("vulnerability", "SQL injection in login form"),),
        )
        flags: list[ModelAmbiguityFlag] = []
        _check_required_context(req, flags)
        assert len(flags) == 0

    def test_code_review_missing_pr_url_flagged(self) -> None:
        req = _request(unit_type="CODE_REVIEW", context=())
        flags: list[ModelAmbiguityFlag] = []
        _check_required_context(req, flags)
        assert len(flags) == 1
        assert "pr_url" in flags[0].description

    def test_infrastructure_missing_component_flagged(self) -> None:
        req = _request(unit_type="INFRASTRUCTURE", context=())
        flags: list[ModelAmbiguityFlag] = []
        _check_required_context(req, flags)
        assert len(flags) == 1
        assert "component" in flags[0].description

    def test_flag_references_context_field(self) -> None:
        req = _request(unit_type="SECURITY_PATCH", context=())
        flags: list[ModelAmbiguityFlag] = []
        _check_required_context(req, flags)
        assert flags[0].field_name == "context"

    def test_flag_contains_suggested_resolution(self) -> None:
        req = _request(unit_type="SECURITY_PATCH", context=())
        flags: list[ModelAmbiguityFlag] = []
        _check_required_context(req, flags)
        assert flags[0].suggested_resolution


# ---------------------------------------------------------------------------
# R2: Rejection — AmbiguityGateError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAmbiguityGateError:
    def test_error_carries_result(self) -> None:
        flag = ModelAmbiguityFlag(
            ambiguity_type=EnumAmbiguityType.TITLE_TOO_VAGUE,
            description="Too vague",
        )
        result = ModelGateCheckResult(
            unit_id="wu-001",
            verdict=EnumGateVerdict.FAIL,
            ambiguity_flags=(flag,),
            dag_id="dag-001",
            intent_id="intent-001",
        )
        err = AmbiguityGateError(result)
        assert err.result is result

    def test_error_message_includes_unit_id(self) -> None:
        flag = ModelAmbiguityFlag(
            ambiguity_type=EnumAmbiguityType.DESCRIPTION_MISSING,
            description="No description",
        )
        result = ModelGateCheckResult(
            unit_id="wu-unique-id",
            verdict=EnumGateVerdict.FAIL,
            ambiguity_flags=(flag,),
            dag_id="dag-001",
            intent_id="intent-001",
        )
        err = AmbiguityGateError(result)
        assert "wu-unique-id" in str(err)

    def test_error_message_includes_ambiguity_type(self) -> None:
        flag = ModelAmbiguityFlag(
            ambiguity_type=EnumAmbiguityType.DESCRIPTION_MISSING,
            description="No description",
        )
        result = ModelGateCheckResult(
            unit_id="wu-001",
            verdict=EnumGateVerdict.FAIL,
            ambiguity_flags=(flag,),
            dag_id="dag-001",
            intent_id="intent-001",
        )
        err = AmbiguityGateError(result)
        assert "DESCRIPTION_MISSING" in str(err)

    def test_error_is_subclass_of_value_error(self) -> None:
        flag = ModelAmbiguityFlag(
            ambiguity_type=EnumAmbiguityType.TITLE_TOO_VAGUE,
            description="Too vague",
        )
        result = ModelGateCheckResult(
            unit_id="wu-001",
            verdict=EnumGateVerdict.FAIL,
            ambiguity_flags=(flag,),
            dag_id="dag-001",
            intent_id="intent-001",
        )
        err = AmbiguityGateError(result)
        assert isinstance(err, ValueError)


# ---------------------------------------------------------------------------
# R2: HandlerAmbiguityGateDefault — gate enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerAmbiguityGateDefault:
    def setup_method(self) -> None:
        self.handler = HandlerAmbiguityGateDefault()

    def test_handler_key_is_default(self) -> None:
        assert self.handler.handler_key == "default"

    def test_clear_work_unit_passes(self) -> None:
        req = _request()
        result = self.handler.check(req)
        assert result.verdict == EnumGateVerdict.PASS
        assert len(result.ambiguity_flags) == 0

    def test_vague_title_raises_ambiguity_gate_error(self) -> None:
        req = _request(unit_title="Fix")
        with pytest.raises(AmbiguityGateError) as exc_info:
            self.handler.check(req)
        assert exc_info.value.result.verdict == EnumGateVerdict.FAIL
        types = {f.ambiguity_type for f in exc_info.value.result.ambiguity_flags}
        assert EnumAmbiguityType.TITLE_TOO_VAGUE in types

    def test_missing_description_raises_ambiguity_gate_error(self) -> None:
        req = _request(unit_description="")
        with pytest.raises(AmbiguityGateError) as exc_info:
            self.handler.check(req)
        types = {f.ambiguity_type for f in exc_info.value.result.ambiguity_flags}
        assert EnumAmbiguityType.DESCRIPTION_MISSING in types

    def test_generic_unit_type_raises_ambiguity_gate_error(self) -> None:
        req = _request(unit_type="GENERIC")
        with pytest.raises(AmbiguityGateError) as exc_info:
            self.handler.check(req)
        types = {f.ambiguity_type for f in exc_info.value.result.ambiguity_flags}
        assert EnumAmbiguityType.UNKNOWN_UNIT_TYPE in types

    def test_multiple_ambiguities_all_reported(self) -> None:
        req = _request(
            unit_title="Fix",
            unit_description="",
            unit_type="GENERIC",
        )
        with pytest.raises(AmbiguityGateError) as exc_info:
            self.handler.check(req)
        types = {f.ambiguity_type for f in exc_info.value.result.ambiguity_flags}
        assert EnumAmbiguityType.TITLE_TOO_VAGUE in types
        assert EnumAmbiguityType.DESCRIPTION_MISSING in types
        assert EnumAmbiguityType.UNKNOWN_UNIT_TYPE in types

    def test_result_unit_id_matches_request(self) -> None:
        req = _request(unit_title="Fix")
        with pytest.raises(AmbiguityGateError) as exc_info:
            self.handler.check(req)
        assert exc_info.value.result.unit_id == req.unit_id

    def test_result_dag_id_matches_request(self) -> None:
        req = _request(unit_title="Fix")
        with pytest.raises(AmbiguityGateError) as exc_info:
            self.handler.check(req)
        assert exc_info.value.result.dag_id == req.dag_id

    def test_result_intent_id_matches_request(self) -> None:
        req = _request(unit_title="Fix")
        with pytest.raises(AmbiguityGateError) as exc_info:
            self.handler.check(req)
        assert exc_info.value.result.intent_id == req.intent_id

    def test_no_ticket_emitted_on_failure(self) -> None:
        """Verify check() never returns on FAIL — only raises."""
        req = _request(unit_description="")
        returned = None
        try:
            returned = self.handler.check(req)
        except AmbiguityGateError:
            pass
        assert returned is None

    def test_security_patch_without_vulnerability_fails(self) -> None:
        req = _request(unit_type="SECURITY_PATCH", context=())
        with pytest.raises(AmbiguityGateError) as exc_info:
            self.handler.check(req)
        types = {f.ambiguity_type for f in exc_info.value.result.ambiguity_flags}
        assert EnumAmbiguityType.MISSING_REQUIRED_CONTEXT in types

    def test_security_patch_with_vulnerability_passes(self) -> None:
        req = _request(
            unit_type="SECURITY_PATCH",
            context=(("vulnerability", "SQL injection in login"),),
        )
        result = self.handler.check(req)
        assert result.verdict == EnumGateVerdict.PASS

    def test_code_review_without_pr_url_fails(self) -> None:
        req = _request(unit_type="CODE_REVIEW", context=())
        with pytest.raises(AmbiguityGateError) as exc_info:
            self.handler.check(req)
        types = {f.ambiguity_type for f in exc_info.value.result.ambiguity_flags}
        assert EnumAmbiguityType.MISSING_REQUIRED_CONTEXT in types

    def test_code_review_with_pr_url_passes(self) -> None:
        req = _request(
            unit_type="CODE_REVIEW",
            context=(("pr_url", "https://github.com/org/repo/pull/42"),),
        )
        result = self.handler.check(req)
        assert result.verdict == EnumGateVerdict.PASS


# ---------------------------------------------------------------------------
# R3: Auditable resolution paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuditability:
    def test_each_flag_has_suggested_resolution(self) -> None:
        req = _request(unit_title="Fix", unit_description="")
        with pytest.raises(AmbiguityGateError) as exc_info:
            HandlerAmbiguityGateDefault().check(req)
        for flag in exc_info.value.result.ambiguity_flags:
            assert flag.suggested_resolution, (
                f"Flag {flag.ambiguity_type} missing suggested_resolution"
            )

    def test_each_flag_has_field_name(self) -> None:
        req = _request(unit_title="Fix", unit_description="")
        with pytest.raises(AmbiguityGateError) as exc_info:
            HandlerAmbiguityGateDefault().check(req)
        for flag in exc_info.value.result.ambiguity_flags:
            assert flag.field_name, f"Flag {flag.ambiguity_type} missing field_name"

    def test_flag_types_are_string_enums(self) -> None:
        for member in EnumAmbiguityType:
            assert isinstance(member.value, str)
            assert member.value == member.value.upper()

    def test_result_traceable_to_dag_and_intent(self) -> None:
        dag_id = f"dag-{uuid.uuid4()}"
        intent_id = f"intent-{uuid.uuid4()}"
        req = _request(
            unit_description="",
            dag_id=dag_id,
            intent_id=intent_id,
        )
        with pytest.raises(AmbiguityGateError) as exc_info:
            HandlerAmbiguityGateDefault().check(req)
        assert exc_info.value.result.dag_id == dag_id
        assert exc_info.value.result.intent_id == intent_id

    def test_detect_ambiguities_returns_empty_for_clean_unit(self) -> None:
        req = _request()
        flags = _detect_ambiguities(req)
        assert flags == []

    def test_detect_ambiguities_returns_flags_for_ambiguous_unit(self) -> None:
        req = _request(unit_title="Fix", unit_description="")
        flags = _detect_ambiguities(req)
        assert len(flags) >= 2
