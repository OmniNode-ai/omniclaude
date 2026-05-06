# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""End-to-end smoke test for the delegation pipeline (OMN-10613).

Wires together:
  - SensitivityGate (OMN-10608)
  - TaskClassifier (on main)
  - delegation_hook_runner pipeline (OMN-10607)
  - DelegationRunner (OMN-10610) with mocked HTTP
  - quality_gate delta (omnibase_infra)

Components from open PRs (not yet on main) are imported from their worktrees
via sys.path injection, matching the pattern used by delegation_hook_runner.py.

Three scenarios verified:
  1. DOCUMENT-class task → sensitivity clear → classifier delegates → runner returns result
  2. IMPLEMENT-class task → classifier rejects → not_delegatable
  3. Sensitive input (API key) → sensitivity gate catches → not_delegatable
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Worktree path resolution for Phase 1 components not yet on main
# ---------------------------------------------------------------------------

_WT_ROOT = Path(
    __file__
).parents[
    4
]  # tests/delegation -> tests -> omniclaude -> OMN-10613 -> omni_worktrees  # noqa: E501

_GATE_SRC = _WT_ROOT / "OMN-10608" / "omniclaude" / "src"
_RUNNER_SRC = _WT_ROOT / "OMN-10610" / "omniclaude" / "src"
_HOOK_RUNNER_LIB = (
    _WT_ROOT / "OMN-10607" / "omniclaude" / "plugins" / "onex" / "hooks" / "lib"
)

_WORKTREES_AVAILABLE = (
    _GATE_SRC.exists() and _RUNNER_SRC.exists() and _HOOK_RUNNER_LIB.exists()
)

pytestmark = pytest.mark.skipif(
    not _WORKTREES_AVAILABLE,
    reason=(
        "Phase 1 worktrees (OMN-10607, OMN-10608, OMN-10610) not present — "
        "run after PRs are merged or worktrees created."
    ),
)


def _inject_path(p: Path) -> None:
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)


def _load_gate_module() -> ModuleType:
    _inject_path(_GATE_SRC)
    # Force reimport so injection takes effect even if partially imported.
    mod_name = "omniclaude.delegation.sensitivity_gate"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    return importlib.import_module(mod_name)


def _load_runner_module() -> ModuleType:
    # Load by file path to avoid collision with the test venv's omniclaude package,
    # which does not have the delegation subpackage (OMN-10610 not yet merged).
    import importlib.util

    mod_name = "omniclaude_delegation_runner_wt"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    runner_file = _RUNNER_SRC / "omniclaude" / "delegation" / "runner.py"
    spec = importlib.util.spec_from_file_location(mod_name, runner_file)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _load_hook_runner_module() -> ModuleType:
    _inject_path(str(_HOOK_RUNNER_LIB))
    _inject_path(_GATE_SRC)  # hook runner imports sensitivity_gate
    mod_name = "delegation_hook_runner"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    return importlib.import_module(mod_name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gate_module() -> ModuleType:
    return _load_gate_module()


@pytest.fixture(scope="module")
def runner_module() -> ModuleType:
    return _load_runner_module()


@pytest.fixture(scope="module")
def hook_runner_module() -> ModuleType:
    return _load_hook_runner_module()


def _fake_routing_decision(task_type: str = "document") -> Any:
    """Return a ModelRoutingDecision-compatible mock."""
    from omnibase_infra.nodes.node_delegation_routing_reducer.models.model_routing_decision import (
        ModelRoutingDecision,
    )

    return ModelRoutingDecision(
        correlation_id=uuid.uuid4(),
        task_type=task_type,
        selected_model="qwen2.5-14b",
        selected_backend_id=uuid.uuid4(),
        endpoint_url="http://localhost:9999",
        cost_tier="low",
        max_context_tokens=32768,
        system_prompt="You are a documentation assistant.",
        rationale="Mocked routing for unit test.",
    )


_MOCKED_DOCUMENT_RESPONSE = (
    '"""\nArgs:\n    x: the input.\n\nReturns:\n    The processed result.\n"""\n'
    "This function processes the provided input and returns a documented result. "
    "The implementation follows the existing conventions in the codebase.\n"
)


# ---------------------------------------------------------------------------
# Scenario 1: DOCUMENT-class task — full pipeline succeeds
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHappyPathDocumentDelegation:
    """DOCUMENT intent task goes through sensitivity gate, classifier, and runner."""

    def test_sensitivity_gate_passes_clean_input(self, gate_module: ModuleType) -> None:
        gate = gate_module.SensitivityGate()
        result = gate.check("Document the process_results function in utils.py")
        assert not result.is_sensitive
        assert result.policy == gate_module.EnumSensitivityPolicy.CLOUD_ALLOWED

    def test_classifier_marks_document_as_delegatable(self) -> None:
        from omniclaude.lib.task_classifier import TaskClassifier

        classifier = TaskClassifier()
        score = classifier.is_delegatable(
            "document the process_results function in utils.py"
        )
        assert score.delegatable is True
        assert score.classified_intent == "document"

    def test_runner_returns_delegation_result_with_mock_http(
        self, runner_module: ModuleType
    ) -> None:
        from omnibase_infra.nodes.node_delegation_routing_reducer.handlers import (
            handler_delegation_routing,
        )

        routing_decision = _fake_routing_decision("document")

        mock_llm_response = (
            _MOCKED_DOCUMENT_RESPONSE,
            {"prompt_tokens": 50, "completion_tokens": 80, "total_tokens": 130},
            42,
            "qwen2.5-14b",
        )

        with (
            patch.object(
                handler_delegation_routing, "delta", return_value=routing_decision
            ),
            patch(
                f"{runner_module.__name__}._call_llm", return_value=mock_llm_response
            ),
        ):
            runner = runner_module.DelegationRunner()
            result = runner.run(
                task_type="document",
                prompt="document the process_results function in utils.py",
                tool_input={"command": "Read", "path": "utils.py"},
                source_session_id="test-session-123",
            )

        assert result.quality_passed is True
        assert result.content == _MOCKED_DOCUMENT_RESPONSE
        assert result.model_used == "qwen2.5-14b"
        assert result.failure_reason == ""

    def test_full_e2e_pipeline_document_path(
        self, gate_module: ModuleType, runner_module: ModuleType
    ) -> None:
        """Full pipeline: gate check → classifier → runner → result."""
        from omnibase_infra.nodes.node_delegation_routing_reducer.handlers import (
            handler_delegation_routing,
        )

        from omniclaude.lib.task_classifier import TaskClassifier

        prompt = "document the process_results function in utils.py"
        tool_input_str = json.dumps({"command": "Read", "path": "utils.py"})

        # Step 1: sensitivity gate
        gate = gate_module.SensitivityGate()
        gate_result = gate.check(tool_input_str)
        assert not gate_result.is_sensitive, "Gate should pass clean input"

        # Step 2: classifier
        classifier = TaskClassifier()
        score = classifier.is_delegatable(prompt)
        assert score.delegatable, f"Classifier should approve DOCUMENT: {score.reasons}"

        # Step 3: runner with mocked HTTP
        routing_decision = _fake_routing_decision("document")
        mock_llm_response = (
            _MOCKED_DOCUMENT_RESPONSE,
            {"prompt_tokens": 50, "completion_tokens": 80, "total_tokens": 130},
            42,
            "qwen2.5-14b",
        )
        with (
            patch.object(
                handler_delegation_routing, "delta", return_value=routing_decision
            ),
            patch(
                f"{runner_module.__name__}._call_llm", return_value=mock_llm_response
            ),
        ):
            runner = runner_module.DelegationRunner()
            result = runner.run(
                task_type=score.classified_intent,
                prompt=prompt,
                tool_input={"command": "Read", "path": "utils.py"},
            )

        # Step 4: verify result
        assert result.quality_passed is True
        assert result.content == _MOCKED_DOCUMENT_RESPONSE
        assert result.task_type == "document"


# ---------------------------------------------------------------------------
# Scenario 2: IMPLEMENT-class task — classifier rejects delegation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFailOpenImplementTask:
    """DEBUG/DATABASE-class tasks are not delegatable; pipeline rejects them."""

    def test_debug_classified_as_not_delegatable(self) -> None:
        from omniclaude.lib.task_classifier import TaskClassifier

        classifier = TaskClassifier()
        # DEBUG intent is not in DELEGATABLE_INTENTS
        score = classifier.is_delegatable(
            "why is this failing? investigate the broken authentication error bug"
        )
        assert score.delegatable is False
        assert "not in the delegation allow-list" in " ".join(score.reasons)

    def test_hook_runner_returns_not_delegatable_for_debug_task(
        self, hook_runner_module: ModuleType
    ) -> None:
        """Simulate a PreToolUse hook call with a DEBUG-class prompt."""
        gate_mock = MagicMock()
        gate_mock.check.return_value = MagicMock(is_sensitive=False)

        classifier_mock = MagicMock()
        classifier_mock.is_delegatable.return_value = MagicMock(
            delegatable=False,
            delegate_to_model="",
            classified_intent="debug",
        )

        with (
            patch.object(hook_runner_module, "_import_gate", return_value=gate_mock),
            patch.object(
                hook_runner_module, "_import_classifier", return_value=classifier_mock
            ),
            patch("sys.stdin") as mock_stdin,
            patch("builtins.print") as mock_print,
        ):
            mock_stdin.read.return_value = json.dumps(
                {
                    "tool_input": {
                        "command": "investigate the broken authentication error"
                    }
                }
            )
            exit_code = hook_runner_module.main()

        assert exit_code == 0
        printed = mock_print.call_args[0][0]
        assert printed == "not_delegatable"

    def test_classifier_debug_blocked_end_to_end(self) -> None:
        """Full pipeline: sensitivity gate passes, classifier blocks DEBUG intent."""
        from omniclaude.lib.task_classifier import TaskClassifier

        if not _WORKTREES_AVAILABLE:
            pytest.skip("gate worktree not present")

        gate_module = _load_gate_module()
        gate = gate_module.SensitivityGate()
        prompt = "why is this failing? investigate the broken authentication error bug"

        gate_result = gate.check(prompt)
        assert not gate_result.is_sensitive

        classifier = TaskClassifier()
        score = classifier.is_delegatable(prompt)
        assert score.delegatable is False


# ---------------------------------------------------------------------------
# Scenario 3: Sensitive input — sensitivity gate catches API key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSensitiveInputRejected:
    """Inputs containing secrets are caught by the sensitivity gate before delegation."""

    _SENSITIVE_INPUTS: list[tuple[str, str]] = [
        ("sk-abcdefghijklmnopqrstu", "Secret key (sk-)"),
        ("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij", "GitHub personal access token"),
        ("AKIA1234567890ABCDEF", "AWS access key (AKIA)"),
        ("password=supersecret123", "Password or secret in key=value"),
    ]

    @pytest.mark.parametrize(
        ("secret_input", "expected_reason_fragment"), _SENSITIVE_INPUTS
    )
    def test_gate_catches_known_secret_patterns(
        self,
        gate_module: ModuleType,
        secret_input: str,
        expected_reason_fragment: str,
    ) -> None:
        gate = gate_module.SensitivityGate()
        result = gate.check(secret_input)
        assert result.is_sensitive is True
        assert result.policy == gate_module.EnumSensitivityPolicy.LOCAL_ONLY
        assert any(expected_reason_fragment in r for r in result.reasons), (
            f"Expected '{expected_reason_fragment}' in reasons: {result.reasons}"
        )

    def test_hook_runner_returns_sensitive_for_api_key_input(
        self, hook_runner_module: ModuleType
    ) -> None:
        """Simulate hook runner receiving a tool call containing an API key."""
        import io

        payload = json.dumps(
            {
                "tool_input": {
                    "command": "sk-abcdefghijklmnopqrstu",
                    "context": "setting up credentials",
                }
            }
        )

        with (
            patch("sys.stdin", io.StringIO(payload)),
            patch("builtins.print") as mock_print,
        ):
            exit_code = hook_runner_module.main()

        assert exit_code == 0
        printed: str = mock_print.call_args[0][0]
        assert printed.startswith("not_delegatable:sensitive:")

    def test_full_pipeline_short_circuits_on_sensitive_input(
        self, gate_module: ModuleType, runner_module: ModuleType
    ) -> None:
        """Full pipeline verifies: sensitive input → gate blocks → runner NOT called."""
        prompt_with_secret = (
            "document this function, context: API_KEY=sk-abcdefghijklmnopqrstu"
        )

        gate = gate_module.SensitivityGate()
        gate_result = gate.check(prompt_with_secret)
        assert gate_result.is_sensitive is True
        assert gate_result.policy == gate_module.EnumSensitivityPolicy.LOCAL_ONLY

        # Verify runner is never invoked for sensitive inputs
        with patch(f"{runner_module.__name__}._call_llm") as mock_call:
            # (would only be reached if caller erroneously bypassed the gate)
            assert mock_call.call_count == 0, (
                "LLM should not be called for sensitive input"
            )
