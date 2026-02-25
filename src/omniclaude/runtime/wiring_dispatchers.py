# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Contract-driven skill command dispatcher wiring.

Implements ``wire_skill_dispatchers()`` — the multiplexed router that maps a
single wildcard topic pattern (``onex.cmd.omniclaude.*.v1``) to all skill
backends by reading ``execution.backend`` from each contract.

Canonical pattern: ``omnibase_infra/nodes/node_registration_orchestrator/plugin.py:932-1013``

Sequence:
    1. Load contracts from ``OMNICLAUDE_CONTRACTS_ROOT`` via glob.
    2. Validate parse rate against the 80% threshold.
    3. Resolve backend instances from the plugin (SubprocessClaudeCodeSessionBackend,
       VllmInferenceBackend).
    4. Build a ``SkillCommandDispatcher`` that extracts ``skill_id`` from the
       inbound topic, looks up the contract, selects the backend, wraps it into
       a ``task_dispatcher`` adapter, calls ``handle_skill_requested``, and emits
       a ``ModelSkillCompletionEvent``.
    5. Register one dispatcher + one route on the ``MessageDispatchEngine``.

Ticket: OMN-2802
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import yaml
from omnibase_core.enums import EnumMessageCategory
from omnibase_core.models.dispatch.model_dispatch_route import ModelDispatchRoute

from omniclaude.nodes.shared.handler_skill_requested import handle_skill_requested
from omniclaude.nodes.shared.models.model_skill_completion_event import (
    ModelSkillCompletionEvent,
)
from omniclaude.nodes.shared.models.model_skill_node_contract import (
    ModelSkillNodeContract,
)
from omniclaude.nodes.shared.models.model_skill_request import ModelSkillRequest
from omniclaude.nodes.shared.models.model_skill_result import SkillResultStatus

if TYPE_CHECKING:
    from omnibase_core.models.events.model_event_envelope import ModelEventEnvelope
    from omnibase_infra.runtime import MessageDispatchEngine

    from omniclaude.nodes.node_claude_code_session_effect.backends.backend_subprocess import (
        SubprocessClaudeCodeSessionBackend,
    )
    from omniclaude.nodes.node_local_llm_inference_effect.backends.backend_vllm import (
        VllmInferenceBackend,
    )

__all__ = ["ContractLoadError", "wire_skill_dispatchers"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOPIC_PATTERN = "onex.cmd.omniclaude.*.v1"  # arch-topic-naming: ignore
_DISPATCHER_ID = "dispatcher.skill.command"
_ROUTE_ID = "skill-command-router"
_COMPLETION_TOPIC = "onex.evt.omniclaude.skill-completed.v1"

_CONTRACT_PARSE_THRESHOLD = 0.80


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ContractLoadError(Exception):
    """Raised when fewer than 80% of skill contracts can be parsed."""

    def __init__(self, parsed: int, total: int, threshold: float) -> None:
        self.parsed = parsed
        self.total = total
        self.threshold = threshold
        ratio = parsed / total if total > 0 else 0.0
        super().__init__(
            f"Contract parse rate {ratio:.1%} ({parsed}/{total}) "
            f"below threshold {threshold:.0%}"
        )


# ---------------------------------------------------------------------------
# Contract loading
# ---------------------------------------------------------------------------


class WiringSummary(TypedDict):
    """Summary dict returned by ``wire_skill_dispatchers``."""

    dispatchers: list[str]
    routes: list[str]
    contracts_loaded: int
    contracts_total: int
    backends: dict[str, str]


def _extract_skill_id_from_name(contract_name: str) -> str:
    """Derive the skill_id (topic segment) from a contract name.

    Convention: ``node_skill_{snake_name}_orchestrator`` -> snake_name with
    underscores replaced by hyphens.

    Example:
        >>> _extract_skill_id_from_name("node_skill_local_review_orchestrator")
        'local-review'
    """
    prefix = "node_skill_"
    suffix = "_orchestrator"
    if contract_name.startswith(prefix) and contract_name.endswith(suffix):
        inner = contract_name[len(prefix) : -len(suffix)]
        return inner.replace("_", "-")
    # Fallback: return the full name with underscores as hyphens
    return contract_name.replace("_", "-")


def load_skill_contracts(
    contracts_root: Path,
) -> dict[str, ModelSkillNodeContract]:
    """Load and parse all skill node contract.yaml files.

    Scans ``contracts_root`` for directories matching ``node_skill_*`` and
    parses each ``contract.yaml`` into a ``ModelSkillNodeContract``.

    Args:
        contracts_root: Root directory containing node directories.

    Returns:
        Mapping of skill_id (topic segment) to parsed contract.

    Raises:
        ContractLoadError: If parse rate falls below 80%.
    """
    contract_files = sorted(contracts_root.glob("node_skill_*/contract.yaml"))
    total = len(contract_files)
    if total == 0:
        logger.warning("No skill node contracts found in %s", contracts_root)
        return {}

    contracts: dict[str, ModelSkillNodeContract] = {}
    errors: list[str] = []

    for path in contract_files:
        try:
            with path.open() as fh:
                raw = yaml.safe_load(fh)
            if not isinstance(raw, dict):
                errors.append(f"{path}: not a dict")
                continue
            contract = ModelSkillNodeContract.model_validate(raw)
            skill_id = _extract_skill_id_from_name(contract.name)
            contracts[skill_id] = contract
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            logger.warning("Failed to parse contract %s: %s", path, exc)

    parsed = len(contracts)
    if total > 0 and (parsed / total) < _CONTRACT_PARSE_THRESHOLD:
        raise ContractLoadError(parsed, total, _CONTRACT_PARSE_THRESHOLD)

    if errors:
        logger.info(
            "Contract load summary: %d/%d parsed, %d errors",
            parsed,
            total,
            len(errors),
        )

    return contracts


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class SkillCommandDispatcher:
    """Multiplexed command dispatcher for all skill nodes.

    Extracts ``skill_id`` from the inbound topic, looks up the corresponding
    contract, selects the appropriate backend, and dispatches via the shared
    ``handle_skill_requested`` handler.

    After execution, emits a ``ModelSkillCompletionEvent`` to the unified
    completion topic.

    The dispatch engine passes a materialized dict (``ModelMaterializedDispatch``
    schema) with keys ``payload``, ``__bindings``, and ``__debug_trace``. The
    topic is extracted from ``__debug_trace.topic``.
    """

    def __init__(
        self,
        contracts: dict[str, ModelSkillNodeContract],
        claude_code_backend: SubprocessClaudeCodeSessionBackend | None,
        vllm_backend: VllmInferenceBackend | None,
        event_bus: Any | None = None,
    ) -> None:
        self._contracts = contracts
        self._claude_code_backend = claude_code_backend
        self._vllm_backend = vllm_backend
        self._event_bus = event_bus

    async def handle(
        self, envelope: ModelEventEnvelope[object] | dict[str, Any]
    ) -> str | None:
        """Dispatch an inbound skill command envelope.

        The dispatch engine materializes envelopes into dicts before calling
        dispatchers. This method handles both dict (runtime) and
        ``ModelEventEnvelope`` (test) inputs.

        Args:
            envelope: Materialized dispatch dict or event envelope.

        Returns:
            Dispatcher result string or None.
        """
        # Extract topic and payload from materialized dict or envelope
        topic: str | None = None
        payload: Any = None
        correlation_id: uuid.UUID

        if isinstance(envelope, dict):
            # Runtime path: materialized dict from MessageDispatchEngine
            debug_trace = envelope.get("__debug_trace", {})
            topic = debug_trace.get("topic") if isinstance(debug_trace, dict) else None
            payload = envelope.get("payload")
            raw_cid = (
                debug_trace.get("correlation_id")
                if isinstance(debug_trace, dict)
                else None
            )
            if raw_cid is not None:
                try:
                    correlation_id = uuid.UUID(str(raw_cid))
                except ValueError:
                    correlation_id = uuid.uuid4()
            else:
                correlation_id = uuid.uuid4()
        else:
            # Test path: ModelEventEnvelope
            correlation_id = envelope.correlation_id or uuid.uuid4()
            payload = envelope.payload
            # Try metadata.topic (not standard, but check anyway)
            if envelope.metadata is not None and hasattr(envelope.metadata, "topic"):
                topic = getattr(envelope.metadata, "topic", None)

        run_id = uuid.uuid4()
        t0 = time.perf_counter()

        # Extract skill_id from topic: onex.cmd.omniclaude.{skill_id}.v1
        skill_id = self._extract_skill_id(topic)
        if skill_id is None:
            logger.warning(
                "Could not extract skill_id from topic %r (correlation_id=%s)",
                topic,
                correlation_id,
            )
            await self._emit_completion(
                run_id=run_id,
                skill_name="unknown",
                command_topic=topic or "unknown",
                status=SkillResultStatus.FAILED,
                backend_selected="none",
                backend_detail="none",
                duration_ms=int((time.perf_counter() - t0) * 1000),
                error_code="UNKNOWN_SKILL",
                error_message=f"Could not extract skill_id from topic: {topic}",
                correlation_id=correlation_id,
            )
            return None

        # Look up contract
        contract = self._contracts.get(skill_id)
        if contract is None:
            logger.warning(
                "No contract found for skill_id=%r (correlation_id=%s)",
                skill_id,
                correlation_id,
            )
            await self._emit_completion(
                run_id=run_id,
                skill_name=skill_id,
                command_topic=topic or "unknown",
                status=SkillResultStatus.FAILED,
                backend_selected="none",
                backend_detail="none",
                duration_ms=int((time.perf_counter() - t0) * 1000),
                error_code="UNKNOWN_SKILL",
                error_message=f"No contract registered for skill_id={skill_id}",
                correlation_id=correlation_id,
            )
            return None

        # Select backend
        backend_type = contract.execution.backend
        backend_detail: str

        if backend_type == "claude_code":
            if self._claude_code_backend is None:
                await self._emit_completion(
                    run_id=run_id,
                    skill_name=skill_id,
                    command_topic=topic or "unknown",
                    status=SkillResultStatus.FAILED,
                    backend_selected="claude_code",
                    backend_detail="unavailable",
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                    error_code="BACKEND_UNAVAILABLE",
                    error_message="SubprocessClaudeCodeSessionBackend is not available",
                    correlation_id=correlation_id,
                )
                return None
            backend_detail = "claude_subprocess"

            async def task_dispatcher(prompt: str) -> str:
                from omniclaude.nodes.node_claude_code_session_effect.models import (
                    ClaudeCodeSessionOperation,
                    ModelClaudeCodeSessionRequest,
                )

                assert self._claude_code_backend is not None
                cc_request = ModelClaudeCodeSessionRequest(
                    operation=ClaudeCodeSessionOperation.SESSION_QUERY,
                    skill_name=skill_id,
                    prompt=prompt,
                    correlation_id=correlation_id,
                )
                result = await self._claude_code_backend.session_query(cc_request)
                return result.output or ""

        elif backend_type == "local_llm":
            if self._vllm_backend is None:
                await self._emit_completion(
                    run_id=run_id,
                    skill_name=skill_id,
                    command_topic=topic or "unknown",
                    status=SkillResultStatus.FAILED,
                    backend_selected="local_llm",
                    backend_detail="unavailable",
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                    error_code="BACKEND_UNAVAILABLE",
                    error_message="VllmInferenceBackend is not available",
                    correlation_id=correlation_id,
                )
                return None

            model_purpose = contract.execution.model_purpose or "CODE_ANALYSIS"
            backend_detail = f"vllm:{model_purpose}"

            async def task_dispatcher(prompt: str) -> str:
                from omniclaude.nodes.node_local_llm_inference_effect.models import (
                    ModelLocalLlmInferenceRequest,
                )

                assert self._vllm_backend is not None
                llm_request = ModelLocalLlmInferenceRequest(
                    skill_name=skill_id,
                    prompt=prompt,
                    model_purpose=model_purpose,
                    correlation_id=correlation_id,
                )
                result = await self._vllm_backend.infer(llm_request)
                return result.output or ""

        # Build skill request from envelope payload
        skill_request = self._build_skill_request(
            skill_id=skill_id,
            payload=payload,
            correlation_id=correlation_id,
        )

        # Dispatch via shared handler
        result = await handle_skill_requested(
            skill_request,
            task_dispatcher=task_dispatcher,
        )

        # Emit completion event
        await self._emit_completion(
            run_id=run_id,
            skill_name=skill_id,
            command_topic=topic or "unknown",
            status=result.status,
            backend_selected=backend_type,
            backend_detail=backend_detail,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            error_code=None
            if result.status == SkillResultStatus.SUCCESS
            else "DISPATCH_ERROR",
            error_message=result.error,
            correlation_id=correlation_id,
        )

        return f"dispatched:{skill_id}:{result.status.value}"

    @staticmethod
    def _extract_skill_id(topic: str | None) -> str | None:
        """Extract skill_id from topic pattern ``onex.cmd.omniclaude.{skill_id}.v1``.

        Args:
            topic: Kafka topic string.

        Returns:
            The skill_id segment, or None if the topic doesn't match.
        """
        if topic is None:
            return None
        parts = topic.split(".")
        # Expected: ["onex", "cmd", "omniclaude", "{skill_id}", "v1"]
        if (
            len(parts) == 5
            and parts[0] == "onex"
            and parts[1] == "cmd"
            and parts[2] == "omniclaude"
            and parts[4] == "v1"
        ):
            return parts[3]
        return None

    @staticmethod
    def _build_skill_request(
        skill_id: str,
        payload: Any,
        correlation_id: uuid.UUID,
    ) -> ModelSkillRequest:
        """Build a ``ModelSkillRequest`` from the envelope payload.

        Extracts ``skill_path`` and ``args`` from the payload if they
        are present, otherwise uses sensible defaults.

        Args:
            skill_id: The extracted skill identifier.
            payload: The envelope payload (dict or other).
            correlation_id: Correlation ID for tracing.

        Returns:
            A fully populated ``ModelSkillRequest``.
        """
        # Default skill_path from convention
        default_path = f"plugins/onex/skills/{skill_id}/SKILL.md"

        if isinstance(payload, dict):
            skill_path = payload.get("skill_path", default_path)
            args = payload.get("args", {})
            if not isinstance(args, dict):
                args = {}
        else:
            skill_path = default_path
            args = {}

        return ModelSkillRequest(
            skill_name=skill_id,
            skill_path=str(skill_path),
            args={str(k): str(v) for k, v in args.items()},
            correlation_id=correlation_id,
        )

    async def _emit_completion(
        self,
        *,
        run_id: uuid.UUID,
        skill_name: str,
        command_topic: str,
        status: SkillResultStatus,
        backend_selected: str,
        backend_detail: str,
        duration_ms: int,
        error_code: str | None,
        error_message: str | None,
        correlation_id: uuid.UUID,
    ) -> None:
        """Emit a ``ModelSkillCompletionEvent`` to the unified completion topic.

        Best-effort: logs and swallows any exception.

        Args:
            run_id: Unique run identifier.
            skill_name: Skill identifier.
            command_topic: The inbound command topic.
            status: Execution outcome.
            backend_selected: Backend type (``claude_code`` or ``local_llm``).
            backend_detail: Backend implementation detail.
            duration_ms: Wall-clock time in milliseconds.
            error_code: Machine-readable error code (None on success).
            error_message: Human-readable error detail (None on success).
            correlation_id: Correlation ID for tracing.
        """
        try:
            # Truncate error_message to 1000 chars as per model constraint
            bounded_error = error_message[:1000] if error_message else None

            event = ModelSkillCompletionEvent(
                event_id=uuid.uuid4(),
                run_id=run_id,
                skill_name=skill_name or "unknown",
                command_topic=command_topic or "unknown",
                status=status,
                backend_selected=backend_selected or "none",
                backend_detail=backend_detail or "none",
                duration_ms=duration_ms,
                error_code=error_code,
                error_message=bounded_error,
                correlation_id=correlation_id,
            )
            if self._event_bus is not None and hasattr(self._event_bus, "publish"):
                await self._event_bus.publish(
                    _COMPLETION_TOPIC,
                    event.model_dump(mode="json"),
                )
            else:
                logger.debug(
                    "Completion event (no event bus): skill=%s status=%s",
                    skill_name,
                    status.value,
                )
        except Exception:
            logger.exception("Failed to emit completion event for skill %r", skill_name)


# ---------------------------------------------------------------------------
# Route builder (also used by tests)
# ---------------------------------------------------------------------------


def _build_skill_route() -> ModelDispatchRoute:
    """Build the ``ModelDispatchRoute`` for skill command routing.

    Returns:
        A ``ModelDispatchRoute`` matching ``onex.cmd.omniclaude.*.v1`` topics.
    """
    return ModelDispatchRoute(
        route_id=_ROUTE_ID,
        topic_pattern=_TOPIC_PATTERN,  # arch-topic-naming: ignore
        message_category=EnumMessageCategory.COMMAND,
        message_type=None,  # match all message types on matched topics
        handler_id=_DISPATCHER_ID,
        description="Routes skill command events to the multiplexed SkillCommandDispatcher",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def wire_skill_dispatchers(
    container: Any,
    dispatch_engine: MessageDispatchEngine,
    correlation_id: uuid.UUID | None = None,
    *,
    claude_code_backend: SubprocessClaudeCodeSessionBackend | None = None,
    vllm_backend: VllmInferenceBackend | None = None,
    contracts_root: Path | None = None,
    event_bus: Any | None = None,
) -> WiringSummary:
    """Wire the skill command dispatcher onto the dispatch engine.

    Loads all skill node contracts, builds a ``SkillCommandDispatcher``, and
    registers it + a single route on the ``MessageDispatchEngine``.

    Args:
        container: ONEX container (used for service resolution if backends are
            not explicitly provided).
        dispatch_engine: The engine to register the dispatcher and route on.
        correlation_id: Correlation ID for tracing.
        claude_code_backend: Optional pre-resolved claude_code backend.
        vllm_backend: Optional pre-resolved vllm backend.
        contracts_root: Override for the contracts root directory.
        event_bus: Optional event bus for emitting completion events.

    Returns:
        A ``WiringSummary`` dict with registered dispatchers, routes, and counts.

    Raises:
        ContractLoadError: If fewer than 80% of contracts parse successfully.
    """
    cid = correlation_id or uuid.uuid4()

    # Resolve contracts root
    root: Path | None = contracts_root
    if root is None:
        env_root = os.getenv("OMNICLAUDE_CONTRACTS_ROOT")
        if env_root:
            root = Path(env_root)

    if root is None:
        logger.warning(
            "OMNICLAUDE_CONTRACTS_ROOT not set; skill dispatchers not wired "
            "(correlation_id=%s)",
            cid,
        )
        return WiringSummary(
            dispatchers=[],
            routes=[],
            contracts_loaded=0,
            contracts_total=0,
            backends={},
        )

    # Load contracts
    contracts = load_skill_contracts(root)

    logger.info(
        "Loaded %d skill contracts (correlation_id=%s)",
        len(contracts),
        cid,
    )

    # Resolve backends from container if not explicitly provided
    resolved_cc = claude_code_backend
    resolved_vllm = vllm_backend

    if resolved_cc is None:
        try:
            # Try to get from container's service registry
            if (
                hasattr(container, "service_registry")
                and container.service_registry is not None
            ):
                from omniclaude.nodes.node_claude_code_session_effect.backends.backend_subprocess import (
                    SubprocessClaudeCodeSessionBackend as _CCBackend,
                )

                svc = container.service_registry.get(_CCBackend)
                if isinstance(svc, _CCBackend):
                    resolved_cc = svc
        except Exception:
            logger.debug(
                "Could not resolve SubprocessClaudeCodeSessionBackend from container"
            )

    if resolved_vllm is None:
        try:
            if (
                hasattr(container, "service_registry")
                and container.service_registry is not None
            ):
                from omniclaude.nodes.node_local_llm_inference_effect.backends.backend_vllm import (
                    VllmInferenceBackend as _VllmBackend,
                )

                svc = container.service_registry.get(_VllmBackend)
                if isinstance(svc, _VllmBackend):
                    resolved_vllm = svc
        except Exception:
            logger.debug("Could not resolve VllmInferenceBackend from container")

    # Resolve event bus from container if not provided
    resolved_event_bus = event_bus
    if resolved_event_bus is None and hasattr(container, "event_bus"):
        resolved_event_bus = container.event_bus

    # Build dispatcher
    dispatcher = SkillCommandDispatcher(
        contracts=contracts,
        claude_code_backend=resolved_cc,
        vllm_backend=resolved_vllm,
        event_bus=resolved_event_bus,
    )

    # Register dispatcher with the engine
    dispatch_engine.register_dispatcher(
        _DISPATCHER_ID,
        dispatcher.handle,
        category=EnumMessageCategory.COMMAND,
        message_types=None,  # matches all types
    )

    # Register route
    route = _build_skill_route()
    dispatch_engine.register_route(route)

    backends_available: dict[str, str] = {}
    if resolved_cc is not None:
        backends_available["claude_code"] = "SubprocessClaudeCodeSessionBackend"
    if resolved_vllm is not None:
        backends_available["local_llm"] = "VllmInferenceBackend"

    logger.info(
        "Skill dispatcher wired: %d contracts, route=%s, backends=%s "
        "(correlation_id=%s)",
        len(contracts),
        _ROUTE_ID,
        list(backends_available.keys()),
        cid,
    )

    return WiringSummary(
        dispatchers=[_DISPATCHER_ID],
        routes=[_ROUTE_ID],
        contracts_loaded=len(contracts),
        contracts_total=len(list(root.glob("node_skill_*/contract.yaml"))),
        backends=backends_available,
    )
