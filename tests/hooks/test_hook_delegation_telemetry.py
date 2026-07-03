# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for hook_delegation_telemetry (T18).

Tests the ModelHookDelegationTelemetry shape, non-authoritative markers,
and build_routing_policy_hash helper.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Load module under test from the hooks lib directory
# ---------------------------------------------------------------------------
_MODULE_PATH = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "hook_delegation_telemetry.py"
)


def _load_module() -> ModuleType:
    import sys

    name = "hook_delegation_telemetry"
    spec = importlib.util.spec_from_file_location(name, _MODULE_PATH)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass(frozen=True) can resolve cls.__module__
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()
ModelHookDelegationTelemetry = _mod.ModelHookDelegationTelemetry
HookQualityResult = _mod.HookQualityResult
build_routing_policy_hash = _mod.build_routing_policy_hash


# ---------------------------------------------------------------------------
# HookQualityResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHookQualityResult:
    def test_authoritative_is_always_false(self) -> None:
        result = HookQualityResult(passed=True)
        assert result.authoritative is False

    def test_passed_false_with_reason(self) -> None:
        result = HookQualityResult(passed=False, reason="response too short")
        assert result.passed is False
        assert result.reason == "response too short"
        assert result.authoritative is False

    def test_frozen(self) -> None:
        result = HookQualityResult(passed=True)
        with pytest.raises(Exception):  # frozen dataclass raises on assignment
            result.passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ModelHookDelegationTelemetry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelHookDelegationTelemetry:
    def _make(self, **kwargs: object) -> ModelHookDelegationTelemetry:
        defaults = {
            "correlation_id": "corr-001",
            "session_id": "sess-A",
            "task_type": "research",
            "delegated_to": "Qwen3-Coder-30B",
        }
        defaults.update(kwargs)
        return ModelHookDelegationTelemetry(**defaults)  # type: ignore[arg-type]

    def test_hook_path_non_authoritative_always_true(self) -> None:
        t = self._make()
        assert t.hook_path_non_authoritative is True

    def test_tokens_default_zero(self) -> None:
        t = self._make()
        assert t.tokens_input == 0
        assert t.tokens_output == 0

    def test_cost_default_zero(self) -> None:
        t = self._make()
        assert t.cost_usd == 0.0

    def test_quality_result_default_passed(self) -> None:
        t = self._make()
        assert t.quality_result.passed is True
        assert t.quality_result.authoritative is False

    def test_delegated_by_default(self) -> None:
        t = self._make()
        assert t.delegated_by == "omniclaude.hook.pre_tool_use_delegation"

    def test_to_dict_shape(self) -> None:
        t = self._make(
            correlation_id="corr-xyz",
            task_type="document",
            delegated_to="local-model",
            routing_policy_hash="sha256:abc123",
            delegation_latency_ms=42,
        )
        d = t.to_dict()
        assert d["correlation_id"] == "corr-xyz"
        assert d["task_type"] == "document"
        assert d["delegated_to"] == "local-model"
        assert d["routing_policy_hash"] == "sha256:abc123"
        assert d["delegation_latency_ms"] == 42
        assert d["tokens_input"] == 0
        assert d["tokens_output"] == 0
        assert d["cost_usd"] == 0.0
        assert d["hook_path_non_authoritative"] is True
        assert isinstance(d["quality_result"], dict)
        assert d["quality_result"]["authoritative"] is False

    def test_to_dict_is_json_serializable(self) -> None:
        t = self._make()
        raw = json.dumps(t.to_dict())
        parsed = json.loads(raw)
        assert parsed["hook_path_non_authoritative"] is True

    def test_quality_result_in_dict_when_failed(self) -> None:
        t = self._make(
            quality_result=HookQualityResult(passed=False, reason="too short")
        )
        d = t.to_dict()
        assert d["quality_result"]["passed"] is False
        assert d["quality_result"]["reason"] == "too short"
        assert d["quality_result"]["authoritative"] is False

    def test_frozen(self) -> None:
        t = self._make()
        with pytest.raises(Exception):
            t.task_type = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# build_routing_policy_hash
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildRoutingPolicyHash:
    def test_returns_empty_when_file_missing(self) -> None:
        with patch.dict(os.environ, {}):
            with patch.object(
                _mod.os.path,
                "exists",
                return_value=False,  # type: ignore[attr-defined]
            ):
                result = build_routing_policy_hash()
        assert result == ""

    def test_returns_sha256_prefix_when_file_exists(self) -> None:
        content = b"rules:\n  - intent: research\n    behavior: suggest\n"
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(content)
            tmp_path = f.name
        try:
            expected_hash = "sha256:" + hashlib.sha256(content).hexdigest()[:16]
            # Redirect expanduser so the function reads our temp file
            with patch.object(_mod.os.path, "expanduser", return_value=tmp_path):  # type: ignore[attr-defined]
                result = build_routing_policy_hash()
            assert result == expected_hash
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_returns_empty_on_oserror(self) -> None:
        with patch.object(
            _mod.os.path,
            "exists",
            return_value=True,  # type: ignore[attr-defined]
        ):
            with patch("builtins.open", side_effect=OSError("permission denied")):
                result = build_routing_policy_hash()
        assert result == ""
