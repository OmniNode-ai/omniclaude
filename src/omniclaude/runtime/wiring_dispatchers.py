# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
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
from typing import TYPE_CHECKING, Any, TypedDict  # any-ok: external API boundary

import yaml
from omnibase_core.enums import EnumMessageCategory
from omnibase_core.models.dispatch.model_dispatch_route import ModelDispatchRoute

from omniclaude.hooks.topics import TopicBase
from omniclaude.shared.handler_skill_requested import handle_skill_requested
from omniclaude.shared.models.model_skill_completion_event import (
    EnumUsageSource,
    ModelCallRecord,
    ModelCostProvenance,
    ModelSkillCompletionEvent,
)
from omniclaude.shared.models.model_skill_node_contract import (
    ModelSkillNodeContract,
)
from omniclaude.shared.models.model_skill_request import ModelSkillRequest
from omniclaude.shared.models.model_skill_result import SkillResultStatus
from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

if TYPE_CHECKING:
    from omnibase_core.models.events.model_event_envelope import ModelEventEnvelope
    from omnibase_infra.runtime import MessageDispatchEngine

    from omniclaude.nodes.node_claude_code_session_effect.backends.backend_subprocess import (
        SubprocessClaudeCodeSessionBackend,
    )
    from omniclaude.nodes.node_local_llm_inference_effect.backends.backend_vllm import (
        VllmInferenceBackend,
    )

__all__ = [
    "ContractLoadError",
    "wire_quirk_finding_subscription",
    "wire_skill_dispatchers",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOPIC_PATTERN = "onex.cmd.omniclaude.*.v1"  # arch-topic-naming: ignore  # noqa: arch-topic-naming  # onex-topic-allow: pending contract auto-wiring
_DISPATCHER_ID = "dispatcher.skill.command"
_ROUTE_ID = "skill-command-router"
_COMPLETION_TOPIC = TopicBase.SKILL_COMPLETED
_DISPATCH_WORKER_SKILL_ID = "dispatch-worker"
_ESTIMATED_COST_PER_1K_TOKENS_USD = 0.0001

_CONTRACT_PARSE_THRESHOLD = 0.80

# ---------------------------------------------------------------------------
# Quirk finding subscription constants (OMN-2908)
# ---------------------------------------------------------------------------

_QUIRK_FINDING_TOPIC = TopicBase.QUIRK_FINDING_PRODUCED
_QUIRK_FINDING_DISPATCHER_ID = "dispatcher.quirk.finding"
_QUIRK_FINDING_ROUTE_ID = "quirk-finding-router"


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


def _canonical_skill_id(skill_id: str) -> str:
    """Normalize topic skill IDs to the contract-key convention."""

    return skill_id.replace("_", "-")


def load_skill_contracts(
    contracts_root: Path,
) -> tuple[dict[str, ModelSkillNodeContract], int]:
    """Load and parse all skill node contract.yaml files.

    Scans ``contracts_root`` for directories matching ``node_skill_*`` and
    parses each ``contract.yaml`` into a ``ModelSkillNodeContract``.

    Args:
        contracts_root: Root directory containing node directories.

    Returns:
        Tuple of (mapping of skill_id to parsed contract, total files found).

    Raises:
        ContractLoadError: If parse rate falls below 80%.
    """
    contract_files = sorted(contracts_root.glob("node_skill_*/contract.yaml"))
    total = len(contract_files)
    if total == 0:
        logger.warning("No skill node contracts found in %s", contracts_root)
        return {}, 0

    contracts: dict[str, ModelSkillNodeContract] = {}
    errors: list[str] = []
    parsed_contracts = 0

    for path in contract_files:
        try:
            with path.open() as fh:
                raw = yaml.safe_load(fh)
            if not isinstance(raw, dict):
                errors.append(f"{path}: not a dict")
                continue
            contract = ModelSkillNodeContract.model_validate(raw)
            parsed_contracts += 1
            skill_id = _extract_skill_id_from_name(contract.name)
            contracts[skill_id] = contract
            subscribe_topic = (
                contract.event_bus.get("subscribe", {}).get("topic")
                if isinstance(contract.event_bus.get("subscribe"), dict)
                else None
            )
            if isinstance(subscribe_topic, str):
                topic_skill_id = SkillCommandDispatcher._extract_skill_id(
                    subscribe_topic
                )
                if topic_skill_id:
                    contracts[_canonical_skill_id(topic_skill_id)] = contract
        except Exception as exc:  # noqa: BLE001 — boundary: individual contract parse failure
            errors.append(f"{path}: {exc}")
            logger.warning("Failed to parse contract %s: %s", path, exc)

    parsed = parsed_contracts
    if total > 0 and (parsed / total) < _CONTRACT_PARSE_THRESHOLD:
        raise ContractLoadError(parsed, total, _CONTRACT_PARSE_THRESHOLD)

    if errors:
        logger.info(
            "Contract load summary: %d/%d parsed, %d errors",
            parsed,
            total,
            len(errors),
        )

    return contracts, total


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
        event_bus: Any  # ONEX_EXCLUDE: any_type - external/untyped API boundary
        | None = None,  # ONEX_EXCLUDE: any_type - external/untyped API boundary
    ) -> None:
        self._contracts = contracts
        self._claude_code_backend = claude_code_backend
        self._vllm_backend = vllm_backend
        self._event_bus = event_bus

    async def handle(
        self,
        envelope: ModelEventEnvelope[object]
        | dict[str, Any],  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary
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
        payload: Any = (  # ONEX_EXCLUDE: any_type - external/untyped API boundary
            None  # ONEX_EXCLUDE: any_type - external/untyped API boundary
        )
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
        raw_skill_id = self._extract_skill_id(topic)
        skill_id = _canonical_skill_id(raw_skill_id) if raw_skill_id else None
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

        backend_result: Any = None  # ONEX_EXCLUDE: any_type - backend boundary
        backend_prompt: str | None = None

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

                # Narrowing: parent scope returns None when backend is None
                cc_backend = self._claude_code_backend
                if (
                    cc_backend is None
                ):  # pragma: no cover — unreachable after parent guard
                    raise RuntimeError(
                        "claude_code backend disappeared after null check"
                    )
                cc_request = ModelClaudeCodeSessionRequest(
                    operation=ClaudeCodeSessionOperation.SESSION_QUERY,
                    skill_name=skill_id,
                    prompt=prompt,
                    correlation_id=correlation_id,
                )
                nonlocal backend_prompt, backend_result
                backend_prompt = prompt
                result = await cc_backend.session_query(cc_request)
                backend_result = result
                return _skill_result_output(result)

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

                # Narrowing: parent scope returns None when backend is None
                vllm_backend = self._vllm_backend
                if (
                    vllm_backend is None
                ):  # pragma: no cover — unreachable after parent guard
                    raise RuntimeError("vllm backend disappeared after null check")
                llm_request = ModelLocalLlmInferenceRequest(
                    skill_name=skill_id,
                    prompt=prompt,
                    model_purpose=model_purpose,
                    correlation_id=correlation_id,
                )
                nonlocal backend_prompt, backend_result
                backend_prompt = prompt
                result = await vllm_backend.infer(llm_request)
                backend_result = result
                return _skill_result_output(result)

        else:
            # Unknown backend type — emit failure and return rather than
            # using potentially uninitialized backend_detail / task_dispatcher.
            await self._emit_completion(  # type: ignore[unreachable]  # Why: defensive else branch for unknown backend
                run_id=run_id,
                skill_name=skill_id,
                command_topic=topic or "unknown",
                status=SkillResultStatus.FAILED,
                backend_selected=backend_type,
                backend_detail="unsupported",
                duration_ms=int((time.perf_counter() - t0) * 1000),
                error_code="BACKEND_UNSUPPORTED",
                error_message=f"Unknown backend type: {backend_type!r}",
                correlation_id=correlation_id,
            )
            return None

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
            event_emitter=emit_event,
        )

        # Emit completion event
        await self._emit_completion(
            contract=contract,
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
            error_message=result.extra.get("error") if result.extra else None,
            correlation_id=correlation_id,
            source_payload=payload,
            backend_prompt=backend_prompt,
            backend_result=backend_result,
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
        payload: Any,  # ONEX_EXCLUDE: any_type - external/untyped API boundary
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
        # Default skill_path from convention.
        # Skill directories use underscores (OMN-5200) but Kafka topics use
        # kebab-case, so normalise the skill_id for filesystem lookup.
        skill_dir = skill_id.replace("-", "_")
        default_path = f"plugins/onex/skills/{skill_dir}/SKILL.md"

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
        contract: ModelSkillNodeContract | None = None,
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
        source_payload: Any = None,  # ONEX_EXCLUDE: any_type - envelope boundary
        backend_prompt: str | None = None,
        backend_result: Any = None,  # ONEX_EXCLUDE: any_type - backend boundary
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
            dispatch_metadata = _extract_dispatch_metadata(
                source_payload=source_payload,
                run_id=run_id,
                correlation_id=correlation_id,
            )
            model_calls = _extract_model_calls(
                backend_selected=backend_selected,
                backend_detail=backend_detail,
                backend_prompt=backend_prompt,
                backend_result=backend_result,
                duration_ms=duration_ms,
            )
            token_cost = sum(  # noqa: secrets
                call.input_tokens + call.output_tokens for call in model_calls
            )
            dollars_cost = sum(call.cost_dollars for call in model_calls)
            cost_provenance = ModelCostProvenance.rollup(model_calls)

            event = ModelSkillCompletionEvent(
                event_id=uuid.uuid4(),
                run_id=run_id,
                skill_name=skill_name or "unknown",
                command_topic=command_topic or "unknown",
                status=status,
                backend_selected=backend_selected or "none",
                backend_detail=backend_detail or "none",
                duration_ms=duration_ms,
                task_id=dispatch_metadata["task_id"],
                dispatch_id=dispatch_metadata["dispatch_id"],
                ticket_id=dispatch_metadata["ticket_id"],
                artifact_path=dispatch_metadata["artifact_path"],
                model_calls=model_calls,
                token_cost=token_cost,
                dollars_cost=dollars_cost,
                cost_provenance=cost_provenance,
                error_code=error_code,
                error_message=bounded_error,
                correlation_id=correlation_id,
            )
            if self._event_bus is not None and hasattr(self._event_bus, "publish"):
                await self._event_bus.publish(
                    _COMPLETION_TOPIC,
                    event.model_dump(mode="json"),
                )
                contract_topic = _completion_topic_for_contract(
                    contract=contract,
                    status=status,
                )
                if (
                    skill_name == _DISPATCH_WORKER_SKILL_ID
                    and contract_topic
                    and contract_topic != _COMPLETION_TOPIC
                ):
                    await self._event_bus.publish(
                        contract_topic,
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


def _skill_result_output(
    result: object | None,
) -> str:
    """Extract output text from either legacy or core ModelSkillResult shapes."""

    output = getattr(result, "output", None)
    if output is None:
        extra = getattr(result, "extra", None)
        if isinstance(extra, dict):
            output = extra.get("output")
    return str(output) if output is not None else ""


def _extract_dispatch_metadata(
    *,
    source_payload: Any,  # ONEX_EXCLUDE: any_type - envelope boundary
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> dict[str, str | None]:
    """Extract dispatch worker identifiers and artifact path from command payload."""

    payload: dict[str, object] = (
        {str(k): v for k, v in source_payload.items()}
        if isinstance(source_payload, dict)
        else {}
    )
    raw_args = payload.get("args")
    args: dict[str, object] = (
        {str(k): v for k, v in raw_args.items()} if isinstance(raw_args, dict) else {}
    )

    def first_str(*keys: str) -> str | None:
        for container in (payload, args):
            for key in keys:
                value = container.get(key)
                if value is not None and str(value):
                    return str(value)
        return None

    return {
        "task_id": first_str("task_id", "ticket_id") or str(correlation_id),
        "dispatch_id": first_str("dispatch_id", "worker_id") or str(run_id),
        "ticket_id": first_str("ticket_id"),
        "artifact_path": first_str("artifact_path", "artifact"),
    }


def _extract_model_calls(
    *,
    backend_selected: str,
    backend_detail: str,
    backend_prompt: str | None,
    backend_result: object | None,
    duration_ms: int,
) -> list[ModelCallRecord]:
    """Build model-call records from backend instrumentation or estimates."""

    if backend_result is None and backend_prompt is None:
        return []

    extra = getattr(backend_result, "extra", None)
    extra_dict = extra if isinstance(extra, dict) else {}
    output = _skill_result_output(backend_result)
    input_tokens = _int_from_extra(extra_dict, "input_tokens", "prompt_tokens")  # noqa: secrets
    output_tokens = _int_from_extra(  # noqa: secrets
        extra_dict,
        "output_tokens",
        "completion_tokens",
    )
    cost_dollars = _float_from_extra(extra_dict, "cost_dollars", "dollars_cost")
    source_payload_hash = extra_dict.get("source_payload_hash")

    if (
        input_tokens is not None
        and output_tokens is not None
        and cost_dollars is not None
    ):
        provenance = ModelCostProvenance(
            usage_source=EnumUsageSource.MEASURED,
            source_payload_hash=str(source_payload_hash)
            if source_payload_hash is not None
            else _hash_model_call_payload(extra_dict),
        )
        return [
            ModelCallRecord(
                provider=backend_selected,
                model=backend_detail,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=duration_ms,
                cost_dollars=cost_dollars,
                cost_provenance=provenance,
            )
        ]

    estimated_prompt_count = input_tokens
    if estimated_prompt_count is None:
        estimated_prompt_count = _estimate_tokens(backend_prompt or "")
    estimated_completion_count = output_tokens
    if estimated_completion_count is None:
        estimated_completion_count = _estimate_tokens(output)
    estimated_total_tokens = estimated_prompt_count + estimated_completion_count
    estimated_cost = cost_dollars
    if estimated_cost is None:
        estimated_cost = (
            estimated_total_tokens / 1000
        ) * _ESTIMATED_COST_PER_1K_TOKENS_USD

    return [
        ModelCallRecord(
            provider=backend_selected or "unknown",
            model=backend_detail or "unknown",
            input_tokens=estimated_prompt_count,
            output_tokens=estimated_completion_count,
            latency_ms=duration_ms,
            cost_dollars=estimated_cost,
            cost_provenance=ModelCostProvenance(
                usage_source=EnumUsageSource.ESTIMATED,
                estimation_method="omniclaude_dispatch_worker_token_estimate_v1",
            ),
        )
    ]


def _estimate_tokens(text: str) -> int:
    """Deterministic local token estimate used when backend usage is absent."""

    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _int_from_extra(extra: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        value = extra.get(key)
        if value is not None:
            if isinstance(value, int | float | str):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
            return None
    return None


def _float_from_extra(extra: dict[str, object], *keys: str) -> float | None:
    for key in keys:
        value = extra.get(key)
        if value is not None:
            if isinstance(value, int | float | str):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
            return None
    return None


def _hash_model_call_payload(payload: dict[str, object]) -> str:
    serialized = yaml.safe_dump(payload, sort_keys=True)
    import hashlib

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _completion_topic_for_contract(
    *,
    contract: ModelSkillNodeContract | None,
    status: SkillResultStatus,
) -> str | None:
    if contract is None:
        return None
    publish = contract.event_bus.get("publish")
    if not isinstance(publish, dict):
        return None
    key = "success_topic" if status == SkillResultStatus.SUCCESS else "failure_topic"
    topic = publish.get(key)
    return str(topic) if topic else None


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
    container: Any,  # ONEX_EXCLUDE: any_type - external/untyped API boundary
    dispatch_engine: MessageDispatchEngine,
    correlation_id: uuid.UUID | None = None,
    *,
    claude_code_backend: SubprocessClaudeCodeSessionBackend | None = None,
    vllm_backend: VllmInferenceBackend | None = None,
    contracts_root: Path | None = None,
    event_bus: Any  # ONEX_EXCLUDE: any_type - external/untyped API boundary
    | None = None,  # ONEX_EXCLUDE: any_type - external/untyped API boundary
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
    contracts, contracts_total = load_skill_contracts(root)

    logger.info(
        "Loaded %d/%d skill contracts (correlation_id=%s)",
        len(contracts),
        contracts_total,
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
        except Exception:  # noqa: BLE001 — boundary: optional backend resolution
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
        except Exception:  # noqa: BLE001 — boundary: optional backend resolution
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
        contracts_total=contracts_total,
        backends=backends_available,
    )


# ---------------------------------------------------------------------------
# Quirk finding dispatcher (OMN-2908)
# ---------------------------------------------------------------------------


class QuirkFindingDispatcher:
    """Dispatcher for ``onex.evt.omniclaude.quirk-finding-produced.v1`` events.

    On each inbound message, resolves ``NodeQuirkMemoryBridgeEffect`` from the
    container and calls ``process_payload(payload)`` to promote the finding into
    OmniMemory.  Cross-process quirk findings are promoted this way; in-process
    findings already call ``promote_finding`` directly.

    Fail-open: any exception during promotion is logged and swallowed so that a
    malformed finding does not break the dispatch loop.

    Ticket: OMN-2908
    """

    def __init__(
        self,
        container: Any,  # ONEX_EXCLUDE: any_type - external/untyped API boundary
    ) -> None:  # ONEX_EXCLUDE: any_type - external/untyped API boundary
        self._container = container

    async def handle(
        self,
        envelope: ModelEventEnvelope[object]
        | dict[str, Any],  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary
    ) -> str | None:
        """Handle one quirk-finding-produced event.

        Extracts the raw payload dict and forwards it to
        ``NodeQuirkMemoryBridgeEffect.process_payload()``.

        Args:
            envelope: Materialized dispatch dict or event envelope.

        Returns:
            ``"promoted"`` on success, ``None`` if the finding was skipped or
            an error occurred.
        """
        try:
            payload: dict[  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary
                str, Any
            ]  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary
            if isinstance(envelope, dict):
                raw = envelope.get("payload")
                payload = raw if isinstance(raw, dict) else {}
            else:
                raw_payload = envelope.payload
                payload = raw_payload if isinstance(raw_payload, dict) else {}

            bridge = self._resolve_bridge()
            if bridge is None:
                logger.warning(
                    "QuirkFindingDispatcher: NodeQuirkMemoryBridgeEffect not available; "
                    "skipping quirk finding payload"
                )
                return None

            result = bridge.process_payload(payload)
            if result is None:
                return None
            return "promoted"
        except Exception:
            logger.exception(
                "QuirkFindingDispatcher: unhandled error promoting quirk finding"
            )
            return None

    def _resolve_bridge(
        self,
    ) -> Any | None:  # ONEX_EXCLUDE: any_type - external/untyped API boundary
        """Resolve ``NodeQuirkMemoryBridgeEffect`` from the container.

        Returns ``None`` if the bridge is not registered or resolution fails.
        """
        try:
            from omniclaude.quirks.memory_bridge import (  # noqa: PLC0415
                NodeQuirkMemoryBridgeEffect,
            )

            if (
                hasattr(self._container, "service_registry")
                and self._container.service_registry is not None
            ):
                svc = self._container.service_registry.get(NodeQuirkMemoryBridgeEffect)
                if isinstance(svc, NodeQuirkMemoryBridgeEffect):
                    return svc

            # Fall back to direct attribute access (test containers and dev setups)
            if hasattr(self._container, "quirk_memory_bridge"):
                bridge = self._container.quirk_memory_bridge
                if bridge is not None:
                    return bridge
        except Exception:  # noqa: BLE001 — boundary: optional service resolution
            logger.debug(
                "QuirkFindingDispatcher: could not resolve NodeQuirkMemoryBridgeEffect "
                "from container",
                exc_info=True,
            )
        return None


def _build_quirk_finding_route() -> ModelDispatchRoute:
    """Build the ``ModelDispatchRoute`` for quirk-finding-produced events.

    Returns:
        A ``ModelDispatchRoute`` matching the quirk-finding-produced topic.
    """
    return ModelDispatchRoute(
        route_id=_QUIRK_FINDING_ROUTE_ID,
        topic_pattern=_QUIRK_FINDING_TOPIC,  # arch-topic-naming: ignore
        message_category=EnumMessageCategory.EVENT,
        message_type=None,  # match all message types on this topic
        handler_id=_QUIRK_FINDING_DISPATCHER_ID,
        description="Routes quirk-finding-produced events to NodeQuirkMemoryBridgeEffect",
    )


class QuirkFindingWiringSummary(TypedDict):
    """Summary dict returned by ``wire_quirk_finding_subscription``."""

    dispatchers: list[str]
    routes: list[str]


def wire_quirk_finding_subscription(
    container: Any,  # ONEX_EXCLUDE: any_type - external/untyped API boundary
    dispatch_engine: MessageDispatchEngine,
) -> QuirkFindingWiringSummary:
    """Wire the quirk-finding-produced subscription onto the dispatch engine.

    Registers a ``QuirkFindingDispatcher`` and a single route on the
    ``MessageDispatchEngine`` so that ``onex.evt.omniclaude.quirk-finding-produced.v1``
    events are forwarded to ``NodeQuirkMemoryBridgeEffect.process_payload()``.

    This ensures cross-process quirk findings are promoted to OmniMemory — findings
    produced by other process instances reach the bridge even when the in-process
    call path is not available.

    Args:
        container: ONEX container used to resolve ``NodeQuirkMemoryBridgeEffect``.
        dispatch_engine: The engine to register the dispatcher and route on.

    Returns:
        A ``QuirkFindingWiringSummary`` dict with registered dispatchers and routes.

    Ticket: OMN-2908
    """
    dispatcher = QuirkFindingDispatcher(container=container)

    dispatch_engine.register_dispatcher(
        _QUIRK_FINDING_DISPATCHER_ID,
        dispatcher.handle,
        category=EnumMessageCategory.EVENT,
        message_types=None,
    )

    route = _build_quirk_finding_route()
    dispatch_engine.register_route(route)

    logger.info(
        "Quirk-finding subscription wired: topic=%s, route=%s",
        _QUIRK_FINDING_TOPIC,
        _QUIRK_FINDING_ROUTE_ID,
    )

    return QuirkFindingWiringSummary(
        dispatchers=[_QUIRK_FINDING_DISPATCHER_ID],
        routes=[_QUIRK_FINDING_ROUTE_ID],
    )
