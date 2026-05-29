#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Runtime-compatible telemetry shape for hook delegation (T18).

All fields in ModelHookDelegationTelemetry are NON-AUTHORITATIVE.
They mirror the shape of the runtime delegation event
(onex.evt.omniclaude.task-delegated.v1) so downstream projections can consume
hook-path events alongside runtime-path events, but they carry reduced fidelity:

  - routing_policy_hash: SHA-256 of the local delegation-rules.yaml path, not a
    contract-versioned routing policy hash from node_routing_policy_engine.
  - tokens_input / tokens_output: always 0 — the hook path does not observe LLM
    token usage; it classifies at the shell level before any LLM call.
  - cost_usd: always 0.0 — same reason.
  - quality_result.passed: reflects run_hook_quality_gate() (T19), which is
    non-blocking and advisory only; not the FSM quality gate in
    node_delegation_orchestrator. fail_category is "pass" or "fail_heuristic" only.

Source: docs/architecture/omniclaude-delegation-classification.md (T17)
Quality gate: plugins/onex/hooks/lib/hook_quality_gate.py (T19)
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Non-authoritative quality result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HookQualityResult:
    """Non-authoritative quality gate result from the hook delegation path.

    Unlike the runtime path (FSM state GATE_EVALUATED with budget + escalation),
    the hook path runs check_agentic_quality() non-blocking with log-only effect.
    This result records what the hook observed, not what the platform decided.
    """

    # NON-AUTHORITATIVE: result of check_agentic_quality(), not FSM quality gate
    passed: bool
    # NON-AUTHORITATIVE: reason from local quality check, not runtime gate
    reason: str = ""
    # Marker: always present so consumers can filter hook-path events
    authoritative: bool = field(default=False, init=False)


# ---------------------------------------------------------------------------
# Non-authoritative telemetry envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelHookDelegationTelemetry:
    """Runtime-compatible telemetry emitted by the hook delegation path (T18).

    Shape mirrors onex.evt.omniclaude.task-delegated.v1 so omnidash projections
    can ingest hook-path events alongside runtime-path events.

    ALL FIELDS ARE NON-AUTHORITATIVE. See module docstring for per-field caveats.
    Field ``hook_path_non_authoritative=True`` is always set so consumers can
    distinguish hook-path events from runtime-path events in projections.
    """

    correlation_id: str
    session_id: str
    task_type: str  # NON-AUTHORITATIVE: from TaskClassifier, not routing policy engine
    delegated_to: str  # model name from classifier
    delegated_by: str = "omniclaude.hook.pre_tool_use_delegation"

    # NON-AUTHORITATIVE: SHA-256 of local delegation-rules.yaml, not platform policy hash
    routing_policy_hash: str = ""

    # NON-AUTHORITATIVE: 0 — hook path does not observe LLM token usage
    tokens_input: int = 0
    tokens_output: int = 0

    # NON-AUTHORITATIVE: 0.0 — hook path does not observe LLM cost
    cost_usd: float = 0.0

    # NON-AUTHORITATIVE: latency from classification, not end-to-end delegation
    delegation_latency_ms: int = 0

    # NON-AUTHORITATIVE: result of local quality check, not FSM gate
    quality_result: HookQualityResult = field(
        default_factory=lambda: HookQualityResult(passed=True)
    )

    # Always True: marker for downstream consumers to distinguish from runtime events
    hook_path_non_authoritative: bool = field(default=True, init=False)
    emitted_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "task_type": self.task_type,
            "delegated_to": self.delegated_to,
            "delegated_by": self.delegated_by,
            "routing_policy_hash": self.routing_policy_hash,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "cost_usd": self.cost_usd,
            "delegation_latency_ms": self.delegation_latency_ms,
            "quality_result": {
                "passed": self.quality_result.passed,
                "reason": self.quality_result.reason,
                "authoritative": self.quality_result.authoritative,
            },
            "hook_path_non_authoritative": self.hook_path_non_authoritative,
            "emitted_at": self.emitted_at,
        }


# ---------------------------------------------------------------------------
# Routing policy hash helper
# ---------------------------------------------------------------------------


def hook_quality_result_from_gate(
    gate_result_dict: dict[str, object],
) -> HookQualityResult:
    """Build a HookQualityResult from a ModelHookQualityGateResult.to_dict() payload (T19).

    Bridges the T19 quality gate output into the T18 telemetry envelope so the
    quality_result field in ModelHookDelegationTelemetry reflects the actual gate
    verdict rather than the default passed=True placeholder.

    Args:
        gate_result_dict: Output of ModelHookQualityGateResult.to_dict().

    Returns:
        HookQualityResult with passed/reason populated from the gate.
    """
    passed = bool(gate_result_dict.get("passed", True))
    reasons = gate_result_dict.get("failure_reasons", [])
    reason = (
        "; ".join(str(r) for r in reasons)
        if isinstance(reasons, list)
        else str(reasons)
    )
    return HookQualityResult(passed=passed, reason=reason)


def build_routing_policy_hash() -> str:
    """Return a SHA-256 hash identifying the local routing rules config.

    NON-AUTHORITATIVE: This hashes the path of the local delegation-rules.yaml
    file, not a contract-versioned policy from node_routing_policy_engine.
    Useful only for detecting when the local config has changed across sessions.
    Returns empty string when the config file does not exist.
    """
    rules_path = os.path.expanduser("~/.omninode/delegation/delegation-rules.yaml")
    if not os.path.exists(rules_path):
        return ""
    try:
        with open(rules_path, "rb") as f:
            return "sha256:" + hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return ""


__all__: list[str] = [
    "HookQualityResult",
    "ModelHookDelegationTelemetry",
    "build_routing_policy_hash",
    "hook_quality_result_from_gate",
]
