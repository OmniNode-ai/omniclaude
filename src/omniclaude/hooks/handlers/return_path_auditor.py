# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Return path control PostToolUse hook handler.

Validates return payloads from sub-agents (Task/Agent tool completions)
against context integrity constraints declared in the context integrity
subcontract.

Enforcement model (OMN-5230):
    - PERMISSIVE: log only, never block
    - WARN:       emit audit event, never block
    - STRICT:     block + emit AuditReturnBoundedEvent + AuditScopeViolationEvent
    - PARANOID:   block + emit events + mark task INVALID in correlation manager

Constraints checked:
    1. Return payload token budget (return_schema.max_tokens)
    2. Return payload field allowlist (return_schema.allowed_fields)

Design constraints:
    - PostToolUse hooks cannot modify return payloads -- enforcement is
      reject-or-accept only (no stripping).
    - Graceful failure: all errors are logged; hook exits 0 on infrastructure
      failures so Claude Code is never blocked by audit machinery.
    - No datetime.now() defaults -- timestamps are injected by callers.
    - All Pydantic models use frozen=True and extra="forbid".

Related:
    - OMN-5230: Context Integrity Audit & Enforcement (parent epic)
    - OMN-5238: Task 8 -- Create return path control PostToolUse hook
    - OMN-5234: Audit event schemas (AuditReturnBoundedEvent,
      AuditScopeViolationEvent)
    - schemas_audit.py: AuditReturnBoundedEvent, AuditScopeViolationEvent
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hooks.schemas_audit import (
    AuditEnforcementAction,
    AuditReturnBoundedEvent,
    AuditScopeViolationEvent,
    AuditScopeViolationType,
)
from omniclaude.hooks.topics import TopicBase

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Characters-per-token approximation (GPT-4 family heuristic: ~4 chars/token).
# Used when a precise token counter is unavailable.
_CHARS_PER_TOKEN: int = 4

# Environment variable controlling the enforcement level.
# Defaults to WARN to be non-blocking in existing deployments.
_ENV_ENFORCEMENT_LEVEL = "OMNICLAUDE_RETURN_AUDIT_ENFORCEMENT"

# Default enforcement level when the env var is absent.
_DEFAULT_ENFORCEMENT_LEVEL = "WARN"

# Recognised enforcement levels (ordered by strictness).
_VALID_ENFORCEMENT_LEVELS: frozenset[str] = frozenset(
    {"PERMISSIVE", "WARN", "STRICT", "PARANOID"}
)

# Default return_schema when no contract subcontract is declared.
_DEFAULT_MAX_TOKENS: int = 8192
_DEFAULT_ALLOWED_FIELDS: list[str] = []  # empty = no field restriction


# =============================================================================
# Config model
# =============================================================================


class ReturnSchemaConfig(BaseModel):
    """Return schema constraints extracted from a context integrity subcontract.

    Attributes:
        max_tokens: Maximum token budget for the return payload.
        allowed_fields: Allowlist of field names permitted in the return
            payload. An empty list means no field restriction is applied.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_tokens: int = Field(
        default=_DEFAULT_MAX_TOKENS,
        ge=1,
        description="Maximum token budget for the return payload",
    )
    allowed_fields: list[str] = Field(
        default_factory=list,
        description="Allowlist of permitted top-level field names (empty = no restriction)",
    )


# =============================================================================
# Audit result model
# =============================================================================


class ReturnAuditResult(BaseModel):
    """Result of a single return path audit evaluation.

    Attributes:
        task_id: UUID of the completing task.
        blocked: Whether the return was blocked by enforcement.
        return_tokens: Estimated token count of the return payload.
        max_tokens: Maximum tokens declared in the contract.
        fields_returned: Top-level field names present in the return payload.
        disallowed_fields: Fields that violate the allowlist (empty if clean).
        enforcement_action: Action taken by the enforcement system.
        correlation_id: Correlation ID propagated from caller context.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID = Field(..., description="UUID of the completing task")
    blocked: bool = Field(..., description="Whether the return was blocked")
    return_tokens: int = Field(
        ..., ge=0, description="Estimated token count of the return payload"
    )
    max_tokens: int = Field(
        ..., ge=1, description="Maximum tokens declared in the contract"
    )
    fields_returned: list[str] = Field(
        ..., description="Top-level field names present in the return payload"
    )
    disallowed_fields: list[str] = Field(
        ..., description="Fields that violate the allowlist"
    )
    enforcement_action: AuditEnforcementAction = Field(
        ..., description="Action taken by the enforcement system"
    )
    correlation_id: UUID = Field(
        ..., description="Correlation ID propagated from caller context"
    )


# =============================================================================
# Token estimation
# =============================================================================


def estimate_tokens(payload_json: str) -> int:
    """Estimate the token count of a JSON payload string.

    Uses a character-per-token approximation when a tokeniser is unavailable.
    Callers should not rely on this being exact -- it is a conservative upper
    bound suitable for enforcement gating.

    Args:
        payload_json: Serialised JSON string of the return payload.

    Returns:
        Estimated token count (always >= 0).
    """
    char_count = len(payload_json)
    return max(0, (char_count + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


# =============================================================================
# Return path audit logic
# =============================================================================


def audit_return_payload(
    payload: dict[str, Any],
    schema: ReturnSchemaConfig,
    task_id: UUID,
    correlation_id: UUID,
    enforcement_level: str,
    emitted_at: datetime,
) -> ReturnAuditResult:
    """Audit a return payload against context integrity constraints.

    Checks:
        1. Token budget: ``len(json.dumps(payload)) / 4 <= schema.max_tokens``
        2. Field allowlist: all top-level keys in ``payload`` must appear in
           ``schema.allowed_fields`` (skipped when allowed_fields is empty).

    Args:
        payload: Deserialised return payload dict.
        schema: Return schema constraints from the subcontract.
        task_id: UUID of the completing task.
        correlation_id: Correlation UUID for distributed tracing.
        enforcement_level: One of PERMISSIVE, WARN, STRICT, PARANOID.
        emitted_at: Timestamp to stamp on emitted audit events.

    Returns:
        A ``ReturnAuditResult`` describing the outcome.
    """
    payload_json = json.dumps(payload, default=str)
    return_tokens = estimate_tokens(payload_json)

    fields_returned: list[str] = list(payload.keys())

    # Field allowlist check
    disallowed_fields: list[str] = []
    if schema.allowed_fields:
        allowed_set = set(schema.allowed_fields)
        disallowed_fields = [f for f in fields_returned if f not in allowed_set]

    # Determine violations
    token_exceeded = return_tokens > schema.max_tokens
    has_disallowed = bool(disallowed_fields)
    has_violation = token_exceeded or has_disallowed

    # Map enforcement level to action
    _level = enforcement_level.upper()
    if not has_violation or _level == "PERMISSIVE":
        action = AuditEnforcementAction.LOG
        blocked = False
    elif _level == "WARN":
        action = AuditEnforcementAction.WARN
        blocked = False
    elif _level in ("STRICT", "PARANOID"):
        action = AuditEnforcementAction.BLOCK
        blocked = True
    else:
        action = AuditEnforcementAction.WARN
        blocked = False

    # Emit AuditReturnBoundedEvent (always, even when clean)
    _emit_return_bounded_event(
        task_id=task_id,
        return_tokens=return_tokens,
        max_tokens=schema.max_tokens,
        fields_returned=fields_returned,
        blocked=blocked,
        correlation_id=correlation_id,
        emitted_at=emitted_at,
    )

    # Emit AuditScopeViolationEvent for each violation type
    if token_exceeded and _level != "PERMISSIVE":
        _emit_scope_violation_event(
            task_id=task_id,
            violation_type=AuditScopeViolationType.RETURN,
            declared_scope=[f"max_tokens:{schema.max_tokens}"],
            actual_access=f"return_tokens:{return_tokens}",
            enforcement_action=action,
            correlation_id=correlation_id,
            emitted_at=emitted_at,
        )

    if has_disallowed and _level != "PERMISSIVE":
        _emit_scope_violation_event(
            task_id=task_id,
            violation_type=AuditScopeViolationType.RETURN,
            declared_scope=schema.allowed_fields,
            actual_access=f"disallowed_fields:{','.join(disallowed_fields)}",
            enforcement_action=action,
            correlation_id=correlation_id,
            emitted_at=emitted_at,
        )

    # PARANOID: mark task INVALID in correlation manager (best-effort)
    if blocked and _level == "PARANOID":
        _mark_task_invalid(task_id=task_id, correlation_id=correlation_id)

    return ReturnAuditResult(
        task_id=task_id,
        blocked=blocked,
        return_tokens=return_tokens,
        max_tokens=schema.max_tokens,
        fields_returned=fields_returned,
        disallowed_fields=disallowed_fields,
        enforcement_action=action,
        correlation_id=correlation_id,
    )


# =============================================================================
# Event emission helpers (best-effort, never raise)
# =============================================================================


def _emit_return_bounded_event(
    *,
    task_id: UUID,
    return_tokens: int,
    max_tokens: int,
    fields_returned: list[str],
    blocked: bool,
    correlation_id: UUID,
    emitted_at: datetime,
) -> None:
    """Emit AuditReturnBoundedEvent to Kafka via cli_emit (best-effort).

    Failures are logged as warnings; they never propagate to the caller.
    """
    try:
        event = AuditReturnBoundedEvent(
            task_id=task_id,
            return_tokens=return_tokens,
            max_tokens=max_tokens,
            fields_returned=fields_returned,
            blocked=blocked,
            correlation_id=correlation_id,
            emitted_at=emitted_at,
        )
        _publish_audit_event(
            topic=TopicBase.AUDIT_RETURN_BOUNDED,
            payload=event.model_dump(mode="json"),
        )
    except Exception:  # noqa: BLE001 — boundary: emit must degrade not crash
        logger.warning("Failed to emit AuditReturnBoundedEvent", exc_info=True)


def _emit_scope_violation_event(
    *,
    task_id: UUID,
    violation_type: AuditScopeViolationType,
    declared_scope: list[str],
    actual_access: str,
    enforcement_action: AuditEnforcementAction,
    correlation_id: UUID,
    emitted_at: datetime,
) -> None:
    """Emit AuditScopeViolationEvent to Kafka via cli_emit (best-effort).

    Failures are logged as warnings; they never propagate to the caller.
    """
    try:
        event = AuditScopeViolationEvent(
            task_id=task_id,
            violation_type=violation_type,
            declared_scope=declared_scope,
            actual_access=actual_access,
            enforcement_action=enforcement_action,
            correlation_id=correlation_id,
            emitted_at=emitted_at,
        )
        _publish_audit_event(
            topic=TopicBase.AUDIT_SCOPE_VIOLATION,
            payload=event.model_dump(mode="json"),
        )
    except Exception:  # noqa: BLE001 — boundary: emit must degrade not crash
        logger.warning("Failed to emit AuditScopeViolationEvent", exc_info=True)


def _publish_audit_event(topic: str, payload: dict[str, Any]) -> None:
    """Publish an audit event payload to the given Kafka topic.

    Uses the existing omnibase_infra EventBusKafka pathway via a background
    subprocess call to ``omniclaude-emit``.  Non-blocking: failures are
    silently logged.

    Args:
        topic: The Kafka topic name.
        payload: Serialisable dict to send as the event body.
    """
    import subprocess

    python_cmd = sys.executable
    payload_json = json.dumps(payload, default=str)
    try:
        subprocess.Popen(  # noqa: S603
            [
                python_cmd,
                "-m",
                "omniclaude.hooks.cli_emit",  # noqa: arch-topic-naming — module path, not a Kafka topic
                "audit-event",
                "--topic",
                topic,
                "--payload",
                payload_json,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception:  # noqa: BLE001 — boundary: emit must degrade not crash
        logger.warning(
            "Failed to launch audit event emission subprocess", exc_info=True
        )


def _mark_task_invalid(*, task_id: UUID, correlation_id: UUID) -> None:
    """Mark a task as INVALID in the correlation manager (PARANOID mode).

    Best-effort: failures are logged as warnings and do not propagate.

    Args:
        task_id: UUID of the task to mark as invalid.
        correlation_id: Correlation UUID for the tracking scope.
    """
    try:
        from omniclaude.hooks.lib.correlation_manager import (
            CorrelationManager,
        )

        manager = CorrelationManager()
        manager.mark_task_invalid(
            task_id=str(task_id),
            reason="return_path_audit_block",
            correlation_id=str(correlation_id),
        )
        logger.info("PARANOID: marked task %s INVALID in correlation manager", task_id)
    except ImportError:
        logger.warning(
            "CorrelationManager not available; skipping PARANOID task invalidation"
        )
    except Exception:  # noqa: BLE001 — boundary: best-effort PARANOID invalidation
        logger.warning(
            "Failed to mark task %s INVALID in correlation manager",
            task_id,
            exc_info=True,
        )


# =============================================================================
# CLI entry point (invoked from PostToolUse shell script)
# =============================================================================


def _load_enforcement_level() -> str:
    """Read enforcement level from environment.

    Returns:
        One of PERMISSIVE, WARN, STRICT, PARANOID.
        Falls back to WARN if the env var is absent or unrecognised.
    """
    raw = os.environ.get(_ENV_ENFORCEMENT_LEVEL, _DEFAULT_ENFORCEMENT_LEVEL).upper()
    if raw not in _VALID_ENFORCEMENT_LEVELS:
        logger.warning(
            "Unrecognised enforcement level %r; defaulting to %s",
            raw,
            _DEFAULT_ENFORCEMENT_LEVEL,
        )
        return _DEFAULT_ENFORCEMENT_LEVEL
    return raw


def _extract_return_schema(tool_input: dict[str, Any]) -> ReturnSchemaConfig:
    """Extract return_schema constraints from PostToolUse tool_input.

    Looks for a ``return_schema`` key inside ``tool_input``.  Falls back to
    sensible defaults when the key is absent (contracts that predate OMN-5230
    have no return_schema).

    Args:
        tool_input: Parsed ``tool_input`` dict from the PostToolUse hook event.

    Returns:
        A ``ReturnSchemaConfig`` instance.
    """
    raw_schema = tool_input.get("return_schema", {})
    if not isinstance(raw_schema, dict):
        return ReturnSchemaConfig()
    return ReturnSchemaConfig(
        max_tokens=raw_schema.get("max_tokens", _DEFAULT_MAX_TOKENS),
        allowed_fields=raw_schema.get("allowed_fields", []),
    )


def _extract_payload(tool_response: dict[str, Any]) -> dict[str, Any]:
    """Extract the return payload dict from the PostToolUse hook event.

    Args:
        tool_response: Parsed ``tool_response`` dict from the hook event.

    Returns:
        The payload as a dict.  Returns an empty dict on failure.
    """
    payload = tool_response.get("content") or tool_response.get("output")
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            # Treat raw strings as a single-field payload for token estimation
            return {"_raw": payload}
    # Treat the entire tool_response as the payload when no content key found
    return dict(tool_response)


def main() -> None:
    """CLI entry point invoked by the PostToolUse shell script.

    Reads hook event JSON from stdin, audits the return payload, and writes
    the result JSON to stdout.  Always exits 0 so Claude Code is never blocked
    by audit failures.

    Input JSON schema (PostToolUse hook event from Claude Code):
        {
            "tool_name": "Task",       // or "Agent"
            "tool_input": {
                "return_schema": {     // optional -- from context integrity subcontract
                    "max_tokens": 4096,
                    "allowed_fields": ["status", "summary"]
                },
                ...
            },
            "tool_response": {         // completed sub-agent output
                "content": { ... }     // or "output": { ... }
            },
            "sessionId": "...",
            "correlation_id": "..."    // optional
        }

    Output JSON (written to stdout):
        {
            "blocked": false,
            "return_tokens": 312,
            "max_tokens": 4096,
            "fields_returned": ["status", "summary"],
            "disallowed_fields": [],
            "enforcement_action": "warn",
            "task_id": "<uuid>",
            "correlation_id": "<uuid>"
        }
    """
    try:
        raw = sys.stdin.read()
        hook_event: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("return_path_auditor: malformed hook event JSON: %s", exc)
        # Output passthrough so the pipeline is never blocked
        sys.stdout.write(raw if "raw" in dir() else "{}")
        sys.exit(0)

    tool_name: str = hook_event.get("tool_name", "")
    # Only audit Task/Agent tool completions
    if tool_name not in ("Task", "Agent"):
        sys.stdout.write(raw)
        sys.exit(0)

    tool_input: dict[str, Any] = hook_event.get("tool_input") or {}
    tool_response: dict[str, Any] = hook_event.get("tool_response") or {}

    # Resolve IDs
    task_id_raw = tool_input.get("task_id") or str(uuid4())
    try:
        task_id = UUID(str(task_id_raw))
    except (ValueError, AttributeError):
        task_id = uuid4()

    correlation_id_raw = hook_event.get("correlation_id") or str(uuid4())
    try:
        correlation_id = UUID(str(correlation_id_raw))
    except (ValueError, AttributeError):
        correlation_id = uuid4()

    schema = _extract_return_schema(tool_input)
    payload = _extract_payload(tool_response)
    enforcement_level = _load_enforcement_level()
    emitted_at = datetime.now(UTC)

    try:
        result = audit_return_payload(
            payload=payload,
            schema=schema,
            task_id=task_id,
            correlation_id=correlation_id,
            enforcement_level=enforcement_level,
            emitted_at=emitted_at,
        )
    except Exception as exc:
        logger.error("return_path_auditor: audit failed: %s", exc, exc_info=True)
        # Fail open: never block Claude Code due to audit machinery errors
        sys.stdout.write(raw)
        sys.exit(0)

    # Emit result JSON to stdout for the shell script to inspect
    output: dict[str, Any] = {
        "blocked": result.blocked,
        "return_tokens": result.return_tokens,
        "max_tokens": result.max_tokens,
        "fields_returned": result.fields_returned,
        "disallowed_fields": result.disallowed_fields,
        "enforcement_action": result.enforcement_action.value,
        "task_id": str(result.task_id),
        "correlation_id": str(result.correlation_id),
        # Always pass through original hook event so the shell script can
        # forward it to the next hook in the chain.
        "_hook_event": hook_event,
    }
    sys.stdout.write(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
