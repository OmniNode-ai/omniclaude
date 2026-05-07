# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""DelegationRunner — routes delegation calls through the Bifrost gateway.

In-process adapter bridging the delegation pipeline's request/response
contract to the production Bifrost gateway (``HandlerBifrostGateway`` from
``omnibase_infra``).

Bifrost provides:
- Declarative routing rules (per config, not per code)
- Failover and exponential backoff across configured backends
- Per-backend circuit breaking
- HMAC-SHA256 outbound authentication
- Auditable routing metadata (rule_id, config_version, backend_selected)

Fallback behaviour:
    If Bifrost is unavailable (config missing, all backends unreachable, or
    any unexpected exception), ``DelegationRunner.run()`` returns ``None``
    so the caller may fall back to the legacy direct-HTTP path without
    blocking the originating Claude Code tool call.

Audit events:
    Every delegation call emits a ``ModelDelegationAuditEvent`` via the
    optional ``on_audit_event`` callback, regardless of success or failure.
    Callers wire this to their Kafka publisher to satisfy the observability
    requirement in OMN-10636.

For the in-process pipeline runner (used when the runtime socket / Kafka path
is unavailable), see :mod:`omniclaude.delegation.inprocess_runner`.

Related:
    - OMN-10636: Wire DelegationRunner → Bifrost gateway
    - OMN-2736: Adopt bifrost as LLM gateway handler
    - OMN-2248: Delegated Task Execution via Local Models (epic)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Audit event model
# ---------------------------------------------------------------------------


class ModelDelegationAuditEvent(BaseModel):
    """Audit record emitted on every Bifrost delegation call.

    Callers persist this via their Kafka publisher to satisfy the
    observability requirements of OMN-10636 (routing metadata must
    be queryable per tenant_id and operation_type).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str = Field(
        ..., description="Correlation ID for distributed tracing"
    )
    session_id: str = Field(
        default="", description="Originating Claude Code session ID"
    )
    backend_selected: str = Field(
        default="", description="Bifrost-selected backend slug"
    )
    rule_id: str = Field(
        default="",
        description="UUID of the matching Bifrost routing rule (empty = default fallback used)",
    )
    config_version: str = Field(
        default="",
        description="Opaque version tag of the Bifrost config in use",
    )
    latency_ms: float = Field(
        default=0.0, ge=0.0, description="E2E Bifrost call latency in ms"
    )
    retry_count: int = Field(
        default=0, ge=0, description="Number of backends attempted"
    )
    success: bool = Field(..., description="Whether Bifrost served the request")
    error_message: str = Field(
        default="", description="Structured error on failure; empty on success"
    )


# ---------------------------------------------------------------------------
# Runner result model
# ---------------------------------------------------------------------------


class ModelBifrostRunnerResult(BaseModel):
    """Result of a single DelegationRunner.run() call.

    Wraps the inference response text alongside the Bifrost routing
    metadata needed by quality-gate and observability consumers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool = Field(..., description="Whether the call was served")
    response_text: str = Field(default="", description="LLM response text on success")
    backend_selected: str = Field(
        default="", description="Backend that served the request"
    )
    rule_id: str = Field(default="", description="Matched Bifrost routing rule UUID")
    config_version: str = Field(default="", description="Bifrost config version tag")
    latency_ms: float = Field(default=0.0, ge=0.0, description="E2E latency in ms")
    retry_count: int = Field(
        default=0, ge=0, description="Backends attempted before success"
    )
    error_message: str = Field(default="", description="Structured error on failure")


# ---------------------------------------------------------------------------
# Minimal HTTP transport for in-process Bifrost use
# ---------------------------------------------------------------------------


def _build_transport_and_handler() -> tuple[object, object]:
    """Instantiate a MixinLlmHttpTransport subclass and HandlerLlmOpenaiCompatible.

    Returns a tuple of (transport_instance, handler_instance) or raises
    ImportError if omnibase_infra is not installed.

    The transport is a minimal concrete subclass of MixinLlmHttpTransport
    that satisfies the mixin's abstract requirements without needing a full
    ModelONEXContainer.
    """
    from omnibase_infra.mixins.mixin_llm_http_transport import MixinLlmHttpTransport
    from omnibase_infra.nodes.node_llm_inference_effect.handlers.handler_llm_openai_compatible import (
        HandlerLlmOpenaiCompatible,
    )

    class _InProcessTransport(MixinLlmHttpTransport):
        """Minimal concrete transport for in-process Bifrost delegation calls."""

        def __init__(self) -> None:
            self._init_llm_http_transport(
                target_name="delegation-bifrost",
                max_timeout_seconds=120.0,
            )

    transport = _InProcessTransport()
    handler = HandlerLlmOpenaiCompatible(transport=transport)
    return transport, handler


# ---------------------------------------------------------------------------
# DelegationRunner
# ---------------------------------------------------------------------------


class DelegationRunner:
    """Routes delegation inference calls through the Bifrost gateway.

    Intended as a drop-in upgrade path for the legacy ``select_backend()``
    direct-HTTP approach in ``handler_delegation_dispatch.py``. On Bifrost
    failure the caller receives ``None`` and may fall back to legacy routing.

    The runner is stateful (it holds the gateway instance and its circuit
    breaker state). One instance should be reused across delegation calls
    within a process lifetime.

    Args:
        config: Bifrost gateway configuration. When None, the runner
            attempts to build a minimal config from env vars
            (``LLM_CODER_FAST_URL`` and friends). If no env vars are
            set, ``run()`` always returns None.
        on_audit_event: Optional synchronous callback invoked with a
            ``ModelDelegationAuditEvent`` after every call. Callers
            wire this to their Kafka publisher.
        config_version: Opaque version tag included in every audit event
            (e.g. a git SHA or semver string identifying the config in use).
    """

    def __init__(
        self,
        config: object | None = None,  # ModelBifrostConfig — lazy import
        on_audit_event: Callable[[ModelDelegationAuditEvent], None] | None = None,
        config_version: str = "",
    ) -> None:
        self._on_audit_event = on_audit_event
        self._config_version = config_version
        self._gateway: object | None = None  # HandlerBifrostGateway — lazy init
        self._transport: object | None = None
        self._config = config
        self._init_error: str = ""

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _ensure_gateway(self) -> bool:
        """Lazily build the Bifrost gateway if not yet initialised.

        Returns True when the gateway is ready, False on any error.
        """
        if self._gateway is not None:
            return True
        if self._init_error:
            return False

        try:
            cfg = self._config or _build_env_config()
            if cfg is None:
                self._init_error = "no_bifrost_config"
                logger.info(
                    "DelegationRunner: no Bifrost config available (no env vars set). "
                    "All delegation calls will return None."
                )
                return False

            transport, handler = _build_transport_and_handler()
            self._transport = transport

            from omnibase_infra.nodes.node_llm_inference_effect.handlers.bifrost.handler_bifrost_gateway import (
                HandlerBifrostGateway,
            )

            self._gateway = HandlerBifrostGateway(
                config=cfg,
                inference_handler=handler,
                on_routing_decision=self._handle_routing_decision,
            )
            logger.info(
                "DelegationRunner: Bifrost gateway initialised. config_version=%s",
                self._config_version,
            )
            return True

        except ImportError as exc:
            self._init_error = f"import_error: {exc}"
            logger.warning("DelegationRunner: omnibase_infra not available: %s", exc)
            return False
        except Exception as exc:  # noqa: BLE001
            self._init_error = f"init_error: {type(exc).__name__}: {exc}"
            logger.warning(
                "DelegationRunner: gateway init failed: %s", self._init_error
            )
            return False

    def _handle_routing_decision(self, response: object) -> None:
        """on_routing_decision callback from HandlerBifrostGateway.

        Receives a ModelBifrostResponse after every routing decision and
        emits an audit event via the caller's on_audit_event callback.
        This callback is stored on self and populated during run(), so
        the correlation_id and session_id are available via closure.
        """
        # Stored per-call context injected in run() before gateway.handle()
        ctx = getattr(self, "_current_call_ctx", {})
        self._emit_audit(
            correlation_id=ctx.get("correlation_id", ""),
            session_id=ctx.get("session_id", ""),
            response=response,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        prompt: str,
        *,
        correlation_id: str = "",
        session_id: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ModelBifrostRunnerResult | None:
        """Route a delegation prompt through Bifrost and return the result.

        This is a synchronous wrapper around the async gateway ``handle()``
        call, suitable for use in the hook runtime's threading context.

        Args:
            prompt: The user prompt to delegate.
            correlation_id: Correlation ID for distributed tracing.
            session_id: Originating Claude Code session ID.
            max_tokens: Optional token limit for the response.
            temperature: Optional sampling temperature.

        Returns:
            ``ModelBifrostRunnerResult`` on success or Bifrost-reported error.
            ``None`` if Bifrost is not configured or experienced an
            unexpected exception — callers should fall back to legacy routing.
        """
        if not self._ensure_gateway():
            return None

        if not prompt:
            return ModelBifrostRunnerResult(
                success=False,
                error_message="empty_prompt",
            )

        corr_id = correlation_id or str(uuid4())

        # Inject per-call context so the routing-decision callback can read it.
        self._current_call_ctx = {"correlation_id": corr_id, "session_id": session_id}

        try:
            result = asyncio.run(
                self._run_async(
                    prompt=prompt,
                    correlation_id=corr_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            )
            return result
        except RuntimeError:
            # asyncio.run() raises RuntimeError when called from within a
            # running event loop (e.g. during tests with pytest-asyncio).
            # Fall back to creating a fresh loop.
            try:
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(
                        self._run_async(
                            prompt=prompt,
                            correlation_id=corr_id,
                            max_tokens=max_tokens,
                            temperature=temperature,
                        )
                    )
                finally:
                    loop.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "DelegationRunner: unexpected error in run(): %s. corr=%s",
                    exc,
                    corr_id,
                )
                return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DelegationRunner: unexpected error in run(): %s. corr=%s",
                exc,
                corr_id,
            )
            return None

    async def run_async(
        self,
        prompt: str,
        *,
        correlation_id: str = "",
        session_id: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ModelBifrostRunnerResult | None:
        """Async variant of ``run()`` for callers already in an event loop.

        Returns the same types as ``run()`` — ``None`` signals Bifrost
        unavailability and the caller should fall back to legacy routing.
        """
        if not self._ensure_gateway():
            return None

        if not prompt:
            return ModelBifrostRunnerResult(success=False, error_message="empty_prompt")

        corr_id = correlation_id or str(uuid4())
        self._current_call_ctx = {"correlation_id": corr_id, "session_id": session_id}

        try:
            return await self._run_async(
                prompt=prompt,
                correlation_id=corr_id,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DelegationRunner: unexpected error in run_async(): %s. corr=%s",
                exc,
                corr_id,
            )
            return None

    # ------------------------------------------------------------------
    # Internal async core
    # ------------------------------------------------------------------

    async def _run_async(
        self,
        prompt: str,
        correlation_id: str,
        max_tokens: int | None,
        temperature: float | None,
    ) -> ModelBifrostRunnerResult:
        """Call Bifrost gateway and return a typed result."""
        from omnibase_infra.enums.enum_cost_tier import EnumCostTier
        from omnibase_infra.enums.enum_llm_operation_type import EnumLlmOperationType
        from omnibase_infra.nodes.node_llm_inference_effect.handlers.bifrost.model_bifrost_request import (
            ModelBifrostRequest,
        )

        try:
            corr_uuid = UUID(correlation_id)
        except (ValueError, AttributeError):
            corr_uuid = uuid4()

        request = ModelBifrostRequest(
            operation_type=EnumLlmOperationType.CHAT_COMPLETION,
            cost_tier=EnumCostTier.LOW,
            tenant_id=_delegation_tenant_id(),
            messages=({"role": "user", "content": prompt},),
            max_tokens=max_tokens,
            temperature=temperature,
            correlation_id=corr_uuid,
        )

        start = time.perf_counter()
        try:
            response = await self._gateway.handle(request)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - start) * 1000
            error_msg = f"bifrost_call_failed: {type(exc).__name__}: {exc}"
            logger.warning(
                "DelegationRunner: Bifrost call failed: %s corr=%s",
                error_msg,
                correlation_id,
            )
            self._emit_audit_direct(
                correlation_id=correlation_id,
                session_id=getattr(self, "_current_call_ctx", {}).get("session_id", ""),
                backend_selected="",
                rule_id="",
                latency_ms=latency_ms,
                retry_count=0,
                success=False,
                error_message=error_msg,
            )
            return ModelBifrostRunnerResult(
                success=False,
                error_message=error_msg,
                latency_ms=latency_ms,
            )

        rule_id = str(response.matched_rule_id) if response.matched_rule_id else ""

        if not response.success or response.inference_response is None:
            return ModelBifrostRunnerResult(
                success=False,
                backend_selected=response.backend_selected,
                rule_id=rule_id,
                config_version=self._config_version,
                latency_ms=response.latency_ms,
                retry_count=response.retry_count,
                error_message=response.error_message or "bifrost_no_response",
            )

        # Extract text from inference response
        response_text = _extract_response_text(response.inference_response)

        return ModelBifrostRunnerResult(
            success=True,
            response_text=response_text,
            backend_selected=response.backend_selected,
            rule_id=rule_id,
            config_version=self._config_version,
            latency_ms=response.latency_ms,
            retry_count=response.retry_count,
        )

    # ------------------------------------------------------------------
    # Audit emission helpers
    # ------------------------------------------------------------------

    def _emit_audit(
        self, correlation_id: str, session_id: str, response: object
    ) -> None:
        """Emit audit event from a ModelBifrostResponse."""
        rule_id = str(response.matched_rule_id) if response.matched_rule_id else ""
        self._emit_audit_direct(
            correlation_id=correlation_id,
            session_id=session_id,
            backend_selected=response.backend_selected,
            rule_id=rule_id,
            latency_ms=response.latency_ms,
            retry_count=response.retry_count,
            success=response.success,
            error_message=response.error_message if not response.success else "",
        )

    def _emit_audit_direct(
        self,
        correlation_id: str,
        session_id: str,
        backend_selected: str,
        rule_id: str,
        latency_ms: float,
        retry_count: int,
        success: bool,
        error_message: str,
    ) -> None:
        """Build and emit a ModelDelegationAuditEvent via the callback."""
        if self._on_audit_event is None:
            return
        event = ModelDelegationAuditEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            backend_selected=backend_selected,
            rule_id=rule_id,
            config_version=self._config_version,
            latency_ms=latency_ms,
            retry_count=retry_count,
            success=success,
            error_message=error_message,
        )
        try:
            self._on_audit_event(event)
        except Exception:  # noqa: BLE001
            logger.warning(
                "DelegationRunner: on_audit_event callback failed", exc_info=True
            )


# ---------------------------------------------------------------------------
# Env-based config builder
# ---------------------------------------------------------------------------

# Fallback tenant UUID used when no per-request tenant is available.
# Stable across process restarts — identifies the delegation subsystem.
_DELEGATION_TENANT_ID = UUID("00000000-cafe-cafe-cafe-000000000001")


def _delegation_tenant_id() -> UUID:
    """Return the stable delegation subsystem tenant UUID."""
    return _DELEGATION_TENANT_ID


def _build_env_config() -> object | None:  # ModelBifrostConfig | None
    """Build a minimal ModelBifrostConfig from environment variables.

    Reads the same env vars as ``select_backend()`` in
    ``handler_delegation_dispatch.py``. Returns None if no endpoints
    are configured.
    """
    try:
        from omnibase_infra.nodes.node_llm_inference_effect.handlers.bifrost.model_bifrost_config import (
            ModelBifrostBackendConfig,
            ModelBifrostConfig,
        )
        from omnibase_infra.nodes.node_llm_inference_effect.handlers.bifrost.model_bifrost_routing_rule import (
            ModelBifrostRoutingRule,
        )
    except (ImportError, SyntaxError):
        # SyntaxError guards against broken/partial omnibase_infra installs
        # (e.g. merge-conflict markers in the canonical clone during development).
        return None

    _ENDPOINT_ENV = [
        (
            "LLM_CODER_FAST_URL",
            "LLM_CODER_FAST_MODEL_NAME",
            "Qwen/Qwen3-14B-AWQ",
            "coder-fast",
        ),
        (
            "LLM_CODER_URL",
            "LLM_CODER_MODEL_NAME",
            "Qwen3-Coder-30B-A3B-Instruct",
            "coder",
        ),
        (
            "LLM_DEEPSEEK_R1_URL",
            "LLM_DEEPSEEK_R1_MODEL_NAME",
            "DeepSeek-R1-Distill",
            "deepseek-r1",
        ),
        ("LLM_GLM_URL", "LLM_GLM_MODEL_NAME", "glm-4.5", "glm"),
    ]

    backends: dict[str, ModelBifrostBackendConfig] = {}
    for url_var, model_var, default_model, backend_id in _ENDPOINT_ENV:
        url = os.environ.get(url_var, "").strip()
        if not url:
            continue
        model_name = os.environ.get(model_var, default_model).strip() or default_model
        backends[backend_id] = ModelBifrostBackendConfig(
            backend_id=backend_id,
            base_url=url,
            model_name=model_name,
        )

    if not backends:
        return None

    priority_order = tuple(backends.keys())
    # Stable rule_id: deterministic UUID based on the sorted backend_id set
    # so that the same env config always produces the same rule_id in audit logs.
    import uuid as _uuid_mod

    rule_id = _uuid_mod.uuid5(
        _uuid_mod.NAMESPACE_OID,
        "delegation-env-rule:" + ",".join(sorted(priority_order)),
    )
    rule = ModelBifrostRoutingRule(
        rule_id=rule_id,
        priority=100,
        backend_ids=priority_order,
    )

    return ModelBifrostConfig(
        backends=backends,
        routing_rules=(rule,),
        default_backends=priority_order,
        failover_attempts=len(backends),
    )


# ---------------------------------------------------------------------------
# Response text extractor
# ---------------------------------------------------------------------------


def _extract_response_text(inference_response: object) -> str:
    """Extract the primary text content from a ModelLlmInferenceResponse."""
    # Try the standard choices path first (OpenAI-compatible response)
    choices = getattr(inference_response, "choices", None)
    if choices:
        first = choices[0] if isinstance(choices, (list, tuple)) else None
        if first is not None:
            message = getattr(first, "message", None)
            if message is not None:
                content = getattr(message, "content", None)
                if content:
                    return str(content)
            # Some response models expose content directly on choice
            content = getattr(first, "content", None)
            if content:
                return str(content)
            # Legacy text field (completion style)
            text = getattr(first, "text", None)
            if text:
                return str(text)

    # Direct content attribute on the response itself
    content = getattr(inference_response, "content", None)
    if content:
        return str(content)

    return ""


__all__: list[str] = [
    "DelegationRunner",
    "ModelBifrostRunnerResult",
    "ModelDelegationAuditEvent",
]
