# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Common helpers for deterministic LLM cost SessionEnd payloads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

UNKNOWN_MODEL_ID = "claude-unknown"
DEFAULT_INPUT_USD_PER_MILLION = Decimal("3.00")
DEFAULT_OUTPUT_USD_PER_MILLION = Decimal("15.00")

_PRICE_TABLE_USD_PER_MILLION: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("opus", Decimal("15.00"), Decimal("75.00")),
    ("sonnet", Decimal("3.00"), Decimal("15.00")),
    ("3-5-haiku", Decimal("0.80"), Decimal("4.00")),
    ("haiku-3-5", Decimal("0.80"), Decimal("4.00")),
    ("haiku", Decimal("0.25"), Decimal("1.25")),
)


def canonical_json(value: object) -> str:
    """Return deterministic JSON for hashing and repeatable payloads."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_payload_hash(value: object) -> str:
    """Hash a JSON-compatible value using canonical JSON serialization."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def derive_idempotency_key(
    *, session_id: str, input_hash: str, repo_name: str | None, machine_id: str | None
) -> str:
    """Derive a durable idempotency key for a logical SessionEnd cost record."""
    return stable_payload_hash(
        {
            "event_type": "llm.cost.completed",
            "session_id": session_id,
            "input_hash": input_hash,
            "repo_name": repo_name,
            "machine_id": machine_id,
        }
    )


def derive_repo_name(omni_home: str | None, project_dir: str | None) -> str | None:
    """Derive the canonical repo name from a path under ``$OMNI_HOME``."""
    if not omni_home or not project_dir:
        return None

    try:
        home = Path(omni_home).expanduser().resolve(strict=False)
        project = Path(project_dir).expanduser().resolve(strict=False)
        relative = project.relative_to(home)
    except (OSError, ValueError):
        return None

    parts = relative.parts
    if not parts:
        return None
    if parts[0] == "omni_worktrees" and len(parts) >= 3:
        return parts[2]
    return parts[0]


def derive_machine_id(env: dict[str, str]) -> str | None:
    """Derive machine identity only from ``ONEX_MACHINE_ID``."""
    value = env.get("ONEX_MACHINE_ID", "").strip()
    return value or None


def estimate_cost_usd(
    *, model_id: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """Estimate USD cost using static Claude per-million-token rates."""
    if prompt_tokens < 0 or completion_tokens < 0:
        raise ValueError("Token counts must be non-negative")

    model_key = model_id.lower()
    input_rate = DEFAULT_INPUT_USD_PER_MILLION
    output_rate = DEFAULT_OUTPUT_USD_PER_MILLION
    for marker, marker_input_rate, marker_output_rate in _PRICE_TABLE_USD_PER_MILLION:
        if marker in model_key:
            input_rate = marker_input_rate
            output_rate = marker_output_rate
            break

    cost = (
        Decimal(prompt_tokens) * input_rate + Decimal(completion_tokens) * output_rate
    ) / Decimal(1_000_000)
    return float(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def build_cost_payload(
    *,
    session_id: str,
    model_id: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    correlation_id: str | None,
    emitted_at: str,
    repo_name: str | None,
    machine_id: str | None,
    input_hash_source: Mapping[str, object],
) -> dict[str, object]:
    """Build the canonical ``llm.cost.completed`` payload."""
    normalized_session_id = session_id.strip()
    normalized_model_id = (model_id or "").strip() or UNKNOWN_MODEL_ID
    normalized_correlation_id = (correlation_id or "").strip() or None
    input_hash = stable_payload_hash(input_hash_source)
    idempotency_key = derive_idempotency_key(
        session_id=normalized_session_id,
        input_hash=input_hash,
        repo_name=repo_name,
        machine_id=machine_id,
    )
    total_tokens = prompt_tokens + completion_tokens
    cost_usd = estimate_cost_usd(
        model_id=normalized_model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    return {
        "session_id": normalized_session_id,
        "model_id": normalized_model_id,
        "correlation_id": normalized_correlation_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "estimated_cost_usd": cost_usd,
        "cost_usd": cost_usd,
        "timestamp_iso": emitted_at,
        "emitted_at": emitted_at,
        "request_type": "session",
        "reporting_source": "omniclaude",
        "usage_source": "ClaudeCodeSessionEnd",
        "request_count": 1,
        "repo_name": repo_name,
        "machine_id": machine_id,
        "input_hash": input_hash,
        "idempotency_key": idempotency_key,
        "idempotency_version": "cost-session-v1",
    }
