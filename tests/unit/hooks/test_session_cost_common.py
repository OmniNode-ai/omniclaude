# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from omniclaude.hooks.session_cost_common import (
    build_cost_payload,
    derive_idempotency_key,
    derive_machine_id,
    derive_repo_name,
    estimate_cost_usd,
    stable_payload_hash,
)


def test_stable_payload_hash_sorts_nested_payloads() -> None:
    left = {"b": [2, {"z": "last", "a": "first"}], "a": 1}
    right = {"a": 1, "b": [2, {"a": "first", "z": "last"}]}

    assert stable_payload_hash(left) == stable_payload_hash(right)


def test_idempotency_key_is_stable_for_same_logical_record() -> None:
    first = derive_idempotency_key(
        session_id="session-1",
        input_hash="abc123",
        repo_name="omniclaude",
        machine_id="machine-a",
    )
    second = derive_idempotency_key(
        session_id="session-1",
        input_hash="abc123",
        repo_name="omniclaude",
        machine_id="machine-a",
    )

    assert first == second
    assert len(first) == 64


def test_repo_derivation_from_canonical_repo() -> None:
    assert (
        derive_repo_name(
            "/workspace/omni_home",
            "/workspace/omni_home/omniclaude",
        )
        == "omniclaude"
    )


def test_repo_derivation_from_ticket_worktree() -> None:
    assert (
        derive_repo_name(
            "/workspace/omni_home",
            "/workspace/omni_home/omni_worktrees/OMN-10335/omniclaude",
        )
        == "omniclaude"
    )


def test_repo_derivation_returns_none_outside_omni_home() -> None:
    assert derive_repo_name("/workspace/omni_home", "/tmp/outside") is None


def test_machine_derivation_uses_onex_machine_id_only() -> None:
    assert (
        derive_machine_id({"ONEX_MACHINE_ID": " machine-1 ", "HOSTNAME": "ignored"})
        == "machine-1"
    )
    assert derive_machine_id({"HOSTNAME": "ignored"}) is None


def test_cost_payload_contains_nonzero_cost_and_idempotency_proof() -> None:
    payload = build_cost_payload(
        session_id="session-1",
        model_id="claude-sonnet-4-5-20250929",
        prompt_tokens=1000,
        completion_tokens=1000,
        correlation_id="corr-1",
        emitted_at="2026-04-29T12:00:00Z",
        repo_name="omniclaude",
        machine_id="machine-1",
        input_hash_source={"source": "test"},
    )

    assert payload["estimated_cost_usd"] == 0.018
    assert payload["cost_usd"] == 0.018
    assert payload["input_hash"]
    assert payload["idempotency_key"]
    assert payload["repo_name"] == "omniclaude"
    assert payload["machine_id"] == "machine-1"


def test_unknown_model_uses_default_nonzero_price() -> None:
    assert (
        estimate_cost_usd(
            model_id="claude-unknown",
            prompt_tokens=1000,
            completion_tokens=1000,
        )
        == 0.018
    )


def test_haiku_35_model_uses_haiku_35_price() -> None:
    assert (
        estimate_cost_usd(
            model_id="claude-3-5-haiku-20241022",
            prompt_tokens=1000,
            completion_tokens=1000,
        )
        == 0.0048
    )


def test_estimate_cost_rejects_negative_token_counts() -> None:
    with pytest.raises(ValueError, match="Token counts must be non-negative"):
        estimate_cost_usd(
            model_id="claude-sonnet-4-5-20250929",
            prompt_tokens=-1,
            completion_tokens=1000,
        )

    with pytest.raises(ValueError, match="Token counts must be non-negative"):
        estimate_cost_usd(
            model_id="claude-sonnet-4-5-20250929",
            prompt_tokens=1000,
            completion_tokens=-1,
        )
