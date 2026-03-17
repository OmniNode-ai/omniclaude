# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for return_path_auditor (OMN-5238).

Covers:
    - estimate_tokens: character-to-token approximation
    - ReturnSchemaConfig: construction and defaults
    - ReturnAuditResult: construction
    - audit_return_payload: all enforcement levels, token budget, field allowlist
    - _extract_return_schema: various hook event shapes
    - _extract_payload: dict / string / raw response shapes
    - _load_enforcement_level: env var handling
    - main(): stdin/stdout integration for Task and non-Task tools
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from omniclaude.hooks.handlers.return_path_auditor import (
    _DEFAULT_ENFORCEMENT_LEVEL,
    _DEFAULT_MAX_TOKENS,
    _VALID_ENFORCEMENT_LEVELS,
    ReturnAuditResult,
    ReturnSchemaConfig,
    _extract_payload,
    _extract_return_schema,
    _load_enforcement_level,
    audit_return_payload,
    estimate_tokens,
    main,
)
from omniclaude.hooks.schemas_audit import AuditEnforcementAction

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


def _ts() -> datetime:
    return datetime.now(UTC)


def _id() -> UUID:
    return uuid4()


def _minimal_payload(fields: dict | None = None) -> dict:
    if fields is None:
        return {"status": "done", "summary": "ok"}
    return fields


def _schema(
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    allowed_fields: list[str] | None = None,
) -> ReturnSchemaConfig:
    return ReturnSchemaConfig(
        max_tokens=max_tokens,
        allowed_fields=allowed_fields if allowed_fields is not None else [],
    )


# =============================================================================
# estimate_tokens
# =============================================================================


class TestEstimateTokens:
    def test_empty_string_returns_zero(self) -> None:
        assert estimate_tokens("") == 0

    def test_four_chars_returns_one_token(self) -> None:
        assert estimate_tokens("abcd") == 1

    def test_five_chars_returns_two_tokens(self) -> None:
        # ceiling: 5/4 = 1.25 → 2
        assert estimate_tokens("abcde") == 2

    def test_large_payload(self) -> None:
        payload = json.dumps({"key": "x" * 4000})
        tokens = estimate_tokens(payload)
        assert tokens > 0

    def test_single_char_returns_one_token(self) -> None:
        assert estimate_tokens("a") == 1


# =============================================================================
# ReturnSchemaConfig
# =============================================================================


class TestReturnSchemaConfig:
    def test_defaults(self) -> None:
        schema = ReturnSchemaConfig()
        assert schema.max_tokens == _DEFAULT_MAX_TOKENS
        assert schema.allowed_fields == []

    def test_custom_values(self) -> None:
        schema = ReturnSchemaConfig(max_tokens=1024, allowed_fields=["status", "data"])
        assert schema.max_tokens == 1024
        assert schema.allowed_fields == ["status", "data"]

    def test_frozen(self) -> None:
        schema = ReturnSchemaConfig()
        with pytest.raises((TypeError, ValidationError)):
            schema.max_tokens = 9999  # type: ignore[misc]

    def test_max_tokens_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            ReturnSchemaConfig(max_tokens=0)

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ReturnSchemaConfig(unknown_field="x")  # type: ignore[call-arg]


# =============================================================================
# ReturnAuditResult
# =============================================================================


class TestReturnAuditResult:
    def test_construct_clean(self) -> None:
        result = ReturnAuditResult(
            task_id=_id(),
            blocked=False,
            return_tokens=100,
            max_tokens=8192,
            fields_returned=["status"],
            disallowed_fields=[],
            enforcement_action=AuditEnforcementAction.LOG,
            correlation_id=_id(),
        )
        assert result.blocked is False
        assert result.return_tokens == 100

    def test_frozen(self) -> None:
        result = ReturnAuditResult(
            task_id=_id(),
            blocked=False,
            return_tokens=50,
            max_tokens=8192,
            fields_returned=[],
            disallowed_fields=[],
            enforcement_action=AuditEnforcementAction.LOG,
            correlation_id=_id(),
        )
        with pytest.raises((TypeError, ValidationError)):
            result.blocked = True  # type: ignore[misc]


# =============================================================================
# audit_return_payload -- PERMISSIVE
# =============================================================================


class TestAuditReturnPayloadPermissive:
    def _run(self, payload: dict, schema: ReturnSchemaConfig) -> ReturnAuditResult:
        with (
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ),
        ):
            return audit_return_payload(
                payload=payload,
                schema=schema,
                task_id=_id(),
                correlation_id=_id(),
                enforcement_level="PERMISSIVE",
                emitted_at=_ts(),
            )

    def test_token_exceeded_not_blocked(self) -> None:
        payload = {"data": "x" * 1000}
        result = self._run(payload, _schema(max_tokens=1))
        assert result.blocked is False
        assert result.enforcement_action == AuditEnforcementAction.LOG

    def test_disallowed_fields_not_blocked(self) -> None:
        result = self._run(
            {"status": "ok", "secret": "leak"},
            _schema(allowed_fields=["status"]),
        )
        assert result.blocked is False

    def test_clean_payload_log_action(self) -> None:
        result = self._run({"status": "ok"}, _schema())
        assert result.blocked is False
        assert result.enforcement_action == AuditEnforcementAction.LOG


# =============================================================================
# audit_return_payload -- WARN
# =============================================================================


class TestAuditReturnPayloadWarn:
    def _run(self, payload: dict, schema: ReturnSchemaConfig) -> ReturnAuditResult:
        with (
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ),
        ):
            return audit_return_payload(
                payload=payload,
                schema=schema,
                task_id=_id(),
                correlation_id=_id(),
                enforcement_level="WARN",
                emitted_at=_ts(),
            )

    def test_token_exceeded_not_blocked(self) -> None:
        payload = {"data": "x" * 1000}
        result = self._run(payload, _schema(max_tokens=1))
        assert result.blocked is False
        assert result.enforcement_action == AuditEnforcementAction.WARN

    def test_disallowed_fields_not_blocked(self) -> None:
        result = self._run(
            {"status": "ok", "secret": "leak"},
            _schema(allowed_fields=["status"]),
        )
        assert result.blocked is False
        assert result.enforcement_action == AuditEnforcementAction.WARN

    def test_clean_payload_log_action(self) -> None:
        result = self._run({"status": "ok"}, _schema())
        assert result.blocked is False
        assert result.enforcement_action == AuditEnforcementAction.LOG


# =============================================================================
# audit_return_payload -- STRICT
# =============================================================================


class TestAuditReturnPayloadStrict:
    def _run(self, payload: dict, schema: ReturnSchemaConfig) -> ReturnAuditResult:
        with (
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ),
        ):
            return audit_return_payload(
                payload=payload,
                schema=schema,
                task_id=_id(),
                correlation_id=_id(),
                enforcement_level="STRICT",
                emitted_at=_ts(),
            )

    def test_token_exceeded_blocked(self) -> None:
        payload = {"data": "x" * 1000}
        result = self._run(payload, _schema(max_tokens=1))
        assert result.blocked is True
        assert result.enforcement_action == AuditEnforcementAction.BLOCK

    def test_disallowed_fields_blocked(self) -> None:
        result = self._run(
            {"status": "ok", "secret": "leak"},
            _schema(allowed_fields=["status"]),
        )
        assert result.blocked is True
        assert result.enforcement_action == AuditEnforcementAction.BLOCK
        assert "secret" in result.disallowed_fields

    def test_clean_payload_not_blocked(self) -> None:
        result = self._run({"status": "ok"}, _schema())
        assert result.blocked is False
        assert result.enforcement_action == AuditEnforcementAction.LOG

    def test_fields_within_allowlist_not_blocked(self) -> None:
        result = self._run(
            {"status": "ok", "summary": "done"},
            _schema(allowed_fields=["status", "summary"]),
        )
        assert result.blocked is False

    def test_fields_returned_populated(self) -> None:
        result = self._run(
            {"a": 1, "b": 2},
            _schema(allowed_fields=["a", "b"]),
        )
        assert set(result.fields_returned) == {"a", "b"}


# =============================================================================
# audit_return_payload -- PARANOID
# =============================================================================


class TestAuditReturnPayloadParanoid:
    def _run(
        self,
        payload: dict,
        schema: ReturnSchemaConfig,
        *,
        mock_mark_invalid: MagicMock | None = None,
    ) -> ReturnAuditResult:
        with (
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._mark_task_invalid",
                mock_mark_invalid or MagicMock(),
            ),
        ):
            return audit_return_payload(
                payload=payload,
                schema=schema,
                task_id=_id(),
                correlation_id=_id(),
                enforcement_level="PARANOID",
                emitted_at=_ts(),
            )

    def test_violation_blocked_and_mark_called(self) -> None:
        mock_mark = MagicMock()
        payload = {"data": "x" * 1000}
        result = self._run(payload, _schema(max_tokens=1), mock_mark_invalid=mock_mark)
        assert result.blocked is True
        mock_mark.assert_called_once()

    def test_clean_payload_mark_not_called(self) -> None:
        mock_mark = MagicMock()
        result = self._run({"status": "ok"}, _schema(), mock_mark_invalid=mock_mark)
        assert result.blocked is False
        mock_mark.assert_not_called()


# =============================================================================
# audit_return_payload -- event emission
# =============================================================================


class TestAuditReturnPayloadEventEmission:
    def test_return_bounded_event_always_emitted(self) -> None:
        with (
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ) as mock_bounded,
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ),
        ):
            audit_return_payload(
                payload={"status": "ok"},
                schema=_schema(),
                task_id=_id(),
                correlation_id=_id(),
                enforcement_level="WARN",
                emitted_at=_ts(),
            )
        mock_bounded.assert_called_once()

    def test_scope_violation_emitted_on_token_excess(self) -> None:
        with (
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ) as mock_violation,
        ):
            audit_return_payload(
                payload={"data": "x" * 1000},
                schema=_schema(max_tokens=1),
                task_id=_id(),
                correlation_id=_id(),
                enforcement_level="WARN",
                emitted_at=_ts(),
            )
        mock_violation.assert_called_once()

    def test_scope_violation_emitted_on_disallowed_fields(self) -> None:
        with (
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ) as mock_violation,
        ):
            audit_return_payload(
                payload={"status": "ok", "extra": "bad"},
                schema=_schema(allowed_fields=["status"]),
                task_id=_id(),
                correlation_id=_id(),
                enforcement_level="WARN",
                emitted_at=_ts(),
            )
        mock_violation.assert_called_once()

    def test_no_scope_violation_on_clean_payload(self) -> None:
        with (
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ) as mock_violation,
        ):
            audit_return_payload(
                payload={"status": "ok"},
                schema=_schema(allowed_fields=["status"]),
                task_id=_id(),
                correlation_id=_id(),
                enforcement_level="WARN",
                emitted_at=_ts(),
            )
        mock_violation.assert_not_called()

    def test_permissive_no_scope_violation_emitted(self) -> None:
        with (
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ) as mock_violation,
        ):
            audit_return_payload(
                payload={"data": "x" * 1000},
                schema=_schema(max_tokens=1),
                task_id=_id(),
                correlation_id=_id(),
                enforcement_level="PERMISSIVE",
                emitted_at=_ts(),
            )
        mock_violation.assert_not_called()


# =============================================================================
# _extract_return_schema
# =============================================================================


class TestExtractReturnSchema:
    def test_missing_key_returns_defaults(self) -> None:
        schema = _extract_return_schema({})
        assert schema.max_tokens == _DEFAULT_MAX_TOKENS
        assert schema.allowed_fields == []

    def test_present_key_extracted(self) -> None:
        schema = _extract_return_schema(
            {"return_schema": {"max_tokens": 2048, "allowed_fields": ["a", "b"]}}
        )
        assert schema.max_tokens == 2048
        assert schema.allowed_fields == ["a", "b"]

    def test_partial_key_uses_defaults_for_missing_fields(self) -> None:
        schema = _extract_return_schema({"return_schema": {"max_tokens": 512}})
        assert schema.max_tokens == 512
        assert schema.allowed_fields == []

    def test_non_dict_return_schema_returns_defaults(self) -> None:
        schema = _extract_return_schema({"return_schema": "bad_value"})
        assert schema.max_tokens == _DEFAULT_MAX_TOKENS


# =============================================================================
# _extract_payload
# =============================================================================


class TestExtractPayload:
    def test_dict_content_returned_as_is(self) -> None:
        result = _extract_payload({"content": {"status": "ok"}})
        assert result == {"status": "ok"}

    def test_string_content_parsed_as_json(self) -> None:
        result = _extract_payload({"content": '{"status": "ok"}'})
        assert result == {"status": "ok"}

    def test_raw_string_wrapped(self) -> None:
        result = _extract_payload({"content": "plain text"})
        assert "_raw" in result

    def test_output_key_used_when_no_content(self) -> None:
        result = _extract_payload({"output": {"status": "done"}})
        assert result == {"status": "done"}

    def test_fallback_to_whole_response(self) -> None:
        result = _extract_payload({"something": "else"})
        assert "something" in result


# =============================================================================
# _load_enforcement_level
# =============================================================================


class TestLoadEnforcementLevel:
    def test_default_when_env_absent(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OMNICLAUDE_RETURN_AUDIT_ENFORCEMENT", None)
            level = _load_enforcement_level()
        assert level == _DEFAULT_ENFORCEMENT_LEVEL

    @pytest.mark.parametrize("level", list(_VALID_ENFORCEMENT_LEVELS))
    def test_valid_levels_accepted(self, level: str) -> None:
        with patch.dict(os.environ, {"OMNICLAUDE_RETURN_AUDIT_ENFORCEMENT": level}):
            assert _load_enforcement_level() == level

    def test_invalid_level_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"OMNICLAUDE_RETURN_AUDIT_ENFORCEMENT": "INVALID"}):
            level = _load_enforcement_level()
        assert level == _DEFAULT_ENFORCEMENT_LEVEL

    def test_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"OMNICLAUDE_RETURN_AUDIT_ENFORCEMENT": "strict"}):
            level = _load_enforcement_level()
        assert level == "STRICT"


# =============================================================================
# main() -- stdin/stdout integration
# =============================================================================


class TestMain:
    def _make_hook_event(
        self,
        tool_name: str = "Task",
        return_schema: dict | None = None,
        response_content: dict | None = None,
    ) -> dict:
        tool_input: dict = {}
        if return_schema is not None:
            tool_input["return_schema"] = return_schema
        return {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_response": {"content": response_content or {"status": "done"}},
            "sessionId": "test-session",
        }

    def _run_main(self, hook_event: dict, enforcement: str = "WARN") -> dict:
        stdin_data = json.dumps(hook_event)
        with (
            patch("sys.stdin", StringIO(stdin_data)),
            patch("sys.stdout", new_callable=StringIO) as mock_stdout,
            patch.dict(
                os.environ,
                {"OMNICLAUDE_RETURN_AUDIT_ENFORCEMENT": enforcement},
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_return_bounded_event"
            ),
            patch(
                "omniclaude.hooks.handlers.return_path_auditor._emit_scope_violation_event"
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 0
        output = mock_stdout.getvalue()
        return json.loads(output)

    def test_non_task_tool_passthrough(self) -> None:
        event = self._make_hook_event(tool_name="Read")
        stdin_data = json.dumps(event)
        with (
            patch("sys.stdin", StringIO(stdin_data)),
            patch("sys.stdout", new_callable=StringIO) as mock_stdout,
            pytest.raises(SystemExit),
        ):
            main()
        output = mock_stdout.getvalue()
        # Should be the original event, not an audit result
        assert json.loads(output) == event

    def test_task_tool_returns_audit_result(self) -> None:
        event = self._make_hook_event()
        result = self._run_main(event)
        assert "blocked" in result
        assert "return_tokens" in result
        assert "enforcement_action" in result

    def test_task_tool_strict_violation_sets_blocked(self) -> None:
        # Tiny max_tokens to force a violation
        event = self._make_hook_event(
            return_schema={"max_tokens": 1, "allowed_fields": []},
            response_content={"data": "x" * 500},
        )
        result = self._run_main(event, enforcement="STRICT")
        assert result["blocked"] is True

    def test_task_tool_warn_violation_not_blocked(self) -> None:
        event = self._make_hook_event(
            return_schema={"max_tokens": 1, "allowed_fields": []},
            response_content={"data": "x" * 500},
        )
        result = self._run_main(event, enforcement="WARN")
        assert result["blocked"] is False

    def test_malformed_json_passthrough(self) -> None:
        bad_input = "not json {"
        with (
            patch("sys.stdin", StringIO(bad_input)),
            patch("sys.stdout", new_callable=StringIO) as mock_stdout,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 0
        # Output should be the raw input (passthrough on parse failure)
        output = mock_stdout.getvalue()
        assert output == bad_input or output == "{}"

    def test_agent_tool_also_audited(self) -> None:
        event = self._make_hook_event(tool_name="Agent")
        result = self._run_main(event)
        assert "blocked" in result
