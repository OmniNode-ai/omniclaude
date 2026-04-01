# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for hook error emission helper [OMN-7158]."""

from unittest.mock import patch

from omniclaude.hooks.schemas import EnumHookErrorCategory, EnumHookErrorTier


class TestClassifyHookError:
    def test_import_error_is_tier1(self) -> None:
        from plugins.onex.hooks.lib.hook_error_emitter import classify_hook_error

        tier, category = classify_hook_error(
            "ImportError: cannot import name 'UTC' from 'datetime'"
        )
        assert tier == EnumHookErrorTier.INTERPRETER
        assert category == EnumHookErrorCategory.IMPORT_ERROR

    def test_type_error_is_tier1(self) -> None:
        from plugins.onex.hooks.lib.hook_error_emitter import classify_hook_error

        tier, category = classify_hook_error(
            "TypeError: unsupported operand type(s) for |"
        )
        assert tier == EnumHookErrorTier.INTERPRETER
        assert category == EnumHookErrorCategory.TYPE_ERROR

    def test_syntax_error_is_tier1(self) -> None:
        from plugins.onex.hooks.lib.hook_error_emitter import classify_hook_error

        tier, category = classify_hook_error("SyntaxError: invalid syntax")
        assert tier == EnumHookErrorTier.INTERPRETER
        assert category == EnumHookErrorCategory.SYNTAX_ERROR

    def test_intent_unavailable_is_tier2(self) -> None:
        from plugins.onex.hooks.lib.hook_error_emitter import classify_hook_error

        tier, category = classify_hook_error(
            "Intent classification unavailable or failed"
        )
        assert tier == EnumHookErrorTier.DEGRADED
        assert category == EnumHookErrorCategory.FUNCTIONAL_DEGRADATION

    def test_authorization_denied_is_tier2(self) -> None:
        from plugins.onex.hooks.lib.hook_error_emitter import classify_hook_error

        tier, category = classify_hook_error("Authorization DENIED for Edit")
        assert tier == EnumHookErrorTier.DEGRADED
        assert category == EnumHookErrorCategory.AUTH_DENIED

    def test_timeout_is_tier2(self) -> None:
        from plugins.onex.hooks.lib.hook_error_emitter import classify_hook_error

        tier, category = classify_hook_error("Connection timed out after 5s")
        assert tier == EnumHookErrorTier.DEGRADED
        assert category == EnumHookErrorCategory.TIMEOUT

    def test_dod_block_is_tier3(self) -> None:
        from plugins.onex.hooks.lib.hook_error_emitter import classify_hook_error

        tier, category = classify_hook_error("No DoD evidence receipt found")
        assert tier == EnumHookErrorTier.INTENTIONAL_BLOCK
        assert category == EnumHookErrorCategory.DOD_BLOCK

    def test_unknown_defaults_to_degraded(self) -> None:
        from plugins.onex.hooks.lib.hook_error_emitter import classify_hook_error

        tier, category = classify_hook_error("Some unknown error occurred")
        assert tier == EnumHookErrorTier.DEGRADED
        assert category == EnumHookErrorCategory.FUNCTIONAL_DEGRADATION


class TestEmitHookError:
    @patch(
        "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
        return_value=True,
        create=True,
    )
    def test_emits_structured_event(self, mock_emit) -> None:  # noqa: ANN001
        from plugins.onex.hooks.lib.hook_error_emitter import emit_hook_error

        result = emit_hook_error(
            hook_name="dod_completion_guard",
            error_message="No DoD evidence receipt found",
            session_id="test-session",
        )
        assert result is True
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "hook.health.error"
        payload = call_args[0][1]
        assert payload["hook_name"] == "dod_completion_guard"
        assert payload["error_tier"] == "intentional_block"
        assert payload["error_category"] == "dod_block"
        assert "fingerprint" in payload
