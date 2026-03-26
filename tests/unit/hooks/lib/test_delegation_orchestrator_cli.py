# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for delegation_orchestrator.main() CLI entry point."""

from __future__ import annotations

import base64
import json
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# Insert hooks/lib so delegation_orchestrator can be imported directly.
# Mirrors the pattern used by test_delegation_orchestrator.py.
_HOOKS_LIB = (
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

# Pre-stub modules that trigger circular imports at module load time.
# Multiple modules in omniclaude.lib.utils (debug_utils, quality_enforcer)
# access `settings.<attr>` at module level, but `settings` is the module object
# (not the Settings instance) during the circular import chain triggered by
# conftest.py adding src/ to sys.path.
#
# OMN-5542: The stubs are saved and restored after import to prevent test
# pollution — prior approach left MagicMock objects in sys.modules which
# caused downstream tests (test_quality_enforcer_*.py) to see a mock instead
# of the real module. We capture only the keys we inject, import the module
# we need, then remove our stubs so other tests get the real modules.
from unittest.mock import MagicMock as _MagicMock

_STUB_MODS = [
    "omniclaude.lib.utils.debug_utils",
    "omniclaude.lib.utils.quality_enforcer",
]
_saved: dict[str, types.ModuleType] = {}
_injected: dict[str, object] = {}
for _mod in _STUB_MODS:
    if _mod in sys.modules:
        _saved[_mod] = sys.modules[_mod]
    else:
        _stub = _MagicMock()
        _injected[_mod] = _stub
        sys.modules[_mod] = _stub

try:
    import delegation_orchestrator  # noqa: E402 I001
finally:
    # Clean up: remove only stubs we injected (identity check prevents
    # removing a real module that was loaded during the import).
    for _mod, _stub in _injected.items():
        if sys.modules.get(_mod) is _stub:
            sys.modules.pop(_mod, None)
    # Restore modules that existed before stubbing.
    for _mod, _orig in _saved.items():
        sys.modules[_mod] = _orig


@pytest.mark.unit
class TestDelegationOrchestratorCLI:
    """Tests for the main() CLI entry point."""

    def _run_main(
        self,
        args: list[str],
        stdin_data: str = "",
    ) -> dict:
        """Helper: invoke main() and capture JSON output."""
        with (
            patch.object(sys, "argv", ["delegation_orchestrator.py", *args]),
            patch("sys.stdin") as mock_stdin,
            patch("builtins.print") as mock_print,
            pytest.raises(SystemExit) as exc_info,
        ):
            mock_stdin.read.return_value = stdin_data
            delegation_orchestrator.main()
        assert exc_info.value.code == 0, "main() must always exit 0"
        assert mock_print.call_count == 1, "main() must print exactly once"
        output = mock_print.call_args[0][0]
        return json.loads(output)

    def test_stdin_mode_calls_orchestrate(self) -> None:
        """--prompt-stdin reads b64 from stdin and calls orchestrate_delegation."""
        prompt = "Write docs for the API"
        b64 = base64.b64encode(prompt.encode()).decode()
        corr_id = "test-corr-123"
        expected = {"delegated": True, "response": "docs here", "model": "test"}

        with patch.object(
            delegation_orchestrator,
            "orchestrate_delegation",
            return_value=expected,
        ) as mock_orch:
            result = self._run_main(["--prompt-stdin", corr_id], stdin_data=b64)

        mock_orch.assert_called_once_with(
            prompt=prompt,
            correlation_id=corr_id,
            session_id="",
        )
        assert result == expected

    def test_stdin_mode_with_session_id(self) -> None:
        """--prompt-stdin with session_id passes it through."""
        prompt = "Write tests"
        b64 = base64.b64encode(prompt.encode()).decode()
        corr_id = "corr-456"
        session_id = "sess-789"
        expected = {"delegated": False, "reason": "feature_disabled"}

        with patch.object(
            delegation_orchestrator,
            "orchestrate_delegation",
            return_value=expected,
        ) as mock_orch:
            result = self._run_main(
                ["--prompt-stdin", corr_id, session_id], stdin_data=b64
            )

        mock_orch.assert_called_once_with(
            prompt=prompt,
            correlation_id=corr_id,
            session_id=session_id,
        )
        assert result == expected

    def test_missing_args_returns_safe_fallback(self) -> None:
        """Missing args returns delegated=False."""
        result = self._run_main(["--prompt-stdin"])
        assert result == {"delegated": False, "reason": "missing_args"}

    def test_no_args_returns_safe_fallback(self) -> None:
        """No args at all returns delegated=False with missing_args reason."""
        result = self._run_main([])
        assert result == {"delegated": False, "reason": "missing_args"}

    def test_bad_base64_returns_decode_error(self) -> None:
        """Invalid base64 returns prompt_decode_error."""
        result = self._run_main(
            ["--prompt-stdin", "corr-id"], stdin_data="not-valid-b64!!!"
        )
        assert result == {"delegated": False, "reason": "prompt_decode_error"}

    def test_empty_stdin_returns_decode_error(self) -> None:
        """Empty stdin (no base64 payload) returns prompt_decode_error."""
        result = self._run_main(["--prompt-stdin", "corr-id"], stdin_data="")
        assert result == {"delegated": False, "reason": "prompt_decode_error"}

    def test_orchestrate_exception_returns_safe_fallback(self) -> None:
        """If orchestrate_delegation raises, return safe fallback."""
        prompt = "anything"
        b64 = base64.b64encode(prompt.encode()).decode()

        with patch.object(
            delegation_orchestrator,
            "orchestrate_delegation",
            side_effect=RuntimeError("boom"),
        ):
            result = self._run_main(["--prompt-stdin", "corr-id"], stdin_data=b64)

        assert result == {
            "delegated": False,
            "reason": "unexpected_error: RuntimeError",
        }

    def test_result_serialization_failure_returns_safe_fallback(self) -> None:
        """If orchestrate_delegation returns non-serializable data, handle it."""
        prompt = "anything"
        b64 = base64.b64encode(prompt.encode()).decode()
        # datetime objects are not JSON-serializable
        bad_result = {
            "delegated": True,
            "response": "ok",
            "timestamp": datetime.now(UTC),
        }

        with patch.object(
            delegation_orchestrator,
            "orchestrate_delegation",
            return_value=bad_result,
        ):
            result = self._run_main(["--prompt-stdin", "corr-id"], stdin_data=b64)

        assert result == {"delegated": False, "reason": "result_serialize_error"}

    def test_extra_args_ignored_and_pass_through_correct(self) -> None:
        """Extra arguments beyond session_id are ignored."""
        prompt = "Write docs"
        b64 = base64.b64encode(prompt.encode()).decode()
        expected = {"delegated": False, "reason": "feature_disabled"}

        with patch.object(
            delegation_orchestrator,
            "orchestrate_delegation",
            return_value=expected,
        ) as mock_orch:
            result = self._run_main(
                ["--prompt-stdin", "corr-id", "sess-id", "extra-arg", "another"],
                stdin_data=b64,
            )

        mock_orch.assert_called_once_with(
            prompt=prompt,
            correlation_id="corr-id",
            session_id="sess-id",
        )
        assert result == expected

    def test_always_exits_zero(self) -> None:
        """main() must always exit 0 regardless of outcome."""
        result = self._run_main(["--prompt-stdin"])
        assert result == {"delegated": False, "reason": "missing_args"}
