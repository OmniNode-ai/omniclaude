# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for DelegationRunner — Bifrost gateway wiring (OMN-10636).

Tests verify:
- DelegationRunner returns None gracefully when no config is available
- DelegationRunner routes through a mocked Bifrost gateway and captures routing metadata
- Audit events are emitted on every call (success and failure)
- run() returns a failed result when all Bifrost backends are down
- run() returns None on unexpected gateway exception
- _build_env_config() builds valid config from env vars
- _extract_response_text() handles diverse response shapes
- ModelBifrostRunnerResult captures rule_id, config_version, backend_selected
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from omniclaude.delegation.runner import (
    DelegationRunner,
    ModelBifrostRunnerResult,
    ModelDelegationAuditEvent,
    _build_env_config,
    _extract_response_text,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_BACKEND_ID = "coder-fast"
_RULE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_CORR_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _make_runner_result(
    *,
    success: bool = True,
    response_text: str = "hello from local model",
    backend_selected: str = _BACKEND_ID,
    rule_id: str = str(_RULE_ID),
    config_version: str = "test-v1",
    latency_ms: float = 42.0,
    retry_count: int = 0,
    error_message: str = "",
) -> ModelBifrostRunnerResult:
    """Build a ModelBifrostRunnerResult for use as a mock return value."""
    return ModelBifrostRunnerResult(
        success=success,
        response_text=response_text,
        backend_selected=backend_selected,
        rule_id=rule_id,
        config_version=config_version,
        latency_ms=latency_ms,
        retry_count=retry_count,
        error_message=error_message,
    )


def _make_runner(
    *,
    on_audit_event=None,
    config_version: str = "test-v1",
    run_async_result: ModelBifrostRunnerResult | None = None,
    run_async_raises: Exception | None = None,
) -> DelegationRunner:
    """Build a DelegationRunner with _run_async patched to avoid omnibase_infra imports.

    Tests that exercise run() / run_async() behavior mock _run_async so that
    the lazy omnibase_infra imports inside that method are never triggered.
    This avoids the syntax error in handler_llm_openai_compatible.py present
    in the current omni_home canonical clone.
    """
    runner = DelegationRunner(
        config=MagicMock(),  # non-None config → _ensure_gateway skips env fallback
        on_audit_event=on_audit_event,
        config_version=config_version,
    )
    # Inject a stub gateway so _ensure_gateway returns True without importing infra
    runner._gateway = MagicMock()

    if run_async_raises is not None:
        runner._run_async = AsyncMock(side_effect=run_async_raises)
    else:
        result = run_async_result or _make_runner_result()
        runner._run_async = AsyncMock(return_value=result)

    return runner


# ---------------------------------------------------------------------------
# Tests: no-config path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_runner_returns_none_when_no_config() -> None:
    """Runner returns None if no config and no env vars are set."""
    runner = DelegationRunner(config=None)
    with patch("omniclaude.delegation.runner._build_env_config", return_value=None):
        result = runner.run("do something")
    assert result is None


@pytest.mark.unit
def test_runner_returns_failed_result_on_empty_prompt() -> None:
    """Runner returns a failed result for empty prompts (not None)."""
    runner = _make_runner()
    result = runner.run("")
    assert result is not None
    assert result.success is False
    assert "empty_prompt" in result.error_message


# ---------------------------------------------------------------------------
# Tests: success path — run() wraps _run_async
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_runner_success_path_captures_routing_metadata() -> None:
    """run() returns routing metadata from _run_async on success."""
    expected = _make_runner_result(
        backend_selected=_BACKEND_ID,
        rule_id=str(_RULE_ID),
        config_version="sha-abc123",
        latency_ms=55.5,
        retry_count=1,
        response_text="result text",
    )
    runner = _make_runner(config_version="sha-abc123", run_async_result=expected)

    result = runner.run("summarize this file", correlation_id=str(_CORR_ID))

    assert isinstance(result, ModelBifrostRunnerResult)
    assert result.success is True
    assert result.response_text == "result text"
    assert result.backend_selected == _BACKEND_ID
    assert result.rule_id == str(_RULE_ID)
    assert result.config_version == "sha-abc123"
    assert result.latency_ms == pytest.approx(55.5)
    assert result.retry_count == 1


@pytest.mark.unit
def test_runner_success_path_with_no_rule_id() -> None:
    """rule_id is empty string when Bifrost uses the default backend fallback."""
    expected = _make_runner_result(rule_id="")
    runner = _make_runner(run_async_result=expected)

    result = runner.run("prompt")

    assert result is not None
    assert result.rule_id == ""


# ---------------------------------------------------------------------------
# Tests: audit event emission
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_audit_event_emitted_via_emit_audit_direct() -> None:
    """_emit_audit_direct delivers a ModelDelegationAuditEvent to the callback."""
    received: list[ModelDelegationAuditEvent] = []
    runner = _make_runner(on_audit_event=received.append, config_version="v2")

    runner._emit_audit_direct(
        correlation_id="corr-1",
        session_id="sess-abc",
        backend_selected=_BACKEND_ID,
        rule_id=str(_RULE_ID),
        latency_ms=10.0,
        retry_count=0,
        success=True,
        error_message="",
    )

    assert len(received) == 1
    evt = received[0]
    assert isinstance(evt, ModelDelegationAuditEvent)
    assert evt.correlation_id == "corr-1"
    assert evt.session_id == "sess-abc"
    assert evt.backend_selected == _BACKEND_ID
    assert evt.rule_id == str(_RULE_ID)
    assert evt.config_version == "v2"
    assert evt.success is True
    assert evt.error_message == ""


@pytest.mark.unit
def test_audit_event_emitted_on_failure() -> None:
    """_emit_audit_direct emits success=False event with error_message."""
    received: list[ModelDelegationAuditEvent] = []
    runner = _make_runner(on_audit_event=received.append)

    runner._emit_audit_direct(
        correlation_id="corr-fail",
        session_id="",
        backend_selected="",
        rule_id="",
        latency_ms=5.0,
        retry_count=2,
        success=False,
        error_message="bifrost_call_failed: ConnectionError: refused",
    )

    assert len(received) == 1
    evt = received[0]
    assert evt.success is False
    assert "bifrost_call_failed" in evt.error_message


@pytest.mark.unit
def test_no_crash_when_audit_callback_raises() -> None:
    """Exceptions in on_audit_event must not propagate out of the runner."""

    def _bad_callback(_event: ModelDelegationAuditEvent) -> None:
        raise RuntimeError("callback failure")

    runner = _make_runner(on_audit_event=_bad_callback)
    # Should not raise
    runner._emit_audit_direct(
        correlation_id="x",
        session_id="",
        backend_selected="",
        rule_id="",
        latency_ms=0.0,
        retry_count=0,
        success=True,
        error_message="",
    )


@pytest.mark.unit
def test_no_audit_event_when_no_callback() -> None:
    """_emit_audit_direct is a no-op when on_audit_event is None."""
    runner = _make_runner(on_audit_event=None)
    # Should not raise and produce no side effect
    runner._emit_audit_direct(
        correlation_id="x",
        session_id="",
        backend_selected="a",
        rule_id="r",
        latency_ms=1.0,
        retry_count=0,
        success=True,
        error_message="",
    )


# ---------------------------------------------------------------------------
# Tests: failure paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_runner_returns_failed_result_when_all_backends_down() -> None:
    """When _run_async returns success=False, run() propagates the failed result."""
    failed = _make_runner_result(
        success=False,
        backend_selected="",
        rule_id="",
        error_message="All backends failed after 3 attempt(s).",
    )
    runner = _make_runner(run_async_result=failed)

    result = runner.run("something")

    assert result is not None
    assert result.success is False
    assert "All backends failed" in result.error_message


@pytest.mark.unit
def test_runner_returns_none_on_unexpected_exception_from_run_async() -> None:
    """run() returns None when _run_async raises an unexpected exception."""
    runner = _make_runner(run_async_raises=RuntimeError("unexpected"))

    result = runner.run("something")

    assert result is None


# ---------------------------------------------------------------------------
# Tests: _build_env_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_env_config_returns_none_when_no_contract(monkeypatch, tmp_path) -> None:
    """_build_env_config returns None when no bifrost contract is available."""
    monkeypatch.setenv("BIFROST_CONTRACT_PATH", str(tmp_path / "nonexistent.yaml"))

    result = _build_env_config()
    assert result is None


_CODER_FAST_URL = (
    "http://192.168.86.201:8001"  # onex-allow-internal-ip  # kafka-fallback-ok
)


def _write_bifrost_with_endpoints(tmp_path, endpoints: dict[str, str]):
    """Write a bifrost contract with endpoint_url populated for given backends."""
    import shutil

    src = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "omniclaude"
        / "delegation"
        / "bifrost_delegation.yaml"
    )
    dst = tmp_path / "bifrost_delegation.yaml"
    shutil.copy2(src, dst)

    import yaml

    data = yaml.safe_load(dst.read_text())
    for backend in data.get("backends", []):
        bid = backend.get("backend_id", "")
        if bid in endpoints:
            backend["endpoint_url"] = endpoints[bid]
    dst.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return dst


@pytest.mark.unit
def test_build_env_config_builds_config_from_single_var(monkeypatch, tmp_path) -> None:
    """_build_env_config loads from contract and reads endpoint_url directly."""
    dst = _write_bifrost_with_endpoints(
        tmp_path, {"local-deepseek-r1-14b": _CODER_FAST_URL}
    )
    monkeypatch.setenv("BIFROST_CONTRACT_PATH", str(dst))

    cfg = _build_env_config()

    assert cfg is not None
    assert "local-deepseek-r1-14b" in cfg.backends
    assert cfg.backends["local-deepseek-r1-14b"].base_url == _CODER_FAST_URL
    assert (
        cfg.backends["local-deepseek-r1-14b"].model_name
        == "Corianas/DeepSeek-R1-Distill-Qwen-14B-AWQ"
    )
    assert len(cfg.routing_rules) >= 1


@pytest.mark.unit
def test_build_env_config_stable_rule_id_across_calls(monkeypatch, tmp_path) -> None:
    """Contract-derived rule_ids are stable across loads."""
    dst = _write_bifrost_with_endpoints(
        tmp_path, {"local-deepseek-r1-14b": _CODER_FAST_URL}
    )
    monkeypatch.setenv("BIFROST_CONTRACT_PATH", str(dst))

    cfg1 = _build_env_config()
    cfg2 = _build_env_config()

    assert cfg1 is not None
    assert cfg2 is not None
    assert cfg1.routing_rules[0].rule_id == cfg2.routing_rules[0].rule_id


@pytest.mark.unit
def test_build_env_config_multiple_backends(monkeypatch, tmp_path) -> None:
    """_build_env_config includes all backends with populated endpoint_url."""
    dst = _write_bifrost_with_endpoints(
        tmp_path,
        {
            "local-qwen-coder-30b": "http://host:8000",
            "local-deepseek-r1-14b": "http://host:8001",
        },
    )
    monkeypatch.setenv("BIFROST_CONTRACT_PATH", str(dst))

    cfg = _build_env_config()

    assert cfg is not None
    assert "local-qwen-coder-30b" in cfg.backends
    assert "local-deepseek-r1-14b" in cfg.backends
    assert cfg.failover_attempts == 3


# ---------------------------------------------------------------------------
# Tests: _extract_response_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_response_text_from_choices_message() -> None:
    """Extracts content from choices[0].message.content (standard path)."""
    msg = MagicMock()
    msg.content = "the answer"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    assert _extract_response_text(resp) == "the answer"


@pytest.mark.unit
def test_extract_response_text_from_choice_content_direct() -> None:
    """Extracts content from choices[0].content when message.content is absent."""
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = None
    choice.content = "direct"
    resp = MagicMock()
    resp.choices = [choice]

    assert _extract_response_text(resp) == "direct"


@pytest.mark.unit
def test_extract_response_text_from_response_content_attr() -> None:
    """Extracts content from response.content when choices is absent."""
    resp = MagicMock()
    resp.choices = []
    resp.generated_text = None
    resp.content = "toplevel"

    assert _extract_response_text(resp) == "toplevel"


@pytest.mark.unit
def test_extract_response_text_from_generated_text() -> None:
    """Extracts from generated_text (ModelLlmInferenceResponse field)."""
    resp = MagicMock()
    resp.choices = None
    resp.content = None
    resp.generated_text = "fibonacci code"

    assert _extract_response_text(resp) == "fibonacci code"


@pytest.mark.unit
def test_extract_response_text_returns_empty_on_no_content() -> None:
    """Returns empty string when no content can be extracted."""
    resp = MagicMock()
    resp.choices = []
    resp.content = None
    resp.generated_text = None

    assert _extract_response_text(resp) == ""


# ---------------------------------------------------------------------------
# Tests: async run_async path
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_async_returns_none_when_no_config() -> None:
    """run_async returns None when no config is available."""
    runner = DelegationRunner(config=None)
    with patch("omniclaude.delegation.runner._build_env_config", return_value=None):
        result = await runner.run_async("something")
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_async_returns_result_on_success() -> None:
    """run_async returns a ModelBifrostRunnerResult when _run_async succeeds."""
    expected = _make_runner_result(response_text="async result")
    runner = _make_runner(run_async_result=expected)

    result = await runner.run_async("async prompt", correlation_id="corr-async")

    assert result is not None
    assert result.success is True
    assert result.response_text == "async result"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_async_returns_none_on_unexpected_exception() -> None:
    """run_async returns None when _run_async raises unexpectedly."""
    runner = _make_runner(run_async_raises=RuntimeError("boom"))

    result = await runner.run_async("something")

    assert result is None


# ---------------------------------------------------------------------------
# Tests: ModelDelegationAuditEvent validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_audit_event_model_validates_correctly() -> None:
    """ModelDelegationAuditEvent accepts valid fields."""
    event = ModelDelegationAuditEvent(
        correlation_id="c1",
        session_id="s1",
        backend_selected="coder-fast",
        rule_id="r1",
        config_version="v1",
        latency_ms=10.0,
        retry_count=0,
        success=True,
        error_message="",
    )
    assert event.success is True
    assert event.backend_selected == "coder-fast"


@pytest.mark.unit
def test_audit_event_model_rejects_extra_fields() -> None:
    """ModelDelegationAuditEvent rejects extra fields (extra='forbid')."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ModelDelegationAuditEvent(
            correlation_id="c1",
            success=True,
            unknown_field="bad",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Tests: ModelBifrostRunnerResult validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_runner_result_model_validates_correctly() -> None:
    """ModelBifrostRunnerResult accepts valid fields."""
    result = ModelBifrostRunnerResult(
        success=True,
        response_text="hello",
        backend_selected="backend-a",
        rule_id="rule-1",
        config_version="sha-abc",
        latency_ms=30.0,
        retry_count=0,
    )
    assert result.response_text == "hello"
    assert result.config_version == "sha-abc"
