# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Timeout values reach hook libraries and the CI relay from the timeouts contract (OMN-21737)."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from omniclaude.hooks import alert_channel
from omniclaude.hooks.lib.code_context_sync import (
    _HttpQdrantClient,
    resolve_code_context_sync,
)
from omniclaude.hooks.lib.compliance_result_subscriber import run_subscriber
from omniclaude.models.model_ci_relay_timeouts import (
    ModelCiRelayTimeouts,
    relay_timeouts,
)
from omniclaude.models.model_hook_timeouts import (
    ModelHookTimeouts,
    hook_timeouts,
)
from omniclaude.services.ci_relay.rate_limiter import RateLimiter

_CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "omniclaude"
    / "contracts"
    / "contract_omniclaude_timeouts.yaml"
)

pytestmark = pytest.mark.unit


def _section(name: str) -> dict[str, object]:
    return yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))[name]


def test_hook_timeouts_equal_contract_section() -> None:
    assert hook_timeouts().model_dump() == _section("hooks")


def test_ci_relay_timeouts_equal_contract_section() -> None:
    assert relay_timeouts().model_dump() == _section("ci_relay")


def test_missing_value_fails_validation(tmp_path: Path) -> None:
    section = dict(_section("hooks"))
    del section["cli_emit_seconds"]
    path = tmp_path / "contract.yaml"
    path.write_text(yaml.safe_dump({"hooks": section}), encoding="utf-8")
    with pytest.raises(ValidationError):
        ModelHookTimeouts.from_contract(path)


def test_non_positive_value_fails_validation(tmp_path: Path) -> None:
    section = dict(_section("ci_relay"))
    section["gh_api_seconds"] = 0
    path = tmp_path / "contract.yaml"
    path.write_text(yaml.safe_dump({"ci_relay": section}), encoding="utf-8")
    with pytest.raises(ValidationError):
        ModelCiRelayTimeouts.from_contract(path)


def test_alert_channel_defaults_come_from_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONEX_ALERT_LIVENESS_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("ONEX_ALERT_LIVENESS_TTL_SECONDS", raising=False)
    expected = hook_timeouts()
    assert alert_channel._timeout() == expected.alert_timeout_seconds
    assert alert_channel._ttl() == expected.alert_ttl_seconds


def test_alert_channel_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEX_ALERT_LIVENESS_TIMEOUT_SECONDS", "7.5")
    assert alert_channel._timeout() == 7.5


def test_qdrant_client_takes_its_timeout_from_the_caller() -> None:
    assert _HttpQdrantClient("http://q", timeout=9.0)._timeout == 9.0


def test_code_context_sync_default_budget_comes_from_contract() -> None:
    default = inspect.signature(resolve_code_context_sync).parameters["timeout_seconds"]
    assert default.default == hook_timeouts().resolve_secs


def test_subscriber_poll_default_comes_from_contract() -> None:
    default = inspect.signature(run_subscriber).parameters["poll_timeout_ms"]
    assert default.default == hook_timeouts().poll_ms


def test_rate_limiter_dedupe_ttl_defaults_to_contract_and_accepts_injection() -> None:
    assert RateLimiter()._dedupe_ttl_seconds == relay_timeouts().dedupe_ttl_seconds
    assert RateLimiter(dedupe_ttl_seconds=11)._dedupe_ttl_seconds == 11
